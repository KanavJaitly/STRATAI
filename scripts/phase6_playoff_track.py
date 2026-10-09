"""The playoff track and alliance-selection validations: P6-M1 (a/b), PX-1, PX-2, PX-4, P6-M6 (b) and P6-M8.

    python -m scripts.phase6_playoff_track m1|m2|m3|m5|m6b|m8|m8-review   # DATABASE_URL = an isolated stratai_test copy
    python -m scripts.phase6_playoff_track m1-2027                        # C0: P6-M1 on 2027 events (approved 2027 ruleset)
    python -m scripts.phase6_playoff_track px2b|px4b|m8b|m8b-review       # C4: the versioned PX-1b chain; each refuses
                                                                          # until PX-1b is accepted and its prerequisites exist

**Every run refuses, writing nothing, unless approved P6-M1 rulesets exist for 2024, 2025 and 2026.** They are
human inputs entered from the manuals with a named reviewer, and no rule is hard-coded instead.

**Prerequisites, all D9:**
- m2 needs m1's record.
- m3 needs a PX-1 pass.
- m5 needs a PX-2 pass.
- m8 needs a PX-4 pass and its own dated pre-run record (`.agent/phase6/decisions/P6_M8_PRE_RUN.md`: the population,
  seed, strata and reason categories).
- A failed prerequisite stops the dependent run unless Kanav records a dated decision.

**Records** are write-once in `.agent/phase6/results/`. Each run has a hard 45-minute budget.

Specification: `docs/P6Milestones.md`, `.agent/phase6/P6_M2_PX1_SPEC.md`, and the dated decisions in
`.agent/phase6/decisions/P6_PX1_COMPOSITION_DECISIONS.md`:
- Compositions are the selection-time members (`ml.playoffs.data.selection_members`). Backups are never included.
- Events whose alliances have four members are outside PX-1's frozen three-team representation (FIRST Championship
  divisions, from the ruleset's cited variant). They are excluded from PX-1, PX-4 and M8 and counted by event.
- Each record keeps the intended population next to the validated one.
"""

from __future__ import annotations

import gzip
import json
import pickle
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from scripts.phase6_common import (REGISTRY_DIR, RESULTS_DIR, git_blob, isolated_database, load_m6m7, read_record,
                                   write_once)

SEASONS, TRAIN, HELD_OUT = (2024, 2025, 2026), (2024, 2025), 2026
BUDGET_SECONDS = 45 * 60
BOOTSTRAP_SEED = 20261010
EXCLUSION_ESCALATION_SHARE = 0.10  # P6-Q13
SNAPSHOT = Path("C:/Dev/StratAI-artifacts/statbotics/statbotics_snapshot_20261001T220423Z")
CHAIN = Path("C:/Dev/StratAI-artifacts/ratings/epa-chain/chain_e77d9444c57a7b50.json")
ROWS_CACHE_DIR = Path("C:/Dev/StratAI-artifacts/phase6")
M8_PRE_RUN = Path(".agent/phase6/decisions/P6_M8_PRE_RUN.md")
# Kanav's 2026-10-06 decisions D-PX1-1..5 and the C1/C2 approvals: selection-time members, and the four-member
# (FIRST Championship division) exclusion from PX-1, PX-4 and M8. Every affected record carries this file's blob.
COMPOSITION_DECISIONS = ".agent/phase6/decisions/P6_PX1_COMPOSITION_DECISIONS.md"
FOUR_MEMBER = "four_member_alliance"
PLAYOFF_BEFORE_SELECTION = "playoff_before_selection_moment"


@dataclass(frozen=True)
class PlayoffTrack:
    """Where one playoff-model chain's PX-2 -> PX-4 -> M8 runs point (C4, approved 2026-10-08).

    `PX1_TRACK` is the frozen P6-M3/M5/M8 chain and every run's default, with its pointers exactly as before.
    `PX1B_TRACK` is the versioned PX-2b/PX-4b/M8b chain (`P6_M3_PX2B_SPEC.md`, `P6_M5_PX4B_SPEC.md`,
    `P6_M8B_SPEC.md`). Its model prerequisite is PX-1b's FINAL-1 pass plus Kanav's sha-matched confirmation."""

    name: str
    model_record: str  # the playoff model's own gate record (passed required)
    confirmation: Path | None  # Kanav's dated confirmation of that record (PX-1b only)
    model_type: str
    seed_only_type: str
    version_tag: str
    calibration_season: int
    holdout: int
    m1_records: tuple[str, ...]
    px2_record: str
    px4_record: str
    m8_run_record: str
    m8_record: str
    calibrator_file: str
    m8_pre_run: Path
    m8_pre_run_json: Path
    m8_review_json: Path
    sentinel_time: str
    epa_snapshot: Path | None  # the D18 EPA source; None = not yet configured for this track's seasons
    epa_chain: Path | None
    exclude_playoffs_before_selection: bool
    specs: dict[str, str] | None = None  # the versioned specs, cited in each record (PX-1b only)
    requires_mentor_agreement: bool = False
    calibration_base_record: str | None = None  # PX-2b v2: out-of-sample calibration from this base model's record


class Blocked(SystemExit):
    def __init__(self, reason: str) -> None:
        print(f"BLOCKED: {reason}", file=sys.stderr)
        super().__init__(2)


def require_rulesets(database, seasons=None) -> dict[int, Any]:
    """The approved ruleset of every season in `seasons` (default: SEASONS, read at call time); refuses if any is
    not approved."""
    from data.rulesets import approved_ruleset, approved_seasons

    required = tuple(SEASONS if seasons is None else seasons)
    try:
        approved = approved_seasons(database)
    except Exception as exc:  # e.g. migration 0011 not applied to this database
        raise Blocked(f"no season_rulesets table ({type(exc).__name__}): migration 0011 must be applied") from exc
    missing = [s for s in required if s not in approved]
    if missing:
        raise Blocked(f"no approved P6-M1 ruleset for {missing}: rulesets are entered from the manuals and approved "
                      "by a named reviewer (scripts.phase6_rulesets)")
    return {s: approved_ruleset(database, s) for s in required}


def _require(name: str, *, passed_key: str | None = None) -> dict[str, Any]:
    record = read_record(name)
    if record is None:
        raise Blocked(f"{name} has not been recorded")
    if passed_key and not record.get(passed_key):
        raise Blocked(f"{name} did not pass ({passed_key} false): the prerequisite gate failed, so dependent "
                      "runs remain blocked under the frozen D9 rule")
    return record


# --- P6-M1 (a)/(b) -------------------------------------------------------------------------------------------


