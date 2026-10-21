"""Historical-data readiness gate for the M4-M7 real-data backtests (decision D8).

Separate from the Statbotics service monitor: the monitor asks "does the API
answer correctly", this asks "does the database hold every input the backtest
will read". It writes nothing persistent -- only session-scoped TEMP tables,
dropped when its connection closes.

The unit of requirement is a team appearance -- (team, target event, as_of) for
every scheduled match in the required seasons. For each one the backtest reads
exactly one EPA row, chosen by ml.features.assembler.EPA_SOURCE_SQL: among the
team's prior events it finished before as_of (end_date before as_of, and its
latest completed match there before as_of), the latest end_date, then the latest
completed match, then event_key ascending -- restricted to events that HAVE a
team_event_stats row. That last clause means a missing row does not fail: the
assembler silently falls back to an older event's EPA. So this gate derives the
*expected* source independently, by the same rule applied to the events the team
actually completed matches at (match_teams), and requires that

    expected source exists  ->  its team_event_stats row exists, is valid, and
                                is the row the assembler will select
    no expected source      ->  the assembler selects nothing either, which is
                                its documented EPA_WITHHELD_NO_PRIOR_EVENT path
                                (the only legitimate absence; counted, reported)

Same-date candidates (a division and its Einstein/finals) are resolved by that
deterministic rule and only counted, as diagnostics.

Scheduled-but-excluded matches (DQ, unplayed) are included deliberately: a
superset of the backtest's rows can only make the gate stricter.

Milestone 11's average_auto_points reads each completed match's raw TBA
score_breakdown through ml.features.score_breakdown. Every completed match in
the required seasons must therefore have a current raw payload whose breakdown
passes that adapter. A breakdown TBA never published is the one legitimate
absence (the feature skips that match; counted, reported); a missing raw
payload is PARTIAL and a breakdown the adapter rejects is INVALID.

Final event rankings are required for the held-out season's evaluation (M4's
ranking baseline, M5's Spearman gate), read through read_final_ranks_for_season
-- the same reader the backtest uses.

Status precedence: UNKNOWN > FAILED > INVALID > PARTIAL > COMPLETE. Only
COMPLETE permits M4-M7 real-data work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from data.rankings import read_final_ranks_for_season
from database.connection import Database
from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError, auto_points

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
FAILED = "FAILED"
INVALID = "INVALID"
UNKNOWN = "UNKNOWN"

REQUIRED_SEASONS = (2024, 2025, 2026)  # decision D7: train 2024+2025, hold out 2026
HELD_OUT_SEASON = 2026

CATEGORY_OK = "ok"
CATEGORY_NO_PRIOR_EVENT = "no_prior_event"          # legitimate: assembler withholds EPA
CATEGORY_MISSING_ROW = "missing_expected_row"       # blocking: PARTIAL
CATEGORY_INVALID_ROW = "invalid_expected_row"       # blocking: INVALID
# Cannot occur while this gate and the assembler agree on the rule; checked
# anyway, because a drift between them is exactly what must never go unnoticed.
CATEGORY_SOURCE_MISMATCH = "source_mismatch"        # blocking: INVALID

_BLOCKING_INVALID = (CATEGORY_INVALID_ROW, CATEGORY_SOURCE_MISMATCH)
_NON_FINITE = "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)"
EXAMPLES_PER_CATEGORY = 10

# Staged through indexed TEMP tables: the single-statement form re-evaluated
# ~320k lateral lookups per query and ran for over ten minutes.
_COMPLETED_SCORE = "(CASE WHEN mt.alliance_color = 'red' THEN m.score_red ELSE m.score_blue END)"

_STAGING_SQL = [
    # Every event each team completed at least one match at, with the time of
    # its latest completed match there -- the independent candidate set.
    f"""
    CREATE TEMP TABLE _rd_played AS
    SELECT mt.team_number, m.event_key, e.end_date, MAX(m.scheduled_time) AS last_completed
    FROM match_teams mt
    JOIN matches m ON m.match_key = mt.match_key
    JOIN events e ON e.event_key = m.event_key
    WHERE e.end_date IS NOT NULL AND m.scheduled_time IS NOT NULL AND {_COMPLETED_SCORE} IS NOT NULL
    GROUP BY mt.team_number, m.event_key, e.end_date
    """,
    "CREATE INDEX ON _rd_played (team_number, end_date DESC)",
    # The assembler's own candidate set: the same, restricted to events with a
    # team_event_stats row.
    """
    CREATE TEMP TABLE _rd_tes AS
    SELECT p.* FROM _rd_played p
    JOIN team_event_stats tes ON tes.team_number = p.team_number AND tes.event_key = p.event_key
    """,
    "CREATE INDEX ON _rd_tes (team_number, end_date DESC)",
    """
    CREATE TEMP TABLE _rd_appearances AS
    SELECT DISTINCT m.season, mt.team_number, m.event_key AS target_event, m.scheduled_time AS as_of
    FROM matches m
    JOIN match_teams mt ON mt.match_key = m.match_key
    WHERE m.season = ANY(%(seasons)s) AND m.scheduled_time IS NOT NULL
    """,
    f"""
    CREATE TEMP TABLE _rd_classified AS
    WITH resolved AS (
        SELECT a.season, a.team_number, a.target_event, a.as_of,
               exp.event_key AS expected_source,
               COALESCE(exp.tied_on_date, FALSE) AS tied_on_date,
               COALESCE(exp.tied_on_match_time, FALSE) AS tied_on_match_time,
               sel.event_key AS selected_source,
               xs.team_number IS NOT NULL AS expected_row_exists,
               (xs.epa_total IS NOT NULL
                AND xs.epa_total NOT IN {_NON_FINITE}
                AND COALESCE(xs.epa_auto NOT IN {_NON_FINITE}, TRUE)
                AND COALESCE(xs.epa_teleop NOT IN {_NON_FINITE}, TRUE)
                AND COALESCE(xs.epa_endgame NOT IN {_NON_FINITE}, TRUE)
                AND xs.matches_played IS NOT NULL AND xs.matches_played > 0) AS expected_row_valid
        FROM _rd_appearances a
        LEFT JOIN LATERAL (
            SELECT p.event_key,
                   COUNT(*) OVER (PARTITION BY p.end_date) > 1 AS tied_on_date,
                   COUNT(*) OVER (PARTITION BY p.end_date, p.last_completed) > 1 AS tied_on_match_time
            FROM _rd_played p
            WHERE p.team_number = a.team_number
              AND p.event_key != a.target_event
              AND p.end_date::timestamptz < a.as_of
              AND p.last_completed < a.as_of
            ORDER BY p.end_date DESC, p.last_completed DESC, p.event_key ASC
            LIMIT 1
        ) exp ON TRUE
        LEFT JOIN LATERAL (
            SELECT t.event_key
            FROM _rd_tes t
            WHERE t.team_number = a.team_number
              AND t.event_key != a.target_event
              AND t.end_date::timestamptz < a.as_of
              AND t.last_completed < a.as_of
            ORDER BY t.end_date DESC, t.last_completed DESC, t.event_key ASC
            LIMIT 1
        ) sel ON TRUE
        LEFT JOIN team_event_stats xs
               ON xs.team_number = a.team_number AND xs.event_key = exp.event_key
    )
    SELECT *,
        CASE
            WHEN expected_source IS NULL AND selected_source IS NULL THEN '{CATEGORY_NO_PRIOR_EVENT}'
            WHEN expected_source IS NULL THEN '{CATEGORY_SOURCE_MISMATCH}'
            WHEN NOT expected_row_exists THEN '{CATEGORY_MISSING_ROW}'
            WHEN NOT expected_row_valid THEN '{CATEGORY_INVALID_ROW}'
            WHEN selected_source IS DISTINCT FROM expected_source THEN '{CATEGORY_SOURCE_MISMATCH}'
            ELSE '{CATEGORY_OK}'
        END AS category
    FROM resolved
    """,
]

_TIE_SQL = """
SELECT COUNT(*) FILTER (WHERE tied_on_date AND NOT tied_on_match_time),
       COUNT(*) FILTER (WHERE tied_on_match_time)
