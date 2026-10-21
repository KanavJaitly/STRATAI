"""P9-M1: every prediction, ranking, strategy and pick list works with zero LLM involvement.

The checks themselves are in scripts/phase9_zero_llm_audit.py. These tests run its static and import-time checks,
and prove each check can fail: a planted import is caught, and the import blocker really blocks. The runtime route
check needs a populated database and is run as evidence (`python -m scripts.phase9_zero_llm_audit --routes`).

Pure: no database connection.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from api import create_app
from data.config import Settings
from scripts.phase9_zero_llm_audit import (
    BLOCKER,
    ROOT,
    _forbidden,
    forbidden_imports,
    import_check,
    inventory,
    judge_disconnection,
    static_violations,
    unclassified,
)

# Every operation that produces or carries a prediction, ranking, strategy or pick list (P9-M1 inventory). A new
# such operation must be added here and to the audit's route calls, or this test fails.
EXPECTED_INVENTORY = {
    "GET /events/{event_key}/alliance-selection/candidates",
    "GET /events/{event_key}/analysis",
    "GET /events/{event_key}/qualification-forecast",
    "GET /human-inputs/capability-profiles/{profile_key}/recommendation",
    "GET /matches/{match_key}/pre-match-report",
    "GET /predictions/events/{event_key}/ranking",
    "GET /predictions/matches/{match_key}/win-probability",
    "GET /teams/{team_number}/events/{event_key}/metrics",
    "GET /teams/{team_number}/events/{event_key}/strength",
    "POST /events/{event_key}/alliance-selection/pick-list",
    "POST /predictions/alliance-synergy",
    "POST /predictions/win-probability",
    "POST /strategy/hypothetical/assess",
    "POST /strategy/hypothetical/compare",
    "POST /strategy/hypothetical/recommend",
    "POST /strategy/matches/{match_key}/assess",
    "POST /strategy/matches/{match_key}/compare",
    "POST /strategy/matches/{match_key}/recommend",
}


def test_no_core_module_imports_an_llm_sdk_or_the_briefing_package():
    assert static_violations() == []


def test_the_scanner_catches_static_and_dynamic_llm_imports():
    source = textwrap.dedent("""
        import anthropic
        import openai.types as t
        from langchain_core.messages import AIMessage
        from briefing.llm import format_briefing
        import importlib
        importlib.import_module("google.genai")
        __import__("briefing")
        import anthropic_helpers          # not an LLM SDK: a different top-level name
        from briefing_notes import x      # likewise
        import json
    """)
    assert sorted(forbidden_imports(source)) == sorted(["anthropic", "openai.types", "langchain_core.messages",
                                                        "briefing.llm", "dynamic:import_module", "dynamic:__import__"])


# Review R1 (C8): each of these evaded the first scanner.
EVASIONS = [
    ("from google import genai", "google.genai"),
    ("from google.cloud import aiplatform", "google.cloud.aiplatform"),
    ("from importlib import import_module as im\nim('anthropic')", "dynamic:import_module"),
    ("import importlib\nimportlib.import_module('anth' + 'ropic')", "dynamic:import_module"),
    ("import importlib\nimportlib.import_module(name='anthropic')", "dynamic:import_module"),
    ("__import__(name='openai')", "dynamic:__import__"),
    ("exec('import anthropic')", "dynamic:exec"),
    ("import builtins\nbuiltins.eval('1')", "dynamic:eval"),
    ("import importlib\ngetattr(importlib, 'import_module')('anthropic')", "dynamic:import_module"),
    ("import botocore", "botocore"), ("import pydantic_ai", "pydantic_ai"), ("import instructor", "instructor"),
    ("import dspy", "dspy"), ("import claude_agent_sdk", "claude_agent_sdk"),
    ("from azure.ai import inference", "azure.ai.inference"), ("import langchain_community", "langchain_community"),
    ("import httpx\nhttpx.post('https://api.anthropic.com/v1/messages')", "host:anthropic.com"),
    ("URL = 'https://api.openai.com/v1/chat/completions'", "host:openai.com"),
    ("try:\n    from google import genai\nexcept ImportError:\n    genai = None", "google.genai"),
    # Review R2 (C6)
    ("from api.routes.briefing import make_briefing", "api.routes.briefing"),
    ("from api.routes import briefing as b", "api.routes.briefing"),
    ("import importlib.util\nimportlib.util.spec_from_file_location('x', 'y.py')", "dynamic:spec_from_file_location"),
    ("import runpy\nrunpy.run_module('briefing.llm')", "dynamic:run_module"),
    ("import pkgutil\npkgutil.resolve_name('anthropic:Anthropic')", "dynamic:resolve_name"),
    ("import pydoc\npydoc.locate('anthropic.Anthropic')", "dynamic:locate"),
    ("import builtins\ngetattr(builtins, '__imp' + 'ort__')('anthropic')", "dynamic:getattr(builtins)"),
    ("import haystack", "haystack"), ("import semantic_kernel", "semantic_kernel"), ("import crewai", "crewai"),
    ("import smolagents", "smolagents"), ("import langgraph", "langgraph"),
]


@pytest.mark.parametrize("source, expected", EVASIONS, ids=[e[1] + ":" + str(i) for i, e in enumerate(EVASIONS)])
def test_the_scanner_catches_the_review_r1_evasions(source, expected):
    assert expected in forbidden_imports(source)


def test_ordinary_code_is_not_flagged():
    source = "import re\nre.compile('x')\nimport json\nTEXT = 'anthropic is a word'\nfrom data import config\n"
    assert forbidden_imports(source) == []
    assert not _forbidden("anthropic_helpers") and not _forbidden("google.cloud.storage")


def test_a_planted_violation_in_a_core_package_is_reported_and_the_allowed_files_are_not(tmp_path: Path):
    (tmp_path / "ml").mkdir()
    (tmp_path / "ml" / "planted.py").write_text("from anthropic import Anthropic\n")
    (tmp_path / "api" / "routes").mkdir(parents=True)
    (tmp_path / "api" / "routes" / "briefing.py").write_text("import briefing\nimport anthropic\n")  # allowed
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "lazy.py").write_text("def f():\n    import importlib\n    return importlib.import_module('openai')\n")
    assert sorted(static_violations(tmp_path)) == ["data/lazy.py imports dynamic:import_module",
                                                   "ml/planted.py imports anthropic"]


def test_every_core_module_imports_and_the_app_builds_with_every_llm_sdk_blocked():
    result = import_check()
    assert result["ok"], result
    assert result["failures"] == {}
    assert result["imported"] == result["modules"] > 150
    assert result["operations"] >= 46


def test_the_import_blocker_really_blocks(tmp_path: Path):
    """The import-time check is only meaningful if the blocker stops an import that would otherwise succeed."""
    (tmp_path / "briefing").mkdir()
    (tmp_path / "briefing" / "__init__.py").write_text("VALUE = 1\n")
    unblocked = subprocess.run([sys.executable, "-c", "import briefing; print(briefing.VALUE)"], cwd=tmp_path,
                               capture_output=True, text=True)
    assert unblocked.returncode == 0 and unblocked.stdout.strip() == "1"
    blocked = subprocess.run([sys.executable, "-c", BLOCKER + "\nimport briefing\n"], cwd=tmp_path,
                             capture_output=True, text=True)
    assert blocked.returncode != 0
    assert "blocked (zero-LLM check)" in blocked.stderr


def test_the_inventory_covers_every_prediction_ranking_strategy_and_pick_list_operation():
    found = {f"{m} {p}" for m, p in inventory(create_app(Settings(api_prefix="")).openapi())}
    assert found == EXPECTED_INVENTORY


def test_every_served_operation_is_classified():
    """Review R1 (C9): a new operation fails here until it is classified as an output (and so checked), the LLM
    layer, or not an output."""
    assert unclassified(create_app(Settings(api_prefix="")).openapi()) == []


def test_the_core_requirements_list_no_llm_sdk_and_the_briefing_ones_are_separate():
    """M1 scope (b): no LLM SDK is a dependency of the core. The briefing's SDK is an optional, separate file."""
    def names(path: Path) -> list[str]:
        lines = [line.split("#")[0].strip() for line in path.read_text(encoding="utf-8").splitlines()]
        return [re.split(r"[<>=!~\[; ]", line)[0].lower().replace("-", "_") for line in lines if line]
    assert [n for n in names(ROOT / "requirements.txt") if _forbidden(n)] == []
    assert names(ROOT / "requirements-briefing.txt") == ["anthropic"]


