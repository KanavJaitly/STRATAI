-- Phase 11: live alliance selection. Each team keeps a private, append-only draft record per event
-- (docs/phase11.md; docs/P11-P19Phases.md §5; workspaces/draft_log.py, workspaces/live_draft.py).
--
-- Overview:
-- - A record is a log. draft_actions rows are written once and never updated (trg_draft_actions_append_only).
-- - The application never deletes them. They go only when their workspace is deleted, by cascade.
-- - The current state is derived by replaying the log in seq order. No state is stored, so none can drift from the
--   log.
--
-- Local-first by design (Phase 12 synchronizes logs, not snapshots):
-- - every record and action carries a stable UUID, created by the client or the local server;
-- - each action has a per-record sequence, an author, a server time and an optional client time;
-- - each action has a source (manual, imported) and a mode (online, local).
--
-- Team isolation holds in the database itself:
-- - every row carries workspace_id;
-- - an action can belong only to a record of its own workspace;
-- - an author can only be a member of that workspace. Both are composite foreign keys, as in 0012.
--
-- The new configurable permission alliance_selection_record (P11-Q2) is added to the CHECK constraint 0012 put on
-- workspace_role_permissions. That constraint keeps listing exactly workspaces/permissions.py
-- CONFIGURABLE_PERMISSIONS.
--
-- Nothing here touches the public data tables, so the D18 fingerprints are unchanged by applying it.

CREATE TABLE IF NOT EXISTS draft_records (
    id                  BIGSERIAL PRIMARY KEY,
    workspace_id        BIGINT      NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    record_uid          UUID        NOT NULL,
    event_key           TEXT        NOT NULL REFERENCES events (event_key),
    created_by_user_id  BIGINT      NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT draft_records_author_fk FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES team_memberships (workspace_id, user_id),
    -- One record per team per event: the single source of truth for that team's event-day state.
    CONSTRAINT draft_records_event_unique UNIQUE (workspace_id, event_key),
    CONSTRAINT draft_records_uid_unique UNIQUE (workspace_id, record_uid),
    -- The target of draft_actions' composite key: an action can only belong to its own team's record.
    CONSTRAINT draft_records_workspace_id_unique UNIQUE (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS draft_actions (
    workspace_id        BIGINT      NOT NULL,
    record_id           BIGINT      NOT NULL,
    action_id           UUID        NOT NULL,
    seq                 INT         NOT NULL,
    action_type         TEXT        NOT NULL,
    payload             JSONB       NOT NULL DEFAULT '{}'::jsonb,
    override_reason     TEXT,
    author_user_id      BIGINT      NOT NULL,
    author_label        TEXT        NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    client_recorded_at  TIMESTAMPTZ,
    source              TEXT        NOT NULL DEFAULT 'manual',
    mode                TEXT        NOT NULL DEFAULT 'online',
    PRIMARY KEY (workspace_id, action_id),
    CONSTRAINT draft_actions_seq_unique UNIQUE (record_id, seq),
    CONSTRAINT draft_actions_record_fk FOREIGN KEY (workspace_id, record_id)
        REFERENCES draft_records (workspace_id, id) ON DELETE CASCADE,
    CONSTRAINT draft_actions_author_fk FOREIGN KEY (workspace_id, author_user_id)
        REFERENCES team_memberships (workspace_id, user_id),
    CONSTRAINT draft_actions_seq_check CHECK (seq >= 1),
    -- workspaces/draft_log.py ENTRY_TYPES (tests/test_phase11_live_draft_units.py checks they agree).
    CONSTRAINT draft_actions_type_check CHECK (action_type IN (
        'configure', 'captain', 'pick', 'decline', 'backup', 'undo', 'correct', 'close', 'reopen')),
    CONSTRAINT draft_actions_payload_check CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT draft_actions_override_check
        CHECK (override_reason IS NULL OR char_length(btrim(override_reason)) BETWEEN 1 AND 500),
    CONSTRAINT draft_actions_author_label_check CHECK (char_length(btrim(author_label)) BETWEEN 1 AND 120),
    CONSTRAINT draft_actions_source_check CHECK (source IN ('manual', 'imported')),
    CONSTRAINT draft_actions_mode_check CHECK (mode IN ('online', 'local'))
);
CREATE INDEX IF NOT EXISTS draft_actions_record_seq ON draft_actions (workspace_id, record_id, seq);

-- The history is never rewritten: a correction is a new entry that supersedes an old one (workspaces/draft_log.py).
CREATE OR REPLACE FUNCTION draft_actions_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'draft_actions is append-only: corrections are new entries'
        USING ERRCODE = 'check_violation', CONSTRAINT = 'draft_actions_append_only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_draft_actions_append_only ON draft_actions;
CREATE TRIGGER trg_draft_actions_append_only
    BEFORE UPDATE ON draft_actions
    FOR EACH ROW EXECUTE FUNCTION draft_actions_append_only();

-- P11-Q2: recording live alliance-selection actions is a configurable permission (default off for both roles).
ALTER TABLE workspace_role_permissions DROP CONSTRAINT IF EXISTS workspace_role_permissions_permission_check;
ALTER TABLE workspace_role_permissions ADD CONSTRAINT workspace_role_permissions_permission_check CHECK (permission IN (
    'team_info', 'match_predictions', 'team_analytics', 'event_analysis', 'qualification_forecast',
    'alliance_selection', 'alliance_selection_record', 'strategy_tools', 'scouting_forms', 'scouting_submit',
    'scouting_view', 'scouting_assign'));
