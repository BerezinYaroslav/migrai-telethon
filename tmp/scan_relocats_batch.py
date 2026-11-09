"""Scan only a specified, already joined Relocats batch (read-only Telegram access)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from migrai_telethon.config import Settings
from migrai_telethon.domain import SourceInput, SourceType
from migrai_telethon.repository import PostgresRepository, make_engine
from migrai_telethon.scanner import Scanner, ScanOptions
from migrai_telethon.telegram_reader import ReadOnlyTelegramReader


async def main(rows: list[int]) -> None:
    state_text = await asyncio.to_thread(
        Path("var/relocats_join_state.json").read_text, encoding="utf-8"
    )
    state = json.loads(state_text)
    selected = [
        item
        for item in state["items"].values()
        if item.get("sheet_row") in rows
    ]
    if len(selected) != len(rows) or any(item.get("status") != "joined" for item in selected):
        raise SystemExit("Every selected row must be present with joined status")
    if any(not isinstance(item.get("telegram_id"), int) for item in selected):
        raise SystemExit("Every selected row must have a numeric Telegram ID")

    settings = Settings()
    if not settings.telegram_ready:
        raise SystemExit("Telegram credentials are missing")
    repository = PostgresRepository(make_engine(settings.database_url))
    refs = {f"-100{item['telegram_id']}" for item in selected}
    try:
        await repository.upsert_sources(
            [
                SourceInput(
                    name=item["name"],
                    telegram_ref=f"-100{item['telegram_id']}",
                    source_type=SourceType.CHAT,
                )
                for item in selected
            ]
        )
        sources = [
            source
            for source in await repository.list_enabled_sources()
            if source.telegram_ref in refs and source.last_message_id == 0
        ]
        if len(sources) != len(rows):
            raise SystemExit(
                f"Expected {len(rows)} new sources; found {len(sources)} with an empty cursor"
            )

        assert settings.telegram_api_id is not None
        assert settings.telegram_api_hash is not None
        async with ReadOnlyTelegramReader(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            session_path=settings.telegram_session_path,
            flood_sleep_threshold=settings.telegram_flood_sleep_threshold_seconds,
            history_limit=200,
            incremental_limit=200,
            wait_time=settings.scan_wait_time_seconds,
            comments_limit=settings.comments_limit_per_post,
            reaction_users_limit=settings.reaction_users_limit,
        ) as telegram:
            scanner = Scanner(
                telegram,
                repository,
                ScanOptions(
                    score_threshold=settings.signal_score_threshold,
                    excerpt_max_chars=settings.signal_excerpt_max_chars,
                    comments_enabled=False,
                    reactions_enabled=False,
                ),
            )
            stats = await scanner.scan(sources)
        print(
            json.dumps(
                {
                    "rows": rows,
                    "sources": stats.sources,
                    "messages_seen": stats.messages_seen,
                    "signals_saved": stats.message_signals_saved,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        await repository.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", nargs="+", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.rows))
