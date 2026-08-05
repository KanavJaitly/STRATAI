from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, TypeVar

from data.metrics.schemas import ScoutingObservation
from data.staging.schemas import (
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
)
from database.connection import Database

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CanonicalRepository:
    """Upsert-based loader from validated staging entities into the canonical tables.

    This is the serving-layer counterpart to the landing-layer RawPayloadWriter:
    it takes the source-agnostic StagingTeam / StagingEvent / StagingMatch /
    StagingTeamEventStats produced by the staging layer, plus (Phase 3
    Milestone 7) data.metrics's ScoutingObservation, and persists them into
    the canonical teams / events / matches / match_teams / team_event_stats /
    scouting_observations tables that downstream metrics and ML consume.

    Every write is an INSERT ... ON CONFLICT DO UPDATE keyed on the table's
    natural key, so loads are idempotent: re-loading the same staging entity
    updates the existing row in place rather than creating a duplicate, and
    changed fields are reflected. Callers are responsible for foreign-key
    ordering (teams and events before matches and team_event_stats); load_all()
    enforces that ordering for the common case of loading a full batch at once.
    """

    database: Database

    # -- teams -------------------------------------------------------------

    def _upsert_team(self, cursor: Any, team: StagingTeam) -> None:
        cursor.execute(
            """
            INSERT INTO teams (
                team_number, name, city, state_province, country, rookie_year, last_updated
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (team_number) DO UPDATE SET
                name = EXCLUDED.name,
                city = EXCLUDED.city,
                state_province = EXCLUDED.state_province,
                country = EXCLUDED.country,
                rookie_year = EXCLUDED.rookie_year,
                last_updated = NOW()
            """,
            (
                team.team_number,
                team.name,
                team.city,
                team.state_province,
                team.country,
                team.rookie_year,
            ),
        )

    def load_team(self, team: StagingTeam) -> None:
        """Upsert a single team into the canonical teams table."""
        self.load_teams([team])

    def load_teams(self, teams: Iterable[StagingTeam]) -> int:
        """Upsert many teams over a single connection. Returns the number processed."""
        return self._load_batch(teams, self._upsert_team, "team", lambda t: str(t.team_number))

    # -- events ------------------------------------------------------------

    def _upsert_event(self, cursor: Any, event: StagingEvent) -> None:
        # The events table column is state_prov (0001); the staging model uses
        # state_province. event_type is a canonical-only column not carried by
        # staging, so it is intentionally left untouched on update and NULL on
        # insert rather than being clobbered.
        cursor.execute(
            """
            INSERT INTO events (
                event_key, season, name, event_code,
                start_date, end_date, city, state_prov, country, last_updated
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (event_key) DO UPDATE SET
                season = EXCLUDED.season,
                name = EXCLUDED.name,
                event_code = EXCLUDED.event_code,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                city = EXCLUDED.city,
                state_prov = EXCLUDED.state_prov,
                country = EXCLUDED.country,
                last_updated = NOW()
            """,
            (
                event.event_key,
                event.season,
                event.name,
                event.event_code,
                event.start_date,
                event.end_date,
                event.city,
                event.state_province,
                event.country,
            ),
        )

    def load_event(self, event: StagingEvent) -> None:
        """Upsert a single event into the canonical events table."""
        self.load_events([event])

    def load_events(self, events: Iterable[StagingEvent]) -> int:
        """Upsert many events over a single connection. Returns the number processed."""
        return self._load_batch(events, self._upsert_event, "event", lambda e: e.event_key)

    # -- matches (+ match_teams junction) ----------------------------------

    def _upsert_match(self, cursor: Any, match: StagingMatch) -> None:
        cursor.execute(
            """
            INSERT INTO matches (
                match_key, event_key, season, competition_level,
                set_number, match_number, scheduled_time,
                score_red, score_blue, winning_alliance, last_updated
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (match_key) DO UPDATE SET
                event_key = EXCLUDED.event_key,
                season = EXCLUDED.season,
                competition_level = EXCLUDED.competition_level,
                set_number = EXCLUDED.set_number,
                match_number = EXCLUDED.match_number,
                scheduled_time = EXCLUDED.scheduled_time,
                score_red = EXCLUDED.score_red,
                score_blue = EXCLUDED.score_blue,
                winning_alliance = EXCLUDED.winning_alliance,
                last_updated = NOW()
            """,
            (
                match.match_key,
                match.event_key,
                match.season,
                match.competition_level,
                match.set_number,
                match.match_number,
                match.scheduled_time,
                match.red_score,
                match.blue_score,
                match.winning_alliance,
            ),
        )
        self._sync_match_teams(cursor, match)

    def _sync_match_teams(self, cursor: Any, match: StagingMatch) -> None:
        """Reconcile the match_teams junction to exactly the match's current roster.

        Each rostered team is upserted with its alliance colour and 1-based
        station position; any junction row for this match whose team is no
        longer on the roster (e.g. a corrected schedule) is pruned, so repeated
        loads converge on the roster rather than accumulating stale rows.
        """
        roster_team_numbers: list[int] = []
        for alliance_color, team_numbers in (("red", match.red_teams), ("blue", match.blue_teams)):
            for station_position, team_number in enumerate(team_numbers, start=1):
                roster_team_numbers.append(team_number)
                cursor.execute(
                    """
                    INSERT INTO match_teams (
                        match_key, team_number, alliance_color, station_position, last_updated
                    ) VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (match_key, team_number) DO UPDATE SET
                        alliance_color = EXCLUDED.alliance_color,
                        station_position = EXCLUDED.station_position,
                        last_updated = NOW()
                    """,
                    (match.match_key, team_number, alliance_color, station_position),
                )

        # Prune rows for teams no longer on this match's roster. The ::int[] cast
        # keeps the empty-roster case (delete all rows for the match) well-typed.
        cursor.execute(
            "DELETE FROM match_teams WHERE match_key = %s AND NOT (team_number = ANY(%s::int[]))",
            (match.match_key, roster_team_numbers),
        )

    def load_match(self, match: StagingMatch) -> None:
        """Upsert a single match and reconcile its match_teams junction rows."""
        self.load_matches([match])

    def load_matches(self, matches: Iterable[StagingMatch]) -> int:
        """Upsert many matches (and their junction rows) over a single connection.

        Requires the referenced events and teams to already be loaded; a match
        referencing an unknown event_key or team_number raises on the offending
        record (foreign-key violation) after committing any earlier records.
        """
        return self._load_batch(matches, self._upsert_match, "match", lambda m: m.match_key)

    # -- team_event_stats --------------------------------------------------

    def _upsert_team_event_stats(self, cursor: Any, stats: StagingTeamEventStats) -> None:
        cursor.execute(
            """
            INSERT INTO team_event_stats (
                team_number, event_key, season,
                epa_total, epa_auto, epa_teleop, epa_endgame,
                wins, losses, ties, matches_played, last_updated
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (team_number, event_key) DO UPDATE SET
                season = EXCLUDED.season,
                epa_total = EXCLUDED.epa_total,
                epa_auto = EXCLUDED.epa_auto,
                epa_teleop = EXCLUDED.epa_teleop,
                epa_endgame = EXCLUDED.epa_endgame,
                wins = EXCLUDED.wins,
                losses = EXCLUDED.losses,
                ties = EXCLUDED.ties,
                matches_played = EXCLUDED.matches_played,
                last_updated = NOW()
            """,
            (
                stats.team_number,
                stats.event_key,
                stats.season,
                stats.epa_total,
                stats.epa_auto,
                stats.epa_teleop,
                stats.epa_endgame,
                stats.wins,
                stats.losses,
                stats.ties,
                stats.matches_played,
            ),
        )

    def load_team_event_stat(self, stats: StagingTeamEventStats) -> None:
        """Upsert a single team-event-stats row into the canonical table."""
        self.load_team_event_stats([stats])

    def load_team_event_stats(self, stats: Iterable[StagingTeamEventStats]) -> int:
        """Upsert many team-event-stats rows over a single connection.

        Requires the referenced teams and events to already be loaded; a row
        referencing an unknown team_number or event_key raises on the offending
        record (foreign-key violation) after committing any earlier records.
        """
        return self._load_batch(
            stats, self._upsert_team_event_stats, "team_event_stats",
            lambda s: f"{s.team_number}_{s.event_key}",
        )

    # -- scouting_observations (Phase 3 Milestone 7) -----------------------
    #
    # No load_scouting_observations batch method: unlike the four Phase 2
    # entity types, a ScoutingObservation's row also needs the raw_payload_id
    # of the specific landed payload it came from -- a per-entity value
    # _load_batch's shared upsert(cursor, entity) signature has no room for.
    # Milestone 7's submission flow loads exactly one observation per
    # submission, so a batch variant would be speculative; add one if a
    # future caller actually needs to load many at once.

    def _upsert_scouting_observation(
        self, cursor: Any, observation: ScoutingObservation, raw_payload_id: int | None
    ) -> None:
        cursor.execute(
            """
            INSERT INTO scouting_observations (
                match_key, event_key, team_number, scout_identifier,
                defense_rating, feeding_rating, notes, source, submitted_at, raw_payload_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_key, team_number, scout_identifier, source) DO UPDATE SET
                event_key = EXCLUDED.event_key,
                defense_rating = EXCLUDED.defense_rating,
                feeding_rating = EXCLUDED.feeding_rating,
                notes = EXCLUDED.notes,
                submitted_at = EXCLUDED.submitted_at,
                raw_payload_id = EXCLUDED.raw_payload_id
            """,
            (
                observation.match_key,
                observation.event_key,
                observation.team_number,
                observation.scout_identifier,
                observation.defense_rating,
                observation.feeding_rating,
                observation.notes,
                observation.source,
                observation.submitted_at,
                raw_payload_id,
            ),
        )

    def load_scouting_observation(
        self, observation: ScoutingObservation, *, raw_payload_id: int | None = None
    ) -> None:
        """Upsert a single scouting observation into the canonical table.

        Conflict target is the same four-column natural key
        scouting_observations.idx_scouting_observations_unique enforces
        (match_key, team_number, scout_identifier, source): a corrected
        resubmission from the same scout for the same team/match updates this
        row in place rather than creating a second opinion, exactly as
        ScoutingObservation's own docstring describes. event_key is included
        in the UPDATE SET despite being part of no natural key column, purely
        for the (currently impossible, since Milestone 5 already rejects a
        match_key/event_key mismatch) case of a corrected submission somehow
        carrying a different event_key than the row already stored.
        """
        with self.database.cursor() as cursor:
            self._upsert_scouting_observation(cursor, observation, raw_payload_id)

    # -- orchestration -----------------------------------------------------

    def load_all(
        self,
        *,
        teams: Iterable[StagingTeam] = (),
        events: Iterable[StagingEvent] = (),
        matches: Iterable[StagingMatch] = (),
        team_event_stats: Iterable[StagingTeamEventStats] = (),
    ) -> dict[str, int]:
        """Load a full batch in foreign-key-safe order.

        Teams and events are loaded first (matches and team_event_stats
        reference them), then matches and team_event_stats. Returns a per-entity
        count of records processed.
        """
        return {
            "teams": self.load_teams(teams),
            "events": self.load_events(events),
            "matches": self.load_matches(matches),
            "team_event_stats": self.load_team_event_stats(team_event_stats),
        }

    # -- shared batch machinery -------------------------------------------

    def _load_batch(
        self,
        entities: Iterable[T],
        upsert: Callable[[Any, T], None],
        entity_label: str,
        key_of: Callable[[T], str],
    ) -> int:
        """Upsert every entity over one shared connection, committing each in turn.

        Mirrors RawPayloadWriter.write_many: each record is committed
        individually so a failure partway through a batch does not roll back
        records already persisted earlier in the same call. On failure this
        logs how much progress was made, then stops (records after the failure
        are never attempted) and re-raises -- whether to skip a bad record and
        continue is an ingestion-policy decision that belongs to the caller.
        """
        processed = 0
        with self.database.connection() as conn:
            for entity in entities:
                try:
                    with conn.cursor() as cursor:
                        upsert(cursor, entity)
                    conn.commit()
                    processed += 1
                except Exception:
                    logger.error(
                        "load_%s stopped after %d record(s); failed on %s",
                        entity_label, processed, key_of(entity),
                    )
                    raise
        return processed
