"""P11A G2: one team's profile at an event, from the event snapshot (works offline).

The output is `ml.alliance.contract.P11AProfileOut`. Every section is either present, with its kind, or absent with a
reason (`<section>_absent_reason`). Nothing missing is invented.

**Sections:**
- **Identity, rank and data times:**
  - `as_of`;
  - `data_through` (latest qualification match in the snapshot);
  - the rank (`observed`, with its fetch time; left out of the snapshot when it was fetched after `as_of`).
- **Every qualification match:** the alliance's component points (`observed_alliance`, never the robot's own points)
  and the alliance-level residual against the A3 fit. A residual describes the **alliance's** match only (spec G2).
  No anomaly bound is approved, so nothing is flagged and no residual is attributed to this robot.
- **Estimated contributions** per component (`estimated`, `not_validated`):
  - uncertainty (SD);
  - sample sizes (rows played, distinct partners);
  - prior influence (`prior_kind`, w_eff; 1 − w_eff is the prior's share);
  - labels;
  - the event's fit diagnostics (the collapse screen is non-authoritative).
- **Consistency:** the SD of the team's alliance totals (`observed_alliance`).
- **Scouted defense and feeding:** quality ratings only, with their computation time, never points.
- **The prior:** from the team's earlier event (`estimated`, with its source event and end date).
- **Alliance fit with your team:** the best expected lineup score, only when the scoring configuration is approved and
  registered. Otherwise it is absent, with the reason.
- **Strengths and weaknesses:** not produced (Phase 16), so always absent, with the reason.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ml.alliance.estimator import EstimatorError, EstimatorPolicy
from ml.alliance.planner import PlanWithheld, _model, fit_diagnostics, robot_estimates
from ml.alliance.snapshot import COMPONENTS, SNAPSHOT_VERSION, EventSnapshot

ESTIMATE_NOTE = "estimated from alliance-level scores; not validated as this robot's own contribution"


def _prior(entry: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if not entry:
        return None, "no earlier same-season event with enough rows for this team"
    components = {c: {"mean": float(entry[c][0]), "variance": float(entry[c][1])} for c in COMPONENTS if c in entry}
    return {"kind": "estimated", "source_event": entry["source_event"], "end_date": entry["end_date"],
            "components": components}, None


def _scouting(entry: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if not entry:
        return None, "no scouting summary computed before as_of is in the snapshot"
    keep = ("kind", "defense", "defense_n", "feeding", "feeding_n", "computed_at", "defense_agreement",
            "feeding_agreement", "defense_insufficient_data", "feeding_insufficient_data")
    return {k: entry.get(k) for k in keep}, None


EXCLUSION_KEYS = ("what", "match_key", "color", "team_number", "reason", "known_at")


def _exclusion(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: entry.get(k) for k in EXCLUSION_KEYS}


def _last_updated(snapshot: EventSnapshot, team: int, prov: dict[str, Any]) -> str | None:
    """The newest of: the latest qualification match in the snapshot, the ranking fetch, this team's scouting summary."""
    times = [max((r.time for r in snapshot.qual_rows), default=None), prov.get("ranking_fetched_at"),
             (snapshot.scouting.get(team) or {}).get("computed_at")]
    parsed = []
    for t in times:
        if t in (None, "", "None"):
            continue
        try:
            when = datetime.fromisoformat(str(t))
        except ValueError:
            continue
        parsed.append((when if when.tzinfo else when.replace(tzinfo=timezone.utc), str(t)))
    return max(parsed)[1] if parsed else None