def run_m1(database, rulesets: dict[int, Any], *, limit: int | None = None, seasons=None) -> dict[str, Any]:
    from data.rankings import read_final_ranks_for_season
    from data.rulesets import RulesetError
    from ml.playoffs.data import event_bracket, map_matches, read_event_playoffs
    from ml.playoffs.evaluation import reproduce_bracket

    per_season, events_out = {}, {}
    for season in (SEASONS if seasons is None else seasons):
        ruleset = rulesets[season]
        events = read_event_playoffs(database, season)[:limit]
        ranks = read_final_ranks_for_season(database, season)
        counts: Counter[str] = Counter()
        variants: Counter[str] = Counter()
        selection_violations = []
        selection_not_established: Counter[str] = Counter()
        for event in events:
            if not event.alliances:
                counts["no_alliances"] += 1
                status = "excluded:no_alliances"
            elif event.division_champion:
                counts["division_champion"] += 1
                status = "excluded:division_champion"
            else:
                try:
                    event_rules = ruleset.for_event(event.event_key)  # explicit variant, else the season default
                except RulesetError as exc:  # an event_exclusions entry: excluded and counted, never approximated
                    reason = (exc.details or {}).get("reason", exc.code)
                    counts[f"ruleset_exclusion:{reason}"] += 1
                    events_out[event.event_key] = {"status": f"excluded:ruleset_exclusion:{reason}",
                                                   "problems": [str(exc)]}
                    continue
                variants[event_rules.variant or "season_default"] += 1
                try:
                    bracket = event_bracket(event, ruleset)
                except RulesetError as exc:
                    counts[f"not_represented:{exc.code}"] += 1
                    events_out[event.event_key] = {"status": f"excluded:{exc.code}", "problems": [str(exc)]}
                    continue
                matches, unmapped = map_matches(event)
                result = reproduce_bracket(bracket, matches)
                problems = list(result.problems) + [f"{n} unmappable sides" for n in unmapped.values() if n]
                status = "reproduced" if not problems else "excluded:reproduction_failed"
                counts[status] += 1
                events_out[event.event_key] = {"status": status, "problems": problems[:10],
                                               "selection_variant": event_rules.variant,
                                               "winner_seed": result.winner_seed,
                                               "finalist_seed": result.finalist_seed}
                violations, not_established = _captain_rule_violations(event, ranks.get(event.event_key, {}),
                                                                       event_rules)
                selection_violations.extend(violations)
                selection_not_established.update(not_established)
                continue
            events_out[event.event_key] = {"status": status}
        excluded = sum(v for k, v in counts.items() if k != "reproduced")
        share = excluded / len(events) if events else 0.0
        per_season[season] = {"events": len(events), "counts": dict(counts), "excluded_share": share,
                              "escalate": share > EXCLUSION_ESCALATION_SHARE,
                              "selection_variants": dict(variants),
                              "selection_rule_violations": len(selection_violations),
                              "selection_rule_not_established": dict(selection_not_established),
                              "selection_rule_examples": selection_violations[:20],
                              "ruleset_sha256": ruleset.sha256()}
    return {"milestone": "P6-M1", "seasons": per_season, "events": events_out,
            "escalate": any(s["escalate"] for s in per_season.values())}


def run_m1_2027(database, rulesets) -> dict[str, Any]:
    """C0 (D9 v1, approved 2026-10-08): the frozen P6-M1 check, unchanged, on 2027 events only, as its own record.
    It needs the approved 2027 ruleset (`main` refuses without it) and 2027 playoff data."""
    from scripts.phase6_px1b import _playoff_matches

    if not _playoff_matches(database, 2027):
        raise Blocked("no 2027 playoff data: the 2027 P6-M1 check runs after the 2027 season is complete and synced")
    return {**run_m1(database, rulesets, seasons=(2027,)), "proposal": "C0",
            "decisions": ".agent/phase6/decisions/P6_D9_PX1B_APPROVALS_C0_C4_2026-10-08.md"}


def _captain_rule_violations(event, ranks: dict[int, int], event_rules) -> tuple[list[str], Counter[str]]:
    """P6-M1 (b): alliance k's captain is the best-ranked team still available when seed k's first turn comes.

    In a serpentine draft that is after the earlier alliances' captains and round-1 picks, and before any round-2
    pick. A team declined earlier is excluded when the rules bar it from becoming captain. A violation is listed,
    never forced to pass.

    A rule that is null (not established, D-PX1-4/5) is never guessed:
    - a null captain rule leaves every alliance unchecked, counted `captain_rule_not_established`;
    - a null decline rule leaves an alliance unchecked only where a recorded decline would decide it, counted
      `decline_rule_not_established` (TBA records 0 declines in 2024-2026)."""
    out, taken, unchecked = [], set(), Counter()
    rules = event_rules.selection
    if rules.captain_rule is None:
        unchecked["captain_rule_not_established"] += len(event.alliances)
        return out, unchecked
    declined = {t for a in event.alliances for t in a.declines}
    for alliance in sorted(event.alliances, key=lambda a: a.seed):
        available = [t for t in ranks if t not in taken]
        if (rules.declined_team_may_become_captain is None and available
                and min(available, key=lambda t: ranks[t]) in declined):
            unchecked["decline_rule_not_established"] += 1
            taken.update(alliance.picks[:2])
            continue
        eligible = [t for t in available if rules.declined_team_may_become_captain or t not in declined]
        if eligible and alliance.captain in ranks and ranks[alliance.captain] > min(ranks[t] for t in eligible):
            best = min(eligible, key=lambda t: ranks[t])
            out.append(f"{event.event_key} seed {alliance.seed}: captain {alliance.captain} (rank "
                       f"{ranks[alliance.captain]}) while {best} (rank {ranks[best]}) was available")
        taken.update(alliance.picks[:2])  # the captain and its round-1 pick precede the next seed's turn
    return out, unchecked


# --- PX-1 / PX-2 / PX-4 -------------------------------------------------------------------------------------


def assemble_rows(database, rulesets, m1: dict[str, Any], *, limit: int | None = None, seasons=None, snapshot=None,
                  chain=None):
    """PX-1 rows for every reproduced, seeded event (§1), with selection-moment features.

    Compositions are the selection-time members (D-PX1-1). Four-member rows are excluded and counted per event
    (D-PX1-2). Also returns the per-event exclusions that are not the frozen per-row reasons."""
    from data.rulesets import RulesetError
    from ml.features.scale import ScaleLookup
    from ml.playoffs.data import event_bracket, event_members, playoff_rows, read_event_playoffs, selection_features
    from ml.ratings.d18_source import load_d18_provider

    provider, integrity = load_d18_provider(database, snapshot or SNAPSHOT, chain or CHAIN)
    scales = ScaleLookup(database)
    rows, excluded, features_by_event, events_by_key = [], Counter(), {}, {}
    by_event: dict[str, dict[str, Any]] = {}
    for season in (SEASONS if seasons is None else seasons):
        for event in read_event_playoffs(database, season)[:limit]:
            if m1["events"].get(event.event_key, {}).get("status") != "reproduced":
                excluded["event_not_reproduced_or_excluded"] += 1
                continue
            event_rules = rulesets[season].for_event(event.event_key)
            try:
                members = event_members(event, event_rules)
            except RulesetError as exc:  # a listing the event's rules do not explain: excluded, counted, never read
                excluded[f"event_{exc.code}"] += 1
                by_event[event.event_key] = {"reason": f"event_{exc.code}", "matches": len(event.matches)}
                continue
            teams = {t for m in members.values() for t in m}
            features = selection_features(database, event, teams, provider=provider, scales=scales)
            event_rows, event_excluded = playoff_rows(event, event_bracket(event, rulesets[season]), features,
                                                      event_rules)
            rows.extend(event_rows)
            excluded.update(event_excluded)
            if event_excluded.get(FOUR_MEMBER):
                by_event[event.event_key] = {"reason": FOUR_MEMBER, "rows": event_excluded[FOUR_MEMBER],
                                             "selection_variant": event_rules.variant}
            features_by_event[event.event_key] = features
            events_by_key[event.event_key] = event
    return rows, excluded, features_by_event, events_by_key, integrity, by_event


