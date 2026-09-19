from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

from telethon import TelegramClient, errors, utils
from telethon.tl.custom.message import Message
from telethon.tl.functions.messages import GetMessageReactionsListRequest
from telethon.tl.types import Channel, Chat, MessagePeerReaction, User

from migrai_telethon.domain import ReactionActor, StoredSource, TelegramMessage, TelegramPerson

logger = logging.getLogger(__name__)


class ReadOnlyTelegramReader:
    """Narrow Telethon adapter that intentionally exposes read operations only."""

    def __init__(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_path: Path,
        flood_sleep_threshold: int,
        history_limit: int,
        incremental_limit: int,
        wait_time: float,
        comments_limit: int,
        reaction_users_limit: int,
    ) -> None:
        session_path.parent.mkdir(parents=True, exist_ok=True)
        self.__client = TelegramClient(
            str(session_path),
            api_id,
            api_hash,
            receive_updates=False,
            flood_sleep_threshold=flood_sleep_threshold,
        )
        self._history_limit = history_limit
        self._incremental_limit = incremental_limit
        self._wait_time = wait_time
        self._comments_limit = comments_limit
        self._reaction_users_limit = reaction_users_limit

    async def __aenter__(self) -> ReadOnlyTelegramReader:
        await self.__client.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.__client.disconnect()

    async def iter_messages(self, source: StoredSource) -> AsyncIterator[TelegramMessage]:
        entity = await self.__client.get_entity(source.telegram_ref)
        if not isinstance(entity, (Channel, Chat)):
            raise ValueError(f"Источник {source.telegram_ref!r} не является чатом или каналом")

        if source.last_message_id:
            iterator = self.__client.iter_messages(
                entity,
                min_id=source.last_message_id,
                reverse=True,
                limit=self._incremental_limit,
                wait_time=self._wait_time,
            )
            async for message in iterator:
                converted = await self._convert_message(source, entity, message)
                if converted is not None:
                    yield converted
            return

        recent = [
            message
            async for message in self.__client.iter_messages(
                entity,
                limit=self._history_limit,
                wait_time=self._wait_time,
            )
        ]
        for message in reversed(recent):
            converted = await self._convert_message(source, entity, message)
            if converted is not None:
                yield converted

    async def iter_comments(
        self, source: StoredSource, message_id: int
    ) -> AsyncIterator[TelegramMessage]:
        entity = await self.__client.get_entity(source.telegram_ref)
        if not isinstance(entity, Channel):
            return
        try:
            iterator = self.__client.iter_messages(
                entity,
                reply_to=message_id,
                limit=self._comments_limit,
                reverse=True,
                wait_time=self._wait_time,
            )
            async for message in iterator:
                chat = await message.get_chat()
                link_entity = chat if isinstance(chat, (Channel, Chat)) else entity
                converted = await self._convert_message(source, link_entity, message)
                if converted is not None:
                    yield TelegramMessage(
                        id=converted.id,
                        source=converted.source,
                        author=converted.author,
                        date=converted.date,
                        text=converted.text,
                        link=converted.link,
                        is_comment=True,
                    )
        except errors.RPCError as exc:
            logger.debug("Комментарии недоступны для %s/%s: %s", source.name, message_id, exc)

    async def iter_reaction_actors(
        self, source: StoredSource, message_id: int
    ) -> AsyncIterator[ReactionActor]:
        entity = await self.__client.get_input_entity(source.telegram_ref)
        offset: str | None = None
        remaining = self._reaction_users_limit

        while remaining > 0:
            try:
                result = await self.__client(
                    GetMessageReactionsListRequest(
                        peer=entity,
                        id=message_id,
                        limit=min(100, remaining),
                        reaction=None,
                        offset=offset,
                    )
                )
            except errors.BroadcastForbiddenError:
                logger.debug("Авторы реакций недоступны для broadcast-канала %s", source.name)
                return
            except errors.RPCError as exc:
                logger.warning(
                    "Не удалось прочитать реакции %s/%s: %s", source.name, message_id, exc
                )
                return

            users = {user.id: user for user in result.users if isinstance(user, User)}
            for item in result.reactions:
                if not isinstance(item, MessagePeerReaction):
                    continue
                peer_id = utils.get_peer_id(item.peer_id)
                user = users.get(peer_id)
                if user is None or user.bot:
                    continue
                yield ReactionActor(
                    person=self._person_from_user(user),
                    reaction=self._reaction_label(item.reaction),
                )
                remaining -= 1
                if remaining <= 0:
                    return

            offset = result.next_offset
            if not offset:
                return

    async def _convert_message(
        self, source: StoredSource, entity: Channel | Chat, message: Message
    ) -> TelegramMessage | None:
        if not message.message or message.id is None or message.date is None:
            return None

        sender = await message.get_sender()
        person = self._person_from_user(sender) if isinstance(sender, User) else None
        return TelegramMessage(
            id=message.id,
            source=source,
            author=person,
            date=message.date,
            text=message.message,
            link=self._message_link(entity, message.id),
        )

    @staticmethod
    def _person_from_user(user: User) -> TelegramPerson:
        return TelegramPerson(
            id=user.id,
            username=user.username,
            display_name=utils.get_display_name(user) or str(user.id),
            is_bot=bool(user.bot),
        )

    @staticmethod
    def _message_link(entity: Channel | Chat, message_id: int) -> str | None:
        username = getattr(entity, "username", None)
        if username:
            return f"https://t.me/{username}/{message_id}"
        if isinstance(entity, Channel):
            return f"https://t.me/c/{entity.id}/{message_id}"
        return None

    @staticmethod
    def _reaction_label(reaction: object) -> str:
        emoticon = getattr(reaction, "emoticon", None)
        document_id = getattr(reaction, "document_id", None)
        if emoticon:
            return str(emoticon)
        if document_id:
            return f"custom:{document_id}"
        return type(reaction).__name__
