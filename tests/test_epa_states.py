"""ml.ratings.epa_states and the TeamFeatures epa_source_state invariants (P5-D2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures
from ml.ratings.epa_states import CURRENT, FALLBACK_STRATAI, STALE, WITHHELD_NO_PRIOR_EVENT, served_state


def _features(**overrides) -> TeamFeatures:
    values = dict(
        team_number=1, epa_total=40.0, epa_total_present=True, epa_auto_present=False, epa_teleop_present=False,
        epa_endgame_present=False, epa_source_event_key="2026x", epa_withheld_reason=None,
        epa_value_source="statbotics", epa_source_state=CURRENT,
        average_score_present=False, score_stddev_present=False, consistency_rating_present=False,
        reliability_score_present=False, matches_considered=0, matches_used=0, average_auto_points_present=False,
        auto_points_matches_used=0, defense_score_present=False, defense_agreement_present=False,
        defense_observation_count=0, feeding_score_present=False, feeding_agreement_present=False,
        feeding_observation_count=0)
    values.update(overrides)
    return TeamFeatures(**values)


def test_served_state_derivation():
    assert served_state("statbotics", {}) == CURRENT
    assert served_state("stratai_fallback", {}) == FALLBACK_STRATAI
    assert served_state("statbotics", {"epa_source_state": STALE}) == STALE
    with pytest.raises(ValueError):
        served_state("statbotics", {"epa_source_state": "pending"})  # a refused state never carries a value


def test_valid_states_construct():
    assert _features().epa_source_state == CURRENT
    assert _features(epa_value_source="stratai_fallback", epa_source_state=FALLBACK_STRATAI)
    absent = _features(epa_total=None, epa_total_present=False, epa_source_event_key=None,
                       epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT, epa_value_source=None,
                       epa_source_state=WITHHELD_NO_PRIOR_EVENT)
    assert absent.epa_source_state == WITHHELD_NO_PRIOR_EVENT
    assert _features(epa_source_state=None).epa_source_state is None  # rows built before Phase 5


@pytest.mark.parametrize("overrides", [
    {"epa_source_state": "pending"},                                     # refused state with a value
    {"epa_source_state": FALLBACK_STRATAI},                              # fallback state, statbotics source
    {"epa_value_source": "stratai_fallback", "epa_source_state": CURRENT},  # fallback source, current state
    {"epa_total": None, "epa_total_present": False, "epa_source_event_key": None,
     "epa_withheld_reason": EPA_WITHHELD_NO_PRIOR_EVENT, "epa_value_source": None, "epa_source_state": CURRENT},
])
def test_inconsistent_states_are_rejected(overrides):
    with pytest.raises(ValidationError):
        _features(**overrides)
