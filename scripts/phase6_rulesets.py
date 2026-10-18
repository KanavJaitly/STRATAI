"""P6-M1: enter, submit and review a season ruleset (human input; data/rulesets.py).

    python -m scripts.phase6_rulesets template                       # an empty skeleton to fill from the manual
    python -m scripts.phase6_rulesets draft  --file ruleset_2026.json --by "Name"
    python -m scripts.phase6_rulesets submit --id 3
    python -m scripts.phase6_rulesets review --id 3 --reviewer "Full Name" --approve \
        --qualification "<FRC-domain qualification>" --checklist review_<season>.json --sha256 <full 64-hex> [--note "..."]
    python -m scripts.phase6_rulesets review --id 3 --reviewer "Full Name" --return --note "what to fix"
    python -m scripts.phase6_rulesets list [--season 2026]

**Who does what** (review control of 2026-10-07, `.agent/phase6/decisions/P6_M1_REVIEW_CONTROL.md`):
- **Authoring:** a ruleset is submitted with a cited source for every rule.
- **Review:** a named, qualified human FRC-domain reviewer independently verifies the **stored** ruleset against the
  authoritative FIRST sources, completes R1–R15 (`P6_M1_HUMAN_INPUT_GUIDE.md` §5), and approves it. The reviewer
  may also be the author.
- **What approval needs:**
  - `--qualification` (recorded as stated);
  - `--checklist`, a JSON file with R1…R14 each `true` (R15 is the record this command writes);
  - `--sha256`, the full stored hash the reviewer verified.
  Anything missing is refused.
- **On approval** the CLI writes the write-once approval record
  `.agent/phase6/decisions/P6_M1_APPROVAL_<season>_v<version>.json`. The reviewer commits it.
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
                  "declined_team_may_become_captain": BLANK, "backup_robots": BLANK,
                  # Schema v3: `captain_rule` / `declined_team_may_become_captain` may be null ONLY when FIRST does
                  # not establish them, each with an entry here. Replace with [] when every rule is established.
                  "unresolved": [{"field": BLANK, "note": BLANK, "sources_checked": BLANK}], "citation": BLANK},
    # Schema v2 (P1, 2026-10-05). Replace with [] when every event uses the season default. Otherwise give each
    # variant a complete selection and, for every listed event, its FIRST provenance (team_update: null when none).
    "selection_variants": [{"name": BLANK, "selection": {
        "order": BLANK, "picks_per_alliance": BLANK, "captain_rule": BLANK, "captain_may_accept_higher_alliance": BLANK,
        "declined_team_may_be_picked_later": BLANK, "declined_team_may_become_captain": BLANK,
        "backup_robots": BLANK, "unresolved": [{"field": BLANK, "note": BLANK, "sources_checked": BLANK}],
        "citation": BLANK},
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
    r.add_argument("--qualification", default="", help="the reviewer's FRC-domain qualification (approval)")
    r.add_argument("--checklist", type=Path, help="JSON file: R1..R14 each true (approval)")
    r.add_argument("--sha256", default="", help="the full stored ruleset sha256 the reviewer verified (approval)")
    r.add_argument("--record-dir", type=Path, default=Path(".agent/phase6/decisions"))
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
            checklist = None
            if args.approve:
                if args.checklist is None or not args.checklist.exists():
                    raise RulesetError("review_incomplete", "approval needs --checklist (R1..R14 each true)")
                checklist = json.loads(args.checklist.read_text(encoding="utf-8"))
                record_path = _record_path(database, args.id, args.record_dir)
            row = review_ruleset(database, args.id, reviewer=args.reviewer, approve=args.approve, note=args.note,
                                 reviewer_qualification=args.qualification, checklist=checklist,
                                 verified_sha256=args.sha256)
            if args.approve:
                _write_approval_record(record_path, row)
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


def _record_path(database, ruleset_id: int, record_dir: Path) -> Path:
    """Where the approval record goes; refuses (before approving) if it already exists: records are write-once."""
    from data.rulesets import RulesetError

    with database.cursor() as cursor:
        cursor.execute("SELECT season, version FROM season_rulesets WHERE id = %s", (ruleset_id,))
        found = cursor.fetchone()
    if found is None:
        raise RulesetError("not_found", f"no ruleset version {ruleset_id}")
    path = record_dir / f"P6_M1_APPROVAL_{found[0]}_v{found[1]}.json"
    if path.exists():
        raise RulesetError("invalid_state", f"{path} exists: approval records are write-once")
    return path


def _write_approval_record(path: Path, row: dict) -> None:
    """The approval record: reviewer, qualification, date, checklist result and the full approved sha256."""
    review = json.loads(row["review_note"])
    record = {"season": row["season"], "ruleset_id": row["id"], "version": row["version"], "status": row["status"],
              "author": row["created_by"], "reviewer_name": row["reviewed_by"],
              "reviewer_qualification": review["reviewer_qualification"],
              "review_date": row["reviewed_at"].isoformat(), "checklist_result": review["checklist"],
              "approved_ruleset_sha256": row["ruleset_sha256"], "note": review["note"],
              "R15": "this write-once file, written at approval; the reviewer commits it",
              "control": ".agent/phase6/decisions/P6_M1_REVIEW_CONTROL.md"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"approval record written: {path} (commit it)")


if __name__ == "__main__":
    sys.exit(main())
