-- Phase 3, Milestone 2: schema for metrics and scouting observations.
--
-- Schema only. No computation logic exists yet and nothing writes these two
-- tables -- the statistics functions, the scouting validator/normalizer, the
-- aggregation policy, and the metrics computation pipeline are all later
-- milestones. This migration exists to fix the *storage* shape now, for the
-- same reason Milestone 1 fixed the model shape before any of that logic was
-- written: getting it wrong here would force a re-key later, exactly as the
-- team_key -> team_number re-key in Milestone 7 did.
--
-- Every column below is a field of a Milestone 1 model in
-- data/metrics/schemas.py, under its own name, with two deliberate exceptions
-- marked inline (scouting_observations.id and .raw_payload_id). The CHECK
-- constraints are transcriptions of the pydantic model_validators in that
-- module -- not new policy -- so a row the models would refuse to construct
-- cannot be stored either.

-- === scouting_observations ================================================
--
-- One scout's (or ScoutRadioz's) direct assessment of one team in one match:
-- data.metrics.schemas.ScoutingObservation, one row per model instance.
--
-- This is the only irreplaceable data in the system. Every other table is
-- re-fetchable from TBA or Statbotics; a human's rating of a match played
-- three weeks ago is not. That fact drives the cascade rules below.
--
-- event_key is denormalized from match_key (it is derivable via
-- matches.event_key) because "every observation for this event" is the
-- expected dominant access pattern, feeding both the API and the future
-- aggregation step. Consistency between the two is deliberately NOT enforced
-- here: Milestone 1 assigns that to a raw-payload validation milestone,
-- mirroring how StagingMatch does not re-validate its own denormalized season.
--
-- scout_identifier is free text, not a foreign key -- there is no scouting
-- user-identity system in Phase 3. A documented MVP limitation, not an
-- oversight: nothing here prevents spoofing or duplicate scout names.

