from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import typer
from alembic.config import Config as AlembicConfig

from alembic import command
from migrai_telethon.config import Settings, get_settings
from migrai_telethon.repository import PostgresRepository, make_engine
from migrai_telethon.scanner import Scanner, ScanOptions
from migrai_telethon.scoring import score_text
from migrai_telethon.sheets import GoogleSheetsGateway, parse_source_rows
from migrai_telethon.telegram_reader import ReadOnlyTelegramReader

app = typer.Typer(help="MIGR.AI read-only Telegram research collector")
db_app = typer.Typer(help="Управление схемой PostgreSQL")
sources_app = typer.Typer(help="Управление источниками")
candidates_app = typer.Typer(help="Работа с найденными кандидатами")
app.add_typer(db_app, name="db")
app.add_typer(sources_app, name="sources")
app.add_typer(candidates_app, name="candidates")


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _alembic_config() -> AlembicConfig:
    root = Path(__file__).resolve().parents[2]
    return AlembicConfig(str(root / "alembic.ini"))


def _sheets(settings: Settings) -> GoogleSheetsGateway:
    if not settings.sheets_ready:
        raise typer.BadParameter("Заполните GOOGLE_SERVICE_ACCOUNT_FILE и GOOGLE_SPREADSHEET_ID")
    assert settings.google_service_account_file is not None
    assert settings.google_spreadsheet_id is not None
    return GoogleSheetsGateway(settings.google_service_account_file, settings.google_spreadsheet_id)


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Применить все миграции PostgreSQL."""
    command.upgrade(_alembic_config(), "head")


@db_app.command("current")
def db_current() -> None:
    """Показать текущую миграцию PostgreSQL."""
    command.current(_alembic_config(), verbose=True)


@app.command("score")
def score_command(text: str) -> None:
    """Локально объяснить rule-based скоринг сообщения."""
    result = score_text(text)
    typer.echo(
        json.dumps(
            {
                "score": result.score,
                "topics": result.topics,
                "countries": result.countries,
                "reasons": [
                    {
                        "rule": reason.rule,
                        "points": reason.points,
                        "description": reason.description,
                    }
                    for reason in result.reasons
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@sources_app.command("sync")
def sync_sources() -> None:
    """Синхронизировать Telegram-источники из Google Sheets в PostgreSQL."""
    asyncio.run(_sync_sources())


async def _sync_sources() -> int:
    settings = get_settings()
    gateway = _sheets(settings)
    values = await gateway.read_values(settings.google_sources_range)
    sources = parse_source_rows(
        values,
        name_column=settings.sheets_source_name_column,
        type_column=settings.sheets_source_type_column,
        url_column=settings.sheets_source_url_column,
        status_column=settings.sheets_source_status_column,
        disabled_statuses=settings.sheets_disabled_statuses,
    )
    repository = PostgresRepository(make_engine(settings.database_url))
    try:
        count = await repository.upsert_sources(sources)
    finally:
        await repository.close()
    typer.echo(f"Синхронизировано источников: {count}")
    return count


@app.command("scan")
def scan_command(
    sync_sheets: bool = typer.Option(False, "--sync-sheets/--no-sync-sheets"),
    export_sheets: bool = typer.Option(False, "--export-sheets/--no-export-sheets"),
) -> None:
    """Выполнить один read-only проход по доступным Telegram-источникам."""
    asyncio.run(_scan(sync_sheets=sync_sheets, export_sheets=export_sheets))


async def _scan(*, sync_sheets: bool, export_sheets: bool) -> None:
    settings = get_settings()
    _configure_logging(settings)
    if not settings.telegram_ready:
        raise typer.BadParameter("Заполните TELEGRAM_API_ID и TELEGRAM_API_HASH")
    if sync_sheets:
        await _sync_sources()

    repository = PostgresRepository(make_engine(settings.database_url))
    try:
        sources = await repository.list_enabled_sources()
        assert settings.telegram_api_id is not None
        assert settings.telegram_api_hash is not None
        async with ReadOnlyTelegramReader(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            session_path=settings.telegram_session_path,
            flood_sleep_threshold=settings.telegram_flood_sleep_threshold_seconds,
            history_limit=settings.scan_history_limit,
            incremental_limit=settings.scan_incremental_limit,
            wait_time=settings.scan_wait_time_seconds,
            comments_limit=settings.comments_limit_per_post,
            reaction_users_limit=settings.reaction_users_limit,
        ) as telegram:
            scanner = Scanner(
                telegram,
                repository,
                ScanOptions(
                    score_threshold=settings.signal_score_threshold,
                    excerpt_max_chars=settings.signal_excerpt_max_chars,
                    comments_enabled=settings.comments_enabled,
                    comments_post_min_score=settings.comments_post_min_score,
                    reactions_enabled=settings.reactions_enabled,
                    reaction_signal_score=settings.reaction_signal_score,
                    reaction_post_min_score=settings.reaction_post_min_score,
                ),
            )
            stats = await scanner.scan(sources)
        typer.echo(
            f"Источников: {stats.sources}; сообщений: {stats.messages_seen}; "
            f"комментариев: {stats.comments_seen}; "
            f"сигналов: {stats.message_signals_saved}; "
            f"реакций: {stats.reaction_signals_saved}"
        )
        if export_sheets:
            await _export_candidates(settings, repository)
    finally:
        await repository.close()


@candidates_app.command("export")
def export_candidates() -> None:
    """Выгрузить ещё не экспортированных кандидатов в Google Sheets."""
    asyncio.run(_export_candidates_command())


async def _export_candidates_command() -> None:
    settings = get_settings()
    repository = PostgresRepository(make_engine(settings.database_url))
    try:
        await _export_candidates(settings, repository)
    finally:
        await repository.close()


async def _export_candidates(settings: Settings, repository: PostgresRepository) -> None:
    gateway = _sheets(settings)
    candidates = await repository.list_candidates_for_export(
        min_score=settings.candidate_export_min_score
    )
    count = await gateway.append_candidates(settings.google_candidates_range, candidates)
    await repository.mark_exported([candidate.telegram_user_id for candidate in candidates])
    typer.echo(f"Экспортировано кандидатов: {count}")


@app.command("doctor")
def doctor() -> None:
    """Проверить наличие обязательных настроек без внешних подключений."""
    settings = get_settings()
    checks = {
        "database_url": bool(settings.database_url),
        "telegram_credentials": settings.telegram_ready,
        "google_sheets": settings.sheets_ready,
        "session_ignored_by_git": True,
        "telegram_mode": "read-only",
    }
    typer.echo(json.dumps(checks, ensure_ascii=False, indent=2))
