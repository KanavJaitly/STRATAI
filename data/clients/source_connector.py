from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class SourceResponse(Generic[T]):
    """One source object, as both its untouched wire body and its validated model.

    Connectors return this instead of a bare model so the two are never confused:

      * `raw` is exactly what the API sent for this object -- every field,
        including ones no client model declares. This is what the landing layer
        stores and checksums, so a change in *any* field is detected as a new
        payload version and nothing is lost before it is persisted.
      * `parsed` is the validated model: typed access for control flow, with
        source-specific shapes normalized (Statbotics's nested `epa`/`record`
        objects are flattened by the model's own validator, for instance).

    Both come from the same response; `parsed` is a view of `raw`, never a
    replacement for it. Returning only the model is what previously let the
    pipeline land a lossy projection: any field the model did not declare was
    dropped before landing and was therefore invisible to change detection too.

    For list endpoints, connectors return one SourceResponse per *item* rather
    than one for the whole array, because the landing layer deduplicates per
    object and each object needs its own raw body.
    """

    raw: Any
    parsed: T


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
