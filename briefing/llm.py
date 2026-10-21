"""P9-M3: the LLM formatter. It is fail closed: it either returns a briefing that passes every fidelity check, or the
deterministic briefing with the reason why.

Design (decision P9-D1, revised after reviews R1 and R2): **the LLM never writes a word of the briefing.** It
arranges the facts:
- it groups them into items under the fixed section headings;
- it orders them;
- it may label an item with one of a closed list of topic labels (LEAD_INS), or none.

The text of every item is the label followed by **the cited facts' own statements, verbatim**. So:
- every number, label, caveat and absence is printed by the fact that owns it, next to its own subject;
- a value cannot be moved to another team or model, or turned into words;
- an absence or an unproduced item cannot be dropped or reworded;
- no slant can be written. Review R2 showed that free lead-ins, even short and filtered ones, can invert or slant
  the statement that follows ("Read as the blue side's figure:", "Unlikely:"). The labels name a topic only, and
  none names a side.

What the LLM gets:
- a frozen system prompt (the rules and the label list), byte-stable across matches so it can be cached (P9-Q10);
- the report's facts (briefing.facts) as the only input.

`validate` checks the structure (P9-Q6). If anything fails, **the whole arrangement is rejected and the
deterministic briefing is served**; there is no partial acceptance. The rules:
- the output has exactly the documented shape (duplicate JSON keys are refused). Headings come from the fixed list,
  each appears at most once, and they are in reading order;
- every cited id exists, and every fact is cited **exactly once**, under its own section's heading;
- every lead-in is empty or exactly one of LEAD_INS.

Nothing here runs unless `briefing_llm_enabled` and `briefing_data_egress_approved` are both true and a credential
resolves (P9-Q3, P9-Q4). The credential is never read into this module's state, logs or results (P9-Q11).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from briefing.facts import Fact
from briefing.render import SECTION_TITLES, Section, Sentence, deterministic_briefing

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"  # refusal fallbacks, "default" form (claude-api reference)
CREDENTIAL_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID")
MAX_RETRIES = 1  # the briefing is on a request path: fail over to the deterministic briefing rather than wait
HEADINGS = tuple(SECTION_TITLES.values())
# The only lead-ins an item may have: topic labels. None names a side, a team, a quantity or a judgement.
LEAD_INS = ("Match details:", "The alliances:", "Team record:", "EPA by phase:", "Scoring record:",
            "Scouting ratings:", "Qualifiers:", "Alliance synergy:", "Model forecast:", "Strategy:",
            "Coach observations:", "Unproduced items:", "Sources:")

SYSTEM_PROMPT = """You arrange the pre-match briefing for a FIRST Robotics Competition drive team.

You are a formatting layer only. Every prediction, rating and strategy was already produced by statistical models
and optimization. You receive the results as FACTS: each has an id, a kind, a section and a statement.

You do not write any text. Each item you return is printed as its label (if any) followed by the statements of the
facts it cites, word for word. Your job is to make the briefing easy to scan:
- group related facts into items (for example, one item per team);
- put the items of each section in a useful reading order;
- give an item one of these labels, or the empty string: """ + ", ".join(f'"{lead}"' for lead in LEAD_INS) + """.

Rules (a validator checks the output and rejects the whole briefing if any rule is broken):
1. Cite every fact exactly once, in an item under the heading of the fact's own section. Use these headings, in this
   order, and omit a heading only if it has no facts: Match, Red alliance, Blue alliance, Match forecast, Strategy,
   Not produced by any engine, Sources.
2. A label is exactly one of the labels above, or "".

