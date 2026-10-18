"""The Phase 7 response-shape lock (P7-A4, P7-Q4; P7-DM2: no endpoint shape changes after frontend work begins).

    python -m scripts.phase7_contract_lock check
    python -m scripts.phase7_contract_lock lock --reason "P7-M2: lock team metrics and strength" \
        "GET /teams/{team_number}/events/{event_key}/metrics" ...
    python -m scripts.phase7_contract_lock relock --reason "..." [--decision "P7_M0_DECISIONS.md row ..."]

The lock file (docs/api_contract_lock.json) holds a normalized copy of each locked operation's contract, every
component schema those operations reach, and the shared building blocks of api.contract. tests/test_phase7_contract.py
fails whenever the live application differs from it.

**What is locked.** Everything a client depends on: parameters (name, location, required, schema), request bodies,
response status codes and their schemas, every declared error code, the `deprecated` flag, and each schema's types,
properties, required lists, enums, constraints and defaults. **What is not:** titles, descriptions, summaries and
examples, which are documentation.

**How a lock may change.** `lock` adds operations and nothing else: if any already-locked entry differs, it refuses
and `relock` must record that change separately. `relock` rewrites the lock from the live application and refuses
any change to an already-locked entry unless `--decision` names the dated decision that allowed it (an existing
decision document plus a date); a purely additive change (a new optional property, a new error status) needs only a
reason. `unlock` removes operations and always needs `--decision`. Every change appends a dated revision listing
every changed entry, so the history of the contract is in the file itself. A new code on an already-declared error
status changes that status's code list, so it needs a decision: clients must handle every code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from api.contract import DECLARED_CODE_PATTERN

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "docs" / "api_contract_lock.json"

_DOC_KEYS = {"title", "description", "summary", "examples", "example"}
# A declared error code, as error_responses writes it into a response description (defined in api.contract).
CODE_PATTERN = DECLARED_CODE_PATTERN
_CODE = CODE_PATTERN
_REF = "#/components/schemas/"


# Keywords whose value is a name -> schema map: the names are data (a property may be called "summary"), so they
# are kept; only the schemas inside are normalized.
_SCHEMA_MAPS = {"properties", "patternProperties", "$defs", "definitions"}
# Keywords whose value is a set in meaning but a list in JSON: sorted, so reordering model fields or writing
# `None | int` instead of `int | None` is not reported as a change.
_UNORDERED = {"required", "anyOf", "oneOf", "allOf", "enum", "type"}


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def normalize_schema(schema: Any) -> Any:
    """A schema without its documentation keywords, recursively; everything else is kept."""
    if isinstance(schema, list):
        return [normalize_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in sorted(schema.items()):
        if key in _DOC_KEYS:
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: normalize_schema(item) for name, item in sorted(value.items())}
        elif key in _UNORDERED and isinstance(value, list):
            out[key] = sorted((normalize_schema(item) for item in value), key=_sort_key)
        else:
            out[key] = normalize_schema(value)
    return out


def _content_schemas(content: dict[str, Any] | None) -> dict[str, Any]:
    return {media: normalize_schema(body.get("schema", {})) for media, body in sorted((content or {}).items())}


def normalize_operation(operation: dict[str, Any]) -> dict[str, Any]:
    """One operation's contract: parameters, request body, responses (with declared error codes), deprecation."""
    parameters = sorted(
        ({"in": p["in"], "name": p["name"], "required": bool(p.get("required", False)),
          "schema": normalize_schema(p.get("schema", {}))} for p in operation.get("parameters", [])),
        key=lambda p: (p["in"], p["name"]))
    body = operation.get("requestBody")
    responses = {}
    for status, response in sorted(operation.get("responses", {}).items()):
        entry: dict[str, Any] = {"content": _content_schemas(response.get("content"))}
        if status[0] in "45":
            entry["codes"] = sorted(set(_CODE.findall(response.get("description", ""))))
        responses[status] = entry
    return {
        # A generated Phase 8 client names its functions after operationId, so renaming a handler is a change.
        "operation_id": operation.get("operationId"),
        "parameters": parameters,
        "request_body": None if body is None else {"required": bool(body.get("required", False)),
                                                   "content": _content_schemas(body.get("content"))},
        "responses": responses,
        "deprecated": bool(operation.get("deprecated", False)),
    }


