"""Phase 11: the agreements that need no database -- the code's lists against migration 0013, the route's declared
codes against the rules module, the new permission's defaults, and the activity vocabulary."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from api.routes.live_draft import RULE_CODES
from workspaces import activity, draft_log, live_draft, permissions

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "0013_live_alliance_selection.sql"


def _string_codes(path: Path, *calls: str) -> set[str]:
    """Every literal first argument of the named calls (e.g. Violation("wrong_turn", ...)) in one module."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in calls:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found.add(node.args[0].value)
    return found


def test_the_migration_type_check_lists_exactly_the_entry_types():
    sql = MIGRATION.read_text(encoding="utf-8")
    block = re.search(r"draft_actions_type_check CHECK \(action_type IN \((.*?)\)\)", sql, re.S)
    assert set(re.findall(r"'([a-z_]+)'", block.group(1))) == set(draft_log.ENTRY_TYPES)
    sources = re.search(r"draft_actions_source_check CHECK \(source IN \((.*?)\)\)", sql, re.S)
    assert set(re.findall(r"'([a-z_]+)'", sources.group(1))) == set(draft_log.SOURCES)


def test_the_log_is_append_only_and_team_scoped_in_the_schema():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "BEFORE UPDATE ON draft_actions" in sql
    assert "REFERENCES draft_records (workspace_id, id)" in sql
    assert sql.count("REFERENCES team_memberships (workspace_id, user_id)") == 2
    assert "UNIQUE (workspace_id, event_key)" in sql


def test_every_rule_code_the_log_can_refuse_with_is_declared_by_the_routes():
    raised = (_string_codes(ROOT / "workspaces" / "draft_log.py", "Violation", "DraftLogError")
              - {"captain_unchecked"})  # a note, never a refusal
    assert raised <= set(RULE_CODES), sorted(raised - set(RULE_CODES))
    # The other direction: every declared code is one the rules module can produce (some are chosen by a conditional
    # expression, e.g. captain_rule_not_established, so they are found as string literals in its source).
    source = (ROOT / "workspaces" / "draft_log.py").read_text(encoding="utf-8")
    assert all(f'"{code}"' in source for code in RULE_CODES), [c for c in RULE_CODES if f'"{c}"' not in source]


def test_the_service_refusal_codes_are_declared_too():
    source = (ROOT / "api" / "routes" / "live_draft.py").read_text(encoding="utf-8")
    service = _string_codes(ROOT / "workspaces" / "live_draft.py", "conflict", "forbidden", "not_found")
    for code in service | {"rules_required", live_draft.CODE_UNAVAILABLE}:
        assert f'"{code}"' in source, code


def test_recording_is_configurable_and_off_by_default_for_every_non_admin_role():
    assert "alliance_selection_record" in permissions.CONFIGURABLE_PERMISSIONS  # P11-Q2: delegable
    for role in permissions.CONFIGURABLE_ROLES:
        assert "alliance_selection_record" not in permissions.effective_permissions(role, {})
    assert "alliance_selection_record" in permissions.effective_permissions("admin", {})
    assert "alliance_selection" in permissions.effective_permissions("strategy", {})  # P11-Q4: the board


def test_every_activity_action_the_service_writes_is_in_the_vocabulary():
    source = (ROOT / "workspaces" / "live_draft.py").read_text(encoding="utf-8")
    written = set(re.findall(r'"(draft_[a-z_]+)"', source)) - {"draft_not_found", "draft_exists"}
    assert written and written <= set(activity.ACTIONS), sorted(written - set(activity.ACTIONS))
