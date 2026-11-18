# Follow-up: sync "Our pick list" through the server

Status: **proposed, not started** (2026-11-17). The pick list ships browser-only; this page is what the backend would
need to share it across the team's devices.

## Today

The alliance selection page leads with **Our pick list** (`frontend/src/dashboard/teamPickList.tsx`):

- the team's own order of every candidate at one event, starting in scoring-EPA order;
- reordered with up/down buttons, a typed rank, or dragging on a laptop;
- saved in the browser's `localStorage` under `stratai.picklist.<event_key>`, as a JSON array of team numbers;
- moved between devices only by hand: **Copy list** writes one line (`StratAI pick list <event_key>: 254, 1678, …`),
  and **Import list** reads it back, keeping only teams on the event's roster and appending any missing teams.

What that leaves out: two people editing at once, a phone and a laptop agreeing, and any record of who changed what.
The page says so ("not synced between devices yet").

## What the backend would need

### 1. Storage (one migration)

A team-private table, scoped to the single team workspace like the other team tables (migration 0013's draft
records):

| column | type | notes |
|---|---|---|
| `id` | bigint identity | |
| `workspace_id` | FK `workspaces` | the team (there is one, team 11, but keep the key) |
| `event_key` | FK `events` | |
| `team_order` | `integer[]` | team numbers, rank 1 first |
| `version` | integer | +1 on every save; used to detect concurrent edits |
| `updated_by` | FK `team_memberships` | |
| `updated_at` | timestamptz | |

Constraint: unique `(workspace_id, event_key)`. Keep history only if the team wants it: either an append-only
`pick_list_revisions` table, or nothing (the live draft already records the real picks).

`scripts/refresh_staged.py` (the hosted data reload) must keep the new table in its KEEP set, like the other
team tables.

### 2. API (two locked operations)

- `GET /workspace/pick-lists/{event_key}`: returns `{event_key, team_order, version, updated_by, updated_at}`, or 404
  `pick_list_not_set` when nobody has saved one (the page then starts in EPA order, as today).
- `PUT /workspace/pick-lists/{event_key}` with `{team_order, base_version}`: CSRF-checked like every write. The server
  checks every number is a team on the event's roster (`match_teams`), with no duplicates. It saves only if
  `base_version` matches the stored version; otherwise it returns **409** `pick_list_conflict` with the current list,
  and the page offers "keep theirs / overwrite with mine". Each save records an activity log entry.

Both are added to `docs/api_contract_lock.json` (`python -m scripts.phase7_contract_lock check`), and the frontend
types are regenerated (`scripts/phase8_generate_api_types.py`).

### 3. Permissions

- **Read:** `alliance_selection` (already granted to admins; base members cannot open the alliance page).
- **Write:** a new fixed grant, `pick_list_edit`, admin-only by default. It's an open question whether recorders of
  the live draft (`alliance_selection_record`) should also edit.

### 4. Frontend changes

- Load from the server first, and fall back to `localStorage` when offline or when the API refuses, so the list still
  works with bad venue Wi-Fi.
- Save after each change, debounced (about 1 s), with the `version` it was based on. Show "Saved" or "Not saved:
  offline" next to the heading.
- On a 409, show both lists and let the person choose. Never merge silently.
- Poll lightly (every 10–15 s, like the live draft's polling but slower) so a second device catches up. Show
  "Updated by <name> just now" when the order changes underneath you.
- Keep **Copy list** and **Import list**. They're still useful for sharing with another team's scouts.

### 5. Tests

- API: a roster check, duplicate refusal, the version conflict (409), the permission split, and CSRF.
- Frontend: server-first load, offline fallback, the conflict choice, and no change to any value shown (the list only
  orders teams).

## Out of scope

- Ranking or reordering automatically from a model. The engine's ranking stays a separate section, and the playoff
  model is still not validated (P6-DM1).
- Sharing between teams.