Return only the JSON object the response format describes."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string", "enum": list(HEADINGS)},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"lead": {"type": "string", "enum": ["", *LEAD_INS]},
                                           "fact_ids": {"type": "array", "items": {"type": "string"}}},
                            "required": ["lead", "fact_ids"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["heading", "items"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sections"],
    "additionalProperties": False,
}



@dataclass(frozen=True)
class BriefingResult:
    mode: str  # "llm" | "deterministic"
    reason: str | None  # why the deterministic briefing was served; None in llm mode
    sections: tuple[Section, ...]
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Item:
    lead: str
    fact_ids: tuple[str, ...]


class ValidationFailed(Exception):
    def __init__(self, rule: str, detail: str):
        super().__init__(f"{rule}: {detail}")
        self.rule = rule


def facts_payload(facts: list[Fact]) -> str:
    """The user message: the facts as stable, compact JSON (sorted keys, so equal facts give equal bytes). The
    statement is what the briefing will print; `values` are not sent, since the LLM never writes a value."""
    return json.dumps({"facts": [{"id": f.id, "kind": f.kind, "section": f.section, "statement": f.statement}
                                 for f in facts]}, sort_keys=True, separators=(",", ":"))


def request_params(facts: list[Fact], model: str, max_tokens: int) -> dict[str, Any]:
    """The Messages API request (without credentials). Used by the formatter and by the cost tool (P9-M6)."""
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": facts_payload(facts)}],
        "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    }


def credential_available(environ: dict[str, str] | None = None) -> bool:
    """Whether the SDK's credential chain can resolve: an env credential, or a stored `ant` profile. Only presence is
    checked; the value is never read into a variable."""
    env = os.environ if environ is None else environ
    if any(env.get(name) for name in CREDENTIAL_ENV):
        return True
    config_dir = env.get("ANTHROPIC_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".config", "anthropic")
    return os.path.isdir(config_dir)


def _exact_keys(obj: Any, keys: set[str], what: str) -> dict[str, Any]:
    if not isinstance(obj, dict) or set(obj) != keys:
        raise ValidationFailed("schema", f"{what} is not an object with exactly {sorted(keys)}")
    return obj


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValidationFailed("schema", "a duplicate JSON key")
    return dict(pairs)


def parse(payload: Any) -> tuple[tuple[str, tuple[Item, ...]], ...]:
    """The output's structure, checked strictly: any other shape is a `schema` failure, never an exception."""
    sections = _exact_keys(payload, {"sections"}, "the output")["sections"]
    if not isinstance(sections, list) or not sections:
        raise ValidationFailed("schema", "no sections")
    out = []
    for section in sections:
        section = _exact_keys(section, {"heading", "items"}, "a section")
        heading, items = section["heading"], section["items"]
        if heading not in HEADINGS:
            raise ValidationFailed("heading", f"{heading!r} is not a briefing heading")
        if not isinstance(items, list) or not items:
            raise ValidationFailed("schema", f"section {heading!r} has no items")
        parsed = []
        for item in items:
            item = _exact_keys(item, {"lead", "fact_ids"}, "an item")
            lead, ids = item["lead"], item["fact_ids"]
            if not isinstance(lead, str) or not isinstance(ids, list) or not ids \
                    or not all(isinstance(i, str) for i in ids):
                raise ValidationFailed("schema", "an item without a lead string or cited facts")
            parsed.append(Item(lead, tuple(ids)))  # exact: a label is matched as given
        out.append((heading, tuple(parsed)))
    return tuple(out)


def check_lead(lead: str) -> None:
    """A lead-in is a topic label from the closed list, or nothing (module docstring)."""
    if lead and lead not in LEAD_INS:
        raise ValidationFailed("lead_not_allowed", "a lead-in outside LEAD_INS")


def validate(arranged: tuple[tuple[str, tuple[Item, ...]], ...], facts: list[Fact]) -> None:
    """Raises ValidationFailed on the first broken rule (module docstring). Returns None when every rule holds."""
    by_id = {f.id: f for f in facts}
    headings = [heading for heading, _ in arranged]
    if len(set(headings)) != len(headings):
        raise ValidationFailed("heading", "a heading appears twice")
    if headings != sorted(headings, key=HEADINGS.index):
        raise ValidationFailed("heading", "headings out of reading order")
    cited: list[str] = []
    for heading, items in arranged:
        for item in items:
            for fact_id in item.fact_ids:
                fact = by_id.get(fact_id)
                if fact is None:
                    raise ValidationFailed("unknown_fact", repr(fact_id))
                if SECTION_TITLES[fact.section] != heading:
                    raise ValidationFailed("wrong_section", f"{fact_id!r} under {heading!r}")
            cited.extend(item.fact_ids)
            check_lead(item.lead)
    repeated = sorted({i for i in cited if cited.count(i) > 1})
    if repeated:
        raise ValidationFailed("fact_cited_twice", f"{repeated[:3]}")
    missing = [f.id for f in facts if f.id not in set(cited)]
    if missing:
        raise ValidationFailed("fact_not_cited", f"{len(missing)} fact(s), e.g. {missing[:3]}")


def render(arranged: tuple[tuple[str, tuple[Item, ...]], ...], facts: list[Fact]) -> tuple[Section, ...]:
    """A validated arrangement as the briefing: each item is its lead-in plus its facts' statements, verbatim."""
    by_id = {f.id: f for f in facts}
    return tuple(Section(heading, tuple(
        Sentence(" ".join(([item.lead] if item.lead else []) + [by_id[i].statement for i in item.fact_ids]),
                 item.fact_ids) for item in items)) for heading, items in arranged)


def _fallback(facts: list[Fact], reason: str, model: str | None = None,
              usage: dict[str, int] | None = None) -> BriefingResult:
    logger.info("briefing: deterministic (%s)", reason)
    return BriefingResult("deterministic", reason, deterministic_briefing(facts), model, usage or {})


USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def usage_of(response: Any) -> dict[str, int]:
    """The tokens this request spent. Under a server-side fallback, top-level `usage` covers only the serving attempt
    and `usage.iterations` lists every attempt (claude-api reference), so the iterations are summed when present."""
    usage = _get(response, "usage")
    if usage is None:
        return {}
    iterations = _get(usage, "iterations")
    sources = iterations if isinstance(iterations, list) and iterations else [usage]
    totals: dict[str, int] = {}
    for source in sources:
        for key in USAGE_KEYS:
            value = _get(source, key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    if isinstance(iterations, list) and iterations:
        totals["attempts"] = len(iterations)
    return totals


def output_text(response: Any) -> str | None:
    """The served JSON text: the text after the last `fallback` block (a fallback marks where a declining model
    stopped; non-streaming responses omit its partial output, and this keeps that true if one is ever present)."""
    content = _get(response, "content")
    if not isinstance(content, list):
        return None
    last_fallback = max((i for i, b in enumerate(content) if _get(b, "type") == "fallback"), default=-1)
    texts = [_get(b, "text") for b in content[last_fallback + 1:] if _get(b, "type") == "text"]
    texts = [t for t in texts if isinstance(t, str)]
    return "".join(texts) if texts else None


def make_briefing(facts: list[Fact], *, enabled: bool, egress_approved: bool, model: str, max_tokens: int,
                  timeout: float, client_factory: Callable[[], Any] | None = None,
                  environ: dict[str, str] | None = None) -> BriefingResult:
    """The briefing for these facts: the LLM one if every gate opens and the output passes `validate`, else the
    deterministic one with the reason. Never raises for anything the API or the model returns. `client_factory`
    builds the SDK client (tests pass a stub)."""
    if not enabled:
        return _fallback(facts, "disabled")
    if not egress_approved:
        return _fallback(facts, "egress_not_approved")
    if client_factory is None:
        if not credential_available(environ):
            return _fallback(facts, "no_credential")
        try:
            import anthropic
        except ImportError:
            return _fallback(facts, "sdk_unavailable")

        def client_factory() -> Any:
            return anthropic.Anthropic(timeout=timeout, max_retries=MAX_RETRIES)

    try:
        client = client_factory()
        response = client.beta.messages.create(**request_params(facts, model, max_tokens),
                                               betas=[FALLBACK_BETA], fallbacks="default")
    except TypeError as exc:  # the SDK raises TypeError when no credential resolves (observed, anthropic 1.16)
        return _fallback(facts, "no_credential" if "authentication" in str(exc).lower() else "api_error:TypeError")
    except Exception as exc:  # every API, network and timeout error: fail closed, the key is never in the message
        return _fallback(facts, f"api_error:{type(exc).__name__}")
    usage = usage_of(response)
    served_model = _get(response, "model")
    served_model = served_model if isinstance(served_model, str) else model
    stop = _get(response, "stop_reason")
    if stop == "refusal":
        return _fallback(facts, "refusal", served_model, usage)
    if stop == "max_tokens":
        return _fallback(facts, "truncated", served_model, usage)
    text = output_text(response)
    if text is None:
        return _fallback(facts, "no_text", served_model, usage)
    try:
        arranged = parse(json.loads(text, object_pairs_hook=_no_duplicate_keys))
        validate(arranged, facts)
    except ValidationFailed as failed:
        logger.info("briefing: LLM output rejected (%s)", failed.rule)
        return _fallback(facts, f"validation_failed:{failed.rule}", served_model, usage)
    except (ValueError, RecursionError):  # JSONDecodeError, a too-long integer, too deep: never a 500 (review R2 C2)
        return _fallback(facts, "invalid_json", served_model, usage)
    return BriefingResult("llm", None, render(arranged, facts), served_model, usage)
