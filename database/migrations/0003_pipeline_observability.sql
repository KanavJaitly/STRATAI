CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    source TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    records_processed INT,
    error_message TEXT,
    CONSTRAINT pipeline_runs_status_check CHECK (status IN ('running', 'succeeded', 'failed'))
);

CREATE TABLE IF NOT EXISTS source_watermarks (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    object_type TEXT NOT NULL,
    scope_key TEXT NOT NULL DEFAULT '',
    watermark_value TEXT,
    last_synced_at TIMESTAMPTZ,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id BIGSERIAL PRIMARY KEY,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id),
    source TEXT,
    object_type TEXT,
    object_id TEXT,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    description TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    CONSTRAINT data_quality_issues_severity_check CHECK (severity IN ('warning', 'error', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline_name ON pipeline_runs (pipeline_name);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_watermarks_unique ON source_watermarks (source, object_type, scope_key);
CREATE INDEX IF NOT EXISTS idx_data_quality_issues_pipeline_run_id ON data_quality_issues (pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_data_quality_issues_resolved ON data_quality_issues (resolved);
