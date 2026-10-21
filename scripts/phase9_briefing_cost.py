"""P9-M6: the cost of the LLM briefing per event.

    python -m scripts.phase9_briefing_cost --event 2026mrcmp [--limit 40] [--seed 9] [--measure] [--out FILE]

For a seeded sample of the event's qualification matches, the pre-match report is built on the isolated database in
`DATABASE_URL` (a `stratai_test*` copy only; nothing is written). Each report is turned into the exact Messages API
request the formatter would send (`briefing.llm.request_params`). The tool then records:
- **Sizes (always):** the bytes of the cached system prompt, of the per-match facts message, and of a reference
  arrangement (the output a faithful model returns: every fact once, one item per team). These are measured.
- **Tokens (`--measure`, needs a credential):** `count_tokens` for the system prompt plus the facts message, and for
  the reference arrangement as text (an estimate of the output tokens), for each priced model. `count_tokens` is
  free and samples nothing. Without a credential this part is reported as BLOCKED (P9-R1); no token count is
  invented here.
- **Cost per event:** from measured tokens only, with the dated price table below, for one briefing per
  qualification match. It gives three figures:
  - cache warm: the first briefing writes the system-prompt cache and every later one reads it (P9-Q10);
  - every call writes: the cache always expires between briefings (the 5-minute TTL), the worst cached case;
  - no caching: the prefix is below the model's minimum cacheable size (512 tokens on the current models), so
    nothing is cached (P9-R11).

**Every figure is a LOWER BOUND on output** (review R2 C7):
- the output count is the visible arrangement only. On claude-opus-5-5 thinking is always on (effort "medium"),
  and thinking tokens bill as output; only a real call's `usage` shows them;
- the structured-output schema's tokens are not in the input count;
- refusal-fallback attempts are not modelled.

Nothing here calls the model to generate text.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from briefing.facts import Fact, report_facts
from briefing.llm import SYSTEM_PROMPT, credential_available, request_params
from briefing.render import SECTION_TITLES

# USD per million tokens: (input, output). From the claude-api skill's model table, cached 2026-10-06. Haiku's price
# is for prompts of 100K tokens or fewer, as these are. Cache writes (5-minute TTL) bill at 1.25x input. Cache reads
# bill at 0.05x input on Opus 5.5 ($0.20) and 0.1x on the others (shared/prompt-caching.md, Economics).
PRICES_AS_OF = "2026-10-06"
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}
CACHE_WRITE = 1.25
CACHE_READ = {"claude-opus-5-5": 0.05, "claude-sonnet-5-5": 0.10, "claude-haiku-5-5": 0.10}
TIME_BUDGET_SECONDS = 20 * 60  # CLAUDE.md: a verification run stops and reports partial results well within 45 min


def reference_arrangement(facts: list[Fact]) -> str:
    """What a faithful model returns: one item per team (lead "Team record:"), one per other fact, in reading order.
    Its size stands in for the output, which the model writes as JSON ids plus short lead-ins."""
    sections: dict[str, list[dict[str, Any]]] = {}
    groups: dict[str, dict[str, Any]] = {}
    for fact in facts:
        parts = fact.id.split(".")
        team = fact.section in ("red", "blue") and len(parts) > 1 and parts[1].isdigit()
        key = ".".join(parts[:2]) if team else fact.id
        if key not in groups:
            groups[key] = {"lead": "Team record:" if team else "", "fact_ids": []}
            sections.setdefault(SECTION_TITLES[fact.section], []).append(groups[key])
        groups[key]["fact_ids"].append(fact.id)
    return json.dumps({"sections": [{"heading": h, "items": sections[h]} for h in SECTION_TITLES.values()
                                    if h in sections]})


def _isolated(url: str) -> bool:
    return re.search(r"/stratai_test(?:_[a-z0-9_]+)?$", url) is not None


def sample_matches(event: str, database_url: str, limit: int, seed: int) -> tuple[list[str], int]:
    import psycopg

    with psycopg.connect(database_url) as conn:
        rows = conn.execute("SELECT match_key FROM matches WHERE event_key = %s AND competition_level = 'qualification' "
                            "ORDER BY match_key", (event,)).fetchall()
    keys = [r[0] for r in rows]
    rng = random.Random(seed)
    return sorted(rng.sample(keys, min(limit, len(keys)))), len(keys)


def build_requests(event: str, matches: list[str], model: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from fastapi.testclient import TestClient

    from api import create_app
    from data.config import Settings

    started = time.monotonic()
    rows, refused = [], {}
    with TestClient(create_app(Settings(api_prefix=""))) as client:
        for match in matches:
            if time.monotonic() - started > TIME_BUDGET_SECONDS:
                break
            response = client.get(f"/matches/{match}/pre-match-report")
            if response.status_code != 200:
                code = response.json().get("error", {}).get("code")
                refused[match] = code
                continue
            facts = report_facts(response.json())
            params = request_params(facts, model, 16000)
            rows.append({"match": match, "facts": len(facts),
                         "user_bytes": len(params["messages"][0]["content"].encode()),
                         "output_bytes": len(reference_arrangement(facts).encode()),
                         "params": params, "arrangement": reference_arrangement(facts)})
    elapsed = round(time.monotonic() - started, 1)
    return rows, {"refused": refused, "elapsed_seconds": elapsed,
                  "stopped_by_time_budget": len(rows) + len(refused) < len(matches)}


def measure_tokens(rows: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    """count_tokens per model: system + facts (input), and the reference arrangement as a message (output estimate)."""
    if not credential_available():
        return {"status": "BLOCKED", "reason": "no_credential (P9-R1)"}
    import anthropic

    client = anthropic.Anthropic(max_retries=1, timeout=30.0)
    out: dict[str, Any] = {"status": "measured", "models": {}}
    for model in models:
        system_only = client.messages.count_tokens(model=model, system=SYSTEM_PROMPT,
                                                   messages=[{"role": "user", "content": "x"}]).input_tokens
        per_match = []
        for row in rows:
            params = row["params"]
            full = client.messages.count_tokens(model=model, system=params["system"],
                                                messages=params["messages"]).input_tokens
            output = client.messages.count_tokens(model=model, messages=[
                {"role": "user", "content": row["arrangement"]}]).input_tokens
            per_match.append({"match": row["match"], "input_tokens": full, "output_tokens_estimate": output})
        out["models"][model] = {"system_prompt_tokens_approx": system_only, "per_match": per_match}
    return out


def cost_per_event(measured: dict[str, Any], qualification_matches: int) -> dict[str, Any]:
    if measured.get("status") != "measured":
        return {"status": "BLOCKED", "reason": "needs measured tokens"}
    costs = {}
    for model, data in measured["models"].items():
        price_in, price_out = PRICES[model]
        per = data["per_match"]
        system = data["system_prompt_tokens_approx"]
        mean_in = statistics.mean(p["input_tokens"] for p in per)
        mean_out = statistics.mean(p["output_tokens_estimate"] for p in per)
        user = max(mean_in - system, 0)
        n = qualification_matches
        output = n * mean_out * price_out / 1e6
        warm = (system * CACHE_WRITE + (n - 1) * system * CACHE_READ[model] + n * user) * price_in / 1e6 + output
        every_write = n * (system * CACHE_WRITE + user) * price_in / 1e6 + output
        no_cache = n * mean_in * price_in / 1e6 + output
        costs[model] = {"usd_per_event_cache_warm": round(warm, 4),
                        "usd_per_event_every_call_writes_cache": round(every_write, 4),
                        "usd_per_event_no_caching": round(no_cache, 4)}
    return {"status": "computed", "lower_bound": True, "prices_as_of": PRICES_AS_OF,
            "qualification_matches": qualification_matches, "costs": costs,
            "not_counted": ["thinking tokens (billed as output)", "the structured-output schema",
                            "refusal-fallback attempts"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--event", default="2026mrcmp")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--seed", type=int, default=9)
    parser.add_argument("--measure", action="store_true", help="count tokens with count_tokens (needs a credential)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    from data.config import Settings

    url = str(Settings().database_url)
    if not _isolated(url):
        raise SystemExit("refusing: DATABASE_URL must point at an isolated stratai_test* database")
    matches, total = sample_matches(args.event, url, args.limit, args.seed)
    rows, run = build_requests(args.event, matches, "claude-opus-5-5")
    system_bytes = len(SYSTEM_PROMPT.encode())
    schema_bytes = len(json.dumps(rows[0]["params"]["output_config"]).encode()) if rows else None

    def summary(key: str) -> dict[str, Any]:
        values = [r[key] for r in rows]
        return {"min": min(values), "median": statistics.median(values), "max": max(values)} if values else {}

    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(), "event": args.event,
        "epa_source": os.environ.get("EPA_SOURCE"), "seed": args.seed,
        "qualification_matches": total, "sampled": len(matches), "built": len(rows), **run,
        "models_loaded_note": "Reports are built with whatever models the API loads. Locally none are registered "
                              "(P9-R4): the forecast and strategy are absences, so real model-populated reports are "
                              "somewhat larger (more facts' worth of strategy text).",
        "sizes_bytes": {"system_prompt": system_bytes, "output_schema": schema_bytes,
                        "facts_message": summary("user_bytes"), "reference_output": summary("output_bytes")},
        "facts_per_report": summary("facts"),
        "tokens": measure_tokens(rows, list(PRICES)) if args.measure else
        {"status": "NOT_RUN" if credential_available() else "BLOCKED",
         "reason": "--measure not given" if credential_available() else "no_credential (P9-R1)"},
    }
    report["cost_per_event"] = cost_per_event(report["tokens"], total)
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
