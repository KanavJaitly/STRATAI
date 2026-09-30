"""Turn a SeasonInput into the ordered match stream the engine consumes.

Applies data contract §4 in order: run-level checks, event filters, match
filters and rejections, breakdown cleaning, skip rules, then chronological
ordering (spec §2.3). Every match that leaves the stream, or stays in it
without a normal update, is recorded in the exclusion collector.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from ml.ratings.epa import exclusions as ex
from ml.ratings.epa.adapters import BreakdownRejection, CleanedAlliance, clean_alliance, post_clean
from ml.ratings.epa.constants import (
    CHAMPS_EVENT_TYPES,
    CHAMPS_WEEK,
    EVENT_BLACKLIST,
    EVENT_TYPE_OVERRIDES,
    EXCLUDED_EVENT_TYPES,
    ISR_SEASON,
    NUM_TEAMS,
    PLACEHOLDER_TEAMS,
    SUPPORTED_SEASONS,
    TEMPCLONE_MARKER,
    WEEK_SHIFTED_EVENT_TYPES,
)
from ml.ratings.epa.inputs import EventInput, MatchInput, SeasonInput


@dataclass(frozen=True)
class PreparedEvent:
    event_key: str
    event_type: int  # after EVENT_TYPE_OVERRIDES
    week: int  # adjusted (spec §2.1)
    district: str | None


@dataclass(frozen=True)
class PreparedMatch:
    """One retained match. red/blue are None exactly when it is upcoming."""

    match_key: str
    event_key: str
    time: int
    week: int
    comp_level: str
    elim: bool
    red_teams: tuple[int, ...]
    blue_teams: tuple[int, ...]
    red_dq: tuple[int, ...]
    blue_dq: tuple[int, ...]
    red_surrogates: tuple[int, ...]
    blue_surrogates: tuple[int, ...]
    red: CleanedAlliance | None
    blue: CleanedAlliance | None
    skip_code: str | None

    @property
    def completed(self) -> bool:
        return self.red is not None

    @property
    def status(self) -> str:
        if not self.completed:
            return ex.UPCOMING
        return self.skip_code or ex.UPDATED

    @property
    def teams(self) -> tuple[int, ...]:
        return self.red_teams + self.blue_teams


@dataclass(frozen=True)
class PreparedSeason:
    season: int
    events: dict[str, PreparedEvent]
    stream: tuple[PreparedMatch, ...]  # processing order
    teams: tuple[int, ...]  # every team in the stream, ascending
    collector: ex.ExclusionCollector


def adjusted_week(season: int, event: EventInput) -> tuple[PreparedEvent | None, str | None]:
    """tba/read_tba.py:86-135: the event as the reference keeps it, or why it is filtered."""
    key = event.event_key
    if TEMPCLONE_MARKER in key or key in EVENT_BLACKLIST:
        return None, ex.EVENT_BLACKLISTED
    if event.event_type in EXCLUDED_EVENT_TYPES and key not in EVENT_TYPE_OVERRIDES:
        return None, ex.EVENT_TYPE_EXCLUDED
    event_type = EVENT_TYPE_OVERRIDES.get(key, event.event_type)
    week = CHAMPS_WEEK if event_type in CHAMPS_EVENT_TYPES else event.week
    if week is None:
        return None, ex.EVENT_WEEK_MISSING
    if season != 2016 and event_type in WEEK_SHIFTED_EVENT_TYPES:
        week += 1
    return PreparedEvent(key, event_type, week, event.district), None


def _check_run(season_input: SeasonInput) -> None:
    season = season_input.season
    if season not in SUPPORTED_SEASONS:
        raise ex.RunRejected(ex.UNSUPPORTED_SEASON, f"season {season} not in {SUPPORTED_SEASONS}")
    for code, keys in (
        (ex.DUPLICATE_EVENT_KEY, [e.event_key for e in season_input.events]),
        (ex.DUPLICATE_MATCH_KEY, [m.match_key for m in season_input.matches]),
    ):
        duplicates = sorted(k for k, n in Counter(keys).items() if n > 1)
        if duplicates:
            raise ex.RunRejected(code, ", ".join(duplicates))
    wrong_season = sorted(e.event_key for e in season_input.events if not e.event_key.startswith(str(season)))
    if wrong_season:
        raise ex.RunRejected(ex.EVENT_SEASON_MISMATCH, ", ".join(wrong_season))
    event_keys = {e.event_key for e in season_input.events}
    unknown = sorted({m.event_key for m in season_input.matches} - event_keys)
    if unknown:
        raise ex.RunRejected(ex.UNKNOWN_EVENT, ", ".join(unknown))
    if season_input.prior is not None:
        late = sorted(
            f"{team}:{year.season}"
            for team, years in season_input.prior.team_years.items()
            for year in years
            if year.season >= season
        )
        if late:
            raise ex.RunRejected(ex.PRIOR_NOT_BEFORE_SEASON, ", ".join(late))
        if season == ISR_SEASON and season_input.team_districts is None:
            raise ex.RunRejected(
                ex.TEAM_DISTRICTS_REQUIRED,
                "a 2026 run with prior history needs team_districts for the isr mean-reversion rule",
            )


def _invalid_alliance(match: MatchInput) -> str | None:
    # tba/read_tba.py:201-205
    red, blue = set(match.red.teams), set(match.blue.teams)
    if len(red) < NUM_TEAMS or len(blue) < NUM_TEAMS:
        return f"distinct teams red={len(red)} blue={len(blue)}"
    if red & blue:
        return f"teams on both alliances: {sorted(red & blue)}"
    return None


def _skip_code(match: MatchInput, red: CleanedAlliance, blue: CleanedAlliance) -> str | None:
    # models/template.py:77-90, in the reference's order
    teams = match.red.teams[:NUM_TEAMS] + match.blue.teams[:NUM_TEAMS]
    if PLACEHOLDER_TEAMS.intersection(teams):
        return ex.SKIP_PLACEHOLDER
    if match.elim and (len(match.red.dq_teams) >= NUM_TEAMS or len(match.blue.dq_teams) >= NUM_TEAMS):
        return ex.SKIP_ELIM_ALL_DQ
    if blue.no_foul == 0 and (blue.foul or 0) > 0 and red.no_foul == 0 and (red.foul or 0) > 0:
        return ex.SKIP_ALL_FOULS
    return None


def _is_completed(match: MatchInput) -> bool:
    red, blue = match.red.score, match.blue.score
    return red is not None and blue is not None and red >= 0 and blue >= 0


def _prepare_match(
    season: int, match: MatchInput, event: PreparedEvent, collector: ex.ExclusionCollector
) -> PreparedMatch | None:
    key, event_key = match.match_key, match.event_key
    invalid = _invalid_alliance(match)
    if invalid is not None:
        collector.add(ex.INVALID_ALLIANCE, event_key, key, invalid)
        return None
    if match.time is None:
        collector.add(ex.MISSING_TIME, event_key, key, "no TBA scheduled time; the reference would synthesize one")
        return None

    red: CleanedAlliance | None = None
    blue: CleanedAlliance | None = None
    skip_code: str | None = None
    if _is_completed(match):
        cleaned = {
            color: clean_alliance(season, alliance.score, alliance.breakdown)  # type: ignore[arg-type]
            for color, alliance in (("red", match.red), ("blue", match.blue))
        }
        rejections = [(c, r) for c, r in cleaned.items() if isinstance(r, BreakdownRejection)]
        if rejections:
            code = rejections[0][1].code
            detail = "; ".join(f"{c}: {r.detail}" for c, r in rejections)
            collector.add(code, event_key, key, detail)
            return None
        red, blue = post_clean(season, cleaned["red"], cleaned["blue"])  # type: ignore[arg-type]
        empties = [c for c, a in (("red", red), ("blue", blue)) if a.empty]
        if empties:
            collector.add(ex.ZERO_SCORE, event_key, key, f"score 0: {', '.join(empties)}")
            collector.shared_empty_alliances += len(empties)
        skip_code = _skip_code(match, red, blue)
        if skip_code is not None:
            collector.add(skip_code, event_key, key, "predicted and recorded, rating not updated")
    else:
        collector.add(
            ex.UPCOMING, event_key, key, f"scores red={match.red.score} blue={match.blue.score}; predicted only"
        )

    return PreparedMatch(
        match_key=key,
        event_key=event_key,
        time=match.time,
        week=event.week,
        comp_level=match.comp_level,
        elim=match.elim,
        red_teams=match.red.teams[:NUM_TEAMS],
        blue_teams=match.blue.teams[:NUM_TEAMS],
        red_dq=match.red.dq_teams,
        blue_dq=match.blue.dq_teams,
        red_surrogates=match.red.surrogate_teams,
        blue_surrogates=match.blue.surrogate_teams,
        red=red,
        blue=blue,
        skip_code=skip_code,
    )


def _ties(stream: list[PreparedMatch]) -> list[ex.TieGroup]:
    by_time: dict[int, list[PreparedMatch]] = defaultdict(list)
    for match in stream:
        by_time[match.time].append(match)
    groups: list[ex.TieGroup] = []
    for time in sorted(by_time):
        group = by_time[time]
        if len(group) < 2:
            continue
        appearances = Counter(team for m in group for team in m.teams)
        groups.append(ex.TieGroup(time, tuple(m.match_key for m in group), any(n > 1 for n in appearances.values())))
    return groups


def prepare_season(season_input: SeasonInput) -> PreparedSeason:
    """Validate, filter, clean and order one season. Raises RunRejected."""
    _check_run(season_input)
    season = season_input.season
    collector = ex.ExclusionCollector()

    events: dict[str, PreparedEvent] = {}
    filtered: dict[str, str] = {}
    for event in sorted(season_input.events, key=lambda e: e.event_key):
        prepared, code = adjusted_week(season, event)
        if prepared is None:
            filtered[event.event_key] = code  # type: ignore[assignment]
        else:
            events[event.event_key] = prepared

    matches_by_event: dict[str, int] = Counter(m.event_key for m in season_input.matches)
    for event_key, code in filtered.items():
        if matches_by_event[event_key] == 0:
            collector.add(code, event_key, None, "event filtered; it has no matches")

    stream: list[PreparedMatch] = []
    for match in sorted(season_input.matches, key=lambda m: m.match_key):
        if match.event_key in filtered:
            collector.add(filtered[match.event_key], match.event_key, match.match_key, "event filtered")
            continue
        prepared_match = _prepare_match(season, match, events[match.event_key], collector)
        if prepared_match is not None:
            stream.append(prepared_match)

    # spec §2.3: scheduled time, then match_key [STRATAI tie-break]
    stream.sort(key=lambda m: (m.time, m.match_key))
    collector.ties.extend(_ties(stream))
    teams = tuple(sorted({team for m in stream for team in m.teams}))
    return PreparedSeason(season, events, tuple(stream), teams, collector)
