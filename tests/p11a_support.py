"""Synthetic fixtures for the P11A tests: a SYNTHETIC season (9911) with a made-up GameSpec, scoring configuration and
event. Nothing here is a real game, a real rule or evidence about any real team."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from data.game_spec import GameSpec
from ml.alliance import scoring_config as scoring_config_module
from ml.alliance.scoring_config import SeasonScoringConfig
from ml.alliance.snapshot import EventSnapshot, QualRow

SEASON = 9911
T0 = datetime(2099, 3, 1, 9, 0, tzinfo=timezone.utc)


def game_spec(season: int = SEASON) -> GameSpec:
    action = lambda aid, period, pts: {"action_id": aid, "name": aid, "period": period, "points": pts,  # noqa: E731
                                       "unit": "synthetic", "action_type": "score", "manual_section": "synthetic"}
    return GameSpec.model_validate({
        "season": season, "game_name": "SYNTHETIC GAME",
        "match_length": {"auto_seconds": 15, "teleop_seconds": 135, "endgame_seconds": 20},
        "scoring_actions": [action("auto_piece", "auto", 4), action("teleop_piece", "teleop", 2),
                            action("climb", "endgame", 10), action("auto_bonus", "auto", 6)],
        "ranking_point_rules": [], "field_elements": [],
        "source": {"manual_title": "SYNTHETIC", "manual_version": "0", "entered_by": "test",
                   "entry_started_at": "2099-01-01T00:00:00Z", "entry_completed_at": "2099-01-02T00:00:00Z"}})


def scoring_config(*, approved: bool = True, endgame_cap_count: int | None = 2, bonus: bool = False,
                   spec: GameSpec | None = None, season: int = SEASON) -> SeasonScoringConfig:
    spec = spec or game_spec(season)
    endgame = ({"component": "endgame", "combination": "alliance_cap", "cap_action_id": "climb",
                "cap_count": endgame_cap_count, "citation": "SYNTHETIC: two climb positions"}
               if endgame_cap_count else {"component": "endgame", "combination": "sum", "citation": "SYNTHETIC"})
    auto = {"component": "auto", "combination": "sum", "citation": "SYNTHETIC"}
    if bonus:
        auto["bonuses"] = [{"threshold_points": 20, "bonus_action_id": "auto_bonus", "citation": "SYNTHETIC"}]
    draft = SeasonScoringConfig.model_validate({
        "season": season, "game_spec_sha256": spec.sha256(),
        "rules": [auto, {"component": "teleop", "combination": "sum", "citation": "SYNTHETIC"}, endgame],
        "fouls": "event_mean",
        "source": {"entered_by": "test", "entered_at": "2099-01-03T00:00:00Z", "manual_title": "SYNTHETIC",
                   "manual_version": "0"}})
    return approve(draft) if approved else draft


def approve(draft: SeasonScoringConfig) -> SeasonScoringConfig:
    """A SYNTHETIC approval, for tests only (no tool in the repository approves a configuration)."""
    return SeasonScoringConfig.model_validate({
        **draft.model_dump(mode="json"), "status": "approved",
        "review": {"reviewer": "Synthetic Reviewer", "qualification": "synthetic test only",
                   "reviewed_at": "2099-01-04T00:00:00Z", "verified_sha256": draft.content_sha256()}})


def truths(n_teams: int = 24, seed: int = 7) -> dict[int, dict[str, float]]:
    rng = np.random.default_rng(seed)
    return {9900 + i: {"auto": float(rng.normal(12, 4)), "teleop": float(rng.normal(25, 8)),
                       "endgame": float(rng.normal(6, 3))} for i in range(1, n_teams + 1)}


def snapshot(n_teams: int = 24, matches_per_team: int = 10, noise: float = 4.0, seed: int = 7,
             with_config: bool = True, approved: bool = True, as_of_offset_hours: int = 100,
             truth: dict | None = None, season: int = SEASON, event_key: str | None = None) -> EventSnapshot:
    """A synthetic event: a balanced random schedule, true per-robot contributions, normal alliance noise."""
    rng = np.random.default_rng(seed)
    truth = truth or truths(n_teams, seed)
    teams = sorted(truth)
    rows, k = [], 0
    n_matches = n_teams * matches_per_team // 6
    for m in range(n_matches):
        order = rng.permutation(teams)[:6]
        for color, group in (("red", order[:3]), ("blue", order[3:])):
            parts = {c: max(0.0, sum(truth[t][c] for t in group) + rng.normal(0, noise)) for c in
                     ("auto", "teleop", "endgame")}
            fouls = float(rng.integers(0, 6))
            rows.append(QualRow(f"{event_key or f'{season}syn'}_qm{m + 1}", (T0 + timedelta(minutes=7 * m)).isoformat(), color,
                                tuple(sorted(int(t) for t in group)), round(parts["auto"], 1),
                                round(parts["teleop"], 1), round(parts["endgame"], 1), fouls,
                                round(sum(parts.values()) + fouls, 1)))
            k += 1
    spec = game_spec(season)
    return EventSnapshot(
        event_key=event_key or f"{season}syn", season=season, start_date="2099-03-01",
        as_of=(T0 + timedelta(hours=as_of_offset_hours)).isoformat(), qual_rows=rows, roster=teams,
        ranks={t: i + 1 for i, t in enumerate(sorted(teams, key=lambda t: -sum(truth[t].values())))},
        scoring_config=(scoring_config(approved=approved, season=season).model_dump(mode="json") if with_config
                        else None),
        game_spec=spec.model_dump(mode="json") if with_config else None,
        provenance={"source": "SYNTHETIC test fixture", "built_at": T0.isoformat()})


def write_registry(directory, season: int = SEASON) -> None:
    """A SYNTHETIC approved configuration for `season`, registered as data/season_scoring would hold it (tests only;
    always in a temporary folder, never in the real registry)."""
    (directory / f"{season}.json").write_text(scoring_config(season=season).model_dump_json())


@pytest.fixture(autouse=True)
def synthetic_registry(tmp_path_factory, monkeypatch):
    """Import into a test module to register the SYNTHETIC season (never the real data/season_scoring)."""
    from ml.alliance.snapshot import clear_fit_cache

    clear_fit_cache()  # identical synthetic snapshots share a fit-cache key; a test that patches the estimator must refit
    directory = tmp_path_factory.mktemp("season_scoring")
    write_registry(directory)
    monkeypatch.setattr(scoring_config_module, "CONFIG_DIR", directory)
    return directory
