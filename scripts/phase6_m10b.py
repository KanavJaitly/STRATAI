"""P6-M10b runs under the frozen `.agent/phase6/P6_M10B_SPEC.md` (blob d699afaf; frozen 2026-10-10 at 22e4d7b).
Isolated `stratai_test` only.

    python -m scripts.phase6_m10b dev         # §4: DEV-M10b, diagnostic only (2024 base, 2025 calibrator, 2026)
    python -m scripts.phase6_m10b calibrate   # §3: fit and register the C-R calibrator on 2026 (needs DEV-M10b to proceed)
    python -m scripts.phase6_m10b pins        # §3: the additive pin record (base + calibrator sha256), before 2027 data
    python -m scripts.phase6_m10b final       # §6: the one-time 2027 acceptance run (fail-closed prerequisites)

Implemented 2026-10-10 (`dev` added the same day). **None of these has been run.**
- Running them needs Kanav's separate authorization: DEV-M10b first, then the calibrator, then the 2027 run.
- `dev` and `final` also refuse without their authorization files, written by Kanav.
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
# §4 DEV-M10b: diagnostic only. Its base and calibrator are never registered, pinned or served.
DEV_MILESTONE = "P6-M10b DEV-M10b (§4), diagnostic only"
DEV_BASE_SEASON, DEV_CALIBRATION_SEASON, DEV_EVALUATION_SEASON = 2024, 2025, 2026
DEV_AUTHORIZATION = Path(".agent/phase6/decisions/p6_m10b_dev_authorization.json")
CALIBRATION_REFUSALS = ("prediction_season_absent", "epa_source_unresolvable", "epa_source_later_season",
                        "probit_index_not_finite")  # ml.strategy.calibration's REASON_* values


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


def dev_proceeded(dev: dict[str, Any] | None) -> bool:
    """§4: only a DEV-M10b record of this frozen spec whose proceed rule held lets v2 continue."""
    from ml.strategy.calibration import SPEC_BLOB

    return (dev is not None and dev.get("milestone") == DEV_MILESTONE and (dev.get("spec") or {}).get("blob") == SPEC_BLOB
            and (dev.get("decision") or {}).get("proceed") is True)


def calibration_set(rows, base, season_of, season: int = CALIBRATION_SEASON) -> dict[str, Any]:
    """§3's calibration set: the `season` (2026; DEV: 2025) v1 population rows the base can score, with group, z and
    s. Refuses any row outside that season, so no other season can reach the fit."""
    from ml.dataset.builder import LABEL_RED_WIN
    from ml.strategy.calibration import source_group, stable_log_odds

    kept, excluded = eligible(rows, season)
    groups, z, s, keys, latest = [], [], [], [], None
    for row in kept:
        if row.season != season:
            raise Blocked(f"a non-{season} row reached the calibration set")
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
            "latest": latest.isoformat() if latest else None, "seasons": [season],
            "fingerprint": hashlib.sha256(lines.encode("utf-8")).hexdigest()}


# --- calibrate / pins -------------------------------------------------------------------------------------------


def run_calibrate(database, *_args) -> dict[str, Any]:
    """§3, once: requires DEV-M10b to have proceeded (otherwise v2 stops, §4) and no 2027 data."""
    from ml.registry import register_model
    from ml.strategy.calibration import (CALIBRATOR_MODEL_TYPE, CALIBRATOR_VERSION_TAG, GROUPS,
                                         CalibrationFitRefused, fit_calibrator)

    spec = _spec()
    if not dev_proceeded(read_record(DEV_RECORD)):
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
    if not dev_proceeded(read_record(DEV_RECORD)):
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
                  earliest_evaluated: datetime, *, allowed_base_seasons=frozenset(BASE_FIT_SEASONS),
                  calibration_season: int = CALIBRATION_SEASON) -> dict[str, Any]:
    """§5 (proposed and adopted) G4: base-fit rows only from 2024–2025 and calibrator-fit rows only from 2026; every fit
    row strictly before every evaluated 2027 row. The base seasons come from the base model's own fit_info, as v1."""
    base_seasons = set(base_fit_seasons)
    calibration = calibrator_record["calibration_set"]
    isolated = (bool(base_seasons) and base_seasons <= set(allowed_base_seasons)
                and set(calibration["seasons"]) == {calibration_season}
                and datetime.fromisoformat(base_fit["latest_fit_row"]) < earliest_evaluated
                and datetime.fromisoformat(calibration["latest"]) < earliest_evaluated)
    return {"base_fit_seasons": sorted(base_seasons), "calibration_seasons": calibration["seasons"],
            "latest_base_fit_row": base_fit["latest_fit_row"], "latest_calibration_row": calibration["latest"],
            "earliest_evaluated_row": earliest_evaluated.isoformat(), "fit_isolated": isolated}