def team_profile(snapshot: EventSnapshot, team: int, *, our_team: int | None = None,
                 policy: EstimatorPolicy = EstimatorPolicy(), scoring_dir: Path | None = None) -> dict[str, Any]:
    if team not in snapshot.teams():
        raise PlanWithheld("team_not_at_event", f"team {team} is not on this event's roster")
    rows = [r for r in snapshot.qual_rows if team in r.teams]
    prov = snapshot.provenance
    prior, prior_reason = _prior(snapshot.priors.get(team))
    scouting, scouting_reason = _scouting(snapshot.scouting.get(team))
    out: dict[str, Any] = {
        "team_number": team, "event_key": snapshot.event_key, "snapshot_id": snapshot.snapshot_id(),
        "as_of": snapshot.as_of, "data_through": max((r.time for r in snapshot.qual_rows), default=None),
        "validation_status": "not_validated", "thresholds_status": policy.status,
        "rank": {"value": None if snapshot.ranks is None else snapshot.ranks.get(team),
                 "status": "observed" if snapshot.ranks is not None and team in snapshot.ranks else "not_available",
                 "fetched_at": prov.get("ranking_fetched_at")},
        "matches_played": len(rows),
        "prior": prior, "prior_absent_reason": prior_reason,
        "scouting": scouting, "scouting_absent_reason": scouting_reason,
        "strengths_and_weaknesses_absent_reason": "not produced by any engine (Phase 16)",
        "provenance": {"source": prov.get("source"), "built_at": prov.get("built_at"),
                       "ranking_fetched_at": prov.get("ranking_fetched_at"),
                       "prior_events": list(prov.get("prior_events") or []), "snapshot_version": SNAPSHOT_VERSION,
                       # spec G2/§8: what the snapshot left out, and why (the missing-data list)
                       "exclusions": [_exclusion(e) for e in snapshot.exclusions],
                       "scoring_config_sha256": None, "game_spec_sha256": None},
        # spec A7: the newest input time behind this profile (all at or before as_of)
        "last_updated": _last_updated(snapshot, team, prov),
        "estimates": None, "estimates_absent_reason": None, "fit_diagnostics": None,
        "alliance_fit": None, "alliance_fit_absent_reason": None,
    }
    totals = np.array([r.auto + r.teleop + r.endgame for r in rows], dtype=float)
    out["consistency"] = {"kind": "observed_alliance",
                          "alliance_points_sd": None if len(totals) < 2 else round(float(totals.std(ddof=1)), 1),
                          "alliance_points_mean": None if not len(totals) else round(float(totals.mean()), 1),
                          "n": len(totals)}
    try:
        fits = snapshot.fit(policy)
    except EstimatorError as exc:
        fits = None
        out["estimates_absent_reason"] = f"{exc.code}: {exc.message}"
    matches = []
    for r in rows:
        entry = {"match_key": r.match_key, "time": r.time, "color": r.color,
                 "partners": [t for t in r.teams if t != team], "kind": "observed_alliance",
                 **{c: getattr(r, c) for c in COMPONENTS}, "fouls": r.fouls,
                 "alliance_residual": None, "anomaly": None}
        if fits is not None:
            resid = {}
            for c in COMPONENTS:
                fit = fits[c]
                a = fit.vector(r.teams)
                pred = float(a @ fit.mean)
                sd = float(np.sqrt(a @ fit.cov @ a + fit.sigma2))
                resid[c] = {"residual": round(getattr(r, c) - pred, 1), "z": round((getattr(r, c) - pred) / sd, 2)}
            entry["alliance_residual"] = resid
            entry["anomaly"] = {"status": "not_flagged", "reason": "no G2 anomaly bound is approved; a residual "
                                                                   "describes the alliance's match, never this robot"}
        matches.append(entry)
    out["matches"] = matches
    if fits is not None:
        out["fit_diagnostics"] = fit_diagnostics(fits, policy)
        if team in fits["auto"].index():
            out["estimates"] = {**robot_estimates(fits, team), "validation_status": "not_validated",
                                "note": ESTIMATE_NOTE}
        else:
            out["estimates_absent_reason"] = "the team played no qualification match before as_of"
    if our_team is None or our_team == team:
        out["alliance_fit_absent_reason"] = "no other team to fit with (your team is not at this event, or is this one)"
    else:
        try:
            model = _model(snapshot, policy, scoring_dir)
            pool = [t for t in model.index if t not in (team, our_team)]
            if our_team not in model.index or team not in model.index or not pool:
                raise PlanWithheld("team_without_estimate", "a team in the lineup has no estimate")
            value, lineup = max((model.best_lineup_value([our_team, team, t]) for t in pool), key=lambda v: v[0])
            out["provenance"]["scoring_config_sha256"] = model.scoring.config_sha256
            out["provenance"]["game_spec_sha256"] = model.scoring.game_spec_sha256
            out["alliance_fit"] = {"with_team": our_team, "expected_alliance_score": round(value, 1),
                                   "lineup": list(lineup), "unit": "points",
                                   "note": "best expected lineup score with any third robot; expected score, not a "
                                           "chance of winning; availability not considered"}
        except PlanWithheld as exc:
            out["alliance_fit_absent_reason"] = f"{exc.code}: {exc.message}"
    return out


__all__ = ["team_profile"]
