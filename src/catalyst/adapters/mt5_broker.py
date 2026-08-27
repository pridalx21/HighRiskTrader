"""Deliberately non-executable MT5 adapter placeholder.

Implement this file only in Phase 4 after replay, journaling, idempotency, and
demo-account contracts pass. Keeping the placeholder fail-closed prevents the
starter archive from sending any broker order.
"""

from catalyst.domain.models import AccountSnapshot, BrokerContract, TradePlan
from catalyst.ports.broker import OrderReceipt


class MT5DemoBroker:
    def account_snapshot(self) -> AccountSnapshot:
        raise RuntimeError("MT5 demo adapter is not implemented; complete Phase 4")

    def contract_for(self, symbol: str) -> BrokerContract:
        del symbol
        raise RuntimeError("MT5 contract metadata is disabled in the starter")

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt:
        del plan
        raise RuntimeError("MT5 order submission is disabled in the starter")
