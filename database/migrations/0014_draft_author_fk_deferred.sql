-- Phase 11 fix: a workspace's live draft history goes with the workspace, by cascade, as 0013 documents.
--
-- 0013's author foreign keys (draft_records_author_fk, draft_actions_author_fk) reference team_memberships and were
-- checked immediately. Deleting a workspace cascades to its memberships and to its records and actions, but
-- PostgreSQL ran the author check for a deleted membership before the cascade had removed the actions that name it,
-- so deleting any workspace that had recorded a draft action failed with a foreign-key violation (found on
-- 2026-11-09, the first run of the DB-backed Phase 11 tests on an isolated copy).
--
-- Checking the two author keys at commit (DEFERRABLE INITIALLY DEFERRED) lets the cascade finish first. Nothing else
-- changes: removing a member who authored history, without its workspace, is still refused at commit, so the log
-- keeps every author (members are removed by status, never deleted: workspaces/management.py remove_member). No
-- data is touched, so the D18 fingerprints are unchanged by applying it.

ALTER TABLE draft_records ALTER CONSTRAINT draft_records_author_fk DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE draft_actions ALTER CONSTRAINT draft_actions_author_fk DEFERRABLE INITIALLY DEFERRED;