def _m6m7_on(row) -> float:
    from ml.features.assembler import MatchFeatureRow

    return M6M7.predict_win_prob(MatchFeatureRow(match_key=row.match_key, as_of=row.scheduled_time,
                                                 event_key=row.event_key, season=row.season,
                                                 red_teams=list(row.red_teams), blue_teams=list(row.blue_teams)))


M6M7 = None
# P6-M2 rerun1 after the PX-1 audit (2026-10-08). The run-1 registry entries (px1-v1) and rows cache are kept;
# PX-2/PX-4 still read run 1's record and models, so the dependency chain is unchanged.
PX1_RERUN_TAG = "px1-v2"
PX1_DEFECT_RECORD = ".agent/phase6/decisions/P6_PX1_AUDIT_DEFECTS_2026-10-08.md"


def run_m2(database, rulesets) -> dict[str, Any]:
    from datetime import datetime, timezone

    from ml.playoffs.evaluation import paired_log_loss_gate
    from ml.playoffs.px1 import MODEL_TYPE, SEED_ONLY_MODEL_TYPE, PlayoffLogisticModel
    from ml.registry import register_model

    global M6M7
    M6M7 = load_m6m7()
    m1 = _require("p6_m1_ruleset_check.json")
    rows, excluded, _, _, integrity, excluded_by_event = assemble_rows(database, rulesets, m1)
    train = [r for r in rows if r.season in TRAIN]
    test = [r for r in rows if r.season == HELD_OUT]
    px1 = PlayoffLogisticModel.fit(train, fit_info={"seasons": list(TRAIN)})
    seed_only = PlayoffLogisticModel.fit(train, seed_only=True, fit_info={"seasons": list(TRAIN)})
    evaluated = [(r, px1.predict(r), seed_only.predict(r), _m6m7_on(r)) for r in test]
    missing = sum(1 for _, p, _, _ in evaluated if p is None)
    evaluated = [e for e in evaluated if e[1] is not None]
    labels = [r.red_win for r, *_ in evaluated]
    events = [r.event_key for r, *_ in evaluated]
    vs_m6m7 = paired_log_loss_gate([e[1] for e in evaluated], [e[3] for e in evaluated], labels, events,
                                   seed=BOOTSTRAP_SEED)
    vs_seed = paired_log_loss_gate([e[1] for e in evaluated], [e[2] for e in evaluated], labels, events,
                                   seed=BOOTSTRAP_SEED)
    created = datetime.now(timezone.utc)
    for model, model_type in ((px1, MODEL_TYPE), (seed_only, SEED_ONLY_MODEL_TYPE)):
        register_model(model, registry_dir=REGISTRY_DIR, model_type=model_type, model_version="1.0.0",
                       version_tag=PX1_RERUN_TAG, training_dataset_hash="phase6-playoff-rows",
                       feature_list=model.design.names(), created_at=created)
    ROWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (ROWS_CACHE_DIR / f"px_rows_{PX1_RERUN_TAG}.pkl.gz").write_bytes(gzip.compress(pickle.dumps(rows)))
    return {"milestone": "P6-M2", "decision": "P6-Q3", "version_tag": PX1_RERUN_TAG,
            "supersedes": {"record": "p6_m2_px1.json", "defects": PX1_DEFECT_RECORD,
                           "reason": "two confirmed defects, same frozen spec, populations, gate and seed: (1) the "
                                     "seed-only baseline carried seed x round interactions, not the seed difference "
                                     "alone (spec §4); (2) events whose playoffs are scheduled before the selection "
                                     "moment leaked those results into the features (P6-Q2). Run 1 is kept"}, "spec_blob": git_blob(".agent/phase6/P6_M2_PX1_SPEC.md"),
            "composition_decisions_blob": git_blob(COMPOSITION_DECISIONS),
            "epa_integrity": integrity, "rows": {"train": len(train), "test": len(evaluated),
                                                 "test_insufficient_data": missing, "excluded": dict(excluded),
                                                 "excluded_by_event": excluded_by_event},
            "columns": px1.fit_info["columns"], "dropped": px1.fit_info["dropped"],
            "vs_m6m7": vs_m6m7, "vs_seed_only": vs_seed, "passed": vs_m6m7["passed"] and vs_seed["passed"]}


def _rows_cache():
    return pickle.loads(gzip.decompress((ROWS_CACHE_DIR / "px_rows.pkl.gz").read_bytes()))


def _models(track: PlayoffTrack | None = None):
    from ml.playoffs.px1 import PlayoffLogisticModel

    track = track or PX1_TRACK
    px1 = PlayoffLogisticModel.load(REGISTRY_DIR / track.model_type / track.version_tag / "model.json")
    seed_only = PlayoffLogisticModel.load(REGISTRY_DIR / track.seed_only_type / track.version_tag / "model.json")
    return px1, seed_only


def _require_model(track: PlayoffTrack) -> dict[str, Any]:
    """The track's playoff model has passed its own gate. For PX-1b, Kanav's dated confirmation must also name that
    exact record by sha256 (D9 v1 Part B, condition 4)."""
    from scripts.phase6_common import file_sha256

    record = _require(track.model_record, passed_key="passed")
    if track.confirmation is not None:
        if not track.confirmation.exists():
            raise Blocked(f"{track.confirmation} (Kanav's dated confirmation of {track.model_record}) is required")
        confirmation = json.loads(track.confirmation.read_text(encoding="utf-8"))
        if not (confirmation.get("confirmed") is True and confirmation.get("confirmed_by") and confirmation.get("date")
                and confirmation.get("record") == track.model_record
                and confirmation.get("record_sha256") == file_sha256(RESULTS_DIR / track.model_record)):
            raise Blocked(f"{track.confirmation} does not confirm the current {track.model_record}")
    return record


def _m1(track: PlayoffTrack) -> dict[str, Any]:
    """The P6-M1 records the track's seasons need, merged by event (each event appears in exactly one)."""
    events: dict[str, Any] = {}
    for name in track.m1_records:
        events.update(_require(name)["events"])
    return {"events": events}


def _epa_source(track: PlayoffTrack) -> tuple[Path, Path]:
    if track.epa_snapshot is None or track.epa_chain is None:
        raise Blocked(f"{track.name}: no D18 EPA source is configured for {track.holdout} (D9 v1 Part B, 3(d))")
    return track.epa_snapshot, track.epa_chain


def _track_rows(database, rulesets, track: PlayoffTrack) -> list:
    """PX-2's rows: PX-1's cached rows, or PX-1b's spec §1 rows of the calibration and held-out seasons."""
    if track is PX1_TRACK:
        return _rows_cache()
    from ml.playoffs.px1b import drop_scale_absent

    snapshot, chain = _epa_source(track)
    rows, *_ = assemble_rows(database, rulesets, _m1(track), seasons=(track.calibration_season, track.holdout),
                             snapshot=snapshot, chain=chain)
    return drop_scale_absent(rows)[0]


