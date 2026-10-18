"""P7-M6: alliance selection as a service -- candidate profiles now, and the pick list exactly as P6-M8 composed it,
behind its real gates.

**Candidate profiles** (P6-M6 factors, `ml.playoffs.selection.candidate_profile`) need no ruleset: each team on the
event's qualification roster, with its features at a moment, plus an optional three-team configuration for the
alliance-level factors.

**The pick list** (P6-M7, `SelectionEngine`) runs only when every check passes, in this order (R4; P7-D5):
1. the season's approved P6-M1 ruleset (`data.rulesets.approved_ruleset`). A stored, approved ruleset that fails its
   schema is `storage_integrity`; no ruleset table at all means no ruleset was ever approved (`not_approved`);
2. the event's rules (`for_event`);
3. the PX gates: the `passed` fields of the write-once records `p6_m2_px1.json` (PX-1, P6-Q3), `p6_m3_px2.json`
   (PX-2, P6-Q4) and `p6_m5_px4.json` (PX-4, P6-Q5), where a missing record means not passed;
4. its inputs at the selection moment:
   - every qualification match played and the moment passed;
   - final qualification ranks fetched no earlier than the last qualification match's scheduled time and the last
     qualification result payload, covering the qualification roster;
   - the pinned PX artifacts loaded (`model_not_loaded`) and the evaluated ones: each pinned sha256 must appear in
     its gate record or the PX-4 record, so a different file is never served under a passed gate;
   - the EPA source, and the event-analysis ordering and features (the P5-M4 policy; after a complete
     qualification schedule that is M5 v2, as P6-M8 forced it), with features for every ranked team;
5. the engine's support for the event's draft rules, then a draft state the serpentine order and the event's
   rules can produce (`_check_state`).

The first failing check sets the refusal. Event-level P(win event) / P(reach finals) are
`validated_playoff_success` (P6-M5 / P6-M7 vocabulary; P7-D7), with their scope stated (SCOPE_REASONS), and only
because the PX-4 record passed, never from a caller. `validated_playoff` stays reserved for P6's single playoff-match
probabilities after PX-2. No awaiting-review ruleset and no qualification model is ever used for playoffs (P6-M1,
P6-A12).

The selection pool is the qualification roster (teams in a qualification match), the rule behind
ml.playoffs.data.QUALIFICATION_SQL. scripts/phase6_playoff_track.py run_m8 used every team with features instead;
for a historical event with full rosters the two coincide, and serving uses the stricter one (docs/phase7.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from data.rankings import OBJECT_TYPE_EVENT_RANKING, read_final_ranks_for_season
from data.rulesets import EventRules, RulesetError, approved_ruleset
from database.connection import Database
from ml.features.assembler import TeamFeatures, build_team_features
from ml.features.roster import get_event_season
from ml.features.scale import ScaleLookup
from ml.playoffs.px1 import OutsidePX1Domain, alliance_match_probability, selection_moment
from ml.playoffs.selection import (
    CandidateProfile,
    DraftState,
    PickRecommendation,
    SelectionEngine,
    candidate_profile,
    next_captain,
    turn_order,
)
from ml.views.event_analysis import analyze_event

PHASE6_RESULTS = Path(__file__).resolve().parents[2] / ".agent" / "phase6" / "results"
PX_GATE_RECORDS = (("PX-1", "p6_m2_px1.json"), ("PX-2", "p6_m3_px2.json"), ("PX-4", "p6_m5_px4.json"))
VALIDATED_PLAYOFF_SUCCESS = "validated_playoff_success"  # P7-D7: the event-level PX-4 label
# The scope a validated playoff value carries (P6-M5 / P6-M7 "scope stated"; P7-D5).
SCOPE_REASONS = (
    "px4_scope: the bracket simulator's P(win event) was validated on actual alliances (P6-M5)",
    "predicted_field_not_validated: the other alliances come from the P6-Q6 draft model; P6-DM1 is not met",
)

# One event's qualification schedule: the rule of ml.playoffs.data.QUALIFICATION_SQL (scheduled qualification
# matches with a roster), plus how many of them are unplayed.
QUALIFICATION_SQL = """
SELECT max(m.scheduled_time), count(*) FILTER (WHERE m.score_red IS NULL OR m.score_blue IS NULL)
FROM matches m
WHERE m.event_key = %s AND m.competition_level = 'qualification' AND m.scheduled_time IS NOT NULL
  AND EXISTS (SELECT 1 FROM match_teams mt WHERE mt.match_key = m.match_key)