CREATE TABLE IF NOT EXISTS scouting_observations (
    -- Not a Milestone 1 field: a surrogate key, because the natural key is the
    -- four-column UNIQUE below. Same pattern as match_teams and
    -- canonical_lineage.
    id               BIGSERIAL PRIMARY KEY,

    match_key        TEXT        NOT NULL,
    event_key        TEXT        NOT NULL,
    team_number      INT         NOT NULL,
    scout_identifier TEXT        NOT NULL,
    defense_rating   INT,
    feeding_rating   INT,
    notes            TEXT,
    source           TEXT        NOT NULL,
    submitted_at     TIMESTAMPTZ NOT NULL,

    -- Not a Milestone 1 field: lineage back to the landed payload an
    -- observation arrived in, required by this milestone. Nullable because an
    -- observation submitted directly to StratAI never passes through the
    -- landing layer at all.
    raw_payload_id   BIGINT,

    -- No ON DELETE action on the three canonical references, matching
    -- match_teams and team_event_stats. Deleting a match that has been scouted
    -- should fail loudly and require the observations to be dealt with
    -- deliberately, precisely because they cannot be re-collected.
    CONSTRAINT scouting_observations_match_fk FOREIGN KEY (match_key)
        REFERENCES matches(match_key),
    CONSTRAINT scouting_observations_team_fk FOREIGN KEY (team_number)
        REFERENCES teams(team_number),
    CONSTRAINT scouting_observations_event_fk FOREIGN KEY (event_key)
        REFERENCES events(event_key),

    -- SET NULL, not CASCADE. 0007 sets two precedents: a row that is purely a
    -- subordinate audit record cascades (canonical_lineage.raw_payload_id),
    -- while a provenance pointer hanging off a row that must outlive it is set
    -- null (canonical_lineage.pipeline_run_id, "a deleted run must not erase
    -- the payload->row provenance"). An observation is emphatically the second
    -- case: purging a raw payload -- which integration teardown does -- must
    -- never take irreplaceable scouting data with it. Losing the provenance
    -- pointer is recoverable; losing the observation is not.
    CONSTRAINT scouting_observations_raw_payload_fk FOREIGN KEY (raw_payload_id)
        REFERENCES raw_source_payloads(id) ON DELETE SET NULL,

    -- MIN_RATING/MAX_RATING. Hardcoded because SQL cannot import the
    -- constants; changing the rating scale requires a migration.
    CONSTRAINT scouting_observations_defense_rating_check
        CHECK (defense_rating IS NULL OR defense_rating BETWEEN 0 AND 5),
    CONSTRAINT scouting_observations_feeding_rating_check
        CHECK (feeding_rating IS NULL OR feeding_rating BETWEEN 0 AND 5),

    -- ScoutingObservation._require_at_least_one_rating: an observation
    -- asserting neither a defense nor a feeding rating is meaningless.
    CONSTRAINT scouting_observations_rating_present_check
        CHECK (defense_rating IS NOT NULL OR feeding_rating IS NOT NULL),

    -- Field(min_length=1) on the two identifiers that have no FK to enforce
    -- their existence. match_key/event_key need no equivalent -- an empty
    -- string cannot satisfy their foreign keys.
    CONSTRAINT scouting_observations_identity_check
        CHECK (length(scout_identifier) > 0 AND length(source) > 0)
);

-- One scout may rate a team in a match once per source. A second submission is
-- an update to that row, not a new opinion; two different scouts, or the same
-- name arriving from a different source, are distinct observations.
CREATE UNIQUE INDEX IF NOT EXISTS idx_scouting_observations_unique
    ON scouting_observations (match_key, team_number, scout_identifier, source);

-- The unique index already serves match_key lookups on its leading column.
CREATE INDEX IF NOT EXISTS idx_scouting_observations_event_key
    ON scouting_observations (event_key);
CREATE INDEX IF NOT EXISTS idx_scouting_observations_team_number
    ON scouting_observations (team_number);
CREATE INDEX IF NOT EXISTS idx_scouting_observations_raw_payload_id
    ON scouting_observations (raw_payload_id);


-- === team_metrics =========================================================
--
-- The complete served metrics object for one team at one event:
-- data.metrics.schemas.TeamMetrics.
--
-- TeamMetrics composes two sub-models, ScoringProfile (pure statistics over
-- match scores) and DefenseFeedingProfile (aggregated scouting observations).
-- They are FLATTENED into columns here rather than stored nested or split into
-- side tables. The nesting is fixed-arity -- exactly one of each, never
-- optional, never a list -- and the two sub-models share no field names, so
-- every column carries its Milestone 1 name unprefixed and reassembly is
-- mechanical. JSONB would have made the column types and the constraints below
-- unenforceable; separate tables would have turned one upsert into two writes
-- for no gain. The served object stays composed; only its storage is flat,
-- exactly as StagingMatch flattens TBA's alliance nesting into
-- score_red/score_blue.
--
-- A current-state snapshot, one row per (team_number, event_key), upserted in
-- place -- not an append-only history, consistent with team_event_stats.
-- Recomputing during a live event overwrites the previous value; "what did we
-- know as of match 5" is answered by replaying the pipeline against a
-- historical cut of the already-versioned raw_source_payloads, not by storing
-- every intermediate snapshot.
--
-- computed_at is the roadmap's "last_computed_at" under its model name. Since
-- the row is upserted in place, the timestamp of the computation that produced
-- it IS the last-computed time; using the Milestone 1 name keeps every column
-- traceable to a model field.

CREATE TABLE IF NOT EXISTS team_metrics (
    -- TeamMetrics identity
    team_number               INT         NOT NULL,
    event_key                 TEXT        NOT NULL,
    season                    INT         NOT NULL,
    computed_at               TIMESTAMPTZ NOT NULL,

    -- TeamMetrics.scoring -- ScoringProfile, flattened.
    -- DOUBLE PRECISION rather than team_event_stats' NUMERIC: Milestone 1
    -- declares these as float, and psycopg3 returns NUMERIC as Decimal, which
    -- these values would have to be converted out of on every read. Nothing
    -- recomputes from team_event_stats yet, which is why its choice has not
    -- bitten anyone; this table is read back and reassembled into a model.
    matches_scheduled         INT         NOT NULL,
    matches_used              INT         NOT NULL,
    average_score             DOUBLE PRECISION,
    score_stddev              DOUBLE PRECISION,
    consistency_rating        DOUBLE PRECISION,
    reliability_score         DOUBLE PRECISION,
    good_day_count            INT,
    average_day_count         INT,
    bad_day_count             INT,

    -- TeamMetrics.defense_feeding -- DefenseFeedingProfile, flattened.
    defense_score             DOUBLE PRECISION,
    defense_observation_count INT         NOT NULL,
    defense_agreement         DOUBLE PRECISION,
    defense_insufficient_data BOOLEAN     NOT NULL,
    feeding_score             DOUBLE PRECISION,
    feeding_observation_count INT         NOT NULL,
    feeding_agreement         DOUBLE PRECISION,
    feeding_insufficient_data BOOLEAN     NOT NULL,
    -- list[str]: which sources contributed at least one counted observation.
    -- An array rather than a junction table because these are free-text source
    -- labels with nothing to reference -- the integrity argument that kept
    -- match_teams a junction does not apply.
    contributing_sources      TEXT[]      NOT NULL DEFAULT '{}',

    CONSTRAINT team_metrics_pk PRIMARY KEY (team_number, event_key),
    CONSTRAINT team_metrics_team_fk  FOREIGN KEY (team_number) REFERENCES teams(team_number),
    CONSTRAINT team_metrics_event_fk FOREIGN KEY (event_key)   REFERENCES events(event_key),

    -- --- Field-level ranges: the Field(ge=/le=) bounds, verbatim ---------
    --
    -- average_score/score_stddev are bounded below but deliberately NOT above:
    -- a future game could score higher than anything seen so far, and a hard
    -- ceiling would eventually reject real data -- the same reasoning that
    -- rejected an invented EPA tolerance in Milestone 9.
    CONSTRAINT team_metrics_scoring_range_check CHECK (
        matches_scheduled >= 0 AND matches_used >= 0
        AND (average_score      IS NULL OR average_score      >= 0)
        AND (score_stddev       IS NULL OR score_stddev       >= 0)
        AND (consistency_rating IS NULL OR consistency_rating BETWEEN 0 AND 100)
        AND (reliability_score  IS NULL OR reliability_score  BETWEEN 0 AND 100)
        AND (good_day_count     IS NULL OR good_day_count     >= 0)
        AND (average_day_count  IS NULL OR average_day_count  >= 0)
        AND (bad_day_count      IS NULL OR bad_day_count      >= 0)
    ),
    CONSTRAINT team_metrics_defense_feeding_range_check CHECK (
        defense_observation_count >= 0 AND feeding_observation_count >= 0
        AND (defense_score     IS NULL OR defense_score     BETWEEN 0 AND 5)
        AND (feeding_score     IS NULL OR feeding_score     BETWEEN 0 AND 5)
        AND (defense_agreement IS NULL OR defense_agreement BETWEEN 0 AND 1)
        AND (feeding_agreement IS NULL OR feeding_agreement BETWEEN 0 AND 1)
    ),

    -- --- ScoringProfile._check_invariants, clause by clause ---------------
    --
    -- ScoringProfile carries no insufficient-data flag: matches_used IS the
    -- signal, and NULL always means "not computed" for a reason determined by
    -- it -- 0 means there is no data at all, 1 means variance is undefined for
    -- a single sample.
    CONSTRAINT team_metrics_matches_used_check
        CHECK (matches_used <= matches_scheduled),
    CONSTRAINT team_metrics_no_data_check CHECK (
        matches_used > 0 OR (
            average_score IS NULL AND score_stddev IS NULL
            AND consistency_rating IS NULL AND reliability_score IS NULL
            AND good_day_count IS NULL AND average_day_count IS NULL
            AND bad_day_count IS NULL
        )
    ),
    -- MIN_MATCHES_FOR_STDDEV = 2. average_score survives a single match (the
    -- average of one value is itself); nothing derived from variance does.
    CONSTRAINT team_metrics_variance_check CHECK (
        matches_used >= 2 OR (
            score_stddev IS NULL AND consistency_rating IS NULL
            AND reliability_score IS NULL AND good_day_count IS NULL
            AND average_day_count IS NULL AND bad_day_count IS NULL
        )
    ),
    CONSTRAINT team_metrics_day_counts_check CHECK (
        (good_day_count IS NULL AND average_day_count IS NULL AND bad_day_count IS NULL)
        OR (good_day_count IS NOT NULL AND average_day_count IS NOT NULL
            AND bad_day_count IS NOT NULL
            AND good_day_count + average_day_count + bad_day_count = matches_used)
    ),

    -- --- DefenseFeedingProfile._check_invariants, clause by clause --------
    --
    -- These two are load-bearing for CLAUDE.md's "defense/feeding scores =
    -- directly measured, NOT inferred from point output". A score exists if
    -- and only if its insufficient_data flag is False, and zero observations
    -- force the flag -- so a confident-looking score built on no observations
    -- is not merely rejected by the model, it is unstorable. Rating 0 stays a
    -- real, meaningful value throughout ("confirmed none observed"); missing
    -- data is never represented by a 0 standing in for "unknown".
    CONSTRAINT team_metrics_defense_sufficiency_check CHECK (
        (defense_score IS NOT NULL) = (NOT defense_insufficient_data)
        AND (defense_observation_count > 0 OR defense_insufficient_data)
    ),
    CONSTRAINT team_metrics_feeding_sufficiency_check CHECK (
        (feeding_score IS NOT NULL) = (NOT feeding_insufficient_data)
        AND (feeding_observation_count > 0 OR feeding_insufficient_data)
    ),
    -- Empty if and only if both tracks are insufficient: if either produced a
    -- real score, at least one source must be named as having produced it.
    CONSTRAINT team_metrics_contributing_sources_check CHECK (
        (defense_insufficient_data AND feeding_insufficient_data)
            = (cardinality(contributing_sources) = 0)
    )
);

-- team_number and (team_number, event_key) are already covered by the primary
-- key, so only event_key needs its own index -- the same reasoning 0005
-- records for team_event_stats, whose keying this table mirrors exactly.
CREATE INDEX IF NOT EXISTS idx_team_metrics_event_key ON team_metrics (event_key);
