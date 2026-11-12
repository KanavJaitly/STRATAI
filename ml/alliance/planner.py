"""P11A B5/B6/C/D/E: alliance value and the first- and second-pick plan, from an event snapshot and the draft state.

Pure: the caller supplies the confirmed draft state as plain values (`DraftPosition`). The Phase 11 draft record is
the only source of confirmed availability, and nothing here predicts other captains' picks.

**Alliance value V** (B5):
- V is the expected points of a **three-robot active lineup** under the approved season scoring configuration.
  Per component:
  - the alliance sum is normal, with mean a'μ (after per-robot caps) and variance a'Σa + σ², i.e. estimation plus
    alliance-level match residual;
  - the rule is then applied: linear sum, alliance cap, threshold bonus (`ml.alliance.scoring_config`).
- Fouls are added as the event's observed qualification mean when the configuration says so.
- With four alliance members (3-pick events), V is the best three-robot lineup, never a four-robot sum (B3). Backup
  robots are never in V.

**The plan** (C, D, E):
- **Captain** (on an alliance, or projected to captain one):
  - the first-pick list ranks each candidate c by V₁(c) = max over d of V(members + c + d). That is
    `availability_not_modelled`: every team not confirmed unavailable counts as available (the P11A-Q1 proposed
    default);
  - each of the top K first picks gets its own conditional second-pick list;
  - backup combinations are listed;
  - once the first pick is recorded, the second-pick list is the conditional list for the actual first pick.
- **Non-captain:** destinations only, i.e. each other alliance's value with this team added. It never presents
  choices this team does not control. Invitation likelihood is withheld (`pick_model_unavailable`).

**Comparisons** (B6):
- Adjacent first picks are compared on the difference of their alliances' **expected** values, under estimation
  uncertainty only (shared draws of the joint posterior, so common members cancel).
- δ and π are not approved, so every comparison is `unresolved` (`comparison_threshold_not_approved`), with P(Δ > 0)
  and the Δ interval reported.

**Labels on every plan:**
- `objective: expected_alliance_score` (points);
- `win_probability: not_available`;
- `validation_status: not_validated`;
- `interval_status: not_calibrated` (E2: nominal 80% covered 68% of playoff alliance scores; playoff scores ran
  about 6 points above prediction on average; no correction is applied);
- `thresholds_status: candidate_unapproved`.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from data.game_spec import GameSpec
from ml.alliance.estimator import ESTIMATOR_VERSION, ComponentFit, EstimatorError, EstimatorPolicy
from ml.alliance.scoring_config import (
    ResolvedScoring,
    ScoringConfigError,
    SeasonScoringConfig,
    alliance_component_mean,
    expected_component_points,
    find_config,
    require_approved,
)
from ml.alliance.snapshot import COMPONENTS, EventSnapshot

PLANNER_VERSION = "p11a-planner-v1"
TOP_K = 5
MAX_LIST = 15
DRAWS = 400
LIMITATIONS = (
    "E2 benchmark: nominal 80% intervals covered 68% of 2024-2026 playoff alliance scores; intervals are not "
    "calibrated (docs/P11-E2-Benchmark-Report.md section 8)",
    "E2 benchmark: playoff alliances scored on average about 6 points above qualification-based expectations; the sign "
    "and size vary by season; no correction is applied (section 19-20)",
    "Robot contributions are statistical estimates from alliance-level scores; no individual robot contribution is "
    "validated (no qualifying per-robot ground truth)",
    "Defense and feeding have no measured effect on points; they are shown as scouted descriptions only",
    "Availability before your turn is not modelled: every team not confirmed unavailable is treated as available",
    "No opponent adjustment: robot estimates do not account for opponent strength; no pre-registered comparison has "
    "shown that one improves held-out prediction (spec A3.5)",
    "Components are estimated and sampled separately: covariance across auto, teleop and endgame is not modelled, so "
    "an alliance's component totals are treated as independent (spec A3.3, B5.3; not yet tested by a pre-registered "
    "comparison)",
    "A robot's own match-to-match variability cannot be separated from alliance-level noise using alliance scores; "
    "it is modelled at the alliance level (spec B5.2(b))",
)
PER_ROBOT_CAP_NOTE = ("Per-robot caps in this season's configuration are applied to each robot's estimated mean, not to "
                      "sampled contributions: an approximation (spec B5.1, B5.2(c))")
CURRENT_EVENT_PRIOR_NOTE = "prior estimated from this event's own matches"


@dataclass(frozen=True)
class DraftPosition:
    """The confirmed draft state as the planner needs it, from the Phase 11 record (workspaces.alliance_plan)."""

    team_number: int
    record_seq: int
    # "captain" | "on_alliance" (picked, not captain) | "projected_captain" | "non_captain" | "no_remaining_turn"
    mode: str
    seed: int | None
    members: tuple[int, ...]  # our alliance's confirmed members (including us), or () when we are not on one
    picks_remaining: int
    turns_before: int | None
    available: tuple[int, ...]  # confirmed available
    unavailable: dict[int, str] = field(default_factory=dict)  # confirmed unavailable -> reason
    other_alliances: tuple[tuple[int, tuple[int, ...]], ...] = ()  # (seed, members incl. projected captain)
    ruleset_sha256: str | None = None  # spec H4: the selection rules behind the record (None for manual entry)
    rules_source: str | None = None  # "approved_ruleset" | "manual_entry"


class PlanWithheld(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _Model:
    fits: dict[str, ComponentFit]
    scoring: ResolvedScoring
    fouls: float
    index: dict[int, int]

    def value(self, lineups: np.ndarray) -> np.ndarray:
        """Expected points of three-robot lineups (rows of team indices), under the predictive distribution: the
        lineup sum's estimation variance a'Σa (full joint covariance) plus the alliance-level match residual."""
        total = 0.0
        for c in COMPONENTS:
            fit, rule = self.fits[c], self.scoring.rules[c]
            m = alliance_component_mean(rule, fit.mean[lineups])
            est_var = fit.cov[lineups[:, :, None], lineups[:, None, :]].sum(axis=(1, 2))
            total = total + expected_component_points(rule, m, est_var + fit.sigma2)
        return total + self.fouls

    def best_lineup_value(self, members: Sequence[int]) -> tuple[float, tuple[int, ...]]:
        """V of the best three-robot lineup drawn from `members` (three or four teams)."""
        best = None
        for lineup in itertools.combinations(members, 3):
            v = float(self.value(np.array([[self.index[t] for t in lineup]]))[0])
            if best is None or v > best[0]:
                best = (v, lineup)
        return best


def _resolve(snapshot: EventSnapshot, scoring_dir: Path | None = None) -> ResolvedScoring:
    """The approved scoring for the snapshot's season.

    The trust root is the version-controlled registry (`data/season_scoring/<season>.json`, or `scoring_dir`), not the
    snapshot: a configuration's review fields are plain JSON, so a snapshot could otherwise carry a self-attested
    "approved" configuration. The snapshot's embedded configuration must equal the registered approved one exactly
    (content and review), and scoring uses the registry copy. The GameSpec must hash to the configuration's reference."""
    if snapshot.scoring_config is None:
        raise PlanWithheld("scoring_config_not_approved", f"no scoring configuration exists for {snapshot.season}")
    if snapshot.game_spec is None:
        raise PlanWithheld("game_spec_not_approved", f"no approved GameSpec exists for {snapshot.season}")
    try:
        embedded = require_approved(SeasonScoringConfig.model_validate(snapshot.scoring_config), snapshot.season)
        registered = find_config(snapshot.season, scoring_dir)
        if registered is None:
            raise PlanWithheld("scoring_config_not_registered", f"no {snapshot.season} configuration is registered "
                                                                "in data/season_scoring; a snapshot cannot bring its "
                                                                "own approval")
        require_approved(registered, snapshot.season)
        if registered.model_dump(mode="json") != embedded.model_dump(mode="json"):
            raise PlanWithheld("scoring_config_not_registered", "the snapshot's scoring configuration differs from "
                                                                f"the registered approved {snapshot.season} one")
        return ResolvedScoring.resolve(registered, GameSpec.model_validate(snapshot.game_spec))
    except ScoringConfigError as exc:
        raise PlanWithheld(exc.code, exc.message) from None
    except PlanWithheld:
        raise
    except ValueError as exc:
        raise PlanWithheld("scoring_config_invalid", str(exc)) from None


