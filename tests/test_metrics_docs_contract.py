"""Contract tests: docs/metrics_pipeline.md, the metrics schema, and the code must agree.

Phase 3 Milestone 15, and the Phase 3 counterpart to tests/test_docs_contract.py --
anti-drift guards rather than new behaviour coverage. They assert things that are true
today and would quietly stop being true as Phase 3 evolves:

  * docs/metrics_pipeline.md names every column the two metrics tables actually have,
    in BOTH directions, so a column added without documenting it fails
  * the keys, foreign keys, cascade rules, and CHECK constraints the docs promise exist
  * every constant the docs quote -- the rating scale, the rating descriptions, the
    aggregation minimum, the z-score thresholds, the confidence thresholds -- equals the
    constant in the code
  * the API's live OpenAPI paths are exactly the endpoints the docs document, and the
    four 404 codes are one vocabulary shared by the docs, the route, and the data layer
  * the claims a sign-off is NOT allowed to overstate stay documented as limitations

Test 10 (test_both_docs_document_the_same_metrics_columns) pins the one structural risk
this milestone introduces: docs/data_pipeline.md section 4.1 already documented these two
tables at the DDL level, and this page documents them semantically. Two pages describing
one table can disagree, so both are pinned to the live schema and to each other.

Deliberately NOT duplicated here: the Phase 2 schema/docs contract (tests/
test_docs_contract.py), aggregation behaviour (tests/test_aggregation.py), statistics
behaviour (tests/test_statistics.py), endpoint behaviour (tests/test_metrics_api.py),
error-envelope behaviour (tests/test_api_foundation.py), and quality-rule behaviour
(tests/test_metrics_quality.py). This module only asserts that the documentation of those
things is accurate.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from api.app import create_app
from api.errors import ErrorBody
from api.routes.metrics import _NOT_FOUND_RESPONSES
from data.config import Settings
from data.metrics import quality as metrics_quality
from data.metrics.aggregation import MIN_OBSERVATIONS_FOR_SCORE
from data.metrics.read import (
    STATUS_EVENT_NOT_FOUND,
    STATUS_METRICS_NOT_COMPUTED,
    STATUS_TEAM_DID_NOT_ATTEND,
    STATUS_TEAM_NOT_FOUND,
)
from data.metrics.schemas import (
    BAD_DAY_ZSCORE_THRESHOLD,
    DEFENSE_RATING_DESCRIPTIONS,
    FEEDING_RATING_DESCRIPTIONS,
    GOOD_DAY_ZSCORE_THRESHOLD,
    MAX_RATING,
    MIN_MATCHES_FOR_STDDEV,
    MIN_RATING,
    TeamMetrics,
)
from data.metrics.scoutradioz import ScoutRadiozRatingMapping
from data.staging import quality
from database.connection import Database, DatabaseConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_PATH = PROJECT_ROOT / "docs" / "metrics_pipeline.md"
PIPELINE_DOCS_PATH = PROJECT_ROOT / "docs" / "data_pipeline.md"

# The two tables this page is the semantic reference for.
METRICS_TABLES = ("scouting_observations", "team_metrics")

# The health probes are mounted outside api_prefix and are Milestone 12's, not this
# page's, so they are excluded when comparing documented endpoints to live ones.
PROBE_PATHS = {"/health", "/ready"}

# Phase 4 Milestone 12's ML prediction endpoints belong to their own future
# docs/ml_models.md (Phase 4 Milestone 13), not this page (the Phase 3
# scouting_observations/team_metrics reference) -- excluded here for the
# identical reason PROBE_PATHS is: out of this page's own documented scope,
# not undocumented by oversight.
ML_PREDICTION_PATHS = {
    "/predictions/matches/{match_key}/win-probability",
    "/predictions/win-probability",
    "/predictions/events/{event_key}/ranking",
    "/predictions/alliance-synergy",
}

# Phase 5's endpoints are documented in docs/phase5.md and pinned by
# tests/test_phase5_contract.py (P5-M10) -- out of this page's scope for the
# same reason as ML_PREDICTION_PATHS. The ones serving Phase 3's
# reliability_score still carry its INTERIM caveat (checked there).
PHASE5_PATHS = {
    "/teams/{team_number}/events/{event_key}/strength",
    "/events/{event_key}/analysis",
    "/events/{event_key}/qualification-forecast",
}


@pytest.fixture(scope="module")
def docs_text() -> str:
    assert DOCS_PATH.exists(), f"{DOCS_PATH} is missing"
    return DOCS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pipeline_docs_text() -> str:
    return PIPELINE_DOCS_PATH.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """Return one `## N.`/`### N.M` section's body.

    Ends at the next heading of equal *or shallower* depth, not merely equal: a `###`
    subsection is terminated by the following `##` too, or the last subsection of one
    section would silently absorb the whole of the next one and every containment
    assertion made against it would pass for the wrong reason.
    """
    assert heading in text, f"docs missing section: {heading}"
    body = text.split(heading, 1)[1]
    depth = len(heading.split(" ", 1)[0])
    next_heading = re.search(rf"^#{{1,{depth}}} ", body, flags=re.MULTILINE)
    return body[: next_heading.start()] if next_heading else body


def _flat(text: str) -> str:
    """Collapse whitespace, so a containment check survives the docs' line wrapping."""
    return re.sub(r"\s+", " ", text)