def _track_info(track: PlayoffTrack) -> dict[str, Any]:
    """What a versioned track's record adds: the track and its frozen specs' blobs (nothing for PX-1)."""
    if track.specs is None:
        return {}
    return {"track": track.name, "version_tag": track.version_tag,
            "specs": {k: {"path": v, "blob": git_blob(v)} for k, v in track.specs.items()}}


def run_m3(database, rulesets, track: PlayoffTrack | None = None) -> dict[str, Any]:
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    from ml.calibration.gate import evaluate_calibration_gate

    track = track or PX1_TRACK
    _require_model(track)
    px1, _ = _models(track)
    rows = _track_rows(database, rulesets, track)
    calibration: dict[str, Any] = {}
    if track.calibration_base_record is not None:  # PX-2b v2: out-of-sample, never px1b-v1's own predictions
        calibrator, slice_rows, calibration = _out_of_sample_calibrator(rows, track)
    else:  # the frozen PX-2 (P6-Q4), unchanged
        season_2025 = sorted((r for r in rows if r.season == track.calibration_season),
                             key=lambda r: (r.scheduled_time, r.match_key))
        slice_rows = season_2025[int(len(season_2025) * 0.8):]
        calibrator = SymmetricIsotonicCalibrator()
        calibrator.fit([px1.predict(r) for r in slice_rows], [r.red_win for r in slice_rows])
    test = [r for r in rows if r.season == track.holdout and px1.predict(r) is not None]
    q = [calibrator.calibrate(px1.predict(r)) for r in test]
    swapped = [calibrator.calibrate(px1.predict(r.swapped())) for r in test]
    backward = [calibrator.calibrate(px1.predict(r)) for r in reversed(test)]
    fit_isolated = max(r.scheduled_time for r in slice_rows) < min(r.scheduled_time for r in test)
    gate = evaluate_calibration_gate(q, [r.red_win for r in test],
                                     symmetry_errors=[abs(a + b - 1.0) for a, b in zip(q, swapped)],
                                     order_independent=q == list(reversed(backward)), fit_isolated=fit_isolated)
    calibrator.save(ROWS_CACHE_DIR / track.calibrator_file)
    return {"milestone": "P6-M3", "decision": "P6-Q4", "slice_rows": len(slice_rows), "evaluated": len(test),
            "gate": gate.to_dict(), "passed": gate.passed, **_track_info(track),
            **({"calibration": calibration} if calibration else {})}


