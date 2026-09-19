from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import timezone
from pathlib import Path
from typing import Any, cast

from google.oauth2 import service_account
from googleapiclient.discovery import build

from migrai_telethon.domain import CandidateExport, SourceInput, SourceType

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def normalize_source_type(value: str) -> SourceType | None:
    normalized = value.strip().lower()
    if normalized in {"чат tg", "чат", "telegram chat", "group", "группа"}:
        return SourceType.CHAT
    if normalized in {"канал tg", "канал", "telegram channel", "channel"}:
        return SourceType.CHANNEL
    return None


def parse_source_rows(
    values: Sequence[Sequence[str]],
    *,
    name_column: str,
    type_column: str,
    url_column: str,
    status_column: str,
    disabled_statuses: Sequence[str],
) -> list[SourceInput]:
    if not values:
        return []
    headers = [cell.strip() for cell in values[0]]
    positions = {header: index for index, header in enumerate(headers)}
    required = {name_column, type_column, url_column, status_column}
    missing = sorted(required - positions.keys())
    if missing:
        raise ValueError(
            f"В листе источников отсутствуют колонки: {', '.join(missing)}. "
            f"Найдены: {', '.join(headers)}"
        )

    disabled = {status.casefold() for status in disabled_statuses}
    sources: list[SourceInput] = []
    seen: set[str] = set()
    for row in values[1:]:
        padded = list(row) + [""] * (len(headers) - len(row))
        telegram_ref = padded[positions[url_column]].strip()
        source_type = normalize_source_type(padded[positions[type_column]])
        if not telegram_ref or not source_type or telegram_ref in seen:
            continue
        status = padded[positions[status_column]].strip()
        enabled = status.casefold() not in disabled
        sources.append(
            SourceInput(
                name=padded[positions[name_column]].strip() or telegram_ref,
                telegram_ref=telegram_ref,
                source_type=source_type,
                enabled=enabled,
            )
        )
        seen.add(telegram_ref)
    return sources


class GoogleSheetsGateway:
    def __init__(self, service_account_file: Path, spreadsheet_id: str) -> None:
        credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            str(service_account_file), scopes=SCOPES
        )
        self._service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._spreadsheet_id = spreadsheet_id

    async def read_values(self, range_name: str) -> list[list[str]]:
        def request() -> list[list[str]]:
            response = cast(
                dict[str, Any],
                self._service.spreadsheets()
                .values()
                .get(spreadsheetId=self._spreadsheet_id, range=range_name)
                .execute(),
            )
            return cast(list[list[str]], response.get("values", []))

        return await asyncio.to_thread(request)

    async def append_candidates(
        self, range_name: str, candidates: Sequence[CandidateExport]
    ) -> int:
        if not candidates:
            return 0
        rows = [self._candidate_row(candidate) for candidate in candidates]

        def request() -> Mapping[str, Any]:
            return cast(
                Mapping[str, Any],
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=range_name,
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": rows},
                )
                .execute(),
            )

        await asyncio.to_thread(request)
        return len(rows)

    @staticmethod
    def _candidate_row(candidate: CandidateExport) -> list[str | int]:
        username = (
            f"@{candidate.username}" if candidate.username else str(candidate.telegram_user_id)
        )
        profile = f"https://t.me/{candidate.username}" if candidate.username else ""
        detected = candidate.detected_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        return [
            username,
            candidate.display_name,
            candidate.status,
            candidate.source_name,
            candidate.message_link or profile,
            candidate.text_excerpt or "Реакция на релевантное сообщение",
            candidate.primary_topic or "",
            candidate.best_score,
            candidate.primary_country or "",
            detected,
            "",
            "",
        ]