def _identifiers_in_backticks(text: str) -> set[str]:
    """Every snake_case identifier appearing inside a backtick span.

    Splits the span rather than matching it whole, so a composite reference like
    `(match_key, team_number, scout_identifier, source)` yields all four names. Callers
    intersect the result with a real column list, so the incidental extras it also picks
    up (table names, function names) are harmless.
    """
    names: set[str] = set()
    for span in re.findall(r"`([^`]+)`", text):
        names.update(re.findall(r"[a-z_][a-z0-9_]*", span))
    return names


# ===========================================================================
# Documentation structure. No database required.
# ===========================================================================


def test_docs_cover_every_documented_section(docs_text: str):
    for heading in (
        "## 1. Scope",
        "## 2. Architecture",
        "## 3. Data flow, end to end",
        "## 4. Schema reference (semantic)",
        "## 5. The 0–5 rating scale",
        "## 6. Scoring statistics",
        "## 7. Aggregation methodology",
        "## 8. API contract",
        "## 9. Known issues and limitations",
        "## 10. Extending Phase 3",
    ):
        assert heading in docs_text, f"docs missing section: {heading}"


def test_docs_reference_only_module_paths_that_exist(docs_text: str):
    referenced = set(
        re.findall(r"`((?:data|database|api|scripts|tests)/[a-z0-9_]+(?:/[a-z0-9_]+)*\.py)`", docs_text)
    )
    assert referenced, "expected the docs to reference module paths"
    missing = sorted(path for path in referenced if not (PROJECT_ROOT / path).exists())
    assert missing == [], f"docs reference non-existent modules: {missing}"


def test_docs_reference_only_migrations_that_exist(docs_text: str):
    referenced = set(re.findall(r"`(\d{4}_[a-z0-9_]+\.sql)`", docs_text))
    assert referenced, "expected the docs to reference the metrics migrations"
    missing = sorted(
        name for name in referenced if not (PROJECT_ROOT / "database" / "migrations" / name).exists()
    )
    assert missing == [], f"docs reference non-existent migrations: {missing}"


def test_docs_reference_the_human_validation_harness(docs_text: str):
    # Milestone 14's deliverable. Covered by the module-path test above too, but named
    # explicitly because a docs page for Phase 3 that never mentions it is incomplete.
    assert "scripts/metrics_spot_check.py" in docs_text
    assert (PROJECT_ROOT / "scripts" / "metrics_spot_check.py").exists()


def test_readme_points_at_the_metrics_docs():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/metrics_pipeline.md" in readme


def test_docs_cross_link_the_phase_2_reference(docs_text: str):
    # This page is deliberately not a second schema reference; it must point at the one
    # that owns the DDL, or the split silently becomes a fork.
    assert "data_pipeline.md" in docs_text


# ===========================================================================
# Rating scale and statistics constants. No database required.
# ===========================================================================


def test_documented_rating_scale_matches_the_code(docs_text: str):
    assert (MIN_RATING, MAX_RATING) == (0, 5)
    scale_section = _section(docs_text, "## 5. The 0–5 rating scale")
    assert "`MIN_RATING` = 0" in scale_section
    assert "`MAX_RATING` = 5" in scale_section


