import { Link, useParams } from 'react-router-dom'

import { dashboardApi } from '../../api/dashboard'
import type { EventMatchesResponse, ScoutingView, TeamMetricsResponse, TeamStrengthView, Validation } from '../../api/generated'
import { useResource } from '../../components/useResource'
import { AsOfControl } from '../asOf'
import { BarChart, type ChartPoint } from '../charts'
import { AllianceTeams, PageHeader } from '../common'
import { Absent, EpaSourceNote, MeasureValue, ResourceView, ValidationBadge, When } from '../display'
import { useAsOf } from '../asOfParams'
import { ResultCell } from '../common'
import { formatNumber } from '../labels'
import { matchLabel, matchPath, seasonOf } from '../routing'

export function TeamPage() {
  const params = useParams()
  const eventKey = params.eventKey ?? ''
  const team = Number(params.team)
  const [asOf] = useAsOf()
  const valid = Number.isInteger(team) && team > 0
  const strength = useResource((s) => dashboardApi.teamStrength(team, eventKey, asOf, s), `strength:${team}:${eventKey}:${asOf}`, valid)
  const metrics = useResource((s) => dashboardApi.teamMetrics(team, eventKey, s), `metrics:${team}:${eventKey}`, valid)
  const matches = useResource((s) => dashboardApi.eventMatches(eventKey, asOf, s), `matches:${eventKey}:${asOf}`, valid)
  const season = seasonOf(eventKey)

  if (!valid) return <PageHeader title="Team not found" subtitle={`“${params.team}” is not a team number.`} />
  return (
    <>
      <PageHeader title={`Team ${team}`}
        crumbs={[{ to: season ? `/?season=${season}` : '/', label: season ? `${season} events` : 'Events' },
          { to: `/events/${encodeURIComponent(eventKey)}`, label: eventKey }]}
        subtitle={<>At <Link to={`/events/${encodeURIComponent(eventKey)}`}><code>{eventKey}</code></Link></>} />
      <AsOfControl defaultNote="Default: now. The strength view and match history use only data available before the moment." />
      <ResourceView resource={strength} what="strength view">
        {(data) => <><StrengthView view={data.strength} /><EpaSourceNote epa={data.epa} /></>}
      </ResourceView>
      <ResourceView resource={matches} what="match history">
        {(data) => <HistoryView data={data} team={team} />}
      </ResourceView>
      <ResourceView resource={metrics} what="stored metrics">
        {(data) => <StoredMetricsView data={data} />}
      </ResourceView>
    </>
  )
}

function ScoutingRow({ label, view }: { label: string; view: ScoutingView }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td><MeasureValue measure={view.score} digits={2} /></td>
      <td><MeasureValue measure={view.agreement} digits={2} /></td>
      <td><ValidationBadge validation={{ status: view.validation_status }} compact /></td>
    </tr>
  )
}

