"""Scheduled-event feed boundary."""

from datetime import datetime
from typing import Protocol, Sequence

from catalyst.domain.models import EconomicEvent


class EventFeedPort(Protocol):
    def events_between(self, start: datetime, end: datetime) -> Sequence[EconomicEvent]:
        """Return normalized events ordered by UTC time and stable ID."""

        ...
