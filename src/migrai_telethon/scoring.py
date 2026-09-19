from __future__ import annotations

import re
from dataclasses import dataclass

from migrai_telethon.domain import ScoreReason, ScoreResult


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    points: int
    description: str
    pattern: re.Pattern[str]


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


POSITIVE_RULES: tuple[Rule, ...] = (
    Rule(
        "migration_intent",
        5,
        "явное намерение переехать или выбрать страну",
        _rx(
            r"\b(хочу|планирую|собираюсь|думаю|решил[аи]?)\b.{0,40}"
            r"\b(переех|уехат|релокац|эмиграц)|\bкуда\s+(?:лучше\s+)?уехать\b|"
            r"\bвыбираю\s+стран"
        ),
    ),
    Rule(
        "direct_status_question",
        5,
        "прямой вопрос о визе, ВНЖ, ПМЖ, гражданстве или легализации",
        _rx(
            r"(?:\?|кто\s+(?:подавал|получал)|как\s+(?:получить|оформить|остаться)|"
            r"подскажите).{0,100}\b(внж|пмж|гражданств|виз[ауые]|легализац|"
            r"digital\s+nomad|номадск)\b|\b(внж|пмж|гражданств|виз[ауые]|легализац|"
            r"digital\s+nomad|номадск)\b.{0,100}(?:\?|как|кто|подскажите)"
        ),
    ),
    Rule(
        "study_route",
        4,
        "образование рассматривается как миграционный маршрут",
        _rx(
            r"\b(учебн\w*\s+виз|студенческ\w*\s+виз|магистратур|языков\w*\s+курс)"
            r".{0,80}(переех|остать|внж|виз|легализац)"
        ),
    ),
    Rule(
        "work_route",
        4,
        "рабочий или профессиональный миграционный маршрут",
        _rx(
            r"\b(blue\s*card|голуб\w*\s+карт|виз\w*\s+талант|рабоч\w*\s+виз|"
            r"оффер|релокейт|relocat).{0,80}(переех|внж|виз|герман|испан|португал|европ)"
        ),
    ),
    Rule(
        "route_comparison",
        3,
        "сравнение стран или миграционных маршрутов",
        _rx(
            r"\b(сравни|выбираю|что\s+лучше|какая\s+страна|между).{0,100}"
            r"(стран|виз|внж|маршрут|испан|португал|герман|итал)"
        ),
    ),
    Rule(
        "family_budget_timeline",
        3,
        "указаны семья, бюджет, доход или сроки переезда",
        _rx(
            r"\b(с\s+(?:женой|мужем|супруг|ребен|детьм)|семь[еёйю]|доход|"
            r"зарабатыва|бюджет|через\s+\d+\s+(?:месяц|год)|до\s+конца\s+год)\b"
        ),
    ),
    Rule(
        "migration_terms",
        2,
        "есть миграционная тематика без достаточного явного намерения",
        _rx(
            r"\b(внж|пмж|гражданств|виза\s*d|digital\s+nomad|номадск\w*\s+виз|"
            r"легализац|консульств|релокац|эмиграц)\b"
        ),
    ),
)

NEGATIVE_RULES: tuple[Rule, ...] = (
    Rule(
        "tourism_only",
        -3,
        "сообщение похоже на туризм, отпуск или поиск билетов",
        _rx(
            r"\b(отпуск|туристическ|отел[ьи]|авиабилет|дешев\w*\s+билет|куда\s+слетать|экскурси)\b"
        ),
    ),
)

POLITICAL_PATTERN = _rx(r"\b(выборы|протест|оппозици|митинг|политическ|правительств|президент)\b")
MIGRATION_PATTERN = _rx(r"\b(переех|уехат|релокац|эмиграц|внж|пмж|виз|легализац|гражданств)\b")

TOPIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "residence": _rx(r"\b(внж|пмж|вид\s+на\s+жительство|резиден)\b"),
    "citizenship": _rx(r"\b(гражданств|паспорт)\b"),
    "digital_nomad": _rx(r"\b(digital\s+nomad|номадск\w*\s+виз|цифров\w*\s+кочевник)\b"),
    "study": _rx(r"\b(учебн\w*\s+виз|магистратур|университет|языков\w*\s+курс)\b"),
    "work": _rx(r"\b(blue\s*card|голуб\w*\s+карт|рабоч\w*\s+виз|оффер|релокейт)\b"),
    "family": _rx(r"\b(семь[яеию]|супруг|женой|мужем|ребен|детьм|воссоединен)\b"),
    "visa": _rx(r"\b(виз[аыеу]|консульств)\b"),
}

COUNTRY_PATTERNS: dict[str, re.Pattern[str]] = {
    "Испания": _rx(r"\b(испан(?:ия|ии|ию|ией)|spain)\b"),
    "Португалия": _rx(r"\b(португал(?:ия|ии|ию|ией)|portugal)\b"),
    "Германия": _rx(r"\b(герман(?:ия|ии|ию|ией)|germany)\b"),
    "Италия": _rx(r"\b(итал(?:ия|ии|ию|ией)|italy)\b"),
    "Франция": _rx(r"\b(франц(?:ия|ии|ию|ией)|france)\b"),
    "Нидерланды": _rx(r"\b(нидерланд|голланди|netherlands)\b"),
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("ё", "е").replace("Ё", "Е")).strip()


def score_text(text: str) -> ScoreResult:
    normalized = normalize_text(text)
    reasons: list[ScoreReason] = []

    for rule in POSITIVE_RULES:
        if rule.pattern.search(normalized):
            reasons.append(ScoreReason(rule.name, rule.points, rule.description))

    for rule in NEGATIVE_RULES:
        if rule.pattern.search(normalized):
            reasons.append(ScoreReason(rule.name, rule.points, rule.description))

    if POLITICAL_PATTERN.search(normalized) and not MIGRATION_PATTERN.search(normalized):
        reasons.append(
            ScoreReason(
                "politics_without_migration",
                -5,
                "политический контекст без явного миграционного запроса",
            )
        )

    topics = tuple(name for name, pattern in TOPIC_PATTERNS.items() if pattern.search(normalized))
    countries = tuple(
        name for name, pattern in COUNTRY_PATTERNS.items() if pattern.search(normalized)
    )
    return ScoreResult(
        score=sum(reason.points for reason in reasons),
        topics=topics,
        countries=countries,
        reasons=tuple(reasons),
    )


def excerpt(text: str, max_chars: int) -> str:
    normalized = normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"
