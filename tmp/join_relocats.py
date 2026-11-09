from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from telethon import TelegramClient, errors
from telethon.tl import functions, types

from migrai_telethon.config import Settings

LIST_PATH = Path("tmp/relocats.json")
STATE_PATH = Path("var/relocats_join_state.json")


def invite_hash(reference: str) -> str:
    path = urlparse(reference).path.strip("/")
    if not path.startswith("+"):
        raise ValueError(f"Не пригласительная ссылка Telegram: {reference}")
    return path[1:]


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(STATE_PATH)


async def joined_chat(client: TelegramClient, hash_value: str) -> types.Channel | types.Chat | None:
    invite = await client(functions.messages.CheckChatInviteRequest(hash_value))
    if isinstance(invite, types.ChatInviteAlready) and isinstance(
        invite.chat, (types.Channel, types.Chat)
    ):
        return invite.chat
    return None


async def main(limit: int, pause_seconds: float) -> None:
    settings = Settings()
    chats = json.loads(await asyncio.to_thread(LIST_PATH.read_text, encoding="utf-8"))
    state_exists = await asyncio.to_thread(STATE_PATH.exists)
    state = (
        json.loads(await asyncio.to_thread(STATE_PATH.read_text, encoding="utf-8"))
        if state_exists
        else {"items": {}}
    )
    items: dict[str, dict[str, object]] = state.setdefault("items", {})

    wait_until = state.get("flood_wait_until")
    if wait_until is None and state_exists:
        legacy_waits = [
            item.get("retry_after_seconds")
            for item in items.values()
            if item.get("status") == "flood_wait"
        ]
        legacy_waits = [seconds for seconds in legacy_waits if isinstance(seconds, int)]
        if legacy_waits:
            recorded_at = datetime.fromtimestamp(STATE_PATH.stat().st_mtime, timezone.utc)
            wait_until = (recorded_at + timedelta(seconds=max(legacy_waits) + 60)).isoformat()
    if wait_until is not None:
        try:
            deadline = datetime.fromisoformat(str(wait_until))
            if deadline.tzinfo is None:
                raise ValueError("FloodWait deadline has no timezone")
        except ValueError:
            print(json.dumps({"status": "flood_wait_deadline_invalid"}), flush=True)
            return
        if datetime.now(timezone.utc) < deadline:
            print(
                json.dumps({"status": "flood_wait_active", "retry_at": deadline.isoformat()}),
                flush=True,
            )
            return

    client = TelegramClient(
        str(settings.telegram_session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        receive_updates=False,
        flood_sleep_threshold=settings.telegram_flood_sleep_threshold_seconds,
    )
    attempted = 0
    joined = 0
    async with client:
        for chat_data in chats:
            reference = chat_data["telegram_ref"]
            previous = items.get(reference, {})
            if previous.get("status") in {"joined", "expired", "invalid"}:
                continue
            if attempted >= limit:
                break
            attempted += 1
            hash_value = invite_hash(reference)
            try:
                result = await client(functions.messages.ImportChatInviteRequest(hash_value))
                updates = getattr(result, "updates", result)
                chat = next(
                    (
                        item
                        for item in getattr(updates, "chats", ())
                        if isinstance(item, (types.Channel, types.Chat))
                    ),
                    None,
                )
                if chat is None:
                    raise RuntimeError("Telegram не вернул данные вступления")
                record = {
                    **chat_data,
                    "status": "joined",
                    "telegram_id": chat.id,
                    "telegram_title": chat.title,
                }
                joined += 1
            except errors.UserAlreadyParticipantError:
                chat = await joined_chat(client, hash_value)
                record = {
                    **chat_data,
                    "status": "joined",
                    "telegram_id": chat.id if chat else None,
                    "telegram_title": chat.title if chat else chat_data["name"],
                }
            except errors.InviteHashExpiredError:
                record = {**chat_data, "status": "expired"}
            except errors.InviteHashInvalidError:
                record = {**chat_data, "status": "invalid"}
            except errors.ChannelsTooMuchError:
                record = {**chat_data, "status": "channel_limit"}
                items[reference] = record
                save_state(state)
                print(json.dumps(record, ensure_ascii=False), flush=True)
                break
            except errors.FloodWaitError as exc:
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=exc.seconds + 60)).isoformat()
                record = {
                    **chat_data,
                    "status": "flood_wait",
                    "retry_after_seconds": exc.seconds,
                    "retry_at": retry_at,
                }
                items[reference] = record
                state["flood_wait_until"] = retry_at
                save_state(state)
                print(json.dumps(record, ensure_ascii=False), flush=True)
                break
            except errors.RPCError as exc:
                record = {**chat_data, "status": "error", "error": type(exc).__name__}

            items[reference] = record
            save_state(state)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            if record["status"] == "joined" and pause_seconds:
                await asyncio.sleep(pause_seconds)

    summary = {
        "attempted": attempted,
        "joined_this_run": joined,
        "joined_total": sum(1 for item in items.values() if item.get("status") == "joined"),
        "remaining": sum(
            1
            for item in chats
            if items.get(item["telegram_ref"], {}).get("status")
            not in {"joined", "expired", "invalid"}
        ),
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--pause-seconds", type=float, default=10.0)
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.pause_seconds))
