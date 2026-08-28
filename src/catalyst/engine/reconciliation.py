"""Read-only restart reconciliation for unresolved durable order intents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from catalyst.ports.journal import JournalPort, OrderIntentState
from catalyst.ports.reconciliation import (
    BrokerOrderLookup,
    BrokerOrderState,
    BrokerReconciliationPort,
)

_FOUND_STATES = {
    BrokerOrderState.FOUND_OPEN,
    BrokerOrderState.FOUND_FILLED,
    BrokerOrderState.FOUND_CLOSED,
}


@dataclass(frozen=True, slots=True)
class ReconciledIntent:
    idempotency_key: str
    lookup: BrokerOrderLookup


@dataclass(frozen=True, slots=True)
class RestartReconciliationReport:
    checked: tuple[ReconciledIntent, ...]
    unresolved_idempotency_keys: tuple[str, ...]
    can_request_manual_arm: bool
    auto_demo_armed: bool = False

    def __post_init__(self) -> None:
        if self.auto_demo_armed:
            raise ValueError("restart reconciliation must never auto-arm demo execution")
        if self.can_request_manual_arm and self.unresolved_idempotency_keys:
            raise ValueError("manual arm cannot be requested with unresolved intents")


class RestartReconciler:
    """Resolve known broker state and leave unknown state explicitly disarmed."""

    def __init__(self, journal: JournalPort, broker: BrokerReconciliationPort) -> None:
        self.journal = journal
        self.broker = broker

    def reconcile(self, *, occurred_at: datetime) -> RestartReconciliationReport:
        if not self.journal.healthy:
            raise RuntimeError("journal is not healthy; restart remains disarmed")
        checked: list[ReconciledIntent] = []
        for intent in self.journal.unresolved_order_intents():
            try:
                lookup = self.broker.lookup_order(intent)
            except Exception as exc:
                lookup = BrokerOrderLookup(
                    BrokerOrderState.UNKNOWN,
                    None,
                    f"reconciliation adapter failed with {type(exc).__name__}",
                )
            resolved = lookup.state in _FOUND_STATES
            self.journal.record_reconciliation_state(
                idempotency_key=intent.idempotency_key,
                event_id=intent.event_id,
                decision_id=intent.decision_id,
                state=(OrderIntentState.RECONCILED if resolved else OrderIntentState.UNCERTAIN),
                occurred_at=occurred_at,
                details={
                    "broker_order_id": lookup.broker_order_id,
                    "broker_state": lookup.state,
                    "reason": lookup.reason,
                    "resubmitted": False,
                },
            )
            checked.append(ReconciledIntent(intent.idempotency_key, lookup))

        unresolved = tuple(
            intent.idempotency_key for intent in self.journal.unresolved_order_intents()
        )
        return RestartReconciliationReport(
            checked=tuple(checked),
            unresolved_idempotency_keys=unresolved,
            can_request_manual_arm=not unresolved,
        )
