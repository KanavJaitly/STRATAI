# Audit follow-up workstreams, 2026-11-26 — work log

Scope: the nine workstreams that followed the 2026-11-26 audit (`.agent/audit_2026-11-26/AUDIT_REPORT.md`). Branch:
`audit/2026-11-26`.

The branch's commit IDs changed on 2026-11-26/27 with the history rewrite (workstream 4). Old-to-new IDs for every
rewritten commit are in `history_rewrite_commit_map.txt`, next to this file. Use it for any commit ID cited in
CLAUDE.md, RUNNING_NOTES.md or `.agent/` records from before the rewrite; for example `3757d2a` → `c4a0378`,
`34cefb5` → `80bed5a`.

Every database-backed check ran on an isolated copy. The serving `stratai` and the source copy `stratai_test` were
not modified.

## Commits (on audit/2026-11-26, after the rewrite)

| Commit | Workstream |
|---|---|
| 2ac3c8e | the audit itself (was 9538fab) |
| 69d308f | WS9: no write-access request for non-administrators |
| 10f3eb8 | WS3: validation labels only where they were measured |
| 08c67e0 | WS5: trusted proxy chain for rate-limit addresses |
| 487ebab | WS6: local development database stratai_dev_fresh |
| 7b63d8e | WS9 follow-up: useWriteAccess in its own module |
| cc9e4ff | WS8: in-app ScoutRadioz CSV upload |
| 760143d | WS7: alliance optimizer foundation |
| 06e01b6 | WS1 + WS2: frozen research candidates |
| 790ed72 | WS4: keep scouting exports out of the repository |

`git log --oneline origin/main..audit/2026-11-26` lists them all.

## WS1 — win-probability model

- **Diagnosis.** M6 uses raw game points. The 2026 season scale is 3.29× the 2024–25 mean (2.6× 2025, 4.6× 2024).
  The audit's "2.5–3.8×" is corrected.
- **Candidate.** WP-NORM-EPA-v1, frozen in `.agent/model_candidates/WP-NORM-EPA-v1.md`.
- **Code.** `ml/candidates/win_prob_norm_epa.py`, `scripts/evaluate_model_candidates.py`.
- **2026, retrospective only.** Log loss 0.4988 against the served model's 0.5394 (95% CI of the difference −0.063 to
  −0.019). G2 fails, so on 2026 the candidate would fail its own gate.
- **Two corrections.** The served model's log loss is 0.539 under the project's metric; the audit's 0.524 used a looser
  clamp. The audit's single-scale normalization scored better on 2026. It was not adopted, because that would be
  choosing a definition by its 2026 result; it is recorded as a v2 idea.
- **Production unchanged.**

## WS2 — ranking model

- **Candidate.** RANK-BLEND-v1, frozen in `.agent/model_candidates/RANK-BLEND-v1.md`. Formula: the mean of the
  available values among prior EPA and the in-event average ÷ 3.
- **The audit reproduces exactly:** midpoint Spearman 0.7166 against M5 v2's 0.6112, better in 194 of 208 events.
- **Limits.**
  - At the midpoint it beats the in-event average alone by only +0.015.
  - At the last snapshot the in-event average is better.
- **Point-in-time.** Tests show the snapshot rating ignores later matches.
- **Production unchanged.**

## WS3 — validation labels

Done before this log. Commit "Workstream 3"; `ml/validation_scope.py`, `tests/test_validation_scope.py`.

## WS4 — personal scouting data removed from public history

