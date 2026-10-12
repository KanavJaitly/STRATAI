"""Game Manual Manager: deterministic processing of an uploaded official game manual (2026-10-11).

A manual is uploaded write-once by `data.human_inputs.store_manual` (unchanged). This module processes the stored
PDF into reviewable artifacts that make the human's work faster. It never makes anything authoritative.

**What it does, deterministically (no LLM ever reads the manual: CLAUDE.md, P5-M8):**
1. Integrity: the stored file's sha256 equals the recorded one; PDF magic; size; parseable; not encrypted; page count.
2. Text and page structure: per-page text (pypdf), each page's sha256, an image-only (unextractable) page warning.
3. Identity: the season and revision detected on the title pages. A season contradicting the declared one fails
   closed (`wrong_season`). An undetectable season needs a named person's explicit resolution.
4. A section index (numbered headings) and a topic index (match play, scoring, ranking points, alliance selection,
   playoffs, field, endgame, Team Updates), each with page references.
5. **Suggestions:** values found by fixed patterns (period lengths, alliance count, point values, ranking-point
   sentences, playoff format), each with its page and the exact snippet. All are labelled
   `machine_extracted_unverified`.

**What it never does:**
- write a game spec (P5-M8 specs are human-entered) or a season ruleset (P6-M1 needs a named, qualified reviewer);
- approve anything, run an evaluation, or touch a model or the canonical match data.

**Storage:** a filesystem ledger beside the stored PDFs (`<artifact_store_dir>/manual_processing/<sha256>/<processor>/`),
so no database migration is needed.
- `extraction.json` and `report.json` are write-once and deterministic for the same PDF and processor version. A
  retry reproduces them byte for byte, or refuses.
- `attempts.jsonl` is append-only.
- `identity_resolution.json` is write-once.
- `lock` exists only while a run is in progress.

**Idempotency:** a succeeded run is never repeated (its artifacts are returned); a run in progress is not
duplicated; a failed run, or a run whose lock is stale (> 30 minutes), may be retried.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROCESSOR_VERSION = "manual-proc-v1"
MAX_PAGES = 1000
MIN_TEXT_PAGE_SHARE = 0.5  # below this, the PDF is mostly images: extraction is refused as unreviewable
STALE_LOCK = timedelta(minutes=30)
STATUSES = ("not_started", "running", "succeeded", "failed", "needs_resolution")
MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")

TOPICS: dict[str, tuple[str, ...]] = {
    "match_play": (r"\bAUTO\b", r"\bTELEOP\b", r"\bTELE-OP\b", r"\bmatch period\b"),
    "scoring": (r"\bpoints?\b", r"\bscor(?:e|es|ed|ing)\b"),
    "ranking_points": (r"\bRanking Points?\b", r"\bRP\b"),
    "endgame": (r"\bEND\s?GAME\b", r"\bENDGAME\b"),
    "alliance_selection": (r"\bAlliance Selection\b", r"\bALLIANCE SELECTION\b", r"\bALLIANCE CAPTAIN\b"),
    "playoffs": (r"\bPlayoffs?\b", r"\bPLAYOFFS?\b", r"\bdouble[- ]elimination\b", r"\bFinals\b"),
    "field": (r"\bARENA\b", r"\bFIELD\b"),
    "team_updates": (r"\bTeam Update\b",),
}
# Topics a complete game manual is expected to cover; a missing one is a warning, not a failure.
EXPECTED_TOPICS = ("match_play", "scoring", "ranking_points", "alliance_selection", "playoffs")


class ManualProcessingError(ValueError):
    """A refused operation; `code` is machine-readable."""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code, self.details = code, details


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _write_once(path: Path, content: bytes) -> None:
    """Atomic and write-once: an existing file must already hold exactly these bytes."""
    if path.exists():
        if path.read_bytes() != content:
            raise ManualProcessingError("storage_integrity", f"{path.name} exists with different content: "
                                                             "processing artifacts are write-once")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def ledger_dir(store_dir: Path, sha256: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ManualProcessingError("invalid_input", "a manual sha256 must be 64 lowercase hex characters")
    return Path(store_dir) / "manual_processing" / sha256 / PROCESSOR_VERSION


def _attempts(directory: Path) -> list[dict[str, Any]]:
    path = directory / "attempts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _attempt_entries(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per attempt, in order: its start line merged with its outcome line.

    The ledger itself stays append-only, with two lines per attempt. It is read, never rewritten (2026-10-12, D1)."""
    merged: dict[Any, dict[str, Any]] = {}
    for line in lines:
        merged.setdefault(line.get("attempt"), {}).update({k: v for k, v in line.items() if v is not None})
    return list(merged.values())


