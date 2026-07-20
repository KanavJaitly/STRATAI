DROP INDEX IF EXISTS idx_raw_source_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_source_dedup ON raw_source_payloads (source, source_object_type, source_object_id, payload_checksum);
CREATE INDEX IF NOT EXISTS idx_raw_source_current ON raw_source_payloads (source, source_object_type, source_object_id) WHERE is_current;