"""
QUALIFICATION_ROSTER_SQL = """
SELECT DISTINCT mt.team_number FROM match_teams mt JOIN matches m ON m.match_key = mt.match_key
WHERE m.event_key = %s AND m.competition_level = 'qualification' AND m.scheduled_time IS NOT NULL
ORDER BY mt.team_number
"""
# When the event's last qualification result was first seen: the current TBA match payloads (P7-D5).
RESULTS_FETCHED_SQL = """
SELECT max(r.fetch_timestamp) FROM raw_source_payloads r JOIN matches m ON m.match_key = r.source_object_id
WHERE r.source = 'tba' AND r.source_object_type = 'match' AND r.is_current
  AND m.event_key = %s AND m.competition_level = 'qualification'
"""
RANKING_FETCHED_SQL = """
SELECT max(fetch_timestamp) FROM raw_source_payloads
WHERE source = 'tba' AND source_object_type = %s AND source_object_id = %s AND is_current
"""


class SelectionServiceError(Exception):
    """A refusal the API serves with `code` (each new code is listed in docs/phase7.md)."""

    code = "selection_service_error"


class SelectionTimeUnavailable(SelectionServiceError):
    """No scheduled qualification match, or qualification is not finished, so no selection moment exists yet."""

    code = "selection_time_unavailable"


class PlayoffModelsNotAccepted(SelectionServiceError):
    """A PX gate has not passed (or its record does not exist), or the gate records do not identify the pinned
    artifacts as the ones they evaluated."""

    code = "playoff_models_not_accepted"


class PlayoffModelsNotLoaded(SelectionServiceError):
    """The PX gates passed, but the pinned PX-1 model and PX-2 calibrator are not loaded."""

    code = "model_not_loaded"


class RankingsUnavailable(SelectionServiceError):
    """The event's final qualification ranks are not landed, predate the end of qualification, or miss a team."""

    code = "rankings_unavailable"


class PlayoffInputsInsufficient(SelectionServiceError):
    """PX-1 lacks an input for some team, or an alliance is outside its 3-team domain: the engine never imputes."""

    code = "playoff_inputs_insufficient"


@dataclass(frozen=True)
class PickListResult:
    """The pick list with its provenance: the selection moment, the approved ruleset (sha256, variant), the
    ordering policy (the P5-M4 model), and each team's EPA source state (for the EPA envelope)."""

    recommendation: PickRecommendation
    moment: datetime
    ruleset_sha256: str
    ruleset_variant: str | None
    ordering_policy: str
    epa_states: list[str | None]


@dataclass(frozen=True)
class PlayoffModels:
    """The pinned PX-1 model and its PX-2 calibrator (api.ml_loading.load_playoff_models)."""

    px1: Any
    calibrate: Callable[[float], float]
    px1_sha256: str
    px2_sha256: str


def _qualification(database: Database, event_key: str) -> tuple[datetime | None, int]:
    """(latest scheduled qualification time, qualification matches not yet scored) for one event."""
    with database.cursor() as cursor:
        cursor.execute(QUALIFICATION_SQL, (event_key,))
        row = cursor.fetchone()
    return (row[0], int(row[1] or 0)) if row else (None, 0)


def qualification_roster(database: Database, event_key: str) -> list[int]:
    """Every team in a scheduled qualification match at the event: the selection pool."""
    with database.cursor() as cursor:
        cursor.execute(QUALIFICATION_ROSTER_SQL, (event_key,))
        return [row[0] for row in cursor.fetchall()]


def event_selection_moment(database: Database, event_key: str) -> datetime:
    """One minute after the event's latest scheduled qualification match (ml.playoffs.px1.selection_moment, the rule
    behind EventPlayoffs.selection_as_of), available before any playoff row exists (R15)."""
    latest, _ = _qualification(database, event_key)
    if latest is None:
        raise SelectionTimeUnavailable(f"{event_key} has no scheduled qualification match")
    return selection_moment(latest)


def candidate_profiles(database: Database, event_key: str, as_of: datetime, *, epa_provider: Any,
                       configuration: Sequence[int] | None = None) -> tuple[list[CandidateProfile], list[str | None]]:
    """Every qualification-roster team's P6-M6 profile at as_of, plus each team's EPA source state (for the EPA
    envelope). A configuration's three members get the alliance-level factors (synergy, role compatibility); every
    other team reports them insufficient_data, as the engine does."""
    scales = ScaleLookup(database)
    features = {t: build_team_features(database, t, event_key, as_of, epa_provider=epa_provider, scale_lookup=scales)
                for t in qualification_roster(database, event_key)}
    members = [features[t] for t in configuration] if configuration else None
    profiles = [candidate_profile(f, members if configuration and f.team_number in configuration else None)
                for _, f in sorted(features.items())]
    return profiles, [f.epa_source_state for f in features.values()]


