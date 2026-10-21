"""P6-M10c runs under the frozen `.agent/phase6/P6_M10C_SPEC.md` (blob f24a8d1c; frozen 2026-10-11 at e0f6490).
Isolated `stratai_test` only.

    python -m scripts.phase6_m10c dev     # §4: DEV-c, diagnostic only (2024 base; 2025 weeks 0-3 -> weeks 4+ and CMP)

**DEV-c runs once**, only with `decisions/p6_m10c_dev_authorization.json` (Kanav). Its record is write-once.
- **It is diagnostic evidence only,** never acceptance.
- **A `proceed` does not authorize** a production fit, registration, pins, serving, or a gate change.
- P6-M10 stays `not_validated`.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from scripts import phase6_common as common
from scripts.phase6_common import file_sha256, git_blob, isolated_database, read_record, write_once
from scripts.phase6_m10b import (DEV_RECORD as M10B_DEV_RECORD, FAIL, PASS, UNEVALUABLE, _finite, _fingerprint,
                                 _identified, _metrics, _per_group, _predictions, calibration_set, eligible,
                                 gate_status, season_resolver)
from scripts.phase6_playoff_track import BUDGET_SECONDS, Blocked

DEV_RECORD = "p6_m10c_dev.json"
DEV_MILESTONE = "P6-M10c DEV-c (§4), diagnostic only"
AUTHORIZATION = Path(".agent/phase6/decisions/p6_m10c_dev_authorization.json")
BASE_SEASON, DEV_SEASON = 2024, 2025
CALIBRATION_WEEKS = (0, 1, 2, 3)
REGIONAL_DISTRICT_TYPES, CHAMPIONSHIP_TYPES = (0, 1, 2, 5), (3, 4)
BASE_TOLERANCE = 1e-12
EVENT_SQL = """
SELECT DISTINCT ON (source_object_id) source_object_id, payload_json->'event_type', payload_json->'week'
FROM raw_source_payloads
WHERE source = 'tba' AND source_object_type = 'event' AND is_current AND source_object_id = ANY(%s)
ORDER BY source_object_id, id DESC
"""


def _spec() -> dict[str, str]:
    from ml.strategy.calibration_m10c import SPEC_BLOB, SPEC_PATH

    if git_blob(SPEC_PATH) != SPEC_BLOB:
        raise Blocked(f"{SPEC_PATH} is not the frozen P6-M10c blob {SPEC_BLOB}")
    return {"path": SPEC_PATH, "blob": SPEC_BLOB}


def check_authorization(value: dict[str, Any]) -> None:
    from ml.strategy.calibration_m10c import SPEC_BLOB

    if not (value.get("authorized") is True and value.get("authorized_by") and value.get("date")
            and value.get("scope") == "DEV-c" and value.get("spec_blob") == SPEC_BLOB):
        raise Blocked(f"{AUTHORIZATION} does not authorize DEV-c (authorized, authorized_by, date, scope=DEV-c, "
                      "spec_blob)")


def dev_prerequisites() -> dict[str, Any]:
    """Before any data is read: once only; the frozen spec; DEV-M10b's base to reproduce; the authorization."""
    if read_record(DEV_RECORD) is not None:
        raise Blocked(f"{DEV_RECORD} already exists: DEV-c runs once and is never overwritten")
    provenance: dict[str, Any] = {"spec": _spec()}
    missing: list[str] = []
    if read_record(M10B_DEV_RECORD) is None:
        missing.append(f"{M10B_DEV_RECORD} (DEV-M10b's base, which §4.1 must reproduce)")
    if read_record("p6_m10_fit.json") is None:
        missing.append("p6_m10_fit.json (the v1 fit record: frame and v1 spec)")
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8")) if AUTHORIZATION.exists() else None
    if authorization is None:
        missing.append(f"{AUTHORIZATION} (Kanav's authorization to run DEV-c)")
    else:
        check_authorization(authorization)
        provenance["authorization"] = {"path": str(AUTHORIZATION), "sha256": file_sha256(AUTHORIZATION)}
    if missing:
        raise Blocked("DEV-c cannot be run yet; missing: " + "; ".join(missing))
    return provenance