def _model(snapshot: EventSnapshot, policy: EstimatorPolicy, scoring_dir: Path | None = None) -> _Model:
    scoring = _resolve(snapshot, scoring_dir)
    try:
        fits = snapshot.fit(policy)
    except EstimatorError as exc:
        raise PlanWithheld(exc.code, exc.message) from None
    degenerate = [c for c, f in fits.items() if f.degenerate]
    if degenerate:
        raise PlanWithheld("estimator_fit_unreliable", f"the {', '.join(degenerate)} fit is degenerate (the noise "
                                                       "estimate is on its lower bound); its intervals would be "
                                                       "falsely narrow")
    fouls = snapshot.mean_fouls() if scoring.fouls == "event_mean" else 0.0
    return _Model(fits, scoring, float(fouls or 0.0), fits["auto"].index())


SCREEN_NOTE = ("non-authoritative: sigma^2/var(y) measures the residual share of the variance, so it also fires on "
               "well-fitted high-signal events; no data-only check tested detects short-schedule collapse reliably "
               "(docs/phase11.md, P11A hardening)")


def fit_diagnostics(fits: dict[str, ComponentFit], policy: EstimatorPolicy) -> dict[str, Any]:
    """Per component: the fitted variances and the noise diagnostics, the screen labelled non-authoritative."""
    out = {}
    for c, f in fits.items():
        noise = f.noise
        out[c] = {"sigma2": round(f.sigma2, 3), "tau2": round(f.tau2, 3), "rows": f.rows,
                  "degenerate": f.degenerate,
                  # capped: near sigma^2 = 0 the objective is ill-conditioned, so only "far above 3.84" is meaningful
                  "sigma2_zero_lr": None if noise is None else round(min(noise.lr_zero, 100.0), 1),
                  "residual_df": None if noise is None else noise.residual_df,
                  "collapse_screen": {"ratio": None if f.collapse_ratio is None else round(f.collapse_ratio, 4),
                                      "threshold": policy.collapse_ratio, "flagged": f.screen_flagged,
                                      "status": "non_authoritative", "note": SCREEN_NOTE}}
    return out


