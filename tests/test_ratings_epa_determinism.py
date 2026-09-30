"""Deterministic replay (data contract §6.2).

Results must be a pure function of the SeasonInput: identical across repeated
runs, input order, dict key order, serialization round trips, process hash
seeds, the clock, and a snapshot/resume at any point.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from ml.ratings.epa import run_season, start_engine
from ml.ratings.epa.engine import EpaEngine
from ml.ratings.epa.inputs import (
    PriorSeasonInput,
    PriorTeamYear,
    SeasonInput,
    canonical_json,
    season_input_fingerprint,
)
from ratings_epa_support import random_season

REPO = Path(__file__).resolve().parents[1]


def _with_prior(season_input: SeasonInput) -> SeasonInput:
    rng = random.Random(3)
    teams = sorted({t for m in season_input.matches for t in m.red.teams + m.blue.teams})
    prior = PriorSeasonInput(source="synthetic", team_years={
        t: tuple(PriorTeamYear(season=season_input.season - k, norm_epa=rng.randint(1300, 1800)) for k in (1, 2))
        for t in teams[::2]
    })
    return season_input.model_copy(update={"prior": prior})


@pytest.fixture(scope="module", params=[2024, 2025, 2026])
def season_input(request) -> SeasonInput:
    base = random_season(request.param, seed=request.param)
    if request.param == 2026:
        base = base.model_copy(update={"team_districts": {100: "isr", 101: "fim"}})
    return _with_prior(base)


def _shuffled(season_input: SeasonInput, seed: int) -> SeasonInput:
    rng = random.Random(seed)
    events, matches = list(season_input.events), list(season_input.matches)
    rng.shuffle(events)
    rng.shuffle(matches)
    reversed_matches = []
    for m in matches:  # reverse every breakdown's key order, as a different JSON parser might
        sides = {}
        for color in ("red", "blue"):
            a = getattr(m, color)
            bd = None if a.breakdown is None else dict(reversed(list(a.breakdown.items())))
            sides[color] = a.model_copy(update={"breakdown": bd})
        reversed_matches.append(m.model_copy(update=sides))
    prior = season_input.prior
    if prior is not None:
        items = list(prior.team_years.items())
        rng.shuffle(items)
        prior = prior.model_copy(update={"team_years": {t: tuple(reversed(ys)) for t, ys in items}})
    return season_input.model_copy(update={"events": tuple(events), "matches": tuple(reversed_matches), "prior": prior})


def test_repeated_runs_are_byte_identical(season_input: SeasonInput) -> None:
    first = run_season(season_input, created_at="a").canonical_json()
    for _ in range(2):
        assert run_season(season_input, created_at="a").canonical_json() == first


def test_input_order_does_not_matter(season_input: SeasonInput) -> None:
    baseline = run_season(season_input, created_at="a")
    for seed in (1, 2):
        shuffled = _shuffled(season_input, seed)
        assert season_input_fingerprint(shuffled) == season_input_fingerprint(season_input)
        assert run_season(shuffled, created_at="a").canonical_json() == baseline.canonical_json()


def test_the_clock_reaches_only_the_manifest(season_input: SeasonInput) -> None:
    a = run_season(season_input, created_at="2026-01-01T00:00:00+00:00")
    b = run_season(season_input)  # real clock
    assert a.canonical_json() == b.canonical_json()
    assert {k: v for k, v in a.manifest.items() if k != "created_at"} == {
        k: v for k, v in b.manifest.items() if k != "created_at"
    }


def test_input_serialization_round_trip(season_input: SeasonInput) -> None:
    restored = SeasonInput.model_validate_json(season_input.model_dump_json())
    assert restored == season_input
    assert run_season(restored, created_at="a").canonical_json() == run_season(season_input, created_at="a").canonical_json()


def test_result_serialization_round_trip(season_input: SeasonInput) -> None:
    text = run_season(season_input, created_at="a").canonical_json()
    assert canonical_json(json.loads(text)) == text


@pytest.mark.parametrize("fraction", [0.0, 0.1, 0.5, 0.9, 1.0])
def test_snapshot_and_resume_is_bit_identical(season_input: SeasonInput, fraction: float) -> None:
    prepared, full_engine = start_engine(season_input)
    full = [full_engine.process(m) for m in prepared.stream]

    prepared, engine = start_engine(season_input)
    cut = int(len(prepared.stream) * fraction)
    head = [engine.process(m) for m in prepared.stream[:cut]]
    snapshot = json.loads(json.dumps(engine.snapshot()))  # through text, as a stored checkpoint would be
    resumed = EpaEngine.from_snapshot(snapshot)
    tail = [resumed.process(m) for m in prepared.stream[cut:]]
    assert head + tail == full
    assert resumed.ratings() == full_engine.ratings()
    assert {t: resumed.qual_count(t) for t in prepared.teams} == {t: full_engine.qual_count(t) for t in prepared.teams}


def test_resumed_engine_refuses_to_replay_processed_matches(season_input: SeasonInput) -> None:
    prepared, engine = start_engine(season_input)
    for m in prepared.stream[:5]:
        engine.process(m)
    resumed = EpaEngine.from_snapshot(json.loads(json.dumps(engine.snapshot())))
    with pytest.raises(ValueError, match="is not after"):
        resumed.process(prepared.stream[4])


def test_tied_matches_are_ordered_by_match_key_whatever_the_input_order() -> None:
    base = random_season(2024, seed=11)
    # put two matches that share a team at the same scheduled time
    matches = list(base.matches)
    a, b = matches[3], matches[4]
    shared = a.red.teams[0]
    b = b.model_copy(update={"time": a.time, "blue": b.blue.model_copy(update={"teams": (shared, *b.blue.teams[1:])})})
    if shared in b.red.teams:
        pytest.skip("synthetic draw put the shared team on both alliances")
    matches[4] = b
    forward = base.model_copy(update={"matches": tuple(matches)})
    backward = base.model_copy(update={"matches": tuple(reversed(matches))})
    ra, rb = run_season(forward, created_at="a"), run_season(backward, created_at="a")
    assert ra.canonical_json() == rb.canonical_json()
    keys = [r.match_key for r in ra.records]
    assert keys.index(min(a.match_key, b.match_key)) < keys.index(max(a.match_key, b.match_key))
    assert ra.report.ties[0].order_sensitive


_HASH_SEED_SCRIPT = """
import sys
sys.path.insert(0, {tests!r})
from ratings_epa_support import random_season
from ml.ratings.epa import run_season
print(run_season(random_season(2025, seed=5), created_at="a").results_fingerprint())
"""


def test_results_do_not_depend_on_the_process_hash_seed() -> None:
    script = _HASH_SEED_SCRIPT.format(tests=str(REPO / "tests"))
    outputs = []
    for seed in ("1", "987654"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run([sys.executable, "-c", script], cwd=REPO, env=env, capture_output=True, text=True,
                              check=True, timeout=120)
        outputs.append(done.stdout.strip())
    assert outputs[0] == outputs[1] and len(outputs[0]) == 64
