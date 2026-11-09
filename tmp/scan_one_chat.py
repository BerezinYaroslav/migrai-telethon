"""Ad-hoc: join (if needed) and score first N messages of one Telegram chat.

Uses migrai's read-only reader and scoring, without PostgreSQL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from telethon import TelegramClient, utils
from telethon.tl import functions, types

from migrai_telethon.config import Settings
from migrai_telethon.scoring import excerpt, score_text


def parse_invite_hash(reference: str) -> str | None:
    path = urlparse(reference).path.strip("/")
    if path.startswith("+") and len(path) > 1:
        return path[1:]
    if path.startswith("joinchat/") and len(path) > len("joinchat/"):
        return path.split("/", 1)[1]
    return None


async def ensure_membership(
    client: TelegramClient, reference: str
) -> types.Channel | types.Chat:
    invite_hash = parse_invite_hash(reference)
    if invite_hash is None:
        entity = await client.get_entity(reference)
        if not isinstance(entity, (types.Channel, types.Chat)):
            raise RuntimeError(f"{reference!r} is not a chat or channel")
        return entity

    invite = await client(functions.messages.CheckChatInviteRequest(invite_hash))
    if isinstance(invite, types.ChatInviteAlready) and isinstance(
        invite.chat, (types.Channel, types.Chat)
    ):
        return invite.chat

    result = await client(functions.messages.ImportChatInviteRequest(invite_hash))
    updates = getattr(result, "updates", result)
    for chat in getattr(updates, "chats", ()):
        if isinstance(chat, (types.Channel, types.Chat)):
            return chat
    raise RuntimeError("Telegram did not return joined chat entity")


@dataclass
class AuthorAggregate:
    user_id: int
    username: str | None
    display_name: str
    best_score: int = 0
    total_score: int = 0
    hits: int = 0
    topics: set[str] = field(default_factory=set)
    countries: set[str] = field(default_factory=set)
    best_excerpt: str = ""
    best_link: str | None = None
    best_date: datetime | None = None


async def main(reference: str, limit: int, excerpt_chars: int, threshold: int) -> None:
    settings = Settings()
    if not settings.telegram_ready:
        raise SystemExit("TELEGRAM_API_ID/TELEGRAM_API_HASH are not set")

    client = TelegramClient(
        str(settings.telegram_session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        receive_updates=False,
        flood_sleep_threshold=settings.telegram_flood_sleep_threshold_seconds,
    )

    async with client:
        entity = await ensure_membership(client, reference)
        title = getattr(entity, "title", str(getattr(entity, "id", "?")))
        print(f"chat: {title} (id={entity.id})", flush=True)

        messages_seen = 0
        messages_with_text = 0
        matched = 0
        aggregates: dict[int, AuthorAggregate] = {}

        async for message in client.iter_messages(
            entity, limit=limit, wait_time=settings.scan_wait_time_seconds
        ):
            messages_seen += 1
            if not message.message or message.id is None or message.date is None:
                continue
            messages_with_text += 1
            result = score_text(message.message)
            if not result.matched:
                continue
            matched += 1

            sender = await message.get_sender()
            if not isinstance(sender, types.User) or sender.bot:
                continue

            agg = aggregates.get(sender.id)
            if agg is None:
                agg = AuthorAggregate(
                    user_id=sender.id,
                    username=sender.username,
                    display_name=utils.get_display_name(sender) or str(sender.id),
                )
                aggregates[sender.id] = agg
            agg.hits += 1
            agg.total_score += result.score
            agg.topics.update(result.topics)
            agg.countries.update(result.countries)
            if result.score > agg.best_score:
                agg.best_score = result.score
                agg.best_excerpt = excerpt(message.message, excerpt_chars)
                username = getattr(entity, "username", None)
                if username:
                    agg.best_link = f"https://t.me/{username}/{message.id}"
                elif isinstance(entity, types.Channel):
                    agg.best_link = f"https://t.me/c/{entity.id}/{message.id}"
                agg.best_date = message.date

        candidates = sorted(
            (a for a in aggregates.values() if a.best_score >= threshold),
            key=lambda a: (a.best_score, a.total_score, a.hits),
            reverse=True,
        )
        near_miss = sorted(
            (a for a in aggregates.values() if a.best_score < threshold),
            key=lambda a: (a.best_score, a.hits),
            reverse=True,
        )

        summary = {
            "chat_title": title,
            "chat_id": entity.id,
            "messages_seen": messages_seen,
            "messages_with_text": messages_with_text,
            "matched_messages": matched,
            "unique_authors_with_signal": len(aggregates),
            "candidates_above_threshold": len(candidates),
            "threshold": threshold,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

        def dump(a: AuthorAggregate) -> dict[str, object]:
            return {
                "user_id": a.user_id,
                "username": a.username,
                "display_name": a.display_name,
                "best_score": a.best_score,
                "total_score": a.total_score,
                "hits": a.hits,
                "topics": sorted(a.topics),
                "countries": sorted(a.countries),
                "best_link": a.best_link,
                "best_date": a.best_date.isoformat() if a.best_date else None,
                "best_excerpt": a.best_excerpt,
            }

        out = {
            "summary": summary,
            "candidates": [dump(a) for a in candidates],
            "near_miss_top10": [dump(a) for a in near_miss[:10]],
        }
        out_path = Path("tmp/scan_one_chat_result.json")
        await asyncio.to_thread(
            out_path.write_text,
            json.dumps(out, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"saved: {out_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", help="t.me invite link, @username, or numeric id")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--excerpt-chars", type=int, default=280)
    parser.add_argument("--threshold", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.reference, args.limit, args.excerpt_chars, args.threshold))
