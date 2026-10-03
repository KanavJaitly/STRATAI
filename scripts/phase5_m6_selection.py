"""P5-M6 verification population (decision P5-D14): seeded, stratified selection of events and windows.

    python -m scripts.phase5_m6_selection draw        # read-only on the serving database; records the selection

Implements `.agent/phase5/M06_Q4_PROPOSAL.md` (approved as P5-D14, without the synthetic score-correction case).
The selection is drawn and recorded write-once (`.agent/phase5/results/p5_m6_selection.json`) **before** any
recorded verification check runs. The harness (scripts/phase5_m6_replay.py) follows the recorded windows exactly.

**Units.**
- **Step:** the event's matches sharing one scheduled time. A window is a run of consecutive steps.
- **Indexing:** qualification steps 0 … n_q − 1, in scheduled order.
- **Playoff steps:** grouped the same way, also in scheduled order.

**Eligibility, common to every stratum:**
- at least 12 qualification and 2 playoff matches;
- every match has a scheduled time;
- not one of the five events of the original P5-M6 population (`EXCLUDED`).

**Strata, with the seeded draws in this order:**

| Stratum | Candidates | Window |
|---|---|---|
| E1 (fixed) | 2026iscmp | qualification steps [s, s+8), s = randint(1, n_q − 8); then the first 2 playoff steps |
| E2 | 2026, Regional or District, TBA week 0 | qualification steps [0, 8); then the first 2 playoff steps |
| E3 | 2026, Championship Division (event_type 3) | qualification steps [s, s+5), s = randint(1, n_q − 5); then the first playoff step |
| E4 | 2026, Regional or District, TBA weeks 2–4 | the switch step w (the last team's ⌈n_i/2⌉-th scheduled qualification match): steps [w−4, w+4); needs w ≥ 4 and w+4 ≤ n_q. Then the first 2 playoff steps |
| E5 | 2025, Regional or District, weeks 1–5, with a qualification step holding a DQ or surrogate team | first such step f; steps [s, s+6) with s = max(1, f−2); needs f ≥ 1 and s+6 ≤ n_q. Then the first 2 playoff steps |

**Draw order:** `rng = random.Random(20261006)`; then E2, E3, E4, E5 by `rng.choice` over each stratum's
candidates sorted by event_key; then E1's and E3's starts by `rng.randint`.

**Fingerprint:** sha256 over the canonical JSON of every stratum's sorted candidate facts and the serving
database's row counts. A different database state yields a different fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

SEED = 20261006
PROPOSAL = Path(".agent/phase5/M06_Q4_PROPOSAL.md")
RECORD = "p5_m6_selection.json"
EXCLUDED = ("2026alhu", "2026arc", "2026arli", "2026ausc", "2026azfg")  # the original P5-M6 five
MIN_QUALS, MIN_PLAYOFFS = 12, 2
REGIONAL_OR_DISTRICT = (0, 1)  # TBA event_type
CHAMPIONSHIP_DIVISION = 3
E1_EVENT = "2026iscmp"
WINDOWS = {"E1": (8, 2), "E2": (8, 2), "E3": (5, 1), "E4": (8, 2), "E5": (6, 2)}  # (qual steps, playoff steps)
BUDGET_MINUTES = 45.0


@dataclass(frozen=True)
class Step:
    time: datetime
    match_keys: tuple[str, ...]


@dataclass
class EventFacts:
    event_key: str
    season: int
    event_type: int | None
    week: int | None
    roster_size: int
    qual_steps: list[Step]
    playoff_steps: list[Step]
    switch_step: int | None  # index of the qualification step holding the event switch time
    edge_step: int | None  # first qualification step with a DQ'd or surrogate team
    untimed_matches: int = 0

    @property
    def eligible(self) -> bool:
        return (self.event_key not in EXCLUDED and self.untimed_matches == 0
                and sum(len(s.match_keys) for s in self.qual_steps) >= MIN_QUALS
                and sum(len(s.match_keys) for s in self.playoff_steps) >= MIN_PLAYOFFS)

    def summary(self) -> dict[str, Any]:
        return {"event_key": self.event_key, "season": self.season, "event_type": self.event_type, "week": self.week,
                "roster_size": self.roster_size, "qual_steps": len(self.qual_steps),
                "playoff_steps": len(self.playoff_steps), "switch_step": self.switch_step, "edge_step": self.edge_step}


def group_steps(matches: list[tuple[str, datetime]]) -> list[Step]:
    """Matches sharing a scheduled time form one step; steps in time order, keys sorted within a step."""
    by_time: dict[datetime, list[str]] = {}
    for key, when in matches:
        by_time.setdefault(when, []).append(key)
    return [Step(when, tuple(sorted(keys))) for when, keys in sorted(by_time.items())]


def switch_step_index(qual_steps: list[Step], team_matches: dict[int, list[datetime]]) -> int | None:
    """Index of the step at the event switch time (ml.views.event_analysis.switch_time over scheduled quals)."""
    from ml.views.event_analysis import switch_time

    when = switch_time(team_matches)
    return next((i for i, s in enumerate(qual_steps) if s.time == when), None)


# --- strata -------------------------------------------------------------------------------------


def candidates(facts: list[EventFacts]) -> dict[str, list[EventFacts]]:
    ok = sorted((f for f in facts if f.eligible), key=lambda f: f.event_key)
    n = {f.event_key: len(f.qual_steps) for f in ok}
    return {
        "E1": [f for f in ok if f.event_key == E1_EVENT and n[f.event_key] >= WINDOWS["E1"][0] + 1],
        "E2": [f for f in ok if f.season == 2026 and f.event_type in REGIONAL_OR_DISTRICT and f.week == 0
               and n[f.event_key] >= WINDOWS["E2"][0]],
        "E3": [f for f in ok if f.season == 2026 and f.event_type == CHAMPIONSHIP_DIVISION
               and n[f.event_key] >= WINDOWS["E3"][0] + 1],
        "E4": [f for f in ok if f.season == 2026 and f.event_type in REGIONAL_OR_DISTRICT and f.week in (2, 3, 4)
               and f.switch_step is not None and f.switch_step >= 4 and f.switch_step + 4 <= n[f.event_key]],
        "E5": [f for f in ok if f.season == 2025 and f.event_type in REGIONAL_OR_DISTRICT and f.week in (1, 2, 3, 4, 5)
               and f.edge_step is not None and f.edge_step >= 1
               and max(1, f.edge_step - 2) + WINDOWS["E5"][0] <= n[f.event_key]],
    }


@dataclass
class EventPlan:
    stratum: str
    event_key: str
    season: int
    roster_size: int
    pre_window_bulk: list[str]  # qualification matches landed in one catch-up sync before the window
    qual_window: list[list[str]]  # one entry per checked step
    post_window_bulk: list[str]  # remaining qualification matches, landed before the playoff steps
    playoff_window: list[list[str]]
    switch_step_in_window: int | None = None  # E4: index within qual_window of the switch step
    sentinel_steps: list[int] = field(default_factory=list)  # indices into qual_window

    @property
    def checked_steps(self) -> int:
        return len(self.qual_window) + len(self.playoff_window)


def plan(stratum: str, facts: EventFacts, start: int) -> EventPlan:
    q, p = WINDOWS[stratum]
    steps = facts.qual_steps
    window = steps[start:start + q]
    if len(window) != q:
        raise ValueError(f"{facts.event_key}: window [{start}, {start + q}) exceeds {len(steps)} qualification steps")
    keys = lambda ss: [k for s in ss for k in s.match_keys]  # noqa: E731
    return EventPlan(stratum, facts.event_key, facts.season, facts.roster_size, keys(steps[:start]),
                     [list(s.match_keys) for s in window], keys(steps[start + q:]),
                     [list(s.match_keys) for s in facts.playoff_steps[:p]],
                     (facts.switch_step - start) if stratum == "E4" else None,  # type: ignore[operator]
                     [q // 2])  # the qualification window's middle step (proposal §5)


def draw(facts: list[EventFacts], seed: int = SEED) -> dict[str, Any]:
    """The seeded selection (see the module docstring for the exact draw order)."""
    pools = candidates(facts)
    if not pools["E1"]:
        raise ValueError(f"{E1_EVENT} is not eligible")
    for stratum in ("E2", "E3", "E4", "E5"):
        if not pools[stratum]:
            raise ValueError(f"stratum {stratum} has no eligible candidate")
    rng = random.Random(seed)
    chosen = {"E1": pools["E1"][0]}
    for stratum in ("E2", "E3", "E4", "E5"):
        chosen[stratum] = rng.choice(pools[stratum])
    starts = {"E2": 0, "E4": chosen["E4"].switch_step - 4,  # type: ignore[operator]
              "E5": max(1, chosen["E5"].edge_step - 2)}  # type: ignore[operator]
    starts["E1"] = rng.randint(1, len(chosen["E1"].qual_steps) - WINDOWS["E1"][0])
    starts["E3"] = rng.randint(1, len(chosen["E3"].qual_steps) - WINDOWS["E3"][0])
    plans = [plan(s, chosen[s], starts[s]) for s in ("E1", "E2", "E3", "E4", "E5")]
    return {"seed": seed, "draw_order": ["E2", "E3", "E4", "E5", "E1 start", "E3 start"],
            "candidate_counts": {s: len(v) for s, v in pools.items()},
            "candidates": {s: [f.event_key for f in v] for s, v in pools.items()},
            "starts": starts, "plans": [asdict(p) for p in plans],
            "checked_steps": sum(p.checked_steps for p in plans)}


def fingerprint(facts: list[EventFacts], row_counts: dict[str, int]) -> str:
    pools = candidates(facts)
    payload = {"row_counts": row_counts,
               "candidates": {s: [f.summary() for f in v] for s, v in sorted(pools.items())}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def estimate_minutes(plans: list[dict[str, Any]]) -> dict[str, float]:
    """From the measured 2026arli costs: ~13 s + 0.45 s × roster per checked step; fixed parts as in the proposal."""
    steps = sum((13 + 0.45 * p["roster_size"]) * (len(p["qual_window"]) + len(p["playoff_window"])) for p in plans) / 60
    bulk = sum((1 + 0.2 * p["roster_size"]) * ((1 if p["pre_window_bulk"] else 0) + (1 if p["post_window_bulk"] else 0))
               for p in plans) / 60
    endpoints = 6.0  # E1 and E2 at window end; E4 before and after the switch
    setup, reserve = 3.0, 2.0
    total = setup + steps + bulk + endpoints + reserve
    return {"setup": setup, "checked_steps": round(steps, 1), "bulk_syncs": round(bulk, 1), "endpoints": endpoints,
            "final_rerequests": reserve, "total": round(total, 1), "budget": BUDGET_MINUTES}


# --- reading facts (read-only) ----------------------------------------------------------------------

EVENTS_SQL = """
SELECT e.event_key, e.season, (r.payload_json->>'event_type')::int, (r.payload_json->>'week')::int
FROM events e LEFT JOIN LATERAL (
    SELECT payload_json FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = 'event'
      AND source_object_id = e.event_key AND is_current ORDER BY id DESC LIMIT 1) r ON TRUE
