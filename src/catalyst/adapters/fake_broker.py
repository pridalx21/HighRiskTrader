"""In-memory broker used for deterministic tests and demonstration."""

from catalyst.domain.enums import AccountMode
from catalyst.domain.models import AccountSnapshot, BrokerContract, TradePlan
from catalyst.ports.broker import OrderReceipt


class FakeDemoBroker:
    def __init__(
        self,
        account: AccountSnapshot,
        contracts: tuple[BrokerContract, ...],
    ) -> None:
        self._account = account
        self._orders: dict[str, TradePlan] = {}
        self._contracts = {contract.symbol: contract for contract in contracts}
        if len(self._contracts) != len(contracts):
            raise ValueError("fake broker contract symbols must be unique")
        if not self._contracts:
            raise ValueError("fake broker requires explicit contract metadata")

    @property
    def orders(self) -> tuple[TradePlan, ...]:
        return tuple(self._orders.values())

    def account_snapshot(self) -> AccountSnapshot:
        return self._account

    def contract_for(self, symbol: str) -> BrokerContract:
        try:
            return self._contracts[symbol]
        except KeyError as exc:
            raise LookupError(f"no broker contract metadata for {symbol}") from exc

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt:
        if self._account.mode is not AccountMode.DEMO:
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "DEMO_ONLY",
                "fake broker rejected a non-demo account",
            )
        if not self._account.connected:
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "BROKER_DISCONNECTED",
                "fake broker is disconnected",
            )
        if not plan.server_side_stop_required:
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "STOP_REQUIRED",
                "protective stop is missing",
            )
        contract = self._contracts.get(plan.symbol)
        if contract is None:
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "CONTRACT_UNKNOWN",
                "broker contract metadata is unavailable for the plan symbol",
            )
        if contract.account_currency.upper() != self._account.currency.upper():
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "ACCOUNT_CURRENCY_MISMATCH",
                "contract and account currencies do not match",
            )
        if plan.entry % contract.tick_size != 0 or plan.stop % contract.tick_size != 0:
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "PRICE_OFF_TICK_GRID",
                "entry or stop is not aligned to the broker tick size",
            )
        if (
            plan.quantity < contract.volume_minimum
            or plan.quantity > contract.volume_maximum
            or plan.quantity % contract.volume_step != 0
        ):
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "VOLUME_INVALID",
                "plan quantity violates broker volume limits or step",
            )
        if plan.decision_id in self._orders:
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "DUPLICATE_ORDER",
                "idempotency key was already submitted",
            )
        self._orders[plan.decision_id] = plan
        return OrderReceipt(
            True,
            plan.decision_id,
            f"FAKE-{len(self._orders):06d}",
            "ACCEPTED",
            "demo bracket accepted by fake broker",
        )
