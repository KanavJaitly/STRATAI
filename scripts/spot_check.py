"""Read-only spot-check report for manually verifying stored data against TBA.

Phase 2's definition of done requires a *human* to compare what the pipeline
stored against known real results. This script exists to make that comparison
cheap: it prints canonical rows in the same shape thebluealliance.com shows
them, so discrepancies are visible by eye rather than by writing SQL.

It is strictly read-only. Every statement is a SELECT; the script opens no
transaction that writes and takes no arguments that could mutate state. It
deliberately does not compare against TBA itself and does not print a
pass/fail verdict -- an automated comparison would just be re-implementing the
pipeline's own normalization and would agree with it by construction. The point
is to put the stored numbers in front of a person who knows what the real
results were.

Usage:

    python -m scripts.spot_check --event 2024casj
    python -m scripts.spot_check --match 2024casj_qm1 --match 2024cmptx_f1m1
    python -m scripts.spot_check --team 1114 --season 2024
    python -m scripts.spot_check --preset            # a curated set to verify
    python -m scripts.spot_check --season-summary 2024

Each match line reads:

    qm1    red 129 - 118 blue   RED     red: 841, 8546, 253   blue: 4159, 2367, 604

so it lines up with TBA's match table left to right: match, scores, winner,
rosters. `--verbose` adds the raw payload id each canonical row was built from,
via canonical_lineage, so a suspicious row can be traced back to the exact
stored response body that produced it.
"""

from __future__ import annotations

import argparse
from typing import Any, Iterable, Sequence

from data.config import Settings
from database.connection import Database, DatabaseConfig

# Matches and events chosen for manual verification. These are deliberately
# *memorable* 2024 results -- a championship final, well-known teams, and the
# structural edge cases a season sync exposes -- so they can be checked against
# thebluealliance.com without trusting anything this pipeline computed.
PRESET_MATCHES = [
    # 2024 Championship (Houston) final. The single most-recorded FRC result of
    # the season, and the last event a chronological season sync loads.
    "2024cmptx_f1m1",
    "2024cmptx_f1m2",
    # Einstein-bound division finals from two divisions.
    "2024arc_f1m1",
    "2024new_f1m1",
    # The event the pipeline was originally proven on, so the season run must
    # not have changed it: qualification and a playoff match.
    "2024casj_qm1",
    "2024casj_f1m1",
    # Double elimination: 2024 replaced the old bracket with sf1-sf13, which is
    # the competition_level/set_number shape most likely to be stored wrong.
    "2024mil_sf13m1",
    # A district event, the most numerous event type in the season.
    "2024ncash_qm1",
    # A parent district championship, which holds only a handful of matches
    # because play happens in its divisions.
    "2024micmp_f1m1",
]

PRESET_EVENTS = ["2024casj", "2024cmptx", "2024micmp"]
PRESET_TEAMS = [1114, 254, 2056]


def _rows(database: Database, query: str, params: Sequence[Any] = ()) -> list[tuple]:
    with database.cursor() as cursor:
        cursor.execute(query, tuple(params))
        return cursor.fetchall()


def _roster(database: Database, match_key: str) -> dict[str, list[int]]:
    """Return {'red': [...], 'blue': [...]} for a match, in station order."""
    roster: dict[str, list[int]] = {"red": [], "blue": []}
    for color, team_number in _rows(
        database,
        """
        SELECT alliance_color, team_number FROM match_teams
        WHERE match_key = %s
        ORDER BY alliance_color, station_position NULLS LAST, team_number
        """,
        (match_key,),
    ):
        roster.setdefault(color, []).append(team_number)
    return roster


def _lineage_note(database: Database, entity_type: str, entity_key: str) -> str:
    raw_ids = _rows(
        database,
        """
        SELECT raw_payload_id FROM canonical_lineage
        WHERE entity_type = %s AND entity_key = %s ORDER BY raw_payload_id
        """,
        (entity_type, entity_key),
    )
    if not raw_ids:
        return "   [no lineage recorded]"
    return f"   [raw_source_payloads.id: {', '.join(str(r[0]) for r in raw_ids)}]"


