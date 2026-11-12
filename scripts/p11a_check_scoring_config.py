"""P11A: check a draft season scoring configuration against a GameSpec, without approval (prints content_sha256).

    python -m scripts.p11a_check_scoring_config --config <draft.json> --spec <game_spec_export.json | game_spec.json>

**What it checks** (`ml.alliance.scoring_config.check_draft`):
- the configuration's schema (one rule per component, cap fields, citations);
- that its `game_spec_sha256` is this GameSpec's sha256;
- that every action it names exists, in its component's period;
- and it prints the resolved point values and the `content_sha256` a reviewer verifies.

**The GameSpec** is either:
- an export of an **approved** row (`scripts.p11a_gamespec_copy export`, verified as that tool verifies it); or
- a plain GameSpec JSON file (a draft, such as `research/p11a_drafts/<season>/game_spec.draft.json`). It is reported
  as `game_spec_approved: false`, and checking against it says nothing about the approved spec.

It reads files only. It never writes a file, approves anything, or touches `data/season_scoring/`. Exit 0 when the
configuration is valid against the spec, 1 when it is not, 2 when an input cannot be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_spec(path: Path) -> tuple[Any, bool]:
    """(GameSpec, approved): an approved-row export, or a plain GameSpec file (not approved)."""
    from data.game_spec import GameSpec
    from scripts.p11a_gamespec_copy import EXPORT_KIND, check_export

    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, dict) and document.get("kind") == EXPORT_KIND:
        row = check_export(document)
        return GameSpec.model_validate_json(row["spec_json"]), True
    return GameSpec.model_validate(document), False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args(argv)

    from ml.alliance.scoring_config import SeasonScoringConfig, check_draft
    from scripts.p11a_gamespec_copy import CopyRefused

    try:
        spec, approved = load_spec(args.spec)
        config = SeasonScoringConfig.model_validate_json(args.config.read_bytes())
    except (OSError, ValueError, CopyRefused) as exc:
        print(json.dumps({"status": "unreadable", "error": f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"},
                         indent=1))
        return 2
    report = {"config_file": str(args.config), "spec_file": str(args.spec), "game_spec_approved": approved,
              **check_draft(config, spec)}
    print(json.dumps(report, indent=1))
    return 0 if report["valid_against_spec"] else 1


if __name__ == "__main__":
    sys.exit(main())