FROM _rd_classified
"""

_COUNTS_SQL = "SELECT season, category, COUNT(*) FROM _rd_classified GROUP BY season, category"

_EXAMPLES_SQL = """
SELECT category, season, team_number, target_event, as_of, expected_source, selected_source
FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY category ORDER BY team_number, target_event, as_of) AS rn
    FROM _rd_classified WHERE category != 'ok'
) ranked
WHERE rn <= %(limit)s
ORDER BY category, rn
"""

_REQUIRED_SOURCES_SQL = """
SELECT COUNT(DISTINCT (team_number, expected_source)),
       COUNT(DISTINCT (team_number, expected_source)) FILTER (WHERE expected_row_valid)
FROM _rd_classified WHERE expected_source IS NOT NULL
"""

_TBA_PRECONDITION_SQL = """
SELECT e.season, COUNT(DISTINCT e.event_key), COUNT(m.match_key)
FROM events e LEFT JOIN matches m ON m.event_key = e.event_key
WHERE e.season = ANY(%(seasons)s)
GROUP BY e.season
"""

_RANKED_EVENTS_SQL = """
SELECT e.event_key FROM events e
WHERE e.season = %(season)s
  AND EXISTS (SELECT 1 FROM matches m WHERE m.event_key = e.event_key AND m.competition_level = 'qualification')
