"""P6-M10b runs under the frozen `.agent/phase6/P6_M10B_SPEC.md` (blob d699afaf; frozen 2026-10-10 at 22e4d7b).
Isolated `stratai_test` only.

    python -m scripts.phase6_m10b calibrate   # §3: fit and register the C-R calibrator on 2026 (needs DEV-M10b to proceed)
    python -m scripts.phase6_m10b pins        # §3: the additive pin record (base + calibrator sha256), before 2027 data
    python -m scripts.phase6_m10b final       # §6: the one-time 2027 acceptance run (fail-closed prerequisites)

Implemented 2026-10-10. **None of these has been run.**
- Running them needs Kanav's separate authorization: DEV-M10b first, then the calibrator, then the 2027 run.
- Every command refuses until its prerequisites exist.
- Records are write-once.
- P6-M10 stays `not_validated`.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts import phase6_common as common
from scripts.phase6_common import (M6M7_SHA256, P6_M10_VERSION_TAG, file_sha256, git_blob, isolated_database,
                                   read_record, write_once)
from scripts.phase6_playoff_track import BUDGET_SECONDS, Blocked

CALIBRATION_SEASON, HOLDOUT = 2026, 2027
DEV_RECORD, CALIBRATOR_RECORD, PINS_RECORD = "p6_m10b_dev.json", "p6_m10b_calibrator.json", "p6_m10b_pins.json"
FRAME_RECORD, OUTCOME_RECORD = "p6_m10b_frame_2027.json", "p6_m10b_outcome_model.json"
# §5 restricts the 2027 population to "official events" but defines no rule, and the canonical events table carries
# no event_type (NULL for every event in the 2026 frame). Until Kanav fixes a definition in a dated record, the
# 2027 run is refused (fail-closed); no definition is guessed here.
OFFICIAL_EVENTS_RULE: str | None = None
AUTHORIZATION = Path(".agent/phase6/decisions/p6_m10b_authorization.json")
BOOTSTRAP_SEED = 20261005  # P6-Q9 / v1 §5, unchanged
BASE_FIT_SEASONS = {2024, 2025}


def _spec() -> dict[str, str]:
    from ml.strategy.calibration import SPEC_BLOB, SPEC_PATH

    if git_blob(SPEC_PATH) != SPEC_BLOB:
        raise Blocked(f"{SPEC_PATH} is not the frozen P6-M10b blob {SPEC_BLOB}")
    return {"path": SPEC_PATH, "blob": SPEC_BLOB}


def _base():
    """The frozen p6m10-v1 base, only with the sha256 its fit record pinned."""
    from ml.strategy.outcome import load_registered_strategy_model

    fit = read_record("p6_m10_fit.json")
    if fit is None:
        raise Blocked("p6_m10_fit.json (the frozen base) is required")
    return load_registered_strategy_model(common.REGISTRY_DIR, version_tag=P6_M10_VERSION_TAG,
                                          expected_sha256=fit["registry"]["model_sha256"]), fit


def season_resolver(database):
    """events.season of an event key (static metadata), for §2's source seasons."""
    from ml.features.scale import ScaleLookup

    return ScaleLookup(database).event_season


def _any_2027(database) -> int:
    with database.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM matches WHERE season = %s", (HOLDOUT,))
        return cursor.fetchone()[0]


def eligible(rows, season: int) -> tuple[list, Counter]:
    """v1 §5's population (unchanged): qualification, all six teams with epa_total; ties excluded and counted."""
    from ml.dataset.builder import LABEL_TIE

    kept, excluded = [], Counter()
    for row in rows:
        teams = [*row.red_teams, *row.blue_teams]
        if row.season != season or row.comp_level != "qualification" or len(teams) != 6 \
                or not all(t.epa_total_present for t in teams):
            continue
        if row.label == LABEL_TIE:
            excluded["tie"] += 1
            continue
        kept.append(row)
    return kept, excluded


def _context(row):
    from ml.strategy.outcome import MatchContext

    return MatchContext(tuple(row.red_teams), tuple(row.blue_teams), prediction_season=row.season)


def _baselines(row):
    from ml.strategy.representation import Strategy

    return (Strategy.baseline([t.team_number for t in row.red_teams]),
            Strategy.baseline([t.team_number for t in row.blue_teams]))


