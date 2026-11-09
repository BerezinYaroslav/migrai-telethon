"""Read-only inventory of chats accessible to the existing Telegram session."""

import asyncio
import json
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

from migrai_telethon.config import Settings


async def main():
    settings = Settings()
    client = TelegramClient(
        str(settings.telegram_session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        receive_updates=False,
        flood_sleep_threshold=0,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Existing Telegram session is not authorized")
        chats = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, Chat) or (
                isinstance(entity, Channel) and entity.megagroup
            ):
                chats.append({
                    "id": dialog.id,
                    "title": entity.title,
                    "username": getattr(entity, "username", None),
                })
        path = Path("var/available_chats_20260927.json")
        path.write_text(json.dumps(chats, ensure_ascii=False, indent=2))
        print(json.dumps(chats, ensure_ascii=False), flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