def event_classes(database, event_keys) -> dict[str, str]:
    """§4.2: each event's class from its current raw TBA payload, fail-closed. C = types 0/1/2/5 in weeks 0-3;
    E = types 0/1/2/5 in week >= 4, or the Championship (types 3/4, whose week is null); other types: 'other'."""
    keys = sorted(set(event_keys))
    with database.cursor() as cursor:
        cursor.execute(EVENT_SQL, (keys,))
        found = {key: (event_type, week) for key, event_type, week in cursor.fetchall()}

    def integer(value):
        return isinstance(value, int) and not isinstance(value, bool)
    problems = [k for k in keys if k not in found or not integer(found[k][0])
                or (found[k][0] in REGIONAL_DISTRICT_TYPES and not integer(found[k][1]))]
    if problems:
        raise Blocked(f"DEV-c: the event type or week cannot be established for {problems} (fail-closed, §4.2)")
    classes = {}
    for key, (event_type, week) in found.items():
        if event_type in CHAMPIONSHIP_TYPES:
            classes[key] = "E"
        elif event_type in REGIONAL_DISTRICT_TYPES:
            classes[key] = "C" if week in CALIBRATION_WEEKS else "E" if week >= 4 else "other"
        else:
            classes[key] = "other"
    return classes


def temporal_checks(base_latest, calibration_rows, evaluation_rows) -> dict[str, Any]:
    """§4.3: refuses unless every check holds; fit isolation (G4's input) is true exactly then."""
    c_events = {r.event_key for r in calibration_rows}
    e_events = {r.event_key for r in evaluation_rows}
    c_keys = {r.match_key for r in calibration_rows}
    e_keys = {r.match_key for r in evaluation_rows}
    c_last = max(r.scheduled_time for r in calibration_rows)
    c_first = min(r.scheduled_time for r in calibration_rows)
    e_first = min(r.scheduled_time for r in evaluation_rows)
    checks = {"events_disjoint": not (c_events & e_events), "c_before_e": c_last < e_first,
              "base_before_c": base_latest < c_first, "matches_disjoint": not (c_keys & e_keys)}
    result = {**checks, "latest_c": c_last.isoformat(), "earliest_e": e_first.isoformat(),
              "latest_base_fit_row": base_latest.isoformat(), "fit_isolated": all(checks.values())}
    if not result["fit_isolated"]:
        raise Blocked(f"DEV-c: temporal ordering or leakage check failed: {checks}")
    return result


def dev_decision(m10c_refusal: dict[str, Any] | None, m10b_refusal: dict[str, Any] | None, m10c_gate,
                 m10b_gate) -> dict[str, Any]:
    """§4.6, predeclared. D1 the M10c fit; D2 the M10b-form comparator fit; D3 G2 rejections; D4 ECE. An
    unevaluable diagnostic never counts as a pass. proceed iff all pass; rule_not_met if any fail."""
    from ml.calibration.gate import G2_FAIL, G2_PASS

    d1 = {"status": PASS} if m10c_refusal is None else {"status": FAIL, "refusal": m10c_refusal}
    d2 = {"status": PASS} if m10b_refusal is None else {"status": UNEVALUABLE, "refusal": m10b_refusal}
    d3: dict[str, Any] = {"status": UNEVALUABLE}
    d4: dict[str, Any] = {"status": UNEVALUABLE}
    if d1["status"] == PASS and d2["status"] == PASS:
        statuses = (m10c_gate.g2.status, m10b_gate.g2.status)
        d3.update(m10c_g2_status=statuses[0], m10b_form_g2_status=statuses[1])
        if set(statuses) <= {G2_PASS, G2_FAIL}:
            c, b = m10c_gate.g2.rejected_bins, m10b_gate.g2.rejected_bins
            d3.update(m10c_rejections=c, m10b_form_rejections=b,
                      status=PASS if c <= b and (c < b or b == 0) else FAIL)
        else:
            d3["reason"] = "a G2 result is unevaluable; its zero rejection count is not a measurement"
        c_ece, b_ece = _finite(m10c_gate.ece), _finite(m10b_gate.ece)
        d4.update(m10c_ece=m10c_gate.ece, m10b_form_ece=m10b_gate.ece)
        if c_ece is not None and b_ece is not None:
            d4["status"] = PASS if c_ece <= b_ece else FAIL
        else:
            d4["reason"] = "an ECE is absent or not finite"
    else:
        d3["reason"] = d4["reason"] = "a fit did not pass (D1 or D2): there is nothing to compare"
    diagnostics = {"D1_m10c_fit": d1, "D2_m10b_form_fit": d2, "D3_g2_rejections": d3, "D4_ece": d4}
    statuses = {name: d["status"] for name, d in diagnostics.items()}
    proceed = all(s == PASS for s in statuses.values())
    outcome = "proceed" if proceed else "rule_not_met" if FAIL in statuses.values() else "unevaluable"
    return {"proceed": proceed, "outcome": outcome, "statuses": statuses, "diagnostics": diagnostics,
            "consequence": {"proceed": "M10c may be put to Kanav for adoption; nothing is registered or served",
                            "rule_not_met": "M10c stops: the predeclared rule failed; M10b stands as frozen",
                            "unevaluable": "DEV-c cannot decide: no adoption; M10b stands as frozen"}[outcome]}