def _refs(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF):
            yield ref[len(_REF):]
        for item in value.values():
            yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def operations_of(openapi: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every operation in an OpenAPI document, keyed "METHOD /path"."""
    return {f"{method.upper()} {path}": operation
            for path, item in openapi.get("paths", {}).items() for method, operation in item.items()}


def contract_of(openapi: dict[str, Any], locked: Iterable[str]) -> dict[str, Any]:
    """The normalized contract of the `locked` operations and every component schema they reach."""
    live = operations_of(openapi)
    missing = sorted(set(locked) - set(live))
    if missing:
        raise KeyError(f"locked operations missing from the application: {missing}")
    operations = {key: normalize_operation(live[key]) for key in sorted(locked)}
    components = openapi.get("components", {}).get("schemas", {})
    reached: set[str] = set()
    pending = [name for op in operations.values() for name in _refs(op)]
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        pending.extend(_refs(components[name]))
    return {"operations": operations, "schemas": {name: normalize_schema(components[name]) for name in sorted(reached)}}


def building_blocks() -> dict[str, Any]:
    """The api.contract building blocks' schemas, locked even before any route uses them."""
    from api.contract import CalibratedWinProbability, StrategyOdds, Validation

    return {model.__name__: normalize_schema(model.model_json_schema())
            for model in (CalibratedWinProbability, StrategyOdds, Validation)}


def live_contract(locked: Iterable[str]) -> dict[str, Any]:
    from api import create_app
    from data.config import Settings

    # The lock describes route shapes, independent of where a deployment mounts them: build the app unmounted, so an
    # API_PREFIX in the environment (a gateway mount) never makes the lock or its check disagree with itself.
    contract = contract_of(create_app(Settings(api_prefix="")).openapi(), locked)
    contract["building_blocks"] = building_blocks()
    return contract


def read_lock(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or LOCK_PATH).read_text(encoding="utf-8"))


def locked_part(lock: dict[str, Any]) -> dict[str, Any]:
    return {key: lock[key] for key in ("operations", "schemas", "building_blocks")}


_EMPTY = "{}"


def _leaves(value: Any, prefix: str = "") -> dict[str, Any]:
    """Every non-object value by its path. An empty object is a leaf of its own (a response with no schema, an
    `Any` body), so its presence and removal are visible; filling it in later is an addition (see differences)."""
    if isinstance(value, dict):
        if not value:
            return {prefix: _EMPTY}
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_leaves(item, f"{prefix}/{key}"))
        return out
    return {prefix: value}


def differences(old: dict[str, Any], new: dict[str, Any]) -> dict[str, list[str]]:
    """Leaf-level differences between two contracts: `changed` (a locked leaf altered or removed) and `added`.

    Objects are walked key by key; a list is one leaf, compared whole. That is deliberately conservative: a
    changed `required`, `enum` or `anyOf` list counts as a change to a locked entry (and so needs a recorded
    decision), even when it only gains an entry -- for a request schema that is a breaking change.
    """
    before, after = _leaves(old), _leaves(new)

    def filled_in(key: str) -> bool:  # an empty object that now has content is an addition, not a change
        return before[key] == _EMPTY and key not in after and any(k.startswith(key + "/") for k in after)

    changed = sorted(k for k in before if (k not in after or after[k] != before[k]) and not filled_in(k))
    added = sorted(k for k in after if k not in before)
    return {"changed": changed, "added": added}


def write_lock(contract: dict[str, Any], revisions: list[dict[str, Any]], path: Path | None = None) -> None:
    body = {"revisions": revisions, **contract}
    target = path or LOCK_PATH
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)  # atomic: a reader never sees a half-written lock


_DECISION = re.compile(r"(?P<file>\S+\.md)\b.*\b(?P<date>\d{4}-\d{2}-\d{2})\b")


def valid_decision(decision: str | None) -> bool:
    """A decision reference names an existing decision document and the decision's date, e.g.
    ".agent/phase7/P7_M0_DECISIONS.md row P7-D1 (2026-11-02)"."""
    match = _DECISION.search(decision or "")
    return bool(match) and (ROOT / match.group("file")).is_file()