def _out_of_sample_calibrator(rows, track: PlayoffTrack):
    """PX-2b v2 §2.2: the calibrator is fit on the calibration-base model's predictions of the frozen slice, after a
    per-row proof that no slice match or event is in the base model's fit set. It is then applied to the candidate
    (px1b-v1) by the caller; the base model is never the candidate."""
    from datetime import datetime

    from ml.playoffs.px1 import PlayoffLogisticModel
    from ml.playoffs.px2b import (SPEC_BLOB, SPEC_PATH, calibration_slice, fit_out_of_sample_calibrator,
                                  frozen_slice_keys, require_frozen_slice)

    if git_blob(SPEC_PATH) != SPEC_BLOB:
        raise Blocked(f"{SPEC_PATH} is not the approved PX-2b v2 blob {SPEC_BLOB}")
    record = _require(track.calibration_base_record)
    base_dir = REGISTRY_DIR / record["registry"]["model_type"] / record["registry"]["version_tag"]
    manifest = json.loads((base_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["training_dataset_hash"] != record["base"]["fingerprint"]:
        raise Blocked("the registered calibration-base model was not trained on the recorded fit set")
    base_model = PlayoffLogisticModel.load(base_dir / "model.json")
    slice_rows = calibration_slice(rows, track.calibration_season)
    require_frozen_slice(slice_rows, frozen_slice_keys())
    calibrator, report = fit_out_of_sample_calibrator(
        base_model, record["base"]["match_keys"], record["base"]["events"],
        datetime.fromisoformat(record["base"]["latest"]), slice_rows)
    return calibrator, slice_rows, {"procedure": "PX-2b v2 out-of-sample (calibration base)",
                                    "calibration_base": record["registry"], "base_fingerprint": record["base"]["fingerprint"],
                                    "isolation": report, "applied_to": f"{track.model_type} {track.version_tag}"}


def run_m5(database, rulesets, track: PlayoffTrack | None = None) -> dict[str, Any]:
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    from ml.playoffs.data import event_bracket, read_event_playoffs
    from ml.playoffs.evaluation import paired_log_loss_gate
    from ml.playoffs.px1 import alliance_match_probability
    from ml.playoffs.selection import field_outcome

    track = track or PX1_TRACK
    _require(track.px2_record, passed_key="passed")
    if track.confirmation is not None:
        _require_model(track)
    m1 = _m1(track)
    px1, seed_only = _models(track)
    calibrator = SymmetricIsotonicCalibrator.load(ROWS_CACHE_DIR / track.calibrator_file)
    snapshot, chain = _epa_source(track)
    _, _, features_by_event, events_by_key, _, population = assemble_rows_for(
        database, rulesets, m1, track.holdout, snapshot=snapshot, chain=chain,
        exclude_playoffs_before_selection=track.exclude_playoffs_before_selection)
    units: dict[str, list] = defaultdict(list)
    for event_key, event in events_by_key.items():
        info = m1["events"][event_key]
        bracket = event_bracket(event, rulesets[track.holdout])
        members = population["members"][event_key]
        alliances = tuple(members[s] for s in sorted(members))
        features = features_by_event[event_key]
        p_px = alliance_match_probability(px1, features, calibrator.calibrate)
        p_seed = alliance_match_probability(seed_only, features)
        for seed in range(1, len(alliances) + 1):
            try:
                ours = field_outcome(alliances, bracket, p_px, seed)
            except ValueError:
                units["insufficient_data"].append(event_key)
                break
            base = field_outcome(alliances, bracket, p_seed, seed)
            units["rows"].append((event_key, ours, base, seed == info["winner_seed"],
                                  seed in (info["winner_seed"], info["finalist_seed"])))
    rows = units["rows"]
    events = [r[0] for r in rows]
    win = paired_log_loss_gate([r[1].p_win_event for r in rows], [r[2].p_win_event for r in rows],
                               [r[3] for r in rows], events, seed=BOOTSTRAP_SEED)
    finals = paired_log_loss_gate([r[1].p_reach_finals for r in rows], [r[2].p_reach_finals for r in rows],
                                  [r[4] for r in rows], events, seed=BOOTSTRAP_SEED)
    reported = {}
    if track.specs is not None:  # PX-4b spec §4: Brier and reliability bins, reported, not gated
        from ml.backtest.metrics import brier_score
        for name, k in (("p_win_event", 3), ("p_reach_finals", 4)):
            ours, base, labels = ([getattr(r[1], name) for r in rows], [getattr(r[2], name) for r in rows],
                                  [r[k] for r in rows])
            reported[name] = {"brier": brier_score(ours, labels), "brier_seed_only": brier_score(base, labels),
                              "reliability_bins": reliability_bins(ours, labels)}
    return {"milestone": "P6-M5", "decision": "P6-Q5", "composition_decisions_blob": git_blob(COMPOSITION_DECISIONS),
            "population": {k: v for k, v in population.items() if k != "members"},
            "alliances": len(rows), "events": len(set(events)),
            "insufficient_data_events": len(set(units["insufficient_data"])), "p_win_event": win,
            "p_reach_finals": finals, "passed": win["passed"] and finals["passed"],
            **({"reported_not_gated": reported} if reported else {}), **_track_info(track)}


def reliability_bins(predictions: list[float], labels: list[bool], n_bins: int = 10) -> list[dict[str, Any]]:
    """Equal-width bins over [0, 1]: count, mean predicted and observed rate (empty bins listed with count 0)."""
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for p, y in zip(predictions, labels):
        bins[min(int(p * n_bins), n_bins - 1)].append((p, y))
    return [{"low": i / n_bins, "high": (i + 1) / n_bins, "count": len(b),
             "mean_predicted": sum(p for p, _ in b) / len(b) if b else None,
             "observed": sum(1 for _, y in b if y) / len(b) if b else None} for i, b in enumerate(bins)]


def representable_events(rulesets, m1, events, *, exclude_playoffs_before_selection: bool = False) -> dict[str, Any]:
    """The intended population (reproduced events) and the validated one (C1/C2, Kanav 2026-10-06).

    An event whose selection-time alliances are not all three members is outside PX-1's frozen representation:
    FIRST Championship divisions, identified by the approved ruleset's cited variant through `for_event`. It is
    excluded and counted with its alliance count, never silently dropped. An unexplained listing is excluded too."""
    from data.rulesets import RulesetError
    from ml.playoffs.data import event_members
    from ml.playoffs.px1 import PX1_TEAMS_PER_ALLIANCE

    intended = [e for e in events if m1["events"].get(e.event_key, {}).get("status") == "reproduced"]
    validated, excluded, members_by_event = [], {}, {}
    for event in intended:
        if exclude_playoffs_before_selection and event.playoffs_precede_selection():  # PX-4b/M8b leakage rule
            excluded[event.event_key] = {"reason": PLAYOFF_BEFORE_SELECTION, "alliances": len(event.alliances)}
            continue
        event_rules = rulesets[event.season].for_event(event.event_key)
        try:
            members = event_members(event, event_rules)
        except RulesetError as exc:
            excluded[event.event_key] = {"reason": f"event_{exc.code}", "alliances": len(event.alliances)}
            continue
        if any(len(m) != PX1_TEAMS_PER_ALLIANCE for m in members.values()):
            excluded[event.event_key] = {"reason": FOUR_MEMBER, "selection_variant": event_rules.variant,
                                         "alliances": len(members)}
            continue
        validated.append(event)
        members_by_event[event.event_key] = members
    return {"intended_events": len(intended), "validated_events": len(validated), "excluded_events": excluded,
            "excluded_alliances": sum(v["alliances"] for v in excluded.values()),
            "validated": validated, "members": members_by_event}


def assemble_rows_for(database, rulesets, m1, season, *, snapshot=None, chain=None,
                      exclude_playoffs_before_selection: bool = False):
    from ml.features.scale import ScaleLookup
    from ml.playoffs.data import read_event_playoffs, selection_features
    from ml.ratings.d18_source import load_d18_provider

    provider, integrity = load_d18_provider(database, snapshot or SNAPSHOT, chain or CHAIN)
    scales = ScaleLookup(database)
    population = representable_events(rulesets, m1, read_event_playoffs(database, season),
                                      exclude_playoffs_before_selection=exclude_playoffs_before_selection)
    features_by_event, events_by_key = {}, {}
    for event in population.pop("validated"):
        teams = {t for m in population["members"][event.event_key].values() for t in m}
        features_by_event[event.event_key] = selection_features(database, event, teams, provider=provider,
                                                                scales=scales)
        events_by_key[event.event_key] = event
    return None, None, features_by_event, events_by_key, integrity, population


M8_PRE_RUN_JSON = Path(".agent/phase6/decisions/p6_m8_pre_run.json")
M8_REVIEW_JSON = Path(".agent/phase6/decisions/p6_m8_mentor_review.json")


def _m8_config(track: PlayoffTrack | None = None) -> dict[str, Any]:
    """The dated, committed pre-run record (P6-Q1, P6-Q13): seed, strata, per-stratum count, reason categories and
    the named mentor. It is written by people before the run; the run refuses without it. M8b also needs the named
    mentor's confirmed agreement in it (`P6_M8B_SPEC.md` §1.3), never presumed."""
    track = track or PX1_TRACK
    if not (track.m8_pre_run.exists() and track.m8_pre_run_json.exists()):
        raise Blocked(f"{track.m8_pre_run} and {track.m8_pre_run_json} (the dated pre-run record: population seed, "
                      "strata, per-stratum count, reason categories, named mentor) must be committed before P6-M8 runs")
    config = json.loads(track.m8_pre_run_json.read_text(encoding="utf-8"))
    for key in ("seed", "per_stratum", "reason_categories", "mentor"):
        if not config.get(key):
            raise Blocked(f"the P6-M8 pre-run record lacks {key!r}")
    if track.requires_mentor_agreement:
        agreement = config.get("mentor_agreement") or {}
        if not (agreement.get("confirmed") is True and agreement.get("date") and agreement.get("evidence")):
            raise Blocked(f"the M8b pre-run record does not confirm {config['mentor']}'s agreement (confirmed, date, "
                          "evidence): M8b does not execute without it")
    return config


def _m8_sample(events: list, weeks: dict[str, int | None], config: dict[str, Any]) -> list:
    """Held-out 2026 events stratified by TBA week and event-size tercile (P6-Q1), seeded."""
    import random

    sizes = sorted(e.team_count for e in events)
    cut = (sizes[len(sizes) // 3], sizes[2 * len(sizes) // 3]) if sizes else (0, 0)
    strata: dict[tuple, list] = defaultdict(list)
    for event in sorted(events, key=lambda e: e.event_key):
        size = 0 if event.team_count <= cut[0] else (1 if event.team_count <= cut[1] else 2)
        week = weeks.get(event.event_key)
        strata[(-1 if week is None else week, size)].append(event)
    sample = []
    for key in sorted(strata):
        members = strata[key]
        n = config["per_stratum"]
        sample.extend(members if len(members) <= n
                      else random.Random(config["seed"] + 100 * key[0] + key[1]).sample(members, n))
    return sample


M8_SENTINEL_PREFIX = "t_p6m8_sentinel"
M8_FAR_FUTURE = "2026-12-31T00:00:00+00:00"


@contextmanager
def future_playoff_sentinel(database, event_key: str, season: int, red: tuple[int, ...], blue: tuple[int, ...],
                            when: str = M8_FAR_FUTURE):
    """P6-M8 leakage sentinel (docs/P6Milestones.md P6-M8 'Leakage'): a far-future playoff result, with scouting rows,
    inserted into the ISOLATED copy for the duration of the block, then always deleted. Every M8 input is assembled
    at the selection moment, so nothing computed inside the block may change."""
    match_key = f"{event_key}_{M8_SENTINEL_PREFIX}"
    with database.cursor() as cursor:
        cursor.execute("INSERT INTO matches (match_key, event_key, season, competition_level, set_number, match_number, "
                       "scheduled_time, score_red, score_blue, winning_alliance, last_updated) "
                       "VALUES (%s, %s, %s, 'final', 99, 1, %s, 999, 0, 'red', NOW())",
                       (match_key, event_key, season, when))
        for colour, teams in (("red", red), ("blue", blue)):
            for team in teams:
                cursor.execute("INSERT INTO match_teams (match_key, team_number, alliance_color, last_updated) "
                               "VALUES (%s, %s, %s, NOW())", (match_key, team, colour))
                cursor.execute("INSERT INTO scouting_observations (match_key, event_key, team_number, scout_identifier, "
                               "defense_rating, feeding_rating, source, submitted_at) "
                               "VALUES (%s, %s, %s, 'p6m8-sentinel', 5, 5, 'p6m8_sentinel', %s)",
                               (match_key, event_key, team, when))
    try:
        yield match_key
    finally:
        with database.cursor() as cursor:
            cursor.execute("DELETE FROM scouting_observations WHERE source = 'p6m8_sentinel'")
            cursor.execute("DELETE FROM match_teams WHERE match_key = %s", (match_key,))
            cursor.execute("DELETE FROM matches WHERE match_key = %s", (match_key,))


PX1_TRACK = PlayoffTrack(
    name="PX-1", model_record="p6_m2_px1.json", confirmation=None, model_type="playoff_px1",
    seed_only_type="playoff_seed_only", version_tag="px1-v1", calibration_season=2025, holdout=HELD_OUT,
    m1_records=("p6_m1_ruleset_check.json",), px2_record="p6_m3_px2.json", px4_record="p6_m5_px4.json",
    m8_run_record="p6_m8_dm1_run.json", m8_record="p6_m8_dm1.json", calibrator_file="px2_calibrator.json",
    m8_pre_run=M8_PRE_RUN, m8_pre_run_json=M8_PRE_RUN_JSON, m8_review_json=M8_REVIEW_JSON, sentinel_time=M8_FAR_FUTURE,
    epa_snapshot=SNAPSHOT, epa_chain=CHAIN, exclude_playoffs_before_selection=False)
PX1B_TRACK = PlayoffTrack(
    name="PX-1b", model_record="p6_px1b_gate_2027.json",
    confirmation=Path(".agent/phase6/decisions/p6_px1b_final1_confirmation.json"), model_type="playoff_px1b",
    seed_only_type="playoff_px1b_seed_only", version_tag="px1b-v1", calibration_season=2026, holdout=2027,
    m1_records=("p6_m1_ruleset_check.json", "p6_m1_ruleset_check_2027.json"), px2_record="p6_px2b.json",
    px4_record="p6_px4b.json", m8_run_record="p6_m8b_dm1_run.json", m8_record="p6_m8b_dm1.json",
    calibrator_file="px2b_calibrator.json", m8_pre_run=Path(".agent/phase6/decisions/P6_M8B_PRE_RUN.md"),
    m8_pre_run_json=Path(".agent/phase6/decisions/p6_m8b_pre_run.json"),
    m8_review_json=Path(".agent/phase6/decisions/p6_m8b_mentor_review.json"),
    sentinel_time="2027-12-31T00:00:00+00:00",
    epa_snapshot=None, epa_chain=None,  # D9 v1 Part B 3(d): a D18 source covering 2027 must be configured first
    exclude_playoffs_before_selection=True,
    specs={"px2b": ".agent/phase6/P6_M3_PX2B_SPEC_V2.md", "px4b": ".agent/phase6/P6_M5_PX4B_SPEC.md",
           "m8b": ".agent/phase6/P6_M8B_SPEC.md"},  # PX-2b v2 governs (approved 2026-10-08); v1 is kept as history
    requires_mentor_agreement=True, calibration_base_record="p6_px2b_calbase.json")


WEEK_SQL = """
SELECT DISTINCT ON (r.source_object_id) r.source_object_id, (r.payload_json->>'week')::int
FROM raw_source_payloads r
WHERE r.source = 'tba' AND r.source_object_type = 'event' AND r.is_current AND r.source_object_id = ANY(%s)
ORDER BY r.source_object_id, r.id DESC
"""


def run_m8(database, rulesets, track: PlayoffTrack | None = None) -> dict[str, Any]:
    """P6-M8 step 1: the engine's predicted field and contenders for each sampled event, the frozen P6-Q1
    identification of the actual winner and finalist, both baselines, and the data facts for every miss.
    P6-DM1 is decided only after the named mentor's review (`m8-review`), never here."""
    from data.rankings import read_final_ranks_for_season
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    from ml.features.assembler import build_team_features
    from ml.features.scale import ScaleLookup
    from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
    from ml.playoffs.data import event_bracket, read_event_playoffs
    from ml.playoffs.evaluation import PredictedAlliance, dm1_result, identifies
    from ml.playoffs.px1 import alliance_match_probability
    from ml.playoffs.selection import DraftState, SelectionEngine, best_available, field_outcome, run_draft
    from ml.ratings.d18_source import load_d18_provider
    from ml.registry import load_registered_model
    from ml.views.event_analysis import POLICY_M5V2, policy_model

    track = track or PX1_TRACK
    config = _m8_config(track)
    _require(track.px4_record, passed_key="passed")
    if track.confirmation is not None:
        _require_model(track)
    m1 = _m1(track)
    px1, _ = _models(track)
    calibrator = SymmetricIsotonicCalibrator.load(ROWS_CACHE_DIR / track.calibrator_file)
    snapshot, chain = _epa_source(track)
    provider, _ = load_d18_provider(database, snapshot, chain)
    scales = ScaleLookup(database)
    ranking, _ = load_registered_model(RankingXGBModelV2, registry_dir=REGISTRY_DIR, model_type="ranking_xgb_v2",
                                       version_tag="d18", current_feature_list=FEATURE_NAMES_V2)
    policy = policy_model(True)
    ranks_by_event = read_final_ranks_for_season(database, track.holdout)
    ruleset = rulesets[track.holdout]
    population = representable_events(rulesets, m1, read_event_playoffs(database, track.holdout),  # C2
                                      exclude_playoffs_before_selection=track.exclude_playoffs_before_selection)
    eligible = population.pop("validated")
    members_by_event = population.pop("members")
    with database.cursor() as cursor:
        cursor.execute(WEEK_SQL, (sorted(e.event_key for e in eligible),))
        weeks = dict(cursor.fetchall())
    sample = _m8_sample(eligible, weeks, config)
    started = time.time()
    per_event: dict[str, Any] = {}
    engine_hits: dict[str, list[bool]] = defaultdict(list)
    baselines: dict[str, dict[str, list[bool]]] = {"raw_epa_draft": defaultdict(list),
                                                   "actual_seed_order": defaultdict(list)}

    def engine_outputs(event) -> dict[str, Any]:
        """Everything the engine computes for one event at its selection moment (inputs only, never labels)."""
        ranks = ranks_by_event.get(event.event_key, {})
        with database.cursor() as cursor:
            cursor.execute(ROSTER_SQL, (event.event_key,))
            roster = sorted(r[0] for r in cursor.fetchall())
        features = {t: build_team_features(database, t, event.event_key, event.selection_as_of(),
                                           epa_provider=provider, scale_lookup=scales) for t in roster}

        def strength(t: int) -> float:
            if policy == POLICY_M5V2:
                return ranking.predict_rating(features[t])
            return features[t].epa_total if features[t].epa_total is not None else float("-inf")

        ordering = sorted(roster, key=lambda t: (-strength(t), t))
        p_match = alliance_match_probability(px1, features, calibrator.calibrate)
        event_rules = ruleset.for_event(event.event_key)
        engine = SelectionEngine(event_rules, ranks, ordering, p_match, probability_status="validated_playoff",
                                 features=features)
        bracket = event_bracket(event, ruleset)

        def engine_choice(state, seed, options):
            return engine.recommend(state, seed).ranked[0].team_number

        predicted = run_draft(DraftState.empty(engine.n_alliances), event_rules, ranks, engine_choice).alliances
        raw_order = sorted(roster, key=lambda t: (-(features[t].epa_total if features[t].epa_total is not None
                                                     else float("-inf")), t))
        raw_field = run_draft(DraftState.empty(engine.n_alliances), event_rules, ranks,
                              best_available(raw_order)).alliances

        def contenders(alliances):
            return [PredictedAlliance(a, field_outcome(alliances, bracket, p_match, i + 1).p_win_event)
                    for i, a in enumerate(alliances)]

        return {"ordering": ordering, "features": features, "predicted": predicted, "raw_field": raw_field,
                "engine_contenders": contenders(predicted), "raw_contenders": contenders(raw_field)}

    def fingerprint(out: dict[str, Any]) -> tuple:
        return (tuple(out["ordering"]), tuple(map(tuple, out["predicted"])), tuple(map(tuple, out["raw_field"])),
                tuple((a.teams, a.p_win_event) for a in out["engine_contenders"]),
                tuple((a.teams, a.p_win_event) for a in out["raw_contenders"]))

    fingerprints: dict[str, tuple] = {}
    for event in sample:
        if time.time() - started > BUDGET_SECONDS:
            raise SystemExit("P6-M8 exceeded its 45-minute budget: nothing recorded; redesign before re-running")
        info = m1["events"][event.event_key]
        out = engine_outputs(event)
        fingerprints[event.event_key] = fingerprint(out)
        ordering, features = out["ordering"], out["features"]
        predicted, engine_contenders, raw_contenders = out["predicted"], out["engine_contenders"], out["raw_contenders"]
        actual = members_by_event[event.event_key]  # selection-time members: a backup is never an actual pick
        seed_order = [PredictedAlliance(actual[s], 1.0 / s) for s in sorted(actual)]
        strong_rows = []
        for label, seed in (("winner", info["winner_seed"]), ("finalist", info["finalist_seed"])):
            alliance = actual[seed]
            hit = identifies(alliance, engine_contenders)
            raw_hit, seed_hit = identifies(alliance, raw_contenders), identifies(alliance, seed_order)
            facts = None if hit else {
                "actual": list(alliance), "actual_seed": seed,
                "raw_epa_draft_hit": raw_hit, "actual_seed_order_hit": seed_hit,  # evidence for the mentor review
                "declines_at_event": sorted(t for a in event.alliances for t in a.declines),
                "ordering_positions": {str(t): ordering.index(t) for t in alliance if t in ordering},
                "reliability": {str(t): features[t].reliability_score for t in alliance if t in features}}
            strong_rows.append({"strong": label, "hit": hit, "facts": facts})
            engine_hits[event.event_key].append(hit)
            baselines["raw_epa_draft"][event.event_key].append(raw_hit)
            baselines["actual_seed_order"][event.event_key].append(seed_hit)
        per_event[event.event_key] = {"predicted_field": [list(a) for a in predicted],
                                      "top2": [list(a.teams) for a in sorted(engine_contenders,
                                                                             key=lambda a: -a.p_win_event)[:2]],
                                      "strong": strong_rows}
    # The frozen leakage sentinel, on the pre-registered sentinel event: the sampled event with the fewest
    # qualification teams (ties: event key), the cheapest re-run. A future playoff result must change nothing.
    target = min(sample, key=lambda e: (e.team_count, e.event_key))
    members = members_by_event[target.event_key]
    with future_playoff_sentinel(database, target.event_key, target.season, members[1], members[2],
                                 when=track.sentinel_time) as sentinel_key:
        unchanged = fingerprint(engine_outputs(target)) == fingerprints[target.event_key]
    if time.time() - started > BUDGET_SECONDS:
        raise SystemExit("P6-M8 exceeded its 45-minute budget: nothing recorded; redesign before re-running")
    sentinel = {"event": target.event_key, "inserted": sentinel_key, "unchanged": unchanged, "passed": unchanged}
    return {"milestone": "P6-M8", "step": "run (P6-DM1 is decided only after the named mentor's review)",
            "leakage_sentinel": sentinel,
            "decision": "P6-Q1", "pre_run": str(track.m8_pre_run_json),
            "pre_run_blob": git_blob(str(track.m8_pre_run_json)), **_track_info(track),
            "composition_decisions_blob": git_blob(COMPOSITION_DECISIONS), "population": population,
            "events": per_event, "identified_before_review": dm1_result(engine_hits, seed=BOOTSTRAP_SEED),
            "baselines": {k: dm1_result(v, seed=BOOTSTRAP_SEED) for k, v in baselines.items()},
            "misses_pending_review": sum(1 for hits in engine_hits.values() for h in hits if not h)}


def run_m8_review(database, rulesets, track: PlayoffTrack | None = None) -> dict[str, Any]:
    """P6-M8 step 2: P6-DM1 from the run and the named mentor's review. A miss counts toward P6-DM1 only if the
    mentor accepted one of the predefined reason categories for it; nothing is accepted by default."""
    from ml.playoffs.evaluation import dm1_result

    track = track or PX1_TRACK
    config = _m8_config(track)
    run = _require(track.m8_run_record)
    if not track.m8_review_json.exists():
        raise Blocked(f"{track.m8_review_json} (the named mentor's review of every miss) is required")
    review = json.loads(track.m8_review_json.read_text(encoding="utf-8"))
    if review.get("mentor") != config["mentor"]:
        raise Blocked("the review is not by the mentor named in the pre-run record")
    categories = {c["code"] for c in config["reason_categories"]}
    decisions = {(d["event_key"], d["strong"]): d for d in review.get("decisions", [])}
    outcomes: dict[str, list[bool]] = defaultdict(list)
    unreviewed = 0
    for event_key, info in run["events"].items():
        for row in info["strong"]:
            if row["hit"]:
                outcomes[event_key].append(True)
                continue
            decision = decisions.get((event_key, row["strong"]))
            if decision is None:
                unreviewed += 1
            outcomes[event_key].append(bool(decision and decision.get("accepted")
                                            and decision.get("category") in categories))
    result = dm1_result(outcomes, seed=BOOTSTRAP_SEED)
    return {"milestone": "P6-M8", "done_means": "P6-DM1", "mentor": review["mentor"],
            "run_blob": git_blob(str(RESULTS_DIR / track.m8_run_record)),
            "review_blob": git_blob(str(track.m8_review_json)),
            "unreviewed_misses": unreviewed, **result, "met": bool(result["met"]) and unreviewed == 0,
            **_track_info(track)}


ROSTER_SQL = """
SELECT DISTINCT mt.team_number FROM matches m JOIN match_teams mt USING (match_key)
WHERE m.event_key = %s AND m.competition_level = 'qualification'
"""


def run_m6b(database, rulesets) -> dict[str, Any]:
    """P6-M6 (b): the draft model's pick prediction on held-out 2026 events, measured once (P6-Q6: not gating).
    Each real pick is compared with the draft model's choice from the real draft state before it. The ordering is
    the validated P5-M4 policy at the selection moment, where the event switch has passed.

    Reported as the frozen P6-M6 (b) row requires: top-1 / top-3 per pick slot (selection round), with
    event-bootstrap 95% CIs, next to a raw-EPA-order baseline (the rerun1 fix of a harness that reported only the
    pooled rates; run 1 is kept)."""
    from ml.backtest.bootstrap import event_bootstrap_mean_ci
    from ml.playoffs.selection import pick_hits
    from ml.features.assembler import build_team_features
    from ml.features.scale import ScaleLookup
    from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
    from ml.playoffs.data import read_event_playoffs
    from ml.playoffs.selection import DraftState, pick_prediction_accuracy, turn_order
    from ml.ratings.d18_source import load_d18_provider
    from ml.registry import load_registered_model
    from ml.views.event_analysis import POLICY_M5V2, policy_model

    m1 = _require("p6_m1_ruleset_check.json")
    provider, _ = load_d18_provider(database, SNAPSHOT, CHAIN)
    scales = ScaleLookup(database)
    ranking, _ = load_registered_model(RankingXGBModelV2, registry_dir=REGISTRY_DIR, model_type="ranking_xgb_v2",
                                       version_tag="d18", current_feature_list=FEATURE_NAMES_V2)
    policy = policy_model(True)
    ruleset = rulesets[HELD_OUT]
    top1 = top3 = picks = events = 0
    notes: Counter[str] = Counter()
    # {ordering: {slot: {metric: {event: [0/1 per pick]}}}}; slot 0 = all picks
    units: dict[str, dict[int, dict[str, dict[str, list[float]]]]] = {
        o: defaultdict(lambda: {"top1": defaultdict(list), "top3": defaultdict(list)}) for o in ("model", "raw_epa")}
    for event in read_event_playoffs(database, HELD_OUT):
        if m1["events"].get(event.event_key, {}).get("status") != "reproduced":
            continue
        with database.cursor() as cursor:
            cursor.execute(ROSTER_SQL, (event.event_key,))
            roster = sorted(r[0] for r in cursor.fetchall())
        as_of = event.selection_as_of()
        features = {t: build_team_features(database, t, event.event_key, as_of, epa_provider=provider,
                                           scale_lookup=scales) for t in roster}

        def score(t: int) -> float:
            if policy == POLICY_M5V2:
                return ranking.predict_rating(features[t])
            return features[t].epa_total if features[t].epa_total is not None else float("-inf")

        ordering = sorted(roster, key=lambda t: (-score(t), t))
        alliances = sorted(event.alliances, key=lambda a: a.seed)
        event_rules = ruleset.for_event(event.event_key)
        declined = frozenset(t for a in alliances for t in a.declines)
        current: list[list[int]] = [[] for _ in alliances]
        actual = []
        for turn, seed in enumerate(turn_order(len(alliances), event_rules.selection.picks_per_alliance)):
            alliance = alliances[seed - 1]
            if not current[seed - 1]:
                current[seed - 1].append(alliance.captain)
            index = len(current[seed - 1])
            if index >= len(alliance.picks):
                notes["pick_missing"] += 1
                break
            actual.append((DraftState(tuple(tuple(a) for a in current), declined, turn), seed, alliance.picks[index]))
            current[seed - 1].append(alliance.picks[index])
        result = pick_prediction_accuracy(actual, ordering, event_rules, roster)
        top1, top3, picks, events = top1 + result["top1"], top3 + result["top3"], picks + result["picks"], events + 1
        raw_ordering = sorted(roster, key=lambda t: (-(features[t].epa_total if features[t].epa_total is not None
                                                       else float("-inf")), t))
        slots = [state.turns_taken // len(alliances) + 1 for state, _, _ in actual]
        for name, order in (("model", ordering), ("raw_epa", raw_ordering)):
            for slot, (hit1, hit3) in zip(slots, pick_hits(actual, order, event_rules, roster)):
                for key in (0, slot):
                    units[name][key]["top1"][event.event_key].append(float(hit1))
                    units[name][key]["top3"][event.event_key].append(float(hit3))
    def summary(by_slot) -> dict[str, Any]:
        out = {}
        for slot in sorted(by_slot):
            label = "all_picks" if slot == 0 else f"round_{slot}"
            out[label] = {metric: event_bootstrap_mean_ci(by_slot[slot][metric], seed=BOOTSTRAP_SEED)
                          for metric in ("top1", "top3")}
            out[label]["picks"] = sum(len(v) for v in by_slot[slot]["top1"].values())
        return out

    return {"milestone": "P6-M6", "criterion": "b", "gating": False, "policy": policy, "events": events,
            "picks": picks, "top1_rate": top1 / picks if picks else None,
            "top3_rate": top3 / picks if picks else None, "notes": dict(notes),
            "per_slot": {"model": summary(units["model"]), "raw_epa_order_baseline": summary(units["raw_epa"])},
            "supersedes": {"record": "p6_m6b_draft_accuracy.json",
                           "reason": "harness defect: run 1 reported pooled rates only; the frozen P6-M6 (b) row "
                                     "requires per pick slot, with CIs, next to a raw-EPA-order baseline. Same "
                                     "method, population and ordering; run 1 is kept"}}


RUNS = {"m1": ("p6_m1_ruleset_check.json", run_m1), "m2": ("p6_m2_px1_rerun1.json", run_m2),
        "m3": ("p6_m3_px2.json", run_m3), "m6b": ("p6_m6b_draft_accuracy_rerun1.json", run_m6b), "m5": ("p6_m5_px4.json", run_m5), "m8": ("p6_m8_dm1_run.json", run_m8),
        "m8-review": ("p6_m8_dm1.json", run_m8_review),
        "m1-2027": ("p6_m1_ruleset_check_2027.json", run_m1_2027),
        # C4: the versioned PX-1b chain (each refuses until its prerequisites exist)
        "px2b": (PX1B_TRACK.px2_record, lambda database, rulesets: run_m3(database, rulesets, PX1B_TRACK)),
        "px4b": (PX1B_TRACK.px4_record, lambda database, rulesets: run_m5(database, rulesets, PX1B_TRACK)),
        "m8b": (PX1B_TRACK.m8_run_record, lambda database, rulesets: run_m8(database, rulesets, PX1B_TRACK)),
        "m8b-review": (PX1B_TRACK.m8_record, lambda database, rulesets: run_m8_review(database, rulesets, PX1B_TRACK))}
# The seasons whose approved rulesets a run needs (default: 2024-2026).
RUN_SEASONS = {"m1-2027": (2027,), "px2b": (2026, 2027), "px4b": (2027,), "m8b": (2027,), "m8b-review": (2027,)}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in RUNS:
        print(__doc__)
        return 2
    started = time.time()
    database = isolated_database()
    rulesets = require_rulesets(database, RUN_SEASONS.get(args[0]))
    name, run = RUNS[args[0]]
    result = run(database, rulesets)
    result["minutes"] = round((time.time() - started) / 60, 1)
    result["over_budget"] = time.time() - started > BUDGET_SECONDS
    path = write_once(name, result)
    print(json.dumps({k: v for k, v in result.items() if k in ("passed", "escalate", "minutes")}), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