def calibration_set(rows, base, season_of) -> dict[str, Any]:
    """§3's calibration set: the 2026 v1 population rows the base can score, with group, z and s. Refuses any row
    outside 2026, so a later season can never reach the fit."""
    from ml.dataset.builder import LABEL_RED_WIN
    from ml.strategy.calibration import source_group, stable_log_odds

    kept, excluded = eligible(rows, CALIBRATION_SEASON)
    groups, z, s, keys, latest = [], [], [], [], None
    for row in kept:
        if row.season != CALIBRATION_SEASON:
            raise Blocked("a non-2026 row reached the calibration set")
        red, blue = _baselines(row)
        evaluation = base.evaluate(_context(row), red, blue)
        if evaluation.p_red is None:
            excluded["model_input_absent"] += 1
            continue
        groups.append(source_group((*row.red_teams, *row.blue_teams), row.season, season_of))
        z.append(stable_log_odds(evaluation.mean_difference / evaluation.sigma))
        s.append(1 if row.label == LABEL_RED_WIN else -1)
        keys.append(row.match_key)
        latest = row.scheduled_time if latest is None or row.scheduled_time > latest else latest
    lines = "\n".join(json.dumps([k, g, repr(zz), ss]) for k, g, zz, ss in sorted(zip(keys, groups, z, s)))
    return {"groups": groups, "z": z, "s": s, "match_keys": keys, "excluded": dict(excluded),
            "latest": latest.isoformat() if latest else None, "seasons": [CALIBRATION_SEASON],
            "fingerprint": hashlib.sha256(lines.encode("utf-8")).hexdigest()}


# --- calibrate / pins -------------------------------------------------------------------------------------------


def run_calibrate(database, *_args) -> dict[str, Any]:
    """§3, once: requires DEV-M10b to have proceeded (otherwise v2 stops, §4) and no 2027 data."""
    from ml.registry import register_model
    from ml.strategy.calibration import (CALIBRATOR_MODEL_TYPE, CALIBRATOR_VERSION_TAG, GROUPS,
                                         CalibrationFitRefused, fit_calibrator)

    spec = _spec()
    dev = read_record(DEV_RECORD)
    if dev is None or not (dev.get("decision") or {}).get("proceed"):
        raise Blocked(f"{DEV_RECORD} is missing or did not proceed: the production calibrator is not fit (§4)")
    if _any_2027(database):
        raise Blocked("2027 matches exist: the calibrator must be fit and pinned before any 2027 data (§3)")
    base, fit = _base()
    rows, frame_hash = common.load_frame()
    if frame_hash != fit["frame_content_hash"]:
        raise Blocked("the D18 frame is not the one the base was fit and evaluated on")
    cal = calibration_set(rows, base, season_resolver(database))
    provenance = {"calibration_set": {k: cal[k] for k in ("fingerprint", "seasons", "latest", "excluded")},
                  "rows": len(cal["z"]), "frame_content_hash": frame_hash}
    try:
        calibrator = fit_calibrator(cal["groups"], cal["z"], cal["s"], base_sha256=base.artifact_sha256,
                                    fit_set_fingerprint=cal["fingerprint"])
    except CalibrationFitRefused as exc:  # §3: nothing registered, no retry; the write-once record names the check
        return {"milestone": "P6-M10b calibrator (§3)", "acceptance": False, "spec": spec, "refused": True,
                "check": exc.check, "details": exc.details, "base_sha256": base.artifact_sha256, **provenance}
    register_model(calibrator, registry_dir=common.REGISTRY_DIR, model_type=CALIBRATOR_MODEL_TYPE, model_version="1.0.0",
                   version_tag=CALIBRATOR_VERSION_TAG, training_dataset_hash=cal["fingerprint"],
                   feature_list=list(GROUPS), created_at=datetime.now(timezone.utc))
    return {"milestone": "P6-M10b calibrator (§3)", "acceptance": False, "spec": spec, "refused": False,
            **calibrator.to_dict(), **provenance}


