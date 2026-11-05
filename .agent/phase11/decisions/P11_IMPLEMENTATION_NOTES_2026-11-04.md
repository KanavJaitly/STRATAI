# Phase 11: implementation decisions (2026-11-04)

These are ordinary engineering decisions taken while building Phase 11, recorded for traceability. None changes
P11-Q1 … Q4 (`P11_Q1_Q4_DECISIONS_2026-11-04.md`), and none changes a frozen record.

1. **Locked, but outside the P7-Q4 example scope.**
   - The ten `/workspace/alliance-selection/drafts…` operations are locked, as §3.1 requires; no earlier entry
     changed (lock revision of 2026-11-04).
   - `api/examples.py` `examples_scope` now leaves out the `/workspace/` operations (`TEAM_PRIVATE_PREFIX`). They
     need a member's session, and a committed capture would publish one team's private draft record and picklist.
   - The P7-Q4 scope stays the same 23 operations.
2. **Two behavior-preserving extractions in Phase 6/7 code**, so that the live record reuses the rules instead of
   copying them:
   - `ml.playoffs.selection.pickable_teams` and `highest_ranked_captain`, behind `available_for_pick` and `_captain`;
   - `ml.playoffs.service.ranks_are_final`, the step-4 final-ranks rule, which `pick_list` now calls.
   - Also added: the public `approved_event_rules` and `qualification_schedule`.
   - No result changes. The existing Phase 6 and Phase 7 tests pass unchanged.
3. **`data.rankings.read_event_ranks`**: a per-event form of `read_final_ranks_for_season`, with the same raw read
   and the same parser.
4. **`set_role_permissions`** refuses `permission_needs_migration` (409) when the database's CHECK constraint
   predates a permission (0013 not applied). Before, toggling the new permission there would have been a 500.
5. **Fixed in passing:** `frontend/src/workspace/EventChooser.tsx` set `aria-controls` to a list that was not
   rendered. axe reported it on the new page. It now names the list only while it is shown.
6. **Environment of this build:**
   - Python 3.14 in a project `.venv`.
   - XGBoost 2.1.4, not the latest. The machine has no system OpenMP, and 2.1.4 runs on the OpenMP runtime that
     scikit-learn bundles (`DYLD_LIBRARY_PATH=.venv/lib/python3.14/site-packages/sklearn/.dylibs`).
   - No PostgreSQL. Starting a pip-packaged server was refused by the session's permission policy, so DB-backed
     tests skip here.
7. **Fixes from the independent adversarial review (2026-11-04).** All of these were found before acceptance, and
   each is fixed with a regression test where one is practical. 
   - `captain_may_accept_higher_alliance=False` is now applied to the pool. The new unavailable reason is
     `projected_captain`. This is a relock of the Phase 11 `GET …/drafts…` entries locked earlier the same day; no
     pre-Phase 11 entry changes.
   - A refresh keeps the rules an administrator entered.
   - On the page:
     - a stale recommendation is never highlighted;
     - an older poll cannot replace a newer board;
     - a withheld recalculation keeps the last picks visible, marked stale;
     - a retried write reuses its action id.
   - P11-FB1 is withheld before the selection moment (`selection_time_unavailable`) instead of ordering at "now",
     as the frozen rule says.
   - Writes check the permission before the body is validated.
   - Unique-key races give 409 `draft_exists` / `action_id_conflict`, not 500.
   - The engine path applies the same rule exclusions and serves its scope reasons.
   - Superseded setups show as superseded.
8. **Two pinned regression tests were updated for the new operations, without weakening either:**
   - `tests/test_phase10_hardening.py`: the 413 is declared on 47 body-taking operations, up from 40. The seven new
     ones are the Phase 11 writes. The body limit applies to them automatically (`api.body_limit`).
   - `tests/test_phase6_contract.py`: `api.routes.live_draft` is named as a sanctioned module for the path family
     `/workspace/alliance-selection/drafts…`. Its recommendations call the P6-M7 engine unchanged, as §5 requires.
     Any other module serving a Phase 6 capability is still caught.
