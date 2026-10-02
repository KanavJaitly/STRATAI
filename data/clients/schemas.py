from __future__ import annotations

from datetime import date

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventSummary(BaseModel):
    """Minimal TBA event summary model.

    TBA's raw API calls this field "year", not "season" — verified against
    external documentation after the original field name ("season") turned
    out to not exist in TBA's real API at all, meaning this model would have
    raised a validation error on every real event payload. The alias accepts
    the real wire field while keeping the "season" attribute name used
    consistently everywhere else in this codebase (database columns, other
    models, etc).
    """

    model_config = ConfigDict(populate_by_name=True)

    key: str
    name: str
    event_code: str | None = None
    season: int = Field(alias="year")
    start_date: date | None = None
    end_date: date | None = None
    # Location fields are present on TBA's real event payloads (both the
    # /events/{year} list and /event/{key} detail) and are carried by the
    # canonical events table, so they are modelled here rather than silently
    # dropped -- the Milestone 8 pipeline reconstructs the payload it lands
    # from this model, and anything absent here cannot reach the canonical row.
    city: str | None = None
    state_prov: str | None = None
    country: str | None = None


class MatchAllianceResult(BaseModel):
    """One alliance's roster and score within a single TBA match.

    team_keys' alias was "teams" until a system-wide audit found it factually
    wrong: TBA's real field is "team_keys" (confirmed against a captured live
    payload in tests/test_raw_body_preservation.py), not "teams" -- "teams" is
    a legacy name that appeared only in payloads landed before raw response
    bodies were preserved (a projection through this same model, which is why
    it used that name). Every real TBA response therefore parsed through this
    model only because populate_by_name=True let the attribute name itself
    ("team_keys") satisfy the field, not because the alias was correct --
    confirmed by grepping every test that populates this model: none ever
    used "teams" as the actual input key. This model deliberately does not
    also accept "teams" as a fallback: unlike data.staging.validator.
    tba_alliance_team_keys (which reads raw payload dicts straight out of
    raw_source_payloads, some landed before this fix and genuinely keyed on
    "teams"), this model exists to parse a live API response, where "team_keys"
    is the only form that has ever actually appeared.
    """

    model_config = ConfigDict(populate_by_name=True)

    score: int | None = None
    team_keys: list[str] = Field(default_factory=list, alias="team_keys")


class MatchAlliances(BaseModel):
    """The red/blue alliance results nested under a TBA match's "alliances" key."""

    red: MatchAllianceResult = Field(default_factory=MatchAllianceResult)
    blue: MatchAllianceResult = Field(default_factory=MatchAllianceResult)


class Match(BaseModel):
    """Minimal TBA match metadata model.

    Two real defects were fixed here: TBA's raw field is "comp_level", not
    "competition_level", and match scores/team rosters are nested under an
    "alliances": {"red": {...}, "blue": {...}} object, not flat score_red/
    score_blue fields — this model previously had no way to know which teams
    played a match at all. "scheduled_time" maps to TBA's "time" field, which
    is a Unix epoch integer, not a string.
    """

    model_config = ConfigDict(populate_by_name=True)

    key: str
    event_key: str
    competition_level: str | None = Field(default=None, alias="comp_level")
    set_number: int | None = None
    match_number: int | None = None
    scheduled_time: int | None = Field(default=None, alias="time")
    alliances: MatchAlliances = Field(default_factory=MatchAlliances)
    winning_alliance: str | None = None


class TeamInfo(BaseModel):
    """Minimal TBA team profile model."""

    key: str
    team_number: int
    nickname: str | None = None
    city: str | None = None
    state_prov: str | None = None
    country: str | None = None
    rookie_year: int | None = None
    website: str | None = None
    school_name: str | None = None
    motto: str | None = None


