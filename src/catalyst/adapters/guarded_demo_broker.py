"""Broker wrapper that enforces the persistent local kill switch in the order path."""

from __future__ import annotations

from typing import Protocol

from catalyst.controls import DemoExecutionControl, LocalKillSwitch
from catalyst.domain.models import AccountSnapshot, BrokerContract, TradePlan
from catalyst.ports.broker import OrderReceipt
from catalyst.ports.journal import OrderIntentRecord
from catalyst.ports.reconciliation import BrokerOrderLookup


class GuardedBrokerDelegate(DemoExecutionControl, Protocol):
    def account_snapshot(self) -> AccountSnapshot: ...

    def contract_for(self, symbol: str) -> BrokerContract: ...

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt: ...

    def lookup_order(self, intent: OrderIntentRecord) -> BrokerOrderLookup: ...


class GuardedDemoBroker:
    """Delegate broker operations while refusing arm/submit when the latch is active."""

    def __init__(self, delegate: GuardedBrokerDelegate, kill_switch: LocalKillSwitch) -> None:
        self.delegate = delegate
        self.kill_switch = kill_switch

    @property
    def armed(self) -> bool:
        return self.delegate.armed and not self.kill_switch.active

    def arm_demo_execution(self) -> None:
        if self.kill_switch.active:
            self.delegate.disarm()
            raise RuntimeError("persistent kill switch is active")
        self.delegate.arm_demo_execution()

    def disarm(self) -> None:
        self.delegate.disarm()

    def account_snapshot(self) -> AccountSnapshot:
        return self.delegate.account_snapshot()

    def contract_for(self, symbol: str) -> BrokerContract:
        return self.delegate.contract_for(symbol)

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt:
        if self.kill_switch.active:
            self.delegate.disarm()
            raise RuntimeError("persistent kill switch blocks demo order submission")
        return self.delegate.submit_bracket(plan)

    def lookup_order(self, intent: OrderIntentRecord) -> BrokerOrderLookup:
        return self.delegate.lookup_order(intent)
