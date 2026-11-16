"""Set a member's role by hand: promote someone to admin, or make them a base member.

    python -m scripts.set_role someone@example.com admin
    python -m scripts.set_role someone@example.com base

The person must have signed up already. This also reactivates a suspended or removed member, which is how someone
removed from the team gets back in (their email stays taken, so they cannot sign up again). Demoting the last active
administrator is refused. The change is recorded in the team's activity log as done from the command line, and takes
effect on the person's next request.

Uses DATABASE_URL from the environment or .env, like every other script here. On Render, run it from the API
service's Shell.
"""

from __future__ import annotations

import argparse
import json
import sys

from data.config import Settings
from database.connection import Database, DatabaseConfig
from workspaces.errors import WorkspaceError
from workspaces.management import set_role_by_email
from workspaces.permissions import ROLES


def main(argv: list[str] | None = None, database: Database | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email", help="the member's email (any case)")
    parser.add_argument("role", choices=ROLES)
    args = parser.parse_args(argv)
    database = database or Database(DatabaseConfig(Settings().database_url))
    try:
        result = set_role_by_email(database, args.email, args.role)
    except WorkspaceError as refused:
        print(f"refused ({refused.code}): {refused.message}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
