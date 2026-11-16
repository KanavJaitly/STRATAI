-- Single-team accounts: StratAI serves one team, FRC Team 11 (MORT) (docs/team_workspaces.md).
--
-- The multi-team model of 0012 (team registration with a setup password, the first-administrator flow, operator
-- verification, invitations, per-workspace role permissions) is replaced by:
-- - one workspace row, team 11, created here already verified; every account belongs to it;
-- - sign-up with a team join code (TEAM_JOIN_CODE), and two roles, admin and base;
-- - password reset by a 6-digit emailed code instead of a link.
-- The workspace layer itself stays (workspace_id on every team-private row, sessions bound to a membership), so the
-- team scouting and live-draft code is unchanged.
--
-- No existing account data is kept (decided 2026-11-11). This migration DELETES every row of: workspaces, and by
-- cascade team_memberships, auth_sessions, password_reset_tokens, invitations, workspace_role_permissions,
-- activity_logs, scouting_assignments, workspace_scouting_reports, draft_records and draft_actions; users; and
-- auth_attempts. It DROPS the tables invitations, password_reset_tokens and workspace_role_permissions, and the column
-- workspaces.setup_password_hash. Nothing here touches the public data tables, so the D18 fingerprints are unchanged.

-- 1. Remove every account and every team-private row. Deleting the workspaces cascades to everything keyed by
--    workspace_id (draft author keys are deferred since 0014, so the cascade completes before they are checked).
DELETE FROM workspaces;
DELETE FROM users;
DELETE FROM auth_attempts;
-- Run the deferred draft author checks now, not at commit: the cascade above has removed every row they refer to,
-- so they pass, and PostgreSQL refuses to ALTER team_memberships (step 3) while their trigger events are pending.
-- (Found 2026-11-16 applying 0015 to a copy that had draft history; a database with no accounts never hits it.)
SET CONSTRAINTS ALL IMMEDIATE;

-- 2. Drop what the single-team model no longer uses.
DROP TABLE IF EXISTS invitations;
DROP TABLE IF EXISTS password_reset_tokens;
-- Role permissions are fixed in code now (workspaces/permissions.py ROLE_GRANTS), so nothing configurable is stored.
DROP TABLE IF EXISTS workspace_role_permissions;
ALTER TABLE workspaces DROP COLUMN IF EXISTS setup_password_hash;

-- 3. Two roles.
ALTER TABLE team_memberships DROP CONSTRAINT IF EXISTS team_memberships_role_check;
ALTER TABLE team_memberships ADD CONSTRAINT team_memberships_role_check CHECK (role IN ('admin', 'base'));

-- 4. Password reset codes. Only a salted SHA-256 of the 6-digit code is stored. A code works once, until expires_at
--    (15 minutes), and while failed_attempts is below 5; asking for a new code retires the earlier ones.
CREATE TABLE IF NOT EXISTS password_reset_codes (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    code_salt        TEXT        NOT NULL,
    code_hash        TEXT        NOT NULL,
    expires_at       TIMESTAMPTZ NOT NULL,
    failed_attempts  INT         NOT NULL DEFAULT 0,
    used_at          TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT password_reset_codes_salt_check CHECK (code_salt ~ '^[0-9a-f]{32}$'),
    CONSTRAINT password_reset_codes_hash_check CHECK (code_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT password_reset_codes_attempts_check CHECK (failed_attempts >= 0)
);
CREATE INDEX IF NOT EXISTS password_reset_codes_live ON password_reset_codes (user_id) WHERE used_at IS NULL;

-- 5. The one workspace. The unique index on a constant allows at most one row in the table.
CREATE UNIQUE INDEX IF NOT EXISTS workspaces_single_team ON workspaces ((true));
INSERT INTO workspaces (team_number, team_name, verification_status, verified_at, verified_by)
VALUES (11, 'MORT', 'verified', NOW(), 'migration 0015_single_team_auth');
