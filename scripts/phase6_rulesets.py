"""P6-M1: enter, submit and review a season ruleset (human input; data/rulesets.py).

    python -m scripts.phase6_rulesets template                       # an empty skeleton to fill from the manual
    python -m scripts.phase6_rulesets draft  --file ruleset_2026.json --by "Name"
    python -m scripts.phase6_rulesets submit --id 3
    python -m scripts.phase6_rulesets review --id 3 --reviewer "Other Name" --approve [--note "..."]
    python -m scripts.phase6_rulesets review --id 3 --reviewer "Other Name" --return --note "what to fix"
    python -m scripts.phase6_rulesets list [--season 2026]

**Who does what:**
- A person enters the ruleset from the official game manual, citing a section for every rule.
- A different named person reviews it against the manual.
- A Claude-prepared research draft (`.agent/phase6/rulesets_research/`, Kanav's workflow of 2026-10-05) is input
  to that person's verification, never a substitute for it. The template itself supplies no values.

**Where it is stored:** the database `DATABASE_URL` names, which needs migration 0011. Applying 0011 to the serving
database is a production step that needs Kanav's explicit approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Every value is an empty-string placeholder. The schema rejects "" for every field (integers, booleans, the fixed
# vocabularies, `max_teams`, citations and free text), so a fresh template fails validation until a person replaces
# every value. The template supplies no rule value of its own (P6-M1 template safety, 2026-10-05).
BLANK = ""
SKELETON = {
    "season": BLANK, "game_name": BLANK, "manual": {"title": BLANK, "version": BLANK},
    "alliance_counts": [{"min_teams": BLANK, "max_teams": BLANK, "alliances": BLANK, "citation": BLANK}],
    "selection": {"order": BLANK, "picks_per_alliance": BLANK, "captain_rule": BLANK,
                  "captain_may_accept_higher_alliance": BLANK, "declined_team_may_be_picked_later": BLANK,
                  "declined_team_may_become_captain": BLANK, "backup_robots": BLANK, "citation": BLANK},
    # Schema v2 (P1, 2026-10-05). Replace with [] when every event uses the season default. Otherwise give each
    # variant a complete selection and, for every listed event, its FIRST provenance (team_update: null when none).
    "selection_variants": [{"name": BLANK, "selection": {
        "order": BLANK, "picks_per_alliance": BLANK, "captain_rule": BLANK, "captain_may_accept_higher_alliance": BLANK,
        "declined_team_may_be_picked_later": BLANK, "declined_team_may_become_captain": BLANK,
        "backup_robots": BLANK, "citation": BLANK},
        "events": [{"event_key": BLANK, "rule": BLANK, "document": BLANK, "version": BLANK, "team_update": BLANK,
                    "section": BLANK, "url": BLANK}]}],
    # Events whose recorded behaviour no FIRST document explains; [] when there are none.
    "event_exclusions": [{"event_key": BLANK, "reason": BLANK, "finding": BLANK}],
    "brackets": [{"alliances": BLANK, "slots": [
        {"slot": BLANK, "competition_level": BLANK, "set_number": BLANK, "round": BLANK,
         "red": {"kind": BLANK, "seed": BLANK}, "blue": {"kind": BLANK, "slot": BLANK}, "citation": BLANK}],
        "finals": {"competition_level": BLANK, "set_number": BLANK, "round": BLANK, "wins_needed": BLANK,
                   "red": {"kind": BLANK, "slot": BLANK}, "blue": {"kind": BLANK, "slot": BLANK},
                   "citation": BLANK}}],
    "tie_rule": BLANK,
}


def main(argv: list[str] | None = None) -> int:
    from data.config import Settings
    from data.rulesets import (RulesetError, list_rulesets, review_ruleset, save_ruleset_draft, submit_ruleset)
    from database.connection import Database, DatabaseConfig

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("template")
    d = sub.add_parser("draft")
    d.add_argument("--file", type=Path, required=True)
    d.add_argument("--by", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--id", type=int, required=True)
    r = sub.add_parser("review")
    r.add_argument("--id", type=int, required=True)
    r.add_argument("--reviewer", required=True)
    group = r.add_mutually_exclusive_group(required=True)
    group.add_argument("--approve", action="store_true")
    group.add_argument("--return", dest="return_", action="store_true")
    r.add_argument("--note", default="")
    lst = sub.add_parser("list")
    lst.add_argument("--season", type=int)
    args = parser.parse_args(argv)

    if args.command == "template":
        print(json.dumps(SKELETON, indent=1))
        return 0
    database = Database(DatabaseConfig(Settings().database_url))
    try:
        if args.command == "draft":
            row = save_ruleset_draft(database, json.loads(args.file.read_text(encoding="utf-8")), created_by=args.by)
        elif args.command == "submit":
            row = submit_ruleset(database, args.id)
        elif args.command == "review":
            row = review_ruleset(database, args.id, reviewer=args.reviewer, approve=args.approve, note=args.note)
        else:
            for row in list_rulesets(database, args.season):
                print(row["id"], row["season"], f"v{row['version']}", row["status"], row["created_by"],
                      row["reviewed_by"] or "-", row["ruleset_sha256"][:12])
            return 0
    except RulesetError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        for detail in exc.details or []:
            print(f"  {detail}", file=sys.stderr)
        return 1
    print(row["id"], row["season"], f"v{row['version']}", row["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