/** The P5-M3 strength view of one team at one moment (also used by the pre-match report). */
export function StrengthView({ view, compact = false, level = 2 }: { view: TeamStrengthView; compact?: boolean;
  /** The heading level of the view's title; its parts are one level below (the report nests it under an h2). */
  level?: 2 | 3 }) {
  const epa = view.epa
  const s = view.scoring
  const Title = `h${level}` as 'h2' | 'h3'
  const Part = `h${level + 1}` as 'h3' | 'h4'
  const epaParts = [epa.total, epa.auto, epa.teleop, epa.endgame]
  // When every EPA part is absent for one reason, the reason is stated once instead of in each cell.
  const sharedEpaReason = epaParts.every((m) => m.value === null && m.absent_reason === epa.total.absent_reason)
    && !epa.withheld_reason ? epa.total.absent_reason : null
  const source = [epa.epa_value_source, epa.source_event_key && `from ${epa.source_event_key}`, epa.epa_source_state]
    .filter(Boolean).join(' · ')
  const autoPoints: ChartPoint[] = view.auto_points.season_by_event.map((e) => ({
    label: e.event_key, value: e.average_auto_points.value, note: e.average_auto_points.absent_reason,
  }))
  return (
    <section className="card" aria-labelledby={`strength-${view.team_number}`}>
      <div className="card-head">
        <Title id={`strength-${view.team_number}`}>{compact ? `Team ${view.team_number}` : 'Strength'}</Title>
        <span className="small muted">as of <When value={view.as_of} /></span>
      </div>
      <Part>EPA</Part>
      <p className="small">Label: <ValidationBadge validation={{ status: epa.validation_status ?? 'descriptive' }} compact /></p>
      {epa.withheld_reason && <p className="small">EPA withheld: <Absent reason={epa.withheld_reason} /></p>}
      {sharedEpaReason && <p className="small">No EPA parts: <Absent reason={sharedEpaReason} /></p>}
      <dl className="facts">
        <dt>Total</dt><dd><MeasureValue measure={epa.total} hideReason={!!sharedEpaReason || !!epa.withheld_reason} /></dd>
        <dt>Auto</dt><dd><MeasureValue measure={epa.auto} hideReason={!!sharedEpaReason || !!epa.withheld_reason} /></dd>
        <dt>Teleop</dt><dd><MeasureValue measure={epa.teleop} hideReason={!!sharedEpaReason || !!epa.withheld_reason} /></dd>
        <dt>Endgame</dt><dd><MeasureValue measure={epa.endgame} hideReason={!!sharedEpaReason || !!epa.withheld_reason} /></dd>
        <dt>Source</dt><dd className="small">{source || <Absent />}</dd>
      </dl>
      <p className="small muted">EPA components are each team's expected point contribution by phase, from its most recent completed prior event.</p>
      <Part>Scoring at this event</Part>
      <p className="small">Label: <ValidationBadge validation={{ status: s.validation_status ?? 'descriptive' }} compact /></p>
      <dl className="facts">
        <dt>Average score</dt><dd><MeasureValue measure={s.average_score} /></dd>
        <dt>Score SD</dt><dd><MeasureValue measure={s.score_stddev} /></dd>
        <dt>Consistency</dt><dd><MeasureValue measure={s.consistency_rating} /></dd>
        <dt>Reliability (INTERIM)</dt><dd><MeasureValue measure={s.reliability_score} /></dd>
        <dt>Good / average / bad days</dt><dd>
          <MeasureValue measure={s.good_day_count} digits={0} /> / <MeasureValue measure={s.average_day_count} digits={0} /> / <MeasureValue measure={s.bad_day_count} digits={0} /></dd>
        <dt>Matches considered</dt><dd>{s.matches_considered}</dd>
        <dt>Auto points (this event)</dt><dd><MeasureValue measure={view.auto_points.this_event} /></dd>
      </dl>
      <p className="small muted">Scores are the alliance's score in each match the team played. Reliability is an INTERIM
        placeholder (an attendance ratio, not a robot-failure measure).</p>
      <Part>Defense and feeding</Part>
      <div className="table-scroll">
        <table className="grid compact">
          <caption className="visually-hidden">Defense and feeding ratings for team {view.team_number}</caption>
          <thead><tr><th scope="col">Measure</th><th scope="col">Score (0–5)</th><th scope="col">Scout agreement</th><th scope="col">Status</th></tr></thead>
          <tbody>
            <ScoutingRow label="Defense" view={view.defense} />
            <ScoutingRow label="Feeding" view={view.feeding} />
          </tbody>
        </table>
      </div>
      <p className="small muted">Measured only from scouting observations, never inferred from scoring.</p>
      {!compact && autoPoints.length > 0 && (
        <BarChart title="Average auto points by event this season" unit="points" points={autoPoints} />
      )}
    </section>
  )
}

