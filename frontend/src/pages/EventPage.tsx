import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { explorer, seasonOfEvent } from '../api/client'
import type { AnalysisBody, EventMatch, EventTeam } from '../api/managerTypes'
import { LoadState, Section, useLoad } from '../components/common'
import { DataTable, RawJson, Unavailable, ValidationBadge } from '../components/seasonUi'
import { formatValue, preEventAsOf } from '../lib/format'
import { useSession } from '../state/session'

type Tab = 'teams' | 'matches' | 'analysis' | 'forecast' | 'ranking'

/**
 * Time-sensitive analyses answer "as of" a moment. A past event defaults to before it began (preEventAsOf), so the
 * view uses only evidence available then; "now" would use evidence from after the event.
 */
function AsOf({ value, onChange, applied, preEvent }: { value: string; onChange: (v: string) => void; applied: string;
  preEvent: string }) {
  return (
    <>
      <label className="inline small">As of (optional, e.g. 2026-03-04T12:00:00-05:00; empty means now)
        <input value={value} onChange={(e) => onChange(e.target.value)} aria-label="As of" placeholder="now" style={{ width: '17rem' }} />
      </label>
      {preEvent && applied === preEvent && <p className="small muted" data-testid="pre-event">Shown as of before the event
        began, using only evidence available then.</p>}
      {preEvent && !applied && <p className="notice notice-warn small" data-testid="as-of-now">Shown as of now: this
        past event is analysed with evidence from after it ended, so it is not a historical test.</p>}
    </>
  )
}

function AnalysisTab({ eventKey, preEvent }: { eventKey: string; preEvent: string }) {
  const [asOf, setAsOf] = useState(preEvent)
  const [applied, setApplied] = useState(preEvent)
  const { data, error, loading } = useLoad<AnalysisBody>(() => explorer.eventAnalysis(eventKey, applied || undefined), [eventKey, applied])
  const ordering = (data?.ordering ?? {}) as { model?: string; validation_status?: string; evidence?: string;
    teams?: Record<string, unknown>[] }
  return (
    <div>
      <div className="form-row"><AsOf value={asOf} onChange={setAsOf} applied={applied} preEvent={preEvent} />
        <button type="button" className="secondary" onClick={() => setApplied(asOf.trim())}>Apply</button></div>
      {error ? <Unavailable error={error} /> : <LoadState loading={loading} error={null} />}
      {data && (
        <>
          <p><ValidationBadge status={ordering.validation_status} /> <span className="small">{ordering.evidence}</span></p>
          <p className="small muted">Ordering model: {ordering.model ?? '—'} · as of {String(data.as_of)}</p>
          <DataTable rows={ordering.teams ?? []} columns={['rank', 'team_number', 'score', 'epa_value_source', 'epa_source_state', 'epa_source_event_key']} />
          <RawJson value={data} />
        </>
      )}
    </div>
  )
}

function ForecastTab({ eventKey, preEvent }: { eventKey: string; preEvent: string }) {
  const [asOf, setAsOf] = useState(preEvent)
  const [applied, setApplied] = useState(preEvent)
  const { data, error, loading } = useLoad<AnalysisBody>(() => explorer.qualificationForecast(eventKey, applied || undefined), [eventKey, applied])
  const teams = (data?.teams ?? []) as Record<string, unknown>[]
  const matches = (data?.matches ?? []) as Record<string, unknown>[]
  return (
    <div>
      <div className="form-row"><AsOf value={asOf} onChange={setAsOf} applied={applied} preEvent={preEvent} />
        <button type="button" className="secondary" onClick={() => setApplied(asOf.trim())}>Apply</button></div>
      {error ? <Unavailable error={error} /> : <LoadState loading={loading} error={null} />}
      {data && (
        <>
          {data.low_confidence === true && <div className="notice notice-warn">Low confidence: early in the season (Statbotics week {String(data.statbotics_week)}).</div>}
          <p className="small">{String(data.record_evidence ?? '')}</p>
          <p className="small">{String(data.range_evidence ?? '')}</p>
          <h4>Teams</h4>
          <DataTable rows={teams} columns={['team_number', 'qualification_matches', 'expected_wins', 'range80_low', 'range80_high', 'record_validation_status', 'record_not_validated_reason']}
            render={{ record_validation_status: (r) => <ValidationBadge status={r.record_validation_status} /> }} />
          <h4>Matches</h4>
          <DataTable rows={matches} columns={['match_key', 'red_team_numbers', 'blue_team_numbers', 'red_win_probability', 'unvalidated_red_win_probability', 'validation_status', 'not_validated_reason']}
            render={{ validation_status: (r) => <ValidationBadge status={r.validation_status} /> }} />
          <RawJson value={data} />
        </>
      )}
    </div>
  )
}

