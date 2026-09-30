"""Synthetic TBA-shaped inputs for the EPA engine tests. Nothing here is real data.

Breakdown builders produce raw TBA score_breakdown dicts with exactly the
fields each season's adapter requires, and compute the alliance score the way
TBA totals it (components + foulPoints + adjustPoints), so a built alliance is
internally consistent unless a test deliberately makes it otherwise.
"""

from __future__ import annotations

import random
from typing import Any

from ml.ratings.epa.inputs import AllianceInput, EventInput, MatchInput, SeasonInput

BASE_TIME = 1_710_000_000


def bd2024(
    *, leave: int = 0, auto_amp: int = 0, auto_speaker: int = 0, teleop_amp: int = 0,
    teleop_speaker: int = 0, amplified: int = 0, park: int = 0, on_stage: int = 0,
    harmony: int = 0, trap: int = 0, spotlight: int = 0, melody: bool = False,
    ensemble: bool = False, coop: bool = False, foul: int = 0, adjust: int = 0,
) -> dict[str, Any]:
    return {
        "autoLeavePoints": leave, "autoAmpNoteCount": auto_amp, "autoSpeakerNoteCount": auto_speaker,
        "teleopAmpNoteCount": teleop_amp, "teleopSpeakerNoteCount": teleop_speaker,
        "teleopSpeakerNoteAmplifiedCount": amplified, "endGameParkPoints": park,
        "endGameOnStagePoints": on_stage, "endGameHarmonyPoints": harmony,
        "endGameNoteInTrapPoints": trap, "endGameSpotLightBonusPoints": spotlight,
        "melodyBonusAchieved": melody, "ensembleBonusAchieved": ensemble,
        "coopertitionBonusAchieved": coop, "foulPoints": foul, "adjustPoints": adjust,
    }


def score2024(bd: dict[str, Any]) -> int:
    auto = bd["autoLeavePoints"] + 2 * bd["autoAmpNoteCount"] + 5 * bd["autoSpeakerNoteCount"]
    amplified = bd["teleopSpeakerNoteAmplifiedCount"]
    teleop = bd["teleopAmpNoteCount"] + 2 * (bd["teleopSpeakerNoteCount"] + amplified) + 3 * amplified
    endgame = (bd["endGameParkPoints"] + bd["endGameOnStagePoints"] + bd["endGameHarmonyPoints"]
               + bd["endGameNoteInTrapPoints"] + bd["endGameSpotLightBonusPoints"])
    return auto + teleop + endgame + bd["foulPoints"] + bd["adjustPoints"]


def bd2025(
    *, mobility: int = 0, auto_coral_points: int = 0, teleop_coral_points: int = 0,
    auto_rows: tuple[int, int, int, int] = (0, 0, 0, 0), teleop_rows: tuple[int, int, int, int] = (0, 0, 0, 0),
    processor: int = 0, net: int = 0, barge: int = 0, auto_rp: bool = False, coral_rp: bool = False,
    barge_rp: bool = False, foul: int = 0, adjust: int = 0,
) -> dict[str, Any]:
    """rows are (top, mid, bot, trough)."""

    def reef(rows: tuple[int, int, int, int]) -> dict[str, int]:
        return {"tba_topRowCount": rows[0], "tba_midRowCount": rows[1], "tba_botRowCount": rows[2], "trough": rows[3]}

    return {
        "autoMobilityPoints": mobility, "autoCoralPoints": auto_coral_points,
        "teleopCoralPoints": teleop_coral_points, "autoReef": reef(auto_rows), "teleopReef": reef(teleop_rows),
        "wallAlgaeCount": processor, "netAlgaeCount": net, "endGameBargePoints": barge,
        "autoBonusAchieved": auto_rp, "coralBonusAchieved": coral_rp, "bargeBonusAchieved": barge_rp,
        "coopertitionCriteriaMet": False, "foulPoints": foul, "adjustPoints": adjust,
    }


def score2025(bd: dict[str, Any]) -> int:
    return (bd["autoMobilityPoints"] + bd["autoCoralPoints"] + bd["teleopCoralPoints"]
            + 6 * bd["wallAlgaeCount"] + 4 * bd["netAlgaeCount"] + bd["endGameBargePoints"]
            + bd["foulPoints"] + bd["adjustPoints"])


def bd2026(
    *, auto_fuel: int = 0, transition: int = 0, shifts: tuple[int, int, int, int] = (0, 0, 0, 0),
    endgame_fuel: int = 0, auto_tower: int = 0, endgame_tower: int = 0, energized: bool = False,
    supercharged: bool = False, traversal: bool = False, foul: int = 0, adjust: int = 0,
) -> dict[str, Any]:
    return {
        "hubScore": {
            "autoPoints": auto_fuel, "endgamePoints": endgame_fuel, "transitionPoints": transition,
            "shift1Points": shifts[0], "shift2Points": shifts[1], "shift3Points": shifts[2], "shift4Points": shifts[3],
        },
        "autoTowerPoints": auto_tower, "endGameTowerPoints": endgame_tower, "energizedAchieved": energized,
        "superchargedAchieved": supercharged, "traversalAchieved": traversal, "foulPoints": foul,
        "adjustPoints": adjust,
    }