def playoff_gate_records(results_dir: Path | None = None) -> dict[str, tuple[bool, str]]:
    """Each PX gate's (passed, record text). A missing, unreadable or non-object record is not passed, and only a
    JSON `true` passes (the string "true" does not)."""
    directory = results_dir or PHASE6_RESULTS
    out: dict[str, tuple[bool, str]] = {}
    for gate, name in PX_GATE_RECORDS:
        try:
            text = (directory / name).read_text(encoding="utf-8")
            record = json.loads(text)
        except (OSError, ValueError):
            out[gate] = (False, "")
            continue
        out[gate] = (isinstance(record, dict) and record.get("passed") is True, text)
    return out


def playoff_gates(results_dir: Path | None = None) -> dict[str, bool]:
    """Each PX gate's recorded `passed` flag."""
    return {gate: passed for gate, (passed, _) in playoff_gate_records(results_dir).items()}


def _guarded(p_match: Callable[..., float]) -> Callable[..., float]:
    """The PX-1 adapter's own refusals (an absent input; an alliance outside its 3-team domain) become typed."""
    def p(*args: Any) -> float:
        try:
            return p_match(*args)
        except OutsidePX1Domain as exc:
            raise PlayoffInputsInsufficient(str(exc)) from exc
        except ValueError as exc:
            if "PX-1 input absent" in str(exc):
                raise PlayoffInputsInsufficient(str(exc)) from exc
            raise
    return p


def _approved_rules(database: Database, season: int, event_key: str) -> EventRules:
    try:
        ruleset = approved_ruleset(database, season)
    except ValidationError as exc:
        raise RulesetError("storage_integrity", f"the approved {season} ruleset fails its schema") from exc
    except RulesetError:
        raise
    except Exception as exc:
        if type(exc).__name__ == "UndefinedTable":  # migration 0011 not applied: nothing was ever approved
            raise RulesetError("not_approved", f"no ruleset table exists, so no {season} ruleset is approved") from exc
        raise
    return ruleset.for_event(event_key)


def _check_state(state: DraftState, seed: int, ranks: dict[int, int], rules: EventRules, n_alliances: int) -> None:
    """A draft state the serpentine order and the event's rules can produce (P7-D5):
    - the event's alliance count, and ranked, distinct teams;
    - a declined team is on an alliance only as the rules allow: as a captain only when
      `declined_team_may_become_captain` is true (null is `not_established`), as a pick only when
      `declined_team_may_be_picked_later` is true;
    - each seed that has taken turns holds its captain plus one team per turn;
    - a seed whose first turn has not come holds nothing, except the acting seed, which may already hold its
      captain, and only the captain the captain rule gives (captains are named when their seed's turn comes, so
      listing later captains up front would wrongly remove them from the pick pool).
    Who the picks are is the caller's: the real draft can differ from the draft model."""
    def invalid(why: str) -> RulesetError:
        return RulesetError("invalid_state", why)

    selection = rules.selection
    if len(state.alliances) != n_alliances:
        raise invalid(f"the event has {n_alliances} alliances, not {len(state.alliances)}")
    members = [t for alliance in state.alliances for t in alliance]
    if len(members) != len(set(members)):
        raise invalid("a team is on more than one alliance slot")
    unknown = sorted((set(members) | set(state.declined)) - set(ranks))
    if unknown:
        raise invalid(f"teams not in the event's final ranks: {unknown}")
    for alliance in state.alliances:
        for position, team in enumerate(alliance):
            if team not in state.declined:
                continue
            if position == 0 and selection.declined_team_may_become_captain is None:
                raise RulesetError("not_established", f"declined team {team} is a captain, and whether a declined "
                                                      "team may become captain is not established (P6-M1)")
            if (position == 0 and not selection.declined_team_may_become_captain) or (
                    position > 0 and not selection.declined_team_may_be_picked_later):
                raise invalid(f"declined team {team} is on an alliance, which the event's rules do not allow")
    order = turn_order(n_alliances, selection.picks_per_alliance)
    if state.turns_taken > len(order):
        raise invalid(f"turns_taken {state.turns_taken} exceeds the draft's {len(order)} turns")
    acting = order[state.turns_taken] if state.turns_taken < len(order) else None
    for s in range(1, n_alliances + 1):
        turns = order[:state.turns_taken].count(s)
        size = len(state.alliances[s - 1])
        if turns and size != turns + 1:
            raise invalid(f"seed {s} holds {size} team(s) after {turns} of its turns")
        if not turns and size > (1 if s == acting else 0):
            raise invalid(f"seed {s} holds {size} team(s) before its first turn; a captain is named only when its "
                          "seed's turn comes")
    if acting is not None and acting == seed and len(state.alliances[seed - 1]) == 1 and not order[
            :state.turns_taken].count(seed):
        alliances = list(state.alliances)
        alliances[seed - 1] = ()
        expected = next_captain(DraftState(tuple(alliances), state.declined, state.turns_taken), ranks, rules)
        if state.alliances[seed - 1][0] != expected:
            raise invalid(f"seed {seed}'s captain is {expected} under the captain rule, not "
                          f"{state.alliances[seed - 1][0]}")