def _evaluate(model, rows, isolation):
    from ml.calibration.gate import evaluate_calibration_gate

    kept, excluded = eligible(rows, DEV_SEASON)
    scored = _predictions(kept, model, excluded)
    gate = evaluate_calibration_gate(scored["q"], scored["labels"], symmetry_errors=scored["symmetry_q"],
                                     order_independent=scored["order_independent_q"],
                                     fit_isolated=isolation["fit_isolated"])
    return scored, excluded, gate


def run_dev(database, *_args) -> dict[str, Any]:
    """§4, once: the 2024 base (reproducing DEV-M10b's), both links fit on C, both evaluated on the identical E rows."""
    import numpy as np

    from ml.strategy.calibration import (Calibrator, CalibratedOutcomeModel, CalibrationFitRefused,
                                         fit_calibrator)
    from ml.strategy.calibration_m10c import FlooredCalibrator, FlooredOutcomeModel, fit_floored
    from ml.strategy.outcome import NOT_VALIDATED, ComponentOutcomeModel
    from scripts.phase6_m10_fit import component_fit_set

    provenance = dev_prerequisites()
    fit = read_record("p6_m10_fit.json")
    dev_m10b = read_record(M10B_DEV_RECORD)["base"]
    rows, frame_hash = common.load_frame()
    if frame_hash != fit["frame_content_hash"]:
        raise Blocked("DEV-c: the D18 frame is not frame_ab1adbf38b43c2f3")
    season_of = season_resolver(database)

    # §4.1 the base
    samples, used, base_excluded = component_fit_set(rows, (BASE_SEASON,), database)
    if not samples or {r.season for r in used} != {BASE_SEASON}:
        raise Blocked("DEV-c: the base fit set is empty or not 2024-only")
    base_latest = max(r.scheduled_time for r in used)
    info = {"frame_content_hash": frame_hash, "seasons": [BASE_SEASON], "comp_level": "qualification",
            "excluded": dict(base_excluded), "latest_fit_row": base_latest.isoformat(), "purpose": DEV_MILESTONE}
    base = ComponentOutcomeModel.fit(samples, fit_info=info, spec_sha256=fit["spec_sha256"])
    beta_diff = max(abs(base.beta[c] - dev_m10b["beta"][c]) for c in base.beta)
    sigma_diff = float(np.max(np.abs(base.sigma_matrix - np.asarray(dev_m10b["sigma_matrix"]))))
    if beta_diff > BASE_TOLERANCE or sigma_diff > BASE_TOLERANCE:
        raise Blocked(f"DEV-c: the 2024 base does not reproduce DEV-M10b's (beta {beta_diff}, sigma {sigma_diff})")
    base = _identified(base, ComponentOutcomeModel).with_status(
        version_tag="p6m10c-dev-base", baseline_status=(NOT_VALIDATED, "dev_c_diagnostic"))

    # §4.2 classes
    season_rows = [r for r in rows if r.season == DEV_SEASON]
    classes = event_classes(database, (r.event_key for r in season_rows))
    by_class = {k: [r for r in season_rows if classes[r.event_key] == k] for k in ("C", "E", "other")}
    other_rows = len(eligible(by_class["other"], DEV_SEASON)[0])

    # §4.2: rows refused by §2 (source rules) are counted apart, never fit; then §4.4 fits on C (identical rows for
    # both links). calibration_set re-applies the v1 population rules and the base's own refusals, and counts them.
    from ml.strategy.calibration import CalibrationInputError, source_group

    c_eligible, _ = eligible(by_class["C"], DEV_SEASON)
    c_rows, c_refused = [], Counter()
    for row in c_eligible:
        try:
            source_group((*row.red_teams, *row.blue_teams), DEV_SEASON, season_of)
            c_rows.append(row)
        except CalibrationInputError as exc:
            c_refused[f"calibration_refused:{exc.reason}"] += 1
    cal = calibration_set(c_rows, base, season_of, season=DEV_SEASON)
    cal["excluded"] = {**dict(eligible(by_class["C"], DEV_SEASON)[1]), **cal["excluded"], **dict(c_refused)}
    c_used = [r for r in by_class["C"] if r.match_key in set(cal["match_keys"])]
    record: dict[str, Any] = {
        "milestone": DEV_MILESTONE, "diagnostic_only": True, "acceptance": False, "authorizes_serving": False,
        "authorizes_registration": False,
        "evidence_class": "consistency evidence only, never independent acceptance evidence (§4.6): 2025 C was "
                          "DEV-M10b's calibration season, the M10c design came from 2026, and within-season "
                          "transfer is not the cross-season transfer 2027 needs",
        "spec": provenance["spec"], "frame_content_hash": frame_hash, "provenance_inputs": provenance,
        "base": {"sha256": base.artifact_sha256, "registered": False, "fit_rows": len(samples),
                 "excluded": dict(base_excluded), "latest_fit_row": base_latest.isoformat(),
                 "fit_set_fingerprint": _fingerprint(r.match_key for r in used),
                 "reproduces_dev_m10b": {"max_abs_beta_diff": beta_diff, "max_abs_sigma_diff": sigma_diff}},
        "classes": {"rule": "C: event_type in {0,1,2,5} and week in {0,1,2,3}; E: event_type in {0,1,2,5} and "
                            "week >= 4, or event_type in {3,4}; other: excluded",
                    "events": dict(Counter(classes.values())), "other_eligible_rows": other_rows},
        "calibration_set": {"rows": len(cal["z"]), "fingerprint": cal["fingerprint"], "latest": cal["latest"],
                            "excluded": cal["excluded"], "groups": dict(Counter(cal["groups"]))},
        "global_fit_reading": "§3: the global fit is always computed and recorded; its checks gate the result only "
                              "when its slope is used (a group with n < 200). Fixed 2026-10-11, before any fit"}
    m10c_refusal = m10b_refusal = None
    m10c_cal = m10b_cal = None
    try:
        m10c_cal = _identified(fit_floored(cal["groups"], cal["z"], cal["s"], base_sha256=base.artifact_sha256,
                                           fit_set_fingerprint=cal["fingerprint"]), FlooredCalibrator)
        record["m10c_fit"] = {"refused": False, "sha256": m10c_cal.artifact_sha256, **m10c_cal.to_dict()}
    except CalibrationFitRefused as exc:
        m10c_refusal = {"check": exc.check, "details": exc.details}
        record["m10c_fit"] = {"refused": True, **m10c_refusal}
    try:
        m10b_cal = _identified(fit_calibrator(cal["groups"], cal["z"], cal["s"], base_sha256=base.artifact_sha256,
                                              fit_set_fingerprint=cal["fingerprint"]), Calibrator)
        record["m10b_form_fit"] = {"refused": False, "sha256": m10b_cal.artifact_sha256, **m10b_cal.to_dict()}
    except CalibrationFitRefused as exc:
        m10b_refusal = {"check": exc.check, "details": exc.details}
        record["m10b_form_fit"] = {"refused": True, **m10b_refusal}

    # §4.3 temporal ordering and leakage, on the scorable C rows and the E rows the models score
    e_rows = by_class["E"]
    if m10c_cal is None or m10b_cal is None:
        record["evaluation"] = None
        record["decision"] = dev_decision(m10c_refusal, m10b_refusal, None, None)
        record["temporal"] = temporal_checks(base_latest, c_used, eligible(e_rows, DEV_SEASON)[0])
        return record
    m10c_model = FlooredOutcomeModel(base, m10c_cal, season_of)
    m10b_model = CalibratedOutcomeModel(base, m10b_cal, season_of)
    probe, _, _ = _evaluate(m10c_model, e_rows, {"fit_isolated": True})
    record["temporal"] = isolation = temporal_checks(base_latest, c_used, probe["used"])

    # §4.5 both on the identical E rows
    c_scored, c_excluded, c_gate = _evaluate(m10c_model, e_rows, isolation)
    b_scored, b_excluded, b_gate = _evaluate(m10b_model, e_rows, isolation)
    if [r.match_key for r in c_scored["used"]] != [r.match_key for r in b_scored["used"]]:
        raise Blocked("DEV-c: the two models do not score the identical evaluation rows (§4.5)")
    labels = c_scored["labels"]
    record["evaluation"] = {
        "population": {"season": DEV_SEASON, "class": "E", "evaluated": len(labels), "excluded": dict(c_excluded),
                       "groups": c_scored["groups"], "events": len({r.event_key for r in c_scored["used"]}),
                       "fingerprint": _fingerprint(r.match_key for r in c_scored["used"])},
        "m10c": {"gate": c_gate.to_dict(), "status": gate_status(c_gate), "metrics": _metrics(c_scored["q"], labels),
                 "per_group_calibration": _per_group(c_scored["by_group"])},
        "m10b_form": {"gate": b_gate.to_dict(), "status": gate_status(b_gate),
                      "metrics": _metrics(b_scored["q"], labels),
                      "per_group_calibration": _per_group(b_scored["by_group"])},
        "raw_base": {"metrics": _metrics(c_scored["raw"], labels)}}
    record["decision"] = dev_decision(None, None, c_gate, b_gate)
    return record


RUNS = {"dev": (DEV_RECORD, run_dev)}


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
    decision = result.get("decision") or {}
    print(json.dumps({"outcome": decision.get("outcome"), "statuses": decision.get("statuses"),
                      "minutes": result["minutes"]}), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
