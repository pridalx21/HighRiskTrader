"""Broker wrapper that enforces the persistent local kill switch in the order path."""

from __future__ import annotations

from catalyst.controls import DemoExecutionControl, LocalKillSwitch
from catalyst.domain.models import AccountSnapshot, BrokerContract, TradePlan
from catalyst.ports.broker import OrderReceipt
from catalyst.ports.journal import OrderIntentRecord
from catalyst.ports.reconciliation import BrokerOrderLookup


class GuardedDemoBroker:
    """Delegate broker operations while refusing arm/submit when the latch is active."""

    def __init__(self, delegate: DemoExecutionControl, kill_switch: LocalKillSwitch) -> None:
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
        method = getattr(self.delegate, "account_snapshot", None)
        if method is None:
            raise RuntimeError("guarded broker delegate has no account_snapshot")
        return method()

    def contract_for(self, symbol: str) -> BrokerContract:
        method = getattr(self.delegate, "contract_for", None)
        if method is None:
            raise RuntimeError("guarded broker delegate has no contract_for")
        return method(symbol)

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt:
        if self.kill_switch.active:
            self.delegate.disarm()
            raise RuntimeError("persistent kill switch blocks demo order submission")
        method = getattr(self.delegate, "submit_bracket", None)
        if method is None:
            raise RuntimeError("guarded broker delegate has no submit_bracket")
        return method(plan)

    def lookup_order(self, intent: OrderIntentRecord) -> BrokerOrderLookup:
        method = getattr(self.delegate, "lookup_order", None)
        if method is None:
            raise RuntimeError("guarded broker delegate has no lookup_order")
        return method(intent)
