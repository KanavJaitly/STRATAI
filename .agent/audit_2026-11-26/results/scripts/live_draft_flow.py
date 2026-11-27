"""Live draft workflow through the real API (stratai_test_e2e via the UI's /api proxy), audit 2026-11-26."""
import json
import sys
import time

import httpx

UI = "http://localhost:5196/api"
H = {"X-StratAI-CSRF": "1"}
EVENT = sys.argv[1] if len(sys.argv) > 1 else "2024njwas"
results = []


def note(step, ok, detail=""):
    results.append((step, ok, detail))
    print(("PASS" if ok else "FAIL"), step, "-", detail)


def session(who):
    c = httpx.Client(base_url=UI, timeout=60)
    r = c.post("/auth/login", headers=H, json={"email": f"{who}@audit.example.test", "password": "Audit-Password-2026!"})
    assert r.status_code == 200, r.text
    return c


st, dr = session("strategy"), session("drive")
existing = st.get("/workspace/alliance-selection/drafts", params={"event_key": EVENT}).json()
if existing:
    record = existing[0]["record_id"]
else:
    r = st.post("/workspace/alliance-selection/drafts", headers=H, json={"event_key": EVENT})
    note("start a record", r.status_code == 201, f"{r.status_code} {r.text[:160] if r.status_code != 201 else ''}")
    record = r.json()["record_id"]
board = st.get(f"/workspace/alliance-selection/drafts/{record}").json()
note("board loads with rules and ranks", board["configured"] and board["setup"]["ranks"] is not None,
     f"missing={board['setup']['missing']}")


def act(c, type_, seed, team, override=None):
    body = {"type": type_, "seed": seed, "team_number": team}
    if override:
        body["override_reason"] = override
    return c.post(f"/workspace/alliance-selection/drafts/{record}/actions", headers=H, json=body)


def recs():
    t = time.perf_counter()
    r = st.get(f"/workspace/alliance-selection/drafts/{record}/recommendations").json()
    return r, time.perf_counter() - t


r = act(dr, "captain", 1, board["turn"]["expected_captain"] or board["available"][0]["team_number"])
note("a drive member cannot record", r.status_code == 403, str(r.status_code))
cap = board["turn"]["expected_captain"]
r = act(st, "captain", 1, cap)
note("confirm alliance 1's captain", r.status_code == 200, f"captain {cap}")
board = r.json()
rec, secs = recs()
note("recommendations cite the record number", rec["record_seq"] == board["record_seq"], f"seq {rec['record_seq']} in {secs:.2f}s")
avail = [t["team_number"] for t in board["available"]]
# An illegal action: alliance 3 picks while it is alliance 1's turn.
r = act(st, "pick", 3, avail[5])
note("an out-of-turn pick is refused with the rule's code", r.status_code == 409 and r.json()["error"]["code"] == "wrong_turn",
     f"{r.status_code} {r.json().get('error', {}).get('code')}")
pick = rec["primary"]["team_number"] if rec.get("primary") else avail[1]
r = act(st, "pick", 1, pick)
note("alliance 1 picks the recommended primary", r.status_code == 200, f"pick {pick}")
board = r.json()
rec2, secs2 = recs()
listed = [rec2["primary"]["team_number"]] + [b["team_number"] for b in rec2["backups"]] if rec2.get("primary") else []
note("the picked team leaves every list", pick not in listed and pick not in [t["team_number"] for t in board["available"]],
     f"{rec2.get('status')} {rec2.get('withheld')} in {secs2:.2f}s")
# Undo, then correct.
last = board["effective"][-1]["action_id"]
r = st.post(f"/workspace/alliance-selection/drafts/{record}/undo", headers=H, json={"target_action_id": last})
note("undo the pick (kept in the history, superseded)", r.status_code == 200 and any(not h["in_effect"] for h in r.json()["history"]),
     str(r.status_code))
r = act(st, "pick", 1, pick)
board = r.json()
target = board["effective"][-1]["action_id"]
other = [t["team_number"] for t in board["available"]][2]
r = st.post(f"/workspace/alliance-selection/drafts/{record}/corrections", headers=H,
            json={"target_action_id": target, "replacement": {"type": "pick", "seed": 1, "team_number": other}})
note("correct the pick to another team", r.status_code == 200 and other in r.json()["alliances"][0]["picks"], str(r.status_code))
# Decline on alliance 2.
board = r.json()
cap2 = board["turn"]["expected_captain"]
r = act(st, "captain", 2, cap2)
board = r.json()
decliner = [t["team_number"] for t in board["available"] if t["projected_captain_of"] is None][0]
r = act(st, "decline", 2, decliner)
note("record a decline", r.status_code == 200, f"{r.status_code} {r.text[:120] if r.status_code != 200 else ''}")
r = act(st, "pick", 2, decliner)
note("a declined team cannot then be picked (rules) unless overridden", r.status_code == 409, f"{r.status_code} {r.json().get('error', {}).get('code')}")
r = act(st, "pick", 2, decliner, override="audit: testing the override path")
note("the room's real action is recorded with an override", r.status_code == 200, str(r.status_code))
rec3, secs3 = recs()
note("recommendations still current after the override", rec3["record_seq"] == r.json()["record_seq"], f"{rec3['status']} {secs3:.2f}s")
r = st.post(f"/workspace/alliance-selection/drafts/{record}/close", headers=H, json={})
note("close the record", r.status_code == 200 and r.json()["status"] == "closed", str(r.status_code))
r = act(st, "pick", 3, avail[-1])
note("a closed record refuses actions", r.status_code == 409 and r.json()["error"]["code"] == "record_closed", str(r.status_code))
r = st.post(f"/workspace/alliance-selection/drafts/{record}/reopen", headers=H, json={})
note("reopen", r.status_code == 200 and r.json()["status"] == "open", str(r.status_code))
print(json.dumps({"passed": sum(ok for _, ok, _ in results), "of": len(results)}))