WHERE e.season = ANY(%(seasons)s) ORDER BY 1
"""
MATCHES_SQL = """
SELECT m.event_key, m.match_key, m.competition_level, m.scheduled_time, raw.dq OR raw.surrogate
FROM matches m JOIN events e ON e.event_key = m.event_key
LEFT JOIN LATERAL (
    SELECT (jsonb_array_length(coalesce(r.payload_json->'alliances'->'red'->'dq_team_keys', '[]'))
          + jsonb_array_length(coalesce(r.payload_json->'alliances'->'blue'->'dq_team_keys', '[]'))) > 0 AS dq,
           (jsonb_array_length(coalesce(r.payload_json->'alliances'->'red'->'surrogate_team_keys', '[]'))
          + jsonb_array_length(coalesce(r.payload_json->'alliances'->'blue'->'surrogate_team_keys', '[]'))) > 0
             AS surrogate
    FROM raw_source_payloads r WHERE r.source = 'tba' AND r.source_object_type = 'match'
      AND r.source_object_id = m.match_key AND r.is_current ORDER BY r.id DESC LIMIT 1) raw ON TRUE
WHERE e.season = ANY(%(seasons)s)
ORDER BY m.event_key, m.scheduled_time, m.match_key
"""
TEAMS_SQL = """
SELECT m.event_key, mt.team_number, m.scheduled_time FROM matches m JOIN match_teams mt USING (match_key)
JOIN events e ON e.event_key = m.event_key
WHERE e.season = ANY(%(seasons)s) AND m.competition_level = 'qualification' AND m.scheduled_time IS NOT NULL
"""
COUNTS_SQL = """
SELECT (SELECT count(*) FROM events WHERE season = ANY(%(seasons)s)),
       (SELECT count(*) FROM matches WHERE season = ANY(%(seasons)s)),
       (SELECT count(*) FROM match_teams mt JOIN matches m USING (match_key) WHERE m.season = ANY(%(seasons)s)),
       (SELECT count(*) FROM raw_source_payloads WHERE source = 'tba' AND is_current)
