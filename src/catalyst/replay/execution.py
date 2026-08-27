"""Deterministic executable-side replay fill model."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from catalyst.domain.enums import Direction
from catalyst.domain.models import BrokerContract, TradePlan
from catalyst.replay.clock import ReplayClock
from catalyst.replay.models import (
    ExecutionResult,
    ExecutionScenario,
    ExecutionStatus,
    RawTick,
)

ZERO = Decimal("0")


class ReplayExecutionModel:
    """Apply explicit latency, price tolerance, rejection and partial fills."""

    def execute(
        self,
        plan: TradePlan,
        ticks: tuple[RawTick, ...],
        contract: BrokerContract,
        scenario: ExecutionScenario,
    ) -> ExecutionResult:
        if plan.symbol != contract.symbol:
            raise ValueError("plan and contract symbols must match")
        if scenario.maximum_adverse_slippage_ticks > contract.slippage_ticks:
            raise ValueError(
                "execution slippage limit exceeds the risk-sized contract allowance"
            )
        if plan.quantity % contract.volume_step != ZERO:
            raise ValueError("requested quantity must align to volume step")
        eligible_at = plan.created_at + timedelta(
            milliseconds=scenario.latency_milliseconds
        )
        quote = next(
            (
                tick
                for tick in ReplayClock.ticks(ticks, plan.symbol)
                if tick.timestamp >= eligible_at
            ),
            None,
        )
        if quote is None:
            return self._unfilled(
                plan,
                ExecutionStatus.MISSED,
                "NO_EXECUTABLE_QUOTE",
                "no executable quote exists after the configured latency",
            )
        if scenario.rejection_code is not None:
            return self._unfilled(
                plan,
                ExecutionStatus.REJECTED,
                scenario.rejection_code,
                "the deterministic execution scenario rejected the order",
                spread=quote.spread,
            )

        fill_price = quote.ask if plan.direction is Direction.LONG else quote.bid
        adverse = self._adverse_ticks(plan, fill_price, contract.tick_size)
        if adverse > scenario.maximum_adverse_slippage_ticks:
            return self._unfilled(
                plan,
                ExecutionStatus.MISSED,
                "ADVERSE_SLIPPAGE_LIMIT",
                "executable quote exceeded the adverse slippage limit",
                spread=quote.spread,
                adverse=adverse,
            )

        raw_quantity = plan.quantity * scenario.fill_fraction
        step_count = (raw_quantity / contract.volume_step).to_integral_value(
            rounding=ROUND_FLOOR
        )
        filled_quantity = step_count * contract.volume_step
        if filled_quantity < contract.volume_minimum:
            return self._unfilled(
                plan,
                ExecutionStatus.MISSED,
                "PARTIAL_FILL_BELOW_MINIMUM",
                "step-rounded partial quantity is below the broker minimum",
                spread=quote.spread,
                adverse=adverse,
            )
        status = (
            ExecutionStatus.FILLED
            if filled_quantity == plan.quantity
            else ExecutionStatus.PARTIAL
        )
        return ExecutionResult(
            status=status,
            code="FILLED" if status is ExecutionStatus.FILLED else "PARTIAL_FILL",
            reason=(
                "order filled at the first executable quote"
                if status is ExecutionStatus.FILLED
                else "order partially filled after volume-step rounding"
            ),
            requested_quantity=plan.quantity,
            filled_quantity=filled_quantity,
            intended_entry=plan.entry,
            fill_price=fill_price,
            fill_timestamp=quote.timestamp,
            observed_spread=quote.spread,
            adverse_slippage_ticks=adverse,
            commission=contract.commission_per_volume * filled_quantity,
        )

    @staticmethod
    def _adverse_ticks(
        plan: TradePlan,
        fill_price: Decimal,
        tick_size: Decimal,
    ) -> Decimal:
        if plan.direction is Direction.LONG:
            adverse_price = max(fill_price - plan.entry, ZERO)
        else:
            adverse_price = max(plan.entry - fill_price, ZERO)
        return adverse_price / tick_size

    @staticmethod
    def _unfilled(
        plan: TradePlan,
        status: ExecutionStatus,
        code: str,
        reason: str,
        *,
        spread: Decimal | None = None,
        adverse: Decimal | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            status=status,
            code=code,
            reason=reason,
            requested_quantity=plan.quantity,
            filled_quantity=ZERO,
            intended_entry=plan.entry,
            fill_price=None,
            fill_timestamp=None,
            observed_spread=spread,
            adverse_slippage_ticks=adverse,
            commission=ZERO,
        )
