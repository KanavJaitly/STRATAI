"""The trained models committed for the hosted API (deploy/ml_registry) agree with render.yaml's pins, and load.

render.yaml points the Render service at deploy/ml_registry and pins each model to the sha256 of its model.json. If a
file and its pin drift apart, the API refuses the model and serves model_not_loaded on the live site; these tests make
that a test failure instead. Needs no database.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from api.ml_loading import load_pinned_ranking_model, load_pinned_strategy_model, load_pinned_win_prob_model
from data.config import Settings

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "deploy" / "ml_registry"
MODELS = {  # kind -> (model type, render.yaml prefix)
    "ranking": ("ranking_xgb_v2", "ML_RANKING_MODEL"),
    "win_prob": ("win_prob_xgb_calibrated", "ML_WIN_PROB_MODEL"),
    "strategy": ("strategy_outcome_component", "ML_STRATEGY_MODEL"),
}


def render_env() -> dict[str, str]:
    """The literal `- key: X / value: Y` pairs of render.yaml (no YAML library is a dependency here)."""
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    pairs = re.findall(r"- key: (\S+)\n\s+value: \"?([^\"\n]+)\"?", text)
    return dict(pairs)


def test_render_points_the_api_at_the_committed_registry():
    assert render_env()["ML_REGISTRY_DIR"] == "deploy/ml_registry"
    assert REGISTRY.is_dir()


@pytest.mark.parametrize("kind", sorted(MODELS))
def test_each_pin_names_a_committed_model_whose_file_matches_it(kind):
    model_type, prefix = MODELS[kind]
    env = render_env()
    tag, pin = env[f"{prefix}_VERSION_TAG"], env[f"{prefix}_SHA256"]
    folder = REGISTRY / model_type / tag
    assert (folder / "manifest.json").is_file(), folder
    assert hashlib.sha256((folder / "model.json").read_bytes()).hexdigest() == pin


def test_no_playoff_model_is_pinned():
    # PX-1 failed its P6-Q3 gate; the pick list stays model_not_loaded on the hosted API too.
    assert not any(key.startswith(("ML_PX1_", "ML_PX2_")) for key in render_env())


def test_the_committed_models_load_with_renders_settings(monkeypatch):
    env = render_env()
    for key, value in env.items():
        if key.startswith("ML_"):
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("ML_REGISTRY_DIR", str(REGISTRY))  # Render runs from the repository root; tests may not
    settings = Settings()
    ranking, win_prob = load_pinned_ranking_model(settings), load_pinned_win_prob_model(settings)
    assert ranking is not None and ranking.version_tag == "d18"
    assert win_prob is not None and win_prob.version_tag == "d18"
    assert load_pinned_strategy_model(settings) is not None
