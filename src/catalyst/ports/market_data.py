"""Normalized market-data boundary."""

from datetime import datetime
from typing import Protocol

from catalyst.domain.models import MarketSnapshot


class MarketDataPort(Protocol):
    def snapshot(self, symbol: str, at: datetime) -> MarketSnapshot:
        """Return a strategy-ready, reconstructable market snapshot."""

        ...
