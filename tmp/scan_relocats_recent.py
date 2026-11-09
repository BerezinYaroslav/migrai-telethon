"""Read 200 recent messages from selected, already joined Relocats chats.

Only scored excerpts are saved. Completed chats are skipped on restart.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.types import Channel, User

from migrai_telethon.config import Settings
from migrai_telethon.scoring import excerpt, score_text

COUNTRIES = ("Испания", "США", "Кипр", "Германия", "Великобритания", "Италия")
STATE = Path("var/relocats_join_state.json")
OUTPUT = Path("var/relocats_recent_20261013.json")
SENSITIVE_PERSONAL_CONTEXT = re.compile(r"\bлгбт\b|сексуальн\w*\s+ориентац", re.I)


def save(result: dict) -> None:
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(OUTPUT)


async def main() -> None:
    settings = Settings()
    if not settings.telegram_ready:
        raise RuntimeError("Telegram credentials are missing")

    joined = json.loads(
        await asyncio.to_thread(STATE.read_text, encoding="utf-8")
    )["items"].values()
    targets = sorted(
        (item for item in joined if item.get("country") in COUNTRIES),
        key=lambda item: (COUNTRIES.index(item["country"]), item["sheet_row"]),
    )
    if len(targets) != 19 or any(
        item.get("status") != "joined" or not isinstance(item.get("telegram_id"), int)
        for item in targets
    ):
        raise RuntimeError("Expected 19 already joined chats with numeric Telegram IDs")

    if await asyncio.to_thread(OUTPUT.exists):
        result = json.loads(await asyncio.to_thread(OUTPUT.read_text, encoding="utf-8"))
        if result.get("limit_per_chat") != 200:
            raise RuntimeError("Existing output uses a different message limit")
    else:
        result = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "limit_per_chat": 200,
            "score_threshold": settings.signal_score_threshold,
            "chats": [],
        }

    completed = {
        chat["sheet_row"] for chat in result["chats"] if chat.get("status") == "complete"
    }
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
            raise RuntimeError("Existing Telegram session is not authorized")
        for item in targets:
            if item["sheet_row"] in completed:
                continue
            chat = {
                "sheet_row": item["sheet_row"],
                "country": item["country"],
                "name": item["name"],
                "telegram_id": item["telegram_id"],
                "messages_seen": 0,
                "text_messages": 0,
                "signals": [],
            }
            try:
                entity = await client.get_entity(-1000000000000 - item["telegram_id"])
                if not isinstance(entity, Channel) or not entity.megagroup:
                    raise RuntimeError("Source is not a joined group chat")
                chat["title"] = entity.title
                async for message in client.iter_messages(
                    entity, limit=200, wait_time=settings.scan_wait_time_seconds
                ):
                    chat["messages_seen"] += 1
                    if message.date:
                        chat["oldest_message_date"] = message.date.isoformat()
                        chat.setdefault("newest_message_date", message.date.isoformat())
                    if not message.message or message.id is None or message.date is None:
                        continue
                    chat["text_messages"] += 1
                    score = score_text(message.message)
                    if (
                        score.score < settings.signal_score_threshold
                        or SENSITIVE_PERSONAL_CONTEXT.search(message.message)
                    ):
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
                    chat["signals"].append(
                        {
                            "user_id": sender.id,
                            "username": sender.username,
                            "display_name": utils.get_display_name(sender) or str(sender.id),
                            "message_id": message.id,
                            "message_date": message.date.isoformat(),
                            "link": link,
                            "score": score.score,
                            "topics": score.topics,
                            "excerpt": excerpt(message.message, settings.signal_excerpt_max_chars),
                            "reasons": [reason.rule for reason in score.reasons],
                        }
                    )
                chat["status"] = "complete" if chat["messages_seen"] == 200 else "short_history"
            except FloodWaitError as exc:
                chat.update(status="flood_wait", retry_after_seconds=exc.seconds)
            except Exception as exc:
                chat.update(status="error", error=type(exc).__name__, error_message=str(exc))
            chat["unique_authors_with_signal"] = len(
                {signal["user_id"] for signal in chat["signals"]}
            )
            result["chats"] = [
                previous
                for previous in result["chats"]
                if previous["sheet_row"] != chat["sheet_row"]
            ] + [chat]
            save(result)
            print(
                json.dumps(
                    {key: value for key, value in chat.items() if key != "signals"},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if chat["status"] == "flood_wait":
                break
            await asyncio.sleep(3)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
