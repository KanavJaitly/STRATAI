"""PX-2b v2 (`.agent/phase6/P6_M3_PX2B_SPEC_V2.md`, blob b4397537; approved 2026-10-08): out-of-sample calibration.

v1 fit the calibrator on `px1b-v1`'s own predictions of a slice it had trained on (in-sample; the C1 audit). In v2:
- the **slice** is v1's: the temporally last 20% of eligible 2026 PX-1b rows, frozen as the 526 match keys in
  `.agent/phase6/diagnostics/px2b_c1_slice_provenance.json`;
- a **calibration-base model** is fit by PX-1b's frozen spec on eligible rows strictly earlier than the slice and from
  no event that has a slice row (M7's held-out procedure, made event-disjoint);
- the **calibrator** is fit only on the base model's predictions of the slice, each proven out-of-sample for its
  match and its event;
- the calibrator is **applied to `px1b-v1`**, which stays the candidate.

Pure: nothing here reads a database or a 2027 row.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ml.playoffs.px1 import PlayoffLogisticModel, PlayoffRow

SPEC_PATH = ".agent/phase6/P6_M3_PX2B_SPEC_V2.md"
SPEC_BLOB = "b4397537755acd818ed24cba6b9586ddc6e09f32"
SLICE_PROVENANCE = Path(".agent/phase6/diagnostics/px2b_c1_slice_provenance.json")
CALBASE_MODEL_TYPE, CALBASE_VERSION_TAG = "playoff_px1b_calbase", "px2b-v2"
SLICE_FRACTION = 0.8  # rows [int(0.8 n):] -- P6-Q4's rule, unchanged
CALIBRATION_SEASON = 2026


class CalibrationIsolationError(ValueError):
    """The calibration-base fit set and the calibration slice are not isolated as v2 §2.2 requires."""


def calibration_slice(rows: Sequence[PlayoffRow], season: int = CALIBRATION_SEASON) -> list[PlayoffRow]:
    """v2 §2.1 (v1's rule): eligible rows of `season` sorted by (scheduled_time, match_key), rows [int(0.8 n):]."""
    ordered = sorted((r for r in rows if r.season == season), key=lambda r: (r.scheduled_time, r.match_key))
    return ordered[int(len(ordered) * SLICE_FRACTION):]


def frozen_slice_keys(path: Path = SLICE_PROVENANCE) -> list[str]:
    """The 526 slice match keys recorded by the C1 audit, in slice order."""
    return [row["match_key"] for row in json.loads(Path(path).read_text(encoding="utf-8"))["slice"]]


def require_frozen_slice(slice_rows: Sequence[PlayoffRow], frozen_keys: Sequence[str]) -> None:
    """v2 §2.1: the slice built now must be exactly the frozen one (same keys, same order); otherwise refuse."""
    built = [r.match_key for r in slice_rows]
    if built != list(frozen_keys):
        missing, extra = set(frozen_keys) - set(built), set(built) - set(frozen_keys)
        raise CalibrationIsolationError(f"the calibration slice differs from the frozen 526-row slice: "
                                        f"{len(built)} rows built, {len(missing)} frozen keys missing, "
                                        f"{len(extra)} unexpected keys")


def calibration_base_rows(rows: Sequence[PlayoffRow], slice_rows: Sequence[PlayoffRow]) -> list[PlayoffRow]:
    """v2 §2.2: eligible rows strictly earlier than the slice's first row AND from no event that has a slice row."""
    if not slice_rows:
        raise CalibrationIsolationError("empty calibration slice")
    start = min(r.scheduled_time for r in slice_rows)
    slice_events = {r.event_key for r in slice_rows}
    return sorted((r for r in rows if r.scheduled_time < start and r.event_key not in slice_events),
                  key=lambda r: (r.scheduled_time, r.match_key))


def straddling_events(rows: Sequence[PlayoffRow], slice_rows: Sequence[PlayoffRow]) -> list[str]:
    """Events with rows both before the slice's first row and in the slice: their earlier rows are excluded."""
    start = min(r.scheduled_time for r in slice_rows)
    slice_events = {r.event_key for r in slice_rows}
    return sorted({r.event_key for r in rows if r.scheduled_time < start and r.event_key in slice_events})


def isolation_report(base_keys: Sequence[str], base_events: Sequence[str], base_latest, slice_rows: Sequence[PlayoffRow]
                     ) -> dict[str, Any]:
    """Per-prediction proof (requirement 3): for every slice row, its match AND its event are absent from the base
    fit set, and the whole fit set precedes the slice. Timestamps alone are not relied on."""
    keys, events = set(base_keys), set(base_events)
    per_row = [{"match_key": r.match_key, "event_key": r.event_key, "match_in_fit": r.match_key in keys,
                "event_in_fit": r.event_key in events} for r in slice_rows]
    first_slice = min(r.scheduled_time for r in slice_rows)
    return {"slice_rows": len(slice_rows), "base_rows": len(keys),
            "match_overlap": sum(p["match_in_fit"] for p in per_row),
            "event_overlap": sum(p["event_in_fit"] for p in per_row),
            "base_latest": base_latest.isoformat(), "slice_first": first_slice.isoformat(),
            "time_ordered": base_latest < first_slice,
            "isolated": not any(p["match_in_fit"] or p["event_in_fit"] for p in per_row) and base_latest < first_slice}


def require_isolated(report: dict[str, Any]) -> None:
    if not report["isolated"]:
        raise CalibrationIsolationError(f"calibration predictions would not be out-of-sample: {report['match_overlap']} "
                                        f"match and {report['event_overlap']} event overlaps; time_ordered="
                                        f"{report['time_ordered']}")


def fit_calibration_base(base_rows: Sequence[PlayoffRow]) -> PlayoffLogisticModel:
    """The calibration-base model: PX-1b's frozen spec §2-§4 (normalized composition), on the base rows only."""
    return PlayoffLogisticModel.fit(base_rows, normalized=True, model_type=CALBASE_MODEL_TYPE,
                                    fit_info={"role": "PX-2b v2 calibration base", "spec": SPEC_PATH})


def fit_out_of_sample_calibrator(base_model: PlayoffLogisticModel, base_keys: Sequence[str],
                                 base_events: Sequence[str], base_latest, slice_rows: Sequence[PlayoffRow]):
    """Requirement 4: the calibrator sees only the base model's predictions of the slice and their outcomes, after
    the per-row isolation proof passes. Returns (calibrator, isolation report)."""
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator

    report = isolation_report(base_keys, base_events, base_latest, slice_rows)
    require_isolated(report)
    predictions = [base_model.predict(r) for r in slice_rows]
    if any(p is None for p in predictions):
        raise CalibrationIsolationError("a slice row has an absent input for the calibration-base model")
    calibrator = SymmetricIsotonicCalibrator()
    calibrator.fit(predictions, [r.red_win for r in slice_rows])
    return calibrator, report
