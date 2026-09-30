"""2024-2026 score-breakdown adapters (spec §6; reference tba/breakdown.py).

Each adapter turns one alliance's raw TBA score_breakdown into the reference's
cleaned breakdown: the 18 values that feed both the season statistics and the
rating update, plus foul points.

Differences from the reference, all deliberate (spec §11, data contract §4):

* Required fields are checked, never defaulted. The reference reads every
  field with .get(name, 0); STRATAI rejects the match as malformed_breakdown
  instead. A field whose value the reference always overwrites (2025
  coopertitionCriteriaMet, replaced by post_clean) is not required.
* A missing breakdown on a scored alliance is rejected (missing_breakdown);
  the reference substitutes its empty breakdown.
* The empty breakdown is a fresh immutable value per alliance. The
  reference returns one module-level dict by reference (tba/types.py:52,
  tba/breakdown.py:830-832) and post_clean_breakdown writes into it, so in a
  long-lived process state written for one match is visible to every later
  empty alliance, across seasons: 2018's post_clean writes comp_6..comp_9
  and 2025's writes tiebreaker. Those values depend on which seasons that
  process handled earlier and in what order, not on the match's own data,
  so STRATAI does not reproduce them (decision (b): a reference-process
  artifact, excluded). Every such alliance is counted as a possible
  divergence (shared_empty_breakdown). The 2025 per-match tiebreaker rule
  itself IS reproduced (decision (a)): post_clean_2025 recomputes the
  tiebreaker from this match's two alliances only, and for an empty alliance
  that value is always 0 because its processor-algae count is unknown (0).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np

from ml.ratings.epa.constants import (
    COMP_0,
    PROCESSOR_ALGAE_2025,
    TELEOP,
    TIEBREAKER,
    VECTOR_LENGTH,
)
from ml.ratings.epa.exclusions import MALFORMED_BREAKDOWN, MISSING_BREAKDOWN

Value = int | bool | None
FieldKind = Literal["int", "bool", "object"]


@dataclass(frozen=True)
class FieldSpec:
    path: tuple[str, ...]
    kind: FieldKind


def _ints(*names: str) -> tuple[FieldSpec, ...]:
    return tuple(FieldSpec((n,), "int") for n in names)


def _bools(*names: str) -> tuple[FieldSpec, ...]:
    return tuple(FieldSpec((n,), "bool") for n in names)


def _nested_ints(parent: str, *names: str) -> tuple[FieldSpec, ...]:
    return (FieldSpec((parent,), "object"), *(FieldSpec((parent, n), "int") for n in names))


_SHARED = _ints("foulPoints", "adjustPoints")

# Every raw field each adapter reads and uses, per season.
REQUIRED_FIELDS: dict[int, tuple[FieldSpec, ...]] = {
    2024: (
        *_SHARED,
        *_ints(
            "autoLeavePoints", "autoAmpNoteCount", "autoSpeakerNoteCount", "teleopAmpNoteCount",
            "teleopSpeakerNoteCount", "teleopSpeakerNoteAmplifiedCount", "endGameParkPoints",
            "endGameOnStagePoints", "endGameHarmonyPoints", "endGameNoteInTrapPoints",
            "endGameSpotLightBonusPoints",
        ),
        *_bools("melodyBonusAchieved", "ensembleBonusAchieved", "coopertitionBonusAchieved"),
    ),
    2025: (
        *_SHARED,
        *_ints(
            "autoMobilityPoints", "autoCoralPoints", "teleopCoralPoints", "wallAlgaeCount",
            "netAlgaeCount", "endGameBargePoints",
        ),
        *_nested_ints("autoReef", "tba_topRowCount", "tba_midRowCount", "tba_botRowCount", "trough"),
        *_nested_ints("teleopReef", "tba_topRowCount", "tba_midRowCount", "tba_botRowCount", "trough"),
        *_bools("autoBonusAchieved", "coralBonusAchieved", "bargeBonusAchieved"),
    ),
    2026: (
        *_SHARED,
        *_ints("autoTowerPoints", "endGameTowerPoints"),
        *_nested_ints(
            "hubScore", "autoPoints", "endgamePoints", "transitionPoints", "shift1Points",
            "shift2Points", "shift3Points", "shift4Points",
        ),
        *_bools("energizedAchieved", "superchargedAchieved", "traversalAchieved"),
    ),
}


@dataclass(frozen=True)
class CleanedAlliance:
    """One alliance's cleaned breakdown, in rating-vector order.

    values[i] is None where the reference stores None: every component of an
    empty breakdown, and rp_3 in 2024. None is excluded from season means
    (data/avg.py:21) and becomes 0 in the rating update (db/models/match.py:
    195-211). rp values of an empty breakdown are False, not None, exactly as
    the reference's empty dict holds them, so they count as 0 in rp means.
    """

    score: int
    foul: int | None
    values: tuple[Value, ...]
    empty: bool
    teleop_residual: int = 0

    @property
    def no_foul(self) -> Value:
        return self.values[0]


@dataclass(frozen=True)
class BreakdownRejection:
    code: str
    detail: str


_EMPTY_VALUES: tuple[Value, ...] = (None, None, None, None, False, False, False, None) + (None,) * 10


def empty_alliance(score: int) -> CleanedAlliance:
    """A fresh empty breakdown (see the module docstring on the shared dict)."""
    return CleanedAlliance(score=score, foul=None, values=_EMPTY_VALUES, empty=True)


def _problems(season: int, breakdown: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for spec in REQUIRED_FIELDS[season]:
        node: Any = breakdown
        for part in spec.path[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
        name = ".".join(spec.path)
        if not isinstance(node, dict) or spec.path[-1] not in node:
            if isinstance(node, dict) or len(spec.path) == 1:
                problems.append(f"{name} missing")
            continue
        value = node[spec.path[-1]]
        if spec.kind == "int" and (isinstance(value, bool) or not isinstance(value, int)):
            problems.append(f"{name} is {type(value).__name__}, expected int")
        elif spec.kind == "bool" and not isinstance(value, bool):
            problems.append(f"{name} is {type(value).__name__}, expected bool")
        elif spec.kind == "object" and not isinstance(value, dict):
            problems.append(f"{name} is {type(value).__name__}, expected object")
    return problems


def _clean_2024(bd: dict[str, Any]) -> tuple[Value, ...]:
    # tba/breakdown.py:619-693
    auto_leave_points = bd["autoLeavePoints"]
    auto_amp_note_points = 2 * bd["autoAmpNoteCount"]
    auto_speaker_note_points = 5 * bd["autoSpeakerNoteCount"]
    auto_note_points = auto_amp_note_points + auto_speaker_note_points
    auto_points = auto_leave_points + auto_note_points

    teleop_amp_note_points = 1 * bd["teleopAmpNoteCount"]
    amplified = bd["teleopSpeakerNoteAmplifiedCount"]
    teleop_speaker_notes = bd["teleopSpeakerNoteCount"] + amplified
    teleop_speaker_points = 2 * teleop_speaker_notes + 3 * amplified
    teleop_note_points = teleop_amp_note_points + teleop_speaker_points
    teleop_points = teleop_note_points

    speaker_points = auto_speaker_note_points + teleop_speaker_points

    park = bd["endGameParkPoints"]
    on_stage = bd["endGameOnStagePoints"]
    harmony = bd["endGameHarmonyPoints"]
    trap = bd["endGameNoteInTrapPoints"]
    spotlight = bd["endGameSpotLightBonusPoints"]
    endgame_points = park + on_stage + harmony + trap + spotlight

    return (
        None, auto_points, teleop_points, endgame_points,
        bool(bd["melodyBonusAchieved"]), bool(bd["ensembleBonusAchieved"]), None,
        int(bd["coopertitionBonusAchieved"]),
        auto_leave_points, auto_note_points, teleop_note_points, speaker_points, amplified,
        park, on_stage, harmony, trap, spotlight,
    )


def _clean_2025(bd: dict[str, Any]) -> tuple[Value, ...]:
    # tba/breakdown.py:696-766
    auto_reef, teleop_reef = bd["autoReef"], bd["teleopReef"]
    auto_top, auto_mid = auto_reef["tba_topRowCount"], auto_reef["tba_midRowCount"]
    auto_bot, auto_trough = auto_reef["tba_botRowCount"], auto_reef["trough"]
    auto_points = bd["autoMobilityPoints"] + bd["autoCoralPoints"]

    teleop_coral_points = bd["teleopCoralPoints"]
    # the counts are as of the end of teleop; the reference subtracts auto for
    # rows 2-4 but not for the trough (reproduced, spec §11)
    teleop_top = teleop_reef["tba_topRowCount"] - auto_top
    teleop_mid = teleop_reef["tba_midRowCount"] - auto_mid
    teleop_bot = teleop_reef["tba_botRowCount"] - auto_bot
    teleop_trough = teleop_reef["trough"]
    processor_algae = bd["wallAlgaeCount"]
    processor_algae_points = 6 * processor_algae
    net_algae_points = 4 * bd["netAlgaeCount"]
    teleop_points = teleop_coral_points + (processor_algae_points + net_algae_points)

    barge_points = bd["endGameBargePoints"]
    return (
        None, auto_points, teleop_points, barge_points,
        bool(bd["autoBonusAchieved"]), bool(bd["coralBonusAchieved"]), bool(bd["bargeBonusAchieved"]),
        # replaced by post_clean_2025; read only to mirror the reference
        int(bd.get("coopertitionCriteriaMet", False)),
        bd["autoCoralPoints"], teleop_coral_points,
        auto_trough + teleop_trough, auto_bot + teleop_bot, auto_mid + teleop_mid, auto_top + teleop_top,
        processor_algae, processor_algae_points, net_algae_points, barge_points,
    )


def _clean_2026(bd: dict[str, Any], no_foul_points: int) -> tuple[Value, ...]:
    # tba/breakdown.py:769-820
    hub = bd["hubScore"]
    auto_fuel = hub["autoPoints"]
    endgame_fuel = hub["endgamePoints"]
    transition_fuel = hub["transitionPoints"]
    first_shift_fuel = hub["shift1Points"] + hub["shift2Points"]
    second_shift_fuel = hub["shift3Points"] + hub["shift4Points"]
    teleop_fuel = transition_fuel + first_shift_fuel + second_shift_fuel
    auto_tower = bd["autoTowerPoints"]
    endgame_tower = bd["endGameTowerPoints"]
    return (
        None, auto_fuel + auto_tower, teleop_fuel, endgame_fuel + endgame_tower,
        bool(bd["energizedAchieved"]), bool(bd["superchargedAchieved"]), bool(bd["traversalAchieved"]),
        no_foul_points,
        auto_fuel, auto_tower, transition_fuel, first_shift_fuel, second_shift_fuel,
        endgame_fuel, endgame_tower, None, None, None,
    )


def clean_alliance(season: int, score: int, breakdown: dict[str, Any] | None) -> CleanedAlliance | BreakdownRejection:
    """Clean one completed alliance (score >= 0), or say why it cannot be."""
    if score == 0:
        # tba/breakdown.py:831: a zero score yields the empty breakdown whatever TBA sent
        return empty_alliance(score)
    if breakdown is None:
        return BreakdownRejection(MISSING_BREAKDOWN, f"score {score} with no score_breakdown")
    problems = _problems(season, breakdown)
    if problems:
        return BreakdownRejection(MALFORMED_BREAKDOWN, "; ".join(problems))

    foul_points = breakdown["foulPoints"] + breakdown["adjustPoints"]
    no_foul_points = score - foul_points
    if season == 2024:
        raw = _clean_2024(breakdown)
    elif season == 2025:
        raw = _clean_2025(breakdown)
    else:
        raw = _clean_2026(breakdown, no_foul_points)
    values = list(raw)
    values[0] = no_foul_points

    # tba/breakdown.py:872-881: the unexplained remainder goes to teleop
    error = (values[0] or 0) - ((values[1] or 0) + (values[2] or 0) + (values[3] or 0))
    if error != 0:
        values[TELEOP] = (values[TELEOP] or 0) + error
    return CleanedAlliance(score=score, foul=foul_points, values=tuple(values), empty=False, teleop_residual=error)


def post_clean(season: int, red: CleanedAlliance, blue: CleanedAlliance) -> tuple[CleanedAlliance, CleanedAlliance]:
    """tba/breakdown.py:929-936, applied to this match's two alliances only.

    2025's API tiebreaker is unreliable, so the reference recomputes it:
    coopertition iff both alliances scored at least 2 processor algae.
    """
    if season != 2025:
        return red, blue
    coop = int(min(red.values[PROCESSOR_ALGAE_2025] or 0, blue.values[PROCESSOR_ALGAE_2025] or 0) >= 2)
    return _with_value(red, TIEBREAKER, coop), _with_value(blue, TIEBREAKER, coop)


def _with_value(alliance: CleanedAlliance, index: int, value: Value) -> CleanedAlliance:
    values = list(alliance.values)
    values[index] = value
    return replace(alliance, values=tuple(values))


def actual_vector(alliance: CleanedAlliance) -> np.ndarray:
    """The observed vector the update uses (db/models/match.py:195-211), float32."""
    v = alliance.values
    return np.array(
        [
            v[0] or 0, v[1] or 0, v[2] or 0, v[3] or 0,
            int(v[4] or False), int(v[5] or False), int(v[6] or False),
            v[7] or 0,
            *[v[COMP_0 + i] or 0 for i in range(VECTOR_LENGTH - COMP_0)],
        ],
        dtype=np.float32,
    )
