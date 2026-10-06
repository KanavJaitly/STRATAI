"""P6-M6 (candidate profiles and the draft model) and P6-M7 (the alliance selection engine).

**Objective (P6-A2, P6-Q7):** maximize P(the alliance wins the event's playoffs).
- That probability is computed by the PX-3 simulator from PX-1/PX-2 match probabilities over the predicted field.
- It never optimizes raw scoring, raw EPA or a weighted factor score.
- The six roadmap factors (synergy, defense, feeding, reliability, consistency, role compatibility) and scoring
  ability are reported in each candidate's **profile**, with values, n and validation status. They affect the
  objective only through PX-1's pre-registered features (P6-A3). Nothing is imputed (P6-Q11, P6-Q12).

**Draft model (P6-Q6):** deterministic.
- **Captains:** assigned when their seed's first turn comes, as the highest-ranked available team. A team picked
  earlier was never a captain.
- **Picks:** every other captain picks the best available team by the validated P5-M4 ordering.
- **Decline rules and picks per alliance** come from the event's rules in the approved P6-M1 ruleset (`for_event`:
  an explicit variant, else the season default). A rule the model cannot represent is refused,
  never approximated.
- **Accuracy:** measured and reported, not gating.

**Engine (P6-M7):**
- For the advised captain's pick, every available candidate is tried. The rest of the draft follows the draft model,
  except that the advised alliance's own later picks are themselves optimized by exhaustive search.
- The resulting field goes through the exact simulator. Candidates are ranked by P(win event), with deterministic
  tie-breaking: higher P(reach finals), then a better ordering position, then team number.
- **Reasoning** is structured attribution: each candidate's predicted alliance, P(win event), P(reach finals), its
  difference from the next candidate, and its factor profile. There is no free text.
- **Alternatives (P6-A7):** up to 5 distinct feasible alliance configurations besides the recommended one. Fewer than
  3 is stated with the reason, and the list is never padded.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from data.rulesets import BracketFormat, EventRules, RulesetError, SelectionRules
from ml.features.assembler import TeamFeatures
from ml.playoffs.simulator import simulate
from ml.synergy.score import alliance_synergy

# p(red alliance teams, blue alliance teams, red seed, blue seed, round) -> P(red wins one match)
AllianceMatchProbability = Callable[[tuple[int, ...], tuple[int, ...], int, int, int], float]
MAX_ALTERNATIVES = 5

DESCRIPTIVE, NOT_VALIDATED, INSUFFICIENT = "descriptive", "not_validated", "insufficient_data"
DEFENSE_PENDING = "descriptive_definition_pending"


# --- P6-M6: candidate profiles ------------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorValue:
    value: float | None
    n: int | None
    validation_status: str
    reason: str | None = None


@dataclass(frozen=True)
class CandidateProfile:
    team_number: int
    scoring_epa: FactorValue
    average_score: FactorValue
    reliability: FactorValue
    consistency: FactorValue
    defense: FactorValue
    feeding: FactorValue
    synergy: FactorValue
    role_compatibility: FactorValue


def _measured(value: float | None, n: int | None, status: str = DESCRIPTIVE) -> FactorValue:
    return FactorValue(value, n, status) if value is not None else FactorValue(None, n, INSUFFICIENT, "absent")


def candidate_profile(candidate: TeamFeatures, configuration: Sequence[TeamFeatures] | None = None) -> CandidateProfile:
    """The candidate's factors, each straight from its Phase 3/4 source with n and status.

    `configuration` is the predicted three-team alliance including the candidate. Synergy and role compatibility
    (Phase 4 M9, as built: P6-A10) are alliance-level, and are reported only for a complete alliance."""
    if candidate.defense_score is None:
        defense = FactorValue(None, candidate.defense_observation_count, INSUFFICIENT, "no scouting observations")
    else:  # P6-Q11: quality only, while the definition stays descriptive
        defense = FactorValue(candidate.defense_score, candidate.defense_observation_count, DEFENSE_PENDING)
    if candidate.feeding_score is None:
        feeding = FactorValue(None, candidate.feeding_observation_count, INSUFFICIENT, "no scouting observations")
    else:
        feeding = FactorValue(candidate.feeding_score, candidate.feeding_observation_count, NOT_VALIDATED,
                              "feeding is not validated (Phase 3 M14)")
    if configuration is not None and len(configuration) == 3:
        score = alliance_synergy(*configuration)
        synergy = FactorValue(score.overall_score, 3, "not_validated_against_outcomes",
                              None if score.overall_score is not None else "no comparable axes")
        role = FactorValue(score.role_fit_term, 3, "not_validated_against_outcomes",
                           None if score.role_fit_term is not None else "no comparable axes")
    else:
        synergy = role = FactorValue(None, None, INSUFFICIENT, "alliance incomplete")
    return CandidateProfile(
        candidate.team_number,
        scoring_epa=_measured(candidate.epa_total, None),
        average_score=_measured(candidate.average_score, candidate.matches_used),
        reliability=_measured(candidate.reliability_score, candidate.matches_used),
        consistency=_measured(candidate.consistency_rating, candidate.matches_used),
        defense=defense, feeding=feeding, synergy=synergy, role_compatibility=role)


# --- P6-M6: the deterministic draft model ---------------------------------------------------------------------


@dataclass(frozen=True)
class DraftState:
    """A draft in progress: alliances by seed (captain first), declines so far, and how many turns are taken."""

    alliances: tuple[tuple[int, ...], ...]
    declined: frozenset[int] = frozenset()
    turns_taken: int = 0

    @classmethod
    def empty(cls, n_alliances: int) -> DraftState:
        return cls(tuple(() for _ in range(n_alliances)))

    def on_alliance(self) -> set[int]:
        return {t for a in self.alliances for t in a}


def turn_order(n_alliances: int, picks_per_alliance: int) -> list[int]:
    """Serpentine: round 1 is seeds 1 … n, round 2 is n … 1, and so on (1-based seeds)."""
    order: list[int] = []
    for r in range(picks_per_alliance):
        seeds = list(range(1, n_alliances + 1))
        order.extend(seeds if r % 2 == 0 else list(reversed(seeds)))
    return order


def _selection(rules: EventRules) -> SelectionRules:
    """The selection rules of ONE event (P6-M1 schema v2). A bare season ruleset is refused: its default would be
    silently applied to events that a variant governs (e.g. FIRST Championship divisions)."""
    if not isinstance(rules, EventRules):
        raise RulesetError("event_rules_required", "selection consumers take one event's rules: "
                                                   "SeasonRuleset.for_event(event_key)")
    return rules.selection


def _check_supported(rules: EventRules) -> None:
    if _selection(rules).order != "serpentine" or _selection(rules).captain_rule != "highest_ranked_available":
        raise RulesetError("not_supported", "the draft model represents serpentine, highest-ranked-available drafts only")
    if not _selection(rules).captain_may_accept_higher_alliance:
        raise RulesetError("not_supported", "a ruleset forbidding captains from joining higher alliances is not "
                                            "represented by the draft model")


def available_for_pick(state: DraftState, teams: Sequence[int], rules: EventRules) -> list[int]:
    taken = state.on_alliance()
    blocked = set() if _selection(rules).declined_team_may_be_picked_later else set(state.declined)
    return [t for t in teams if t not in taken and t not in blocked]


def _captain(state: DraftState, ranks: Mapping[int, int], rules: EventRules) -> int:
    taken = state.on_alliance()
    blocked = set() if _selection(rules).declined_team_may_become_captain else set(state.declined)
    eligible = [t for t in ranks if t not in taken and t not in blocked]
    if not eligible:
        raise RulesetError("infeasible", "no team is eligible to be a captain")
    return min(eligible, key=lambda t: (ranks[t], t))


Chooser = Callable[[DraftState, int, list[int]], int]


def run_draft(state: DraftState, rules: EventRules, ranks: Mapping[int, int], chooser: Chooser) -> DraftState:
    """Complete the draft from `state`. `chooser(state, seed, available)` returns the team the acting captain picks."""
    _check_supported(rules)
    n = len(state.alliances)
    order = turn_order(n, _selection(rules).picks_per_alliance)
    teams = sorted(ranks, key=lambda t: (ranks[t], t))
    alliances = [list(a) for a in state.alliances]
    current = state
    for turn in range(state.turns_taken, len(order)):
        seed = order[turn]
        if not alliances[seed - 1]:
            alliances[seed - 1].append(_captain(current, ranks, rules))
            current = DraftState(tuple(tuple(a) for a in alliances), current.declined, turn)
        options = available_for_pick(current, teams, rules)
        if not options:
            raise RulesetError("infeasible", f"no team is available for seed {seed}'s pick")
        choice = chooser(current, seed, options)
        if choice not in options:
            raise RulesetError("infeasible", f"team {choice} is not available")
        alliances[seed - 1].append(choice)
        current = DraftState(tuple(tuple(a) for a in alliances), current.declined, turn + 1)
    return current


def best_available(ordering: Sequence[int]) -> Chooser:
    """The draft model's choice for every other captain: the first available team in the validated ordering."""
    position = {t: i for i, t in enumerate(ordering)}

    def choose(state: DraftState, seed: int, options: list[int]) -> int:
        return min(options, key=lambda t: (position.get(t, len(position)), t))
    return choose


