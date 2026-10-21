"""A reviewable P6-M1 ruleset worksheet for a new season (2026-10-11): a starting point, never a ruleset.

**It does not save, submit or approve anything.** It returns a schema-valid draft *proposal* that a person edits and
saves under their own name (`data.rulesets.save_ruleset_draft`). A named, qualified reviewer then verifies it against
the authoritative FIRST sources (`.agent/phase6/decisions/P6_M1_REVIEW_CONTROL.md`).

**How it is built:**
- the structure of the latest **earlier** season's approved ruleset, re-labelled for the target season;
- event-specific lists (selection variants, event exclusions) emptied, since another season's events never apply;
- **every citation and the tie rule marked `UNVERIFIED (carried from <season>)`**. An approval refuses while any
  marker remains (`data.rulesets._approval_record`), so carried-over text can never be approved by accident;
- the uploaded manual's machine-extracted suggestions attached as verification items with page references.

It never substitutes one season's rules for another: nothing here is served or read by any engine.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from database.connection import Database

MARKER = "UNVERIFIED (carried from"


def _mark(value: Any, source_season: int) -> Any:
    """Every citation-like string marked as carried over; structure and numbers left for the person to verify."""
    if isinstance(value, dict):
        return {k: (f"{MARKER} {source_season}): {v}" if k in ("citation", "tie_rule", "section") and isinstance(v, str)
                    else _mark(v, source_season)) for k, v in value.items()}
    if isinstance(value, list):
        return [_mark(v, source_season) for v in value]
    return value


def ruleset_worksheet(database: Database, store_dir: Path, season: int) -> dict[str, Any]:
    from data import manual_processing as mp
    from data.human_inputs import list_manuals
    from data.rulesets import RulesetError, list_rulesets, validate_ruleset

    earlier = [r for r in list_rulesets(database) if r["status"] == "approved" and r["season"] < season]
    if not earlier:
        raise RulesetError("not_found", f"no approved ruleset from a season before {season} to use as a structure")
    template = max(earlier, key=lambda r: r["season"])
    source = template["season"]
    proposal = _mark(copy.deepcopy(template["ruleset_json"]), source)
    manuals = list_manuals(database, season)
    # The most recent successfully processed manual, so a later failed upload (a scan, another season's manual) cannot
    # hide its suggestions; with none processed, the latest upload is reported as unprocessed and lends no identity
    # (2026-10-12, D2).
    manual, extraction = None, None
    for candidate in reversed(manuals):
        extraction = mp.extraction(store_dir, candidate)
        if extraction is not None:
            manual = candidate
            break
    if manual is None and manuals:
        manual = manuals[-1]
    identity = (extraction or {}).get("identity") or {}
    proposal.update({
        "season": season,
        "game_name": manual["game_name"] if manual else f"{MARKER} {source}): {proposal['game_name']}",
        "manual": {"title": identity.get("title_line") or f"{MARKER} {source}): enter the {season} manual title",
                   "version": identity.get("revision") or f"{MARKER} {source}): enter the manual revision"},
        "selection_variants": [], "event_exclusions": [],
    })
    suggestions = (extraction or {}).get("suggestions", [])
    topics = (extraction or {}).get("topics", {})

    def hints(rule_names: tuple[str, ...], topic: str) -> dict[str, Any]:
        return {"suggestions": [s for s in suggestions if s["rule"] in rule_names],
                "manual_pages": (topics.get(topic) or {}).get("top_pages", [])}
    verify = [
        {"path": "alliance_counts", "reason": f"carried from {source}", **hints(("alliance_count",), "alliance_selection")},
        {"path": "selection", "reason": f"carried from {source}; every citation marked", **hints((), "alliance_selection")},
        {"path": "brackets", "reason": f"carried from {source}", **hints(("playoff_format",), "playoffs")},
        {"path": "tie_rule", "reason": f"carried from {source}; marked", **hints((), "playoffs")},
        {"path": "selection_variants", "reason": "emptied: list any 2027 event that uses other rules", **hints((), "alliance_selection")},
        {"path": "event_exclusions", "reason": "emptied: list any 2027 event that must be excluded", **hints((), "playoffs")},
        {"path": "manual", "reason": "from the uploaded manual's identity; confirm the title and revision", "suggestions": [],
         "manual_pages": [1]},
    ]
    try:
        validate_ruleset(proposal)
        schema_errors: list[Any] = []
    except RulesetError as exc:
        schema_errors = exc.details or [str(exc)]
    return {"season": season, "template_from_season": source, "template_ruleset_id": template["id"],
            "manual": None if manual is None else {"id": manual["id"], "sha256": manual["content_sha256"],
                                                    "processed": extraction is not None},
            "proposal": proposal, "schema_errors": schema_errors, "verify": verify,
            "unverified_marker": MARKER, "saved": False,
            "note": "A starting point only. Save it as a draft under your own name, replace every UNVERIFIED marker "
                    "from the official manual, then submit it for a named, qualified reviewer's approval."}