class TeamRanking(BaseModel):
    """One team's row in an event's qualification ranking, per TBA's real
    /event/{event_key}/rankings response (confirmed against TBA's own live
    OpenAPI spec, schema "Event_Ranking", 2026-09-25 -- the same verification
    discipline Phase 4 Milestone 2 already applied to dq_team_keys/
    surrogate_team_keys).

    Only team_key and rank are modeled. TBA's real response also carries
    dq, matches_played, qual_average, record (W-L-T), sort_orders, and
    extra_stats per team -- all preserved untouched in the landed raw
    payload (SourceResponse.raw), just not modeled here, because nothing in
    this codebase consumes them yet. Modeling fields nothing reads would be
    exactly the speculative-feature building this project's principles
    reject; extend this model when a real consumer needs one of them.
    """

    team_key: str
    rank: int


class EventRankings(BaseModel):
    """An event's full qualification ranking, per TBA's /event/{event_key}/rankings.

    rankings defaults to an empty list rather than being required, because
    TBA returns a bare `null` response body (not an empty rankings array)
    for an event with no computed ranking yet -- an unplayed or very early
    event. TBAClient.fetch_event_rankings handles that null case explicitly
    at the call site; this model's own default keeps construction from a
    genuinely empty ranking list working the same way.
    """

    rankings: list[TeamRanking] = Field(default_factory=list)


class EventAlliance(BaseModel):
    """One playoff alliance per TBA's /event/{event_key}/alliances.

    TBA returns the alliances as a list in seed order ("Alliance 1" first), or a
    bare `null` for an event with no alliance selection yet. picks[0] is the
    captain. ``status`` (the alliance's playoff record and result) is an
    *outcome* and is deliberately not modeled: it stays only in the landed raw
    payload, where data.alliances keeps it apart from the seed/pick data.
    """

    name: str | None = None
    picks: list[str] = Field(default_factory=list)
    declines: list[str] = Field(default_factory=list)
    backup: dict[str, Any] | None = None


class ScoutRadiozMatchScoutingRow(BaseModel):
    """One row of a ScoutRadioz match-scouting CSV export -- the platform's own
    stable, cross-season metadata columns only.

    ScoutRadioz (github.com/FIRSTTeam102/scoutradioz) has no public API --
    confirmed 2026-08-05 during Phase 3 Milestone 9 by reading its real GitHub
    repo, wiki, and TypeScript route source directly rather than assuming one
    existed: every data-bearing route, including this CSV export itself
    (`/exportdata`), sits behind an authenticated per-team login. There is no
    live request/response to model the way TBA/Statbotics have; a team exports
    this CSV from their own ScoutRadioz instance and hands it to StratAI
    directly. See RUNNING_NOTES.md for the full research trail.

    These eight columns are ScoutRadioz's own stable export schema -- present
    in every export regardless of season or game. Every OTHER column a real
    export carries (StartPos, AutoScore, qDefenseQuality, superNotes, and
    dozens more, all specific to one season's scouting form) is deliberately
    NOT modeled here: data.metrics.scoutradioz reads those directly out of the
    untouched raw row dict, driven by a caller-supplied field mapping, so this
    model never has to change when a new game's form adds or renames a field.

    `scouter` is allowed to be empty: a real export can have blank entries
    (verified in the captured fixture, not assumed) for a row where the
    scouting app was never told who was scouting. That is a real, structural
    gap in the *data*, not a bug in this model -- data.metrics.scoutradioz's
    mapping step surfaces it as a rejected row (an empty scout_identifier),
    the same way any other source's missing required field is rejected.

    `time` stays a raw string, not parsed here: it carries no timezone (see
    data.metrics.scoutradioz's _parse_scheduled_time for the documented
    limitation), and interpreting it is a mapping-layer concern, not a
    property of the wire row itself -- mirroring how team_key also stays an
    unparsed "frcNNNN" string here, exactly like MatchAllianceResult.team_keys.
    """

    org_key: str
    event_key: str
    match_key: str
    match_number: int
    time: str
    alliance: str
    team_key: str
    scouter: str