def pick_prediction_accuracy(actual: Sequence[tuple[DraftState, int, int]], ordering: Sequence[int],
                             rules: EventRules, teams: Sequence[int]) -> dict[str, Any]:
    """P6-M6 (b): for each actual pick (state before it, seed, team picked), whether the draft model's choice
    matches (top-1), or the pick is among its top 3 available. Measured, not gating (P6-Q6)."""
    position = {t: i for i, t in enumerate(ordering)}
    top1 = top3 = 0
    for state, seed, picked in actual:
        options = sorted(available_for_pick(state, teams, rules), key=lambda t: (position.get(t, len(position)), t))
        top1 += bool(options) and options[0] == picked
        top3 += picked in options[:3]
    n = len(actual)
    return {"picks": n, "top1": top1, "top3": top3, "top1_rate": top1 / n if n else None,
            "top3_rate": top3 / n if n else None}


# --- P6-M7: the alliance selection engine --------------------------------------------------------------------


@dataclass(frozen=True)
class FieldOutcome:
    alliances: tuple[tuple[int, ...], ...]
    p_win_event: float
    p_reach_finals: float


@dataclass(frozen=True)
class RankedPick:
    team_number: int
    configuration: tuple[int, ...]
    p_win_event: float
    p_reach_finals: float
    margin_over_next: float | None
    profile: CandidateProfile | None = None