def _predictions(kept, model, excluded: Counter) -> dict[str, Any]:
    """Each eligible row the model scores: the calibrated q and the raw base p on the same rows, both colour orders
    (G3), the label, event and group. Rows it cannot score are counted by reason; a §2 refusal is counted apart from
    an absent v1 input, so the claim that §2 refusals are unreachable is checked, not assumed."""
    from ml.dataset.builder import LABEL_RED_WIN

    out: dict[str, Any] = {k: [] for k in ("q", "raw", "labels", "events", "symmetry_q", "symmetry_raw", "used")}
    groups: Counter = Counter()
    by_group: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for row in kept:
        red, blue = _baselines(row)
        forward = model.evaluate(_context(row), red, blue)
        if forward.p_red is None:
            reason = (forward.reasons or ("",))[0].removeprefix("missing_input:")
            excluded[f"calibration_refused:{reason}" if reason in CALIBRATION_REFUSALS else "model_input_absent"] += 1
            continue
        backward = model.evaluate(_context(row).swapped(), blue, red)
        raw_forward = model.base.evaluate(_context(row), red, blue)
        raw_backward = model.base.evaluate(_context(row).swapped(), blue, red)
        label = row.label == LABEL_RED_WIN
        out["q"].append(forward.p_red)
        out["raw"].append(raw_forward.p_red)
        out["symmetry_q"].append(abs(forward.p_red + backward.p_red - 1.0))
        out["symmetry_raw"].append(abs(raw_forward.p_red + raw_backward.p_red - 1.0))
        out["labels"].append(label)
        out["events"].append(row.event_key)
        out["used"].append(row)
        groups[forward.calibration["group"]] += 1
        by_group[forward.calibration["group"]].append((forward.p_red, label))
    if not out["used"]:
        raise Blocked("no eligible rows")
    reverse = list(reversed(out["used"]))
    out["order_independent_q"] = out["q"] == list(reversed(
        [model.evaluate(_context(r), *_baselines(r)).p_red for r in reverse]))
    out["order_independent_raw"] = out["raw"] == list(reversed(
        [model.base.evaluate(_context(r), *_baselines(r)).p_red for r in reverse]))
    out["groups"], out["by_group"] = dict(groups), by_group
    return out


def _metrics(p, labels) -> dict[str, Any]:
    from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss

    return {"ece": expected_calibration_error(p, labels), "log_loss": log_loss(p, labels),
            "brier": brier_score(p, labels)}


def _per_group(by_group) -> dict[str, Any]:
    return {g: {"n": len(v), "calibration": _slope(v)} for g, v in sorted(by_group.items())}


def _fingerprint(match_keys) -> str:
    """sha256 of the sorted match keys: which rows a set holds, independent of order."""
    return hashlib.sha256("\n".join(sorted(match_keys)).encode("utf-8")).hexdigest()