def test_documented_rating_descriptions_are_verbatim(docs_text: str):
    # These strings are what a scout is told a rating means. If code and docs drift, two
    # scouts are calibrated against two different scales.
    for descriptions in (DEFENSE_RATING_DESCRIPTIONS, FEEDING_RATING_DESCRIPTIONS):
        assert sorted(descriptions) == [0, 1, 2, 3, 4, 5], "a rating tier has no description"
        for rating, description in descriptions.items():
            assert description in docs_text, f"docs do not quote rating {rating} verbatim: {description!r}"


def test_zero_is_documented_as_a_real_rating_not_a_sentinel(docs_text: str):
    # The single most load-bearing convention on this scale, and the reason
    # excluded_values and target_min both exist.
    scale_section = _section(docs_text, "## 5. The 0–5 rating scale")
    assert "never a missing-data" in scale_section
    assert "insufficient_data" in scale_section


def test_documented_statistics_thresholds_match_the_code(docs_text: str):
    assert MIN_MATCHES_FOR_STDDEV == 2
    assert GOOD_DAY_ZSCORE_THRESHOLD == 1.0
    assert BAD_DAY_ZSCORE_THRESHOLD == -1.0

    scoring_section = _flat(_section(docs_text, "## 6. Scoring statistics"))
    assert "MIN_MATCHES_FOR_STDDEV` (2)" in scoring_section
    assert "GOOD_DAY_ZSCORE_THRESHOLD * stddev`, where the threshold is `1.0`" in scoring_section
    assert "BAD_DAY_ZSCORE_THRESHOLD * stddev`, where the threshold is `-1.0`" in scoring_section


def test_reliability_is_documented_as_a_placeholder_with_both_formulas(docs_text: str):
    section = _section(docs_text, "### 6.3 `reliability_score` is an interim placeholder")
    assert "100 * (matches_used / matches_scheduled)" in section, "the formula in use is not documented"
    assert "100 * (1 - (no_shows + disqualifications) / matches_scheduled)" in section, (
        "the intended formula is not documented"
    )
    assert "placeholder" in _flat(section).lower()
    assert "validating `reliability_score` validates nothing" in _flat(section).lower()


def test_candidate_tba_field_names_are_marked_unverified(docs_text: str):
    # Explicit M15 constraint: the no-show/DQ source does not exist, and these field
    # names were never checked against TBA's live docs. Documenting them as fact would
    # invite someone to build on them.
    section = _section(docs_text, "### 6.3 `reliability_score` is an interim placeholder")
    assert "dq_team_keys" in section, "the candidate field names are not documented at all"
    assert "UNVERIFIED" in section, "dq_team_keys is documented without an UNVERIFIED marker"
    assert "candidate" in section.lower()


# ===========================================================================
# Aggregation methodology. No database required.
# ===========================================================================


def test_documented_aggregation_minimum_matches_the_code(docs_text: str):
    assert MIN_OBSERVATIONS_FOR_SCORE == 2
    section = _section(docs_text, "## 7. Aggregation methodology")
    assert "`MIN_OBSERVATIONS_FOR_SCORE = 2`" in section
    assert "median" in section.lower(), "the median-not-mean decision is not documented"


def test_documented_agreement_formula_matches_the_code(docs_text: str):
    section = _section(docs_text, "### 7.3 Agreement")
    assert "pstdev" in section
    assert "(MAX_RATING - MIN_RATING) / 2" in section
    # Population, not sample -- the same choice score_stddev makes, and the reason the
    # formula's [0, 1] range is guaranteed rather than clamped into existence.
    assert "Population standard deviation" in _flat(section)
    assert "complete population of opinions" in _flat(section)


def test_documented_metric_confidence_thresholds_match_the_code(docs_text: str):
    assert quality.LOW_SAMPLE_MATCHES == 4
    assert quality.LOW_SAMPLE_OBSERVATIONS == 4
    assert quality.LOW_AGREEMENT == 0.5

    section = _section(docs_text, "### 7.6 Quality checks on a computed metric")
    for quoted in ("`matches_used < 4`", "`observation_count < 4`", "`agreement < 0.5`"):
        assert quoted in section, f"section 7.6 does not quote threshold {quoted}"
    assert "warning" in section.lower(), "section 7.6 does not state that every rule is a warning"


