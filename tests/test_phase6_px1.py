"""PX-1 mechanics on SYNTHETIC rows (not evidence; no real playoff data is read here)."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from data.alliances import Alliance
from ml.playoffs.px1 import (PlayoffLogisticModel, PlayoffRow, alliance_match_probability, fit_design, map_side,
                             selection_moment)
from tests.phase6_fixtures import team

T0 = datetime(2099, 4, 1, tzinfo=timezone.utc)


def _team(n: int, epa: float) -> object:
    return team(n, epa * 0.2, epa * 0.6, epa * 0.2, average_score=epa * 2.5, average_score_present=True,
                matches_used=10, matches_considered=10)


def synthetic_rows(n: int, seed: int) -> list[PlayoffRow]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        red_seed, blue_seed = rng.sample(range(1, 9), 2)
        red_strength = rng.gauss(30 - 2 * red_seed, 4)
        blue_strength = rng.gauss(30 - 2 * blue_seed, 4)
        red = tuple(_team(1000 + 6 * i + k, red_strength / 3) for k in range(3))
        blue = tuple(_team(1003 + 6 * i + k, blue_strength / 3) for k in range(3))
        z = 0.15 * (red_strength - blue_strength) - 0.2 * (red_seed - blue_seed)
        rows.append(PlayoffRow(f"m{i}", f"e{i // 20}", 2099, T0 + timedelta(minutes=i), rng.randint(1, 3),
                               red_seed, blue_seed, red, blue, rng.random() < 1 / (1 + math.exp(-z))))
    return rows


def test_selection_moment_and_side_mapping():
    assert selection_moment(T0) == T0 + timedelta(minutes=1)
    alliances = [Alliance(1, 1, None, 11, (11, 12, 13), None, ()), Alliance(2, 2, None, 21, (21, 22, 23), None, ())]
    assert map_side((11, 12, 99), alliances).seed == 1  # a substitute is tolerated
    assert map_side((11, 22, 99), alliances) is None


def test_design_drops_absent_and_constant_columns_and_never_imputes():
    design = fit_design(synthetic_rows(200, 1))
    assert design.dropped["defense_score"] == "no data"
    assert design.dropped["defense_observation_count"] == "no variation"
    assert "epa_total" in design.composition_columns
    assert design.rounds == [2, 3] and len(design.names()) == 3 * (1 + len(design.composition_columns))


def test_model_is_antisymmetric_and_deterministic():
    rows = synthetic_rows(400, 2)
    a = PlayoffLogisticModel.fit(rows)
    b = PlayoffLogisticModel.fit(rows)
    assert a.coef.tolist() == b.coef.tolist()
    for row in rows[:50]:
        assert abs(a.predict(row) + a.predict(row.swapped()) - 1.0) <= 1e-12


def test_seed_only_baseline_uses_the_seed_alone():
    model = PlayoffLogisticModel.fit(synthetic_rows(400, 3), seed_only=True)
    assert model.design.composition_columns == [] and model.model_type == "playoff_seed_only"
    assert model.predict(synthetic_rows(1, 9)[0]) is not None


def test_missing_used_input_is_insufficient_data(tmp_path):
    rows = synthetic_rows(300, 4)
    model = PlayoffLogisticModel.fit(rows)
    broken = rows[0]
    absent = team(1, None, None, None, epa_scale=None)
    hole = PlayoffRow(broken.match_key, broken.event_key, broken.season, broken.scheduled_time, broken.round,
                      broken.red_seed, broken.blue_seed, (absent, *broken.red_teams[1:]), broken.blue_teams,
                      broken.red_win)
    assert model.predict(hole) is None
    path = tmp_path / "model.json"
    model.save(path)
    assert PlayoffLogisticModel.load(path).predict(rows[1]) == model.predict(rows[1])
    features = {t.team_number: t for t in (*rows[1].red_teams, *rows[1].blue_teams)}
    p = alliance_match_probability(model, features)
    red = tuple(t.team_number for t in rows[1].red_teams)
    blue = tuple(t.team_number for t in rows[1].blue_teams)
    assert p(red, blue, rows[1].red_seed, rows[1].blue_seed, rows[1].round) == model.predict(rows[1])
    features[absent.team_number] = absent
    with pytest.raises(ValueError):
        alliance_match_probability(model, features)((1, *red[1:]), blue, 1, 2, 1)