def robot_estimates(fits: dict[str, ComponentFit], team: int) -> dict[str, Any]:
    """One robot's component estimates with SD, prior kind, w_eff and labels (`estimated`, not validated)."""
    index = fits["auto"].index()
    out = {"team_number": team, "components": {}, "labels": set(), "n": None}
    for c in COMPONENTS:
        fit = fits[c]
        i = index[team]
        diag = fit.diagnostics[i]
        out["components"][c] = {"estimate": round(float(fit.mean[i]), 2), "sd": round(float(np.sqrt(fit.cov[i, i])), 2),
                                "kind": "estimated", "prior_kind": diag.prior_kind, "w_eff": round(diag.w_eff, 3),
                                "labels": list(diag.labels),
                                "prior_mean": None if diag.prior_mean is None else round(diag.prior_mean, 2),
                                "prior_sd": None if diag.prior_sd is None else round(diag.prior_sd, 2),
                                "max_abs_corr": round(diag.max_abs_corr, 3), "label_reasons": list(diag.label_reasons)}
        out["labels"].update(diag.labels)
        out["n"] = diag.n
        out["partners"] = diag.partners
    out["labels"] = sorted(out["labels"])
    return out


def _statements(model: _Model, team: int, lineup_value: float, rob: dict) -> list[str]:
    """Fixed templates over computed factors (G1). No free text; no thresholds beyond the stated labels."""
    comps = rob["components"]
    top = max(COMPONENTS, key=lambda c: comps[c]["estimate"])
    lines = [f"Largest estimated contribution: {top} {comps[top]['estimate']:.1f} ± {comps[top]['sd']:.1f} points "
             f"(estimated from {rob['n']} qualification matches)"]
    for c in COMPONENTS:
        cap = model.scoring.rules[c].cap_points
        if cap is not None:
            lines.append(f"{c.capitalize()} is capped at {cap:g} alliance points by the season rules")
    joint = [c for c in COMPONENTS if comps[c]["prior_kind"] == "current_event_joint"]
    if joint:  # spec A3.2 disclosure: cards say the prior came from this event's own matches
        lines.append(f"{CURRENT_EVENT_PRIOR_NOTE.capitalize()} ({', '.join(joint)}; current_event_joint)")
    if "prior_dominated" in rob["labels"]:
        lines.append("Estimate is prior-dominated (few matches or little information); treat with caution")
    if "weakly_identified" in rob["labels"]:
        lines.append(f"Estimate is weakly identified (played with {rob['partners']} distinct partners or is strongly "
                     "correlated with a partner's estimate)")
    lines.append(f"Expected alliance score of the best lineup with this pick: {lineup_value:.1f} points "
                 "(expected score, not a chance of winning)")
    return lines


