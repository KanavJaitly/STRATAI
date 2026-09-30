"""The per-match EPA loop (spec §5; reference models/template.py:54-99).

EpaEngine holds one season's state (every team's rating vector and qualifying
match count) and advances it one prepared match at a time, strictly in
processing order. Each step records the ratings of all six teams before the
match, the prediction made from those ratings alone, and the ratings after.
Because a step reads only the current state and the match being processed,
and the engine refuses a match that is not later than the previous one, a
rating recorded before match N cannot depend on match N or anything after it
(the season statistics are the documented exception; see year_stats).

The state can be snapshotted to plain JSON-able data and restored, and a
restored engine continues bit-identically (tests/test_ratings_epa_determinism.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ml.ratings.epa.adapters import actual_vector
from ml.ratings.epa.constants import ELIM_WEIGHT, EPA_FIELD_NAMES, NO_FOUL, RP_INDICES
from ml.ratings.epa.math import (
    add_observation,
    alliance_sum,
    attribution,
    percent,
    post_process_breakdown,
    predicted_rps,
    win_probability,
)
from ml.ratings.epa.rounding import python_round, reference_round
from ml.ratings.epa.validation import PreparedMatch
from ml.ratings.epa.year_stats import YearStats

Vector = tuple[float, ...]


def as_vector(array: np.ndarray) -> Vector:
    return tuple(float(x) for x in array)


def recorded_epas(vector: Vector) -> dict[str, float]:
    """pre_record_team / post_record_team's returned dict (main.py:174-239)."""
    rounded = np.round(np.array(vector, dtype=np.float64), 2)
    out: dict[str, float] = {}
    for i, name in enumerate(EPA_FIELD_NAMES):
        out[name] = python_round(vector[i], 4) if i in RP_INDICES else float(rounded[i])
    return out


@dataclass(frozen=True)
class MatchRecord:
    """Everything the engine computed for one match, unrounded."""

    match_key: str
    event_key: str
    time: int
    week: int
    comp_level: str
    elim: bool
    status: str
    red_teams: tuple[int, ...]
    blue_teams: tuple[int, ...]
    win_prob: float
    red_score: float  # predicted no-foul score
    blue_score: float
    red_score_with_fouls: float
    blue_score_with_fouls: float
    red_rps: tuple[float, float, float]
    blue_rps: tuple[float, float, float]
    pre: dict[int, Vector]
    post: dict[int, Vector] | None  # None when upcoming; equal to pre when skipped

    def reference_rounded(self, season: int) -> dict[str, Any]:
        """The values the reference stores for this match (main.py:241-257, template.py:64-99)."""
        out: dict[str, Any] = {
            "epa_win_prob": reference_round(self.win_prob, 4),
            "epa_winner": "red" if self.win_prob >= 0.5 else "blue",
            "epa_red_score_pred": reference_round(self.red_score_with_fouls, 2),
            "epa_blue_score_pred": reference_round(self.blue_score_with_fouls, 2),
        }
        rp_count = 3 if season >= 2025 else 2
        for i in range(rp_count):
            out[f"epa_red_rp_{i + 1}_pred"] = reference_round(self.red_rps[i] or 0, 4)
            out[f"epa_blue_rp_{i + 1}_pred"] = reference_round(self.blue_rps[i] or 0, 4)
        out["pre_epas"] = {str(t): recorded_epas(v) for t, v in sorted(self.pre.items())}
        out["epas"] = None if self.post is None else {str(t): recorded_epas(v) for t, v in sorted(self.post.items())}
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_key": self.match_key,
            "event_key": self.event_key,
            "time": self.time,
            "week": self.week,
            "comp_level": self.comp_level,
            "elim": self.elim,
            "status": self.status,
            "red_teams": list(self.red_teams),
            "blue_teams": list(self.blue_teams),
            "win_prob": self.win_prob,
            "red_score": self.red_score,
            "blue_score": self.blue_score,
            "red_score_with_fouls": self.red_score_with_fouls,
            "blue_score_with_fouls": self.blue_score_with_fouls,
            "red_rps": list(self.red_rps),
            "blue_rps": list(self.blue_rps),
            "pre": {str(t): list(v) for t, v in sorted(self.pre.items())},
            "post": None if self.post is None else {str(t): list(v) for t, v in sorted(self.post.items())},
        }