def test_metric_quality_issues_are_always_warnings():
    # The docs promise a computed metric is never rejected. That promise is only true
    # while severity is not a parameter of the issue builder.
    build = metrics_quality._issue_builder(metrics_quality.QUALITY_SOURCE, "1114_2026casj")
    issue = build(quality.ISSUE_LOW_SAMPLE_SIZE, "matches_used", "test")
    assert issue.severity == quality.SEVERITY_WARNING


# ===========================================================================
# Extension guide. No database required.
# ===========================================================================


def test_extension_guide_names_the_real_mapping_fields(docs_text: str):
    # The guide describes a Python dataclass, not a config file. If a field is renamed
    # or added, the guide must move with it.
    section = _section(docs_text, "### 10.1 Adding a season's column mapping")
    actual_fields = {field.name for field in dataclasses.fields(ScoutRadiozRatingMapping)}
    assert actual_fields == {"column", "source_min", "source_max", "excluded_values", "target_min"}
    for name in actual_fields:
        assert name in section, f"extension guide does not mention ScoutRadiozRatingMapping.{name}"


def test_target_min_default_is_documented_correctly(docs_text: str):
    # The docs claim every mapping written before target_min existed is unaffected. That
    # is only true while the default is MIN_RATING.
    default = {f.name: f.default for f in dataclasses.fields(ScoutRadiozRatingMapping)}["target_min"]
    assert default == MIN_RATING
    assert "`target_min` defaults to `MIN_RATING`" in docs_text


def test_extension_guide_documents_the_reimport_watermark_trap(docs_text: str):
    # The one operational fact that silently corrupts a re-import under a changed mapping.
    section = _section(docs_text, "### 10.1 Adding a season's column mapping")
    assert "watermark" in section.lower()
    assert "source_watermarks" in section


# ===========================================================================
# API contract. No database required -- the app builds on a bare Settings().
# ===========================================================================


@pytest.fixture(scope="module")
def openapi_schema(monkeypatch_module_env) -> dict:
    return create_app().openapi()


@pytest.fixture(scope="module")
def monkeypatch_module_env():
    """Minimal env for a bare Settings(), matching tests/test_docs_contract.py's fixture."""
    import os

    previous = {key: os.environ.get(key) for key in ("DATABASE_URL", "TBA_API_KEY", "ENV")}
    os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    os.environ.setdefault("TBA_API_KEY", "test-key")
    os.environ.setdefault("ENV", "development")
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_documented_endpoints_are_exactly_the_live_ones(docs_text: str, openapi_schema: dict):
    live = {p for p in openapi_schema["paths"] if not p.startswith("/human-inputs")}         - PROBE_PATHS - ML_PREDICTION_PATHS - PHASE5_PATHS
    documented = set(re.findall(r"^GET (/\S+)$", docs_text, flags=re.MULTILINE))
    assert documented, "section 8 documents no endpoint"
    assert live == documented, (
        f"live API paths and documented paths differ: only live={sorted(live - documented)}, "
        f"only documented={sorted(documented - live)}"
    )


def test_documented_api_prefix_default_matches_settings(docs_text: str, monkeypatch_module_env):
    assert Settings().api_prefix == ""
    section = _section(docs_text, "### 8.1 The endpoint")
    assert "`Settings.api_prefix`" in section
    assert 'defaults to `""`' in section


def test_health_probes_stay_outside_the_prefix(openapi_schema: dict):
    # The docs say so, and it is what keeps a probe stable when the API is remounted.
    assert PROBE_PATHS <= set(openapi_schema["paths"])


