"""Strict, auditable manual-CSV event adapter."""

from __future__ import annotations

from csv import reader
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from re import fullmatch

from catalyst.domain.enums import EventImportance, EventStatus
from catalyst.domain.models import EconomicEvent
from catalyst.ports.event_feed import SourceEventRecord

CSV_HEADER = (
    "event_id",
    "name",
    "scheduled_at",
    "currency",
    "importance",
    "status",
    "eligible_symbols",
    "source",
    "actual",
    "consensus",
    "previous",
)

_IMPORTANCE = {
    "LOW": EventImportance.LOW,
    "MEDIUM": EventImportance.MEDIUM,
    "HIGH": EventImportance.HIGH,
}
_STATUS = {
    "SCHEDULED": EventStatus.SCHEDULED,
    "CANCELLED": EventStatus.CANCELLED,
    "AMBIGUOUS": EventStatus.AMBIGUOUS,
    "DUPLICATE": EventStatus.DUPLICATE,
    "STALE": EventStatus.STALE,
}


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


def _strict_text(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain a null byte")
    return value


def _parse_utc(value: str) -> datetime:
    raw = _strict_text(value, "scheduled_at")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("scheduled_at must be an ISO-8601 timestamp") from exc
    _require_utc(parsed, "scheduled_at")
    return parsed.astimezone(UTC)


def _validate_optional_decimal(value: str, field_name: str) -> None:
    if value == "":
        return
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a decimal string when present") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite when present")


def _parse_symbols(value: str) -> tuple[str, ...]:
    raw = _strict_text(value, "eligible_symbols")
    symbols = tuple(raw.split("|"))
    if any(fullmatch(r"[A-Z0-9][A-Z0-9._-]*", symbol) is None for symbol in symbols):
        raise ValueError("eligible_symbols must contain uppercase logical symbols")
    if len(set(symbols)) != len(symbols):
        raise ValueError("eligible_symbols must not contain duplicates")
    return symbols


class CsvEventFeed:
    """Load one exact manual-CSV schema without inference or wall-clock reads."""

    def __init__(self, records: tuple[SourceEventRecord, ...]) -> None:
        if not records:
            raise ValueError("CSV event feed requires at least one event")
        event_ids = tuple(record.event.event_id for record in records)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("CSV event_id values must be unique")
        self._records = tuple(
            sorted(records, key=lambda item: (item.event.scheduled_at, item.event.event_id))
        )

    @classmethod
    def load(cls, path: str | Path, *, ingested_at: datetime) -> CsvEventFeed:
        _require_utc(ingested_at, "ingested_at")
        csv_path = Path(path)
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(reader(handle, strict=True))
        except UnicodeDecodeError as exc:
            raise ValueError("event CSV must be UTF-8") from exc
        if not rows:
            raise ValueError("event CSV must not be empty")
        if tuple(rows[0]) != CSV_HEADER:
            raise ValueError("event CSV header does not match the required schema")

        records: list[SourceEventRecord] = []
        seen: set[str] = set()
        for row_number, row in enumerate(rows[1:], start=2):
            if len(row) != len(CSV_HEADER):
                raise ValueError(f"event CSV row {row_number} has the wrong field count")
            values = dict(zip(CSV_HEADER, row, strict=True))
            event_id = _strict_text(values["event_id"], "event_id")
            if fullmatch(r"[A-Z0-9][A-Z0-9_.:-]*", event_id) is None:
                raise ValueError("event_id contains unsupported characters")
            if event_id in seen:
                raise ValueError(f"duplicate event_id in CSV: {event_id}")
            seen.add(event_id)

            name = _strict_text(values["name"], "name")
            currency = _strict_text(values["currency"], "currency")
            if fullmatch(r"[A-Z]{3}", currency) is None:
                raise ValueError("currency must be a three-letter uppercase code")
            source = _strict_text(values["source"], "source")
            if source != "manual_csv":
                raise ValueError("Phase 3 CSV source must equal manual_csv")
            try:
                importance = _IMPORTANCE[values["importance"]]
            except KeyError as exc:
                raise ValueError("importance must be LOW, MEDIUM, or HIGH") from exc
            try:
                status = _STATUS[values["status"]]
            except KeyError as exc:
                raise ValueError("status is not a supported explicit event status") from exc
            for field_name in ("actual", "consensus", "previous"):
                _validate_optional_decimal(values[field_name], field_name)

            event = EconomicEvent(
                event_id=event_id,
                name=name,
                scheduled_at=_parse_utc(values["scheduled_at"]),
                ingested_at=ingested_at,
                currency=currency,
                importance=importance,
                status=status,
                eligible_symbols=_parse_symbols(values["eligible_symbols"]),
                source=source,
            )
            records.append(
                SourceEventRecord(
                    event=event,
                    source_row_number=row_number,
                    raw_fields=tuple(zip(CSV_HEADER, row, strict=True)),
                )
            )
        return cls(tuple(records))

    @property
    def records(self) -> tuple[SourceEventRecord, ...]:
        return self._records

    def records_between(
        self,
        start: datetime,
        end: datetime,
    ) -> tuple[SourceEventRecord, ...]:
        _require_utc(start, "start")
        _require_utc(end, "end")
        if end < start:
            raise ValueError("event range end must not precede start")
        return tuple(
            record for record in self._records if start <= record.event.scheduled_at <= end
        )

    def events_between(self, start: datetime, end: datetime) -> tuple[EconomicEvent, ...]:
        return tuple(record.event for record in self.records_between(start, end))
