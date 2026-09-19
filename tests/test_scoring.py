from migrai_telethon.scoring import excerpt, score_text


def test_scores_high_intent_migration_message() -> None:
    result = score_text(
        "Кто подавался на ВНЖ Испании по digital nomad? "
        "Подскажите, какой доход нужен и можно ли с женой?"
    )

    assert result.score >= 8
    assert "Испания" in result.countries
    assert "digital_nomad" in result.topics
    assert "family" in result.topics


def test_tourism_is_not_a_candidate() -> None:
    result = score_text("Где найти дешевые авиабилеты и отель в Испании на отпуск?")

    assert result.score < 5


def test_politics_without_migration_is_rejected() -> None:
    result = score_text("Обсуждаем выборы, правительство и политический протест")

    assert result.score == -5


def test_political_context_does_not_override_explicit_migration_intent() -> None:
    result = score_text("Из-за политики планирую переезд. Куда лучше уехать и как получить ВНЖ?")

    assert result.score >= 5
    assert all(reason.rule != "politics_without_migration" for reason in result.reasons)


def test_excerpt_does_not_store_full_long_message() -> None:
    value = excerpt("а" * 1000, 100)

    assert len(value) == 100
    assert value.endswith("…")
