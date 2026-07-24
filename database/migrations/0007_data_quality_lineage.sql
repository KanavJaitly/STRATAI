-- Milestone 9: data quality issue references and canonical lineage.
--
-- Part 1: data_quality_issues gains the two references it was missing.
--
-- 0003 gave the table a logical identity for the offender (source,
-- object_type, object_id) but no way to point at the specific raw payload
-- *version* that was bad -- and since the landing layer keeps every version of
-- an object, "team frc1114 was invalid" is not enough to find the payload that
-- caused it. raw_payload_id closes that gap. `field` carries the precise field
-- name the staging layer's ValidationIssue already knows, which would
-- otherwise only survive as prose inside description.
--
-- Both FKs cascade on delete, and 0003's existing pipeline_run_id FK is
-- redefined to cascade too. A quality issue is a subordinate record of the run
-- and payload it describes: if either is deleted the issue is meaningless, and
-- without the cascade any cleanup of pipeline_runs or raw_source_payloads
-- (integration test teardown does exactly this) would fail on a foreign-key
-- violation. Constraint redefinition only; no data is touched.

ALTER TABLE data_quality_issues ADD COLUMN IF NOT EXISTS raw_payload_id BIGINT;
ALTER TABLE data_quality_issues ADD COLUMN IF NOT EXISTS field TEXT;

ALTER TABLE data_quality_issues DROP CONSTRAINT IF EXISTS data_quality_issues_raw_payload_fk;
ALTER TABLE data_quality_issues ADD CONSTRAINT data_quality_issues_raw_payload_fk
    FOREIGN KEY (raw_payload_id) REFERENCES raw_source_payloads(id) ON DELETE CASCADE;

ALTER TABLE data_quality_issues DROP CONSTRAINT IF EXISTS data_quality_issues_pipeline_run_id_fkey;
ALTER TABLE data_quality_issues DROP CONSTRAINT IF EXISTS data_quality_issues_pipeline_run_fk;
ALTER TABLE data_quality_issues ADD CONSTRAINT data_quality_issues_pipeline_run_fk
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_data_quality_issues_raw_payload_id ON data_quality_issues (raw_payload_id);
CREATE INDEX IF NOT EXISTS idx_data_quality_issues_object ON data_quality_issues (source, object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_data_quality_issues_severity ON data_quality_issues (severity);

-- Part 2: canonical_lineage -- audit trail from a canonical row back to the
-- raw payload it was built from.
--
-- Deliberately a separate table rather than a source_payload_id column on each
-- canonical table. The canonical schema (0001/0005) and the Milestone 7
-- repository stay completely untouched, and lineage becomes an append-only
-- history: every payload version an entity was ever built from, and which run
-- promoted each one. A single column on the row could only ever hold the last
-- writer, recording no history and unable to represent an entity fed by more
-- than one source.
--
-- entity_type reuses the same vocabulary as raw_source_payloads.
-- source_object_type and source_watermarks.object_type ('event', 'team',
-- 'match', 'team_event'), so one word describes the same thing across the raw
-- rows, the incremental state, the quality issues, and the lineage.
-- entity_key is the canonical row's natural key rendered as text
-- (team_number, event_key, match_key, or "<team_number>_<event_key>").
-- match_teams has no entity type of its own: its rows are reconciled from a
-- match's roster, so they are traced through their parent match.
--
-- UNIQUE (entity_type, entity_key, raw_payload_id) makes recording idempotent,
-- so re-running a sync that re-promotes the same payload does not accumulate
-- duplicate lineage rows. Combined with ON CONFLICT DO NOTHING on insert, the
-- retained pipeline_run_id is the run that *first* promoted that payload, which
-- is the more useful audit fact than the most recent re-promotion.

CREATE TABLE IF NOT EXISTS canonical_lineage (
    id              BIGSERIAL PRIMARY KEY,
    entity_type     TEXT   NOT NULL,
    entity_key      TEXT   NOT NULL,
    raw_payload_id  BIGINT NOT NULL,
    pipeline_run_id BIGINT,
    source          TEXT   NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT canonical_lineage_raw_payload_fk FOREIGN KEY (raw_payload_id)
        REFERENCES raw_source_payloads(id) ON DELETE CASCADE,
    -- A deleted run must not erase the payload->row provenance, which stays
    -- true regardless of which run happened to record it.
    CONSTRAINT canonical_lineage_pipeline_run_fk FOREIGN KEY (pipeline_run_id)
        REFERENCES pipeline_runs(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_lineage_unique
    ON canonical_lineage (entity_type, entity_key, raw_payload_id);
CREATE INDEX IF NOT EXISTS idx_canonical_lineage_entity
    ON canonical_lineage (entity_type, entity_key);
CREATE INDEX IF NOT EXISTS idx_canonical_lineage_raw_payload_id
    ON canonical_lineage (raw_payload_id);
CREATE INDEX IF NOT EXISTS idx_canonical_lineage_pipeline_run_id
    ON canonical_lineage (pipeline_run_id);