def print_match(database: Database, match_key: str, *, verbose: bool = False) -> None:
    """Print one match the way TBA displays it: scores, winner, then rosters."""
    rows = _rows(
        database,
        """
        SELECT match_key, event_key, season, competition_level, set_number, match_number,
               score_red, score_blue, winning_alliance, scheduled_time
        FROM matches WHERE match_key = %s
        """,
        (match_key,),
    )
    if not rows:
        print(f"  {match_key:20s} NOT IN DATABASE")
        return

    (key, event_key, season, level, set_number, number,
     score_red, score_blue, winner, scheduled) = rows[0]
    roster = _roster(database, key)
    label = _match_label(level, set_number, number)
    winner_text = (winner or "none").upper()
    red = ", ".join(str(t) for t in roster["red"]) or "(empty)"
    blue = ", ".join(str(t) for t in roster["blue"]) or "(empty)"

    print(
        f"  {label:10s} red {_score(score_red)} - {_score(score_blue)} blue   "
        f"{winner_text:6s}  red: {red:26s} blue: {blue}"
    )
    if verbose:
        print(f"   {key}  event={event_key} season={season} scheduled={scheduled}")
        print(_lineage_note(database, "match", key))


def _score(value: int | None) -> str:
    return "  ?" if value is None else f"{value:3d}"


# The canonical tables store the staging layer's normalized vocabulary
# ('qualification'), not TBA's wire abbreviation ('qm'). Rendering TBA's form
# here is the whole point: a spot-check is a comparison against TBA's own
# display, so the label has to read the way TBA writes it.
_LEVEL_TO_TBA_ABBREVIATION = {
    "qualification": "qm",
    "eighthfinal": "ef",
    "quarterfinal": "qf",
    "semifinal": "sf",
    "final": "f",
}


def _match_label(level: str | None, set_number: int | None, number: int | None) -> str:
    """Render a stored match the way TBA names it: qm1, sf13m1, f1m2."""
    abbreviation = _LEVEL_TO_TBA_ABBREVIATION.get(level or "", level or "?")
    if abbreviation == "qm":
        return f"qm{number if number is not None else '?'}"
    return f"{abbreviation}{set_number if set_number is not None else '?'}m{number if number is not None else '?'}"


def print_event(database: Database, event_key: str, *, verbose: bool = False) -> None:
    """Print an event's stored header plus every match, in play order."""
    rows = _rows(
        database,
        """
        SELECT event_key, name, season, event_type, start_date, end_date, city, state_prov, country
        FROM events WHERE event_key = %s
        """,
        (event_key,),
    )
    print(f"\n=== EVENT {event_key} ===")
    if not rows:
        print("  NOT IN DATABASE")
        return

    key, name, season, event_type, start_date, end_date, city, state_prov, country = rows[0]
    location = ", ".join(part for part in (city, state_prov, country) if part) or "(no location stored)"
    print(f"  {name}   season={season}   {start_date} to {end_date}")
    print(f"  location: {location}   event_type={event_type if event_type is not None else '(not populated)'}")

    team_count = _rows(database, "SELECT count(DISTINCT team_number) FROM match_teams mt "
                                 "JOIN matches m ON m.match_key = mt.match_key WHERE m.event_key = %s",
                       (event_key,))[0][0]
    match_rows = _rows(
        database,
        """
        SELECT match_key, competition_level, set_number, match_number
        FROM matches WHERE event_key = %s
        ORDER BY CASE competition_level
                     WHEN 'qualification' THEN 0 WHEN 'eighthfinal' THEN 1
                     WHEN 'quarterfinal' THEN 2 WHEN 'semifinal' THEN 3
                     WHEN 'final' THEN 4 ELSE 5 END,
                 set_number NULLS FIRST, match_number NULLS FIRST
        """,
        (event_key,),
    )
    print(f"  stored: {len(match_rows)} match(es), {team_count} distinct team(s) on rosters")
    if verbose:
        print(_lineage_note(database, "event", key))
    print()
    for match_key, _level, _set_number, _number in match_rows:
        print_match(database, match_key, verbose=verbose)


