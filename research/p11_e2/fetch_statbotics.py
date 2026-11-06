"""P11A E2 research: download Statbotics events and matches for one season, raw-first.

    python -I research/p11_e2/fetch_statbotics.py --season 2024 --out research/p11_e2/cache/raw [--budget-minutes 40]

Research tooling only (not production; nothing imports it). Every API page is written unmodified to
<out>/<season>/<kind>_<offset>.json, and a manifest records each page's URL, fetch time, byte count and sha256. Pages
already present (same URL) are not re-fetched. 2027 is refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx  # verifies TLS against certifi's CA bundle (this Python build has none of its own)

BASE = "https://api.statbotics.io/v3"
PAGE = 1000
ALLOWED_SEASONS = (2024, 2025, 2026)  # the 2027 holdout is never requested


def fetch(url: str) -> bytes:
    response = httpx.get(url, headers={"User-Agent": "stratai-research-benchmark"}, timeout=60.0)
    response.raise_for_status()
    return response.content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget-minutes", type=float, default=40.0)
    args = parser.parse_args(argv)
    if args.season not in ALLOWED_SEASONS:
        parser.error(f"season must be one of {ALLOWED_SEASONS} (2027 is a reserved holdout)")
    if not 0 < args.budget_minutes <= 45:
        parser.error("--budget-minutes must be in (0, 45]")
    deadline = time.monotonic() + args.budget_minutes * 60
    folder = args.out / str(args.season)
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"pages": []}
    have = {p["url"] for p in manifest["pages"]}
    partial = False
    for kind in ("events", "matches"):
        offset = 0
        while True:
            if time.monotonic() > deadline:
                partial = True
                break
            url = f"{BASE}/{kind}?year={args.season}&limit={PAGE}&offset={offset}"
            path = folder / f"{kind}_{offset:06d}.json"
            if url in have and path.exists():
                body = path.read_bytes()
            else:
                body = fetch(url)
                path.write_bytes(body)
                manifest["pages"].append({"url": url, "file": path.name, "kind": kind,
                                          "fetched_at": datetime.now(timezone.utc).isoformat(),
                                          "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
                manifest_path.write_text(json.dumps(manifest, indent=1))
                time.sleep(0.5)
            rows = json.loads(body)
            if not isinstance(rows, list):
                raise SystemExit(f"unexpected response for {url}")
            if len(rows) < PAGE:
                break
            offset += PAGE
        if partial:
            break
    manifest["partial"] = partial
    manifest_path.write_text(json.dumps(manifest, indent=1))
    counts = {}
    for page in manifest["pages"]:
        counts[page["kind"]] = counts.get(page["kind"], 0) + len(json.loads((folder / page["file"]).read_bytes()))
    print(json.dumps({"season": args.season, "pages": len(manifest["pages"]), "rows": counts, "partial": partial}))
    return 1 if partial else 0


if __name__ == "__main__":
    sys.exit(main())