def _draws(model: _Model, seed_text: str, draws: int) -> dict[str, np.ndarray]:
    seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:16], 16)
    rng = np.random.default_rng(seed)
    return {c: rng.multivariate_normal(f.mean, f.cov, size=draws, method="cholesky") for c, f in model.fits.items()}


def _compare(model: _Model, draws: dict[str, np.ndarray], a: Sequence[int], b: Sequence[int]) -> dict[str, Any]:
    if sorted(a) == sorted(b):  # two first picks whose best lineups are the same three robots: nothing to compare
        return {"compared": "same three-robot lineup (each is the other's best second pick)",
                "p_delta_positive": None, "delta_mean": 0.0, "delta_interval_80": [0.0, 0.0],
                "outcome": "unresolved", "reason": "same_lineup"}
    la = np.array([[model.index[t] for t in a]])
    lb = np.array([[model.index[t] for t in b]])
    va, vb = _value_draws(model, la, draws), _value_draws(model, lb, draws)
    delta = va - vb
    return {"compared": "difference of expected alliance scores under estimation uncertainty",
            "p_delta_positive": round(float((delta > 0).mean()), 3),
            "delta_mean": round(float(delta.mean()), 2),
            "delta_interval_80": [round(float(np.percentile(delta, 10)), 2), round(float(np.percentile(delta, 90)), 2)],
            "outcome": "unresolved", "reason": "comparison_threshold_not_approved"}


def _value_draws(model: _Model, lineup: np.ndarray, draws: dict[str, np.ndarray]) -> np.ndarray:
    """V of one lineup under each estimation draw (the residual is kept inside each expectation)."""
    total = 0.0
    for c in COMPONENTS:
        fit, rule = model.fits[c], model.scoring.rules[c]
        m = alliance_component_mean(rule, draws[c][:, lineup[0]])
        total = total + expected_component_points(rule, m, np.full(m.shape, fit.sigma2))
    return total + model.fouls


