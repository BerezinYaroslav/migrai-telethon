from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from migrai_telethon.domain import (
    ReactionActor,
    ScoreReason,
    ScoreResult,
    SignalRecord,
    SignalType,
    SourceType,
    StoredSource,
    TelegramMessage,
)
from migrai_telethon.scoring import excerpt, score_text

logger = logging.getLogger(__name__)


class TelegramReadPort(Protocol):
    def iter_messages(self, source: StoredSource) -> AsyncIterator[TelegramMessage]: ...

    def iter_comments(
        self, source: StoredSource, message_id: int
    ) -> AsyncIterator[TelegramMessage]: ...

    def iter_reaction_actors(
        self, source: StoredSource, message_id: int
    ) -> AsyncIterator[ReactionActor]: ...


class RepositoryPort(Protocol):
    async def save_signal(self, signal: SignalRecord) -> bool: ...

    async def advance_cursor(self, source_id: int, message_id: int) -> None: ...


@dataclass(frozen=True, slots=True)
class ScanOptions:
    score_threshold: int = 5
    excerpt_max_chars: int = 500
    comments_enabled: bool = True
    comments_post_min_score: int = 5
    reactions_enabled: bool = True
    reaction_signal_score: int = 1
    reaction_post_min_score: int = 5


@dataclass(slots=True)
class ScanStats:
    sources: int = 0
    messages_seen: int = 0
    comments_seen: int = 0
    message_signals_saved: int = 0
    reaction_signals_saved: int = 0
    skipped_bots: int = 0


class Scanner:
    def __init__(
        self,
        telegram: TelegramReadPort,
        repository: RepositoryPort,
        options: ScanOptions,
    ) -> None:
        self._telegram = telegram
        self._repository = repository
        self._options = options

    async def scan(self, sources: Sequence[StoredSource]) -> ScanStats:
        total = ScanStats()
        for source in sources:
            total.sources += 1
            try:
                await self._scan_source(source, total)
            except Exception:
                logger.exception("Ошибка при сканировании источника %s", source.name)
        return total

    async def _scan_source(self, source: StoredSource, stats: ScanStats) -> None:
        max_message_id = source.last_message_id
        async for message in self._telegram.iter_messages(source):
            stats.messages_seen += 1
            max_message_id = max(max_message_id, message.id)
            result = score_text(message.text)
            await self._save_authored_message(message, result, stats)

            if (
                self._options.comments_enabled
                and source.source_type is SourceType.CHANNEL
                and result.score >= self._options.comments_post_min_score
            ):
                async for comment in self._telegram.iter_comments(source, message.id):
                    stats.comments_seen += 1
                    await self._save_authored_message(comment, score_text(comment.text), stats)

            if (
                self._options.reactions_enabled
                and result.score >= self._options.reaction_post_min_score
            ):
                async for actor in self._telegram.iter_reaction_actors(source, message.id):
                    if actor.person.is_bot or (
                        message.author is not None and actor.person.id == message.author.id
                    ):
                        continue
                    reaction_saved = await self._repository.save_signal(
                        SignalRecord(
                            evidence_key=f"reaction:{source.id}:{message.id}:{actor.person.id}",
                            source_id=source.id,
                            person=actor.person,
                            message_id=message.id,
                            signal_type=SignalType.REACTION,
                            message_date=message.date,
                            message_link=message.link,
                            text_excerpt=None,
                            reaction=actor.reaction,
                            score=self._options.reaction_signal_score,
                            topics=result.topics,
                            countries=result.countries,
                            reasons=(
                                ScoreReason(
                                    "reaction_to_relevant_post",
                                    self._options.reaction_signal_score,
                                    "реакция на релевантное миграционное сообщение",
                                ),
                            ),
                        )
                    )
                    stats.reaction_signals_saved += int(reaction_saved)

        if max_message_id > source.last_message_id:
            await self._repository.advance_cursor(source.id, max_message_id)

    async def _save_authored_message(
        self,
        message: TelegramMessage,
        result: ScoreResult,
        stats: ScanStats,
    ) -> None:
        if message.author is None:
            return
        if message.author.is_bot:
            stats.skipped_bots += 1
            return
        if result.score < self._options.score_threshold:
            return

        signal_type = SignalType.COMMENT if message.is_comment else SignalType.MESSAGE
        saved = await self._repository.save_signal(
            SignalRecord(
                evidence_key=(
                    f"{signal_type.value}:{message.source.id}:{message.id}:{message.author.id}"
                ),
                source_id=message.source.id,
                person=message.author,
                message_id=message.id,
                signal_type=signal_type,
                message_date=message.date,
                message_link=message.link,
                text_excerpt=excerpt(message.text, self._options.excerpt_max_chars),
                score=result.score,
                topics=result.topics,
                countries=result.countries,
                reasons=result.reasons,
            )
        )
        stats.message_signals_saved += int(saved)
