"""P5-M8 curated design reference, its human codebook, and double-coding agreement (P5-D10).

**The reference.** `data/reference/frc_robot_design_curated.csv`:
- 77 rows, sha256 `40aef139…139e1`, verified at every load;
- a **curated, unverified reference/knowledge layer, not a quantitative source**
  (.agent/phase5/robot_design_audit/AUDIT.md);
- each row is served as a historical design example labelled `curated_reference_unverified`, with its
  micro-archetype text verbatim;
- never served with a success rate or a performance ranking.

**The codebook** is human-authored and frozen before coding:
- a set of robot functions, and a family per function;
- every row is coded independently by two people (multi-label).

Keyword auto-labelling is not used: the audit found 19 of 77 rows (25%) misassigned.

**Agreement.** Cohen's κ on the function labels decides how the labels are used:
- **κ ≥ 0.6:** they are used as categories;
- **otherwise:** they are served `provisional`.

κ is reported two ways:
- pooled over every (row, function) present/absent decision;
- per function.

**Decided as P5-D13** (`label_status`):
- the pooled κ ≥ 0.6 makes the coding acceptable overall;
- every per-function κ is reported;
- a function whose own κ is below 0.6 is served `provisional`.

**Reconciliation** (`reconcile_with_consensus`): the served labels are the consensus meeting's coding, never
one coder's.

**The pre-reveal filter** (DM1 leakage) keeps only rows from before the simulated reveal year. For 2026, that
excludes the 10 REBUILT rows.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

REFERENCE_PATH = Path("data/reference/frc_robot_design_curated.csv")
REFERENCE_SHA256 = "40aef13982eba6589136806150d9f1e5f92ce49bea588e1ee561ca44c77139e1"
REFERENCE_ROWS = 77
CURATED_REFERENCE_UNVERIFIED = "curated_reference_unverified"
KAPPA_THRESHOLD = 0.6
LABELS_AS_CATEGORIES, LABELS_PROVISIONAL = "categories", "provisional"


class ReferenceIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class DesignExample:
    row_id: int  # 1-based CSV row (header excluded), the stable key codings refer to
    year: int
    team: int
    game_name: str
    micro_archetype: str  # verbatim
    technical_specifications: str  # verbatim
    key_characteristic: str  # verbatim
    label: str = CURATED_REFERENCE_UNVERIFIED


def load_reference(path: Path = REFERENCE_PATH, *, expected_sha256: str = REFERENCE_SHA256) -> list[DesignExample]:
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ReferenceIntegrityError(f"{path} does not match its recorded sha256 {expected_sha256[:12]}…")
    rows = list(csv.DictReader(data.decode("utf-8").splitlines()))
    if len(rows) != REFERENCE_ROWS:
        raise ReferenceIntegrityError(f"{path} has {len(rows)} rows, expected {REFERENCE_ROWS}")
    return [DesignExample(i, int(r["Year"]), int(r["Team"]), r["Game Name"], r["Robot Micro-Archetype"],
                          r["Technical Specifications"], r["Key Characteristic & Competitive Advantage"])
            for i, r in enumerate(rows, start=1)]


def before_reveal(examples: Sequence[DesignExample], reveal_season: int) -> list[DesignExample]:
    return [e for e in examples if e.year < reveal_season]


class Codebook(BaseModel):
    """Human-authored taxonomy: function -> family. Frozen (hashed) before any coding."""

    version: str = Field(min_length=1)
    authored_by: str = Field(min_length=1)
    functions: dict[str, str] = Field(min_length=1, description="function -> family")

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode("utf-8")).hexdigest()


class Coding(BaseModel):
    """One coder's independent multi-label coding of every reference row."""

    coder: str = Field(min_length=1)
    codebook_sha256: str = Field(min_length=64, max_length=64)
    labels: dict[int, list[str]]  # row_id -> functions

    @model_validator(mode="after")
    def _labels_are_sets(self) -> Coding:
        for row, functions in self.labels.items():
            if len(functions) != len(set(functions)):
                raise ValueError(f"row {row} repeats a function")
        return self


def validate_codings(codebook: Codebook, first: Coding, second: Coding, rows: Sequence[int]) -> None:
    if first.coder == second.coder:
        raise ValueError("double coding needs two different coders")
    for coding in (first, second):
        if coding.codebook_sha256 != codebook.sha256():
            raise ValueError(f"{coding.coder} coded against a different codebook")
        if sorted(coding.labels) != sorted(rows):
            raise ValueError(f"{coding.coder} did not code every row exactly once")
        unknown = {f for fs in coding.labels.values() for f in fs} - set(codebook.functions)
        if unknown:
            raise ValueError(f"{coding.coder} used functions outside the codebook: {sorted(unknown)}")


def cohens_kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    """Cohen's κ for two binary raters; None when chance agreement is 1 (κ undefined)."""
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def agreement(codebook: Codebook, first: Coding, second: Coding) -> dict[str, object]:
    rows = sorted(first.labels)
    per_function = {}
    pooled_a, pooled_b = [], []
    for function in sorted(codebook.functions):
        a = [function in first.labels[r] for r in rows]
        b = [function in second.labels[r] for r in rows]
        per_function[function] = cohens_kappa(a, b)
        pooled_a += a
        pooled_b += b
    return {"rows": len(rows), "pooled_kappa": cohens_kappa(pooled_a, pooled_b), "per_function_kappa": per_function}


def label_status(result: dict[str, object]) -> dict[str, object]:
    """P5-D13 (5).
    - Pooled κ ≥ 0.6 makes the coding acceptable overall.
    - Every per-function κ is reported, and a function whose own κ is below 0.6 (or undefined) is served
      `provisional`, so a weak function never hides behind the pooled κ.
    - If the pooled κ fails, every label is `provisional`."""
    pooled = result["pooled_kappa"]
    overall_ok = pooled is not None and pooled >= KAPPA_THRESHOLD  # type: ignore[operator]
    functions = {f: (LABELS_AS_CATEGORIES if overall_ok and k is not None and k >= KAPPA_THRESHOLD
                     else LABELS_PROVISIONAL)
                 for f, k in result["per_function_kappa"].items()}  # type: ignore[union-attr]
    return {"overall": LABELS_AS_CATEGORIES if overall_ok else LABELS_PROVISIONAL, "functions": functions}


def reconcile_with_consensus(codebook: Codebook, first: Coding, second: Coding, consensus: Coding) -> Coding:
    """P5-D13 (6): the served labels are the consensus meeting's coding, made after the independent codings
    and κ; never one coder's labels."""
    if consensus.coder in (first.coder, second.coder):
        raise ValueError("the consensus coding must be the meeting's, not one coder's")
    validate_codings(codebook, first, consensus, sorted(first.labels))
    return consensus


def examples_by_function(examples: Sequence[DesignExample], coding: Coding, function: str) -> list[DesignExample]:
    """Historical design examples carrying a function label (each stays curated_reference_unverified)."""
    return [e for e in examples if function in coding.labels.get(e.row_id, [])]
