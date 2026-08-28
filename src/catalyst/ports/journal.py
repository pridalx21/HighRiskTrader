"""Append-only journal boundary used by durable demo execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from re import fullmatch
from typing import Any, Protocol

from catalyst.domain.models import TradePlan


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


class JournalEntryKind(StrEnum):
    EVENT = "event"
    DECISION = "decision"
    ORDER = "order"
    FILL = "fill"
    STATE_TRANSITION = "state_transition"
    HEARTBEAT = "heartbeat"
    RECONCILIATION = "reconciliation"


class OrderIntentState(StrEnum):
    RESERVED = "reserved"
    SUBMITTING = "submitting"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"
    RECONCILED = "reconciled"


@dataclass(frozen=True, slots=True)
class OrderIntentRecord:
    idempotency_key: str
    event_id: str
    decision_id: str
    created_at: datetime
    plan_json: str
    plan_hash: str
    latest_state: OrderIntentState

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.idempotency_key, self.event_id, self.decision_id)
        ):
            raise ValueError("order intent identifiers must not be empty")
        _require_utc(self.created_at, "created_at")
        if not self.plan_json.strip():
            raise ValueError("plan_json must not be empty")
        if fullmatch(r"[0-9a-f]{64}", self.plan_hash) is None:
            raise ValueError("plan_hash must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class JournalEntryRecord:
    sequence: int
    entry_id: str
    kind: JournalEntryKind
    occurred_at: datetime
    event_id: str | None
    decision_id: str | None
    idempotency_key: str | None
    configuration_hash: str | None
    software_version: str
    payload_json: str
    payload_hash: str
    previous_hash: str
    entry_hash: str

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("journal sequence must be positive")
        if (
            not self.entry_id.strip()
            or not self.software_version.strip()
            or not self.payload_json.strip()
        ):
            raise ValueError("journal identifiers and payload must not be empty")
        _require_utc(self.occurred_at, "occurred_at")
        for field_name in ("payload_hash", "previous_hash", "entry_hash"):
            value = getattr(self, field_name)
            if fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        if (
            self.configuration_hash is not None
            and fullmatch(r"[0-9a-f]{64}", self.configuration_hash) is None
        ):
            raise ValueError("configuration_hash must be a lowercase SHA-256 digest")


class JournalPort(Protocol):
    @property
    def healthy(self) -> bool:
        """Return whether the opened journal has passed integrity checks."""

        ...

    def reserve_order_intent(self, plan: TradePlan, occurred_at: datetime) -> bool:
        """Persist one idempotency key before submission; return false if it exists."""

        ...

    def record_order_state(
        self,
        *,
        idempotency_key: str,
        event_id: str,
        decision_id: str,
        state: OrderIntentState,
        occurred_at: datetime,
        details: Mapping[str, Any],
    ) -> bool:
        """Append a sanitized order lifecycle state."""

        ...

    def record_reconciliation_state(
        self,
        *,
        idempotency_key: str,
        event_id: str,
        decision_id: str,
        state: OrderIntentState,
        occurred_at: datetime,
        details: Mapping[str, Any],
    ) -> bool:
        """Append the explicit result of one read-only broker reconciliation."""

        ...

    def unresolved_order_intents(self) -> Sequence[OrderIntentRecord]:
        """Return intents that cannot safely be considered terminal after restart."""

        ...

    def order_intent_requires_reconciliation(self, idempotency_key: str) -> bool:
        """Return true unless the durable latest state is terminal."""

        ...