def test_reliability_score_placeholder_caveat_reaches_the_served_schema(openapi_schema: dict):
    """Section 6.3's caveat must travel on the API too, not only in prose.

    The interim formula is documented in three places and printed by the M14
    harness at every site, none of which an API client sees. Pinning it to the
    OpenAPI schema keeps the caveat from being dropped while the placeholder
    formula still stands -- the same reason section 6.3's UNVERIFIED marker is
    pinned by a test rather than trusted.
    """
    field = openapi_schema["components"]["schemas"]["ScoringProfile"]["properties"]["reliability_score"]
    assert "INTERIM" in field["description"]
    assert "matches_used / matches_scheduled" in field["description"]

    endpoints = [
        operation["description"]
        for path, item in openapi_schema["paths"].items()
        if path not in PROBE_PATHS and path not in ML_PREDICTION_PATHS and path not in PHASE5_PATHS
        and not path.startswith("/human-inputs")
        for operation in item.values()
    ]
    assert endpoints, "no non-probe endpoint to check"
    assert all("INTERIM" in description for description in endpoints)


def test_documented_example_response_is_a_valid_team_metrics(docs_text: str):
    section = _section(docs_text, "### 8.2 A successful response")
    fences = re.findall(r"```json\n(.*?)```", section, flags=re.DOTALL)
    assert fences, "section 8.2 shows no example response"
    # Constructing the real model runs Milestone 1's validators, so an example that
    # violates an invariant (day counts not summing, a score set alongside its
    # insufficient_data flag) fails here rather than misleading a reader.
    metrics = TeamMetrics.model_validate(json.loads(fences[0]))
    assert metrics.scoring.good_day_count is not None
    assert (
        metrics.scoring.good_day_count
        + metrics.scoring.average_day_count
        + metrics.scoring.bad_day_count
        == metrics.scoring.matches_used
    )


def test_the_four_not_found_codes_are_one_vocabulary(docs_text: str):
    # The same distinction is named in three places: the data layer's lookup statuses,
    # the route's response map, and the docs. A rename in one is a silent API break.
    data_layer = {
        STATUS_TEAM_NOT_FOUND,
        STATUS_EVENT_NOT_FOUND,
        STATUS_TEAM_DID_NOT_ATTEND,
        STATUS_METRICS_NOT_COMPUTED,
    }
    assert data_layer == {"team_not_found", "event_not_found", "team_did_not_attend", "metrics_not_computed"}

    route_codes = {code for code, _message in _NOT_FOUND_RESPONSES.values()}
    assert route_codes == data_layer
    assert set(_NOT_FOUND_RESPONSES) == data_layer

    section = _section(docs_text, "### 8.4 Four ways to have nothing, four codes")
    for code in data_layer:
        assert f"`{code}`" in section, f"section 8.4 does not document code {code!r}"


def test_docs_explain_the_actionability_split(docs_text: str):
    # The whole reason four codes exist behind one status. If this reasoning is lost, a
    # future change will collapse them back into one.
    section = _section(docs_text, "### 8.4 Four ways to have nothing, four codes")
    assert "Never resolves" in section
    assert "Resolves by waiting" in section


def test_documented_error_envelope_matches_the_model(docs_text: str):
    section = _section(docs_text, "### 8.5 The error envelope")
    fences = re.findall(r"```json\n(.*?)```", section, flags=re.DOTALL)
    assert fences, "section 8.5 shows no example envelope"
    example = json.loads(fences[0])
    assert set(example) == {"error"}, "the envelope must nest everything under one 'error' key"
    assert set(example["error"]) == set(ErrorBody.model_fields), (
        "the documented error body keys differ from api.errors.ErrorBody's fields"
    )


def test_docs_state_the_endpoint_never_recomputes(docs_text: str):
    section = _section(docs_text, "### 8.6 What this endpoint deliberately does not do")
    assert "never recomputes" in section.lower()
    assert "pipeline_runs" in section, "the external witness for 'never recomputes' is not documented"


# ===========================================================================
# Known-issues anti-drift. No database required.
# ===========================================================================


def test_agreement_is_documented_as_not_inter_scout(docs_text: str):
    # The single most important constraint on what an M14 sign-off may claim. Measured,
    # not assumed: zero (match, team) pairs in the real dataset had two scouts.
    section = _section(docs_text, "### 9.1 🔴 `defense_agreement` is not an inter-scout signal")
    assert "collection-time change" in section
    assert "observer-reliability" in section
    # The methodology section must warn at the point of use, not only in section 9.
    agreement_section = _section(docs_text, "### 7.3 Agreement")
    assert "§9.1" in agreement_section, "section 7.3 does not point at the limitation"


