from migrai_telethon.telegram_reader import ReadOnlyTelegramReader


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
