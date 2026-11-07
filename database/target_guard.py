"""The local-test-database guard for the migration runner and the P11A preflight (2026-11-07).

**What it accepts.** Only a database on **this machine** whose name is `stratai_test_<suffix>`.
- The serving `stratai`, the bare `stratai_test`, any other name, Render, and every other remote host are refused.
- There is no override: a production migration is not something this repository's runner does.

**Two checks:**
1. **`check_target(url)`, before any connection.**
   - The URL must name its database explicitly, and that name must match `stratai_test_<suffix>`.
   - Every host must be the Unix socket (no host, or a socket path) or a loopback name (`localhost`, `127.0.0.1`,
     `::1`).
   - Any `hostaddr` must be loopback.
   - A missing host or database is not filled in from `PGHOST`, `PGHOSTADDR` or `PGDATABASE`: libpq would use those,
     so they are checked too, and a service file (`service=` or `PGSERVICE`) is refused because it cannot be
     inspected here.
2. **`verify_server(cursor, target)`, after connecting.**
   - The server itself must report the expected `current_database()`.
   - Its `inet_server_addr()` must be NULL (a Unix socket) or loopback.
   - This catches what a name cannot, such as a tunnel to a remote server or a hosts-file entry pointing
     `localhost` elsewhere.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SERVING_DATABASE = "stratai"
TEST_DATABASE = re.compile(r"^stratai_test_[a-z0-9]+(?:_[a-z0-9]+)*$")
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


class TargetRefused(RuntimeError):
    """The database is not an isolated local test copy. `code` is stable for tests and reports."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Target:
    hosts: tuple[str, ...]  # "" is the default Unix socket
    port: str
    dbname: str
    user: str | None

    def describe(self) -> dict[str, Any]:
        """For reports: never includes a password."""
        return {"hosts": [h or "(default socket)" for h in self.hosts], "port": self.port, "dbname": self.dbname,
                "user": self.user}


def _is_loopback_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value.strip().strip("[]")).is_loopback
    except ValueError:
        return False


def _host_is_local(host: str) -> bool:
    host = host.strip()
    return host == "" or host.startswith("/") or host.lower() in LOOPBACK_NAMES or _is_loopback_ip(host)


def check_target(url: str, environ: Mapping[str, str] | None = None) -> Target:
    """The target if it is a local `stratai_test_<suffix>` database; TargetRefused otherwise. Makes no connection."""
    from psycopg.conninfo import conninfo_to_dict

    env = os.environ if environ is None else environ
    try:
        params = conninfo_to_dict(url)
    except Exception:
        raise TargetRefused("unparseable_url", "the database URL cannot be parsed") from None
    if params.get("service") or env.get("PGSERVICE"):
        raise TargetRefused("service_file", "a libpq service (service= or PGSERVICE) cannot be verified; name the "
                                            "host and database in the URL")
    host = params.get("host") if params.get("host") is not None else env.get("PGHOST", "")
    hosts = tuple(h.strip() for h in str(host).split(",")) if host else ("",)
    for h in hosts:
        if not _host_is_local(h):
            kind = "a Render host" if "render.com" in h.lower() else "a remote host"
            raise TargetRefused("remote_host", f"{kind} is refused: only this machine's socket or loopback is allowed")
    hostaddr = params.get("hostaddr") or env.get("PGHOSTADDR")
    if hostaddr and not all(_is_loopback_ip(a) for a in str(hostaddr).split(",")):
        raise TargetRefused("remote_host", "hostaddr is not a loopback address")
    dbname = params.get("dbname")
    if not dbname:
        raise TargetRefused("database_not_named", "the URL must name its database explicitly")
    dbname = str(dbname)
    if dbname == SERVING_DATABASE:
        raise TargetRefused("serving_database", "the serving database 'stratai' is refused")
    if not TEST_DATABASE.fullmatch(dbname):
        raise TargetRefused("not_a_test_database", f"{dbname!r} is not a stratai_test_<suffix> database")
    port = str(params.get("port") or env.get("PGPORT") or "5432")
    return Target(hosts, port, dbname, params.get("user") or env.get("PGUSER"))


def verify_server(cursor: Any, target: Target) -> dict[str, Any]:
    """Ask the connected server who it is. TargetRefused unless it is the expected database, on a socket or
    loopback address."""
    cursor.execute("SELECT current_database(), inet_server_addr()::text, current_setting('server_version')")
    database, address, version = cursor.fetchone()
    if database != target.dbname:
        raise TargetRefused("server_mismatch", f"connected to {database!r}, not {target.dbname!r}")
    if address is not None and not _is_loopback_ip(str(address).split("/")[0]):
        raise TargetRefused("remote_host", "the server reports a non-loopback address")
    return {"current_database": database, "server_address": address or "unix socket", "server_version": version}


__all__ = ["SERVING_DATABASE", "TEST_DATABASE", "Target", "TargetRefused", "check_target", "verify_server"]