def print_team(database: Database, team_number: int, season: int, *, verbose: bool = False) -> None:
    """Print a team's stored identity, its events that season, and its record."""
    rows = _rows(
        database,
        "SELECT team_number, name, city, state_province, country, rookie_year FROM teams WHERE team_number = %s",
        (team_number,),
    )
    print(f"\n=== TEAM {team_number} (season {season}) ===")
    if not rows:
        print("  NOT IN DATABASE")
        return

    number, name, city, state_province, country, rookie_year = rows[0]
    location = ", ".join(part for part in (city, state_province, country) if part) or "(no location stored)"
    print(f"  {name}   {location}   rookie_year={rookie_year}")

    events = _rows(
        database,
        """
        SELECT m.event_key, count(*) AS matches,
               count(*) FILTER (WHERE m.winning_alliance = mt.alliance_color) AS wins,
               count(*) FILTER (WHERE m.winning_alliance IS NOT NULL
                                AND m.winning_alliance <> mt.alliance_color) AS losses,
               count(*) FILTER (WHERE m.winning_alliance IS NULL) AS no_winner
        FROM match_teams mt JOIN matches m ON m.match_key = mt.match_key
        WHERE mt.team_number = %s AND m.season = %s
        GROUP BY m.event_key ORDER BY min(m.scheduled_time) NULLS LAST, m.event_key
        """,
        (team_number, season),
    )
    if not events:
        print(f"  no stored {season} matches")
    for event_key, matches, wins, losses, no_winner in events:
        print(f"    {event_key:12s} {matches:3d} match(es)  {wins}W-{losses}L"
              f"{f'  ({no_winner} with no winner stored)' if no_winner else ''}")

    stats = _rows(
        database,
        """
        SELECT event_key, epa_total, epa_auto, epa_teleop, epa_endgame, wins, losses, ties, matches_played
        FROM team_event_stats WHERE team_number = %s AND season = %s ORDER BY event_key
        """,
        (team_number, season),
    )
    if stats:
        print("  team_event_stats (Statbotics):")
        for row in stats:
            print(f"    {row[0]:12s} epa_total={row[1]} auto={row[2]} teleop={row[3]} "
                  f"endgame={row[4]} {row[5]}W-{row[6]}L-{row[7]}T played={row[8]}")
    else:
        print("  team_event_stats: none stored (Statbotics is a known open item)")
    if verbose:
        print(_lineage_note(database, "team", str(team_number)))


def print_season_summary(database: Database, season: int) -> None:
    """Print season-wide stored totals, plus the shape checks worth eyeballing."""
    print(f"\n=== SEASON {season} STORED TOTALS ===")
    for label, query in (
        ("events", "SELECT count(*) FROM events WHERE season = %s"),
        ("matches", "SELECT count(*) FROM matches WHERE season = %s"),
        ("match_teams", "SELECT count(*) FROM match_teams mt JOIN matches m "
                        "ON m.match_key = mt.match_key WHERE m.season = %s"),
        ("distinct teams on rosters", "SELECT count(DISTINCT mt.team_number) FROM match_teams mt "
                                      "JOIN matches m ON m.match_key = mt.match_key WHERE m.season = %s"),
        ("team_event_stats", "SELECT count(*) FROM team_event_stats WHERE season = %s"),
    ):
        print(f"  {label:26s} {_rows(database, query, (season,))[0][0]}")

    print("\n  matches by competition_level:")
    for level, count in _rows(
        database,
        "SELECT competition_level, count(*) FROM matches WHERE season = %s GROUP BY 1 ORDER BY 2 DESC",
        (season,),
    ):
        print(f"    {str(level):6s} {count}")

    print("\n  events by stored event_type:")
    for event_type, count in _rows(
        database,
        "SELECT event_type, count(*) FROM events WHERE season = %s GROUP BY 1 ORDER BY 2 DESC",
        (season,),
    ):
        print(f"    {str(event_type) if event_type is not None else '(not populated)':22s} {count}")

    # Shape checks. These are read-only observations, not assertions: an
    # unplayed match legitimately has no score, so a nonzero count here is
    # something for a human to interpret rather than a failure.
    print("\n  shape observations (for interpretation, not pass/fail):")
    for label, query in (
        ("matches with no score", "SELECT count(*) FROM matches WHERE season = %s "
                                  "AND (score_red IS NULL OR score_blue IS NULL)"),
        ("matches with no winner", "SELECT count(*) FROM matches WHERE season = %s AND winning_alliance IS NULL"),
        ("matches whose roster is not 6", "SELECT count(*) FROM (SELECT m.match_key FROM matches m "
                                          "LEFT JOIN match_teams mt ON mt.match_key = m.match_key "
                                          "WHERE m.season = %s GROUP BY m.match_key HAVING count(mt.id) <> 6) s"),
        ("matches with an empty roster", "SELECT count(*) FROM matches m WHERE m.season = %s AND NOT EXISTS "
                                         "(SELECT 1 FROM match_teams mt WHERE mt.match_key = m.match_key)"),
        ("winner disagrees with scores", "SELECT count(*) FROM matches WHERE season = %s "
                                         "AND score_red IS NOT NULL AND score_blue IS NOT NULL "
                                         "AND winning_alliance IN ('red','blue') AND ("
                                         "(winning_alliance = 'red' AND score_red < score_blue) OR "
                                         "(winning_alliance = 'blue' AND score_blue < score_red))"),
    ):
        print(f"    {label:32s} {_rows(database, query, (season,))[0][0]}")


