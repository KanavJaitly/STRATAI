"""Which predictions a served model's validation label may describe (audit 2026-11-26, workstream 3).

A label like `approximately_calibrated_qualification` or `validated_as_measured` is evidence measured somewhere: on a
season the model never saw, at a particular point in an event. Served outside that scope it overstates what is known.
This module is the one place those scopes are written down; every route that serves a served D18 model's label asks it.

**Seasons** (D7 split; `scripts/register_d18_production_models.py` fits both served models on `fold.train_rows`, and
their manifests record `held_out_2026_*` metrics):
- **Training seasons, 2024 and 2025.** The served M5 v2 ranking model and the M6/M7 win-probability pair were fit on
  them, so a prediction for a 2024 or 2025 match or event is IN-SAMPLE. It is never labelled validated or calibrated
  (reason `training_season`); the value is still shown, as an unvalidated model output.
- **The evaluation season, 2026.** Held out from training, but examined repeatedly since (D15, D18, the M7 diagnostic,
  P5-M4, the 2026-11-26 audit). The evidence is retrospective, so validated labels carry the qualifier
  `evidence_retrospective_2026`.
- **Later seasons (2027 on).** Genuinely out of sample for these models; the label still rests on the 2026 evidence,
  so it carries the same qualifier. Only a pre-registered evaluation on 2027 itself can replace it.

**Within an event** (P5-M4 criterion (b), `scripts/phase5_m4_event_analysis.py`): M5 v2's ordering was measured at the
event's switch point, with qualification still in progress. `validated_as_measured` is served only in that window:
after the switch point and before the event's last scheduled qualification match. Outside it (after qualification,
during playoffs, or later) the ordering is `not_validated` with reason `outside_measured_window`.
"""

from __future__ import annotations

from datetime import datetime

SERVED_D18_TRAINING_SEASONS: frozenset[int] = frozenset({2024, 2025})
SERVED_D18_EVALUATION_SEASON = 2026

REASON_TRAINING_SEASON = "training_season"
REASON_OUTSIDE_MEASURED_WINDOW = "outside_measured_window"
QUALIFIER_RETROSPECTIVE_EVIDENCE = "evidence_retrospective_2026"


def season_of_event(event_key: str) -> int | None:
    """The season an event key names (its first four digits), or None."""
    head = event_key[:4]
    return int(head) if head.isdigit() else None


def is_training_season(season: int | None) -> bool:
    """True when the served D18 models were fit on this season (their predictions on it are in-sample)."""
    return season is not None and season in SERVED_D18_TRAINING_SEASONS


def evidence_qualifier(season: int | None) -> str | None:
    """The qualifier a validated label carries for this season: the evidence is the 2026 retrospective evaluation.
    None for a training season (which is never validated) or an unknown season."""
    if season is None or is_training_season(season):
        return None
    return QUALIFIER_RETROSPECTIVE_EVIDENCE


def in_measured_window(as_of: datetime, switch_time: datetime | None, last_qualification: datetime | None) -> bool:
    """True when `as_of` is after the event's switch point and no later than its last scheduled qualification match:
    the window M5 v2's ordering was measured in (P5-M4 (b)). Unknown bounds are never inside the window."""
    if switch_time is None or last_qualification is None:
        return False
    return switch_time < as_of <= last_qualification


__all__ = ["QUALIFIER_RETROSPECTIVE_EVIDENCE", "REASON_OUTSIDE_MEASURED_WINDOW", "REASON_TRAINING_SEASON",
           "SERVED_D18_EVALUATION_SEASON", "SERVED_D18_TRAINING_SEASONS", "evidence_qualifier", "in_measured_window",
           "is_training_season", "season_of_event"]
