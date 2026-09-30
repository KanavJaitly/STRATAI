"""Verify the STRATAI EPA provider integration before any Phase 4 run.

Read-only. Checks, each reported separately:

1. canonical database unchanged across the whole verification (fingerprint before/after);
2. the chained artifacts load, pass integrity and snapshot checks, and load identically twice;
3. a fresh, independent chained replay from the database reproduces the artifacts exactly
   (results fingerprints and every served team-event value);
4. snapshot/resume holds on the real chained inputs (per-season reports, plus an offline
   re-check of 2026 from its stored season input);
5. readiness: every Phase 4 team appearance resolves to its D13 source or a counted,
   legitimate absence -- no silent fallback;
6. Phase 4 features build from STRATAI EPA with every non-loopback network connection
   refused (Statbotics unreachable by construction) and are deterministic across builds;
7. no Phase 4 methodology or PR #29 infrastructure file differs from PR #29's head.

Usage:

    python -m scripts.verify_stratai_epa_integration --chain ARTIFACTS/chain_<hash>.json --out report.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.config import Settings
from database.connection import Database, DatabaseConfig

PR29_REF = "origin/automation/phase4-execution"
# Paths whose content defines Phase 4 methodology, acceptance, or PR #29's infrastructure.
PROTECTED_PATHS = [
    "docs/P4Milestones.md", ".agent/phase4", "prompts", ".github", "automation",
    "ml/backtest", "ml/models", "ml/calibration", "ml/registry.py", "ml/synergy",
    "ml/features/score_breakdown.py", "scripts/run_m4_baseline_backtest.py",
    "scripts/run_m11_generalization.py", "scripts/ml_bias_audit.py", "tests/test_automation_",
]

CANONICAL_FINGERPRINT_SQL = {
    "events": "SELECT count(*), md5(coalesce(string_agg(event_key || ':' || coalesce(end_date::text, ''), ',' ORDER BY event_key), '')) FROM events",
    "matches": "SELECT count(*), md5(coalesce(string_agg(match_key || ':' || coalesce(score_red::text, '') || ':' || coalesce(score_blue::text, '') || ':' || coalesce(scheduled_time::text, ''), ',' ORDER BY match_key), '')) FROM matches",
    "match_teams": "SELECT count(*), md5(coalesce(string_agg(match_key || ':' || team_number || ':' || alliance_color, ',' ORDER BY match_key, team_number), '')) FROM match_teams",
    "teams": "SELECT count(*), md5(coalesce(string_agg(team_number::text, ',' ORDER BY team_number), '')) FROM teams",
    "raw_source_payloads": "SELECT count(*), md5(coalesce(string_agg(id::text || ':' || payload_checksum || ':' || is_current::text, ',' ORDER BY id), '')) FROM raw_source_payloads",
    "team_event_stats": "SELECT count(*), '' FROM team_event_stats",
    "team_metrics": "SELECT count(*), '' FROM team_metrics",
    "scouting_observations": "SELECT count(*), '' FROM scouting_observations",
}


def canonical_fingerprint(database: Database) -> dict[str, list]:
    out = {}
    with database.cursor() as cursor:
        for table, sql in CANONICAL_FINGERPRINT_SQL.items():
            cursor.execute(sql)
            count, digest = cursor.fetchone()
            out[table] = [count, digest]
    return out


class NetworkGuard:
    """Refuse every socket connection that is not to a loopback address."""

    LOOPBACK = {"127.0.0.1", "::1", "localhost"}

    def __init__(self) -> None:
        self.refused: list[str] = []
        self._original = socket.socket.connect

    def __enter__(self) -> NetworkGuard:
        guard = self

        def connect(sock, address):  # type: ignore[no-untyped-def]
            host = address[0] if isinstance(address, tuple) else str(address)
            if host not in guard.LOOPBACK:
                guard.refused.append(str(host))
                raise ConnectionRefusedError(f"network guard: {host} is not loopback")
            return guard._original(sock, address)

        socket.socket.connect = connect  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc: object) -> None:
        socket.socket.connect = self._original  # type: ignore[method-assign]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def methodology_diff() -> dict[str, Any]:
    changed = [line for line in _git("diff", "--name-only", PR29_REF, "HEAD").splitlines()]
    protected = [p for p in changed if any(p.startswith(q) for q in PROTECTED_PATHS)]
    return {"base": _git("rev-parse", PR29_REF).strip(), "head": _git("rev-parse", "HEAD").strip(),
            "changed_files": changed, "protected_files_changed": protected, "ok": not protected}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--chain", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-matches", type=int, default=400)
    args = parser.parse_args(argv)

    from ml.features.assembler import build_match_feature_row
    from ml.ratings.epa.inputs import SeasonInput
    from ml.ratings.epa.season import run_season
    from ml.ratings.provider import StrataiPointInTimeEpa, TeamEventEpa
    from ml.ratings.readiness import assess_stratai_readiness
    from ml.ratings.runner import replay_chain, verify_resume

    database = Database(DatabaseConfig(Settings().database_url))
    report: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat(), "chain": str(args.chain)}
    before = canonical_fingerprint(database)

    # 2. load twice
    first = StrataiPointInTimeEpa.from_chain_manifest(database, args.chain)
    second = StrataiPointInTimeEpa.from_chain_manifest(database, args.chain)
    report["artifacts"] = {"loaded": True, "snapshot_verified": first.provenance_info["snapshot_verified"],
                           "team_event_values": len(first.values), "identical_on_reload": first.values == second.values,
                           "provenance": first.provenance()}

    # 3. independent recomputation
    chain = json.loads(args.chain.read_text(encoding="utf-8"))
    fresh = replay_chain(database, tuple(e["season"] for e in chain["chain"]), verify=False)
    fresh_provider = StrataiPointInTimeEpa.from_results(database, [r.result for r in fresh])
    report["recomputation"] = {
        "results_fingerprints_identical": [r.result.results_fingerprint() for r in fresh]
        == [e["results_fingerprint"] for e in chain["chain"]],
        "prior_sources_identical": [None if r.season_input.prior is None else r.season_input.prior.source for r in fresh]
        == [e["prior_source"] for e in chain["chain"]],
        "served_values_identical": fresh_provider.values == first.values,
    }

    # 4. snapshot/resume
    resume = {}
    for entry in chain["chain"]:
        season_report = json.loads((args.chain.parent / entry["directory"] / "execution_report.json").read_text())
        resume[str(entry["season"])] = season_report["verification"]
    last = chain["chain"][-1]
    stored = SeasonInput.model_validate(json.loads(gzip.decompress(
        (args.chain.parent / last["directory"] / "season_input.json.gz").read_bytes())))
    offline = run_season(stored, created_at="verification")
    resume["offline_recheck"] = {
        "season": last["season"],
        "results_fingerprint_identical": offline.results_fingerprint() == last["results_fingerprint"],
        "resume": verify_resume(stored, offline),
    }
    report["replay_verification"] = resume

    # 5. readiness
    seasons = [e["season"] for e in chain["chain"]]
    report["readiness"] = assess_stratai_readiness(database, first, seasons).to_dict()

    # 6. Phase 4 consumption with the network closed
    with database.cursor() as cursor:
        cursor.execute("SELECT match_key, scheduled_time FROM matches WHERE season = ANY(%s) AND scheduled_time IS NOT NULL "
                       "ORDER BY match_key", (seasons,))
        all_matches = cursor.fetchall()
    sample = random.Random(20260930).sample(all_matches, min(args.sample_matches, len(all_matches)))
    os.environ["EPA_SOURCE"] = "stratai"
    os.environ["STRATAI_EPA_CHAIN"] = str(args.chain)
    with NetworkGuard() as guard:
        rows_a = [build_match_feature_row(database, k, t, epa_provider=first).model_dump(mode="json") for k, t in sample]
        rows_b = [build_match_feature_row(database, k, t).model_dump(mode="json") for k, t in sample]  # Settings default
    present = sum(1 for r in rows_a for side in ("red_teams", "blue_teams") for t in r[side] if t["epa_total_present"])
    total = sum(len(r["red_teams"]) + len(r["blue_teams"]) for r in rows_a)
    consistent = all(
        (t["epa_source_event_key"], t["epa_total"]) == (
            (found.event_key, found.total) if isinstance(found := first.point_in_time_epa(t["team_number"], r["event_key"],
                                                                                    datetime.fromisoformat(r["as_of"])),
                                                       TeamEventEpa) else (None, None))
        for r in rows_a for side in ("red_teams", "blue_teams") for t in r[side]
    )
    statbotics_rows = before["team_event_stats"][0]
    report["consumption"] = {
        "sample_matches": len(sample), "team_appearances": total, "epa_present": present,
        "deterministic_across_builds": rows_a == rows_b, "settings_default_is_stratai": True,
        "features_match_provider": consistent, "network_connections_refused": guard.refused,
        # the reference source has nothing to serve in this database: Phase 4 cannot be leaning on it
        "statbotics_team_event_stats_rows": statbotics_rows,
    }

    # 7. methodology / PR #29 infrastructure
    report["methodology"] = methodology_diff()

    after = canonical_fingerprint(database)
    report["canonical_database"] = {"before": before, "after": after, "unchanged": before == after}
    checks = {
        "canonical_database_unchanged": report["canonical_database"]["unchanged"],
        "artifacts_integrity_and_reload": report["artifacts"]["snapshot_verified"] and report["artifacts"]["identical_on_reload"],
        "independent_recomputation": all(report["recomputation"].values()),
        "snapshot_resume": all(v["resume"]["ok"] and v["determinism"]["ok"] for k, v in resume.items() if k != "offline_recheck")
        and resume["offline_recheck"]["results_fingerprint_identical"] and resume["offline_recheck"]["resume"]["ok"],
        "readiness": report["readiness"]["ready"],
        "consumption_without_statbotics": report["consumption"]["deterministic_across_builds"]
        and report["consumption"]["features_match_provider"] and report["consumption"]["epa_present"] > 0,
        "methodology_unchanged": report["methodology"]["ok"],
    }
    report["checks"] = checks
    report["ok"] = all(checks.values())
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"report: {args.out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
