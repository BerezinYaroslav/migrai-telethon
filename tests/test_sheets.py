import pytest

from migrai_telethon.domain import SourceType
from migrai_telethon.sheets import parse_source_rows


def test_parse_source_rows_uses_headers_and_filters_types() -> None:
    values = [
        ["Название", "Тип", "Ссылка", "Статус"],
        ["Испания чат", "Чат TG", "https://t.me/spain_chat", "Активен"],
        ["Канал", "Канал TG", "https://t.me/spain_news", "Забанен"],
        ["Сайт", "Сайт", "https://example.com", "Активен"],
    ]

    sources = parse_source_rows(
        values,
        name_column="Название",
        type_column="Тип",
        url_column="Ссылка",
        status_column="Статус",
        disabled_statuses=("Забанен",),
    )

    assert len(sources) == 2
    assert sources[0].source_type is SourceType.CHAT
    assert sources[0].enabled is True
    assert sources[1].source_type is SourceType.CHANNEL
    assert sources[1].enabled is False


def test_parse_source_rows_explains_missing_columns() -> None:
    with pytest.raises(ValueError, match="Статус"):
        parse_source_rows(
            [["Название", "Тип", "Ссылка"]],
            name_column="Название",
            type_column="Тип",
            url_column="Ссылка",
            status_column="Статус",
            disabled_statuses=(),
        )