ORDER BY e.event_key
"""

_FINGERPRINT_SQL = """
SELECT COUNT(*),
       md5(COALESCE(string_agg(
           concat_ws(':', team_number, event_key, epa_total, epa_auto, epa_teleop, epa_endgame, matches_played),
           ',' ORDER BY team_number, event_key), ''))
FROM team_event_stats WHERE season = ANY(%(seasons)s)
"""

BREAKDOWN_OK = "ok"
BREAKDOWN_NOT_PUBLISHED = "not_published"       # legitimate: TBA has no breakdown for the match
BREAKDOWN_RAW_MISSING = "raw_payload_missing"   # blocking: PARTIAL
BREAKDOWN_INVALID = "invalid"                   # blocking: INVALID

_BREAKDOWN_SQL = """
SELECT m.season, m.match_key, raw.found, raw.breakdown
FROM matches m
LEFT JOIN LATERAL (
    SELECT TRUE AS found, r.payload_json->'score_breakdown' AS breakdown
    FROM raw_source_payloads r
    WHERE r.source = 'tba' AND r.source_object_type = 'match'
      AND r.source_object_id = m.match_key AND r.is_current
    ORDER BY r.id DESC
    LIMIT 1
) raw ON TRUE
WHERE m.season = ANY(%(seasons)s) AND m.scheduled_time IS NOT NULL
  AND (m.score_red IS NOT NULL OR m.score_blue IS NOT NULL)
