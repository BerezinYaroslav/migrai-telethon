from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SourceRow(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("source_type IN ('chat', 'channel')", name="ck_sources_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    telegram_ref: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_message_id: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TelegramUserRow(Base):
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CandidateRow(Base):
    __tablename__ = "candidates"
    __table_args__ = (Index("ix_candidates_status_score", "status", "best_score"),)

    telegram_user_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), default="new", server_default="new")
    best_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    signal_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    primary_topic: Mapped[str | None] = mapped_column(Text)
    primary_country: Mapped[str | None] = mapped_column(Text)
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[TelegramUserRow] = relationship()


class SignalRow(Base):
    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('message', 'comment', 'reaction')", name="ck_signals_type"
        ),
        UniqueConstraint("evidence_key"),
        Index("ix_signals_source_message", "source_id", "telegram_message_id"),
        Index("ix_signals_user", "telegram_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    evidence_key: Mapped[str] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    telegram_user_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="CASCADE")
    )
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    signal_type: Mapped[str] = mapped_column(String(16))
    message_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message_link: Mapped[str | None] = mapped_column(Text)
    text_excerpt: Mapped[str | None] = mapped_column(Text)
    reaction: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer)
    topics: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    countries: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
