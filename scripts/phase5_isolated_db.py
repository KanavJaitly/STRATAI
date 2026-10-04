"""Clone the serving database into an isolated, non-serving copy (Phase 5).

    python -m scripts.phase5_isolated_db --name stratai_test [--replace]
    python -m scripts.phase5_isolated_db --name stratai_test --print-url-env   # for DATABASE_URL=... (not echoed)

Phase 5 rule (docs/P5Milestones.md, standing rules; docs/ml_models.md §9 limitation 6):
tests and replays never run against a serving database. This makes a full copy
(``CREATE DATABASE <name> TEMPLATE <serving>``) on the same server, so a test suite
or the P5-M6 replay can write sentinel and replayed rows without touching what
the API serves. It refuses to use the serving database's own name, and refuses
to replace a database unless --replace is given. Credentials are never printed.
"""

from __future__ import annotations

import argparse
import re
import sys
from urllib.parse import urlparse, urlunparse

import psycopg
from psycopg import sql

from data.config import Settings

_NAME = re.compile(r"^stratai_[a-z0-9_]+$")


def isolated_url(serving_url: str, name: str) -> str:
    """The serving URL with its database name replaced."""
    parsed = urlparse(serving_url)
    return urlunparse(parsed._replace(path=f"/{name}"))


def serving_name(serving_url: str) -> str:
    return urlparse(serving_url).path.lstrip("/")


def clone(name: str, *, replace: bool = False) -> None:
    """CREATE DATABASE name TEMPLATE <serving database>, refusing the serving name itself."""
    url = str(Settings().database_url)
    source = serving_name(url)
    if not _NAME.match(name) or name == source:
        raise SystemExit(f"refusing database name {name!r}: must match stratai_<suffix> and differ from {source!r}")
    with psycopg.connect(isolated_url(url, "postgres"), autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if exists and not replace:
            raise SystemExit(f"{name} exists; pass --replace to recreate it")
        if exists:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        busy = admin.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (source,)).fetchone()[0]
        if busy:
            raise SystemExit(f"{source} has {busy} open connection(s); a template copy needs none")
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(name), sql.Identifier(source)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--print-url-env", action="store_true", help="print the isolated URL for a shell variable")
    args = parser.parse_args(argv)
    if args.print_url_env:
        if args.name == serving_name(str(Settings().database_url)):
            raise SystemExit("refusing to print the serving database's URL")
        sys.stdout.write(isolated_url(str(Settings().database_url), args.name))
        return 0
    clone(args.name, replace=args.replace)
    print(f"cloned the serving database into {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
