"""P11A §14: export an event snapshot, and compute the plan or a team profile from one offline.

    python -m scripts.p11a_snapshot export --event 2026njfla --as-of 2026-03-15T17:30:00Z --out DIR
    python -m scripts.p11a_snapshot plan --snapshot FILE --log LOG.json --team 1234 [--out PLAN.json]
    python -m scripts.p11a_snapshot profile --snapshot FILE --team 254 [--our-team 1234]

**export** reads the project database named by DATABASE_URL:
- through one REPEATABLE READ, READ ONLY transaction (`database.connection.read_snapshot`), so it cannot write;
- it prints the destination it reads (host, port and database name, never the password) before reading;
- it makes no external API call;
- it writes `<DIR>/<event>__<as_of>__<id>.json`, the name the server's P11A_SNAPSHOT_DIR lookup expects;
- it is UNVERIFIED against a real database on the build machine (no PostgreSQL there).

**plan** and **profile** need nothing but local files:
- the snapshot embeds the scoring configuration and GameSpec;
- the draft state is a JSON list of draft log entries
  (`[{"action_id", "seq", "type", "payload", "override_reason"}, ...]`), replayed with the Phase 11 rules
  (`workspaces.draft_log.replay`);
- they open no socket, which tests/test_p11a_offline.py checks with the network denied at the OS level;
- their output passes through the same response types as the API (`ml.alliance.contract`), so the labels are enforced
  offline too;
- the scoring configuration must be the registered approved one (`--scoring-dir`, default data/season_scoring).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.alliance.contract import P11APlanOut, P11AProfileOut
from ml.alliance.planner import PlanWithheld, build_plan
from ml.alliance.profile import team_profile
from ml.alliance.snapshot import EventSnapshot, SnapshotError, snapshot_filename


def _log(path: Path) -> list[Any]:
    from workspaces.draft_log import LogEntry

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("the draft log must be a JSON list of entries")
    return [LogEntry(str(e["action_id"]), int(e["seq"]), str(e["type"]), dict(e.get("payload") or {}),
                     e.get("override_reason"), str(e.get("author_label") or "offline")) for e in data]


def _dir(args: argparse.Namespace) -> Path | None:
    return Path(args.scoring_dir) if args.scoring_dir else None


def _emit(result: dict[str, Any], out: str | None) -> None:
    text = json.dumps(result, indent=1, default=str, sort_keys=True)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def _plan(args: argparse.Namespace) -> int:
    from workspaces import draft_log
    from workspaces.alliance_plan import RELATION, SOURCE, position_from_view

    snap = EventSnapshot.load(Path(args.snapshot))
    view = draft_log.replay(_log(Path(args.log)))
    result: dict[str, Any] = {"source": SOURCE, "experimental": True, "relation_to_recommendations": RELATION,
                              "record_seq": view.record_seq, "mode": "offline", "status": "withheld",
                              "withheld": None, "plan": None}
    try:
        plan = build_plan(snap, position_from_view(view, args.team), scoring_dir=_dir(args))
        result["plan"] = P11APlanOut.model_validate(plan).model_dump(mode="json")  # the API's contract, enforced
        result["status"] = "current"
    except PlanWithheld as exc:
        result["withheld"] = {"code": exc.code, "message": exc.message}
    _emit(result, args.out)
    return 0


def _profile(args: argparse.Namespace) -> int:
    snap = EventSnapshot.load(Path(args.snapshot))
    try:
        profile = team_profile(snap, args.team, our_team=args.our_team, scoring_dir=_dir(args))
        result = {"status": "current", "profile": P11AProfileOut.model_validate(profile).model_dump(mode="json")}
    except PlanWithheld as exc:
        result = {"status": "withheld", "withheld": {"code": exc.code, "message": exc.message}, "profile": None}
    _emit(result, args.out)
    return 0


def _destination(url: str) -> str:
    from psycopg.conninfo import conninfo_to_dict

    parts = conninfo_to_dict(url)
    return f"{parts.get('host', 'localhost')}:{parts.get('port', '5432')}/{parts.get('dbname', '?')}"


def _export(args: argparse.Namespace) -> int:
    from data.config import Settings
    from database.connection import Database, DatabaseConfig, read_snapshot
    from ml.alliance.snapshot import build_event_snapshot

    settings = Settings()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if as_of.tzinfo is None:
        raise SystemExit("--as-of needs a time zone (for example 2026-03-15T17:30:00Z)")
    print(f"reading (read-only transaction) from {_destination(str(settings.database_url))}", file=sys.stderr)
    with read_snapshot(Database(DatabaseConfig(settings.database_url))) as database:
        snap = build_event_snapshot(database, args.event, as_of.astimezone(timezone.utc))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / snapshot_filename(snap)
    sid = snap.save(path)
    print(json.dumps({"path": str(path), "snapshot_id": sid, "qual_rows": len(snap.qual_rows),
                      "teams": len(snap.teams()), "scoring_config": snap.scoring_config is not None,
                      "game_spec": snap.game_spec is not None, "exclusions": len(snap.exclusions)}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.p11a_snapshot", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="build an event snapshot from the project database (read-only)")
    export.add_argument("--event", required=True)
    export.add_argument("--as-of", required=True, help="ISO time with zone; only data before it is included")
    export.add_argument("--out", required=True, help="snapshot folder (P11A_SNAPSHOT_DIR)")
    plan = sub.add_parser("plan", help="the plan for a team from a snapshot and a draft log, offline")
    plan.add_argument("--snapshot", required=True)
    plan.add_argument("--log", required=True)
    plan.add_argument("--team", required=True, type=int)
    plan.add_argument("--out")
    plan.add_argument("--scoring-dir", help="the scoring registry (default data/season_scoring, the trust root)")
    profile = sub.add_parser("profile", help="a team's profile from a snapshot, offline")
    profile.add_argument("--snapshot", required=True)
    profile.add_argument("--team", required=True, type=int)
    profile.add_argument("--our-team", type=int)
    profile.add_argument("--out")
    profile.add_argument("--scoring-dir", help="the scoring registry (default data/season_scoring, the trust root)")
    args = parser.parse_args(argv)
    try:
        return {"export": _export, "plan": _plan, "profile": _profile}[args.command](args)
    except SnapshotError as exc:
        print(f"snapshot refused: {exc.code}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
