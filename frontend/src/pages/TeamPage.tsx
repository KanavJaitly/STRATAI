import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { explorer } from '../api/client'
import type { AnalysisBody, TeamSeason } from '../api/managerTypes'
import { LoadState, Section, useLoad } from '../components/common'
import { Measured, RawJson, Unavailable, ValidationBadge } from '../components/seasonUi'
import { formatValue, preEventAsOf } from '../lib/format'
import { useSession } from '../state/session'

type Loaded = { data?: AnalysisBody; error?: unknown; loading?: boolean }

function useOnDemand(): [Loaded, (load: () => Promise<AnalysisBody>) => Promise<void>] {
  const [state, setState] = useState<Loaded>({})
  const run = async (load: () => Promise<AnalysisBody>) => {
    setState({ loading: true })
    try { setState({ data: await load() }) } catch (error) { setState({ error }) }
  }
  return [state, run]
}

function Strength({ body }: { body: AnalysisBody }) {
  const s = body.strength as Record<string, Record<string, unknown>>
  const rows: [string, unknown, unknown][] = [
    ['EPA total', s.epa?.total, s.epa?.validation_status], ['EPA auto', s.epa?.auto, s.epa?.validation_status],
    ['EPA teleop', s.epa?.teleop, s.epa?.validation_status], ['EPA endgame', s.epa?.endgame, s.epa?.validation_status],
    ['Average score', s.scoring?.average_score, s.scoring?.validation_status],
    ['Consistency', s.scoring?.consistency_rating, s.scoring?.validation_status],
    ['Reliability', s.scoring?.reliability_score, s.scoring?.validation_status],
    ['Auto points (this event)', s.auto_points?.this_event, s.auto_points?.validation_status],
    ['Defense', s.defense?.score, s.defense?.validation_status], ['Feeding', s.feeding?.score, s.feeding?.validation_status],
  ]
  return (
    <div>
      <p className="small muted">As of {String((s as unknown as { as_of?: string }).as_of ?? '')} · EPA source event {String(s.epa?.source_event_key ?? '—')}</p>
      <table className="grid compact" data-testid="strength-table">
        <thead><tr><th>Measure</th><th>Value</th><th>Status</th></tr></thead>
        <tbody>{rows.map(([label, value, status]) => (
          <tr key={label}><td>{label}</td><td><Measured value={value} /></td><td><ValidationBadge status={status} /></td></tr>
        ))}</tbody>
      </table>
      <RawJson value={body} />
    </div>
  )
}

function EventRow({ team, event }: { team: number; event: TeamSeason['events'][number] }) {
  const [metrics, loadMetrics] = useOnDemand()
  const [strength, loadStrength] = useOnDemand()
  // A past event's strength is shown as of before it began (only evidence available then); see preEventAsOf.
  const asOf = preEventAsOf(event.start_date)
  return (
    <>
      <tr>
        <td><Link to={`/explorer/events/${event.event_key}`}>{event.name}</Link> <code className="small">{event.event_key}</code></td>
        <td>{formatValue(event.epa_total)}</td>
        <td>{event.wins ?? '—'}-{event.losses ?? '—'}-{event.ties ?? '—'}</td>
        <td>
          <button type="button" className="link" onClick={() => void loadStrength(() => explorer.teamStrength(team, event.event_key, asOf || undefined))}>Strength</button>
          <button type="button" className="link" onClick={() => void loadMetrics(() => explorer.teamMetrics(team, event.event_key))}>Metrics</button>
        </td>
      </tr>
      {(strength.loading || strength.data || strength.error) && (
        <tr><td colSpan={4}>
          {strength.loading && <span className="muted">Loading strength…</span>}
          {strength.error ? <Unavailable error={strength.error} /> : null}
          {asOf && (strength.data || strength.error) ? <p className="small muted" data-testid="pre-event">As of before the event began ({asOf}).</p> : null}
          {strength.data && <Strength body={strength.data} />}
        </td></tr>
      )}
      {(metrics.loading || metrics.data || metrics.error) && (
        <tr><td colSpan={4}>
          {metrics.loading && <span className="muted">Loading metrics…</span>}
          {metrics.error ? <Unavailable error={metrics.error} /> : null}
          {metrics.data && <RawJson value={metrics.data} label="Team metrics" />}
        </td></tr>
      )}
    </>
  )
}

export function TeamPage() {
  const { teamNumber = '' } = useParams()
  const team = Number(teamNumber)
  const { season } = useSession()
  const { data, error, loading } = useLoad<TeamSeason>(() => explorer.teamSeason(team, season), [team, season])
  return (
    <>
      <p className="small"><Link to="/explorer">← {season} events</Link></p>
      <Section title={data ? `Team ${team}${data.team.name ? ` — ${data.team.name}` : ''}` : `Team ${team}`}>
        {error ? <Unavailable error={error} /> : <LoadState loading={loading} error={null} />}
        {data && (
          <>
            <p className="small muted">{[data.team.city, data.team.state_province, data.team.country].filter(Boolean).join(', ')}
              {data.team.rookie_year ? ` · rookie year ${data.team.rookie_year}` : ''}</p>
            <h3>{season} events</h3>
            {data.events.length === 0 ? <p className="muted" data-testid="no-team-events">Team {team} played no synced {season} events.</p> : (
              <div className="table-scroll">
                <table className="grid compact">
                  <thead><tr><th>Event</th><th>EPA (synced)</th><th>W-L-T</th><th>Details</th></tr></thead>
                  <tbody>{data.events.map((e) => <EventRow key={e.event_key} team={team} event={e} />)}</tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Section>
    </>
  )
}