"""

_STATBOTICS_ISSUES_SQL = "SELECT severity, COUNT(*) FROM data_quality_issues WHERE source = 'statbotics' GROUP BY severity"


@dataclass
class ReadinessReport:
    status: str
    computed_at: str
    seasons: list[int]
    held_out_season: int
    reasons: list[str] = field(default_factory=list)
    appearance_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    ties_resolved_by_latest_match: int = 0
    ties_resolved_by_event_key: int = 0
    required_source_rows: int = 0
    valid_source_rows: int = 0
    rankings_events_required: int = 0
    rankings_missing: list[str] = field(default_factory=list)
    examples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    statbotics_quality_issues: dict[str, int] = field(default_factory=dict)
    score_breakdown_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    score_breakdown_examples: dict[str, list[str]] = field(default_factory=dict)
    team_event_stats_rows: int = 0
    team_event_stats_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def totals(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for per_season in self.appearance_counts.values():
            for category, count in per_season.items():
                totals[category] = totals.get(category, 0) + count
        return totals


def assess_readiness(
    database: Database,
    *,
    seasons: Sequence[int] = REQUIRED_SEASONS,
    held_out_season: int = HELD_OUT_SEASON,
    now: datetime | None = None,
) -> ReadinessReport:
    """Classify the database's fitness for the M4-M7 backtests. Never raises on
    data problems; a query failure is reported as UNKNOWN."""
    report = ReadinessReport(
        status=UNKNOWN, computed_at=(now or datetime.now(timezone.utc)).isoformat(),
        seasons=list(seasons), held_out_season=held_out_season,
    )
    params = {"seasons": list(seasons)}
    try:
        with database.cursor() as cursor:
            cursor.execute(_TBA_PRECONDITION_SQL, params)
            present = {season: matches for season, _events, matches in cursor.fetchall()}
            missing_seasons = [s for s in seasons if not present.get(s)]
            if missing_seasons:
                report.reasons.append(f"no TBA matches synced for season(s) {missing_seasons}")
                return report

            for statement in _STAGING_SQL:
                cursor.execute(statement, params)

            cursor.execute(_COUNTS_SQL)
            for season, category, count in cursor.fetchall():
                report.appearance_counts.setdefault(str(season), {})[category] = count

            cursor.execute(_TIE_SQL)
            report.ties_resolved_by_latest_match, report.ties_resolved_by_event_key = cursor.fetchone()

            cursor.execute(_REQUIRED_SOURCES_SQL)
            report.required_source_rows, report.valid_source_rows = cursor.fetchone()

            cursor.execute(_EXAMPLES_SQL, {"limit": EXAMPLES_PER_CATEGORY})
            for category, season, team, target, as_of, expected, selected in cursor.fetchall():
                report.examples.setdefault(category, []).append({
                    "season": season, "team_number": team, "target_event": target,
                    "as_of": as_of.isoformat() if as_of else None,
                    "expected_source": expected, "selected_source": selected,
                })

            cursor.execute(_RANKED_EVENTS_SQL, {"season": held_out_season})
            ranked_events = [row[0] for row in cursor.fetchall()]

            cursor.execute(_FINGERPRINT_SQL, params)
            report.team_event_stats_rows, report.team_event_stats_fingerprint = cursor.fetchone()

            cursor.execute(_STATBOTICS_ISSUES_SQL)
            report.statbotics_quality_issues = {severity: count for severity, count in cursor.fetchall()}

        _assess_breakdowns(database, seasons, report)

        # The exact reader the backtest uses: an event it cannot evaluate --
        # no payload, or one that parses to no ranks -- is missing here too.
        final_ranks = read_final_ranks_for_season(database, held_out_season)
        report.rankings_events_required = len(ranked_events)
        report.rankings_missing = [key for key in ranked_events if key not in final_ranks]
    except Exception as exc:  # an unreadable database is UNKNOWN, never ready
        report.status = UNKNOWN
        report.reasons.append(f"readiness query failed: {type(exc).__name__}: {exc}")
        return report

    report.status, reasons = classify(report)
    report.reasons.extend(reasons)
    return report


def classify_breakdown(season: int, found: bool | None, breakdown: Any) -> tuple[str, str | None]:
    """One completed match's score_breakdown status, and why if it is not ok."""
    if not found:
        return BREAKDOWN_RAW_MISSING, "no current raw TBA payload"
    if not isinstance(breakdown, dict):
        return BREAKDOWN_NOT_PUBLISHED, None
    for color in ("red", "blue"):
        if breakdown.get(color) is None:
            return BREAKDOWN_INVALID, f"breakdown has no {color} side"
        try:
            auto_points(season, breakdown[color])
        except (UnsupportedSeasonError, ScoreBreakdownSchemaError) as exc:
            return BREAKDOWN_INVALID, str(exc)
    return BREAKDOWN_OK, None


