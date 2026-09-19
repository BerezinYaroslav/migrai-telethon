import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete

from migrai_telethon.db_models import CandidateRow, SignalRow, SourceRow, TelegramUserRow
from migrai_telethon.domain import (
    ScoreReason,
    SignalRecord,
    SignalType,
    SourceInput,
    SourceType,
    TelegramPerson,
)
from migrai_telethon.repository import PostgresRepository, make_engine


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_repository_deduplicates_signals() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    suffix = uuid4().hex
    telegram_ref = f"https://t.me/integration_{suffix}"
    user_id = 9_000_000_000 + int(suffix[:6], 16)
    weak_user_id = user_id + 100_000_000
    evidence_key = f"integration:{suffix}"
    engine = make_engine(database_url)
    repository = PostgresRepository(engine)

    try:
        await repository.upsert_sources([SourceInput("Integration", telegram_ref, SourceType.CHAT)])
        source = next(
            item
            for item in await repository.list_enabled_sources()
            if item.telegram_ref == telegram_ref
        )
        signal = SignalRecord(
            evidence_key=evidence_key,
            source_id=source.id,
            person=TelegramPerson(user_id, f"integration_{suffix}", "Integration User"),
            message_id=101,
            signal_type=SignalType.MESSAGE,
            message_date=datetime.now(timezone.utc),
            message_link=f"{telegram_ref}/101",
            text_excerpt="Планирую переезд и выбираю ВНЖ",
            score=7,
            topics=("residence",),
            countries=("Испания",),
            reasons=(ScoreReason("integration", 7, "integration test"),),
        )

        assert await repository.save_signal(signal) is True
        assert await repository.save_signal(signal) is False

        later_weak_signal = SignalRecord(
            evidence_key=f"integration:later-weak:{suffix}",
            source_id=source.id,
            person=signal.person,
            message_id=102,
            signal_type=SignalType.REACTION,
            message_date=datetime.now(timezone.utc),
            message_link=f"{telegram_ref}/102",
            score=1,
            reaction="👍",
            reasons=(ScoreReason("reaction", 1, "later weak signal"),),
        )
        assert await repository.save_signal(later_weak_signal) is True

        weak_signal = SignalRecord(
            evidence_key=f"integration:weak:{suffix}",
            source_id=source.id,
            person=TelegramPerson(weak_user_id, None, "Weak Reaction User"),
            message_id=101,
            signal_type=SignalType.REACTION,
            message_date=datetime.now(timezone.utc),
            message_link=f"{telegram_ref}/101",
            score=1,
            reaction="👍",
            reasons=(ScoreReason("reaction", 1, "weak signal"),),
        )
        assert await repository.save_signal(weak_signal) is True

        candidates = await repository.list_candidates_for_export()
        candidate = next(item for item in candidates if item.telegram_user_id == user_id)
        assert candidate.best_score == 7
        assert candidate.primary_topic == "residence"
        assert candidate.primary_country == "Испания"
        assert candidate.text_excerpt == "Планирую переезд и выбираю ВНЖ"
        assert all(item.telegram_user_id != weak_user_id for item in candidates)
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(SignalRow).where(
                    SignalRow.evidence_key.in_(
                        [
                            evidence_key,
                            f"integration:later-weak:{suffix}",
                            f"integration:weak:{suffix}",
                        ]
                    )
                )
            )
            await connection.execute(
                delete(CandidateRow).where(
                    CandidateRow.telegram_user_id.in_([user_id, weak_user_id])
                )
            )
            await connection.execute(
                delete(TelegramUserRow).where(TelegramUserRow.id.in_([user_id, weak_user_id]))
            )
            await connection.execute(
                delete(SourceRow).where(SourceRow.telegram_ref == telegram_ref)
            )
        await repository.close()
