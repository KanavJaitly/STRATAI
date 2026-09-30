"""Real-data EPA replay: read a season, run the pure core, verify, and write artifacts.

    read (ml.ratings.reader, read-only SQL) -> run_season (pure core)
    -> verification (determinism, snapshot/resume) -> execution report
    -> write-once artifact directory

Nothing here writes to the database. Outputs go to an explicit directory,
one write-once subdirectory per (season, results fingerprint), in the same
spirit as ml.registry and ml.dataset.builder's persist_training_frame: a run
that reproduces an existing artifact exactly is recognised and not
rewritten; a different result never overwrites an old one.

Three questions are kept apart in every report (spec §0):
  * algorithmic correctness -- the unit tests (tests/test_ratings_epa_*.py);
  * successful real-data execution -- this module's execution report;
  * agreement with Statbotics' published values -- NOT measured here.
The prediction metrics in the report are a sanity check that the ratings
carry signal, not a measure of Statbotics agreement.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database.connection import Database
from ml.backtest.metrics import accuracy, brier_score, expected_calibration_error, log_loss
from ml.ratings.chain import CHAIN_SEASONS, prior_coverage, prior_from_results, team_districts_from_events
from ml.ratings.epa import exclusions as ex
from ml.ratings.epa.constants import ISR_DISTRICT, REFERENCE_COMMIT
from ml.ratings.epa.engine import EpaEngine
from ml.ratings.epa.inputs import PriorSeasonInput, SeasonInput, canonical_json, canonical_season_payload
from ml.ratings.epa.season import SeasonResult, run_season, start_engine
from ml.ratings.epa.validation import PreparedSeason, prepare_season
from ml.ratings.reader import ReadResult, read_season_input

logger = logging.getLogger(__name__)

RESUME_FRACTIONS = (0.25, 0.5, 0.75)
REJECTION_CODES = ex.DEFINITE_DIVERGENCE_CODES
SKIP_CODES = (ex.SKIP_PLACEHOLDER, ex.SKIP_ELIM_ALL_DQ, ex.SKIP_ALL_FOULS)
FILTER_CODES = (ex.EVENT_BLACKLISTED, ex.EVENT_TYPE_EXCLUDED, ex.EVENT_WEEK_MISSING, ex.INVALID_ALLIANCE)
EVENT_FILTER_CODES = (ex.EVENT_BLACKLISTED, ex.EVENT_TYPE_EXCLUDED, ex.EVENT_WEEK_MISSING)

WEEK_ONE_NOTE = (
    "Week-1 look-ahead: season statistics (score mean/sd, component means, foul rate) are computed from "
    "every completed week-1 match and fix the scale of every starting rating and every prediction. A match "
    "scheduled at or before the last week-1 match is therefore predicted with results not yet known when it "
    "was played (exposed matches). This is the reference EPA calculation, not a strictly point-in-time one. "
    "Matches scheduled after the last week-1 match use only earlier results. See docs/ratings/data_contract.md §9."
)


@dataclass(frozen=True)
class SeasonReplay:
    season: int
    read: ReadResult
    season_input: SeasonInput
    result: SeasonResult
    report: dict[str, Any]


def engine_input(read: ReadResult, prior: PriorSeasonInput | None) -> tuple[SeasonInput, tuple[int, ...]]:
    """The read input plus explicit prior history; with a prior, team districts are
    derived from the district events played (ml.ratings.chain). Returns the input and
    the teams whose district could not be derived consistently."""
    if prior is None:
        return read.season_input, ()
    districts, conflicts = team_districts_from_events(read.season_input)
    return read.season_input.model_copy(update={"prior": prior, "team_districts": districts}), conflicts


# --- verification ------------------------------------------------------------------


def verify_resume(season_input: SeasonInput, full: SeasonResult, fractions=RESUME_FRACTIONS) -> dict[str, Any]:
    """Snapshot at each cut, through JSON text, restore, finish; compare with the full run."""
    prepared, _ = start_engine(season_input)
    stream = prepared.stream
    cuts = sorted({int(len(stream) * f) for f in fractions} | {_first_week_two_index(prepared)})
    checks = []
    for cut in cuts:
        _, engine = start_engine(season_input)
        head = [engine.process(m) for m in stream[:cut]]
        restored = EpaEngine.from_snapshot(json.loads(json.dumps(engine.snapshot())))
        tail = [restored.process(m) for m in stream[cut:]]
        identical = tuple(head + tail) == full.records
        checks.append({"cut_index": cut, "resumed_after": stream[cut - 1].match_key if cut else None,
                       "records_identical": identical})
    return {"ok": all(c["records_identical"] for c in checks), "checks": checks}


def _first_week_two_index(prepared: PreparedSeason) -> int:
    return next((i for i, m in enumerate(prepared.stream) if m.week >= 2), 0)


# --- report ------------------------------------------------------------------------


def _prediction_sanity(prepared: PreparedSeason, result: SeasonResult) -> dict[str, Any]:
    """Win-probability metrics on completed, non-tied matches. A sanity check only."""
    by_key = {m.match_key: m for m in prepared.stream}
    groups: dict[str, tuple[list[float], list[bool]]] = {"all": ([], []), "week_1": ([], []), "week_2_plus": ([], [])}
    for record in result.records:
        match = by_key[record.match_key]
        if not match.completed or match.red.score == match.blue.score:  # type: ignore[union-attr]
            continue
        label = match.red.score > match.blue.score  # type: ignore[union-attr]
        for name in ("all", "week_1" if match.week == 1 else "week_2_plus"):
            groups[name][0].append(record.win_prob)
            groups[name][1].append(label)
    return {
        name: {"matches": len(p), "accuracy": accuracy(p, y), "brier": brier_score(p, y), "log_loss": log_loss(p, y),
               "ece_10_bins": expected_calibration_error(p, y)}
        for name, (p, y) in groups.items()
    }


def _breakdown_quality(prepared: PreparedSeason) -> dict[str, Any]:
    """Observations about the cleaned breakdowns; none of these stop a match."""
    residuals: list[tuple[int, str, str]] = []
    negative_foul = 0
    for match in prepared.stream:
        for color, alliance in (("red", match.red), ("blue", match.blue)):
            if alliance is None or alliance.empty:
                continue
            if alliance.teleop_residual:
                residuals.append((alliance.teleop_residual, match.match_key, color))
            if alliance.foul is not None and alliance.foul < 0:
                negative_foul += 1
    magnitudes = Counter(abs(r[0]) for r in residuals)
    return {
        "teleop_residual_alliances": len(residuals),
        "teleop_residual_abs_distribution": {str(k): v for k, v in sorted(magnitudes.items())},
        "largest_teleop_residuals": [
            {"residual": r, "match_key": k, "alliance": c}
            for r, k, c in sorted(residuals, key=lambda x: (-abs(x[0]), x[1], x[2]))[:10]
        ],
        "negative_foul_alliances": negative_foul,
    }


def build_execution_report(read: ReadResult, season_input: SeasonInput, result: SeasonResult,
                           verification: dict[str, Any], district_conflicts: tuple[int, ...] = ()) -> dict[str, Any]:
    """Everything the milestone asks the per-season report to show, as plain data."""
    prepared = prepare_season(season_input)
    districts = season_input.team_districts
    report = result.report
    counts = report.counts
    reader_counts = Counter((i.code, i.effect) for i in read.issues)
    excluded_events = {i.event_key for i in read.issues if i.effect == "excluded" and i.match_key is None}
    processed_events = {m.event_key for m in prepared.stream}
    statuses = Counter(r.status for r in result.records)
    filtered_events = Counter(
        code for code, _ in {(e.code, e.event_key) for e in report.entries if e.code in EVENT_FILTER_CODES}
    )
    played = {team for r in result.records if r.post is not None for team in r.post}
    week_one_times = [m.time for m in prepared.stream if m.week == 1 and m.completed]
    last_week_one = max(week_one_times, default=None)
    exposed = [m for m in prepared.stream if last_week_one is not None and m.time <= last_week_one]
    return {
        "season": result.season,
        "run": {
            "results_fingerprint": result.results_fingerprint(),
            "input_fingerprint": result.manifest["input_fingerprint"],
            "initialization": result.initialization,
            "engine_version": result.manifest["engine_version"],
            "reference_commit": REFERENCE_COMMIT,
            "libraries": result.manifest["libraries"],
            "data_snapshot": read.snapshot,
        },
        "events": {
            "canonical": read.canonical_events,
            "excluded_by_reader": len(excluded_events),
            "given_to_engine": len(season_input.events),
            "filtered_by_engine": {code: filtered_events[code] for code in EVENT_FILTER_CODES},
            "processed": len(processed_events),
        },
        "matches": {
            "canonical": read.canonical_matches,
            "excluded_by_reader": sum(1 for i in read.issues if i.effect == "excluded" and i.match_key is not None),
            "given_to_engine": len(season_input.matches),
            "filtered": {code: counts[code] for code in FILTER_CODES},
            "rejected": {code: counts[code] for code in REJECTION_CODES},
            "processed": len(result.records),
            "updated": statuses[ex.UPDATED],
            "skipped": {code: statuses[code] for code in SKIP_CODES},
            "upcoming_predicted_only": statuses[ex.UPCOMING],
            "with_zero_score_alliance": counts[ex.ZERO_SCORE],
        },
        "teams": {
            "rated": len(result.team_seasons),
            "with_qual_updates": sum(1 for t in result.team_seasons if t.qual_updates > 0),
            "without_any_completed_match": sum(1 for t in result.team_seasons if t.team not in played),
        },
        "outputs": {
            "match_records": len(result.records),
            "team_events": len(result.team_events),
            "team_events_season_end_lookahead": sum(1 for e in result.team_events if e.epa_is_season_end),
            "team_seasons": len(result.team_seasons),
            "norm_computed": result.norm_computed,
        },
        "initialization": {
            "label": result.initialization,
            "prior_source": None if season_input.prior is None else season_input.prior.source,
            "coverage": prior_coverage(season_input, prepared.teams),
            "team_districts_derived": districts is not None,
            "teams_with_district": 0 if districts is None else sum(1 for t in prepared.teams if t in districts),
            "isr_teams_without_mean_reversion": 0 if districts is None or result.season != 2026
            else sum(1 for t in prepared.teams if districts.get(t) == ISR_DISTRICT),
            "district_conflicts": list(district_conflicts),
        },
        "availability": result.availability.to_dict(),
        "year_stats": result.stats.to_dict(),
        "week_one_lookahead": {
            "week_one_matches": sum(1 for m in prepared.stream if m.week == 1),
            "last_week_one_match_time": last_week_one,
            "exposed_matches": len(exposed),
            "exposed_matches_after_week_one": sum(1 for m in exposed if m.week > 1),
            "exposed_share_of_processed": len(exposed) / len(prepared.stream) if prepared.stream else 0.0,
            "note": WEEK_ONE_NOTE,
        },
        "statbotics_divergence": {
            "definite": dict(report.divergences),
            "possible": dict(report.possible_divergences),
            "tie_groups": len(report.ties),
            "order_sensitive_tie_groups": [t.to_dict() for t in report.ties if t.order_sensitive],
        },
        "data_quality": {
            "reader_issues": {f"{code} ({effect})": n for (code, effect), n in sorted(reader_counts.items())},
            "breakdowns": _breakdown_quality(prepared),
        },
        "prediction_sanity_check": _prediction_sanity(prepared, result),
        "verification": verification,
    }


def replay_season(database: Database, season: int, *, prior: PriorSeasonInput | None = None,
                  compute_norm: bool = True, verify: bool = True,
                  event_keys: list[str] | None = None) -> SeasonReplay:
    """Read, run, verify and report one season. Writes nothing."""
    read = read_season_input(database, season, event_keys=event_keys)
    season_input, conflicts = engine_input(read, prior)
    logger.info("season %s: %s events, %s matches read", season, len(season_input.events), len(season_input.matches))
    result = run_season(season_input, compute_norm=compute_norm, data_snapshot=read.snapshot)
    verification: dict[str, Any] = {"performed": verify}
    if verify:
        reread = read_season_input(database, season, event_keys=event_keys)
        rerun = run_season(engine_input(reread, prior)[0], compute_norm=compute_norm, data_snapshot=reread.snapshot)
        verification["determinism"] = {
            "reread_input_identical": canonical_json(canonical_season_payload(reread.season_input))
            == canonical_json(canonical_season_payload(read.season_input)),
            "reread_issues_identical": reread.issues == read.issues,
            "rerun_results_fingerprint_identical": rerun.results_fingerprint() == result.results_fingerprint(),
        }
        verification["determinism"]["ok"] = all(verification["determinism"].values())
        verification["resume"] = verify_resume(season_input, result)
        logger.info("season %s: determinism %s, resume %s", season, verification["determinism"]["ok"],
                    verification["resume"]["ok"])
    report = build_execution_report(read, season_input, result, verification, conflicts)
    return SeasonReplay(season, read, season_input, result, report)


def replay_chain(database: Database, seasons: tuple[int, ...] = CHAIN_SEASONS, *, compute_norm: bool = True,
                 verify: bool = True) -> list[SeasonReplay]:
    """Replay consecutive seasons, each starting from the two before it (ml.ratings.chain)."""
    if list(seasons) != list(range(seasons[0], seasons[0] + len(seasons))):
        raise ValueError(f"chain seasons must be consecutive, got {seasons}")
    replays: list[SeasonReplay] = []
    for season in seasons:
        prior = prior_from_results(season, [r.result for r in replays[-2:]])
        replays.append(replay_season(database, season, prior=prior, compute_norm=compute_norm, verify=verify))
    return replays


def chain_manifest(replays: list[SeasonReplay], directories: list[Path]) -> dict[str, Any]:
    """What a chained run produced, in order, with each season's prior source."""
    return {
        "chain": [
            {"season": r.season, "directory": d.name, "results_fingerprint": r.result.results_fingerprint(),
             "input_fingerprint": r.result.manifest["input_fingerprint"],
             "prior_source": None if r.season_input.prior is None else r.season_input.prior.source}
            for r, d in zip(replays, directories, strict=True)
        ],
    }