"""


def read_facts(database, seasons: tuple[int, ...] = (2025, 2026)) -> tuple[list[EventFacts], dict[str, int]]:
    params = {"seasons": list(seasons)}
    with database.cursor() as c:
        c.execute(EVENTS_SQL, params)
        events = c.fetchall()
        c.execute(MATCHES_SQL, params)
        matches = c.fetchall()
        c.execute(TEAMS_SQL, params)
        team_rows = c.fetchall()
        c.execute(COUNTS_SQL, params)
        counts = dict(zip(("events", "matches", "match_teams", "current_tba_payloads"), c.fetchone()))
    by_event: dict[str, list] = {}
    for row in matches:
        by_event.setdefault(row[0], []).append(row[1:])
    team_matches: dict[str, dict[int, list[datetime]]] = {}
    roster: dict[str, set[int]] = {}
    for event_key, team, when in team_rows:
        team_matches.setdefault(event_key, {}).setdefault(team, []).append(when)
        roster.setdefault(event_key, set()).add(team)
    facts = []
    for event_key, season, event_type, week in events:
        rows = by_event.get(event_key, [])
        quals = [(k, t) for k, level, t, _ in rows if level == "qualification" and t is not None]
        playoffs = [(k, t) for k, level, t, _ in rows if level != "qualification" and t is not None]
        edge_keys = {k for k, level, t, edge in rows if level == "qualification" and edge}
        qual_steps = group_steps(quals)
        edge = next((i for i, s in enumerate(qual_steps) if edge_keys & set(s.match_keys)), None)
        facts.append(EventFacts(event_key, season, event_type, week, len(roster.get(event_key, ())),
                                qual_steps, group_steps(playoffs),
                                switch_step_index(qual_steps, team_matches.get(event_key, {})) if qual_steps else None,
                                edge, untimed_matches=sum(1 for _, _, t, _ in rows if t is None)))
    return facts, counts


def main(argv: list[str] | None = None) -> int:
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from scripts.phase5_records import sha256_file, write_once

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("draw",))
    parser.parse_args(argv)
    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    try:
        facts, counts = read_facts(database)
    finally:
        database.close()
    selection = draw(facts)
    result = {"decision": "P5-D14", "proposal_sha256": sha256_file(PROPOSAL), "population_fingerprint":
              fingerprint(facts, counts), "serving_row_counts": counts, **selection,
              "estimated_minutes": estimate_minutes(selection["plans"]),
              "synthetic_cases": "none (P5-D14 removed the synthetic score-correction case)"}
    path = write_once(RECORD, result)
    print(json.dumps({k: result[k] for k in ("population_fingerprint", "candidate_counts", "starts", "checked_steps",
                                             "estimated_minutes")}, indent=1, default=str))
    for p in result["plans"]:
        print(p["stratum"], p["event_key"], "roster", p["roster_size"], "pre-bulk", len(p["pre_window_bulk"]),
              "qual window", p["qual_window"], "post-bulk", len(p["post_window_bulk"]), "playoffs", p["playoff_window"],
              "switch", p["switch_step_in_window"], "sentinels", p["sentinel_steps"])
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
