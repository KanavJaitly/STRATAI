-- Milestone 7: canonical schema, re-keyed to team_number.
--
-- 0001 created the canonical tables keyed on team_key TEXT (e.g. "frc1114").
-- The Milestone 6 staging layer deliberately discards that source-specific key
-- and works in plain team_number ints (StagingTeam.team_number,
-- StagingMatch.red_teams/blue_teams: list[int]). Keeping team_key as the
-- canonical identity would force every load to re-synthesize an identifier the
-- pipeline intentionally dropped, so the canonical team identity is moved to
-- team_number here to match the staging output that feeds it.
--
-- events and matches are already keyed on event_key / match_key (both TEXT,
-- matching staging exactly) and are left untouched. Only team identity moves,
-- which touches teams (PK), match_teams (team FK) and team_event_stats (team FK).
--
-- These three tables have never been populated (no repository/loader existed
-- before Milestone 7 and the serving layer is empty), so a clean drop-and-
-- recreate loses no historical data. Drop dependents before teams.

DROP TABLE IF EXISTS team_event_stats;
DROP TABLE IF EXISTS match_teams;
DROP TABLE IF EXISTS teams;

CREATE TABLE IF NOT EXISTS teams (
    team_number    INT PRIMARY KEY,
    name           TEXT,
    city           TEXT,
    state_province TEXT,
    country        TEXT,
    rookie_year    INT,
    last_updated   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS match_teams (
    id               BIGSERIAL PRIMARY KEY,
    match_key        TEXT NOT NULL,
    team_number      INT  NOT NULL,
    alliance_color   TEXT NOT NULL,
    station_position INT,
    last_updated     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT match_teams_match_fk    FOREIGN KEY (match_key)   REFERENCES matches(match_key),
    CONSTRAINT match_teams_team_fk     FOREIGN KEY (team_number) REFERENCES teams(team_number),
    CONSTRAINT match_teams_color_check CHECK (alliance_color IN ('red', 'blue'))
);

CREATE TABLE IF NOT EXISTS team_event_stats (
    team_number    INT  NOT NULL,
    event_key      TEXT NOT NULL,
    season         INT  NOT NULL,
    epa_total      NUMERIC,
    epa_auto       NUMERIC,
    epa_teleop     NUMERIC,
    epa_endgame    NUMERIC,
    wins           INT,
    losses         INT,
    ties           INT,
    matches_played INT,
    last_updated   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT team_event_stats_pk       PRIMARY KEY (team_number, event_key),
    CONSTRAINT team_event_stats_team_fk  FOREIGN KEY (team_number) REFERENCES teams(team_number),
    CONSTRAINT team_event_stats_event_fk FOREIGN KEY (event_key)   REFERENCES events(event_key)
);

-- 0002_add_indexes.sql's team_key-based indexes vanished with the dropped
-- columns and will not re-run (that migration is already recorded as applied),
-- so recreate the ones that still apply under the new keying. team_number and
-- (team_number, event_key) are already covered by their primary keys.
CREATE UNIQUE INDEX IF NOT EXISTS idx_match_teams_unique        ON match_teams (match_key, team_number);
CREATE INDEX        IF NOT EXISTS idx_match_teams_team_number    ON match_teams (team_number);
CREATE INDEX        IF NOT EXISTS idx_team_event_stats_event_key ON team_event_stats (event_key);
