"""Fail-closed account assessment and broker-aware sizing."""

from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

from catalyst.domain.enums import AccountMode, ReasonCode
from catalyst.domain.models import AccountSnapshot, BrokerContract, PositionSize, RiskDecision
from catalyst.risk.policy import RiskPolicy


class RiskManager:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def assess(
        self,
        account: AccountSnapshot,
        now: datetime,
        maximum_snapshot_age_seconds: Decimal,
    ) -> RiskDecision:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware UTC")
        if now.utcoffset() != timedelta(0):
            raise ValueError("now must be normalized to UTC")
        if not isinstance(maximum_snapshot_age_seconds, Decimal):
            raise ValueError("maximum_snapshot_age_seconds must be Decimal")
        if (
            not maximum_snapshot_age_seconds.is_finite()
            or maximum_snapshot_age_seconds < 0
        ):
            raise ValueError("maximum_snapshot_age_seconds must be finite and non-negative")
        if not account.connected:
            return RiskDecision(
                False,
                ReasonCode.BROKER_DISCONNECTED,
                "broker connection is unavailable",
            )
        if account.mode is not AccountMode.DEMO:
            return RiskDecision(
                False,
                ReasonCode.DEMO_ONLY,
                "account is not positively identified as demo",
            )
        age_delta = now - account.timestamp
        age_seconds = Decimal(age_delta.days * 86_400 + age_delta.seconds)
        age_seconds += Decimal(age_delta.microseconds) / Decimal("1000000")
        if age_seconds < 0 or age_seconds > maximum_snapshot_age_seconds:
            return RiskDecision(
                False,
                ReasonCode.ACCOUNT_SNAPSHOT_STALE,
                "account snapshot is stale or timestamped in the future",
            )
        if account.active_risk_clusters >= self.policy.maximum_active_risk_clusters:
            return RiskDecision(
                False,
                ReasonCode.CLUSTER_LIMIT,
                "an active correlated risk cluster exists",
            )
        if account.consecutive_losses >= self.policy.maximum_consecutive_losses:
            return RiskDecision(
                False,
                ReasonCode.LOSS_STREAK_LOCK,
                "consecutive-loss lock is active",
            )

        day_r = account.day_start_equity * self.policy.risk_fraction
        daily_loss_limit = day_r * self.policy.maximum_daily_loss_r
        realized_loss = max(-account.daily_realized_pnl, Decimal("0"))
        daily_risk_used = realized_loss + account.open_worst_case_risk
        if daily_risk_used >= daily_loss_limit:
            return RiskDecision(
                False,
                ReasonCode.DAILY_LOSS_LOCK,
                "daily realized loss plus open worst-case risk reaches the limit",
            )

        risk_amount = account.equity * self.policy.risk_fraction
        if risk_amount <= 0 or not risk_amount.is_finite():
            return RiskDecision(
                False,
                ReasonCode.INVALID_RISK,
                "risk amount cannot be calculated",
            )
        return RiskDecision(
            True,
            ReasonCode.RISK_ALLOWED,
            "account risk checks pass",
            risk_amount,
        )

    @staticmethod
    def size_position(
        risk_amount: Decimal,
        entry: Decimal,
        stop: Decimal,
        contract: BrokerContract,
    ) -> PositionSize:
        values = (risk_amount, entry, stop)
        if any(not isinstance(value, Decimal) for value in values):
            raise ValueError("sizing inputs must be Decimal")
        if any(not value.is_finite() for value in values):
            raise ValueError("sizing inputs must be finite")
        if risk_amount <= 0 or entry <= 0 or stop <= 0:
            raise ValueError("sizing inputs must be positive")
        stop_distance = abs(entry - stop)
        if stop_distance == 0:
            raise ValueError("entry and stop must differ")
        if entry % contract.tick_size != 0 or stop % contract.tick_size != 0:
            raise ValueError("entry and stop must align to tick_size")

        stop_ticks = stop_distance / contract.tick_size
        base_loss_per_volume = (
            stop_ticks * contract.tick_value * contract.profit_to_account_rate
        )
        if not base_loss_per_volume.is_finite() or base_loss_per_volume <= 0:
            raise ValueError("base loss per volume is invalid")

        raw_quantity = risk_amount / base_loss_per_volume
        if not raw_quantity.is_finite() or raw_quantity <= 0:
            raise ValueError("calculated raw quantity is invalid")
        if raw_quantity > contract.volume_maximum:
            raise ValueError("calculated raw quantity exceeds volume_maximum")

        step_count = (raw_quantity / contract.volume_step).to_integral_value(
            rounding=ROUND_FLOOR
        )
        quantity = step_count * contract.volume_step
        if quantity < contract.volume_minimum:
            raise ValueError("rounded quantity is below volume_minimum")
        if quantity > contract.volume_maximum:
            raise ValueError("rounded quantity exceeds volume_maximum")

        slippage_loss_per_volume = (
            contract.slippage_ticks
            * contract.tick_value
            * contract.profit_to_account_rate
        )
        worst_case_loss_per_volume = (
            base_loss_per_volume
            + slippage_loss_per_volume
            + contract.commission_per_volume
        )
        maximum_loss = quantity * worst_case_loss_per_volume
        if not maximum_loss.is_finite() or maximum_loss <= 0:
            raise ValueError("recalculated maximum loss is invalid")
        if maximum_loss > risk_amount:
            raise ValueError("recalculated maximum loss exceeds permitted risk")
        return PositionSize(quantity=quantity, maximum_loss=maximum_loss)
