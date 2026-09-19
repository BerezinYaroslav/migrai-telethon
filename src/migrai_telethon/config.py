from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = "postgresql+asyncpg://migrai:migrai@localhost:5432/migrai"

    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_path: Path = Path("var/sessions/migrai-research")
    telegram_flood_sleep_threshold_seconds: int = Field(default=60, ge=0, le=86400)

    scan_history_limit: int = Field(default=500, ge=1, le=10000)
    scan_incremental_limit: int = Field(default=2000, ge=1, le=50000)
    scan_wait_time_seconds: float = Field(default=1.0, ge=0, le=60)
    signal_score_threshold: int = Field(default=5, ge=1, le=100)
    candidate_export_min_score: int = Field(default=5, ge=1, le=100)
    signal_excerpt_max_chars: int = Field(default=500, ge=50, le=2000)

    comments_enabled: bool = True
    comments_post_min_score: int = Field(default=5, ge=1, le=100)
    comments_limit_per_post: int = Field(default=200, ge=1, le=5000)
    reactions_enabled: bool = True
    reaction_signal_score: int = Field(default=1, ge=0, le=10)
    reaction_post_min_score: int = Field(default=5, ge=1, le=100)
    reaction_users_limit: int = Field(default=100, ge=1, le=1000)

    google_service_account_file: Path | None = None
    google_spreadsheet_id: str | None = None
    google_sources_range: str = "'Каналы и чаты'!A:Z"
    google_candidates_range: str = "'Потенциальные респонденты'!A:L"
    sheets_source_name_column: str = "Название"
    sheets_source_type_column: str = "Тип"
    sheets_source_url_column: str = "Ссылка"
    sheets_source_status_column: str = "Статус"
    sheets_disabled_statuses: tuple[str, ...] = ("Забанен", "Отключен", "Не использовать")

    log_level: str = "INFO"

    @field_validator("sheets_disabled_statuses", mode="before")
    @classmethod
    def parse_disabled_statuses(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash)

    @property
    def sheets_ready(self) -> bool:
        return bool(self.google_service_account_file and self.google_spreadsheet_id)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
