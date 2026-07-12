CREATE TABLE IF NOT EXISTS raw_source_payloads (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    source_object_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    season INT,
    event_key TEXT,
    match_key TEXT,
    fetch_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_json JSONB NOT NULL,
    payload_checksum TEXT NOT NULL,
    schema_version TEXT,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teams (
    team_key TEXT PRIMARY KEY,
    team_number INT NOT NULL,
    team_name TEXT,
    city TEXT,
    state_prov TEXT,
    country TEXT,
    rookie_year INT,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    event_key TEXT PRIMARY KEY,
    season INT NOT NULL,
    name TEXT,
    event_code TEXT,
    event_type TEXT,
    start_date DATE,
    end_date DATE,
    city TEXT,
    state_prov TEXT,
    country TEXT,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS matches (
    match_key TEXT PRIMARY KEY,
    event_key TEXT NOT NULL,
    season INT NOT NULL,
    competition_level TEXT,
    set_number INT,
    match_number INT,
    scheduled_time TIMESTAMPTZ,
    score_red INT,
    score_blue INT,
    winning_alliance TEXT,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT matches_event_fk FOREIGN KEY (event_key) REFERENCES events(event_key)
);

CREATE TABLE IF NOT EXISTS match_teams (
    id BIGSERIAL PRIMARY KEY,
    match_key TEXT NOT NULL,
    team_key TEXT NOT NULL,
    alliance_color TEXT NOT NULL,
    station_position INT,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT match_teams_match_fk FOREIGN KEY (match_key) REFERENCES matches(match_key),
    CONSTRAINT match_teams_team_fk FOREIGN KEY (team_key) REFERENCES teams(team_key)
);

CREATE TABLE IF NOT EXISTS team_event_stats (
    id BIGSERIAL PRIMARY KEY,
    team_key TEXT NOT NULL,
    event_key TEXT NOT NULL,
    season INT NOT NULL,
    epa_total NUMERIC,
    epa_auto NUMERIC,
    epa_teleop NUMERIC,
    epa_endgame NUMERIC,
    matches_played INT,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT team_event_stats_team_fk FOREIGN KEY (team_key) REFERENCES teams(team_key),
    CONSTRAINT team_event_stats_event_fk FOREIGN KEY (event_key) REFERENCES events(event_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_source_key ON raw_source_payloads (source, source_object_type, source_object_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_match_teams_unique ON match_teams (match_key, team_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_team_event_stats_unique ON team_event_stats (team_key, event_key);
