# Incident 2026-11-09: migrations 0010–0013 applied to the serving database without approval

**Resolution: KEPT (Sven Morais, 2026-11-09).**
- The 18 empty tables and the four `migrations_applied` rows stay; the local serving database is now at 0013.
- No rollback or drop DDL was run.
- This is an operational incident, not a Phase 11 verification result. No acceptance criterion or record was altered
  because of it.

## What happened

| | |
|---|---|
| When | 2026-11-09 18:40:52 America/New_York (`migrations_applied.applied_at`, all four rows) |
| Database | the serving database on Sven's machine, `stratai` (the one `.env` names) |
| Migrations | `0010_phase5_human_inputs.sql`, `0011_phase6_season_rulesets.sql`, `0012_team_workspaces.sql`, `0013_live_alliance_selection.sql` (it was at 0009) |
| How | Phase 11 verification was meant to migrate an isolated copy, `stratai_test_p11` (cloned by template from `stratai_test_handoff`). The step that wrote the copy's env file failed (the file it was derived from no longer existed), but the shell command continued past the failure and ran `python -m database.migrate` with no `DATABASE_URL` exported, so `Settings()` resolved `.env`'s serving URL. Same mechanism as the 2026-10-04 incident. |
| Whose error | Claude's, as operator: the commands were chained with `;` after a failing step instead of stopping, and no target check preceded the migration. |

## Affected objects

18 tables created by 0010–0013 (`game_manuals`, `game_spec_versions`, `capability_profiles`, `human_review_artifacts`,
`season_rulesets`, `workspaces`, `users`, `team_memberships`, `invitations`, `workspace_role_permissions`,
`auth_sessions`, `password_reset_tokens`, `auth_attempts`, `activity_logs`, `scouting_assignments`,
`workspace_scouting_reports`, `draft_records`, `draft_actions`) with their indexes, sequences, constraints and
triggers, and four rows in `migrations_applied`. All four migrations are additive: no `UPDATE`, `DELETE`, `TRUNCATE`,
or `DROP` of a pre-existing object (0012 and 0013 drop and recreate only triggers and a CHECK on tables they create).

## Verification that serving data was untouched (read-only, after the incident)

- The 18 new tables hold 0 rows in total.
- The latest serving-data timestamps all predate the incident: `matches.last_updated` 2026-08-07 23:17,
  `pipeline_runs` 2026-08-08 01:20, `team_metrics` 2026-08-08 01:20.
- Untouched: `stratai_test_handoff` (still at 0011), `stratai_test` (0011). The intended target `stratai_test_p11` was
  not migrated by that command.
- The hosted demo (Render) uses its own database and is unaffected.

## Prevention

- Every later Phase 11 database command runs through a wrapper that loads the copy's env file and refuses to run
  unless the connected database is exactly `stratai_test_p11`, with `set -e` so a failed step stops the command.
- `origin/p11a/recommendation-intelligence` (d51d626) adds `database/target_guard.py`, which makes `database/migrate.py`
  refuse the serving `stratai` outright. It is not on `main` yet; merging it would have prevented this.