def _assess_breakdowns(database: Database, seasons: Sequence[int], report: "ReadinessReport") -> None:
    with database.connection() as connection:
        with connection.cursor(name="readiness_breakdowns") as cursor:
            cursor.itersize = 2000
            cursor.execute(_BREAKDOWN_SQL, {"seasons": list(seasons)})
            for season, match_key, found, breakdown in cursor:
                status, why = classify_breakdown(season, found, breakdown)
                per_season = report.score_breakdown_counts.setdefault(str(season), {})
                per_season[status] = per_season.get(status, 0) + 1
                examples = report.score_breakdown_examples.setdefault(status, [])
                if why and len(examples) < EXAMPLES_PER_CATEGORY:
                    examples.append(f"{match_key}: {why}")


def resolve_sources(database: Database, *, seasons: Sequence[int]) -> list[tuple[int, str, datetime, str | None, str | None]]:
    """Every appearance's (team, target, as_of, expected_source, selected_source),
    for checking the gate's rule against the assembler's directly."""
    with database.cursor() as cursor:
        for statement in _STAGING_SQL:
            cursor.execute(statement, {"seasons": list(seasons)})
        cursor.execute("SELECT team_number, target_event, as_of, expected_source, selected_source FROM _rd_classified "
                       "ORDER BY team_number, target_event, as_of")
        return list(cursor.fetchall())


def _breakdown_totals(report: ReadinessReport) -> dict[str, int]:
    totals: dict[str, int] = {}
    for per_season in report.score_breakdown_counts.values():
        for status, count in per_season.items():
            totals[status] = totals.get(status, 0) + count
    return totals


def classify(report: ReadinessReport) -> tuple[str, list[str]]:
    totals = report.totals()
    appearances = sum(totals.values())
    if appearances == 0:
        return UNKNOWN, ["no match appearances found in the required seasons"]

    if report.required_source_rows > 0 and report.valid_source_rows == 0:
        return FAILED, [
            f"none of the {report.required_source_rows} required team_event_stats rows exist and validate "
            "(Statbotics data has not been synced)"
        ]

    breakdowns = _breakdown_totals(report)
    invalid = {category: totals[category] for category in _BLOCKING_INVALID if totals.get(category)}
    reasons: list[str] = []
    if invalid:
        reasons.append(f"invalid EPA inputs: {invalid}")
    if breakdowns.get(BREAKDOWN_INVALID):
        reasons.append(f"{breakdowns[BREAKDOWN_INVALID]} completed match(es) have a score_breakdown the M11 adapter rejects")
    if reasons:
        return INVALID, reasons

    if breakdowns.get(BREAKDOWN_RAW_MISSING):
        reasons.append(f"{breakdowns[BREAKDOWN_RAW_MISSING]} completed match(es) have no current raw TBA payload")
    if totals.get(CATEGORY_MISSING_ROW):
        reasons.append(
            f"{totals[CATEGORY_MISSING_ROW]} appearance(s) whose expected EPA source row is missing "
            f"({report.valid_source_rows}/{report.required_source_rows} required source rows valid)"
        )
    if report.rankings_missing:
        reasons.append(f"{len(report.rankings_missing)} held-out event(s) have no usable final ranking")
    if reasons:
        return PARTIAL, reasons

    return COMPLETE, [
        f"all {appearances} appearances resolved: {totals.get(CATEGORY_OK, 0)} with validated EPA, "
        f"{totals.get(CATEGORY_NO_PRIOR_EVENT, 0)} legitimately withheld (no prior concluded event); "
        f"{breakdowns.get(BREAKDOWN_OK, 0)} score breakdowns valid, {breakdowns.get(BREAKDOWN_NOT_PUBLISHED, 0)} "
        "not published by TBA; "
        f"final rankings present for all {report.rankings_events_required} held-out events"
    ]