function HistoryView({ data, team }: { data: EventMatchesResponse; team: number }) {
  const mine = data.matches.filter((m) => m.red_team_numbers.includes(team) || m.blue_team_numbers.includes(team))
  const points: ChartPoint[] = mine.map((m) => {
    const red = m.red_team_numbers.includes(team)
    return {
      label: matchLabel(m),
      value: m.result ? (red ? m.result.score_red : m.result.score_blue) : null,
      note: m.result_withheld_reason?.replaceAll('_', ' '),
      tone: red ? 'red' : 'blue',
    }
  })
  const played = mine.filter((m) => m.result)
  const ownColour = (m: typeof mine[number]) => (m.red_team_numbers.includes(team) ? 'red' : 'blue')
  const wins = played.filter((m) => m.result?.winning_alliance === ownColour(m)).length
  const ties = played.filter((m) => m.result?.winning_alliance === 'tie').length
  const losses = played.filter((m) => m.result?.winning_alliance === (ownColour(m) === 'red' ? 'blue' : 'red')).length
  const noWinner = played.length - wins - ties - losses // a result without a recorded winner is not a loss
  return (
    <section className="card" aria-labelledby="history-heading">
      <div className="card-head">
        <h2 id="history-heading">Performance history at this event</h2>
        <ValidationBadge validation={data.validation} compact />
      </div>
      {mine.length === 0 ? <p className="empty">No matches for this team at this moment.</p> : (
        <>
          <p>{played.length} played: {wins} won, {ties} tied, {losses} lost
            {noWinner > 0 && <span className="muted"> · {noWinner} without a recorded winner</span>}
            {mine.length > played.length && <span className="muted"> · {mine.length - played.length} without a result at this moment</span>}.</p>
          <BarChart title="Alliance score in each match" unit="points" points={points} digits={0} />
          <div className="table-scroll">
            <table className="grid compact">
              <caption className="visually-hidden">Team {team}'s matches</caption>
              <thead><tr><th scope="col">Match</th><th scope="col">Scheduled</th><th scope="col">Alliances</th><th scope="col">Result</th></tr></thead>
              <tbody>
                {mine.map((m) => (
                  <tr key={m.match_key}>
                    <th scope="row"><Link to={matchPath(m.match_key)}>{matchLabel(m)}</Link></th>
                    <td><When value={m.scheduled_time} /></td>
                    <td><AllianceTeams teams={m.red_team_numbers} eventKey={data.event_key} tone="red" />{' '}
                      <AllianceTeams teams={m.blue_team_numbers} eventKey={data.event_key} tone="blue" /></td>
                    <td><ResultCell match={m} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

function v(value: number | null | undefined, digits = 1) {
  return value === null || value === undefined ? <Absent /> : formatNumber(value, digits)
}

function StoredLabel({ validation }: { validation: Validation }) {
  return <ValidationBadge validation={validation} />
}

function StoredMetricsView({ data }: { data: TeamMetricsResponse }) {
  const s = data.scoring
  const df = data.defense_feeding
  return (
    <section className="card" aria-labelledby="metrics-heading">
      <div className="card-head">
        <h2 id="metrics-heading">Stored metrics (Phase 3)</h2>
        <span className="small muted">computed <When value={data.computed_at} /></span>
      </div>
      <p className="small muted">The latest computed snapshot for the whole event, including matches after any moment chosen above.</p>
      <h3>Scoring</h3>
      <StoredLabel validation={data.validation.scoring} />
      <dl className="facts">
        <dt>Matches used / scheduled</dt><dd>{s.matches_used} / {s.matches_scheduled}</dd>
        <dt>Average score</dt><dd>{v(s.average_score)}</dd>
        <dt>Score SD</dt><dd>{v(s.score_stddev)}</dd>
        <dt>Consistency</dt><dd>{v(s.consistency_rating)}</dd>
        <dt>Reliability (INTERIM)</dt><dd>{v(s.reliability_score)}</dd>
        <dt>Good / average / bad days</dt><dd>{v(s.good_day_count, 0)} / {v(s.average_day_count, 0)} / {v(s.bad_day_count, 0)}</dd>
      </dl>
      <h3>Defense</h3>
      <StoredLabel validation={data.validation.defense} />
      <dl className="facts">
        <dt>Score</dt><dd>{df.defense_insufficient_data ? <Absent reason="insufficient data" /> : v(df.defense_score, 2)}</dd>
        <dt>Observations</dt><dd>{df.defense_observation_count}</dd>
        <dt>Agreement</dt><dd>{v(df.defense_agreement, 2)}</dd>
      </dl>
      <h3>Feeding</h3>
      <StoredLabel validation={data.validation.feeding} />
      <dl className="facts">
        <dt>Score</dt><dd>{df.feeding_insufficient_data ? <Absent reason="insufficient data" /> : v(df.feeding_score, 2)}</dd>
        <dt>Observations</dt><dd>{df.feeding_observation_count}</dd>
        <dt>Agreement</dt><dd>{v(df.feeding_agreement, 2)}</dd>
      </dl>
    </section>
  )
}
