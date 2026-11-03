-- Team workspaces: individual accounts, memberships, roles and permissions, invitations, sessions, the activity
-- log, and each team's private scouting (docs/team_workspaces.md).
--
-- A workspace is one FRC team's private area on StratAI. It is named `workspaces`, not `teams`, because `teams`
-- already holds the canonical FRC team list from TBA; a workspace records the team number it belongs to.
--
-- Every row of team-private data carries workspace_id. The API takes the workspace from the caller's server-side
-- session, never from the request, and every query filters on it (workspaces/). The constraints below hold the
-- rest of the model in the database itself:
-- - at most one pending or verified workspace per FRC team number;
-- - a member's scouting report and a scouting assignment can only name a member of the same workspace
--   (composite foreign keys onto team_memberships);
-- - role permissions can only grant the configurable permissions, and only to the non-admin roles, so an
--   administrative permission can never be stored for a strategy or scouter role;
-- - a workspace that has an active administrator always keeps at least one (trg_keep_an_active_admin);
-- - every secret (session, invitation, reset and setup credentials) is stored only as a hash.
-- Nothing here touches the public data tables, so the D18 fingerprints (team_event_stats, TBA raw payloads) are
-- unchanged by applying it.

CREATE TABLE IF NOT EXISTS workspaces (
    id                   BIGSERIAL PRIMARY KEY,
    team_number          INT         NOT NULL,
    team_name            TEXT        NOT NULL,
    verification_status  TEXT        NOT NULL DEFAULT 'pending_verification',
    verification_note    TEXT,
    verified_at          TIMESTAMPTZ,
    verified_by          TEXT,
    -- The one-time onboarding credential: set at registration, cleared when the first administrator is created.
    setup_password_hash  TEXT,
    settings             JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT workspaces_team_number_check CHECK (team_number BETWEEN 1 AND 99999),
    CONSTRAINT workspaces_team_name_check CHECK (char_length(btrim(team_name)) BETWEEN 1 AND 100),
    CONSTRAINT workspaces_status_check
        CHECK (verification_status IN ('pending_verification', 'verified', 'rejected')),
    CONSTRAINT workspaces_verified_check
        CHECK (verification_status <> 'verified' OR (verified_at IS NOT NULL AND verified_by IS NOT NULL)),
    CONSTRAINT workspaces_settings_check CHECK (jsonb_typeof(settings) = 'object')
);
-- A rejected registration frees the number for the real team.
CREATE UNIQUE INDEX IF NOT EXISTS workspaces_one_active_per_team
    ON workspaces (team_number) WHERE verification_status IN ('pending_verification', 'verified');

CREATE TABLE IF NOT EXISTS users (
    id                   BIGSERIAL PRIMARY KEY,
    email                TEXT        NOT NULL,
    full_name            TEXT        NOT NULL,
    -- Which system holds the credential. 'stratai' is the built-in provider (password_hash below); another provider
    -- would set auth_subject to its own user id and leave password_hash NULL.
    auth_provider        TEXT        NOT NULL DEFAULT 'stratai',
    auth_subject         TEXT,
    password_hash        TEXT,
    status               TEXT        NOT NULL DEFAULT 'active',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    password_changed_at  TIMESTAMPTZ,
    CONSTRAINT users_email_check CHECK (email = lower(btrim(email)) AND email ~ '^[^@\s]+@[^@\s]+$'
                                        AND char_length(email) <= 254),
    CONSTRAINT users_full_name_check CHECK (char_length(btrim(full_name)) BETWEEN 1 AND 120),
    CONSTRAINT users_provider_check CHECK (auth_provider IN ('stratai', 'supabase')),
    CONSTRAINT users_credential_check CHECK (auth_provider <> 'stratai' OR password_hash IS NOT NULL),
    CONSTRAINT users_status_check CHECK (status IN ('active', 'disabled')),
    CONSTRAINT users_email_unique UNIQUE (email)
);
CREATE UNIQUE INDEX IF NOT EXISTS users_provider_subject_unique
    ON users (auth_provider, auth_subject) WHERE auth_subject IS NOT NULL;

