"""P5-M1 acceptance: alliance and seed data quality, computed once on real data.

    python -m scripts.phase5_m1_alliance_acceptance

Applies data.alliance_checks to every 2024-2026 event and records the frozen
criteria (docs/P5Milestones.md, P5-M1) write-once in
.agent/phase5/results/p5_m1_alliance_acceptance.json:

(a) coverage per season: events with alliances / events with playoff matches;
(b) playoff participants missing from their event's alliance picks (listed);
(c) seed-rank violations in seeded events (listed);
(d) seed-order rejections (non-empty payloads that parse to no alliances; listed).

It also re-derives the ingestion facts the frozen methodology quotes (608 payloads,
606 events, 591 seeded, 15 division-champion, 4,782 alliances, 0 backups) and states
whether each still holds. A failing criterion is a data finding, recorded as such.
"""

from __future__ import annotations

import sys
from collections import defaultdict

from data.alliance_checks import is_seeded_event, playoff_membership_exceptions, seed_rank_violations
from data.alliances import OBJECT_TYPE_EVENT_ALLIANCES, parse_alliances_payload, read_event_alliances
from data.config import Settings
from data.pipeline import SOURCE_TBA
from data.rankings import read_final_ranks_for_season
from database.connection import DatabaseConfig
from database.readonly import ReadOnlySessionDatabase
from scripts.phase5_records import write_once

SEASONS = (2024, 2025, 2026)
RECORD = "p5_m1_alliance_acceptance.json"
FROZEN_FACTS = {"payloads": 608, "events_with_alliances": 606, "seeded_events": 591,
                "division_champion_events": 15, "alliances": 4782, "alliances_with_backup": 0}


def main() -> int:
    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT rsp.source_object_id, e.season, rsp.payload_json FROM raw_source_payloads rsp "
            "JOIN events e ON e.event_key = rsp.source_object_id "
            "WHERE rsp.source = %s AND rsp.source_object_type = %s AND rsp.is_current AND e.season = ANY(%s)",
            (SOURCE_TBA, OBJECT_TYPE_EVENT_ALLIANCES, list(SEASONS)))
        payloads = cursor.fetchall()
        cursor.execute(
            "SELECT m.event_key, e.season, mt.team_number FROM matches m JOIN events e ON e.event_key = m.event_key "
            "JOIN match_teams mt ON mt.match_key = m.match_key "
            "WHERE m.competition_level <> 'qualification' AND e.season = ANY(%s)", (list(SEASONS),))
        playoff_teams: dict[str, set[int]] = defaultdict(set)
        playoff_events_by_season: dict[int, set[str]] = defaultdict(set)
        for event_key, season, team in cursor.fetchall():
            playoff_teams[event_key].add(team)
            playoff_events_by_season[season].add(event_key)

    rejections = [key for key, _, payload in payloads if isinstance(payload, list) and payload
                  and not parse_alliances_payload(payload)]
    coverage, membership, seed_rank = {}, {}, {}
    facts = defaultdict(int)
    facts["payloads"] = len(payloads)
    for season in SEASONS:
        alliances = read_event_alliances(database, season)
        ranks = read_final_ranks_for_season(database, season)
        playoff_events = playoff_events_by_season[season]
        covered = playoff_events & set(alliances)
        coverage[str(season)] = {"events_with_playoff_matches": len(playoff_events),
                                 "events_with_alliances": len(covered),
                                 "coverage": round(len(covered) / len(playoff_events), 4) if playoff_events else None,
                                 "playoff_events_without_alliances": sorted(playoff_events - set(alliances))}
        for event_key, event_alliances in sorted(alliances.items()):
            facts["events_with_alliances"] += 1
            facts["alliances"] += len(event_alliances)
            facts["alliances_with_backup"] += sum(a.backup is not None for a in event_alliances)
            seeded = is_seeded_event(event_alliances)
            facts["seeded_events" if seeded else "division_champion_events"] += 1
            missing = playoff_membership_exceptions(event_alliances, playoff_teams.get(event_key, ()))
            if missing:
                membership[event_key] = [m.team for m in missing]
            if seeded:
                if event_key not in ranks:
                    seed_rank[event_key] = [{"reason": "no_final_ranks"}]
                    continue
                violations = seed_rank_violations(event_alliances, ranks[event_key])
                if violations:
                    seed_rank[event_key] = [v.__dict__ for v in violations]
    facts = dict(facts)
    seeded_checked = facts["seeded_events"]
    result = {
        "milestone": "P5-M1", "spec": "docs/P5Milestones.md (frozen P5-M0)",
        "ingestion_facts": {"observed": facts, "frozen": FROZEN_FACTS,
                            "all_hold": all(facts.get(k) == v for k, v in FROZEN_FACTS.items())},
        "a_coverage": coverage,
        "b_membership_exceptions": {"events_with_exceptions": len(membership),
                                    "teams": sum(len(v) for v in membership.values()), "by_event": membership},
        "c_seed_rank": {"seeded_events_checked": seeded_checked, "events_with_violations": len(seed_rank),
                        "violations": sum(len(v) for v in seed_rank.values()), "by_event": seed_rank},
        "d_seed_order_rejections": {"count": len(rejections), "events": sorted(rejections)},
    }
    path = write_once(RECORD, result)
    print(f"facts hold: {result['ingestion_facts']['all_hold']}; coverage: "
          f"{ {s: c['coverage'] for s, c in coverage.items()} }; membership exceptions: "
          f"{result['b_membership_exceptions']['teams']} teams in {len(membership)} events; seed-rank: "
          f"{result['c_seed_rank']['violations']} violations in {len(seed_rank)} of {seeded_checked} events; "
          f"rejections: {len(rejections)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
