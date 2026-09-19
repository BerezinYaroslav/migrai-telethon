from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from migrai_telethon.db_models import CandidateRow, SignalRow, SourceRow, TelegramUserRow
from migrai_telethon.domain import (
    CandidateExport,
    SignalRecord,
    SourceInput,
    SourceType,
    StoredSource,
)


def make_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


class PostgresRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def close(self) -> None:
        await self._engine.dispose()

    async def upsert_sources(self, sources: Sequence[SourceInput]) -> int:
        async with self._sessions.begin() as session:
            for source in sources:
                statement = insert(SourceRow).values(
                    telegram_ref=source.telegram_ref,
                    name=source.name,
                    source_type=source.source_type.value,
                    enabled=source.enabled,
                )
                statement = statement.on_conflict_do_update(
                    index_elements=[SourceRow.telegram_ref],
                    set_={
                        "name": statement.excluded.name,
                        "source_type": statement.excluded.source_type,
                        "enabled": statement.excluded.enabled,
                        "updated_at": func.now(),
                    },
                )
                await session.execute(statement)
        return len(sources)

    async def list_enabled_sources(self) -> list[StoredSource]:
        async with self._sessions() as session:
            result = await session.scalars(
                select(SourceRow).where(SourceRow.enabled.is_(True)).order_by(SourceRow.id)
            )
            return [
                StoredSource(
                    id=row.id,
                    name=row.name,
                    telegram_ref=row.telegram_ref,
                    source_type=SourceType(row.source_type),
                    last_message_id=row.last_message_id,
                )
                for row in result
            ]

    async def save_signal(self, signal: SignalRecord) -> bool:
        async with self._sessions.begin() as session:
            await self._upsert_user(session, signal)
            inserted = await self._insert_signal(session, signal)
            if inserted:
                await self._upsert_candidate(session, signal)
            return inserted

    async def advance_cursor(self, source_id: int, message_id: int) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(SourceRow)
                .where(SourceRow.id == source_id)
                .values(
                    last_message_id=func.greatest(SourceRow.last_message_id, message_id),
                    updated_at=func.now(),
                )
            )

    async def list_candidates_for_export(
        self, limit: int = 500, min_score: int = 5
    ) -> list[CandidateExport]:
        async with self._sessions() as session:
            ranked_signals = select(
                SignalRow.id.label("signal_id"),
                SignalRow.telegram_user_id.label("telegram_user_id"),
                func.row_number()
                .over(
                    partition_by=SignalRow.telegram_user_id,
                    order_by=(SignalRow.score.desc(), SignalRow.id.desc()),
                )
                .label("rank"),
            ).subquery()
            query = (
                select(CandidateRow, TelegramUserRow, SignalRow, SourceRow)
                .join(TelegramUserRow, TelegramUserRow.id == CandidateRow.telegram_user_id)
                .join(
                    ranked_signals,
                    ranked_signals.c.telegram_user_id == CandidateRow.telegram_user_id,
                )
                .join(SignalRow, SignalRow.id == ranked_signals.c.signal_id)
                .join(SourceRow, SourceRow.id == SignalRow.source_id)
                .where(
                    ranked_signals.c.rank == 1,
                    CandidateRow.exported_at.is_(None),
                    CandidateRow.best_score >= min_score,
                )
                .order_by(CandidateRow.best_score.desc(), CandidateRow.last_detected_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(query)).all()
            return [
                CandidateExport(
                    telegram_user_id=candidate.telegram_user_id,
                    username=user.username,
                    display_name=user.display_name,
                    status=candidate.status,
                    source_name=source.name,
                    message_link=signal.message_link,
                    text_excerpt=signal.text_excerpt,
                    primary_topic=candidate.primary_topic,
                    best_score=candidate.best_score,
                    primary_country=candidate.primary_country,
                    detected_at=candidate.last_detected_at,
                )
                for candidate, user, signal, source in rows
            ]

    async def mark_exported(self, user_ids: Sequence[int]) -> None:
        if not user_ids:
            return
        async with self._sessions.begin() as session:
            await session.execute(
                update(CandidateRow)
                .where(CandidateRow.telegram_user_id.in_(user_ids))
                .values(exported_at=datetime.now(timezone.utc))
            )

    @staticmethod
    async def _upsert_user(session: AsyncSession, signal: SignalRecord) -> None:
        person = signal.person
        statement = insert(TelegramUserRow).values(
            id=person.id,
            username=person.username,
            display_name=person.display_name,
            is_bot=person.is_bot,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[TelegramUserRow.id],
                set_={
                    "username": statement.excluded.username,
                    "display_name": statement.excluded.display_name,
                    "is_bot": statement.excluded.is_bot,
                    "last_seen_at": func.now(),
                },
            )
        )

    @staticmethod
    async def _insert_signal(session: AsyncSession, signal: SignalRecord) -> bool:
        statement = (
            insert(SignalRow)
            .values(
                evidence_key=signal.evidence_key,
                source_id=signal.source_id,
                telegram_user_id=signal.person.id,
                telegram_message_id=signal.message_id,
                signal_type=signal.signal_type.value,
                message_date=signal.message_date,
                message_link=signal.message_link,
                text_excerpt=signal.text_excerpt,
                reaction=signal.reaction,
                score=signal.score,
                topics=list(signal.topics),
                countries=list(signal.countries),
                reasons=[
                    {
                        "rule": reason.rule,
                        "points": reason.points,
                        "description": reason.description,
                    }
                    for reason in signal.reasons
                ],
            )
            .on_conflict_do_nothing(index_elements=[SignalRow.evidence_key])
            .returning(SignalRow.id)
        )
        return (await session.scalar(statement)) is not None

    @staticmethod
    async def _upsert_candidate(session: AsyncSession, signal: SignalRecord) -> None:
        topic = signal.topics[0] if signal.topics else None
        country = signal.countries[0] if signal.countries else None
        statement = insert(CandidateRow).values(
            telegram_user_id=signal.person.id,
            best_score=signal.score,
            signal_count=1,
            primary_topic=topic,
            primary_country=country,
            exported_at=None,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[CandidateRow.telegram_user_id],
                set_={
                    "best_score": func.greatest(
                        CandidateRow.best_score, statement.excluded.best_score
                    ),
                    "signal_count": CandidateRow.signal_count + 1,
                    "primary_topic": func.coalesce(
                        statement.excluded.primary_topic, CandidateRow.primary_topic
                    ),
                    "primary_country": func.coalesce(
                        statement.excluded.primary_country, CandidateRow.primary_country
                    ),
                    "last_detected_at": func.now(),
                    "exported_at": None,
                },
            )
        )
