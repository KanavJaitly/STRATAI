"""Historical-data readiness gate for the M4-M7 real-data backtests (decision D8).

Separate from the Statbotics service monitor: the monitor asks "does the API
answer correctly", this asks "does the database hold every input the backtest
will read". It writes nothing persistent -- only session-scoped TEMP tables,
dropped when its connection closes.

The unit of requirement is a team appearance -- (team, target event, as_of) for
every scheduled match in the required seasons. For each one the backtest reads
exactly one EPA row, chosen by ml.features.assembler._point_in_time_epa: the
most recent event, other than the target, whose end_date is before as_of AND
which has a team_event_stats row. That "has a row" clause means a missing row
does not fail -- it silently falls back to an older event's EPA. So this gate
derives the *expected* source independently, from the events the team actually
played (match_teams), and requires that

    expected source exists  ->  its team_event_stats row exists, is valid, and
                                is the row the assembler will select
    no expected source      ->  the assembler selects nothing either, which is
                                its documented EPA_WITHHELD_NO_PRIOR_EVENT path
                                (the only legitimate absence; counted, reported)

Scheduled-but-excluded matches (DQ, unplayed) are included deliberately: a
superset of the backtest's rows can only make the gate stricter.

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
CATEGORY_SOURCE_MISMATCH = "source_mismatch"        # blocking: INVALID
CATEGORY_AMBIGUOUS_SOURCE = "ambiguous_source"      # blocking: INVALID

_BLOCKING_INVALID = (CATEGORY_INVALID_ROW, CATEGORY_SOURCE_MISMATCH, CATEGORY_AMBIGUOUS_SOURCE)
_NON_FINITE = "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)"
EXAMPLES_PER_CATEGORY = 10

# Staged through indexed TEMP tables: the single-statement form re-evaluated
# ~320k lateral lookups per query and ran for over ten minutes.
_STAGING_SQL = [
    """
    CREATE TEMP TABLE _rd_played AS
    SELECT DISTINCT mt.team_number, m.event_key, e.end_date
    FROM match_teams mt
    JOIN matches m ON m.match_key = mt.match_key
    JOIN events e ON e.event_key = m.event_key
    WHERE e.end_date IS NOT NULL
    """,
    "CREATE INDEX ON _rd_played (team_number, end_date DESC)",
    # The candidate set of the assembler's own query (team_event_stats joined
    # to events with a non-null end_date), indexed the same way.
    """
    CREATE TEMP TABLE _rd_tes AS
    SELECT tes.team_number, tes.event_key, e.end_date
    FROM team_event_stats tes
    JOIN events e ON e.event_key = tes.event_key
    WHERE e.end_date IS NOT NULL
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
               exp.event_key AS expected_source, exp.tied AS expected_tied,
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
            SELECT p.event_key, COUNT(*) OVER (PARTITION BY p.end_date) > 1 AS tied
            FROM _rd_played p
            WHERE p.team_number = a.team_number
              AND p.event_key != a.target_event
              AND p.end_date::timestamptz < a.as_of
            ORDER BY p.end_date DESC
            LIMIT 1
        ) exp ON TRUE
        LEFT JOIN LATERAL (
            SELECT t.event_key
            FROM _rd_tes t
            WHERE t.team_number = a.team_number
              AND t.event_key != a.target_event
              AND t.end_date::timestamptz < a.as_of
            ORDER BY t.end_date DESC
            LIMIT 1
        ) sel ON TRUE
        LEFT JOIN team_event_stats xs
               ON xs.team_number = a.team_number AND xs.event_key = exp.event_key
    )
    SELECT *,
        CASE
            WHEN expected_source IS NULL AND selected_source IS NULL THEN '{CATEGORY_NO_PRIOR_EVENT}'
            WHEN expected_source IS NULL THEN '{CATEGORY_SOURCE_MISMATCH}'
            WHEN expected_tied THEN '{CATEGORY_AMBIGUOUS_SOURCE}'
            WHEN NOT expected_row_exists THEN '{CATEGORY_MISSING_ROW}'
            WHEN NOT expected_row_valid THEN '{CATEGORY_INVALID_ROW}'
            WHEN selected_source IS DISTINCT FROM expected_source THEN '{CATEGORY_SOURCE_MISMATCH}'
            ELSE '{CATEGORY_OK}'
        END AS category
    FROM resolved
    """,
]

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

_STATBOTICS_ISSUES_SQL = "SELECT severity, COUNT(*) FROM data_quality_issues WHERE source = 'statbotics' GROUP BY severity"


@dataclass
class ReadinessReport:
    status: str
    computed_at: str
    seasons: list[int]
    held_out_season: int
    reasons: list[str] = field(default_factory=list)
    appearance_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    required_source_rows: int = 0
    valid_source_rows: int = 0
    rankings_events_required: int = 0
    rankings_missing: list[str] = field(default_factory=list)
    examples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    statbotics_quality_issues: dict[str, int] = field(default_factory=dict)
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

    invalid = {category: totals[category] for category in _BLOCKING_INVALID if totals.get(category)}
    if invalid:
        return INVALID, [f"invalid EPA inputs: {invalid}"]

    reasons: list[str] = []
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
        f"final rankings present for all {report.rankings_events_required} held-out events"
    ]