def score2026(bd: dict[str, Any]) -> int:
    hub = bd["hubScore"]
    return (sum(hub.values()) + bd["autoTowerPoints"] + bd["endGameTowerPoints"]
            + bd["foulPoints"] + bd["adjustPoints"])


SCORERS = {2024: score2024, 2025: score2025, 2026: score2026}


def alliance(season: int, teams: tuple[int, ...], bd: dict[str, Any] | None, *, score: int | None = None,
             dq: tuple[int, ...] = (), surrogates: tuple[int, ...] = ()) -> AllianceInput:
    if score is None and bd is not None:
        score = SCORERS[season](bd)
    return AllianceInput(teams=teams, dq_teams=dq, surrogate_teams=surrogates, score=score, breakdown=bd)


def event(key: str, *, event_type: int = 0, week: int | None = 0, district: str | None = None) -> EventInput:
    return EventInput(event_key=key, event_type=event_type, week=week, district=district)


def match(key: str, event_key: str, time: int | None, red: AllianceInput, blue: AllianceInput, *,
          level: str = "qm", set_number: int = 1, number: int = 1) -> MatchInput:
    return MatchInput(match_key=key, event_key=event_key, comp_level=level, set_number=set_number,  # type: ignore[arg-type]
                      match_number=number, time=time, red=red, blue=blue)


def random_bd(season: int, rng: random.Random) -> dict[str, Any]:
    if season == 2024:
        return bd2024(leave=rng.choice([0, 2, 4, 6]), auto_speaker=rng.randint(0, 4), auto_amp=rng.randint(0, 1),
                      teleop_speaker=rng.randint(2, 14), teleop_amp=rng.randint(0, 5), amplified=rng.randint(0, 4),
                      park=rng.randint(0, 2), on_stage=rng.choice([0, 3, 6, 9]), harmony=rng.choice([0, 0, 2]),
                      trap=rng.choice([0, 0, 5]), melody=rng.random() < 0.3, ensemble=rng.random() < 0.25,
                      coop=rng.random() < 0.2, foul=rng.choice([0, 0, 0, 2, 5]))
    if season == 2025:
        return bd2025(mobility=rng.choice([0, 3, 6, 9]), auto_coral_points=rng.randint(0, 20),
                      teleop_coral_points=rng.randint(5, 50), auto_rows=(rng.randint(0, 2), 0, 0, rng.randint(0, 1)),
                      teleop_rows=(rng.randint(2, 6), rng.randint(0, 4), rng.randint(0, 4), rng.randint(0, 6)),
                      processor=rng.randint(0, 4), net=rng.randint(0, 4), barge=rng.choice([0, 2, 6, 12, 14]),
                      auto_rp=rng.random() < 0.3, coral_rp=rng.random() < 0.2, barge_rp=rng.random() < 0.3,
                      foul=rng.choice([0, 0, 0, 2, 6]))
    return bd2026(auto_fuel=rng.randint(0, 20), transition=rng.randint(0, 10),
                  shifts=tuple(rng.randint(0, 15) for _ in range(4)), endgame_fuel=rng.randint(0, 10),  # type: ignore[arg-type]
                  auto_tower=rng.choice([0, 15]), endgame_tower=rng.choice([0, 10, 20, 30]),
                  energized=rng.random() < 0.3, supercharged=rng.random() < 0.1, traversal=rng.random() < 0.3,
                  foul=rng.choice([0, 0, 0, 3]))


def random_season(season: int = 2024, *, seed: int = 7, teams: int = 18, events: int = 3,
                  quals_per_event: int = 12, elims_per_event: int = 3) -> SeasonInput:
    """A small multi-event season: event i is TBA week i (adjusted week i + 1).

    Week-1 is event 0. Each event's matches are spaced 10 minutes apart and
    events are a week apart, so the order is unambiguous; elims come last.
    """
    rng = random.Random(seed)
    team_pool = list(range(100, 100 + teams))
    event_inputs, match_inputs = [], []
    for e in range(events):
        key = f"{season}ev{e}"
        event_inputs.append(event(key, event_type=0, week=e))
        start = BASE_TIME + e * 7 * 86400
        for q in range(quals_per_event + elims_per_event):
            picked = rng.sample(team_pool, 6)
            level = "qm" if q < quals_per_event else "sf"
            match_inputs.append(match(
                f"{key}_{level}{q + 1}", key, start + q * 600,
                alliance(season, tuple(picked[:3]), random_bd(season, rng)),
                alliance(season, tuple(picked[3:]), random_bd(season, rng)),
                level=level, number=q + 1,
            ))
    return SeasonInput(season=season, events=tuple(event_inputs), matches=tuple(match_inputs))