@dataclass(frozen=True)
class PickRecommendation:
    seed: int
    ranked: tuple[RankedPick, ...]
    alternatives: tuple[FieldOutcome, ...]
    alternatives_note: str | None
    probability_status: str
    evaluated_fields: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


def field_outcome(alliances: tuple[tuple[int, ...], ...], bracket: BracketFormat, p_match: AllianceMatchProbability,
                  seed: int) -> FieldOutcome:
    def p(red: int, blue: int, round_: int) -> float:
        return p_match(alliances[red - 1], alliances[blue - 1], red, blue, round_)
    result = simulate(bracket, p)
    return FieldOutcome(alliances, result.win_event[seed], result.reach_finals[seed])


class SelectionEngine:
    def __init__(self, rules: EventRules, ranks: Mapping[int, int], ordering: Sequence[int],
                 p_match: AllianceMatchProbability, *, probability_status: str,
                 features: Mapping[int, TeamFeatures] | None = None) -> None:
        _check_supported(rules)
        self.rules = rules
        self.ranks = dict(ranks)
        self.ordering = list(ordering)
        self.position = {t: i for i, t in enumerate(self.ordering)}
        self.p_match = p_match
        self.probability_status = probability_status
        self.features = dict(features or {})
        self.n_alliances = rules.alliances_for(len(self.ranks))
        self.bracket = rules.bracket(self.n_alliances)
        self.others = best_available(self.ordering)
        self.fields_evaluated = 0

    def _outcome(self, state: DraftState, seed: int) -> FieldOutcome:
        self.fields_evaluated += 1
        return field_outcome(state.alliances, self.bracket, self.p_match, seed)

    def _finish(self, state: DraftState, seed: int) -> tuple[FieldOutcome, DraftState]:
        """Complete the draft from `state`, optimizing `seed`'s own remaining picks by exhaustive search; every
        other captain follows the draft model."""
        order = turn_order(self.n_alliances, _selection(self.rules).picks_per_alliance)
        upcoming = [t for t in range(state.turns_taken, len(order)) if order[t] == seed]
        if not upcoming:
            done = run_draft(state, self.rules, self.ranks, self.others)
            return self._outcome(done, seed), done
        stop = upcoming[0]
        before = run_draft_until(state, self.rules, self.ranks, self.others, stop)
        if not before.alliances[seed - 1]:
            before = _assign_captain(before, seed, self.ranks, self.rules)
        best: tuple[FieldOutcome, DraftState] | None = None
        for option in self._options(before):
            after = _apply_pick(before, seed, option)
            outcome, final = self._finish(after, seed)
            key = (outcome.p_win_event, outcome.p_reach_finals)
            if best is None or key > (best[0].p_win_event, best[0].p_reach_finals):
                best = (outcome, final)
        assert best is not None
        return best

    def _options(self, state: DraftState) -> list[int]:
        teams = sorted(self.ranks, key=lambda t: (self.ranks[t], t))
        return sorted(available_for_pick(state, teams, self.rules), key=lambda t: (self.position.get(t, 10 ** 9), t))

    def recommend(self, state: DraftState, seed: int) -> PickRecommendation:
        """Rank every available pick for `seed`'s next turn by P(the alliance wins the event)."""
        order = turn_order(self.n_alliances, _selection(self.rules).picks_per_alliance)
        if state.turns_taken >= len(order) or order[state.turns_taken] != seed:
            raise RulesetError("invalid_state", f"it is not seed {seed}'s turn")
        if not state.alliances[seed - 1]:
            state = _assign_captain(state, seed, self.ranks, self.rules)
        self.fields_evaluated = 0
        evaluated = []
        for candidate in self._options(state):
            outcome, final = self._finish(_apply_pick(state, seed, candidate), seed)
            evaluated.append((candidate, outcome))
        evaluated.sort(key=lambda co: (-co[1].p_win_event, -co[1].p_reach_finals,
                                       self.position.get(co[0], 10 ** 9), co[0]))
        ranked = []
        for i, (candidate, outcome) in enumerate(evaluated):
            nxt = evaluated[i + 1][1].p_win_event if i + 1 < len(evaluated) else None
            configuration = outcome.alliances[seed - 1]
            profile = None
            if candidate in self.features:
                members = [self.features[t] for t in configuration if t in self.features]
                profile = candidate_profile(self.features[candidate], members if len(members) == 3 else None)
            ranked.append(RankedPick(candidate, configuration, outcome.p_win_event, outcome.p_reach_finals,
                                     None if nxt is None else outcome.p_win_event - nxt, profile))
        configurations: dict[tuple[int, ...], FieldOutcome] = {}
        for _, outcome in evaluated:
            key = tuple(sorted(outcome.alliances[seed - 1]))
            if key not in configurations:
                configurations[key] = outcome
        distinct = list(configurations.values())
        alternatives = tuple(distinct[1:1 + MAX_ALTERNATIVES])
        note = None if len(alternatives) >= 3 else (
            f"only {len(alternatives)} distinct feasible alternative configuration(s) exist from this draft state")
        notes = ("objective: P(the alliance wins the event), from the exact bracket simulator over the predicted field",
                 "other captains follow the deterministic best-available draft model (P6-Q6)")
        return PickRecommendation(seed, tuple(ranked), alternatives, note, self.probability_status,
                                  self.fields_evaluated, notes)