CREATE TABLE IF NOT EXISTS team_memberships (
    id                  BIGSERIAL PRIMARY KEY,
    workspace_id        BIGINT      NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    user_id             BIGINT      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role                TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'active',
    -- The name this team shows for the member. A person can belong to several teams, so a team's administrator
    -- edits this, never the person's own users.full_name.
    display_name        TEXT,
    invited_by_user_id  BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at       TIMESTAMPTZ,
    CONSTRAINT team_memberships_role_check CHECK (role IN ('admin', 'strategy', 'scouter')),
    CONSTRAINT team_memberships_status_check CHECK (status IN ('active', 'suspended', 'removed')),
    CONSTRAINT team_memberships_display_name_check
        CHECK (display_name IS NULL OR char_length(btrim(display_name)) BETWEEN 1 AND 120),
    CONSTRAINT team_memberships_unique UNIQUE (workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS team_memberships_user ON team_memberships (user_id);

-- Keep at least one active administrator in a workspace that has one. Locking the workspace row serialises two
-- concurrent demotions, so they cannot both pass by each seeing the other administrator still active.
CREATE OR REPLACE FUNCTION keep_an_active_admin() RETURNS trigger AS $$
BEGIN
    IF OLD.role = 'admin' AND OLD.status = 'active'
       AND (TG_OP = 'DELETE' OR NEW.role <> 'admin' OR NEW.status <> 'active') THEN
        PERFORM 1 FROM workspaces WHERE id = OLD.workspace_id FOR UPDATE;
        IF FOUND AND NOT EXISTS (SELECT 1 FROM team_memberships
                                 WHERE workspace_id = OLD.workspace_id AND role = 'admin' AND status = 'active') THEN
            RAISE EXCEPTION 'workspace % would have no active administrator', OLD.workspace_id
                USING ERRCODE = 'check_violation', CONSTRAINT = 'team_memberships_last_active_admin';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_keep_an_active_admin ON team_memberships;
CREATE TRIGGER trg_keep_an_active_admin
    AFTER UPDATE OR DELETE ON team_memberships
    FOR EACH ROW EXECUTE FUNCTION keep_an_active_admin();

CREATE TABLE IF NOT EXISTS invitations (
    id                  BIGSERIAL PRIMARY KEY,
    workspace_id        BIGINT      NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    email               TEXT        NOT NULL,
    full_name           TEXT        NOT NULL,
    role                TEXT        NOT NULL,
    token_hash          TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'pending',
    expires_at          TIMESTAMPTZ NOT NULL,
    invited_by_user_id  BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at         TIMESTAMPTZ,
    accepted_user_id    BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    revoked_at          TIMESTAMPTZ,
    CONSTRAINT invitations_email_check CHECK (email = lower(btrim(email)) AND email ~ '^[^@\s]+@[^@\s]+$'),
    CONSTRAINT invitations_full_name_check CHECK (char_length(btrim(full_name)) BETWEEN 1 AND 120),
    CONSTRAINT invitations_role_check CHECK (role IN ('admin', 'strategy', 'scouter')),
    CONSTRAINT invitations_status_check CHECK (status IN ('pending', 'accepted', 'revoked')),
    CONSTRAINT invitations_token_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT invitations_accepted_check CHECK (status <> 'accepted' OR accepted_at IS NOT NULL),
    CONSTRAINT invitations_token_unique UNIQUE (token_hash)
);
CREATE UNIQUE INDEX IF NOT EXISTS invitations_one_pending_per_email
    ON invitations (workspace_id, email) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS workspace_role_permissions (
    workspace_id        BIGINT      NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    role                TEXT        NOT NULL,
    permission          TEXT        NOT NULL,
    granted             BOOLEAN     NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by_user_id  BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    PRIMARY KEY (workspace_id, role, permission),
    -- Administrators always hold every permission; only the two other roles are configurable.
    CONSTRAINT workspace_role_permissions_role_check CHECK (role IN ('strategy', 'scouter')),
    -- The configurable permissions (workspaces/permissions.py CONFIGURABLE_PERMISSIONS). The administrative ones
    -- (team management, permissions, settings, the activity log) are absent, so they can never be granted here.
    CONSTRAINT workspace_role_permissions_permission_check CHECK (permission IN (
        'team_info', 'match_predictions', 'team_analytics', 'event_analysis', 'qualification_forecast',
        'alliance_selection', 'strategy_tools', 'scouting_forms', 'scouting_submit', 'scouting_view',
        'scouting_assign'))
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id             BIGSERIAL PRIMARY KEY,
    token_hash     TEXT        NOT NULL,
    membership_id  BIGINT      NOT NULL REFERENCES team_memberships (id) ON DELETE CASCADE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at     TIMESTAMPTZ NOT NULL,
    revoked_at     TIMESTAMPTZ,
    CONSTRAINT auth_sessions_token_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT auth_sessions_token_unique UNIQUE (token_hash)
);
CREATE INDEX IF NOT EXISTS auth_sessions_membership ON auth_sessions (membership_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id                 BIGSERIAL PRIMARY KEY,
    membership_id      BIGINT      NOT NULL REFERENCES team_memberships (id) ON DELETE CASCADE,
    token_hash         TEXT        NOT NULL,
    expires_at         TIMESTAMPTZ NOT NULL,
    used_at            TIMESTAMPTZ,
    issued_by_user_id  BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT password_reset_tokens_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT password_reset_tokens_unique UNIQUE (token_hash)
);

-- Failed and successful credential attempts, for rate limiting. The subject (an IP address, or a team number and
-- email) is stored only as a hash.
CREATE TABLE IF NOT EXISTS auth_attempts (
    id            BIGSERIAL PRIMARY KEY,
    scope         TEXT        NOT NULL,
    subject_hash  TEXT        NOT NULL,
    succeeded     BOOLEAN     NOT NULL,
    attempted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT auth_attempts_subject_check CHECK (subject_hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS auth_attempts_lookup ON auth_attempts (scope, subject_hash, attempted_at);

CREATE TABLE IF NOT EXISTS activity_logs (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT      NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    actor_user_id   BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    actor_label     TEXT        NOT NULL,
    action          TEXT        NOT NULL,
    target_user_id  BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    target_label    TEXT,
    details         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT activity_logs_details_check CHECK (jsonb_typeof(details) = 'object')
);
CREATE INDEX IF NOT EXISTS activity_logs_workspace_time ON activity_logs (workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS scouting_assignments (
    id                  BIGSERIAL PRIMARY KEY,
    workspace_id        BIGINT      NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    event_key           TEXT        NOT NULL REFERENCES events (event_key),
    match_key           TEXT        NOT NULL REFERENCES matches (match_key),
    team_number         INT         NOT NULL REFERENCES teams (team_number),
    assigned_user_id    BIGINT      NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'assigned',
    created_by_user_id  BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT scouting_assignments_status_check CHECK (status IN ('assigned', 'completed', 'cancelled')),
    CONSTRAINT scouting_assignments_match_event_check CHECK (left(match_key, char_length(event_key) + 1)
                                                            = event_key || '_'),
    CONSTRAINT scouting_assignments_member_fk FOREIGN KEY (workspace_id, assigned_user_id)
        REFERENCES team_memberships (workspace_id, user_id),
    -- The target of workspace_scouting_reports' composite key: a report can only cite its own team's assignment.
    CONSTRAINT scouting_assignments_workspace_id_unique UNIQUE (workspace_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS scouting_assignments_open_unique
    ON scouting_assignments (workspace_id, match_key, team_number, assigned_user_id) WHERE status <> 'cancelled';
CREATE INDEX IF NOT EXISTS scouting_assignments_assignee ON scouting_assignments (workspace_id, assigned_user_id);

-- A team's own scouting, private to its workspace. Same rating scale and match/event rules as
-- scouting_observations (data/metrics/schemas.py); kept separate so one team's scouting never reaches the shared
-- defense/feeding metrics every other team can read.
CREATE TABLE IF NOT EXISTS workspace_scouting_reports (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT      NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    user_id         BIGINT      NOT NULL,
    event_key       TEXT        NOT NULL REFERENCES events (event_key),
    match_key       TEXT        NOT NULL REFERENCES matches (match_key),
    team_number     INT         NOT NULL REFERENCES teams (team_number),
    defense_rating  INT,
    feeding_rating  INT,
    notes           TEXT,
    assignment_id   BIGINT,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT workspace_scouting_reports_member_fk FOREIGN KEY (workspace_id, user_id)
        REFERENCES team_memberships (workspace_id, user_id),
    -- Assignments are cancelled, never deleted, so this needs no ON DELETE action.
    CONSTRAINT workspace_scouting_reports_assignment_fk FOREIGN KEY (workspace_id, assignment_id)
        REFERENCES scouting_assignments (workspace_id, id),
    CONSTRAINT workspace_scouting_reports_match_event_check CHECK (left(match_key, char_length(event_key) + 1)
                                                                  = event_key || '_'),
    CONSTRAINT workspace_scouting_reports_defense_check CHECK (defense_rating IS NULL OR defense_rating BETWEEN 0 AND 5),
    CONSTRAINT workspace_scouting_reports_feeding_check CHECK (feeding_rating IS NULL OR feeding_rating BETWEEN 0 AND 5),
    CONSTRAINT workspace_scouting_reports_rating_present_check
        CHECK (defense_rating IS NOT NULL OR feeding_rating IS NOT NULL),
    CONSTRAINT workspace_scouting_reports_notes_check CHECK (notes IS NULL OR char_length(notes) <= 2000)
);
CREATE INDEX IF NOT EXISTS workspace_scouting_reports_event
    ON workspace_scouting_reports (workspace_id, event_key, team_number);
CREATE INDEX IF NOT EXISTS workspace_scouting_reports_author ON workspace_scouting_reports (workspace_id, user_id);
