"""The StratAI operator's tool for team ownership verification (docs/team_workspaces.md section 3).

    python -m scripts.workspace_operator list [--status pending_verification]
    python -m scripts.workspace_operator verify --team 1676 --operator "Your Name" --note "how ownership was checked"
    python -m scripts.workspace_operator reject --team 1676 --operator "Your Name" --note "why"

A team number and name are public, so a new workspace stays pending_verification until an operator confirms, out of
band, that its registrant speaks for the team (section 3 lists acceptable checks). Until then the workspace can
configure itself but cannot invite members or hold scouting. The verdict, the operator's name and the note are
recorded in the workspace and in its activity log. Rejecting ends every session in the workspace and frees the team
number for the real team.

This is a command-line tool on purpose: no HTTP route can verify a team, so no web credential can either.
Uses DATABASE_URL from the environment or .env, like every other script here.
"""

from __future__ import annotations

import argparse
import json
import sys

from data.config import Settings
from database.connection import Database, DatabaseConfig
from workspaces.errors import WorkspaceError
from workspaces.management import list_workspaces, operator_decide


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list workspaces")
    listing.add_argument("--status", choices=("pending_verification", "verified", "rejected"))
    for name in ("verify", "reject"):
        decide = commands.add_parser(name, help=f"{name} a team's workspace")
        decide.add_argument("--team", type=int, required=True)
        decide.add_argument("--operator", required=True, help="your name, as recorded")
        decide.add_argument("--note", required=True, help="how ownership was checked, or why it was rejected")
    args = parser.parse_args(argv)
    database = Database(DatabaseConfig(Settings().database_url))
    try:
        if args.command == "list":
            for row in list_workspaces(database, args.status):
                print(json.dumps(row, default=str))
            return 0
        result = operator_decide(database, team_number=args.team,
                                 decision="verified" if args.command == "verify" else "rejected",
                                 operator=args.operator, note=args.note)
    except WorkspaceError as refused:
        print(f"refused ({refused.code}): {refused.message}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
