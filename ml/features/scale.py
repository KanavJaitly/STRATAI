"""Causal season scoring scale for M5 v2's feature normalization (decision D16 §1.2).

S(Y, t) = population SD of every official alliance score (score_red and
score_blue) in completed matches of season Y, all events, with
scheduled_time strictly before t -- defined only when at least
MIN_ALLIANCE_SCORES such scores exist, otherwise absent (None). S(Y, None)
means the whole season, used only for a season that ended before the one
being predicted.

Read from the canonical matches table only. A ScaleLookup loads each season's
score timeline once and answers each query with a binary search over exact
integer prefix sums, so results are exact and deterministic. A lookup is
meant to live for one feature build (one frame build, or one feature
request), never across database changes.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime

from database.connection import Database

MIN_ALLIANCE_SCORES = 200

_TIMELINE_SQL = """
SELECT scheduled_time, score_red, score_blue
FROM matches
WHERE season = %s AND scheduled_time IS NOT NULL AND score_red IS NOT NULL AND score_blue IS NOT NULL
ORDER BY scheduled_time, match_key
"""


class _Timeline:
    def __init__(self, rows: list[tuple]) -> None:
        self.times = [row[0] for row in rows]
        self.count = [0]
        self.total = [0]
        self.squares = [0]
        for _, red, blue in rows:
            self.count.append(self.count[-1] + 2)
            self.total.append(self.total[-1] + red + blue)
            self.squares.append(self.squares[-1] + red * red + blue * blue)

    def scale(self, before: datetime | None) -> float | None:
        index = len(self.times) if before is None else bisect_left(self.times, before)
        n, s, q = self.count[index], self.total[index], self.squares[index]
        if n < MIN_ALLIANCE_SCORES:
            return None
        return math.sqrt((n * q - s * s) / (n * n))  # exact integer numerator: population variance


class ScaleLookup:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._timelines: dict[int, _Timeline] = {}
        self._event_seasons: dict[str, int | None] = {}

    def season_scale(self, season: int, before: datetime | None) -> float | None:
        if season not in self._timelines:
            with self._database.cursor() as cursor:
                cursor.execute(_TIMELINE_SQL, (season,))
                self._timelines[season] = _Timeline(cursor.fetchall())
        return self._timelines[season].scale(before)

    def event_season(self, event_key: str) -> int | None:
        if event_key not in self._event_seasons:
            with self._database.cursor() as cursor:
                cursor.execute("SELECT season FROM events WHERE event_key = %s", (event_key,))
                row = cursor.fetchone()
            self._event_seasons[event_key] = None if row is None else row[0]
        return self._event_seasons[event_key]

    def feature_scales(self, season: int, as_of: datetime, epa_source_event_key: str | None) -> tuple[float | None, float | None]:
        """(score_scale, epa_scale) for one team snapshot (D16 §1.2)."""
        score_scale = self.season_scale(season, as_of)
        if epa_source_event_key is None:
            return score_scale, None
        source_season = self.event_season(epa_source_event_key)
        if source_season is None:
            return score_scale, None
        if source_season == season:
            return score_scale, score_scale
        if source_season < season:
            return score_scale, self.season_scale(source_season, None)
        return score_scale, None  # a later-season source cannot occur under D13; never normalize with it