def test_feeding_is_documented_as_unvalidatable(docs_text: str):
    section = _section(docs_text, "### 9.3 🔴 Feeding is unvalidatable")
    assert "pre-aggregated" in section, "the reason the DCMP summary cannot substitute is not documented"
    assert "at scout time" in section


def test_rescale_and_bucket_resolution_are_both_documented(docs_text: str):
    section = _section(docs_text, "### 9.5 Rescaling: one defect fixed, one open")
    # The fixed half, and the caveat that survives the fix.
    assert "target_min" in section
    assert "opt-in" in section.lower()
    # The open half.
    assert "float" in section.lower(), "the float-score proposal is not documented"
    assert "0.54" in section and "0.51" in section, "the measured rank-correlation cost is not quoted"


def test_open_product_decision_is_documented(docs_text: str):
    section = _section(docs_text, "### 9.6 Open product decision: quality versus volume")
    assert "quality when defending" in section


# ===========================================================================
# Schema contract. Requires a reachable database.
# ===========================================================================


def _database_available() -> bool:
    # Duplicated from tests/test_docs_contract.py rather than imported: it is a private
    # helper of another test module, and this codebase's convention is to duplicate a
    # two-line private helper rather than reach across a module boundary for it.
    try:
        import psycopg

        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


@pytest.fixture
def database() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    return Database(DatabaseConfig(settings.database_url))


def _columns(database: Database, table: str) -> set[str]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}


def _constraint_defs(database: Database, table: str) -> list[str]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass",
            (table,),
        )
        return [row[0] for row in cursor.fetchall()]


def _index_defs(database: Database, table: str) -> list[str]:
    with database.cursor() as cursor:
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", (table,))
        return [row[0] for row in cursor.fetchall()]


@requires_db
@pytest.mark.parametrize("table", METRICS_TABLES)
def test_docs_document_every_column_these_tables_have(database, docs_text: str, table: str):
    # Both directions. A column added without documenting it fails here, and a column the
    # docs invent fails the live lookup.
    actual = _columns(database, table)
    assert actual, f"{table} has no columns -- is the migration applied?"

    heading = "### 4.1 `scouting_observations`" if table == "scouting_observations" else "### 4.2 `team_metrics`"
    documented = _identifiers_in_backticks(_section(docs_text, heading))

    undocumented = actual - documented
    assert undocumented == set(), (
        f"{table} columns exist but are not documented in docs/metrics_pipeline.md: {sorted(undocumented)}"
    )


@requires_db
@pytest.mark.parametrize("table", METRICS_TABLES)
def test_both_docs_document_the_same_metrics_columns(
    database, docs_text: str, pipeline_docs_text: str, table: str
):
    """Two pages describe these tables; neither may name a column the other omits.

    This is the structural risk Milestone 15 introduces by adding a second page about
    tables docs/data_pipeline.md already documents. Both sets are intersected with the
    live schema, so this pins the two pages to each other AND to the database -- the two
    cannot drift apart, and cannot drift together away from reality either.
    """
    actual = _columns(database, table)

    metrics_heading = (
        "### 4.1 `scouting_observations`" if table == "scouting_observations" else "### 4.2 `team_metrics`"
    )
    in_metrics_docs = _identifiers_in_backticks(_section(docs_text, metrics_heading)) & actual
    in_pipeline_docs = _identifiers_in_backticks(
        _section(pipeline_docs_text, f"#### `{table}`")
    ) & actual

    assert in_metrics_docs == actual, f"metrics_pipeline.md omits {sorted(actual - in_metrics_docs)}"
    assert in_pipeline_docs == actual, f"data_pipeline.md omits {sorted(actual - in_pipeline_docs)}"


@requires_db
@pytest.mark.parametrize("table,expected_pk", [
    ("team_metrics", "PRIMARY KEY (team_number, event_key)"),
    ("scouting_observations", "PRIMARY KEY (id)"),
])
def test_documented_primary_keys(database, table, expected_pk):
    assert any(expected_pk in defn for defn in _constraint_defs(database, table)), (
        f"{table} is missing documented {expected_pk}"
    )


