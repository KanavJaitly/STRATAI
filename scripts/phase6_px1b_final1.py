"""FINAL-1: PX-1b's 2027 acceptance evaluation, exactly as frozen in `.agent/phase6/P6_M2_PX1B_SPEC.md` §6, under D9
decision v1 Part B (`.agent/phase6/decisions/P6_D9_PX1B_REPLACEMENT_V1.md`).

Run only through `python -m scripts.phase6_px1b gate2027`, once.

**Fail-closed prerequisites.** All of them are checked before any data is read.
- Absent prerequisites are collected and refused together.
- An inconsistent one (a hash, fingerprint or provenance mismatch) is refused at once.

**The gate (the P6-Q3 form, unchanged).**
- PX-1b's held-out 2027 log-loss must be strictly better than both the frozen M6/M7 `d18` and the `px1b-v1` seed-only
  comparator.
- Each comparison is a paired event-bootstrap 95% CI of the per-match difference (2,000 resamples, seed 20261010) that
  must lie entirely below 0.
- All three models are scored on the identical eligible rows.

**A pass does not accept PX-1b.** Under D9 v1 Part B condition 4, acceptance also needs Kanav's dated confirmation
whose sha256 matches the record.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import phase6_common as common
from scripts import phase6_playoff_track as track
from scripts.phase6_common import M6M7_SHA256, file_sha256, git_blob, read_record
from scripts.phase6_playoff_track import Blocked

HOLDOUT = 2027
PX1B_SPEC = ".agent/phase6/P6_M2_PX1B_SPEC.md"
PX1B_SPEC_BLOB = "80201eb0db17d3c54d373559ca5cf88f9546b330"  # frozen at ca13e98
D9_RECORD = ".agent/phase6/decisions/P6_D9_PX1B_REPLACEMENT_V1.md"
DECISIONS = Path(".agent/phase6/decisions")
D9_CONFIRMATION = DECISIONS / "p6_d9_v1_confirmation.json"  # Kanav: D9 record v1 confirmed (human-written)
AUTHORIZATION = DECISIONS / "p6_px1b_final1_authorization.json"  # Kanav: run FINAL-1 now (human-written)
EPA_CONFIG = DECISIONS / "p6_px1b_epa_source_2027_config.json"  # which 2027 EPA source (human-written)
GATE_RECORD, FINAL_RECORD, DEV_RECORD = "p6_px1b_gate_2027.json", "p6_px1b_final_fit.json", "p6_px1b_dev.json"
M1_2027_RECORD, EPA_RECORD = "p6_m1_ruleset_check_2027.json", "p6_px1b_epa_source_2027.json"
TRAINING_SEASONS = {"2024", "2025", "2026"}
# Registration evidence (2026-10-10): px1b-v1 is shown to predate 2027 by git, never by the registry's own timestamp.
REGISTRATION_RECORD = "p6_px1b_registration_evidence.json"
CANDIDATE_MODELS = (("playoff_px1b", "px1b-v1"), ("playoff_px1b_seed_only", "px1b-v1"))
EVIDENCE_PATH = ".agent/phase6/results/p6_px1b_chain_pins.json"  # the first record holding the exact model sha256s
M1_2027_PATH = f".agent/phase6/results/{M1_2027_RECORD}"
REPO = Path(".")


# --- human-written decision files -----------------------------------------------------------------------------


def _json(path: Path) -> dict[str, Any] | None:
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None


def check_d9_confirmation(value: dict[str, Any]) -> None:
    """Kanav's confirmation of D9 decision v1: confirmed, by, date, and the record's current git blob."""
    if not (value.get("confirmed") is True and value.get("confirmed_by") and value.get("date")
            and value.get("record") == D9_RECORD and value.get("record_blob") == git_blob(D9_RECORD)):
        raise Blocked(f"{D9_CONFIRMATION} does not confirm the current {D9_RECORD} (confirmed, confirmed_by, date, "
                      "record, record_blob)")


def check_authorization(value: dict[str, Any]) -> None:
    """Kanav's instruction to run FINAL-1 now (§6: once, after the 2027 season is complete and synced)."""
    if not (value.get("authorized") is True and value.get("authorized_by") and value.get("date")
            and value.get("scope") == "FINAL-1" and value.get("season") == HOLDOUT
            and value.get("season_complete_and_synced") is True):
        raise Blocked(f"{AUTHORIZATION} does not authorize FINAL-1 for a complete, synced 2027 season (authorized, "
                      "authorized_by, date, scope=FINAL-1, season=2027, season_complete_and_synced)")