def top_combinations(values: dict[tuple[int, int], float], k: int) -> list[dict[str, Any]]:
    """D2: the k best complete alliances {us, c, d} over **every** pair, by unrounded V (ties by team numbers), so the
    list is the global top k and its order never depends on rounding or on which first-pick card found a pair."""
    unique = {tuple(sorted(pair)): v for pair, v in values.items()}
    best = sorted(unique.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    return [{"picks": list(pair), "expected_alliance_score": round(v, 1)} for pair, v in best]


def build_plan(snapshot: EventSnapshot, position: DraftPosition, *, policy: EstimatorPolicy = EstimatorPolicy(),
               draws: int = DRAWS, scoring_dir: Path | None = None) -> dict[str, Any]:
    """The P11A plan for `position` from `snapshot`. Raises PlanWithheld with the exact reason when a gate is unmet."""
    model = _model(snapshot, policy, scoring_dir)
    known = set(model.index)
    available = [t for t in position.available if t in known and t != position.team_number]
    no_estimate = sorted(t for t in position.available if t not in known)
    base = {
        "snapshot_id": snapshot.snapshot_id(), "record_seq": position.record_seq, "event_key": snapshot.event_key,
        "as_of": snapshot.as_of, "mode": position.mode, "seed": position.seed, "members": list(position.members),
        "picks_remaining": position.picks_remaining, "turns_before": position.turns_before,
        "objective": "expected_alliance_score", "unit": "points",
        "win_probability": {"status": "not_available", "reason": "no validated opponent model or calibration"},
        "validation_status": "not_validated", "interval_status": "not_calibrated",
        "thresholds_status": policy.status, "availability_model": "not_modelled",
        "availability": {"confirmed_available": available,
                         "confirmed_unavailable": [{"team_number": t, "reason": r}
                                                   for t, r in sorted(position.unavailable.items())],
                         "no_estimate": no_estimate, "predicted": None},
        "fit_diagnostics": fit_diagnostics(model.fits, policy),
        "versions": {"estimator": ESTIMATOR_VERSION, "planner": PLANNER_VERSION,
                     "scoring_config_sha256": model.scoring.config_sha256,
                     "game_spec_sha256": model.scoring.game_spec_sha256,
                     "ruleset_sha256": position.ruleset_sha256, "rules_source": position.rules_source},
        "known_limitations": list(LIMITATIONS) + ([PER_ROBOT_CAP_NOTE] if any(
            r.per_robot_cap_points is not None for r in model.scoring.rules.values()) else []),
        # spec B5.7: the Monte Carlo is seeded; its run count and error are recorded
        "monte_carlo": {"draws": draws, "seed_basis": "sha256(snapshot_id:record_seq:team_number)",
                        "p_delta_positive_mc_se_max": round(0.5 / np.sqrt(draws), 4),
                        "note": "p_delta_positive is a share of the draws; its Monte Carlo SE is at most 0.5/sqrt(draws). "
                                "The 80% interval ends are draw percentiles and carry Monte Carlo error too"},
        # spec B5.6: defense and feeding add zero points until a measured effect exists (P6-M10 rule; P11A-Q8)
        "defense_effect": {"status": "defense_effect_insufficient_data", "points": 0.0,
                           "reason": "no measured effect of defense or feeding on points; scouted values are reported, "
                                     "never converted to points"}}
    if position.team_number not in known:
        raise PlanWithheld("team_without_estimate", f"team {position.team_number} has no qualification data here")
    if position.mode == "no_remaining_turn":
        raise PlanWithheld("no_remaining_turn", "this alliance has no turn left")
    draw = _draws(model, f"{base['snapshot_id']}:{position.record_seq}:{position.team_number}", draws)

    if position.mode == "non_captain":
        destinations = []
        for seed, members in position.other_alliances:
            if not all(t in known for t in members):
                destinations.append({"seed": seed, "members": list(members), "status": "withheld",
                                     "reason": "a member has no estimate"})
                continue
            group = [*members, position.team_number]
            if len(group) < 3:
                pool = [t for t in available if t not in group]
                best = max(((model.best_lineup_value([*group, t]), t) for t in pool), default=None)
                value, lineup = best[0] if best else (None, None)
            else:
                value, lineup = model.best_lineup_value(group)
            destinations.append({"seed": seed, "members": list(members),
                                 "expected_alliance_score": None if value is None else round(value, 1),
                                 "lineup": list(lineup) if lineup else None})
        return {**base, "destinations": sorted(destinations, key=lambda d: -(d.get("expected_alliance_score") or 0)),
                "invitation_likelihood": {"status": "withheld", "reason": "pick_model_unavailable"},
                "note": "You do not choose your partners: these are the alliances you could join, valued with you "
                        "added"}

    members = list(position.members) or [position.team_number]
    if len(members) + position.picks_remaining < 3:
        raise PlanWithheld("invalid_position", "an alliance needs three active robots")
    cards = []
    values: dict[tuple[int, int], float] = {}
    if len(members) == 1 and position.picks_remaining >= 2:  # first pick, with conditional second picks
        pairs = list(itertools.combinations(available, 2))
        me = model.index[members[0]]
        lineups = np.array([[me, model.index[c], model.index[d]] for c, d in pairs]).reshape(-1, 3)
        batch = model.value(lineups) if pairs else np.empty(0)  # one vectorised pass over every {us, c, d}
        for (c, d), v in zip(pairs, batch):
            values[(c, d)] = values[(d, c)] = float(v)
        for c in available:
            seconds = sorted(((values[(c, d)], d) for d in available if d != c), reverse=True)
            if not seconds:
                continue
            cards.append({"team_number": c, "value": seconds[0][0], "best_second": seconds[0][1],
                          "seconds": seconds[:MAX_LIST]})
        cards.sort(key=lambda x: (-x["value"], x["team_number"]))
        stage = "first_pick"
    else:  # the next pick only: second pick, or the fourth member at 3-pick events
        current, _ = model.best_lineup_value(members) if len(members) >= 3 else (None, None)
        for c in available:
            group = [*members, c]
            if len(group) < 3:
                best = max(((model.best_lineup_value([*group, d]), d) for d in available if d != c), default=None)
                if best is None:
                    continue
                (value, _), _d = best
            else:
                value, _ = model.best_lineup_value(group)
            gain = None if current is None else value - current
            cards.append({"team_number": c, "value": value, "lineup_gain": gain})
        cards.sort(key=lambda x: (-x["value"], x["team_number"]))
        stage = "fourth_member" if len(members) >= 3 else "next_pick"
    cards = cards[:MAX_LIST]
    out_cards = []
    for i, card in enumerate(cards):
        rob = robot_estimates(model.fits, card["team_number"])
        lineup = card.get("best_second")
        group = [*members, card["team_number"]] + ([lineup] if lineup is not None else [])
        _, best_lineup = model.best_lineup_value(group) if len(group) >= 3 else (None, group)
        lineup_draws = _value_draws(model, np.array([[model.index[t] for t in best_lineup]]), draw)
        entry = {"rank": i + 1, "team_number": card["team_number"], "expected_alliance_score": round(card["value"], 1),
                 "estimation_interval_80": [round(float(np.percentile(lineup_draws, 10)), 1),
                                            round(float(np.percentile(lineup_draws, 90)), 1)],
                 "interval_note": "estimation uncertainty of the expected score only; not a prediction interval; "
                                  "not calibrated",
                 "lineup": list(best_lineup), "robot": rob, "availability": "confirmed_available",
                 "statements": _statements(model, card["team_number"], card["value"], rob),
                 "scouting": snapshot.scouting.get(card["team_number"])}
        if stage == "first_pick":
            entry["conditional_seconds"] = [{"team_number": d, "expected_alliance_score": round(v, 1)}
                                            for v, d in card["seconds"][:MAX_LIST]] if i < TOP_K else None
        if card.get("lineup_gain") is not None:
            entry["lineup_gain"] = round(card["lineup_gain"], 1)
        out_cards.append(entry)
    comparisons = []
    for a, b in zip(out_cards, out_cards[1:]):
        comparisons.append({"a": a["team_number"], "b": b["team_number"],
                            **_compare(model, draw, a["lineup"], b["lineup"])})
    combos = top_combinations(values, 5) if stage == "first_pick" else []
    return {**base, "stage": stage, "cards": out_cards, "comparisons": comparisons, "backup_combinations": combos,
            "combinations_note": None if len(combos) >= 3 or stage != "first_pick" else
            f"only {len(combos)} distinct combinations exist"}


__all__ = ["DraftPosition", "LIMITATIONS", "PLANNER_VERSION", "PlanWithheld", "build_plan", "fit_diagnostics",
           "robot_estimates"]
