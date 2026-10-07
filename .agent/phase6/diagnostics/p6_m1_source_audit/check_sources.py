"""Audit: the stored rulesets' citations and quotations against the official FIRST PDFs (text extracted with pypdf).

Checks:
- (a) every section reference '§X ... p.N' lies within that section's pages;
- (b) every single-quoted phrase in the stored rulesets appears verbatim in an official source (whitespace and
  apostrophes normalized; ' ... ' marks an ellipsis);
- (c) the manual version strings against the PDF page footers;
- (d) the PDF sha256 against sources.json."""

import hashlib
import json
import pathlib
import re

A = pathlib.Path(r"C:\Users\Kanav\AppData\Local\Temp\claude\c--Dev-StratAI\7c888c37-aa1f-476d-a442-bd691493b99d\scratchpad\audit")
D = A.parent / "first_docs"
SRC = json.loads(pathlib.Path(r"C:\Dev\StratAI\.agent\phase6\rulesets_research\sources.json").read_text(encoding="utf-8"))
FILES = {2024: ("2024_2024GameManual", "2024_TeamUpdates-combined"),
         2025: ("2025_2025GameManual", "2025_TeamUpdate-Combined"),
         2026: ("2026_2026GameManual", "2026_REBUILT_TeamUpdate-Combined")}
EXTRA = ["2025_alliance-selection-changes.txt", "2025_mc-training.txt", "dl_alliance-selection-script.txt",
         "dl_alliance-selection-process.txt", "dl_2026-alliance-selection-script.txt"]


def pages(name):
    text = (D / f"{name}.txt").read_text(encoding="utf-8")
    parts = re.split(r"=====PAGE (\d+)=====\n", text)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def section_pages(pg, section):
    """First and last page of a numbered section heading (body, not the table of contents)."""
    heading = re.compile(rf"^\s*{re.escape(section)}\s+[A-Z0-9]", re.M)
    starts = [n for n, t in pg.items() if n > 10 and heading.search(t)]
    if not starts:
        return None
    start = min(starts)
    depth = section.count(".")
    nxt = None
    parts = section.split(".")
    # the next sibling or parent section heading after `start`
    for n in sorted(pg):
        if n < start:
            continue
        for m in re.finditer(r"^\s*(\d+(?:\.\d+)*)\s+[A-Z]", pg[n], re.M):
            num = m.group(1).split(".")
            if num == parts or (n == start and m.start() <= heading.search(pg[start]).start()):
                continue
            if len(num) <= depth + 1 and num[:len(num)] != parts[:len(num)] and num > parts[:len(num)]:
                nxt = n
                break
        if nxt:
            break
    return start, (nxt or start)


report = {}
for y, (gm, tu) in FILES.items():
    out = {}
    gmp, tup = pages(gm), pages(tu)
    gm_all, tu_all = norm(" ".join(gmp.values())), norm(" ".join(tup.values()))
    extra_all = norm(" ".join((D / f).read_text(encoding="utf-8") for f in EXTRA))
    stored = json.loads((A / f"stored_{y}.json").read_text(encoding="utf-8"))
    blob = json.dumps(stored, ensure_ascii=False)
    texts = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from walk(x)
        elif isinstance(v, list):
            for x in v:
                yield from walk(x)
        elif isinstance(v, str):
            yield v
    texts = list(walk(stored))
    # (a) section references
    refs = sorted({(m.group(1), m.group(2)) for t in texts
                   for m in re.finditer(r"§\s?(\d+(?:\.\d+)*)(?: Table [\d-]+)?[^;§']*?pp?\.\s?(\d+)(?:-(\d+))?", t)})
    checks = []
    for section, page in refs:
        span = section_pages(gmp, section)
        ok = span is not None and span[0] <= int(page) <= max(span[1], span[0])
        checks.append({"ref": f"§{section} p.{page}", "section_pages": span, "ok": ok})
    out["section_refs"] = checks
    # (b) quotations
    quotes = []
    for t in texts:
        for q in re.findall(r"'([^']{12,})'", t):
            for frag in [f for f in re.split(r"\s*\.\.\.\s*", q) if len(f) >= 8]:
                f = norm(frag)
                where = ("game_manual" if f in gm_all else "team_updates" if f in tu_all
                         else "first_volunteer_docs" if f in extra_all else None)
                quotes.append({"fragment": frag, "found_in": where})
    out["quotes"] = quotes
    # (c) versions from footers
    footers = sorted({m.group(0).strip() for t in gmp.values()
                      for m in re.finditer(r"Section 1[0-3] [A-Za-z ()]+(?:V\d+|Version: TU\d+)", t)})
    out["footers"] = footers
    out["cover_version"] = re.findall(r"Version: TU\d+", gmp[1])
    # (d) hashes
    out["sha_manual_ok"] = hashlib.sha256((D / f"{gm}.pdf").read_bytes()).hexdigest() == SRC["seasons"][str(y)]["game_manual"]["sha256"]
    out["sha_tu_ok"] = hashlib.sha256((D / f"{tu}.pdf").read_bytes()).hexdigest() == SRC["seasons"][str(y)]["team_updates"]["sha256"]
    report[str(y)] = out

(A / "source_checks.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
for y, o in report.items():
    bad_refs = [c for c in o["section_refs"] if not c["ok"]]
    missing = [q for q in o["quotes"] if q["found_in"] is None]
    print(y, "refs:", len(o["section_refs"]), "bad:", bad_refs)
    print("   quotes:", len(o["quotes"]), "not found:", [q["fragment"][:90] for q in missing])
    print("   footers:", o["footers"], o["cover_version"], "| pdf sha ok:", o["sha_manual_ok"], o["sha_tu_ok"])
