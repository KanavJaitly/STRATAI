"""P11A §14: the plan and the profile computed offline, with the network denied at the OS level.

The CLI (`scripts/p11a_snapshot.py`) runs in a child process under macOS `sandbox-exec` with `(deny network*)`. A
local listener is the positive control: the same child code reaches it without the sandbox and cannot with it, so a
pass means "works with no network", not "the network happened to be down". Skipped where sandbox-exec is missing
(not macOS). Synthetic season 9911, teams 1-24 only.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ml.alliance.snapshot import snapshot_filename
from tests.p11a_support import snapshot, truths, write_registry
from tests.test_phase11_draft_log import Log, setup

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = shutil.which("sandbox-exec")
DENY = "(version 1)(allow default)(deny network*)"
pytestmark = pytest.mark.skipif(sys.platform != "darwin" or SANDBOX is None, reason="needs macOS sandbox-exec")


def _run(args: list[str], *, sandboxed: bool, timeout: int = 300) -> subprocess.CompletedProcess:
    command = [sys.executable, *args]
    if sandboxed:
        # sandbox-exec is SIP-protected, so macOS drops DYLD_* from its environment; /usr/bin/env puts back the
        # library path this machine's xgboost needs (ml/__init__ imports it), then runs Python inside the sandbox.
        keep = [f"{k}={v}" for k, v in os.environ.items() if k.startswith("DYLD_")]
        command = [SANDBOX, "-p", DENY, "/usr/bin/env", *keep, *command]
    return subprocess.run(command, cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def listener():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    yield server.getsockname()[1]
    server.close()


def test_the_sandbox_really_denies_the_network(listener):
    probe = f"import socket; socket.create_connection(('127.0.0.1', {listener}), timeout=3); print('connected')"
    assert _run(["-c", probe], sandboxed=False).stdout.strip() == "connected"  # positive control
    denied = _run(["-c", probe], sandboxed=True)
    assert denied.returncode != 0 and "Operation not permitted" in denied.stderr


def _files(tmp_path: Path) -> tuple[Path, Path]:
    truth = {i: v for i, v in enumerate(truths(24, 7).values(), start=1)}
    snap = snapshot(truth=truth)
    snap_path = tmp_path / snapshot_filename(snap)
    snap.save(snap_path)
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 24)
    entries = [{"action_id": e.action_id, "seq": e.seq, "type": e.type, "payload": dict(e.payload),
                "override_reason": e.override_reason} for e in log.entries]
    log_path = tmp_path / "draft_log.json"
    log_path.write_text(json.dumps(entries))
    (tmp_path / "registry").mkdir()
    write_registry(tmp_path / "registry")
    return snap_path, log_path


def test_the_plan_runs_with_the_network_denied(tmp_path):
    snap_path, log_path = _files(tmp_path)
    out = tmp_path / "plan.json"
    done = _run(["-m", "scripts.p11a_snapshot", "plan", "--snapshot", str(snap_path), "--log", str(log_path),
                 "--team", "1", "--out", str(out), "--scoring-dir", str(tmp_path / "registry")], sandboxed=True)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(out.read_text())
    assert result["status"] == "current" and result["mode"] == "offline"
    plan = result["plan"]
    assert plan["stage"] == "next_pick" and plan["members"] == [1, 24] and plan["cards"]
    assert plan["win_probability"]["status"] == "not_available" and plan["validation_status"] == "not_validated"


def test_the_profile_runs_with_the_network_denied(tmp_path):
    snap_path, _ = _files(tmp_path)
    out = tmp_path / "profile.json"
    done = _run(["-m", "scripts.p11a_snapshot", "profile", "--snapshot", str(snap_path), "--team", "5",
                 "--our-team", "1", "--out", str(out), "--scoring-dir", str(tmp_path / "registry")],
                sandboxed=True)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(out.read_text())
    assert result["status"] == "current" and result["profile"]["team_number"] == 5
    assert result["profile"]["alliance_fit"]["unit"] == "points"


def test_an_altered_snapshot_is_refused_offline(tmp_path):
    snap_path, log_path = _files(tmp_path)
    snap_path.write_text(snap_path.read_text().replace('"auto": ', '"auto": 1', 1))
    done = _run(["-m", "scripts.p11a_snapshot", "plan", "--snapshot", str(snap_path), "--log", str(log_path),
                 "--team", "1"], sandboxed=True)
    assert done.returncode == 2 and "snapshot_integrity" in done.stderr
