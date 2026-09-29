"""Re-verify a restored dataset before an attempt uses it: `python -m automation.verify_dataset`.

The dump's sha256 proves the file is the one the build produced; this proves
the restored database is the one the build *gated*: readiness must still be
COMPLETE and the team_event_stats fingerprint must equal the one recorded at
build time. Any mismatch exits non-zero, so the attempt never starts.
"""

from __future__ import annotations

import argparse
import sys

from automation.data_readiness import COMPLETE, assess_readiness


def verify(report_status: str, fingerprint: str | None, expected: str) -> list[str]:
    problems = []
    if report_status != COMPLETE:
        problems.append(f"restored dataset readiness is {report_status}, not {COMPLETE}")
    if not expected:
        problems.append("no fingerprint was recorded for this dump; refusing to trust it")
    elif fingerprint != expected:
        problems.append(f"team_event_stats fingerprint {fingerprint} != recorded {expected}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-fingerprint", default="")
    args = parser.parse_args(argv)

    from data.config import Settings
    from database.connection import Database, DatabaseConfig

    report = assess_readiness(Database(DatabaseConfig(Settings().database_url)))
    problems = verify(report.status, report.team_event_stats_fingerprint, args.expected_fingerprint)
    for reason in report.reasons:
        print(f"readiness: {reason}")
    for problem in problems:
        print(f"REFUSED: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