# --- the 2027 EPA source ----------------------------------------------------------------------------------------


def _manifest(snapshot: Path) -> dict[str, Any]:
    return json.loads((Path(snapshot) / "manifest.json").read_text(encoding="utf-8"))


def verified_epa_source(record: dict[str, Any]) -> tuple[Path, Path]:
    """The pinned 2027 D18 source: the snapshot manifest and the chain must hash to the record, and the snapshot must
    cover 2027. (The loader then verifies every raw file against that manifest.)"""
    snapshot, chain = Path(record["snapshot"]), Path(record["chain"])
    for label, path, expected in (("snapshot manifest", snapshot / "manifest.json", record["manifest_sha256"]),
                                  ("EPA chain", chain, record["chain_sha256"])):
        if not path.exists():
            raise Blocked(f"2027 EPA source: the {label} {path} is missing")
        if file_sha256(path) != expected:
            raise Blocked(f"2027 EPA source: the {label} no longer matches its pin")
    if HOLDOUT not in _manifest(snapshot).get("seasons", []):
        raise Blocked("2027 EPA source: the pinned snapshot does not cover 2027")
    return snapshot, chain


def run_epa_pin_2027(database, rulesets) -> dict[str, Any]:
    """Pin the 2027 D18 EPA source named in Kanav's config, after D18's own integrity checks pass on it. Write-once
    `p6_px1b_epa_source_2027.json`; nothing is evaluated."""
    from ml.ratings.d18_source import load_d18_provider

    config = _json(EPA_CONFIG)
    if config is None or not config.get("snapshot") or not config.get("chain"):
        raise Blocked(f"{EPA_CONFIG} (the 2027 snapshot and chain to pin) is required")
    snapshot, chain = Path(config["snapshot"]), Path(config["chain"])
    if not (snapshot / "manifest.json").exists() or not chain.exists():
        raise Blocked("the configured 2027 EPA snapshot or chain does not exist")
    manifest = _manifest(snapshot)
    if HOLDOUT not in manifest.get("seasons", []):
        raise Blocked("the configured snapshot does not cover 2027")
    try:
        _, integrity = load_d18_provider(database, snapshot, chain)
    except Exception as exc:  # D18SourceIntegrityError and any read failure: refuse, never pin
        raise Blocked(f"the configured 2027 EPA source failed D18's integrity checks: {exc}") from exc
    return {"milestone": "PX-1b 2027 EPA source pin", "acceptance": False, "snapshot": str(snapshot),
            "manifest_sha256": file_sha256(snapshot / "manifest.json"), "chain": str(chain),
            "chain_sha256": file_sha256(chain), "seasons": manifest["seasons"], "integrity": integrity,
            "config": {"path": str(EPA_CONFIG), "sha256": file_sha256(EPA_CONFIG)}}


# --- registration evidence (tamper-evident; independent of the registry's own timestamp) ---------------------------


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)