function RankingTab({ eventKey }: { eventKey: string }) {
  const { data, error, loading } = useLoad<AnalysisBody>(() => explorer.eventRanking(eventKey), [eventKey])
  return (
    <div>
      <p className="notice notice-warn small" data-testid="ranking-now">The ranking prediction is always as of now (the
        endpoint takes no "as of"). For a past event it uses evidence from after the event, so it is not a historical test.</p>
      {error ? <Unavailable error={error} /> : <LoadState loading={loading} error={null} />}
      {data && (
        <>
          <p><ValidationBadge status={data.validation_status} /> <span className="small">{String(data.evidence ?? '')}</span></p>
          <DataTable rows={(data.rankings ?? []) as Record<string, unknown>[]} columns={['rank', 'team_number', 'predicted_rating', 'epa_value_source', 'epa_source_event_key', 'epa_withheld_reason']} />
          <RawJson value={data} />
        </>
      )}
    </div>
  )
}

function MatchProbability({ matchKey }: { matchKey: string }) {
  const [state, setState] = useState<{ data?: AnalysisBody; error?: unknown; loading?: boolean }>({})
  const load = async () => {
    setState({ loading: true })
    try { setState({ data: await explorer.matchWinProbability(matchKey) }) } catch (error) { setState({ error }) }
  }
  if (state.loading) return <span className="muted small">…</span>
  if (state.error) return <Unavailable error={state.error} />
  if (state.data) {
    const d = state.data
    const validated = d.red_win_probability !== null && d.red_win_probability !== undefined
    return (
      <span className="small" data-testid={`wp-${matchKey}`}>
        <ValidationBadge status={d.validation_status} /> red{' '}
        {validated ? formatValue(d.red_win_probability) : <>{formatValue(d.unvalidated_red_win_probability)} <em>(not a validated probability)</em></>}
        {d.not_validated_reason ? <span className="muted"> · {String(d.not_validated_reason)}</span> : null}
      </span>
    )
  }
  return <button type="button" className="link" onClick={() => void load()}>Win probability</button>
}

