from __future__ import annotations

from abc import ABC, abstractmethod

from data.clients.schemas import EventSummary, Match, TeamInfo


class SourceConnector(ABC):
    """Abstract interface for external source connectors."""

    @abstractmethod
    def fetch_event_list(self, year: int | None = None) -> list[EventSummary]:
        """Fetch a list of events for the current or specified season."""

    @abstractmethod
    def fetch_event_matches(self, event_key: str) -> list[Match]:
        """Fetch match metadata for the given event."""

    @abstractmethod
    def fetch_team_info(self, team_number: int) -> TeamInfo:
        """Fetch the team profile for the given team number."""