def print_preset(database: Database, *, verbose: bool = False) -> None:
    """Print the curated set of well-known 2024 results for manual comparison."""
    print("\n" + "=" * 78)
    print("CURATED 2024 RESULTS FOR MANUAL VERIFICATION")
    print("Compare each line against thebluealliance.com. Nothing here is checked")
    print("automatically -- the pipeline must not be allowed to grade its own work.")
    print("=" * 78)
    print("\n--- Known matches ---")
    for match_key in PRESET_MATCHES:
        print(f"\n  https://www.thebluealliance.com/match/{match_key}")
        print_match(database, match_key, verbose=verbose)
    for event_key in PRESET_EVENTS:
        print(f"\n  https://www.thebluealliance.com/event/{event_key}")
        print_event(database, event_key, verbose=verbose)
    for team_number in PRESET_TEAMS:
        print(f"\n  https://www.thebluealliance.com/team/{team_number}/2024")
        print_team(database, team_number, 2024, verbose=verbose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only report of stored StratAI data, for manual comparison against TBA.",
    )
    parser.add_argument("--event", action="append", default=[], metavar="EVENT_KEY",
                        help="Print an event header and all its matches. Repeatable.")
    parser.add_argument("--match", action="append", default=[], metavar="MATCH_KEY",
                        help="Print one match. Repeatable.")
    parser.add_argument("--team", action="append", default=[], type=int, metavar="TEAM_NUMBER",
                        help="Print a team's identity and per-event record. Repeatable.")
    parser.add_argument("--season", type=int, default=2024,
                        help="Season used by --team and --season-summary (default 2024).")
    parser.add_argument("--season-summary", type=int, metavar="YEAR",
                        help="Print season-wide stored totals and shape observations.")
    parser.add_argument("--preset", action="store_true",
                        help="Print a curated set of well-known 2024 results to verify.")
    parser.add_argument("--verbose", action="store_true",
                        help="Also print raw_source_payloads lineage for each row.")
    args = parser.parse_args(argv)

    if not any((args.event, args.match, args.team, args.season_summary, args.preset)):
        parser.error("nothing to report: pass --preset, --event, --match, --team, or --season-summary")

    database = Database(DatabaseConfig(Settings().database_url))

    if args.season_summary is not None:
        print_season_summary(database, args.season_summary)
    if args.preset:
        print_preset(database, verbose=args.verbose)
    for match_key in args.match:
        print(f"\n  https://www.thebluealliance.com/match/{match_key}")
        print_match(database, match_key, verbose=args.verbose)
    for event_key in args.event:
        print_event(database, event_key, verbose=args.verbose)
    for team_number in args.team:
        print_team(database, team_number, args.season, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
