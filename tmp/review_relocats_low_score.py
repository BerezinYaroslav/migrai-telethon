"""Review recent keyword matches below the scoring threshold in the same chats."""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.types import User

from migrai_telethon.config import Settings
from migrai_telethon.scoring import excerpt, score_text

PATH = Path("var/relocats_recent_20261013.json")
SINCE = datetime(2026, 9, 23, tzinfo=timezone.utc)
KEYWORDS = re.compile(
    r"внж|пмж|виз[ауыое]|переез|переех|релока|эмигр|иммигр|"
    r"легализ|гражданств|nomad|aufenthalt|blue.?card|консул|шенген|"
    r"citizen|residen|\bvisa\b|студенческ|work.permit",
    re.I,
)
SENSITIVE_CONTEXT = re.compile(
    r"\bлгбт\b|сексуальн\w*\s+ориентац|полит\w*\s+убежищ|"
    r"религи\w*|диагноз|заболеван|болезн", re.I
)


def save(snapshot: dict) -> None:
    temporary = PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PATH)


async def main() -> None:
    snapshot = json.loads(await asyncio.to_thread(PATH.read_text, encoding="utf-8"))
    settings = Settings()
    client = TelegramClient(
        str(settings.telegram_session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        receive_updates=False,
        flood_sleep_threshold=0,
        request_retries=1,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Existing session is not authorized")
        for chat in snapshot["chats"]:
            if "low_score_review" in chat:
                continue
            extra = []
            try:
                entity = await client.get_entity(-1000000000000 - chat["telegram_id"])
                cutoff = datetime.fromisoformat(chat["newest_message_date"]) + timedelta(
                    seconds=1
                )
                async for message in client.iter_messages(
                    entity,
                    limit=200,
                    offset_date=cutoff,
                    wait_time=settings.scan_wait_time_seconds,
                ):
                    if message.date and message.date < SINCE:
                        break
                    if (
                        not message.message
                        or not KEYWORDS.search(message.message)
                        or SENSITIVE_CONTEXT.search(message.message)
                    ):
                        continue
                    score = score_text(message.message)
                    if score.score >= settings.signal_score_threshold:
                        continue
                    sender = await message.get_sender()
                    if not isinstance(sender, User) or sender.bot:
                        continue
                    username = getattr(entity, "username", None)
                    link = (
                        f"https://t.me/{username}/{message.id}"
                        if username
                        else f"https://t.me/c/{entity.id}/{message.id}"
                    )
                    extra.append(
                        {
                            "user_id": sender.id,
                            "username": sender.username,
                            "display_name": utils.get_display_name(sender) or str(sender.id),
                            "message_id": message.id,
                            "message_date": message.date.isoformat(),
                            "link": link,
                            "score": score.score,
                            "excerpt": excerpt(message.message, 300),
                        }
                    )
                chat["low_score_review"] = extra
                print(
                    json.dumps(
                        {
                            "row": chat["sheet_row"],
                            "country": chat["country"],
                            "low_score": len(extra),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except FloodWaitError as exc:
                chat["low_score_error"] = f"flood_wait:{exc.seconds}"
                save(snapshot)
                break
            except Exception as exc:
                chat["low_score_error"] = f"{type(exc).__name__}:{exc}"
                print(
                    json.dumps({"row": chat["sheet_row"], "error": chat["low_score_error"]}),
                    flush=True,
                )
            save(snapshot)
            await asyncio.sleep(3)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