def run_pins(database, *_args) -> dict[str, Any]:
    """§3: the additive pin record, before any 2027 data."""
    from ml.registry import model_file_sha256
    from ml.strategy.calibration import CALIBRATOR_MODEL_TYPE, CALIBRATOR_VERSION_TAG
    from ml.strategy.outcome import MODEL_TYPE

    spec = _spec()
    calibrator = read_record(CALIBRATOR_RECORD)
    if calibrator is None:
        raise Blocked(f"{CALIBRATOR_RECORD} is required")
    if calibrator.get("refused") is not False:
        raise Blocked(f"{CALIBRATOR_RECORD} records a refused fit ({calibrator.get('check')}): v2 stops (§3)")
    if _any_2027(database):
        raise Blocked("2027 matches exist: the pins are taken before any 2027 data")
    base_sha = model_file_sha256(common.REGISTRY_DIR, MODEL_TYPE, P6_M10_VERSION_TAG)
    if base_sha != calibrator["base_sha256"]:
        raise Blocked("the registered base is not the one the calibrator was fit on")
    return {"milestone": "P6-M10b pins", "acceptance": False, "spec": spec,
            "model_identity": {"base_sha256": base_sha,
                               "calibrator_sha256": model_file_sha256(common.REGISTRY_DIR, CALIBRATOR_MODEL_TYPE,
                                                                      CALIBRATOR_VERSION_TAG)}}


# --- final (§6) --------------------------------------------------------------------------------------------------


def check_authorization(value: dict[str, Any]) -> None:
    from ml.strategy.calibration import SPEC_BLOB

    if not (value.get("authorized") is True and value.get("authorized_by") and value.get("date")
            and value.get("scope") == "P6-M10b" and value.get("season") == HOLDOUT
            and value.get("season_complete_and_synced") is True and value.get("spec_blob") == SPEC_BLOB):
        raise Blocked(f"{AUTHORIZATION} does not authorize the P6-M10b 2027 run (authorized, authorized_by, date, "
                      "scope=P6-M10b, season=2027, season_complete_and_synced, spec_blob)")


def final_prerequisites() -> dict[str, Any]:
    """§6: every prerequisite, before any data is read. Absent ones are refused together; inconsistent ones at once."""
    from ml.registry import model_file_sha256
    from ml.strategy.calibration import CALIBRATOR_MODEL_TYPE, CALIBRATOR_VERSION_TAG
    from ml.strategy.outcome import MODEL_TYPE
    import scripts.phase6_px1b_final1 as final1

    if read_record(OUTCOME_RECORD) is not None:
        raise Blocked(f"{OUTCOME_RECORD} already exists: the P6-M10b run is once only and never overwritten")
    provenance: dict[str, Any] = {"spec": _spec()}
    missing: list[str] = []
    dev = read_record(DEV_RECORD)
    if dev is None or not (dev.get("decision") or {}).get("proceed"):
        missing.append(f"{DEV_RECORD} with DEV-M10b proceeded")
    pins = read_record(PINS_RECORD)
    if pins is None:
        missing.append(f"{PINS_RECORD} (the calibrator and base pins)")
    else:
        actual = {"base_sha256": model_file_sha256(common.REGISTRY_DIR, MODEL_TYPE, P6_M10_VERSION_TAG),
                  "calibrator_sha256": model_file_sha256(common.REGISTRY_DIR, CALIBRATOR_MODEL_TYPE,
                                                         CALIBRATOR_VERSION_TAG)}
        v1_sha = ((read_record("p6_m10_fit.json") or {}).get("registry") or {}).get("model_sha256")
        if actual != pins["model_identity"] or actual["base_sha256"] != v1_sha:  # §6: the base is v1 (aded2c82…)
            raise Blocked("the registered base or calibrator does not match its pin")
        provenance["model_identity"] = actual
    try:
        common.load_m6m7()  # sha-pinned
    except (FileNotFoundError, ValueError) as exc:
        raise Blocked(f"the M6/M7 d18 baseline does not match its pin: {exc}") from exc
    provenance["m6m7_sha256"] = M6M7_SHA256
    epa = read_record(final1.EPA_RECORD)
    if epa is None:
        missing.append(f"{final1.EPA_RECORD} (the pinned 2027 EPA source)")
    else:
        final1.verified_epa_source(epa)
        provenance["epa_source"] = {"record": final1.EPA_RECORD, "sha256": file_sha256(common.RESULTS_DIR / final1.EPA_RECORD)}
    frame = read_record(FRAME_RECORD)
    if frame is None:
        missing.append(f"{FRAME_RECORD} (the committed 2027 D18 frame record)")
    else:
        from scripts.run_phase4_stratai import frame_info
        if HOLDOUT not in frame.get("seasons", []) or \
                frame_info(Path(frame["frame_dir"]))["manifest"]["content_hash"] != frame.get("content_hash"):
            raise Blocked(f"{FRAME_RECORD}: the 2027 frame does not match its recorded content hash")
        provenance["frame"] = {k: frame[k] for k in ("frame_dir", "content_hash")}
    if pins is not None and frame is not None:
        pins_commit = final1.adding_commit(f".agent/phase6/results/{PINS_RECORD}")
        frame_commit = final1.adding_commit(f".agent/phase6/results/{FRAME_RECORD}")
        if pins_commit is None or frame_commit is None:
            raise Blocked(f"{PINS_RECORD} and {FRAME_RECORD} must both be committed, so their order is provable")
        if not final1.is_strict_ancestor(pins_commit, frame_commit):
            raise Blocked(f"the pins commit {pins_commit} is not a strict ancestor of the 2027 frame commit "
                          f"{frame_commit}")
        provenance["ordering"] = {"pins_commit": pins_commit, "frame_commit": frame_commit}
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8")) if AUTHORIZATION.exists() else None
    if authorization is None:
        missing.append(f"{AUTHORIZATION} (Kanav's authorization to run P6-M10b on 2027)")
    else:
        check_authorization(authorization)
        provenance["authorization"] = {"path": str(AUTHORIZATION), "sha256": file_sha256(AUTHORIZATION)}
    if OFFICIAL_EVENTS_RULE is None:
        missing.append("a dated definition of §5's 'official events' (the canonical events carry no event_type)")
    if missing:
        raise Blocked("P6-M10b cannot be evaluated yet; missing: " + "; ".join(missing))
    return provenance


