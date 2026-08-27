"""Stable replay ordering independent of input file order."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from catalyst.domain.models import EconomicEvent
from catalyst.replay.models import RawBar, RawTick, require_utc


class ClockItemKind(StrEnum):
    EVENT = "event"
    BAR_CLOSE = "bar_close"
    TICK = "tick"


_KIND_PRIORITY = {
    ClockItemKind.EVENT: 0,
    ClockItemKind.BAR_CLOSE: 1,
    ClockItemKind.TICK: 2,
}


@dataclass(frozen=True, slots=True)
class ClockItem:
    timestamp: datetime
    kind: ClockItemKind
    symbol: str
    source_sequence: int
    payload: EconomicEvent | RawBar | RawTick

    def __post_init__(self) -> None:
        require_utc(self.timestamp, "clock timestamp")
        if not self.symbol.strip():
            raise ValueError("clock symbol must not be empty")
        if type(self.source_sequence) is not int or self.source_sequence < 0:
            raise ValueError("clock source_sequence must be a non-negative integer")


class ReplayClock:
    """Merge events, completed bars and ticks using one total ordering."""

    def timeline(
        self,
        event: EconomicEvent,
        ticks: tuple[RawTick, ...],
        bars: tuple[RawBar, ...],
    ) -> tuple[ClockItem, ...]:
        items = [
            ClockItem(
                event.scheduled_at,
                ClockItemKind.EVENT,
                event.eligible_symbols[0],
                0,
                event,
            )
        ]
        items.extend(
            ClockItem(
                bar.closed_at,
                ClockItemKind.BAR_CLOSE,
                bar.symbol,
                bar.source_sequence,
                bar,
            )
            for bar in bars
        )
        items.extend(
            ClockItem(
                tick.timestamp,
                ClockItemKind.TICK,
                tick.symbol,
                tick.source_sequence,
                tick,
            )
            for tick in ticks
        )
        return tuple(
            sorted(
                items,
                key=lambda item: (
                    item.timestamp,
                    _KIND_PRIORITY[item.kind],
                    item.symbol,
                    item.source_sequence,
                ),
            )
        )

    @staticmethod
    def ticks(ticks: tuple[RawTick, ...], symbol: str) -> tuple[RawTick, ...]:
        return tuple(
            sorted(
                (tick for tick in ticks if tick.symbol == symbol),
                key=lambda tick: (tick.timestamp, tick.source_sequence),
            )
        )
