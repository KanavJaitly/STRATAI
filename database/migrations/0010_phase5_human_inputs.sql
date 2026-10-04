-- Phase 5 (P5-M8 / P5-M9 / DM1): storage for the human inputs entered through the STRATAI web app.
--
-- Every table is append-only in content.
-- - A row's payload is never updated. An edit inserts a new version; only status and review metadata move
--   forward.
-- - Nothing here is computed or inferred. These rows hold what people uploaded, entered, coded or reviewed, with
--   who and when.
-- - Uploading a PDF validates nothing: a structured spec becomes authoritative only through human review.

-- An official game manual: the original PDF is kept on disk (write-once, named by its sha256). This row is its
-- provenance. A different file for the same season is a new row; the same bytes again are the same row.
CREATE TABLE IF NOT EXISTS game_manuals (
    id              BIGSERIAL PRIMARY KEY,
    season          INT         NOT NULL,
    game_name       TEXT        NOT NULL,
    filename        TEXT        NOT NULL,
    media_type      TEXT        NOT NULL,
    byte_size       BIGINT      NOT NULL,
    content_sha256  TEXT        NOT NULL,
    storage_path    TEXT        NOT NULL,
    uploaded_by     TEXT        NOT NULL,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT game_manuals_season_check CHECK (season >= 1992),
    CONSTRAINT game_manuals_media_type_check CHECK (media_type = 'application/pdf'),
    CONSTRAINT game_manuals_size_check CHECK (byte_size > 0),
    CONSTRAINT game_manuals_sha_check CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT game_manuals_season_content_unique UNIQUE (season, content_sha256)
);

-- A structured game specification (data.game_spec.GameSpec), entered by a person from the manual.
-- - Drafts may be incomplete.
-- - A version becomes authoritative only when a named reviewer approves it.
-- - Approving a version supersedes the season's earlier approved one.
-- - entry_started_at is when the season's first draft was created: DM1's 5-day clock.
CREATE TABLE IF NOT EXISTS game_spec_versions (
    id                BIGSERIAL PRIMARY KEY,
    season            INT         NOT NULL,
    version           INT         NOT NULL,
    spec_json         JSONB       NOT NULL,
    complete          BOOLEAN     NOT NULL,
    validation_errors JSONB       NOT NULL DEFAULT '[]'::jsonb,
    spec_sha256       TEXT,
    manual_id         BIGINT      REFERENCES game_manuals(id),
    based_on_id       BIGINT      REFERENCES game_spec_versions(id),
    status            TEXT        NOT NULL,
    created_by        TEXT        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entry_started_at  TIMESTAMPTZ NOT NULL,
    submitted_at      TIMESTAMPTZ,
    reviewed_by       TEXT,
    reviewed_at       TIMESTAMPTZ,
    review_note       TEXT,
    CONSTRAINT game_spec_versions_status_check
        CHECK (status IN ('draft', 'awaiting_review', 'approved', 'superseded')),
    CONSTRAINT game_spec_versions_review_check
        CHECK (status NOT IN ('approved', 'superseded') OR (complete AND reviewed_by IS NOT NULL)),
    CONSTRAINT game_spec_versions_unique UNIQUE (season, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS game_spec_versions_one_approved_per_season
    ON game_spec_versions (season) WHERE status = 'approved';

-- P5-M9 team capability profiles (ml.gameanalysis.capability.CapabilityIntake). Each submission is landed
-- raw-first in raw_source_payloads (source 'capability_intake') before validation. An edit is a new version, and
-- the previous version is superseded.
CREATE TABLE IF NOT EXISTS capability_profiles (
    id              BIGSERIAL PRIMARY KEY,
    profile_key     TEXT        NOT NULL,
    version         INT         NOT NULL,
    payload         JSONB       NOT NULL,
    raw_payload_id  BIGINT      REFERENCES raw_source_payloads(id) ON DELETE SET NULL,
    based_on_id     BIGINT      REFERENCES capability_profiles(id),
    status          TEXT        NOT NULL,
    created_by      TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT capability_profiles_status_check CHECK (status IN ('active', 'archived', 'superseded')),
    CONSTRAINT capability_profiles_unique UNIQUE (profile_key, version)
);

-- DM1's other human artifacts:
-- - codebook (data.design_reference.Codebook);
-- - independent codings and the consensus-meeting coding (Coding);
-- - the action-type -> function map (ml.gameanalysis.rules_p5d13.ActionFunctionMap);
-- - the feasibility rubric (ml.gameanalysis.capability.Rubric);
-- - the mentor review.
-- 'established' is a named person's act, never the system's.
CREATE TABLE IF NOT EXISTS human_review_artifacts (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT        NOT NULL,
    season          INT         NOT NULL,
    author          TEXT        NOT NULL,
    version         INT         NOT NULL,
    payload         JSONB       NOT NULL,
    payload_sha256  TEXT        NOT NULL,
    status          TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    established_by  TEXT,
    established_at  TIMESTAMPTZ,
    note            TEXT,
    CONSTRAINT human_review_artifacts_kind_check CHECK (kind IN
        ('codebook', 'coding', 'consensus_coding', 'action_function_map', 'rubric', 'mentor_review')),
    CONSTRAINT human_review_artifacts_status_check CHECK (status IN ('submitted', 'established', 'superseded')),
    CONSTRAINT human_review_artifacts_established_check CHECK (status <> 'established' OR established_by IS NOT NULL),
    CONSTRAINT human_review_artifacts_unique UNIQUE (kind, season, author, version)
);