class StatboticsMatchStats(BaseModel):
    """Minimal Statbotics EPA-based match prediction model.

    Statbotics's real /matches payload nests predictions under a `pred` object
    (`pred.winner`, `pred.red_win_prob`, `pred.red_score`, `pred.blue_score`)
    and actual outcomes under a parallel `result` object. This model flattens
    the prediction fields and ignores the rest; actual scores already reach the
    canonical layer from TBA, which is the authority on what happened.

    Not currently consumed by the pipeline -- StatboticsClient.fetch_event_match_stats
    is implemented but not wired into any flow -- but the shape is corrected here
    so it cannot mislead whoever wires it up.
    """

    key: str
    event: str
    predicted_winner: str | None = None
    red_win_prob: float | None = None
    red_score_pred: float | None = None
    blue_score_pred: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten_prediction_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("pred"), dict):
            return data

        pred = data["pred"]
        flat = {key: value for key, value in data.items() if key != "pred"}
        for field_name, source_key in (
            ("predicted_winner", "winner"),
            ("red_win_prob", "red_win_prob"),
            ("red_score_pred", "red_score"),
            ("blue_score_pred", "blue_score"),
        ):
            flat.setdefault(field_name, pred.get(source_key))
        return flat


class StatboticsTeamEventMetrics(BaseModel):
    """Statbotics EPA-based team-event performance metrics, flattened.

    The attribute names mirror the team_event_stats columns, but Statbotics's
    real /team_event/{team}/{event} payload is deeply nested:

        {"team": 254, "event": "2024casj", "year": 2024, ...,
         "epa": {"total_points": 61.4, "unitless": ..., "norm": ...,
                 "breakdown": {"auto_points": ..., "teleop_points": ...,
                               "endgame_points": ..., ...},
                 "stats": {"start": ..., "mean": ..., "max": ...}},
         "record": {"total": {"wins": 8, "losses": 2, "ties": 0, "count": 10, ...},
                    "qual": {...}, "elim": {...}}}

    Flattening happens here rather than in the client or the staging normalizer
    so that exactly one place knows the source's nesting: the connector, the
    staging normalizer, and the canonical table all continue to work in flat
    fields. The `epa.breakdown` keys used below (`auto_points`, `teleop_points`,
    `endgame_points`) are stable across the 2024-2026 seasons in Statbotics's
    per-year key mapping, unlike the game-specific breakdown keys beside them.

    An already-flat payload is accepted unchanged, which keeps hand-built test
    fixtures and any payload landed by an earlier version of this code valid.

    `count` is the number of matches Statbotics counted, taken from
    record.total.count. Earlier versions of this pipeline believed no such count
    existed and derived it by summing the W/L/T breakdown; see
    normalize_statbotics_team_event_stats.
    """

    team: int
    event: str
    epa_total: float | None = None
    epa_auto: float | None = None
    epa_teleop: float | None = None
    epa_endgame: float | None = None
    wins: int | None = None
    losses: int | None = None
    ties: int | None = None
    count: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten_nested_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        epa, record = data.get("epa"), data.get("record")
        if not isinstance(epa, dict) and not isinstance(record, dict):
            return data  # already flat

        flat = {key: value for key, value in data.items() if key not in ("epa", "record")}

        if isinstance(epa, dict):
            flat.setdefault("epa_total", epa.get("total_points"))
            breakdown = epa.get("breakdown")
            if isinstance(breakdown, dict):
                flat.setdefault("epa_auto", breakdown.get("auto_points"))
                flat.setdefault("epa_teleop", breakdown.get("teleop_points"))
                flat.setdefault("epa_endgame", breakdown.get("endgame_points"))

        if isinstance(record, dict) and isinstance(record.get("total"), dict):
            total = record["total"]
            for field_name in ("wins", "losses", "ties", "count"):
                flat.setdefault(field_name, total.get(field_name))

        return flat
