"""Labeled match-outcome dataset builder.

Phase 4 Milestone 2 (authoritative plan, docs/P4Milestones.md). Attaches a
real outcome -- red_win / blue_win / tie, plus score margin as an auxiliary
target -- to Milestone 1's leakage-safe MatchFeatureRow, for every match this
milestone's documented rules consider "playable and completed", across a set
of seasons. The result is persisted as a versioned, regenerable parquet
artifact with a manifest, per the milestone's own "Success looks like".

build_training_frame(database, season_keys) is the entry point. It never
recomputes or reinterprets anything Milestone 1 already gets right --
red_teams/blue_teams on each row are exactly build_match_feature_row's own
MatchFeatureRow.red_teams/blue_teams, called with as_of set to the target
match's own scheduled_time (the same boundary Milestone 1's module docstring
names this module as the intended caller of). This module's only new job is
deciding *which* matches qualify for a label at all, and computing that label
correctly.

Inclusion / exclusion rules (the milestone's own required deliverable)
========================================================================
Five rules, applied in this order, each match keeping exactly one reason if
excluded:

1. no_scheduled_time -- matches.scheduled_time IS NULL. Without a scheduled
   time there is no point-in-time cutoff to build point-in-time-safe features
   against (Milestone 1's as_of has no default for exactly this reason), and
   no temporal-split field (Milestone 3) to place the row in. Rare in
   practice (Phase 2's 2024-season validation found scheduled_time populated
   for every real synced match it checked -- see
   ml/features/assembler.py's _point_in_time_scores), a safety net, not a
   routine case.

2. unplayed -- score_red IS NULL (equivalently score_blue IS NULL; the
   staging normalizer's own invariant, data/staging/normalizer.py's
   _alliance_scores, guarantees they are always both-null or both-set). A
   match with no recorded score has no outcome to label.

3. winning_alliance_missing -- defensive only. Once score_red/score_blue are
   both present, data/staging/normalizer.py's _derive_winning_alliance
   guarantees winning_alliance is exactly "red", "blue", or "tie" -- never
   NULL or "". This branch should be unreachable against any row that passed
   through that normalizer; it exists so a row that somehow reached the
   canonical table by a different path (a future non-TBA match source, a
   hand-built fixture, a bug) is excluded with a clear reason instead of
   mislabeled or crashing the build.

4. dq_affected -- either alliance had a team disqualified in this match.
   comp_level (qualification vs playoff), ties, and surrogate appearances are
   all kept and correctly labeled per the milestone's own "never silently
   dropped or mislabeled" instruction -- but a DQ ruling can override what
   actually happened on the field (an alliance that outscored its opponent
   can still lose the match to a disqualification), which makes the recorded
   winner a procedural outcome rather than a signal of relative alliance
   strength. That is exactly the wrong kind of example for a model whose
   whole job is learning "which alliance is stronger" from the recorded
   winner, so these are excluded by default. This is a judgment call, not a
   structural necessity -- call build_training_frame(..., include_dq_affected
   =True) to keep them (and dq_status_unknown-excluded matches -- see below)
   instead; every excluded match is still named, counted by reason, and
   never silently dropped either way.

   TBA's raw match payload -- confirmed 2026-09-24 against TBA's own live
   OpenAPI spec (github.com/the-blue-alliance/the-blue-alliance,
   src/backend/web/static/swagger/api_v3.json, schema "Match_alliance") --
   really does carry dq_team_keys (and surrogate_team_keys) per alliance,
   resolving the "UNVERIFIED" caveat CLAUDE.md and RUNNING_NOTES.md have
   carried on these exact field names since Phase 3 M15. Both are REQUIRED
   fields on every alliance TBA has ever returned. Confirmed at the same time:
   TBA has no "no-show" concept distinct from DQ (a no-show is recorded as a
   DQ), so "DQ / no-show" in the milestone brief is one rule, not two; and
   TBA has no "replay" concept at all -- match_key is already TBA's one
   canonical, continuously-updated record per match, so there is nothing for
   a separate replay-exclusion rule to do.

   Neither field reached this codebase's canonical schema, though --
   data/clients/schemas.py's MatchAllianceResult only ever parsed score and
   team_keys. But the untouched TBA response body is preserved in full at
   raw_source_payloads.payload_json (data/clients/source_connector.py's
   SourceResponse.raw is what the landing layer stores), keyed by
   source_object_id = the same match_key used everywhere else
   (data/pipeline.py: RawPayloadRecord(SOURCE_TBA, OBJECT_TYPE_MATCH,
   payload["key"], payload)). So this module reads that raw JSON directly,
   additively -- no migration, no change to matches/match_teams, nothing
   touched in Kanav's M3-M10 computation logic.

5. dq_status_unknown -- no current raw TBA payload was found for this match
   at all, so DQ/surrogate status cannot be determined from data this system
   holds. Every real match synced through this codebase's own TBA pipeline
   has one (it is how the match itself got into the matches table in the
   first place); this only fires for a match inserted by some other path
   (most likely a hand-built test fixture). Treating "unknown" as "assume no
   DQ" would be exactly the kind of fabricated certainty CLAUDE.md's ML
   principles forbid, so it is excluded rather than guessed at -- unless
   include_dq_affected=True, in which case the caller has already opted out
   of DQ-based filtering entirely and the row is kept with
   dq_status_known=False so a downstream consumer can still filter on it.

Kept, not excluded
===================
- comp_level (qualification vs playoff): both kept by default, tagged on
  every row (comp_level field) so a downstream consumer (Milestone 3's
  temporal split, Milestone 5's training) can filter or stratify by it.
  Nothing in this milestone's brief calls for dropping either.
- Ties: label = "tie" (from winning_alliance = "tie"), never coerced to a
  fabricated red/blue winner and never dropped.
- Surrogates: a team playing as a surrogate genuinely was on the field and
  contributed to its alliance's recorded score, so its match is kept. The
  surrogate team numbers are recorded (red_surrogate_team_numbers /
  blue_surrogate_team_numbers) rather than silently absorbed, for
  observability -- a future milestone may decide a surrogate appearance
  should not count toward *that team's own* scoring history the way
  Milestone 1's _point_in_time_scores currently counts every rostered match
  unconditionally. That is a real, related gap this module's own research
  surfaced, not something this milestone's scope authorizes fixing --
  documented here and in RUNNING_NOTES.md rather than patched silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, Field, model_validator

from data.landing.raw_writer import compute_payload_checksum
from data.pipeline import OBJECT_TYPE_MATCH, SOURCE_TBA
from data.staging.normalizer import parse_tba_team_number
from database.connection import Database
from ml.features.assembler import MatchFeatureRow, TeamFeatures, build_match_feature_row

__all__ = [
    "DATASET_BUILDER_VERSION",
    "EXCLUSION_REASON_DQ_AFFECTED",
    "EXCLUSION_REASON_DQ_STATUS_UNKNOWN",
    "EXCLUSION_REASON_NO_SCHEDULED_TIME",
    "EXCLUSION_REASON_UNPLAYED",
    "EXCLUSION_REASON_WINNING_ALLIANCE_MISSING",
    "LABEL_BLUE_WIN",
    "LABEL_RED_WIN",
    "LABEL_TIE",
    "TRAINING_ROW_ARROW_SCHEMA",
    "DatasetManifest",
    "ExcludedMatch",
    "PersistedDataset",
    "TrainingFrameResult",
    "TrainingRow",
    "build_training_frame",
    "persist_training_frame",
]

# Bumped whenever the row schema or an inclusion/exclusion rule changes --
# recorded on every DatasetManifest so a consumer (Milestone 10's model
# registry, eventually) can tell which build logic produced a given artifact
# without diffing this file against it.
DATASET_BUILDER_VERSION = "1.0.0"

# --- exclusion reasons -------------------------------------------------
# Module-level string constants, not an Enum -- matching this codebase's
# existing convention for a closed vocabulary of reasons
# (data.staging.quality's severity constants, data.metrics.read's STATUS_*).
EXCLUSION_REASON_NO_SCHEDULED_TIME = "no_scheduled_time"
EXCLUSION_REASON_UNPLAYED = "unplayed"
EXCLUSION_REASON_WINNING_ALLIANCE_MISSING = "winning_alliance_missing"
EXCLUSION_REASON_DQ_AFFECTED = "dq_affected"
EXCLUSION_REASON_DQ_STATUS_UNKNOWN = "dq_status_unknown"

# --- labels --------------------------------------------------------------
LABEL_RED_WIN = "red_win"
LABEL_BLUE_WIN = "blue_win"
LABEL_TIE = "tie"

_WINNING_ALLIANCE_TO_LABEL = {"red": LABEL_RED_WIN, "blue": LABEL_BLUE_WIN, "tie": LABEL_TIE}


class TrainingRow(BaseModel):
    """One labeled, leakage-safe training example: one match, one outcome.

    red_teams/blue_teams are exactly build_match_feature_row's own output for
    this match_key at as_of=scheduled_time -- this model adds nothing to
    Milestone 1's feature computation, only the label alongside it.

    label and score_margin are independently sourced (label from
    matches.winning_alliance, score_margin from matches.score_red -
    matches.score_blue) and are NOT asserted consistent with each other here:
    data.staging.normalizer._derive_winning_alliance prefers TBA's own
    explicit winning_alliance over a score-derived one when TBA supplies it,
    so a real (rare) divergence -- a post-match penalty adjustment changing
    the recorded winner without changing the posted score -- is possible and
    legitimate. Asserting agreement would make this model crash on genuine
    real data instead of faithfully carrying what each source actually says.
    """

    match_key: str = Field(min_length=1)
    event_key: str = Field(min_length=1)
    season: int
    comp_level: str = Field(min_length=1)
    set_number: int | None = None
    match_number: int | None = None
    scheduled_time: datetime
    label: str
    score_margin: int
    score_red: int
    score_blue: int
    red_teams: list[TeamFeatures] = Field(default_factory=list)
    blue_teams: list[TeamFeatures] = Field(default_factory=list)
    red_surrogate_team_numbers: list[int] = Field(default_factory=list)
    blue_surrogate_team_numbers: list[int] = Field(default_factory=list)
    dq_status_known: bool

    @model_validator(mode="after")
    def _check_label_is_known(self) -> "TrainingRow":
        if self.label not in _WINNING_ALLIANCE_TO_LABEL.values():
            raise ValueError(f"label={self.label!r} is not one of {sorted(_WINNING_ALLIANCE_TO_LABEL.values())}")
        if self.scheduled_time.tzinfo is None:
            raise ValueError("scheduled_time must be timezone-aware")
        return self


class ExcludedMatch(BaseModel):
    """One match this build considered and did not include, with exactly why.

    Every excluded match is named here -- "never silently dropped", per the
    milestone's own instruction -- even though only counts (DatasetManifest.
    excluded_by_reason) are typically what a caller inspects first.
    """

    match_key: str = Field(min_length=1)
    event_key: str = Field(min_length=1)
    season: int
    reason: str
    detail: str | None = None


class DatasetManifest(BaseModel):
    """Everything needed to know what a training-frame artifact is, without
    re-reading the database it came from.

    content_hash deliberately excludes build_date from what it hashes: two
    builds against unchanged underlying data, run on different days, must
    produce the identical hash (the milestone's own idempotency requirement),
    which build_date -- true wall-clock time of this specific build -- would
    break if it were part of the hashed payload.
    """

    season_keys: list[int]
    include_dq_affected: bool
    code_version: str
    build_date: datetime
    row_count: int
    excluded_count: int
    excluded_by_reason: dict[str, int]
    content_hash: str


class TrainingFrameResult(BaseModel):
    """The full output of one build_training_frame call: rows, exclusions, and the manifest describing both."""

    rows: list[TrainingRow]
    excluded: list[ExcludedMatch]
    manifest: DatasetManifest


class PersistedDataset(BaseModel):
    """Where one TrainingFrameResult was written, and the manifest that describes it."""

    parquet_path: Path
    manifest_path: Path
    manifest: DatasetManifest


# --- Arrow schema ----------------------------------------------------------
# Declared explicitly (not inferred from the row data via pa.Table.from_
# pylist's own type inference) for two reasons: inference cannot resolve a
# schema from zero rows at all (a real case -- a season with nothing synced,
# or everything excluded, must still persist a valid, readable empty
# artifact, not crash the build), and an explicit schema is what keeps every
# build of the same code version byte-comparable in shape regardless of
# which optional fields happen to be populated in any given row.
#
# This does duplicate TrainingRow/TeamFeatures' field lists by hand, which is
# exactly the kind of duplication this codebase otherwise avoids -- accepted
# here because a fully generic pydantic-to-Arrow type mapper is a bigger
# abstraction than one milestone's dataset schema justifies. The drift risk
# is closed by a contract test (tests/test_ml_dataset_builder.py) asserting
# these field names exactly match TrainingRow.model_fields / TeamFeatures.
# model_fields, the same discipline Phase 3 M15 applies to documentation.
_TEAM_FEATURES_ARROW_TYPE = pa.struct([
    ("team_number", pa.int64()),
    ("epa_total", pa.float64()),
    ("epa_total_present", pa.bool_()),
    ("epa_auto", pa.float64()),
    ("epa_auto_present", pa.bool_()),
    ("epa_teleop", pa.float64()),
    ("epa_teleop_present", pa.bool_()),
    ("epa_endgame", pa.float64()),
    ("epa_endgame_present", pa.bool_()),
    ("epa_source_event_key", pa.string()),
    ("epa_withheld_reason", pa.string()),
    ("average_score", pa.float64()),
    ("average_score_present", pa.bool_()),
    ("score_stddev", pa.float64()),
    ("score_stddev_present", pa.bool_()),
    ("consistency_rating", pa.float64()),
    ("consistency_rating_present", pa.bool_()),
    ("reliability_score", pa.float64()),
    ("reliability_score_present", pa.bool_()),
    ("matches_considered", pa.int64()),
    ("matches_used", pa.int64()),
    ("average_auto_points", pa.float64()),
    ("average_auto_points_present", pa.bool_()),
    ("auto_points_matches_used", pa.int64()),
    ("defense_score", pa.float64()),
    ("defense_score_present", pa.bool_()),
    ("defense_agreement", pa.float64()),
    ("defense_agreement_present", pa.bool_()),
    ("defense_observation_count", pa.int64()),
    ("feeding_score", pa.float64()),
    ("feeding_score_present", pa.bool_()),
    ("feeding_agreement", pa.float64()),
    ("feeding_agreement_present", pa.bool_()),
    ("feeding_observation_count", pa.int64()),
    ("contributing_scouting_sources", pa.list_(pa.string())),
])

TRAINING_ROW_ARROW_SCHEMA = pa.schema([
    ("match_key", pa.string()),
    ("event_key", pa.string()),
    ("season", pa.int64()),
    ("comp_level", pa.string()),
    ("set_number", pa.int64()),
    ("match_number", pa.int64()),
    ("scheduled_time", pa.timestamp("us", tz="UTC")),
    ("label", pa.string()),
    ("score_margin", pa.int64()),
    ("score_red", pa.int64()),
    ("score_blue", pa.int64()),
    ("red_teams", pa.list_(_TEAM_FEATURES_ARROW_TYPE)),
    ("blue_teams", pa.list_(_TEAM_FEATURES_ARROW_TYPE)),
    ("red_surrogate_team_numbers", pa.list_(pa.int64())),
    ("blue_surrogate_team_numbers", pa.list_(pa.int64())),
    ("dq_status_known", pa.bool_()),
])


def _fetch_season_matches(database: Database, season_keys: Sequence[int]) -> list[tuple[Any, ...]]:
    """Every matches row for these seasons, in a fixed, fully deterministic order.

    ORDER BY event_key, scheduled_time NULLS LAST, match_key -- not just
    match_key alone -- so the row order (and therefore DatasetManifest.
    content_hash) is stable regardless of how season_keys was ordered by the
    caller, and NULLS LAST keeps a no-scheduled-time match (excluded, but
    still visited) in a reproducible position rather than an
    engine-dependent one.
    """
    if not season_keys:
        return []
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT match_key, event_key, season, competition_level, set_number,
                   match_number, scheduled_time, score_red, score_blue, winning_alliance
            FROM matches
            WHERE season = ANY(%s::int[])
            ORDER BY event_key, scheduled_time NULLS LAST, match_key
            """,
            (list(season_keys),),
        )
        return cursor.fetchall()


