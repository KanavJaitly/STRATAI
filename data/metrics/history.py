"""Match history retrieval: one team's own scores at one event.

Phase 3 Milestone 4. This is the first read path against the canonical
matches/match_teams tables that Milestone 3's pure statistics functions and
Milestone 1's ScoringProfile are built to consume -- everything here does one
job: turn a (team_number, event_key) into the plain `list[int]` of that team's
own recorded scores, plus the matches_scheduled/matches_used counts
ScoringProfile stores alongside them. It queries the database and returns
plain data; it does not compute an average, a stddev, or anything else --
that is data.metrics.statistics's job, not this module's.

Scope decision: every competition_level at the event is included (qualification
through final), not qualification matches only. The milestone asks for "one
team's match score history at one event", not a qualification-only slice, and
narrowing to quals would be inventing a restriction nobody asked for. This is
a real, documented scope decision, not an oversight: playoff matches are
alliance-selected and can behave differently from a team's standalone
qualification performance, so a future milestone may want a
competition_level-filtered variant. Not built now -- no current consumer has
asked for it.

Reliability decision: a match counts as "used" (played) exactly when this
team's own alliance score is NOT NULL. This relies on an invariant already
established and enforced elsewhere in the pipeline, not re-validated here:
score_red and score_blue are always both NULL or both set (see RUNNING_NOTES
.md's 2026-08-01 "-1 unplayed sentinel" and "one-sided sentinel" decisions,
and data/staging/normalizer.py's handling of TBA's -1 sentinel) -- so there is
no possible state where this team's own alliance has a score but the match is
otherwise unplayed, or vice versa on the other alliance's side.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from database.connection import Database

# Play order: qualification first, then the playoff bracket in bracket order,
# then chronological within a level. Identical to scripts/spot_check.py's
# print_event ordering -- one canonical "play order" convention for the whole
# codebase, not two that could quietly drift apart.
_PLAY_ORDER_SQL = """
    CASE m.competition_level
        WHEN 'qualification' THEN 0 WHEN 'eighthfinal' THEN 1
        WHEN 'quarterfinal' THEN 2 WHEN 'semifinal' THEN 3
        WHEN 'final' THEN 4 ELSE 5 END,
    m.set_number NULLS FIRST, m.match_number NULLS FIRST
"""


@dataclass(frozen=True)
class TeamMatchHistory:
    """One team's match participation and recorded scores at one event.

    matches_scheduled counts every match this team is rostered into at this
    event (match_teams rows), regardless of whether it has been played yet.
    matches_used is len(scores) -- both are carried explicitly, rather than
    leaving a caller to infer one from the other, because ScoringProfile
    stores both for exactly this reason: a team with 2 played and 8 scheduled
    matches is not the same confidence level as one with 2 played and 2
    scheduled, even though both produce a 2-score history.

    scores is in play order (see _PLAY_ORDER_SQL), which is a natural and
    reproducible ordering choice; nothing in Milestone 3's statistics
    functions is order-sensitive today, but a future consumer that wants a
    trend (e.g. "did this team improve across the event") is not something a
    per-match retrieval layer should have to be re-queried to support.
    """

    team_number: int
    event_key: str
    matches_scheduled: int
    matches_used: int
    scores: list[int] = field(default_factory=list)


def get_team_match_history(database: Database, team_number: int, event_key: str) -> TeamMatchHistory:
    """Fetch team_number's own score history at event_key.

    A team with no match_teams rows at this event (never attended, or an
    unknown team/event) returns matches_scheduled=0, matches_used=0, scores=[]
    -- the same shape a real team with a genuinely empty history would
    produce. This function does not raise or distinguish "team does not
    exist" from "team exists but wasn't at this event": both are simply
    "no data", and ScoringProfile's own matches_used == 0 invariant already
    treats that case uniformly.
    """
    with database.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT mt.alliance_color, m.score_red, m.score_blue
            FROM match_teams mt
            JOIN matches m ON m.match_key = mt.match_key
            WHERE mt.team_number = %s AND m.event_key = %s
            ORDER BY {_PLAY_ORDER_SQL}
            """,
            (team_number, event_key),
        )
        rows = cursor.fetchall()

    scores: list[int] = []
    for alliance_color, score_red, score_blue in rows:
        # alliance_color has no third value to guard against: match_teams'
        # own CHECK constraint (0005_canonical.sql) already restricts it to
        # exactly 'red'/'blue' at the database level, unlike TBA's raw
        # competition_level strings, which had no such enforced vocabulary
        # and needed active normalization (data/staging/normalizer.py).
        own_score = score_red if alliance_color == "red" else score_blue
        if own_score is not None:
            scores.append(own_score)

    return TeamMatchHistory(
        team_number=team_number,
        event_key=event_key,
        matches_scheduled=len(rows),
        matches_used=len(scores),
        scores=scores,
    )
