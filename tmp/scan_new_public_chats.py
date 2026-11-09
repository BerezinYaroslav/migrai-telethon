"""Read 200 recent messages per new public chat, saving only scored excerpts."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.types import Channel, User

from migrai_telethon.config import Settings
from migrai_telethon.scoring import excerpt, score_text

TARGETS = [
    {"sheet_row": 259, "reference": "https://t.me/visadesp", "country": "Испания"},
    {"sheet_row": 271, "reference": "https://t.me/startup_visa_spain", "country": "Испания"},
    {"sheet_row": 317, "reference": "https://t.me/spain_migrun", "country": "Испания"},
    {"sheet_row": 389, "reference": "https://t.me/left4portugal", "country": "Португалия"},
    {"sheet_row": 196, "reference": "https://t.me/o1eb1eb2", "country": "США"},
]
OUTPUT = Path("var/new_chats_20260927.json")


def save(result):
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(OUTPUT)


async def main():
    if OUTPUT.exists():
        raise RuntimeError("Output already exists; inspect it before another scan")
    settings = Settings()
    result = {"scanned_at": datetime.now(timezone.utc).isoformat(), "limit_per_chat": 200,
              "score_threshold": settings.signal_score_threshold, "chats": []}
    client = TelegramClient(str(settings.telegram_session_path), settings.telegram_api_id,
                            settings.telegram_api_hash, receive_updates=False,
                            flood_sleep_threshold=0, request_retries=1)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Existing Telegram session is not authorized")
        for target in TARGETS:
            chat = {**target, "messages_seen": 0, "text_messages": 0, "signals": []}
            result["chats"].append(chat)
            try:
                entity = await client.get_entity(target["reference"])
                if not isinstance(entity, Channel) or not entity.megagroup:
                    raise RuntimeError("Source must be a public group chat")
                chat.update(title=entity.title, telegram_id=entity.id,
                            participants_count=getattr(entity, "participants_count", None))
                async for message in client.iter_messages(entity, limit=200, wait_time=1):
                    chat["messages_seen"] += 1
                    if message.date:
                        chat["oldest_message_date"] = message.date.isoformat()
                        chat.setdefault("newest_message_date", message.date.isoformat())
                    if not message.message:
                        continue
                    chat["text_messages"] += 1
                    score = score_text(message.message)
                    if score.score < settings.signal_score_threshold:
                        continue
                    sender = await message.get_sender()
                    if not isinstance(sender, User) or sender.bot:
                        continue
                    chat["signals"].append({
                        "user_id": sender.id, "username": sender.username,
                        "display_name": utils.get_display_name(sender) or str(sender.id),
                        "message_id": message.id, "message_date": message.date.isoformat(),
                        "link": f"https://t.me/{entity.username}/{message.id}",
                        "score": score.score, "topics": score.topics,
                        "excerpt": excerpt(message.message, settings.signal_excerpt_max_chars),
                        "reasons": [reason.rule for reason in score.reasons],
                    })
                chat["status"] = "complete" if chat["messages_seen"] == 200 else "short_history"
            except FloodWaitError as exc:
                chat.update(status="flood_wait", retry_after_seconds=exc.seconds)
                save(result)
                print(json.dumps(chat, ensure_ascii=False), flush=True)
                break
            except Exception as exc:
                chat.update(status="error", error=type(exc).__name__, error_message=str(exc))
            chat["unique_authors_with_signal"] = len({s["user_id"] for s in chat["signals"]})
            save(result)
            print(json.dumps({k: v for k, v in chat.items() if k != "signals"},
                             ensure_ascii=False), flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
