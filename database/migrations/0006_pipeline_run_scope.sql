-- Milestone 8: give pipeline_runs somewhere to record *what* a run synced.
--
-- 0003_pipeline_observability.sql created pipeline_runs with pipeline_name and
-- source but no scope column, so two runs of the same pipeline against two
-- different events were indistinguishable in the run history. The orchestrator
-- keys its incremental state on (source, object_type, scope_key) -- the same
-- scoping source_watermarks already uses -- so the run log needs the matching
-- scope_key to be reconcilable against those watermarks.
--
-- stage_counts holds the per-stage/per-entity breakdown (how many payloads
-- landed, staged, loaded, skipped) that a single records_processed INT cannot
-- express. JSONB rather than a column per stage: the stage list is expected to
-- grow (data-quality checks in Milestone 9), and this is observability data
-- read by humans, not something metrics or ML join against.
--
-- Both columns are nullable with no default and no constraint changes, so every
-- existing row and every existing query keeps working untouched; rolling this
-- back is a DROP COLUMN with no data loss beyond the new columns themselves.
-- source_watermarks needs no changes: its UNIQUE (source, object_type,
-- scope_key) index is already exactly the upsert key the orchestrator needs.

ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS scope_key TEXT;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS stage_counts JSONB;

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_scope_key ON pipeline_runs (scope_key);