def fit_isolation(base_fit_seasons, base_fit: dict[str, Any], calibrator_record: dict[str, Any],
                  earliest_evaluated: datetime) -> dict[str, Any]:
    """§5 (proposed and adopted) G4: base-fit rows only from 2024–2025 and calibrator-fit rows only from 2026; every fit
    row strictly before every evaluated 2027 row. The base seasons come from the base model's own fit_info, as v1."""
    base_seasons = set(base_fit_seasons)
    calibration = calibrator_record["calibration_set"]
    isolated = (base_seasons <= BASE_FIT_SEASONS and set(calibration["seasons"]) == {CALIBRATION_SEASON}
                and datetime.fromisoformat(base_fit["latest_fit_row"]) < earliest_evaluated
                and datetime.fromisoformat(calibration["latest"]) < earliest_evaluated)
    return {"base_fit_seasons": sorted(base_seasons), "calibration_seasons": calibration["seasons"],
            "latest_base_fit_row": base_fit["latest_fit_row"], "latest_calibration_row": calibration["latest"],
            "earliest_evaluated_row": earliest_evaluated.isoformat(), "fit_isolated": isolated}


def evaluate_gate(rows, model, m6m7_predict, base_fit: dict[str, Any], calibrator_record: dict[str, Any]
                  ) -> dict[str, Any]:
    """§5 on 2027: `evaluate_calibration_gate`, unchanged, on the calibrated q of the eligible rows; v1 raw and M6/M7
    are reported on the same rows, not gated."""
    from ml.backtest.bootstrap import ci_excludes_zero, event_bootstrap_mean_ci
    from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss
    from ml.calibration.gate import evaluate_calibration_gate
    from ml.dataset.builder import LABEL_RED_WIN

    kept, excluded = eligible(rows, HOLDOUT)
    q, raw, labels, symmetry, events, m6, used, groups = [], [], [], [], [], [], [], Counter()
    by_group: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for row in kept:
        red, blue = _baselines(row)
        forward = model.evaluate(_context(row), red, blue)
        if forward.p_red is None:
            excluded["model_input_absent"] += 1
            continue
        backward = model.evaluate(_context(row).swapped(), blue, red)
        q.append(forward.p_red)
        symmetry.append(abs(forward.p_red + backward.p_red - 1.0))
        raw.append(model.base.evaluate(_context(row), red, blue).p_red)
        labels.append(row.label == LABEL_RED_WIN)
        events.append(row.event_key)
        m6.append(m6m7_predict(row))
        groups[forward.calibration["group"]] += 1
        by_group[forward.calibration["group"]].append((forward.p_red, row.label == LABEL_RED_WIN))
        used.append(row)
    if not used:
        raise Blocked("no eligible 2027 rows")
    backward_order = [model.evaluate(_context(r), *_baselines(r)).p_red for r in reversed(used)]
    isolation = fit_isolation(model.base.fit_info["seasons"], base_fit, calibrator_record,
                              min(r.scheduled_time for r in used))
    gate = evaluate_calibration_gate(q, labels, symmetry_errors=symmetry,
                                     order_independent=q == list(reversed(backward_order)),
                                     fit_isolated=isolation["fit_isolated"])
    paired: dict[str, list[float]] = defaultdict(list)
    for a, b, y, e in zip(q, m6, labels, events):
        paired[e].append(log_loss([a], [y]) - log_loss([b], [y]))
    comparison = event_bootstrap_mean_ci(paired, seed=BOOTSTRAP_SEED)
    metrics = lambda p: {"ece": expected_calibration_error(p, labels), "log_loss": log_loss(p, labels),  # noqa: E731
                         "brier": brier_score(p, labels)}
    return {"population": {"season": HOLDOUT, "comp_level": "qualification", "epa_complete": True,
                           "evaluated": len(q), "excluded": dict(excluded), "groups": dict(groups)},
            "fit_isolation": isolation, "gate": gate.to_dict(), "passed": gate.passed,
            "metrics": metrics(q), "raw_v1_same_rows": metrics(raw), "m6m7_same_rows": metrics(m6),
            "paired_log_loss_minus_m6m7": {**comparison, "ci_excludes_zero": ci_excludes_zero(comparison),
                                           "gated": False},
            "per_group_calibration": {g: {"n": len(v), "calibration": _slope(v)} for g, v in sorted(by_group.items())}}


