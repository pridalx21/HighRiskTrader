"""Broker boundary used by demo and later MT5 adapters."""

from dataclasses import dataclass
from typing import Protocol

from catalyst.domain.models import AccountSnapshot, BrokerContract, TradePlan


@dataclass(frozen=True, slots=True)
class OrderReceipt:
    accepted: bool
    client_order_id: str
    broker_order_id: str | None
    code: str
    message: str


class BrokerPort(Protocol):
    def account_snapshot(self) -> AccountSnapshot:
        """Return normalized current account state."""

        ...

    def contract_for(self, symbol: str) -> BrokerContract:
        """Return explicit broker contract metadata for one logical symbol."""

        ...

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt:
        """Submit one idempotent order that includes its protective stop."""

        ...
