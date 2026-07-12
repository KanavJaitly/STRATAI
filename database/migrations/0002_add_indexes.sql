CREATE INDEX IF NOT EXISTS idx_teams_team_number ON teams (team_number);
CREATE INDEX IF NOT EXISTS idx_events_event_code ON events (event_code);
CREATE INDEX IF NOT EXISTS idx_matches_event_key ON matches (event_key);
CREATE INDEX IF NOT EXISTS idx_match_teams_match_key ON match_teams (match_key);
CREATE INDEX IF NOT EXISTS idx_match_teams_team_key ON match_teams (team_key);
CREATE INDEX IF NOT EXISTS idx_team_event_stats_team_key ON team_event_stats (team_key);
CREATE INDEX IF NOT EXISTS idx_team_event_stats_event_key ON team_event_stats (event_key);
