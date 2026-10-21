"""P9-M2: the deterministic briefing. The report's facts are rendered by fixed templates, with no LLM.

This is what "the LLM disconnected" means for readability (P9-DM1). It is also the fallback whenever the LLM
formatter is off, unapproved, unconfigured, failing or rejected (P9-Q7). The same facts always give the same bytes.

A briefing is sections of sentences, and every sentence names the fact ids it states. The LLM formatter returns the
same shape, so the API and the dashboard treat both modes alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from briefing.facts import Fact, report_facts

SECTION_TITLES = {
    "match": "Match",
    "red": "Red alliance",
    "blue": "Blue alliance",
    "forecast": "Match forecast",
    "strategy": "Strategy",
    "not_produced": "Not produced by any engine",
    "source": "Sources",
}


@dataclass(frozen=True)
class Sentence:
    text: str
    fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class Section:
    heading: str
    sentences: tuple[Sentence, ...]


def deterministic_briefing(facts: list[Fact]) -> tuple[Section, ...]:
    """One section per report part, in reading order, with each fact's own statement as a sentence."""
    sections: list[Section] = []
    for key, title in SECTION_TITLES.items():
        sentences = tuple(Sentence(f.statement, (f.id,)) for f in facts if f.section == key)
        if sentences:
            sections.append(Section(title, sentences))
    return tuple(sections)


def briefing_for_report(report: dict[str, Any]) -> tuple[list[Fact], tuple[Section, ...]]:
    facts = report_facts(report)
    return facts, deterministic_briefing(facts)


def as_text(sections: tuple[Section, ...]) -> str:
    """Plain text, for logs and the cost tool's size measurements."""
    return "\n\n".join(s.heading + "\n" + "\n".join(x.text for x in s.sentences) for s in sections)