def _revision(command: str, reason: str, decision: str | None, diff: dict[str, list[str]],
              operations_added: list[str], operations_removed: list[str]) -> dict[str, Any]:
    return {"date": date.today().isoformat(), "command": command, "reason": reason, "decision": decision,
            "operations_added": operations_added, "operations_removed": operations_removed,
            "changed": diff["changed"], "added_leaves": len(diff["added"])}


def _owned_by(leaf: str, operations: Iterable[str], schemas: Iterable[str], blocks: Iterable[str]) -> bool:
    """True if `leaf` belongs to something `lock` is adding: a new operation, a schema only it reaches, or a
    building block not locked before."""
    return (any(leaf.startswith(f"/operations/{op}/") for op in operations)
            or any(leaf.startswith(f"/schemas/{name}/") for name in schemas)
            or any(leaf.startswith(f"/building_blocks/{name}/") for name in blocks))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    add = sub.add_parser("lock", help="add operations; nothing already locked may change")
    add.add_argument("operations", nargs="+")
    relock = sub.add_parser("relock", help="record a change to locked operations")
    unlock = sub.add_parser("unlock", help="remove operations from the lock (always needs --decision)")
    unlock.add_argument("operations", nargs="+")
    for p in (add, relock, unlock):
        p.add_argument("--reason", required=True)
        p.add_argument("--decision", default=None,
                       help="the dated decision allowing a change to a locked entry: '<decisions .md path> ... "
                            "YYYY-MM-DD'")
    args = parser.parse_args(argv)
    if getattr(args, "decision", None) and not valid_decision(args.decision):
        print(f"refused: --decision must name an existing decision document and a date: {args.decision!r}",
              file=sys.stderr)
        return 2

    lock = read_lock() if LOCK_PATH.exists() else {"revisions": [], "operations": {}, "schemas": {},
                                                    "building_blocks": {}}
    locked = list(lock["operations"])
    try:
        if args.command == "check":
            diff = differences(locked_part(lock), live_contract(locked))
            print(json.dumps(diff, indent=1))
            return 1 if diff["changed"] or diff["added"] else 0
        if args.command == "unlock":
            unknown = sorted(set(args.operations) - set(locked))
            if unknown or not args.decision:
                print(f"refused: unlock needs --decision and locked operations (not locked: {unknown})",
                      file=sys.stderr)
                return 2
            removed, keep = list(args.operations), [op for op in locked if op not in args.operations]
            contract = live_contract(keep)
            diff = differences(locked_part(lock), contract)
            write_lock(contract, lock["revisions"] + [_revision("unlock", args.reason, args.decision, diff, [],
                                                                removed)])
            print(f"lock written: removed {removed}")
            return 0
        new_ops = [op for op in getattr(args, "operations", []) if op not in lock["operations"]]
        contract = live_contract(locked + new_ops)
    except KeyError as exc:  # a locked operation vanished from the application, or a mistyped name
        print(f"refused: {exc.args[0]}", file=sys.stderr)
        return 2
    diff = differences(locked_part(lock), contract)
    if diff["changed"] and not args.decision:
        print("refused: these locked entries would change, and no --decision was given:", file=sys.stderr)
        print("\n".join(diff["changed"][:50]), file=sys.stderr)
        return 2
    if args.command == "lock":
        new_schemas = set(contract["schemas"]) - set(lock["schemas"])
        new_blocks = set(contract["building_blocks"]) - set(lock["building_blocks"])
        unrelated = [leaf for leaf in diff["added"] + diff["changed"]
                     if not _owned_by(leaf, new_ops, new_schemas, new_blocks)]
        if unrelated:
            print("refused: `lock` only adds operations; these other entries differ (use `relock`):",
                  file=sys.stderr)
            print("\n".join(unrelated[:50]), file=sys.stderr)
            return 2
    write_lock(contract, lock["revisions"] + [_revision(args.command, args.reason, args.decision, diff, new_ops, [])])
    print(f"lock written: {len(contract['operations'])} operations, {len(diff['changed'])} changed leaves, "
          f"{len(diff['added'])} added leaves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