def evaluate_gate(rows, model, m6m7_predict, base_fit: dict[str, Any], calibrator_record: dict[str, Any]
                  ) -> dict[str, Any]:
    """§5 on 2027: `evaluate_calibration_gate`, unchanged, on the calibrated q of the eligible rows; v1 raw and M6/M7
    are reported on the same rows, not gated."""
    from ml.backtest.bootstrap import ci_excludes_zero, event_bootstrap_mean_ci
    from ml.backtest.metrics import log_loss
    from ml.calibration.gate import evaluate_calibration_gate

    kept, excluded = eligible(rows, HOLDOUT)
    scored = _predictions(kept, model, excluded)
    q, labels, used = scored["q"], scored["labels"], scored["used"]
    m6 = [m6m7_predict(r) for r in used]
    isolation = fit_isolation(model.base.fit_info["seasons"], base_fit, calibrator_record,
                              min(r.scheduled_time for r in used))
    gate = evaluate_calibration_gate(q, labels, symmetry_errors=scored["symmetry_q"],
                                     order_independent=scored["order_independent_q"],
                                     fit_isolated=isolation["fit_isolated"])
    paired: dict[str, list[float]] = defaultdict(list)
    for a, b, y, e in zip(q, m6, labels, scored["events"]):
        paired[e].append(log_loss([a], [y]) - log_loss([b], [y]))
    comparison = event_bootstrap_mean_ci(paired, seed=BOOTSTRAP_SEED)
    return {"population": {"season": HOLDOUT, "comp_level": "qualification", "epa_complete": True,
                           "evaluated": len(q), "excluded": dict(excluded), "groups": scored["groups"],
                           "fingerprint": _fingerprint(r.match_key for r in used)},
            "fit_isolation": isolation, "gate": gate.to_dict(), "passed": gate.passed,
            "metrics": _metrics(q, labels), "raw_v1_same_rows": _metrics(scored["raw"], labels),
            "m6m7_same_rows": _metrics(m6, labels),
            "paired_log_loss_minus_m6m7": {**comparison, "ci_excludes_zero": ci_excludes_zero(comparison),
                                           "gated": False},
            "per_group_calibration": _per_group(scored["by_group"])}


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


# --- dev (§4): DEV-M10b, diagnostic only ---------------------------------------------------------------------


def check_dev_authorization(value: dict[str, Any]) -> None:
    from ml.strategy.calibration import SPEC_BLOB

    if not (value.get("authorized") is True and value.get("authorized_by") and value.get("date")
            and value.get("scope") == "DEV-M10b" and value.get("spec_blob") == SPEC_BLOB):
        raise Blocked(f"{DEV_AUTHORIZATION} does not authorize DEV-M10b (authorized, authorized_by, date, "
                      "scope=DEV-M10b, spec_blob)")


def dev_prerequisites() -> dict[str, Any]:
    """Before any data is read. DEV runs once, before the production calibrator, under the frozen spec and the
    frozen v1 procedure; absent items are refused together, inconsistent ones at once."""
    from ml.strategy.outcome import SPEC_PATH as V1_SPEC_PATH

    if read_record(DEV_RECORD) is not None:
        raise Blocked(f"{DEV_RECORD} already exists: DEV-M10b runs once and is never overwritten")
    if read_record(CALIBRATOR_RECORD) is not None:
        raise Blocked(f"{CALIBRATOR_RECORD} exists: DEV-M10b must precede the production calibrator (§4)")
    provenance: dict[str, Any] = {"spec": _spec()}
    missing: list[str] = []
    fit = read_record("p6_m10_fit.json")
    if fit is None:
        missing.append("p6_m10_fit.json (the v1 fit record: frame, v1 spec sha256)")
    else:
        if file_sha256(V1_SPEC_PATH) != fit["spec_sha256"]:
            raise Blocked(f"{V1_SPEC_PATH} is not the v1 specification the base was fit under")
        provenance["v1_procedure"] = {"spec": V1_SPEC_PATH, "spec_sha256": fit["spec_sha256"],
                                      "spec_blob": git_blob(V1_SPEC_PATH)}
    authorization = (json.loads(DEV_AUTHORIZATION.read_text(encoding="utf-8")) if DEV_AUTHORIZATION.exists()
                     else None)
    if authorization is None:
        missing.append(f"{DEV_AUTHORIZATION} (Kanav's authorization to run DEV-M10b)")
    else:
        check_dev_authorization(authorization)
        provenance["authorization"] = {"path": str(DEV_AUTHORIZATION), "sha256": file_sha256(DEV_AUTHORIZATION)}
    if missing:
        raise Blocked("DEV-M10b cannot be run yet; missing: " + "; ".join(missing))
    return provenance


