"""Reading real playoff data for the playoff track and P6-DM1 (point in time; outcomes are labels only).

- **Read:** an event's playoff matches with each side's teams and the TBA winner, its P5-M1 alliances, its latest
  qualification match (the selection moment) and its roster size.
- **Build:** PX-1 rows from those, with every exclusion counted by reason (`.agent/phase6/P6_M2_PX1_SPEC.md` §1).
- **Bracket rounds** always come from the approved ruleset passed in, never from code.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from data.alliances import Alliance, read_event_alliances
from data.rulesets import BracketFormat, RulesetError, SeasonRuleset
from database.connection import Database
from ml.features.assembler import TeamFeatures, build_team_features
from ml.playoffs.evaluation import PlayoffMatch
from ml.playoffs.px1 import PlayoffRow, map_side, selection_moment

PLAYOFF_SQL = """
SELECT m.match_key, m.event_key, m.competition_level, m.set_number, m.match_number, m.scheduled_time,
       m.winning_alliance,
       array_agg(mt.team_number ORDER BY mt.team_number) FILTER (WHERE mt.alliance_color = 'red'),
       array_agg(mt.team_number ORDER BY mt.team_number) FILTER (WHERE mt.alliance_color = 'blue')
FROM matches m JOIN match_teams mt USING (match_key)
WHERE m.season = %s AND m.competition_level IN ('semifinal', 'final')
GROUP BY m.match_key, m.event_key, m.competition_level, m.set_number, m.match_number, m.scheduled_time,
         m.winning_alliance
ORDER BY m.event_key, m.scheduled_time, m.match_key
"""
QUALIFICATION_SQL = """
SELECT m.event_key, max(m.scheduled_time), count(DISTINCT mt.team_number)
FROM matches m JOIN match_teams mt USING (match_key)
WHERE m.season = %s AND m.competition_level = 'qualification' AND m.scheduled_time IS NOT NULL
GROUP BY m.event_key
"""


@dataclass(frozen=True)
class RawPlayoffMatch:
    match_key: str
    competition_level: str
    set_number: int
    match_number: int
    scheduled_time: datetime | None
    winner: str | None
    red: tuple[int, ...]
    blue: tuple[int, ...]


@dataclass(frozen=True)
class EventPlayoffs:
    event_key: str
    season: int
    alliances: tuple[Alliance, ...]
    matches: tuple[RawPlayoffMatch, ...]
    latest_qualification: datetime | None
    team_count: int

    @property
    def division_champion(self) -> bool:
        return any(a.seed is None for a in self.alliances)

    def selection_as_of(self) -> datetime:
        if self.latest_qualification is None:
            raise ValueError(f"{self.event_key} has no qualification schedule")
        return selection_moment(self.latest_qualification)


def read_event_playoffs(database: Database, season: int) -> list[EventPlayoffs]:
    alliances = read_event_alliances(database, season)
    with database.cursor() as cursor:
        cursor.execute(QUALIFICATION_SQL, (season,))
        quals = {e: (t, n) for e, t, n in cursor.fetchall()}
        cursor.execute(PLAYOFF_SQL, (season,))
        rows = cursor.fetchall()
    by_event: dict[str, list[RawPlayoffMatch]] = {}
    for key, event, level, set_number, number, when, winner, red, blue in rows:
        by_event.setdefault(event, []).append(RawPlayoffMatch(
            key, level, set_number or 0, number or 0, when, winner if winner in ("red", "blue") else None,
            tuple(red or ()), tuple(blue or ())))
    return [EventPlayoffs(event, season, tuple(alliances.get(event, ())), tuple(matches),
                          quals.get(event, (None, 0))[0], quals.get(event, (None, 0))[1])
            for event, matches in sorted(by_event.items())]


def map_matches(event: EventPlayoffs) -> tuple[list[PlayoffMatch], Counter[str]]:
    """Each playoff match with its sides as seeds; unmappable sides counted, never guessed."""
    out, excluded = [], Counter()
    for m in event.matches:
        red, blue = map_side(m.red, event.alliances), map_side(m.blue, event.alliances)
        if red is None or blue is None or red.seed is None or blue.seed is None:
            excluded["side_unmappable"] += 1
            continue
        out.append(PlayoffMatch(m.match_key, m.competition_level, m.set_number, m.match_number, red.seed, blue.seed,
                                m.winner))
    return out, excluded


def event_bracket(event: EventPlayoffs, ruleset: SeasonRuleset) -> BracketFormat:
    """The ruleset's format for this event's number of alliances; the count must agree with the roster rule."""
    n = len(event.alliances)
    expected = ruleset.alliances_for(event.team_count)
    if n != expected:
        raise RulesetError("alliance_count", f"{event.event_key}: {n} alliances, the ruleset gives {expected} for "
                                             f"{event.team_count} teams")
    return ruleset.bracket(n)


def selection_features(database: Database, event: EventPlayoffs, teams: set[int], *, provider, scales
                       ) -> dict[int, TeamFeatures]:
    as_of = event.selection_as_of()
    return {t: build_team_features(database, t, event.event_key, as_of, epa_provider=provider, scale_lookup=scales)
            for t in sorted(teams)}


def playoff_rows(event: EventPlayoffs, bracket: BracketFormat, features: Mapping[int, TeamFeatures]
                 ) -> tuple[list[PlayoffRow], Counter[str]]:
    """PX-1 rows (§1): every exclusion counted by reason."""
    excluded: Counter[str] = Counter()
    seeds = {a.seed: a for a in event.alliances}
    slot_round = {(s.competition_level, s.set_number): s.round for s in bracket.slots}
    finals_key = (bracket.finals.competition_level, bracket.finals.set_number)
    mapped, unmapped = map_matches(event)
    excluded.update(unmapped)
    rows = []
    for m in mapped:
        key = (m.competition_level, m.set_number)
        round_ = bracket.finals.round if key == finals_key else slot_round.get(key)
        if round_ is None:
            excluded["slot_unknown"] += 1
            continue
        if m.winner is None:
            excluded["tie_or_unplayed"] += 1
            continue
        red = tuple(features[t] for t in seeds[m.red_seed].picks)
        blue = tuple(features[t] for t in seeds[m.blue_seed].picks)
        if not all(t.epa_total_present for t in (*red, *blue)):
            excluded["epa_incomplete"] += 1
            continue
        raw = next(r for r in event.matches if r.match_key == m.match_key)
        rows.append(PlayoffRow(m.match_key, event.event_key, event.season, raw.scheduled_time or event.selection_as_of(),
                               round_, m.red_seed, m.blue_seed, red, blue, m.winner == "red"))
    return rows, excluded
