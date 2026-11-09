import pytest

from migrai_telethon.telegram_reader import ReadOnlyTelegramReader, telegram_invite_hash


def test_reader_does_not_expose_outgoing_telegram_actions() -> None:
    forbidden = {
        "send_message",
        "send_file",
        "forward_messages",
        "send_reaction",
        "join_channel",
        "invite_to_channel",
    }

    assert forbidden.isdisjoint(dir(ReadOnlyTelegramReader))


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("https://t.me/+MFPqqhcy8n1kNjBi", "MFPqqhcy8n1kNjBi"),
        ("https://telegram.me/joinchat/abc123", "abc123"),
        ("https://t.me/public_channel", None),
        ("https://example.com/+abc123", None),
    ],
)
def test_telegram_invite_hash(reference: str, expected: str | None) -> None:
    assert telegram_invite_hash(reference) == expected
