"""Immutable risk-policy defaults."""

from dataclasses import dataclass
from decimal import Decimal

APPROVED_RISK_FRACTION = Decimal("0.05")


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    risk_fraction: Decimal = APPROVED_RISK_FRACTION
    maximum_daily_loss_r: Decimal = Decimal("3")
    maximum_consecutive_losses: int = 3
    maximum_active_risk_clusters: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.risk_fraction, Decimal):
            raise ValueError("risk_fraction must be Decimal")
        if not isinstance(self.maximum_daily_loss_r, Decimal):
            raise ValueError("maximum_daily_loss_r must be Decimal")
        if not Decimal("0") < self.risk_fraction <= APPROVED_RISK_FRACTION:
            raise ValueError("risk_fraction must be in (0, 0.05]")
        if not Decimal("0") < self.maximum_daily_loss_r <= Decimal("3"):
            raise ValueError("maximum_daily_loss_r must be in (0, 3]")
        if not 1 <= self.maximum_consecutive_losses <= 3:
            raise ValueError("maximum_consecutive_losses must be in [1, 3]")
        if self.maximum_active_risk_clusters != 1:
            raise ValueError("maximum_active_risk_clusters must equal 1 in the MVP")