def test_only_the_app_may_import_the_briefing_route(tmp_path: Path):
    """R2 C6: the route is a door to the LLM layer. The app's optional router may use it; no other core module."""
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "app.py").write_text("from api.routes.briefing import router\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sneak.py").write_text("from api.routes.briefing import make_briefing\n")
    assert static_violations(tmp_path) == ["data/sneak.py imports api.routes.briefing"]


def test_the_import_blocker_also_blocks_the_name_prefixes(tmp_path: Path):
    (tmp_path / "langchain_extra").mkdir()
    (tmp_path / "langchain_extra" / "__init__.py").write_text("")
    blocked = subprocess.run([sys.executable, "-c", BLOCKER + "\nimport langchain_extra\n"], cwd=tmp_path,
                             capture_output=True, text=True)
    assert blocked.returncode != 0 and "blocked (zero-LLM check)" in blocked.stderr


def _op(name: str, status: int, body: str = "x", code: str | None = None) -> dict:
    return {"operation": name, "status": status, "code": code, "ok": True, "body_sha256": body}


LLM_RAN = {"url": "/matches/m/briefing", "status": 200, "mode": "llm", "fallback_reason": None}


def test_the_disconnection_verdict_passes_only_on_equal_real_outputs_with_the_llm_layer_running():
    """R2 C5: the verdict can never pass vacuously."""
    off = [_op("GET /a", 200, "h1"), _op("GET /b", 404, "h2", "model_not_loaded")]
    assert judge_disconnection(off, off + [LLM_RAN])["ok"]
    # a different body
    assert not judge_disconnection(off, [_op("GET /a", 200, "h9"), off[1], LLM_RAN])["ok"]
    # refusals only: nothing real was compared
    refusals = [_op("GET /b", 404, "h2", "model_not_loaded")]
    assert not judge_disconnection(refusals, refusals + [LLM_RAN])["ok"]
    # the LLM layer did not really run (no credential, or the route missing)
    assert not judge_disconnection(off, off + [{**LLM_RAN, "mode": "deterministic"}])["ok"]
    assert not judge_disconnection(off, off + [{**LLM_RAN, "status": 500, "mode": None}])["ok"]
    assert not judge_disconnection(off, off)["ok"]
    # a missing or extra operation
    assert not judge_disconnection(off, off[:1] + [LLM_RAN])["ok"]