**Found** (names never printed; matched in memory against the export's 26 scout names):
- `data/imports/matchscouting_frc11_2026mrcmp_full.csv` (26 names);
- `data/imports/DCMP_2026_Scouting_Data.xlsx`;
- `tests/fixtures/scoutradioz_matchscouting_2026mrcmp.csv` (20 names);
- one name in a `data/metrics/scoutradioz.py` docstring;
- one name in each of `tests/test_scoutradioz_client.py` and `tests/test_scoutradioz_import.py`.

No commit message contained a name.

**Backups, outside the repository:**
- the files and the name→pseudonym map: `C:/Users/Kanav/StratAI-private/2026-11-26_scouting_data/` (readable only by
  Kanav, SYSTEM and Administrators; hashes verified);
- every ref before the rewrite: `C:/Dev/StratAI-backups/2026-11-26_pre-rewrite/all-refs-pre-rewrite.bundle`
  (verified), with ref listings and the remote's state;
- the earlier pre-workstreams bundle: `C:/Dev/StratAI-backups/2026-11-26_pre-workstreams/`.

**The rewrite** (`git filter-repo 2.47.0`, in a throwaway mirror with the remote's branches in their own namespace):
- removed `data/imports/`;
- replaced each name with a fixed pseudonym (`Scout 01`–`Scout 26`) in every file of every commit;
- updated commit IDs cited in messages.

No other change: per ref, the files differ only in those paths, and the messages only in the cited commit IDs.

**Remote**, before the push:
- fetched and inspected: 32 branches, which matched the tracked refs exactly, and were unchanged again just before
  the push;
- not diverged: `audit/2026-11-26` was 9 ahead and 0 behind `origin/main`;
- no branch protection or rulesets on `main`.

**Pushed:** 31 rewritten branches, in one atomic push, each with a lease on its exact old ID. The 32nd,
`automation/phase4-state`, is an orphan branch of the monitor bot that holds no affected file, so it was unchanged and
not pushed.

**Verified on GitHub:** a fresh clone of all branches has no `data/imports` path and none of the names, across 5,203
objects.

**Local repository:**
- 21 local branches were moved to their rewritten commits (compare-and-swap);
- the current branch was moved with `reset --keep`, and the uncommitted `docs/P11-P19Phases.md` is kept;
- the exports are back in `data/imports/`, now ignored;
- the worktrees `StratAI-deploy` and `StratAI-integration` were realigned. Their own uncommitted work is kept; they
  still hold untracked copies of the exports.

**Not reachable from here, and why:**
- **GitHub pull-request refs.** 44 of the 59 `refs/pull/*/head` refs point at commits with the data, and they are
  read-only. Those commits stay viewable by ID and on the PR pages until **GitHub Support** removes them.
  GitHub's "Removing sensitive data from a repository" procedure asks for the affected PRs and the commit map.
- **Sven's fork**, `svenmorais-debug/STRATAI`, still has the old history. Only he, or GitHub Support, can rewrite it.
  Until he re-clones (or resets every branch to the rewritten remote), anything he pushes or opens as a PR from old
  history brings the data back.
- **Copies already downloaded.** Clones, forks, caches, and anyone who downloaded the files cannot be recalled.
  Rewriting history stops future exposure only.

**Kept from coming back:**
- `.gitignore` covers `data/imports/*` (except its README and a synthetic example), `*.xlsx` and `*.xls`;
- `tests/test_no_personal_scouting_data.py` fails if an export or spreadsheet is tracked, or if a tracked
  ScoutRadioz CSV has a scouter that is not a pseudonym.

## WS5 — trusted proxy

- **`client_ip`** counts `X-Forwarded-For` from the right and requires a valid IP; otherwise it uses the connecting
  peer.
- **`GET /auth/network-check`** (administrators only) shows what the server sees.
- **Tests:**
  - address extraction (9 cases);
  - per-client isolation behind two proxies, for sign-in, sign-up and reset;
  - the check route's permission.
- **No Render access from here.** `docs/DEPLOYMENT.md` §4.1 gives the exact steps and a two-network verification.
- **Known limit.** Requests sent directly to `stratai-api.onrender.com` bypass Vercel, so the per-address limits can be
  steered there. The per-account and global limits still hold.

## WS6 — local development database

- **`scripts/local_dev_db.py --create`** makes `stratai_dev_fresh`, a template copy of `stratai_test` migrated to 0016,
  and can drop only that database.
- **`local_test_env --serve`** defaults to it, using local join codes (`local-dev-admin`, `local-dev-join`) and
  `ACCESS_POLICY=members`.
- **Smoke test:** sign-up, sign-in, refusals, team-private routes, 190 events for 2024 and analysis 200. The copy was
  then recreated empty.
- **`stratai_test`** stayed at 0014, with its 2024njfla record (1 draft, 28 actions). It was backed up with `pg_dump`
  to `C:/Dev/StratAI-backups/2026-11-26_pre-workstreams/stratai_test_20261126.dump`.

## WS7 — alliance optimizer foundation

- **Code:** `ml/alliance/optimizer/`, documented in `docs/alliance_optimizer.md`.
- **Inactive:**
  - a test proves nothing in the API, workspaces, data or scripts imports it;
  - no season configuration is shipped;
  - an unapproved configuration is refused.
- **Tests:** 19, all synthetic.
- **Open:** the values that need approval are listed in docs section 2.

## WS8 — scouting CSV upload

- **Where:** `/scouting/import` (administrators, `scouting_import`); `data/metrics/scoutradioz_upload.py`,
  `api/routes/scouting_import.py`; docs in `docs/team_workspaces.md` §6.1.
- **How it works:**
  - the preview writes nothing;
  - the import needs the previewed file's sha256 and a confirmation;
  - it reuses `import_scoutradioz_csv`, and retries are idempotent;
  - a stored observation is never overwritten;
  - only the team's own organization is accepted;
  - scouts' names are never returned;
  - the mapping comes from `data/metrics/scoutradioz_mappings.py` (2026 only).
- **Tests:** 12 backend, 5 frontend.

## WS9 — no write-access request for non-administrators

Done before this log. Commit "Workstream 9"; the follow-up moves `useWriteAccess` to its own module, which keeps lint
at its 8-warning baseline.

## Final verification

See `FINAL_VERIFICATION.md` in this folder.
