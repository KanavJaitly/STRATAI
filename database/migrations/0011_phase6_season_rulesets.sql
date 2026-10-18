-- Phase 6 (P6-M1): per-season alliance-selection and playoff rulesets, entered by people from the game manuals.
--
-- Content is append-only:
-- - An edit is a new version, and only status and review metadata move forward.
-- - A ruleset becomes authoritative only when a named reviewer approves it.
-- - Approving a version supersedes the season's earlier approved version.
-- - The reviewer must be a different person from the author (enforced in data/rulesets.py).
-- - Nothing here is inferred from data: every rule is cited to its manual section inside ruleset_json.

CREATE TABLE IF NOT EXISTS season_rulesets (
    id              BIGSERIAL PRIMARY KEY,
    season          INT         NOT NULL,
    version         INT         NOT NULL,
    ruleset_json    JSONB       NOT NULL,
    ruleset_sha256  TEXT        NOT NULL,
    status          TEXT        NOT NULL,
    created_by      TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submitted_at    TIMESTAMPTZ,
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMPTZ,
    review_note     TEXT,
    CONSTRAINT season_rulesets_season_check CHECK (season >= 1992),
    CONSTRAINT season_rulesets_sha_check CHECK (ruleset_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT season_rulesets_status_check CHECK (status IN ('draft', 'awaiting_review', 'approved', 'superseded')),
    CONSTRAINT season_rulesets_review_check CHECK (status NOT IN ('approved', 'superseded') OR reviewed_by IS NOT NULL),
    CONSTRAINT season_rulesets_unique UNIQUE (season, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS season_rulesets_one_approved_per_season
    ON season_rulesets (season) WHERE status = 'approved';