def pick_list(database: Database, event_key: str, seed: int, state: DraftState, now: datetime, *,
              epa_provider: Callable[[], Any], m5v2_predict_rating: Callable[[TeamFeatures], float] | None,
              playoff_models: PlayoffModels | None, results_dir: Path | None = None,
              ) -> PickListResult:
    """The P6-M7 pick list for `seed`'s next turn from `state`, at the event's selection moment. Raises RulesetError
    (steps 1, 2, 5), SelectionServiceError (3, 4), M5V2Required and SilentFallbackError (4) in the order above.
    `epa_provider` is called only at step 4, so an unloaded EPA source is reported in its place in the order."""
    season = get_event_season(database, event_key)
    if season is None:
        raise RulesetError("wrong_season", f"{event_key} has no season")
    rules = _approved_rules(database, season, event_key)
    records = playoff_gate_records(results_dir)
    failed = [gate for gate, (passed, _) in records.items() if not passed]
    if failed:
        raise PlayoffModelsNotAccepted(f"PX gates not passed: {', '.join(failed)}")
    latest, unplayed = _qualification(database, event_key)
    if latest is None:
        raise SelectionTimeUnavailable(f"{event_key} has no scheduled qualification match")
    moment = selection_moment(latest)
    if moment > now or unplayed:
        raise SelectionTimeUnavailable(f"{event_key}'s qualification is not finished ({unplayed} match(es) unscored; "
                                       f"selection at {moment})")
    ranks = read_final_ranks_for_season(database, season).get(event_key)
    with database.cursor() as cursor:
        cursor.execute(RANKING_FETCHED_SQL, (OBJECT_TYPE_EVENT_RANKING, event_key))
        fetched = cursor.fetchone()[0]
        cursor.execute(RESULTS_FETCHED_SQL, (event_key,))
        results_seen = cursor.fetchone()[0]
    roster = qualification_roster(database, event_key)
    if (not ranks or fetched is None or fetched < latest or (results_seen is not None and fetched < results_seen)
            or set(roster) - set(ranks)):
        raise RankingsUnavailable(f"{event_key} has no final qualification ranks fetched after its last "
                                  "qualification match was scheduled and its last result was seen, covering its "
                                  "qualification roster")
    if playoff_models is None:
        raise PlayoffModelsNotLoaded("the PX-1 model and PX-2 calibrator are not pinned/loadable")
    if (playoff_models.px1_sha256 not in records["PX-1"][1] + records["PX-4"][1]
            or playoff_models.px2_sha256 not in records["PX-2"][1] + records["PX-4"][1]):
        raise PlayoffModelsNotAccepted("the PX gate records do not identify the pinned PX-1 model and PX-2 "
                                       "calibrator as the artifacts they evaluated")
    analysis = analyze_event(database, event_key, moment, epa_provider=epa_provider(),
                             m5v2_predict_rating=m5v2_predict_rating)
    features = {f.team_number: f for f in analysis.features}
    missing = sorted(set(ranks) - set(features))
    if missing:
        raise PlayoffInputsInsufficient(f"ranked teams without features at the selection moment: {missing}")
    ordering = [o.team_number for o in analysis.ordering]
    p_match = _guarded(alliance_match_probability(playoff_models.px1, features, playoff_models.calibrate))
    engine = SelectionEngine(rules, ranks, ordering, p_match, probability_status=VALIDATED_PLAYOFF_SUCCESS,
                             features=features)
    _check_state(state, seed, ranks, rules, engine.n_alliances)
    return PickListResult(engine.recommend(state, seed), moment, rules.season_ruleset.sha256(), rules.variant,
                          analysis.model, [f.epa_source_state for f in analysis.features])


__all__ = [
    "PX_GATE_RECORDS", "PickListResult", "PlayoffInputsInsufficient", "PlayoffModels", "PlayoffModelsNotAccepted",
    "PlayoffModelsNotLoaded", "RankingsUnavailable", "SCOPE_REASONS", "SelectionServiceError",
    "SelectionTimeUnavailable", "VALIDATED_PLAYOFF_SUCCESS", "candidate_profiles", "event_selection_moment",
    "pick_list", "playoff_gate_records", "playoff_gates", "qualification_roster",
]
