"""Broker-neutral restart reconciliation boundary."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from catalyst.ports.journal import OrderIntentRecord


class BrokerOrderState(StrEnum):
    FOUND_OPEN = "found_open"
    FOUND_FILLED = "found_filled"
    FOUND_CLOSED = "found_closed"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BrokerOrderLookup:
    state: BrokerOrderState
    broker_order_id: str | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reconciliation reason must not be empty")
        found = self.state in {
            BrokerOrderState.FOUND_OPEN,
            BrokerOrderState.FOUND_FILLED,
            BrokerOrderState.FOUND_CLOSED,
        }
        if found and (self.broker_order_id is None or not self.broker_order_id.strip()):
            raise ValueError("found broker orders require a broker_order_id")
        if not found and self.broker_order_id is not None:
            raise ValueError("unresolved broker lookups must not invent an order ID")


class BrokerReconciliationPort(Protocol):
    def lookup_order(self, intent: OrderIntentRecord) -> BrokerOrderLookup:
        """Look up one durable intent without creating or resubmitting an order."""

        ...