# --- artifacts ---------------------------------------------------------------------


def _gzip_bytes(text: str) -> bytes:
    # mtime=0 and no filename: identical content gives identical bytes
    import io

    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as handle:
        handle.write(text.encode("utf-8"))
    return buffer.getvalue()


def artifact_files(replay: SeasonReplay) -> dict[str, bytes]:
    """Every file of a replay artifact except manifest.json, as bytes."""
    result = replay.result
    records = "\n".join(
        canonical_json({**r.to_dict(), "reference_rounded": r.reference_rounded(result.season)}) for r in result.records
    ) + "\n"
    return {
        "season_input.json.gz": _gzip_bytes(canonical_json(canonical_season_payload(replay.season_input))),
        "match_records.jsonl.gz": _gzip_bytes(records),
        "team_events.json": canonical_json([t.to_dict() for t in result.team_events]).encode("utf-8"),
        "team_seasons.json": canonical_json([t.to_dict() for t in result.team_seasons]).encode("utf-8"),
        "exclusions.json": canonical_json(result.report.to_dict()).encode("utf-8"),
        "reader_issues.json": canonical_json([i.to_dict() for i in replay.read.issues]).encode("utf-8"),
        "execution_report.json": (json.dumps(replay.report, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "execution_report.md": render_execution_report(replay.report).encode("utf-8"),
    }


def write_artifacts(out_root: Path, replay: SeasonReplay) -> tuple[Path, bool]:
    """Write-once. Returns (directory, written); written is False when an identical artifact exists."""
    fingerprint = replay.result.results_fingerprint()
    directory = out_root / f"epa_{replay.season}_{fingerprint[:16]}"
    files = artifact_files(replay)
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    manifest = {**replay.result.manifest, "results_fingerprint": fingerprint, "files": digests}
    if directory.exists():
        existing = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if existing.get("results_fingerprint") != fingerprint or existing.get("files") != digests:
            raise FileExistsError(f"{directory} holds a different artifact; refusing to overwrite")
        return directory, False
    directory.mkdir(parents=True)
    for name, data in files.items():
        (directory / name).write_bytes(data)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return directory, True


def write_once_json(path: Path, value: Any) -> tuple[Path, bool]:
    """Write JSON unless an identical file exists; refuse to replace a different one."""
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"{path} holds different content; refusing to overwrite")
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, True


# --- rendering ---------------------------------------------------------------------


def _table(rows: list[tuple[str, Any]]) -> str:
    return "\n".join(["| Item | Value |", "|---|---|", *(f"| {k} | {v} |" for k, v in rows)])


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_fmt(v)}" for k, v in value.items()) or "none"
    return str(value)