def commit_time(commit: str) -> datetime | None:
    """The commit's committer time, read from git (never from a record)."""
    out = _git("show", "-s", "--format=%cI", commit)
    return datetime.fromisoformat(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def is_strict_ancestor(ancestor: str, descendant: str) -> bool:
    if _git("rev-parse", "--verify", f"{ancestor}^{{commit}}").returncode != 0:
        return False
    same = _git("rev-parse", ancestor).stdout.strip() == _git("rev-parse", descendant).stdout.strip()
    return not same and _git("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def file_at(commit: str, path: str) -> str | None:
    out = _git("show", f"{commit}:{path}")
    return out.stdout if out.returncode == 0 else None


def adding_commit(path: str) -> str | None:
    """The commit that first added `path` on HEAD's history (None if it was never committed)."""
    out = _git("log", "--diff-filter=A", "--format=%H", "--", path)
    lines = [line for line in out.stdout.split() if line]
    return lines[-1] if out.returncode == 0 and lines else None


def _manifest_path(model_type: str, tag: str) -> Path:
    return track.REGISTRY_DIR / model_type / tag / "manifest.json"


def _models_in_commit(commit: str) -> dict[str, str]:
    text = file_at(commit, EVIDENCE_PATH)
    if text is None:
        raise Blocked(f"registration evidence: {EVIDENCE_PATH} does not exist at commit {commit}")
    return json.loads(text).get("models", {})


def run_registration_evidence(database, rulesets) -> dict[str, Any]:
    """Write-once `p6_px1b_registration_evidence.json`: per candidate model, its file sha256, its registry manifest's
    sha256 (making `created_at` tamper-evident) and training hash; and the git commit that first recorded the exact
    model hashes, with that commit's committer time. Taken before any 2027 data; nothing is evaluated."""
    from ml.registry import model_file_sha256
    from scripts.phase6_px1b import _playoff_matches

    if _playoff_matches(database, HOLDOUT):
        raise Blocked("2027 playoff matches exist: the registration evidence is taken before any 2027 data")
    evidence = adding_commit(EVIDENCE_PATH)
    if evidence is None:
        raise Blocked(f"{EVIDENCE_PATH} has never been committed: there is no registration evidence")
    committed = commit_time(evidence)
    recorded = _models_in_commit(evidence)
    models = {}
    for model_type, tag in CANDIDATE_MODELS:
        key = f"{model_type}/{tag}"
        sha = model_file_sha256(track.REGISTRY_DIR, model_type, tag)
        if recorded.get(key) != sha:
            raise Blocked(f"registration evidence: {key}'s file is not the one recorded at commit {evidence}")
        manifest = json.loads(_manifest_path(model_type, tag).read_text(encoding="utf-8"))
        created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
        if not created <= committed:
            raise Blocked(f"registration evidence: {key}'s manifest time is after its evidence commit")
        models[key] = {"model_sha256": sha, "manifest_sha256": file_sha256(_manifest_path(model_type, tag)),
                       "manifest_created_at": manifest["created_at"],
                       "training_dataset_hash": manifest["training_dataset_hash"]}
    return {"milestone": "PX-1b registration evidence", "acceptance": False, "models": models,
            "evidence_commit": evidence, "evidence_path": EVIDENCE_PATH,
            "evidence_committed_at": committed.isoformat(),
            "method": "the commit that first added the pin record holding each candidate's exact file sha256; "
                      "FINAL-1 re-derives the commit's existence, ancestry, content and committer time from git"}


def verify_registration(record: dict[str, Any], pins: dict[str, Any]) -> dict[str, Any]:
    """FINAL-1's frozen-first evidence, re-derived from git and the files, never from the record alone:
    - each candidate's pinned sha256 = the record's = the sha256 in EVIDENCE_PATH at the evidence commit;
    - each registry manifest still hashes to the record's sha256 (so its `created_at` is unaltered), and that
      `created_at` is no later than the evidence commit;
    - the evidence commit exists, is in HEAD's history, and its committer time (from git) equals the record's;
    - the C0 2027 record is committed, and the evidence commit is its strict ancestor: a date-independent proof
      that the candidate's exact bytes were recorded before any 2027 result was."""
    evidence = record.get("evidence_commit")
    if not evidence or record.get("evidence_path") != EVIDENCE_PATH:
        raise Blocked(f"{REGISTRATION_RECORD} names no evidence commit for {EVIDENCE_PATH}")
    committed = commit_time(evidence)
    if committed is None or _git("merge-base", "--is-ancestor", evidence, "HEAD").returncode != 0:
        raise Blocked(f"registration evidence: commit {evidence} is not in this repository's history")
    if committed.isoformat() != record.get("evidence_committed_at"):
        raise Blocked("registration evidence: the recorded commit time disagrees with git")
    recorded = _models_in_commit(evidence)
    for model_type, tag in CANDIDATE_MODELS:
        key = f"{model_type}/{tag}"
        entry = (record.get("models") or {}).get(key)
        if not entry:
            raise Blocked(f"registration evidence: no entry for {key}")
        if not (entry["model_sha256"] == pins["models"].get(key) == recorded.get(key)):
            raise Blocked(f"registration evidence: {key}'s sha256 differs between the record, the pins and commit "
                          f"{evidence}")
        path = _manifest_path(model_type, tag)
        if not path.exists() or file_sha256(path) != entry["manifest_sha256"]:
            raise Blocked(f"registration evidence: {key}'s registry manifest was altered or is missing")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
        if manifest["created_at"] != entry["manifest_created_at"] or not created <= committed:
            raise Blocked(f"registration evidence: {key}'s manifest time is inconsistent with its evidence commit")
    c0 = adding_commit(M1_2027_PATH)
    if c0 is None:
        raise Blocked(f"{M1_2027_RECORD} must be committed before FINAL-1, so its order after the evidence is provable")
    if not is_strict_ancestor(evidence, c0):
        raise Blocked(f"registration evidence: commit {evidence} is not a strict ancestor of the commit that "
                      f"recorded the 2027 P6-M1 check ({c0})")
    return {"evidence_commit": evidence, "committed_at": committed.isoformat(), "c0_commit": c0,
            "evidence_precedes_2027_record": True,
            "manifests": {k: v["manifest_sha256"] for k, v in record["models"].items()}}


# --- prerequisites ------------------------------------------------------------------------------------------------


def prerequisites(database, rulesets) -> dict[str, Any]:
    """Every frozen FINAL-1 prerequisite, checked before any data is read. Returns the verified provenance."""
    from data.rulesets import approved_ruleset, approved_seasons
    from ml.playoffs.pins import PIN_RECORD
    from scripts.phase6_common import load_m6m7
    from scripts.phase6_px1b import _playoff_matches, pinned_px1b_models

    if read_record(GATE_RECORD) is not None:
        raise Blocked(f"{GATE_RECORD} already exists: FINAL-1 runs once and is never re-run or overwritten")
    if git_blob(PX1B_SPEC) != PX1B_SPEC_BLOB:
        raise Blocked(f"{PX1B_SPEC} is not the frozen PX-1b spec blob {PX1B_SPEC_BLOB}")
    missing: list[str] = []
    provenance: dict[str, Any] = {"spec": {"path": PX1B_SPEC, "blob": PX1B_SPEC_BLOB},
                                  "d9_record": {"path": D9_RECORD, "blob": git_blob(D9_RECORD)}}

    for path, check, label in ((D9_CONFIRMATION, check_d9_confirmation, "Kanav's confirmation of D9 decision v1"),
                               (AUTHORIZATION, check_authorization, "Kanav's authorization to run FINAL-1")):
        value = _json(path)
        if value is None:
            missing.append(f"{path} ({label})")
        else:
            check(value)
            provenance[path.stem] = {"path": str(path), "sha256": file_sha256(path)}

    final, dev = read_record(FINAL_RECORD), read_record(DEV_RECORD)
    if final is None:
        missing.append(f"{FINAL_RECORD} (the frozen final candidate)")
    elif not set(final["rows"]["by_season"]) <= TRAINING_SEASONS:
        raise Blocked("px1b-v1's training population includes a season outside 2024-2026")
    if dev is None or not dev["decision"]["proceed_to_final"]:
        missing.append(f"{DEV_RECORD} with DV1 and DV2 met")

    if read_record(PIN_RECORD) is None:
        missing.append(f"{PIN_RECORD} (the G1/G2/G3 integrity pins)")
    else:
        pinned_px1b_models()  # raises Blocked on an altered or missing pinned file
        pins = read_record(PIN_RECORD)
        if final is not None:
            manifest = json.loads((track.REGISTRY_DIR / "playoff_px1b/px1b-v1/manifest.json").read_text(encoding="utf-8"))
            if not (manifest["training_dataset_hash"] == final["dataset_fingerprint"] == pins["population_fingerprint"]):
                raise Blocked("px1b-v1's registry training hash, final-fit fingerprint and pinned population disagree")
            provenance["candidate"] = {"training_fingerprint": final["dataset_fingerprint"]}
        provenance["pins"] = {"record": PIN_RECORD, "sha256": file_sha256(common.RESULTS_DIR / PIN_RECORD),
                              "models": {k: v for k, v in pins["models"].items() if k.endswith("/px1b-v1")}}
    try:
        load_m6m7()  # pinned: refuses an artifact other than sha256 M6M7_SHA256
    except (FileNotFoundError, ValueError) as exc:
        raise Blocked(f"the M6/M7 d18 baseline does not match its pin: {exc}") from exc
    provenance["m6m7_sha256"] = M6M7_SHA256

    ruleset_2027 = None
    if HOLDOUT not in approved_seasons(database):
        missing.append("an approved 2027 P6-M1 ruleset (human-entered; a qualified reviewer)")
    else:
        ruleset_2027 = approved_ruleset(database, HOLDOUT)
        provenance["ruleset_2027_sha256"] = ruleset_2027.sha256()
    m1 = read_record(M1_2027_RECORD)
    if m1 is None:
        missing.append(f"{M1_2027_RECORD} (the P6-M1 reproduction check for 2027 events, C0)")
    else:
        season = m1["seasons"].get(str(HOLDOUT)) or m1["seasons"].get(HOLDOUT) or {}
        if m1.get("escalate") or season.get("escalate"):
            raise Blocked(f"{M1_2027_RECORD} escalated (excluded share above 10%): Kanav must resolve it first")
        if ruleset_2027 is not None and season.get("ruleset_sha256") != ruleset_2027.sha256():
            raise Blocked(f"{M1_2027_RECORD} was not made with the approved 2027 ruleset")
        provenance["m1_2027"] = {"record": M1_2027_RECORD, "sha256": file_sha256(common.RESULTS_DIR / M1_2027_RECORD)}
    if not _playoff_matches(database, HOLDOUT):
        missing.append("2027 playoff data (the season complete and synced)")
    epa = read_record(EPA_RECORD)
    if epa is None:
        missing.append(f"{EPA_RECORD} (a pinned D18 EPA source covering 2027)")
    else:
        snapshot, chain = verified_epa_source(epa)
        provenance["epa_source"] = {"record": EPA_RECORD, "sha256": file_sha256(common.RESULTS_DIR / EPA_RECORD),
                                    "snapshot": str(snapshot), "chain": str(chain),
                                    "manifest_sha256": epa["manifest_sha256"], "chain_sha256": epa["chain_sha256"]}
    registration = read_record(REGISTRATION_RECORD)
    if registration is None:
        missing.append(f"{REGISTRATION_RECORD} (the candidate's tamper-evident registration evidence)")
    if missing:
        raise Blocked("FINAL-1 cannot be evaluated yet; missing: " + "; ".join(missing))
    provenance["registration"] = {"record": REGISTRATION_RECORD,
                                  "sha256": file_sha256(common.RESULTS_DIR / REGISTRATION_RECORD),
                                  **verify_registration(registration, read_record(PIN_RECORD))}
    provenance["m1_2027_events"] = m1
    return provenance


# --- the evaluation ---------------------------------------------------------------------------------------------


def evaluate(rows: Sequence, px1b, seed_only, m6m7_predict: Callable[[Any], float]) -> dict[str, Any]:
    """The §6 gate on identical rows: PX-1b, the seed-only comparator and M6/M7 scored on the same eligible 2027 rows
    and labels, then `ml.playoffs.px1b.gate_2027` (2,000 resamples, seed 20261010)."""
    from ml.playoffs.history import model_summary
    from ml.playoffs.px1b import BOOTSTRAP_SEED, dataset_fingerprint, gate_2027

    scored = [(r, px1b.predict(r), seed_only.predict(r)) for r in rows]
    eligible = [(r, p, s) for r, p, s in scored if p is not None and s is not None]
    if not eligible:
        raise Blocked("no eligible 2027 rows to evaluate")
    kept = [r for r, _, _ in eligible]
    predictions = {"px1b": [p for _, p, _ in eligible], "seed_only": [s for _, _, s in eligible],
                   "m6m7": [m6m7_predict(r) for r in kept]}
    labels, events = [r.red_win for r in kept], [r.event_key for r in kept]
    gate = gate_2027(predictions["px1b"], predictions["m6m7"], predictions["seed_only"], labels, events)
    return {"rows": len(kept), "events": len(set(events)), "insufficient_data": len(rows) - len(kept),
            "dataset_fingerprint": dataset_fingerprint(kept),
            "bootstrap": {"resamples": gate["vs_m6m7"]["resamples"], "seed": BOOTSTRAP_SEED},
            "models": {m: model_summary(p, labels, events) for m, p in predictions.items()},
            "vs_m6m7": gate["vs_m6m7"], "vs_seed_only": gate["vs_seed_only"], "passed": gate["passed"]}


def assemble_2027(database, rulesets, provenance) -> tuple[list, Counter, dict]:
    """PX-1b spec §1 rows of 2027 (A1, the P6-M1 exclusions, four-member, EPA-incomplete and scale_absent, each
    counted), assembled at each event's selection moment from the pinned 2027 EPA source."""
    from ml.playoffs.px1b import drop_scale_absent
    from scripts.phase6_playoff_track import assemble_rows

    epa = provenance["epa_source"]
    rows, excluded, _, events_by_key, integrity, by_event = assemble_rows(
        database, rulesets, provenance["m1_2027_events"], seasons=(HOLDOUT,), snapshot=Path(epa["snapshot"]),
        chain=Path(epa["chain"]))
    rows, scale_excluded = drop_scale_absent(rows)
    excluded.update(scale_excluded)
    if any(r.season != HOLDOUT for r in rows):
        raise Blocked("a non-2027 row reached the FINAL-1 population")
    return rows, excluded, {"epa_integrity": integrity, "excluded_by_event": by_event,
                            "selection_moments": {k: e.selection_as_of().isoformat() for k, e in events_by_key.items()}}


def require_candidate_frozen_first(provenance: dict[str, Any], selection_moments: dict[str, str]) -> dict[str, Any]:
    """§6: px1b-v1's exact bytes must be on record before any 2027 prediction time. The time is the git committer
    time of the verified evidence commit (`verify_registration`), never the registry manifest's own timestamp."""
    recorded = datetime.fromisoformat(provenance["registration"]["committed_at"])
    first = min(datetime.fromisoformat(t) for t in selection_moments.values())
    if not recorded < first:
        raise Blocked(f"px1b-v1's evidence commit is from {recorded.isoformat()}, not before the first 2027 "
                      f"selection moment {first.isoformat()}")
    return {"candidate_recorded_at": recorded.isoformat(), "evidence_commit": provenance["registration"]["evidence_commit"],
            "first_2027_selection": first.isoformat(), "frozen_first": True}


def run_gate2027(database, rulesets) -> dict[str, Any]:
    """FINAL-1, once: prerequisites, then the 2027 population, then the gate. `main` writes the write-once record."""
    from scripts.phase6_common import load_m6m7
    from scripts.phase6_px1b import pinned_px1b_models

    provenance = prerequisites(database, rulesets)
    rows, excluded, extra = assemble_2027(database, rulesets, provenance)
    temporal = require_candidate_frozen_first(provenance, extra["selection_moments"])
    px1b, seed_only = pinned_px1b_models()
    track.M6M7 = load_m6m7()
    result = evaluate(rows, px1b, seed_only, track._m6m7_on)
    provenance.pop("m1_2027_events")
    return {"milestone": "PX-1b FINAL-1 (PX-1b spec §6; D9 v1 Part B)",
            "acceptance_note": "a pass does NOT accept PX-1b by itself: D9 v1 Part B condition 4 requires Kanav's "
                               "dated confirmation whose sha256 matches this record",
            "provenance_inputs": provenance, "temporal": temporal,
            "population": {"eligible_rows": result["rows"], "events": result["events"],
                           "insufficient_data": result["insufficient_data"], "excluded": dict(excluded),
                           "excluded_by_event": extra["excluded_by_event"]},
            "epa_integrity": extra["epa_integrity"], **{k: v for k, v in result.items() if k not in ("rows", "events")}}
