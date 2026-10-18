"""Reading real playoff data for the playoff track and P6-DM1 (point in time; outcomes are labels only).

- **Read:** an event's playoff matches with each side's teams and the TBA winner, its P5-M1 alliances, its latest
  qualification match (the selection moment) and its roster size.
- **Build:** PX-1 rows from those, with every exclusion counted by reason (`.agent/phase6/P6_M2_PX1_SPEC.md` §1).
- **Bracket rounds** always come from the approved ruleset passed in, never from code.

**Selection-time members (D-PX1-1, Kanav 2026-10-06; `.agent/phase6/decisions/P6_PX1_COMPOSITION_DECISIONS.md`).**
- **Definition:** an alliance's composition is its members at the selection moment, i.e. the captain plus the
  event's `picks_per_alliance` picks, from the event's own rules (`SeasonRuleset.for_event`).
- **Backups:** TBA lists a backup as an extra `picks` entry. Recruited during the playoffs, it is never a member.
- **Refused, counted:** an extra entry where the rules allow no backup, or more than one extra entry
  (`unexpected_listed_team`). Never interpreted.
- **Used everywhere:** PX-1 rows (and so the M6/M7 baseline), PX-4's alliances and P6-M8's actual alliances all use
  `selection_members`.
- **Four members (D-PX1-2):** a row with a side that is not three members (FIRST Championship divisions, 4-ROBOT
  ALLIANCES) is outside PX-1's frozen three-team representation. It is excluded as `four_member_alliance` and
  counted.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from data.alliances import Alliance, read_event_alliances
from data.rulesets import BracketFormat, EventRules, RulesetError, SeasonRuleset
from database.connection import Database
from ml.features.assembler import TeamFeatures, build_team_features
from ml.playoffs.evaluation import PlayoffMatch
from ml.playoffs.px1 import PX1_TEAMS_PER_ALLIANCE, PlayoffRow, map_side, selection_moment

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


def selection_members(alliance: Alliance, event_rules: EventRules) -> tuple[int, ...]:
    """The alliance at the selection moment: the captain and the event's picks (D-PX1-1). A listed backup is not a
    member; a listing the event's rules do not explain is refused (`unexpected_listed_team`), never interpreted."""
    selection = event_rules.selection
    size = 1 + selection.picks_per_alliance
    if len(alliance.picks) < size:
        raise RulesetError("incomplete_alliance", f"{event_rules.event_key} seed {alliance.seed}: "
                                                  f"{len(alliance.picks)} listed teams, the rules need {size}")
    extra = alliance.picks[size:]
    if extra and (not selection.backup_robots or len(extra) > 1):
        raise RulesetError("unexpected_listed_team", f"{event_rules.event_key} seed {alliance.seed}: listed "
                                                     f"{alliance.picks} but the rules allow {size} members and "
                                                     f"{'one backup' if selection.backup_robots else 'no backup'}")
    return alliance.picks[:size]


def event_members(event: EventPlayoffs, event_rules: EventRules) -> dict[int, tuple[int, ...]]:
    """{seed: selection-time members} for every alliance of the event (raises as `selection_members` does)."""
    return {a.seed: selection_members(a, event_rules) for a in event.alliances}


def map_side_members(side_teams, members: Mapping[int, tuple[int, ...]]) -> int | None:
    """The seed whose captain-and-picks contain at least two of the side's teams (PX-1 spec §1), or None."""
    seeds = [seed for seed, teams in members.items() if len(set(teams) & set(side_teams)) >= 2]
    return seeds[0] if len(seeds) == 1 else None


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


def playoff_rows(event: EventPlayoffs, bracket: BracketFormat, features: Mapping[int, TeamFeatures],
                 event_rules: EventRules) -> tuple[list[PlayoffRow], Counter[str]]:
    """PX-1 rows (§1): every exclusion counted by reason.

    The composition is the selection-time members (D-PX1-1). A side that is not three members is excluded as
    `four_member_alliance` before the EPA check (D-PX1-2). Raises `RulesetError` when a listing is unexplained."""
    excluded: Counter[str] = Counter()
    members = event_members(event, event_rules)
    slot_round = {(s.competition_level, s.set_number): s.round for s in bracket.slots}
    finals_key = (bracket.finals.competition_level, bracket.finals.set_number)
    rows = []
    for raw in event.matches:
        red_seed, blue_seed = map_side_members(raw.red, members), map_side_members(raw.blue, members)
        if red_seed is None or blue_seed is None:
            excluded["side_unmappable"] += 1
            continue
        key = (raw.competition_level, raw.set_number)
        round_ = bracket.finals.round if key == finals_key else slot_round.get(key)
        if round_ is None:
            excluded["slot_unknown"] += 1
            continue
        if raw.winner is None:
            excluded["tie_or_unplayed"] += 1
            continue
        if any(len(members[s]) != PX1_TEAMS_PER_ALLIANCE for s in (red_seed, blue_seed)):
            excluded["four_member_alliance"] += 1
            continue
        red = tuple(features[t] for t in members[red_seed])
        blue = tuple(features[t] for t in members[blue_seed])
        if not all(t.epa_total_present for t in (*red, *blue)):
            excluded["epa_incomplete"] += 1
            continue
        rows.append(PlayoffRow(raw.match_key, event.event_key, event.season,
                               raw.scheduled_time or event.selection_as_of(), round_, red_seed, blue_seed, red, blue,
                               raw.winner == "red"))
    return rows, excluded