def _next_attempt(lines: list[dict[str, Any]]) -> int:
    """The next attempt number: after the highest recorded one, never the count of ledger lines (D1)."""
    return max((line.get("attempt") or 0 for line in lines), default=0) + 1


def _append_attempt(directory: Path, entry: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "attempts.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


def _read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --- the steps ---------------------------------------------------------------------------------------------------


def _open_pdf(content: bytes):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if not content.startswith(b"%PDF-"):
        raise ManualProcessingError("not_a_pdf", "the file is not a PDF (missing the %PDF- header)")
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise ManualProcessingError("encrypted_pdf", "the PDF is encrypted; upload an unencrypted official "
                                                         "manual")
        pages = len(reader.pages)
    except ManualProcessingError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
        raise ManualProcessingError("malformed_pdf", f"the PDF cannot be read: {type(exc).__name__}: {exc}") from exc
    if not 1 <= pages <= MAX_PAGES:
        raise ManualProcessingError("malformed_pdf", f"the PDF has {pages} pages (1 to {MAX_PAGES} accepted)")
    return reader


def extract_pages(content: bytes) -> list[dict[str, Any]]:
    """Per-page text with each page's sha256. A page whose text cannot be extracted is kept, empty, and flagged."""
    reader = _open_pdf(content)
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 -- one unreadable page is recorded, never fatal by itself
            text, error = "", f"{type(exc).__name__}: {exc}"
        else:
            error = None
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        pages.append({"page": number, "chars": len(text.strip()), "text": text,
                      "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "error": error})
    return pages


def detect_identity(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """The season, game name and revision found on the first pages, with the evidence. Never decides alone: the
    caller compares it with the declared season."""
    head = "\n".join(p["text"] for p in pages[:3])
    anchored = re.findall(r"\b(20\d\d)\b[^\n]{0,80}?(?:Robotics Competition|Game Manual)", head, re.IGNORECASE)
    anchored += re.findall(r"(?:Robotics Competition|Game Manual)[^\n]{0,80}?\b(20\d\d)\b", head, re.IGNORECASE)
    years = sorted({int(y) for y in anchored})
    revision = re.search(r"\b(?:Rev(?:ision)?\.?|Version)\s*([0-9]+[A-Za-z0-9.]*)", head)
    team_update = re.search(r"\bTeam Update\s*([0-9]{1,3})\b", head)
    date = re.search(rf"\b(?:{MONTHS})\s+\d{{1,2}},\s+20\d\d\b", head)
    title = next((line.strip() for line in head.splitlines() if re.search(r"Game Manual", line, re.IGNORECASE)), None)
    return {"seasons_found": years, "season": years[0] if len(years) == 1 else None,
            "revision": revision.group(1) if revision else None,
            "team_update": int(team_update.group(1)) if team_update else None,
            "date": date.group(0) if date else None, "title_line": title}


def _snippet(text: str, start: int, end: int, width: int = 60) -> str:
    return " ".join(text[max(0, start - width):min(len(text), end + width)].split())


def index_sections(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Numbered headings (`5.2 MATCH Overview`): the section number, its title and the page it starts on."""
    seen, sections = set(), []
    pattern = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-Z][^\n]{2,90})$", re.MULTILINE)
    for page in pages:
        for match in pattern.finditer(page["text"]):
            number, title = match.group(1), " ".join(match.group(2).split())
            if number in seen or re.search(r"\.{4,}|\s\d+$", title):  # skip table-of-contents lines
                continue
            seen.add(number)
            sections.append({"number": number, "title": title[:90], "page": page["page"]})
    return sections


def index_topics(pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    topics = {}
    for name, patterns in TOPICS.items():
        hits = {}
        for page in pages:
            count = sum(len(re.findall(p, page["text"])) for p in patterns)
            if count:
                hits[page["page"]] = count
        top = sorted(hits, key=lambda p: (-hits[p], p))[:10]
        topics[name] = {"pages": sorted(hits), "top_pages": top, "mentions": sum(hits.values())}
    return topics


SUGGESTION_RULES: list[tuple[str, str, str]] = [
    # (rule id, target field, pattern); every value is unverified until a person checks the cited page
    ("auto_seconds", "game_spec.match_length.auto_seconds",
     r"\bAUTO(?:NOMOUS)?\b[^.\n]{0,80}?\b(\d{1,3})\s*(?:\(\d+\)\s*)?seconds?\b"),
    ("teleop_seconds", "game_spec.match_length.teleop_seconds",
     r"\bTELE-?OP\b[^.\n]{0,80}?\b(\d{1,3})\s*(?:\(\d+\)\s*)?seconds?\b"),
    ("teleop_minutes", "game_spec.match_length.teleop_minutes_seconds",
     r"\bTELE-?OP\b[^.\n]{0,80}?\b(\d)\s*minutes?(?:\s*(?:and\s*)?(\d{1,2})\s*seconds?)?"),
    ("alliance_count", "ruleset.alliance_counts.alliances",
     r"\b(?:eight|six|four|\d{1,2})\s*\(?(\d{1,2})?\)?\s+(?:Playoff\s+)?ALLIANCES?\b"),
    ("point_value", "game_spec.scoring_actions.points",
     r"\b([A-Z][A-Za-z0-9 '/()-]{2,50}?)\s*[:\-–]?\s*\b(\d{1,3})\s*(?:points?|pts)\b"),
    ("ranking_point", "game_spec.ranking_point_rules",
     r"[^.\n]{0,120}\bRanking Points?\b[^.\n]{0,160}"),
    ("playoff_format", "ruleset.brackets.format",
     r"\b(double[- ]elimination|best[- ]of[- ]three|single[- ]elimination)\b"),
]
NUMBER_WORDS = {"four": 4, "six": 6, "eight": 8}


def suggest(pages: list[dict[str, Any]], limit_per_rule: int = 40) -> list[dict[str, Any]]:
    """Every pattern hit with its page and exact snippet, in page order. Unverified by construction."""
    suggestions = []
    for rule, target, pattern in SUGGESTION_RULES:
        found = 0
        for page in pages:
            for match in re.finditer(pattern, page["text"], re.IGNORECASE if rule != "point_value" else 0):
                if found >= limit_per_rule:
                    break
                if rule == "teleop_seconds" and re.search(r"minute", match.group(0), re.IGNORECASE):
                    continue  # "2 minutes and 15 seconds" is the teleop_minutes rule's, never 15 s
                if rule == "ranking_point" and len(match.group(0).strip()) < 25:
                    continue  # a heading ("6.3 Ranking Points"), not a rule sentence
                value: Any
                if rule == "teleop_minutes":
                    value = int(match.group(1)) * 60 + int(match.group(2) or 0)
                elif rule == "alliance_count":
                    word = match.group(0).split()[0].lower()
                    value = int(match.group(1)) if match.group(1) else NUMBER_WORDS.get(word, int(word)
                                                                                       if word.isdigit() else None)
                    if value is None or not 2 <= value <= 16:
                        continue
                elif rule == "point_value":
                    value = {"action": " ".join(match.group(1).split()), "points": int(match.group(2))}
                elif rule in ("ranking_point", "playoff_format"):
                    value = " ".join(match.group(0 if rule == "ranking_point" else 1).split())
                else:
                    value = int(match.group(1))
                suggestions.append({"rule": rule, "target": target, "value": value, "page": page["page"],
                                    "snippet": _snippet(page["text"], match.start(), match.end()),
                                    "status": "machine_extracted_unverified"})
                found += 1
    return suggestions


# --- the run ------------------------------------------------------------------------------------------------------


def _identity_decision(identity: dict[str, Any], declared: int, resolution: dict[str, Any] | None) -> tuple[str, str]:
    """(status, reason): the declared season must match the detected one, or a named person must resolve it."""
    found = identity["seasons_found"]
    if declared in found and len(found) == 1:
        return "identified", f"the title pages name {declared}"
    if found and declared not in found:
        return "wrong_season", f"the title pages name {found}, not the declared season {declared}"
    if resolution is not None and resolution.get("season") == declared:
        return "resolved", f"resolved by {resolution['resolved_by']}: {resolution.get('note') or 'no note'}"
    return "ambiguous", ("no season could be read from the title pages" if not found
                         else f"the title pages name several seasons: {found}")


def manual_meta(database, manual_id: int) -> dict[str, Any]:
    """The manual's row only (no file read), so status stays readable even when the stored file is damaged."""
    with database.cursor() as cursor:
        cursor.execute("SELECT * FROM game_manuals WHERE id = %s", (manual_id,))
        row = cursor.fetchone()
        columns = [d[0] for d in cursor.description]
    if row is None:
        raise ManualProcessingError("not_found", f"no manual {manual_id}")
    return dict(zip(columns, row))


def _manual_content(database, manual_id: int) -> bytes:
    """The stored bytes, verified against the recorded sha256 by the existing reader (fail-closed)."""
    from data.human_inputs import HumanInputError, manual_file

    try:
        return manual_file(database, manual_id)[1]
    except HumanInputError as exc:
        raise ManualProcessingError("hash_mismatch" if exc.code == "storage_integrity" else exc.code, str(exc)) from exc


def _manual_row(database, manual_id: int) -> tuple[dict[str, Any], bytes]:
    return manual_meta(database, manual_id), _manual_content(database, manual_id)


def status(store_dir: Path, manual: dict[str, Any]) -> dict[str, Any]:
    """The processing state of a stored manual, from its ledger only (reads nothing else)."""
    directory = ledger_dir(store_dir, manual["content_sha256"])
    attempts = _attempt_entries(_attempts(directory))
    report = _read_json(directory / "report.json")
    lock = _read_json(directory / "lock")
    if report is not None:
        state = report["status"]
    elif lock is not None and not _stale(lock):
        state = "running"
    elif attempts:
        state = attempts[-1].get("status", "failed")
        if state == "running":  # the run ended without finishing (a crash or a stale lock)
            state = "failed"
    else:
        state = "not_started"
    return {"manual_id": manual["id"], "season": manual["season"], "content_sha256": manual["content_sha256"],
            "processor_version": PROCESSOR_VERSION, "status": state, "attempts": attempts, "report": report,
            "identity_resolution": _read_json(directory / "identity_resolution.json"),
            "retry_allowed": state in ("failed", "not_started") or (state == "needs_resolution"
                                                                   and _read_json(directory / "identity_resolution.json")
                                                                   is not None and report is None)}


def _stale(lock: dict[str, Any]) -> bool:
    return _now() - datetime.fromisoformat(lock["started_at"]) > STALE_LOCK


def _acquire(directory: Path, requested_by: str) -> bool:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "lock"
    if path.exists():
        lock = _read_json(path)
        if lock is not None and not _stale(lock):
            return False
        path.unlink()  # a stale lock: the earlier run died; it is recorded as failed in status()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False  # a concurrent request won
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"started_at": _now().isoformat(), "requested_by": requested_by, "pid": os.getpid()}, handle)
    return True


def start(database, store_dir: Path, manual_id: int, *, requested_by: str) -> dict[str, Any]:
    """Claim the run (idempotent). Returns the status; `claimed` is true only if the caller must now call `run`."""
    if not (requested_by or "").strip():
        raise ManualProcessingError("invalid_input", "requested_by must name the person starting the processing")
    manual = manual_meta(database, manual_id)
    current = status(store_dir, manual)
    if current["status"] in ("succeeded",) or current["status"] == "running":
        return {**current, "claimed": False}
    if current["status"] == "needs_resolution" and current["identity_resolution"] is None:
        return {**current, "claimed": False}
    directory = ledger_dir(store_dir, manual["content_sha256"])
    if current["report"] is not None:  # a final report exists (succeeded, or a write-once refusal): never redone
        return {**current, "claimed": False}
    claimed = _acquire(directory, requested_by.strip())
    return {**status(store_dir, manual), "claimed": claimed}


def run(database, store_dir: Path, manual_id: int, *, requested_by: str) -> dict[str, Any]:
    """Process a claimed manual. Every outcome is recorded; the lock is always released."""
    manual = manual_meta(database, manual_id)
    directory = ledger_dir(store_dir, manual["content_sha256"])
    attempt = _next_attempt(_attempts(directory))
    started = _now()
    _append_attempt(directory, {"attempt": attempt, "status": "running", "started_at": started.isoformat(),
                                "requested_by": requested_by})
    try:
        outcome = _process(manual, _manual_content(database, manual_id), directory)
        _append_attempt(directory, {"attempt": attempt, "status": outcome, "finished_at": _now().isoformat()})
    except ManualProcessingError as exc:
        _append_attempt(directory, {"attempt": attempt, "status": "failed", "finished_at": _now().isoformat(),
                                    "error": {"code": exc.code, "message": str(exc)}})
    except Exception as exc:  # noqa: BLE001 -- recorded and retryable, never swallowed silently
        _append_attempt(directory, {"attempt": attempt, "status": "failed", "finished_at": _now().isoformat(),
                                    "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}})
    finally:
        (directory / "lock").unlink(missing_ok=True)
    return status(store_dir, manual)


def _process(manual: dict[str, Any], content: bytes, directory: Path) -> str:
    sha = hashlib.sha256(content).hexdigest()
    if sha != manual["content_sha256"]:
        raise ManualProcessingError("hash_mismatch", "the stored file does not hash to the recorded sha256")
    pages = extract_pages(content)
    text_pages = sum(1 for p in pages if p["chars"] > 0)
    if text_pages / len(pages) < MIN_TEXT_PAGE_SHARE:
        raise ManualProcessingError("unreadable_text", f"only {text_pages} of {len(pages)} pages have extractable "
                                                       "text (a scanned manual?); OCR is not supported")
    identity = detect_identity(pages)
    resolution = _read_json(directory / "identity_resolution.json")
    decision, reason = _identity_decision(identity, manual["season"], resolution)
    identity_block = {**identity, "declared_season": manual["season"], "decision": decision, "reason": reason}
    if decision == "wrong_season":
        raise ManualProcessingError("wrong_season", reason)
    if decision == "ambiguous":
        _write_once(directory / "identity.json", _canonical(identity_block))
        return "needs_resolution"
    extraction = {"processor_version": PROCESSOR_VERSION, "manual_sha256": sha, "season": manual["season"],
                  "page_count": len(pages), "identity": identity_block,
                  "pages": [{k: p[k] for k in ("page", "chars", "text_sha256", "error", "text")} for p in pages],
                  "sections": index_sections(pages), "topics": index_topics(pages), "suggestions": suggest(pages)}
    _write_once(directory / "extraction.json", _canonical(extraction))
    warnings = []
    for page in pages:
        if page["error"]:
            warnings.append({"code": "page_unreadable", "page": page["page"], "message": page["error"]})
        elif page["chars"] == 0:
            warnings.append({"code": "page_without_text", "page": page["page"], "message": "no extractable text"})
    for topic in EXPECTED_TOPICS:
        if not extraction["topics"][topic]["pages"]:
            warnings.append({"code": "topic_not_found", "topic": topic,
                             "message": f"no page mentions {topic.replace('_', ' ')}: check the manual is complete"})
    report = {"status": "succeeded", "processor_version": PROCESSOR_VERSION, "manual_sha256": sha,
              "season": manual["season"], "page_count": len(pages), "text_pages": text_pages,
              "identity": identity_block, "sections": len(extraction["sections"]),
              "suggestions": len(extraction["suggestions"]),
              "extraction_sha256": hashlib.sha256(_canonical(extraction)).hexdigest(),
              "warnings": warnings, "authoritative": False,
              "note": "Extraction and suggestions are review aids. The game spec (P5-M8) and the season ruleset "
                      "(P6-M1) are entered and approved by people; nothing here approves or runs anything."}
    _write_once(directory / "report.json", _canonical(report))
    return "succeeded"


def resolve_identity(database, store_dir: Path, manual_id: int, *, season: int, resolved_by: str,
                     note: str = "") -> dict[str, Any]:
    """A named person confirms the season of a manual whose title pages do not identify it (write-once). A
    contradiction (`wrong_season`) cannot be resolved this way: upload the manual under its own season."""
    if not (resolved_by or "").strip():
        raise ManualProcessingError("invalid_input", "resolved_by must name the person resolving the identity")
    manual = manual_meta(database, manual_id)
    if season != manual["season"]:
        raise ManualProcessingError("wrong_season", f"the manual was uploaded for {manual['season']}; a different "
                                                    "season needs a new upload under that season")
    directory = ledger_dir(store_dir, manual["content_sha256"])
    identity = _read_json(directory / "identity.json")
    if identity is None or identity.get("decision") != "ambiguous":
        raise ManualProcessingError("invalid_state", "only a manual whose identity is ambiguous needs resolution")
    _write_once(directory / "identity_resolution.json", _canonical(
        {"season": season, "resolved_by": resolved_by.strip(), "note": note.strip() or None,
         "resolved_at": _now().isoformat(), "detected": identity}))
    return status(store_dir, manual)


def extraction(store_dir: Path, manual: dict[str, Any]) -> dict[str, Any] | None:
    return _read_json(ledger_dir(store_dir, manual["content_sha256"]) / "extraction.json")


def pages(store_dir: Path, manual: dict[str, Any], first: int, last: int) -> list[dict[str, Any]]:
    data = extraction(store_dir, manual)
    if data is None:
        raise ManualProcessingError("not_found", "the manual has not been processed")
    return [p for p in data["pages"] if first <= p["page"] <= last]