def _fetch_current_raw_tba_match_payloads(database: Database, match_keys: Sequence[str]) -> dict[str, Any]:
    """The current raw TBA payload for each of these match_keys, keyed by match_key.

    A match_key absent from the returned dict has no current raw TBA
    payload landed -- see EXCLUSION_REASON_DQ_STATUS_UNKNOWN. Mirrors data.
    pipeline.read_pending's own is_current + source + source_object_type
    filter exactly, the established convention for reading a landed payload
    back out (data/pipeline.py:389-403), applied here for a fixed list of
    already-known match_keys rather than a watermark-bounded batch.

    ORDER BY id, with a later row overwriting an earlier one of the same
    match_key in the dict comprehension below, is belt-and-braces against
    the (should-be-impossible, per data/landing/raw_writer.py's own
    documented invariant) case of more than one is_current row for the same
    key: the most recently landed one wins, deterministically, rather than
    whichever the database happens to return first.
    """
    if not match_keys:
        return {}
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, source_object_id, payload_json
            FROM raw_source_payloads
            WHERE source = %s AND source_object_type = %s
              AND source_object_id = ANY(%s::text[])
              AND is_current
            ORDER BY id
            """,
            (SOURCE_TBA, OBJECT_TYPE_MATCH, list(match_keys)),
        )
        rows = cursor.fetchall()
    return {source_object_id: payload_json for _id, source_object_id, payload_json in rows}


def _team_numbers_from_keys(team_keys: Sequence[str]) -> list[int]:
    """Resolve TBA team keys (e.g. 'frc1114') to team numbers, dropping any that don't parse.

    Reuses data.staging.normalizer.parse_tba_team_number so the B-team
    ('frc254b' -> 254) collapsing rule stays in exactly one place. A key that
    still fails to parse (never observed against real TBA data, which is why
    this drops rather than raises) is skipped rather than crashing the whole
    build over one malformed entry in an otherwise-usable payload.
    """
    numbers: list[int] = []
    for team_key in team_keys:
        try:
            numbers.append(parse_tba_team_number(team_key))
        except (AssertionError, TypeError):
            # AssertionError: parse_tba_team_number's own regex-match assertion
            # failed (a key that isn't shaped like "frc<digits>[letter]").
            # TypeError: team_key wasn't even a string (a malformed payload).
            # Either way this is a payload authenticity concern, not something
            # worth aborting the whole dataset build over.
            continue
    return numbers


def _as_dict(value: Any) -> dict[str, Any]:
    """value if it's a dict, else {} -- including when value is explicitly None.

    Plain dict.get(key, {}) only supplies its default when the key is
    *absent*; a payload with an explicit "alliances": {"red": null, ...}
    still returns None from .get("red", {}), which would crash the next
    .get() call. This closes that gap at every nesting level.
    """
    return value if isinstance(value, dict) else {}


def _parse_dq_and_surrogates(payload_json: Any) -> tuple[list[int], list[int], list[int], list[int]]:
    """Extract (red_dq, blue_dq, red_surrogate, blue_surrogate) team numbers from a raw TBA match payload.

    TBA's Match_alliance schema marks dq_team_keys/surrogate_team_keys
    REQUIRED on every alliance (verified 2026-09-24 against TBA's live
    api_v3.json -- see this module's docstring). A key missing from a
    payload we do have is therefore treated as an empty list, not as
    "unknown" -- unknown is what "no payload at all" means (see
    EXCLUSION_REASON_DQ_STATUS_UNKNOWN), and once a payload is in hand a
    missing key inside it is the same as an explicit [] for any payload
    shaped like TBA's real API. This only degrades for a hand-built payload
    that omits the key entirely (some test fixtures), never for live TBA data.
    """
    alliances = _as_dict(_as_dict(payload_json).get("alliances"))
    red = _as_dict(alliances.get("red"))
    blue = _as_dict(alliances.get("blue"))
    return (
        _team_numbers_from_keys(red.get("dq_team_keys") or []),
        _team_numbers_from_keys(blue.get("dq_team_keys") or []),
        _team_numbers_from_keys(red.get("surrogate_team_keys") or []),
        _team_numbers_from_keys(blue.get("surrogate_team_keys") or []),
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_training_frame(
    database: Database, season_keys: Sequence[int], *, include_dq_affected: bool = False,
) -> TrainingFrameResult:
    """Build the labeled training frame for every qualifying match in these seasons.

    season_keys is a list of season years (matches.season, e.g. [2024,
    2026]) -- matching Settings/the TBA client's own "year" vocabulary, not
    event keys. An empty season_keys produces an empty, valid result rather
    than raising: this is a real, well-formed answer ("nothing to build"),
    not a caller error.

    include_dq_affected=False (the default) excludes EXCLUSION_REASON_
    DQ_AFFECTED and EXCLUSION_REASON_DQ_STATUS_UNKNOWN matches -- see this
    module's docstring for the full rationale. =True keeps both (dq_status_
    known=False on a kept row whose DQ status could not be determined),
    opting out of DQ-based filtering entirely rather than only halfway.

    Deterministic: same database contents + same arguments always produce
    the same rows in the same order and the same DatasetManifest.
    content_hash -- see _fetch_season_matches' own ORDER BY for how row
    order is pinned regardless of season_keys' input order.
    """
    match_rows = _fetch_season_matches(database, season_keys)

    excluded: list[ExcludedMatch] = []
    candidates: list[tuple[Any, ...]] = []
    for row in match_rows:
        match_key, event_key, season, comp_level, set_number, match_number, scheduled_time, score_red, score_blue, winning_alliance = row
        if scheduled_time is None:
            excluded.append(ExcludedMatch(
                match_key=match_key, event_key=event_key, season=season, reason=EXCLUSION_REASON_NO_SCHEDULED_TIME,
            ))
            continue
        if score_red is None or score_blue is None:
            excluded.append(ExcludedMatch(
                match_key=match_key, event_key=event_key, season=season, reason=EXCLUSION_REASON_UNPLAYED,
            ))
            continue
        if winning_alliance not in _WINNING_ALLIANCE_TO_LABEL:
            excluded.append(ExcludedMatch(
                match_key=match_key, event_key=event_key, season=season,
                reason=EXCLUSION_REASON_WINNING_ALLIANCE_MISSING,
                detail=f"winning_alliance={winning_alliance!r}",
            ))
            continue
        candidates.append(row)

    raw_payloads = _fetch_current_raw_tba_match_payloads(database, [row[0] for row in candidates])

    rows: list[TrainingRow] = []
    for row in candidates:
        match_key, event_key, season, comp_level, set_number, match_number, scheduled_time, score_red, score_blue, winning_alliance = row

        payload_json = raw_payloads.get(match_key)
        dq_status_known = payload_json is not None
        if dq_status_known:
            red_dq, blue_dq, red_surrogate, blue_surrogate = _parse_dq_and_surrogates(payload_json)
        else:
            red_dq, blue_dq, red_surrogate, blue_surrogate = [], [], [], []

        if not include_dq_affected:
            if not dq_status_known:
                excluded.append(ExcludedMatch(
                    match_key=match_key, event_key=event_key, season=season,
                    reason=EXCLUSION_REASON_DQ_STATUS_UNKNOWN,
                    detail="no current raw TBA match payload found in raw_source_payloads",
                ))
                continue
            if red_dq or blue_dq:
                excluded.append(ExcludedMatch(
                    match_key=match_key, event_key=event_key, season=season, reason=EXCLUSION_REASON_DQ_AFFECTED,
                    detail=f"red_dq_team_numbers={sorted(red_dq)}, blue_dq_team_numbers={sorted(blue_dq)}",
                ))
                continue

        feature_row: MatchFeatureRow = build_match_feature_row(database, match_key, as_of=scheduled_time)
        assert feature_row.event_key == event_key and feature_row.season == season, (
            f"build_match_feature_row returned event_key/season {feature_row.event_key!r}/{feature_row.season!r} "
            f"inconsistent with matches row {event_key!r}/{season!r} for {match_key!r}"
        )

        rows.append(TrainingRow(
            match_key=match_key,
            event_key=event_key,
            season=season,
            comp_level=comp_level or "unknown",
            set_number=set_number,
            match_number=match_number,
            scheduled_time=scheduled_time,
            label=_WINNING_ALLIANCE_TO_LABEL[winning_alliance],
            score_margin=score_red - score_blue,
            score_red=score_red,
            score_blue=score_blue,
            red_teams=feature_row.red_teams,
            blue_teams=feature_row.blue_teams,
            red_surrogate_team_numbers=sorted(red_surrogate),
            blue_surrogate_team_numbers=sorted(blue_surrogate),
            dq_status_known=dq_status_known,
        ))

    excluded_by_reason: dict[str, int] = {}
    for item in excluded:
        excluded_by_reason[item.reason] = excluded_by_reason.get(item.reason, 0) + 1

    content_hash = _compute_content_hash(season_keys, include_dq_affected, rows)

    manifest = DatasetManifest(
        season_keys=sorted(season_keys),
        include_dq_affected=include_dq_affected,
        code_version=DATASET_BUILDER_VERSION,
        build_date=_utcnow(),
        row_count=len(rows),
        excluded_count=len(excluded),
        excluded_by_reason=excluded_by_reason,
        content_hash=content_hash,
    )

    return TrainingFrameResult(rows=rows, excluded=excluded, manifest=manifest)


def _compute_content_hash(season_keys: Sequence[int], include_dq_affected: bool, rows: list[TrainingRow]) -> str:
    """A deterministic fingerprint of what build_training_frame produced.

    Reuses data.landing.raw_writer.compute_payload_checksum -- the same
    sorted-key, no-incidental-whitespace canonicalization this codebase
    already uses to fingerprint a raw payload -- rather than inventing a
    second hashing convention. season_keys is sorted here (independent of
    DatasetManifest.season_keys, which callers may reasonably expect to
    reflect their own input order) purely so [2024, 2026] and [2026, 2024]
    -- the same logical request -- hash identically.
    """
    canonical_payload = {
        "season_keys": sorted(season_keys),
        "include_dq_affected": include_dq_affected,
        "code_version": DATASET_BUILDER_VERSION,
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    return compute_payload_checksum(canonical_payload)


def persist_training_frame(result: TrainingFrameResult, output_dir: Path) -> PersistedDataset:
    """Write one TrainingFrameResult to disk as a parquet artifact plus a JSON manifest.

    output_dir has no default -- like Milestone 1's as_of, forcing every
    caller to state explicitly where an artifact lands rather than writing
    to an implicit, easy-to-lose location. The parquet/manifest filenames are
    derived from the manifest's own content_hash (first 16 hex chars) so two
    builds of identical content always collide onto the same filename
    (rewriting, not duplicating) while two builds of different content never
    do.

    Rows are dumped with mode="python" (not "json") for the parquet write --
    real datetime objects, not ISO strings, so TRAINING_ROW_ARROW_SCHEMA's
    scheduled_time column lands as an actual Arrow timestamp column, queryable
    as one by any downstream reader, rather than an opaque string.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = f"training_frame_{result.manifest.content_hash[:16]}"
    parquet_path = output_dir / f"{stem}.parquet"
    manifest_path = output_dir / f"{stem}.manifest.json"

    table = pa.Table.from_pylist(
        [row.model_dump(mode="python") for row in result.rows], schema=TRAINING_ROW_ARROW_SCHEMA,
    )
    pq.write_table(table, parquet_path)

    manifest_path.write_text(result.manifest.model_dump_json(indent=2), encoding="utf-8")

    return PersistedDataset(parquet_path=parquet_path, manifest_path=manifest_path, manifest=result.manifest)