@requires_db
def test_documented_natural_key_of_an_observation(database):
    # Section 4.1 promises one scout rates one team in one match once per source.
    columns = "(match_key, team_number, scout_identifier, source)"
    assert any(
        "UNIQUE INDEX" in defn and columns in defn
        for defn in _index_defs(database, "scouting_observations")
    ), f"scouting_observations is missing its documented unique index on {columns}"


@requires_db
@pytest.mark.parametrize("table,column,target", [
    ("scouting_observations", "match_key", "matches(match_key)"),
    ("scouting_observations", "team_number", "teams(team_number)"),
    ("scouting_observations", "event_key", "events(event_key)"),
    ("scouting_observations", "raw_payload_id", "raw_source_payloads(id)"),
    ("team_metrics", "team_number", "teams(team_number)"),
    ("team_metrics", "event_key", "events(event_key)"),
])
def test_documented_foreign_keys(database, table, column, target):
    expected = f"FOREIGN KEY ({column}) REFERENCES {target}"
    assert any(expected in defn for defn in _constraint_defs(database, table)), (
        f"{table} is missing documented FK {expected}"
    )


@requires_db
def test_observations_survive_a_raw_payload_deletion(database):
    # Section 4.1 calls observations the only irreplaceable data in the system and rests
    # a cascade rule on that claim. If this FK became CASCADE, integration teardown would
    # silently destroy human-collected scouting data.
    fks = [d for d in _constraint_defs(database, "scouting_observations") if "FOREIGN KEY" in d]
    raw_payload_fk = [d for d in fks if "raw_payload_id" in d]
    assert raw_payload_fk, "scouting_observations is missing its raw_payload_id FK"
    assert all("ON DELETE SET NULL" in d for d in raw_payload_fk)

    for column in ("match_key", "team_number", "event_key"):
        for defn in (d for d in fks if f"({column})" in d):
            assert "ON DELETE" not in defn, (
                f"scouting_observations.{column} FK must have no ON DELETE action: {defn}"
            )


@requires_db
def test_the_critical_constraint_is_enforced_in_the_schema(database):
    # Section 2.1 names four enforcement points for "directly measured, NOT inferred".
    # This is the second one: a confident score built on no observations is unstorable.
    checks = _constraint_defs(database, "team_metrics")
    assert any("defense_score" in d and "defense_insufficient_data" in d for d in checks), (
        "team_metrics is missing its defense sufficiency CHECK"
    )
    assert any("feeding_score" in d and "feeding_insufficient_data" in d for d in checks), (
        "team_metrics is missing its feeding sufficiency CHECK"
    )
    assert any("contributing_sources" in d for d in checks), (
        "team_metrics is missing its contributing_sources CHECK"
    )

    # And the first table's own rule: an observation rating neither metric is meaningless.
    observation_checks = _constraint_defs(database, "scouting_observations")
    assert any(
        "defense_rating" in d and "feeding_rating" in d and "IS NOT NULL" in d
        for d in observation_checks
    ), "scouting_observations is missing its at-least-one-rating CHECK"


@requires_db
def test_documented_matches_used_buckets_are_enforced_in_the_schema(database):
    # Section 6.1's three buckets are a storage-layer guarantee, not only a model one.
    checks = _constraint_defs(database, "team_metrics")
    assert any("matches_used" in d and "matches_scheduled" in d for d in checks)
    assert any("good_day_count" in d and "average_day_count" in d and "bad_day_count" in d for d in checks)


@requires_db
def test_documented_rating_bounds_are_enforced_in_the_schema(database):
    # Section 5 says the 0-5 bounds are hardcoded in SQL and that changing the scale
    # requires a migration. That is only true while the CHECKs actually carry them.
    # Postgres normalizes the migration's BETWEEN into a pair of comparisons, so the
    # bounds are asserted in that rendered form rather than as written.
    checks = _constraint_defs(database, "scouting_observations")
    for column in ("defense_rating", "feeding_rating"):
        assert any(
            f"{column} >= {MIN_RATING}" in defn and f"{column} <= {MAX_RATING}" in defn
            for defn in checks
        ), f"scouting_observations.{column} does not carry the documented {MIN_RATING}-{MAX_RATING} bounds"