def _slope(pairs: list[tuple[float, bool]]) -> dict[str, float] | None:
    """§5, reported only: v1's diagnostic recalibration y ~ a + b·logit(q), per group; None when it is undefined."""
    import numpy as np

    from scripts.phase6_m10_diagnostics import calibration_slope

    p, y = [a for a, _ in pairs], [b for _, b in pairs]
    if len(set(y)) < 2:
        return None
    try:
        with np.errstate(over="ignore", invalid="ignore"):  # a separable group diverges; reported as None below
            result = calibration_slope(p, y)
    except np.linalg.LinAlgError:
        return None
    return result if all(np.isfinite(list(result.values()))) else None


def run_final(database, *_args) -> dict[str, Any]:
    """§6, once: the prerequisites, then the 2027 frame rows, then the unchanged gate. `main` writes the record."""
    from ml.backtest.harness import _match_features
    from ml.registry import load_registered_model
    from ml.strategy.calibration import (CALIBRATOR_MODEL_TYPE, CALIBRATOR_VERSION_TAG, GROUPS, Calibrator,
                                         CalibratedOutcomeModel)
    from scripts.run_phase4_stratai import load_frame_rows

    provenance = final_prerequisites()
    base, fit = _base()
    calibrator, _ = load_registered_model(Calibrator, registry_dir=common.REGISTRY_DIR, model_type=CALIBRATOR_MODEL_TYPE,
                                          version_tag=CALIBRATOR_VERSION_TAG, current_feature_list=list(GROUPS),
                                          expected_sha256=provenance["model_identity"]["calibrator_sha256"])
    model = CalibratedOutcomeModel(base, calibrator, season_resolver(database))
    m6m7 = common.load_m6m7()
    rows = load_frame_rows(Path(provenance["frame"]["frame_dir"]))
    result = evaluate_gate(rows, model, lambda r: m6m7.predict_win_prob(_match_features(r)), fit,
                           read_record(CALIBRATOR_RECORD))
    return {"milestone": "P6-M10b (P6-M10 v2) 2027 acceptance", "decision": "P6-Q9 (v2)",
            "acceptance_note": "a pass does not switch serving: Kanav's sha-matched confirmation and a passing P6-M13 "
                               "parity rerun on this identity are also required (§7)",
            "model_identity": provenance["model_identity"], "provenance_inputs": provenance, **result}


RUNS = {"calibrate": (CALIBRATOR_RECORD, run_calibrate), "pins": (PINS_RECORD, run_pins),
        "final": (OUTCOME_RECORD, run_final)}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in RUNS:
        print(__doc__)
        return 2
    started = time.time()
    database = isolated_database()
    name, run = RUNS[args[0]]
    result = run(database)
    result["minutes"] = round((time.time() - started) / 60, 1)
    result["over_budget"] = time.time() - started > BUDGET_SECONDS
    path = write_once(name, result)
    print(json.dumps({k: result.get(k) for k in ("passed", "minutes", "over_budget")}), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
