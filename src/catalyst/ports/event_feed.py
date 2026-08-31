"""Scheduled-event feed boundary and auditable source record."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from catalyst.domain.models import EconomicEvent
from catalyst.domain.serialization import sha256_canonical


@dataclass(frozen=True, slots=True)
class SourceEventRecord:
    """One normalized event plus the exact ordered fields supplied by its source."""

    event: EconomicEvent
    source_row_number: int
    raw_fields: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.source_row_number < 2:
            raise ValueError("source_row_number must include the header row")
        if not self.raw_fields:
            raise ValueError("raw_fields must not be empty")
        names = tuple(name for name, _ in self.raw_fields)
        if any(not name for name in names):
            raise ValueError("raw field names must not be empty")
        if len(set(names)) != len(names):
            raise ValueError("raw field names must be unique")
        if any(not isinstance(value, str) for _, value in self.raw_fields):
            raise ValueError("raw field values must be strings")

    @property
    def raw_hash(self) -> str:
        return sha256_canonical({"fields": self.raw_fields})

    @property
    def normalized_hash(self) -> str:
        return sha256_canonical(self.event)

    def raw_mapping(self) -> dict[str, str]:
        return dict(self.raw_fields)


class EventFeedPort(Protocol):
    def events_between(self, start: datetime, end: datetime) -> Sequence[EconomicEvent]:
        """Return normalized events ordered by UTC time and stable ID."""

        ...


class AuditableEventFeedPort(EventFeedPort, Protocol):
    def records_between(self, start: datetime, end: datetime) -> Sequence[SourceEventRecord]:
        """Return source-preserving records ordered by UTC time and stable ID."""

        ...
