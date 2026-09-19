from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest

from migrai_telethon.domain import (
    ReactionActor,
    SignalRecord,
    SourceType,
    StoredSource,
    TelegramMessage,
    TelegramPerson,
)
from migrai_telethon.scanner import Scanner, ScanOptions


class FakeReadOnlyTelegram:
    def __init__(
        self,
        messages: list[TelegramMessage],
        reactions: dict[int, list[ReactionActor]] | None = None,
        comments: dict[int, list[TelegramMessage]] | None = None,
    ) -> None:
        self.messages = messages
        self.reactions = reactions or {}
        self.comments = comments or {}

    async def iter_messages(self, source: StoredSource) -> AsyncIterator[TelegramMessage]:
        for message in self.messages:
            yield message

    async def iter_reaction_actors(
        self, source: StoredSource, message_id: int
    ) -> AsyncIterator[ReactionActor]:
        for actor in self.reactions.get(message_id, []):
            yield actor

    async def iter_comments(
        self, source: StoredSource, message_id: int
    ) -> AsyncIterator[TelegramMessage]:
        for comment in self.comments.get(message_id, []):
            yield comment


class FakeRepository:
    def __init__(self) -> None:
        self.signals: list[SignalRecord] = []
        self.cursor: tuple[int, int] | None = None

    async def save_signal(self, signal: SignalRecord) -> bool:
        if signal.evidence_key in {item.evidence_key for item in self.signals}:
            return False
        self.signals.append(signal)
        return True

    async def advance_cursor(self, source_id: int, message_id: int) -> None:
        self.cursor = (source_id, message_id)


@pytest.mark.asyncio
async def test_scanner_saves_relevant_message_and_weak_reaction() -> None:
    source = StoredSource(1, "Испания", "https://t.me/example", SourceType.CHAT)
    author = TelegramPerson(10, "author", "Author")
    reactor = TelegramPerson(11, "reactor", "Reactor")
    message = TelegramMessage(
        id=42,
        source=source,
        author=author,
        date=datetime.now(timezone.utc),
        text="Кто получал ВНЖ Испании digital nomad и можно ли переехать с женой?",
        link="https://t.me/example/42",
    )
    telegram = FakeReadOnlyTelegram([message], {42: [ReactionActor(person=reactor, reaction="👍")]})
    repository = FakeRepository()

    stats = await Scanner(telegram, repository, ScanOptions()).scan([source])

    assert stats.message_signals_saved == 1
    assert stats.reaction_signals_saved == 1
    assert repository.signals[0].score >= 5
    assert repository.signals[1].score == 1
    assert repository.signals[1].text_excerpt is None
    assert repository.cursor == (1, 42)


@pytest.mark.asyncio
async def test_scanner_ignores_irrelevant_message() -> None:
    source = StoredSource(1, "Туризм", "https://t.me/example", SourceType.CHAT)
    message = TelegramMessage(
        id=7,
        source=source,
        author=TelegramPerson(10, "tourist", "Tourist"),
        date=datetime.now(timezone.utc),
        text="Где найти дешевые авиабилеты на отпуск?",
        link="https://t.me/example/7",
    )
    repository = FakeRepository()

    stats = await Scanner(FakeReadOnlyTelegram([message]), repository, ScanOptions()).scan([source])

    assert stats.message_signals_saved == 0
    assert repository.signals == []
    assert repository.cursor == (1, 7)


@pytest.mark.asyncio
async def test_scanner_reads_authored_comments_on_relevant_channel_post() -> None:
    source = StoredSource(1, "Испания", "https://t.me/example", SourceType.CHANNEL)
    post = TelegramMessage(
        id=50,
        source=source,
        author=None,
        date=datetime.now(timezone.utc),
        text="Как получить ВНЖ Испании по digital nomad?",
        link="https://t.me/example/50",
    )
    comment = TelegramMessage(
        id=501,
        source=source,
        author=TelegramPerson(20, "respondent", "Respondent"),
        date=datetime.now(timezone.utc),
        text="Тоже планирую переезд с семьей и выбираю ВНЖ Испании",
        link="https://t.me/discussion/501",
        is_comment=True,
    )
    repository = FakeRepository()
    telegram = FakeReadOnlyTelegram([post], comments={50: [comment]})

    stats = await Scanner(telegram, repository, ScanOptions()).scan([source])

    assert stats.comments_seen == 1
    assert stats.message_signals_saved == 1
    assert repository.signals[0].signal_type.value == "comment"
    assert repository.signals[0].person.id == 20


def test_telegram_port_has_no_outgoing_methods() -> None:
    public_methods = {
        name
        for name in dir(FakeReadOnlyTelegram)
        if not name.startswith("_") and callable(getattr(FakeReadOnlyTelegram, name))
    }

    assert public_methods == {"iter_comments", "iter_messages", "iter_reaction_actors"}
