"""Review keyword matches below the threshold within the same 200-message snapshot."""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.tl.types import User

from migrai_telethon.config import Settings
from migrai_telethon.scoring import excerpt, score_text

PATH = Path("var/new_chats_20260928.json")
KEYWORDS = re.compile(
    r"внж|пмж|виз[ауыое]|переез|переех|релока|эмигр|иммигр|икамет|"
    r"легализ|гражданств|nomad|\bdtv\b|дтв|aufenthalt|blue.?card", re.I
)


async def main():
    snapshot = json.loads(PATH.read_text())
    settings = Settings()
    client = TelegramClient(
        str(settings.telegram_session_path), settings.telegram_api_id,
        settings.telegram_api_hash, receive_updates=False, flood_sleep_threshold=0,
        request_retries=1,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Existing session is not authorized")
        for chat in snapshot["chats"]:
            if chat["sheet_row"] not in {286, 365, 309}:
                continue
            cutoff = datetime.fromisoformat(chat["newest_message_date"]) + timedelta(seconds=1)
            extra = []
            entity = await client.get_entity(chat["reference"])
            async for message in client.iter_messages(entity, limit=200, offset_date=cutoff,
                                                       wait_time=1):
                if not message.message or not KEYWORDS.search(message.message):
                    continue
                score = score_text(message.message)
                if score.score >= settings.signal_score_threshold:
                    continue
                sender = await message.get_sender()
                if not isinstance(sender, User) or sender.bot:
                    continue
                extra.append({
                    "user_id": sender.id, "username": sender.username,
                    "display_name": utils.get_display_name(sender) or str(sender.id),
                    "message_id": message.id, "message_date": message.date.isoformat(),
                    "link": f"https://t.me/{entity.username}/{message.id}",
                    "score": score.score, "excerpt": excerpt(message.message, 500),
                    "reasons": [reason.rule for reason in score.reasons],
                })
            chat["low_score_review"] = extra
            PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
            print(json.dumps({"row": chat["sheet_row"], "extra": extra}, ensure_ascii=False),
                  flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
