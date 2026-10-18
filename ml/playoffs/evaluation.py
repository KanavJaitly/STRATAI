"""Pure evaluation functions for the playoff track and P6-DM1 (P6-M1 a, PX-1, PX-4, P6-M8).

None of these reads data or hard-codes a bracket: rulesets come from P6-M1, outcomes from TBA via P5-M1, and
probabilities from PX-1/PX-2.
- `reproduce_bracket`: P6-M1 (a). Does an approved ruleset's bracket graph reproduce an event's real playoff
  structure? It also returns the event's real winner and finalist seeds.
- `paired_log_loss_gate`: the P6-Q3 / P6-Q5 test. Strictly better log-loss, with the event-bootstrap 95% CI of the
  paired difference entirely below 0.
- `identifies` / `dm1_result`: the frozen P6-Q1 definition of P6-DM1.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from data.rulesets import BracketFormat, SlotSource
from ml.backtest.bootstrap import event_bootstrap_mean_ci
from ml.backtest.metrics import log_loss


@dataclass(frozen=True)
class PlayoffMatch:
    match_key: str
    competition_level: str
    set_number: int
    match_number: int
    red_seed: int | None
    blue_seed: int | None
    winner: str | None  # "red" / "blue" / None (tie or unplayed)


@dataclass(frozen=True)
class Reproduction:
    problems: tuple[str, ...]
    winner_seed: int | None
    finalist_seed: int | None

    @property
    def reproduced(self) -> bool:
        return not self.problems


def _resolve(source: SlotSource, winners: Mapping[str, int], losers: Mapping[str, int]) -> int | None:
    if source.kind == "seed":
        return source.seed
    return (winners if source.kind == "winner" else losers).get(source.slot)


def reproduce_bracket(bracket: BracketFormat, matches: Sequence[PlayoffMatch]) -> Reproduction:
    """Walk the ruleset's graph with the event's real results; every structural disagreement is a problem."""
    problems: list[str] = []
    by_key: dict[tuple[str, int], list[PlayoffMatch]] = defaultdict(list)
    for m in matches:
        by_key[(m.competition_level, m.set_number)].append(m)
    slots = bracket.slot_by_tba()
    finals_key = (bracket.finals.competition_level, bracket.finals.set_number)
    unknown = sorted(set(by_key) - set(slots) - {finals_key})
    problems.extend(f"match {k} has no slot in the ruleset" for k in unknown)
    winners: dict[str, int] = {}
    losers: dict[str, int] = {}
    for slot in bracket.slots:
        played = sorted(by_key.get((slot.competition_level, slot.set_number), []), key=lambda m: m.match_number)
        expected = {_resolve(slot.red, winners, losers), _resolve(slot.blue, winners, losers)}
        if not played:
            problems.append(f"slot {slot.slot} was not played")
            continue
        decided = [m for m in played if m.winner in ("red", "blue")]
        for m in played:
            if {m.red_seed, m.blue_seed} != expected:
                problems.append(f"slot {slot.slot}: seeds {sorted(s or 0 for s in (m.red_seed, m.blue_seed))} "
                                f"!= expected {sorted(s or 0 for s in expected)}")
        if not decided:
            problems.append(f"slot {slot.slot} has no decided match")
            continue
        last = decided[-1]
        win, lose = (last.red_seed, last.blue_seed) if last.winner == "red" else (last.blue_seed, last.red_seed)
        winners[slot.slot], losers[slot.slot] = win, lose
    finals = sorted(by_key.get(finals_key, []), key=lambda m: m.match_number)
    expected = {_resolve(bracket.finals.red, winners, losers), _resolve(bracket.finals.blue, winners, losers)}
    wins: dict[int, int] = defaultdict(int)
    for m in finals:
        if {m.red_seed, m.blue_seed} != expected:
            problems.append(f"finals: seeds {sorted(s or 0 for s in (m.red_seed, m.blue_seed))} != expected "
                            f"{sorted(s or 0 for s in expected)}")
        if m.winner in ("red", "blue"):
            wins[m.red_seed if m.winner == "red" else m.blue_seed] += 1
    champion = [s for s, w in wins.items() if w >= bracket.finals.wins_needed]
    if len(champion) != 1:
        problems.append(f"finals: no alliance reached {bracket.finals.wins_needed} wins")
        return Reproduction(tuple(problems), None, None)
    finalist = next(iter(expected - {champion[0]}), None)
    return Reproduction(tuple(problems), champion[0], finalist)


def paired_log_loss_gate(candidate: Sequence[float], baseline: Sequence[float], labels: Sequence[bool],
                         events: Sequence[str], *, seed: int) -> dict[str, object]:
    """Candidate minus baseline log-loss per unit, event-bootstrapped. Passes iff the whole CI is below 0."""
    if not (len(candidate) == len(baseline) == len(labels) == len(events)):
        raise ValueError("inputs differ in length")
    by_event: dict[str, list[float]] = defaultdict(list)
    for p, b, y, e in zip(candidate, baseline, labels, events):
        by_event[e].append(log_loss([p], [y]) - log_loss([b], [y]))
    ci = event_bootstrap_mean_ci(by_event, seed=seed)
    return {**ci, "candidate_log_loss": log_loss(list(candidate), list(labels)),
            "baseline_log_loss": log_loss(list(baseline), list(labels)), "passed": ci["ci_high"] < 0}


# --- P6-DM1 (P6-Q1) ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PredictedAlliance:
    teams: tuple[int, ...]  # captain first
    p_win_event: float


def identifies(actual: tuple[int, ...], predicted: Sequence[PredictedAlliance]) -> bool:
    """P6-Q1: some predicted alliance contains the actual captain and at least one actual pick, and is among the
    top 2 predicted contenders by P(win event)."""
    top = sorted(predicted, key=lambda a: (-a.p_win_event, a.teams))[:2]
    captain, picks = actual[0], set(actual[1:])
    return any(captain in a.teams and picks & set(a.teams) for a in top)


def dm1_result(per_event: Mapping[str, Sequence[bool]], *, seed: int) -> dict[str, object]:
    """Pooled share identified over strong alliances (winner and finalist), with an event-bootstrap CI. Met iff the
    pooled share is > 0.5 (P6-Q1)."""
    values = {e: [1.0 if hit else 0.0 for hit in hits] for e, hits in per_event.items()}
    ci = event_bootstrap_mean_ci(values, seed=seed)
    return {**ci, "share_identified": ci["mean"], "met": ci["mean"] > 0.5}
