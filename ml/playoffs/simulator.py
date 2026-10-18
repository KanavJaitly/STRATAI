"""PX-3 (P6-M4): the exact bracket and series simulator.

Given a P6-M1 bracket format, the alliances by seed and a match-probability function, the simulator computes each
alliance's probability of every bracket outcome:
- winning the event;
- reaching the finals;
- the slot in which it is eliminated.

**Exact, not sampled.** Every outcome path through the bracket graph is enumerated. A slot has two outcomes, so an
8-alliance double elimination has 2^13 = 8,192 paths, and the finals series is computed in closed form. The result
is deterministic.

**Two exact implementations:**
- `simulate` (production): which seeds meet in each slot depends only on the outcome bits of earlier slots, so the
  path table is built once per bracket (`bracket_plan`). Any probability function is then evaluated in one vectorized
  pass.
- `simulate_recursive` walks the same paths one by one. Tests require the two to agree.

`monte_carlo` is an independent, seeded sampler used **only** as a test oracle.

**Assumptions:**
- Matches are independent given the probability function. The probability function may depend on the round, so
  PX-1's bracket-round input is honoured.
- Every finals match uses the same per-match probability.
- A structure the ruleset cannot express is refused by the ruleset's own validation, never approximated here.
- Backup robots are not modelled (backups are unknown in the data, P5-M1).

**Validation status:** the simulator adds no claim of its own. Its probabilities carry the status of the probability
function (PX-1/PX-2), and predictive validity is P6-M5's job.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from math import comb

import numpy as np

from data.rulesets import BracketFormat, SlotSource

# p(red_seed, blue_seed, round) -> P(red wins one match)
MatchProbability = Callable[[int, int, int], float]


def series_probability(p: float, wins_needed: int) -> float:
    """P(the side with per-match probability p wins a race to `wins_needed` wins)."""
    q = 1.0 - p
    return sum(comb(wins_needed - 1 + k, k) * p ** wins_needed * q ** k for k in range(wins_needed))


@dataclass
class BracketProbabilities:
    win_event: dict[int, float] = field(default_factory=dict)
    reach_finals: dict[int, float] = field(default_factory=dict)
    eliminated_in: dict[int, dict[str, float]] = field(default_factory=dict)
    paths: int = 0

    def total(self) -> float:
        return sum(self.win_event.values())


def _resolve(source: SlotSource, winners: Mapping[str, int], losers: Mapping[str, int]) -> int:
    if source.kind == "seed":
        return source.seed
    return winners[source.slot] if source.kind == "winner" else losers[source.slot]


def _elimination_slots(bracket: BracketFormat) -> dict[str, bool]:
    """Whether a slot's loser is eliminated (True) or routed onward (False)."""
    routed = {s.slot for b in bracket.slots for s in (b.red, b.blue) if s.kind == "loser"}
    routed |= {s.slot for s in (bracket.finals.red, bracket.finals.blue) if s.kind == "loser"}
    return {slot.slot: slot.slot not in routed for slot in bracket.slots}


def simulate_recursive(bracket: BracketFormat, p: MatchProbability) -> BracketProbabilities:
    """Exact probabilities over every outcome path, walked one path at a time (the test reference)."""
    seeds = range(1, bracket.alliances + 1)
    result = BracketProbabilities({s: 0.0 for s in seeds}, {s: 0.0 for s in seeds}, {s: {} for s in seeds})
    eliminates = _elimination_slots(bracket)
    slots = bracket.slots

    def walk(index: int, weight: float, winners: dict[str, int], losers: dict[str, int]) -> None:
        if weight == 0.0:
            return
        if index == len(slots):
            finals = bracket.finals
            red, blue = _resolve(finals.red, winners, losers), _resolve(finals.blue, winners, losers)
            p_red = series_probability(p(red, blue, finals.round), finals.wins_needed)
            for seed in (red, blue):
                result.reach_finals[seed] += weight
            result.win_event[red] += weight * p_red
            result.win_event[blue] += weight * (1.0 - p_red)
            for seed, share in ((red, 1.0 - p_red), (blue, p_red)):
                result.eliminated_in[seed]["finals"] = result.eliminated_in[seed].get("finals", 0.0) + weight * share
            result.paths += 2
            return
        slot = slots[index]
        red, blue = _resolve(slot.red, winners, losers), _resolve(slot.blue, winners, losers)
        p_red = p(red, blue, slot.round)
        if not 0.0 <= p_red <= 1.0:
            raise ValueError(f"match probability {p_red} for seeds {red} v {blue} is not a probability")
        for winner, loser, share in ((red, blue, p_red), (blue, red, 1.0 - p_red)):
            if eliminates[slot.slot]:
                bucket = result.eliminated_in[loser]
                bucket[slot.slot] = bucket.get(slot.slot, 0.0) + weight * share
            walk(index + 1, weight * share, {**winners, slot.slot: winner}, {**losers, slot.slot: loser})

    walk(0, 1.0, {}, {})
    return result