def render_execution_report(report: dict[str, Any]) -> str:
    """Markdown rendering of build_execution_report's output."""
    run, ev, ma, te, out = report["run"], report["events"], report["matches"], report["teams"], report["outputs"]
    div, dq, ver = report["statbotics_divergence"], report["data_quality"], report["verification"]
    lines = [
        f"# STRATAI EPA replay — {report['season']}",
        "",
        "Successful real-data execution only. This report does not measure agreement with Statbotics'",
        "published values, and none is claimed. Algorithmic correctness is established separately by",
        "tests/test_ratings_epa_*.py.",
        "",
        _table([
            ("Results fingerprint", f"`{run['results_fingerprint']}`"),
            ("Input fingerprint", f"`{run['input_fingerprint']}`"),
            ("Initialization", run["initialization"]),
            ("Engine / reference", f"{run['engine_version']} / {run['reference_commit'][:7]}"),
            ("Libraries", _fmt(run["libraries"])),
            ("Raw payloads read", f"{run['data_snapshot']['raw_payloads_read']} (max id {run['data_snapshot']['max_raw_payload_id']})"),
        ]),
        "",
        "## Events",
        _table([("Canonical", ev["canonical"]), ("Excluded by reader", ev["excluded_by_reader"]),
                ("Given to engine", ev["given_to_engine"]), ("Filtered by engine", _fmt(ev["filtered_by_engine"])),
                ("Processed (at least one retained match)", ev["processed"])]),
        "",
        "## Matches",
        _table([("Canonical", ma["canonical"]), ("Excluded by reader", ma["excluded_by_reader"]),
                ("Given to engine", ma["given_to_engine"]), ("Filtered", _fmt(ma["filtered"])),
                ("Rejected", _fmt(ma["rejected"])), ("Processed", ma["processed"]), ("Updated", ma["updated"]),
                ("Skipped", _fmt(ma["skipped"])), ("Upcoming (predicted only)", ma["upcoming_predicted_only"]),
                ("With a zero-score alliance", ma["with_zero_score_alliance"])]),
        "",
        "## Teams and outputs",
        _table([("Teams rated", te["rated"]), ("Teams with qual updates", te["with_qual_updates"]),
                ("Teams with no completed match", te["without_any_completed_match"]),
                ("Match records", out["match_records"]), ("Team-events", out["team_events"]),
                ("Team-events using season-end rating (look-ahead)", out["team_events_season_end_lookahead"]),
                ("Team-seasons", out["team_seasons"]), ("Norm computed", out["norm_computed"])]),
        "",
        "## Initialization",
        _table([("Label", report["initialization"]["label"]),
                ("Prior source", report["initialization"]["prior_source"] or "none"),
                ("Teams by prior seasons", _fmt(report["initialization"]["coverage"])),
                ("Team districts derived from events", report["initialization"]["team_districts_derived"]),
                ("2026 isr teams (no mean reversion)", report["initialization"]["isr_teams_without_mean_reversion"]),
                ("District conflicts", len(report["initialization"]["district_conflicts"]))]),
        "",
        "## Availability (a value may be used only strictly after this time)",
        _table([(k, v) for k, v in report["availability"].items()]),
        "",
        "## Week-1 statistics and look-ahead",
        _table([(k, _fmt(v)) for k, v in report["year_stats"].items() if k != "comp_means"]
               + [("Week-1 matches", report["week_one_lookahead"]["week_one_matches"]),
                  ("Exposed matches (scheduled at or before the last week-1 match)",
                   report["week_one_lookahead"]["exposed_matches"]),
                  ("...of which after week 1", report["week_one_lookahead"]["exposed_matches_after_week_one"]),
                  ("Exposed share of processed matches", _fmt(report["week_one_lookahead"]["exposed_share_of_processed"]))]),
        "",
        report["week_one_lookahead"]["note"],
        "",
        "## Possible Statbotics divergences",
        _table([("Definite", _fmt(div["definite"])), ("Possible", _fmt(div["possible"])),
                ("Tie groups", div["tie_groups"]),
                ("Order-sensitive tie groups", "; ".join(", ".join(t["match_keys"]) for t in div["order_sensitive_tie_groups"]) or "none")]),
        "",
        "## Data quality",
        _table([("Reader issues", _fmt(dq["reader_issues"])),
                ("Alliances with a teleop residual", dq["breakdowns"]["teleop_residual_alliances"]),
                ("Residual |size| distribution", _fmt(dq["breakdowns"]["teleop_residual_abs_distribution"])),
                ("Alliances with negative foul points", dq["breakdowns"]["negative_foul_alliances"])]),
        "",
        "## Prediction sanity check (not a Statbotics comparison)",
        "| Group | Matches | Accuracy | Brier | Log loss | ECE |",
        "|---|---|---|---|---|---|",
        *(f"| {name} | {m['matches']} | {_fmt(m['accuracy'])} | {_fmt(m['brier'])} | {_fmt(m['log_loss'])} | "
          f"{_fmt(m['ece_10_bins'])} |" for name, m in report["prediction_sanity_check"].items()),
        "",
        "## Verification",
    ]
    if ver.get("performed"):
        det, res = ver["determinism"], ver["resume"]
        lines.append(_table([("Re-read input identical", det["reread_input_identical"]),
                             ("Re-read reader issues identical", det["reread_issues_identical"]),
                             ("Re-run results fingerprint identical", det["rerun_results_fingerprint_identical"]),
                             ("Snapshot/resume", "; ".join(f"cut {c['cut_index']}: {c['records_identical']}"
                                                           for c in res["checks"]))]))
    else:
        lines.append("Not performed for this run.")
    return "\n".join(lines) + "\n"