function MatchesTab({ matches }: { matches: EventMatch[] }) {
  const [level, setLevel] = useState<'all' | 'qualification' | 'playoff'>('all')
  const shown = matches.filter((m) => level === 'all' || (level === 'qualification') === (m.competition_level === 'qualification'))
  return (
    <div>
      <div className="form-row">
        <label>Level
          <select value={level} onChange={(e) => setLevel(e.target.value as typeof level)} aria-label="Match level">
            <option value="all">All</option><option value="qualification">Qualification</option><option value="playoff">Playoffs</option>
          </select>
        </label>
      </div>
      {shown.length === 0 ? <p className="muted">No matches.</p> : (
        <div className="table-scroll">
          <table className="grid compact" data-testid="matches-table">
            <thead><tr><th>Match</th><th>Red</th><th>Blue</th><th>Score</th><th>Winner</th><th>Win probability (pre-match)</th></tr></thead>
            <tbody>
              {shown.map((m) => (
                <tr key={m.match_key}>
                  <td><code className="small">{m.match_key.split('_')[1] ?? m.match_key}</code></td>
                  <td>{(m.red ?? []).join(', ') || '—'}</td><td>{(m.blue ?? []).join(', ') || '—'}</td>
                  <td>{m.score_red ?? '—'} – {m.score_blue ?? '—'}</td>
                  <td>{m.winning_alliance || (m.score_red !== null ? 'tie' : '—')}</td>
                  <td><MatchProbability matchKey={m.match_key} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function TeamsTab({ teams, epaSource }: { teams: EventTeam[]; epaSource: string }) {
  return (
    <div>
      <p className="muted small">EPA: {epaSource}. Blank EPA means none was synced for this team at this event.</p>
      <DataTable rows={teams as unknown as Record<string, unknown>[]}
        columns={['team_number', 'name', 'epa_total', 'epa_auto', 'epa_teleop', 'epa_endgame', 'wins', 'losses', 'ties', 'metrics_computed']}
        render={{ team_number: (r) => <Link to={`/explorer/teams/${r.team_number}`}>{String(r.team_number)}</Link>,
          metrics_computed: (r) => (r.metrics_computed ? 'yes' : <span className="muted">no</span>) }} />
    </div>
  )
}

export function EventPage() {
  const { eventKey = '' } = useParams()
  const { season, setSeason } = useSession()
  const [tab, setTab] = useState<Tab>('teams')
  const teams = useLoad(() => explorer.eventTeams(eventKey), [eventKey])
  const matches = useLoad(() => explorer.eventMatches(eventKey), [eventKey])
  const eventSeason = seasonOfEvent(eventKey)
  const event = teams.data?.event
  const preEvent = event ? preEventAsOf(event.start_date, event.end_date) : ''
  const tabs: [Tab, string][] = [['teams', 'Teams'], ['matches', 'Matches'], ['analysis', 'Event analysis'],
    ['forecast', 'Qualification forecast'], ['ranking', 'Ranking prediction']]
  return (
    <>
      <p className="small"><Link to="/explorer">← {season} events</Link></p>
      {eventSeason !== null && eventSeason !== season && (
        <div className="notice notice-warn mismatch" role="alert" data-testid="season-mismatch">
          This event is from {eventSeason}, but {season} is selected. Its data and rules are {eventSeason}'s.{' '}
          <button type="button" className="link" onClick={() => setSeason(eventSeason)}>Switch to {eventSeason}</button>
        </div>
      )}
      <Section title={event ? `${event.name} (${eventKey})` : eventKey}>
        {teams.error ? <Unavailable error={teams.error} /> : <LoadState loading={teams.loading} error={null} />}
        {event && <p className="small muted">{event.start_date ?? '—'} – {event.end_date ?? '—'} · {[event.city, event.state_prov, event.country].filter(Boolean).join(', ')}</p>}
        <div className="tabs" role="tablist">
          {tabs.map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>{label}</button>
          ))}
        </div>
        {tab === 'teams' && teams.data && (teams.data.teams.length
          ? <TeamsTab teams={teams.data.teams} epaSource={teams.data.epa_source} /> : <p className="muted">No teams are recorded for this event.</p>)}
        {tab === 'matches' && (matches.error ? <Unavailable error={matches.error} />
          : matches.data ? <MatchesTab matches={matches.data.matches} /> : <LoadState loading={matches.loading} error={null} />)}
        {(tab === 'analysis' || tab === 'forecast') && !event && <LoadState loading={teams.loading} error={null} />}
        {tab === 'analysis' && event && <AnalysisTab key={preEvent} eventKey={eventKey} preEvent={preEvent} />}
        {tab === 'forecast' && event && <ForecastTab key={preEvent} eventKey={eventKey} preEvent={preEvent} />}
        {tab === 'ranking' && <RankingTab eventKey={eventKey} />}
      </Section>
    </>
  )
}

