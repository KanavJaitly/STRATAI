from __future__ import annotations

from abc import ABC, abstractmethod


class SourceConnector(ABC):
    """Common contract for external source connectors.

    Each source's API shape differs too much to force identical fetch method
    signatures across connectors: TBA exposes events/matches/teams, while
    Statbotics exposes EPA-based match statistics and team-event metrics with
    entirely different fields. Requiring a fixed set of fetch_* methods here
    (as an earlier version of this interface did) just leaks one source's
    data model into what's supposed to be a source-agnostic contract. Each
    concrete connector instead defines its own fetch_* methods and models.

    What every connector genuinely shares is a stable `source_name` (used to
    tag landed payloads so the landing layer never has to know which
    connector produced them) and safe HTTP resource cleanup.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Stable identifier for this source, e.g. 'tba' or 'statbotics'."""

    @abstractmethod
    def close(self) -> None:
        """Release any underlying network resources."""

    def __enter__(self) -> "SourceConnector":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