def _assign_captain(state: DraftState, seed: int, ranks: Mapping[int, int], rules: EventRules) -> DraftState:
    alliances = [list(a) for a in state.alliances]
    alliances[seed - 1].append(_captain(state, ranks, rules))
    return DraftState(tuple(tuple(a) for a in alliances), state.declined, state.turns_taken)


def _apply_pick(state: DraftState, seed: int, team: int) -> DraftState:
    alliances = [list(a) for a in state.alliances]
    alliances[seed - 1].append(team)
    return DraftState(tuple(tuple(a) for a in alliances), state.declined, state.turns_taken + 1)


def run_draft_until(state: DraftState, rules: EventRules, ranks: Mapping[int, int], chooser: Chooser,
                    stop_turn: int) -> DraftState:
    """Advance the draft with `chooser` up to (not including) turn index `stop_turn`."""
    n = len(state.alliances)
    order = turn_order(n, _selection(rules).picks_per_alliance)
    teams = sorted(ranks, key=lambda t: (ranks[t], t))
    current = state
    for turn in range(state.turns_taken, stop_turn):
        seed = order[turn]
        if not current.alliances[seed - 1]:
            current = _assign_captain(current, seed, ranks, rules)
        options = available_for_pick(current, teams, rules)
        if not options:
            raise RulesetError("infeasible", f"no team is available for seed {seed}'s pick")
        current = _apply_pick(current, seed, chooser(current, seed, options))
    return current