def monte_carlo(bracket: BracketFormat, p: MatchProbability, *, trials: int, seed: int) -> BracketProbabilities:
    """A seeded sampler of the same bracket: an independent oracle for tests only."""
    rng = random.Random(seed)
    seeds = range(1, bracket.alliances + 1)
    wins = {s: 0 for s in seeds}
    finals = {s: 0 for s in seeds}
    for _ in range(trials):
        winners: dict[str, int] = {}
        losers: dict[str, int] = {}
        for slot in bracket.slots:
            red, blue = _resolve(slot.red, winners, losers), _resolve(slot.blue, winners, losers)
            red_wins = rng.random() < p(red, blue, slot.round)
            winners[slot.slot], losers[slot.slot] = (red, blue) if red_wins else (blue, red)
        f = bracket.finals
        red, blue = _resolve(f.red, winners, losers), _resolve(f.blue, winners, losers)
        finals[red] += 1
        finals[blue] += 1
        red_count = blue_count = 0
        while red_count < f.wins_needed and blue_count < f.wins_needed:
            if rng.random() < p(red, blue, f.round):
                red_count += 1
            else:
                blue_count += 1
        wins[red if red_count == f.wins_needed else blue] += 1
    return BracketProbabilities({s: wins[s] / trials for s in seeds}, {s: finals[s] / trials for s in seeds},
                                {s: {} for s in seeds}, trials)


MAX_SLOTS = 20


@dataclass(frozen=True)
class BracketPlan:
    """Every outcome path of one bracket: who meets in each slot, and who is eliminated where."""

    red: np.ndarray  # (paths, slots) red seed per slot
    blue: np.ndarray
    red_won: np.ndarray  # (paths, slots) bool
    rounds: tuple[int, ...]  # per slot
    finals_red: np.ndarray  # (paths,)
    finals_blue: np.ndarray
    eliminated: np.ndarray  # (paths, slots) seed eliminated at the slot, 0 if the loser is routed onward
    slot_names: tuple[str, ...]
    finals_round: int
    wins_needed: int
    alliances: int


@lru_cache(maxsize=64)
def _plan_cached(bracket_json: str) -> BracketPlan:
    bracket = BracketFormat.model_validate_json(bracket_json)
    slots = bracket.slots
    if len(slots) > MAX_SLOTS:
        raise ValueError(f"{len(slots)} slots exceed the exact simulator's {MAX_SLOTS}-slot limit")
    eliminates = _elimination_slots(bracket)
    n_paths = 2 ** len(slots)
    red = np.zeros((n_paths, len(slots)), dtype=np.int64)
    blue = np.zeros_like(red)
    red_won = np.zeros((n_paths, len(slots)), dtype=bool)
    eliminated = np.zeros_like(red)
    finals_red = np.zeros(n_paths, dtype=np.int64)
    finals_blue = np.zeros_like(finals_red)
    for path in range(n_paths):
        winners: dict[str, int] = {}
        losers: dict[str, int] = {}
        for i, slot in enumerate(slots):
            r, b = _resolve(slot.red, winners, losers), _resolve(slot.blue, winners, losers)
            won = bool((path >> i) & 1)
            red[path, i], blue[path, i], red_won[path, i] = r, b, won
            winners[slot.slot], losers[slot.slot] = (r, b) if won else (b, r)
            if eliminates[slot.slot]:
                eliminated[path, i] = losers[slot.slot]
        finals_red[path] = _resolve(bracket.finals.red, winners, losers)
        finals_blue[path] = _resolve(bracket.finals.blue, winners, losers)
    return BracketPlan(red, blue, red_won, tuple(s.round for s in slots), finals_red, finals_blue, eliminated,
                       tuple(s.slot for s in slots), bracket.finals.round, bracket.finals.wins_needed,
                       bracket.alliances)


def bracket_plan(bracket: BracketFormat) -> BracketPlan:
    return _plan_cached(bracket.model_dump_json())


def simulate(bracket: BracketFormat, p: MatchProbability) -> BracketProbabilities:
    """Exact probabilities over every outcome path, in one vectorized pass. Seeds are 1 … bracket.alliances."""
    plan = bracket_plan(bracket)
    n = plan.alliances
    rounds = sorted(set(plan.rounds) | {plan.finals_round})
    table = np.zeros((max(rounds) + 1, n + 1, n + 1))
    for k in rounds:
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                if i != j:
                    value = p(i, j, k)
                    if not 0.0 <= value <= 1.0:
                        raise ValueError(f"match probability {value} for seeds {i} v {j} is not a probability")
                    table[k, i, j] = value
    slot_rounds = np.array(plan.rounds)
    probs = table[slot_rounds[None, :], plan.red, plan.blue]
    factors = np.where(plan.red_won, probs, 1.0 - probs)
    weights = np.prod(factors, axis=1)
    p_match = table[plan.finals_round, plan.finals_red, plan.finals_blue]
    q = 1.0 - p_match
    p_series = sum(comb(plan.wins_needed - 1 + k, k) * p_match ** plan.wins_needed * q ** k
                   for k in range(plan.wins_needed))
    size = n + 1
    win = (np.bincount(plan.finals_red, weights * p_series, size) + np.bincount(plan.finals_blue, weights * (1 - p_series), size))
    finals = np.bincount(plan.finals_red, weights, size) + np.bincount(plan.finals_blue, weights, size)
    result = BracketProbabilities({s: float(win[s]) for s in range(1, size)}, {s: float(finals[s]) for s in range(1, size)},
                                  {s: {} for s in range(1, size)}, 2 * len(weights))
    for i, name in enumerate(plan.slot_names):
        totals = np.bincount(plan.eliminated[:, i], weights, size)  # the path weight already fixes the outcome
        for seed in range(1, size):
            if totals[seed] > 0:
                result.eliminated_in[seed][name] = float(totals[seed])
    finals_loss_red = np.bincount(plan.finals_red, weights * (1 - p_series), size)
    finals_loss_blue = np.bincount(plan.finals_blue, weights * p_series, size)
    for seed in range(1, size):
        loss = float(finals_loss_red[seed] + finals_loss_blue[seed])
        if loss > 0:
            result.eliminated_in[seed]["finals"] = loss
    return result
