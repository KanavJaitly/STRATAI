-- Phase 3, Milestone 7: a lightweight anti-abuse gate for human scouting submissions.
--
-- Not full auth -- there is no scouting-user-identity system in Phase 3 (see
-- ScoutingObservation's own documented MVP limitation on scout_identifier).
-- This exists only to deter casual/accidental cross-event noise: a coordinator
-- can set one shared code per event and hand it to their scouts, so a
-- submission for the wrong event (or a stranger's guess) is rejected before it
-- is ever landed.
--
-- A row's ABSENCE means "no gate configured for this event" -- submissions are
-- allowed through without a code. Requiring a code with no way yet to set one
-- (no admin surface exists in Phase 3) would make the whole feature unusable
-- out of the box; an event only becomes gated once a coordinator explicitly
-- inserts a row for it. A row's PRESENCE means submissions must supply the
-- exact matching code.
--
-- A dedicated table, not a column on `events`: `events` is a Phase 2 canonical
-- table sourced from TBA, and this is a Phase-3-only, scouting-specific
-- concern -- the same reasoning that already kept `scouting_observations` and
-- `team_metrics` as their own tables referencing `events`/`teams` by FK rather
-- than columns bolted onto them.

CREATE TABLE IF NOT EXISTS scouting_access_codes (
    event_key    TEXT NOT NULL,
    access_code  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT scouting_access_codes_pk PRIMARY KEY (event_key),
    CONSTRAINT scouting_access_codes_event_fk FOREIGN KEY (event_key) REFERENCES events(event_key),
    CONSTRAINT scouting_access_codes_code_check CHECK (length(access_code) > 0)
);
