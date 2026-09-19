from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SourceType(str, Enum):
    CHAT = "chat"
    CHANNEL = "channel"


class SignalType(str, Enum):
    MESSAGE = "message"
    COMMENT = "comment"
    REACTION = "reaction"


@dataclass(frozen=True, slots=True)
class SourceInput:
    name: str
    telegram_ref: str
    source_type: SourceType
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class StoredSource:
    id: int
    name: str
    telegram_ref: str
    source_type: SourceType
    last_message_id: int = 0


@dataclass(frozen=True, slots=True)
class TelegramPerson:
    id: int
    username: str | None
    display_name: str
    is_bot: bool = False


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    id: int
    source: StoredSource
    author: TelegramPerson | None
    date: datetime
    text: str
    link: str | None
    is_comment: bool = False


@dataclass(frozen=True, slots=True)
class ReactionActor:
    person: TelegramPerson
    reaction: str


@dataclass(frozen=True, slots=True)
class ScoreReason:
    rule: str
    points: int
    description: str


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: int
    topics: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    reasons: tuple[ScoreReason, ...] = ()

    @property
    def matched(self) -> bool:
        return bool(self.reasons)


@dataclass(frozen=True, slots=True)
class SignalRecord:
    evidence_key: str
    source_id: int
    person: TelegramPerson
    message_id: int
    signal_type: SignalType
    message_date: datetime
    message_link: str | None
    score: int
    text_excerpt: str | None = None
    reaction: str | None = None
    topics: tuple[str, ...] = field(default_factory=tuple)
    countries: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[ScoreReason, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CandidateExport:
    telegram_user_id: int
    username: str | None
    display_name: str
    status: str
    source_name: str
    message_link: str | None
    text_excerpt: str | None
    primary_topic: str | None
    best_score: int
    primary_country: str | None
    detected_at: datetime