def _identified(artifact, cls):
    """The artifact saved and loaded back, so it carries the sha256 of its serialized file. DEV artifacts live only
    in a temporary directory: they are never registered, pinned or served."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "artifact.json"
        artifact.save(path)
        return cls.load(path)


def dev_decision(refusal: dict[str, Any] | None, raw_gate, calibrated_gate) -> dict[str, Any]:
    """§4's proceed rule (C5), all three: (i) the §3 fit succeeds; (ii) calibrated G2 rejections ≤ raw, strictly
    fewer unless raw has 0; (iii) calibrated ECE ≤ raw ECE. A G2 the gate calls unevaluable has no measured rejection
    count (the gate reports 0), and an absent ECE has no value, so neither can satisfy (ii) or (iii): fail-closed."""
    from ml.calibration.gate import G2_UNEVALUABLE

    rule = {"i_fit_succeeded": refusal is None, "ii_g2_rejections_reduced": False, "iii_ece_not_worse": False}
    detail: dict[str, Any] = {}
    if refusal is None and raw_gate is not None and calibrated_gate is not None:
        measured = G2_UNEVALUABLE not in (raw_gate.g2.status, calibrated_gate.g2.status)
        raw_rejections, calibrated_rejections = raw_gate.g2.rejected_bins, calibrated_gate.g2.rejected_bins
        rule["ii_g2_rejections_reduced"] = measured and calibrated_rejections <= raw_rejections and (
            calibrated_rejections < raw_rejections or raw_rejections == 0)
        rule["iii_ece_not_worse"] = (raw_gate.ece is not None and calibrated_gate.ece is not None
                                     and calibrated_gate.ece <= raw_gate.ece)
        detail = {"g2_measured": measured, "raw_g2_rejections": raw_rejections,
                  "calibrated_g2_rejections": calibrated_rejections, "raw_ece": raw_gate.ece,
                  "calibrated_ece": calibrated_gate.ece}
    proceed = all(rule.values())
    return {"proceed": proceed, "rule": rule, **detail,
            "consequence": "the production calibrator may be fit, on Kanav's separate authorization" if proceed
            else "v2 stops: no production calibrator and no FINAL run; a further version would be needed (§4)"}


def dev_evaluate(rows, model, calibration: dict[str, Any]) -> tuple[dict[str, Any], Any, Any]:
    """§4 step 3: the raw DEV base and the calibrated DEV model, on the same 2026 rows, through the unchanged gate."""
    from ml.calibration.gate import evaluate_calibration_gate

    kept, excluded = eligible(rows, DEV_EVALUATION_SEASON)
    scored = _predictions(kept, model, excluded)
    labels, used = scored["labels"], scored["used"]
    isolation = fit_isolation(model.base.fit_info["seasons"], model.base.fit_info, {"calibration_set": calibration},
                              min(r.scheduled_time for r in used), allowed_base_seasons={DEV_BASE_SEASON},
                              calibration_season=DEV_CALIBRATION_SEASON)
    raw_gate = evaluate_calibration_gate(scored["raw"], labels, symmetry_errors=scored["symmetry_raw"],
                                         order_independent=scored["order_independent_raw"],
                                         fit_isolated=isolation["fit_isolated"])
    calibrated_gate = evaluate_calibration_gate(scored["q"], labels, symmetry_errors=scored["symmetry_q"],
                                                order_independent=scored["order_independent_q"],
                                                fit_isolated=isolation["fit_isolated"])
    result = {"population": {"season": DEV_EVALUATION_SEASON, "comp_level": "qualification", "epa_complete": True,
                             "evaluated": len(used), "excluded": dict(excluded), "groups": scored["groups"],
                             "fingerprint": _fingerprint(r.match_key for r in used)},
              "fit_isolation": isolation,
              "raw": {"gate": raw_gate.to_dict(), "metrics": _metrics(scored["raw"], labels)},
              "calibrated": {"gate": calibrated_gate.to_dict(), "metrics": _metrics(scored["q"], labels)},
              "per_group_calibration": _per_group(scored["by_group"])}
    return result, raw_gate, calibrated_gate


def run_dev(database, *_args) -> dict[str, Any]:
    """§4, once: refit the v1 procedure on 2024, fit the §3 calibrator on 2025, evaluate on 2026. Diagnostic only."""
    from ml.strategy.calibration import Calibrator, CalibratedOutcomeModel, CalibrationFitRefused, fit_calibrator
    from ml.strategy.outcome import NOT_VALIDATED, ComponentOutcomeModel
    from scripts.phase6_m10_fit import component_fit_set

    provenance = dev_prerequisites()
    fit = read_record("p6_m10_fit.json")
    rows, frame_hash = common.load_frame()
    if frame_hash != fit["frame_content_hash"]:
        raise Blocked("the D18 frame is not the one v1 was fit and evaluated on")
    season_of = season_resolver(database)

    samples, used, base_excluded = component_fit_set(rows, (DEV_BASE_SEASON,), database)
    if not samples or {r.season for r in used} != {DEV_BASE_SEASON}:
        raise Blocked(f"the DEV base fit set is empty or not {DEV_BASE_SEASON}-only")
    info = {"frame_content_hash": frame_hash, "seasons": [DEV_BASE_SEASON], "comp_level": "qualification",
            "excluded": dict(base_excluded), "latest_fit_row": max(r.scheduled_time for r in used).isoformat(),
            "spec_blob": provenance["v1_procedure"]["spec_blob"], "purpose": DEV_MILESTONE}
    base = _identified(ComponentOutcomeModel.fit(samples, fit_info=info, spec_sha256=fit["spec_sha256"]),
                       ComponentOutcomeModel)
    base = base.with_status(version_tag="p6m10b-dev-base", baseline_status=(NOT_VALIDATED, "dev_m10b_diagnostic"))
    record: dict[str, Any] = {
        "milestone": DEV_MILESTONE, "diagnostic_only": True, "acceptance": False, "authorizes_serving": False,
        "evidence_class": "consistency evidence only, never independent acceptance evidence: 2026 motivated this "
                          "design (§4). It cannot switch serving: only the §7 guard can.",
        "spec": provenance["spec"], "v1_procedure": provenance["v1_procedure"], "frame_content_hash": frame_hash,
        "seasons": {"base_fit": DEV_BASE_SEASON, "calibration": DEV_CALIBRATION_SEASON,
                    "evaluation": DEV_EVALUATION_SEASON},
        "base": {"sha256": base.artifact_sha256, "registered": False, "beta": base.beta,
                 "sigma_matrix": base.sigma_matrix.tolist(), "sigma": base.sigma, "fit_rows": len(samples),
                 "excluded": dict(base_excluded), "latest_fit_row": info["latest_fit_row"],
                 "fit_set_fingerprint": _fingerprint(r.match_key for r in used)},
        "provenance_inputs": provenance}

    cal = calibration_set(rows, base, season_of, season=DEV_CALIBRATION_SEASON)
    record["calibration_set"] = {"fingerprint": cal["fingerprint"], "rows": len(cal["z"]), "seasons": cal["seasons"],
                                 "latest": cal["latest"], "excluded": cal["excluded"],
                                 "groups": dict(Counter(cal["groups"]))}
    try:
        calibrator = fit_calibrator(cal["groups"], cal["z"], cal["s"], base_sha256=base.artifact_sha256,
                                    fit_set_fingerprint=cal["fingerprint"])
    except CalibrationFitRefused as exc:
        record["calibrator"] = {"refused": True, "check": exc.check, "details": exc.details, "registered": False}
        record["evaluation"] = None
        record["decision"] = dev_decision(record["calibrator"], None, None)
        return record
    calibrator = _identified(calibrator, Calibrator)
    record["calibrator"] = {"refused": False, "registered": False, "sha256": calibrator.artifact_sha256,
                            **calibrator.to_dict()}
    model = CalibratedOutcomeModel(base, calibrator, season_of)
    record["evaluation"], raw_gate, calibrated_gate = dev_evaluate(rows, model, record["calibration_set"])
    record["decision"] = dev_decision(None, raw_gate, calibrated_gate)
    return record


RUNS = {"dev": (DEV_RECORD, run_dev), "calibrate": (CALIBRATOR_RECORD, run_calibrate), "pins": (PINS_RECORD, run_pins),
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
    summary = {k: result.get(k) for k in ("passed", "minutes", "over_budget")}
    summary["proceed"] = (result.get("decision") or {}).get("proceed") if isinstance(result.get("decision"), dict) \
        else None
    print(json.dumps(summary), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