class EpaEngine:
    """One season's rating state, advanced one match at a time."""

    def __init__(
        self,
        stats: YearStats,
        ratings: dict[int, np.ndarray],
        counts: dict[int, int] | None = None,
        processed: int = 0,
        last_position: tuple[int, str] | None = None,
    ) -> None:
        self.stats = stats
        self.season = stats.season
        self._ratings = {team: np.array(v, dtype=np.float64) for team, v in ratings.items()}
        self._counts = {team: 0 for team in self._ratings} if counts is None else dict(counts)
        self.processed = processed
        self.last_position = last_position

    def rating(self, team: int) -> Vector:
        return as_vector(self._ratings[team])

    def qual_count(self, team: int) -> int:
        return self._counts[team]

    def ratings(self) -> dict[int, Vector]:
        return {team: as_vector(v) for team, v in sorted(self._ratings.items())}

    def process(self, match: PreparedMatch) -> MatchRecord:
        """Predict, then (when completed and not skipped) attribute and update."""
        position = (match.time, match.match_key)
        if self.last_position is not None and position <= self.last_position:
            raise ValueError(f"{match.match_key} at {position} is not after {self.last_position}")
        unknown = [t for t in match.teams if t not in self._ratings]
        if unknown:
            raise KeyError(f"{match.match_key}: teams {unknown} have no starting rating")

        season = self.season
        red_ratings = [self._ratings[t] for t in match.red_teams]
        blue_ratings = [self._ratings[t] for t in match.blue_teams]
        red_pred = post_process_breakdown(season, alliance_sum(red_ratings), alliance_sum(blue_ratings))
        blue_pred = post_process_breakdown(season, alliance_sum(blue_ratings), alliance_sum(red_ratings))
        red_score, blue_score = red_pred[NO_FOUL], blue_pred[NO_FOUL]
        win_prob = win_probability(red_score, blue_score, self.stats.score_sd)
        foul_rate = self.stats.foul_rate()
        pre = {t: as_vector(self._ratings[t]) for t in match.teams}

        post: dict[int, Vector] | None = None
        if match.completed:
            if match.skip_code is None:
                self._update(match, red_pred, blue_pred)
            post = {t: as_vector(self._ratings[t]) for t in match.teams}

        self.processed += 1
        self.last_position = position
        return MatchRecord(
            match_key=match.match_key,
            event_key=match.event_key,
            time=match.time,
            week=match.week,
            comp_level=match.comp_level,
            elim=match.elim,
            status=match.status,
            red_teams=match.red_teams,
            blue_teams=match.blue_teams,
            win_prob=float(win_prob),
            red_score=float(red_score),
            blue_score=float(blue_score),
            red_score_with_fouls=float(red_score * (1 + foul_rate)),
            blue_score_with_fouls=float(blue_score * (1 + foul_rate)),
            red_rps=tuple(float(x) for x in predicted_rps(season, red_pred)),  # type: ignore[arg-type]
            blue_rps=tuple(float(x) for x in predicted_rps(season, blue_pred)),  # type: ignore[arg-type]
            pre=pre,
            post=post,
        )

    def _update(self, match: PreparedMatch, red_pred: np.ndarray, blue_pred: np.ndarray) -> None:
        red_actual = actual_vector(match.red)  # type: ignore[arg-type]
        blue_actual = actual_vector(match.blue)  # type: ignore[arg-type]
        red_err = red_actual - red_pred
        blue_err = blue_actual - blue_pred
        # every attribution is taken from the pre-match ratings before any update (main.py:140-165)
        attributions: list[tuple[int, np.ndarray]] = []
        for teams, my_err, opp_err in ((match.red_teams, red_err, blue_err), (match.blue_teams, blue_err, red_err)):
            for team in teams:
                attributions.append((team, attribution(self.season, self._ratings[team], my_err, opp_err, match.elim)))
        weight = ELIM_WEIGHT if match.elim else 1
        for team, attrib in attributions:
            step = percent(self._counts[team])
            self._ratings[team] = add_observation(self._ratings[team], attrib, step, weight)
            if not match.elim:
                self._counts[team] += 1

    def snapshot(self) -> dict[str, Any]:
        """Plain data that from_snapshot restores exactly (floats round-trip through repr)."""
        return {
            "stats": self.stats.to_dict(),
            "ratings": {str(t): list(v) for t, v in self.ratings().items()},
            "counts": {str(t): n for t, n in sorted(self._counts.items())},
            "processed": self.processed,
            "last_position": None if self.last_position is None else list(self.last_position),
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> EpaEngine:
        last = data["last_position"]
        return cls(
            stats=YearStats.from_dict(data["stats"]),
            ratings={int(t): np.array(v, dtype=np.float64) for t, v in data["ratings"].items()},
            counts={int(t): int(n) for t, n in data["counts"].items()},
            processed=int(data["processed"]),
            last_position=None if last is None else (int(last[0]), str(last[1])),
        )

