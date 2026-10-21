import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, explorer } from '../api/client'
import type { EventSummary, Readiness } from '../api/managerTypes'
import { LoadState, Section, useLoad } from '../components/common'
import { CoverageTiles, FeatureBadge } from '../components/seasonUi'
import { useSession } from '../state/session'

function FeatureList({ readiness }: { readiness: Readiness }) {
  const shown = readiness.features.filter((f) => f.route === '/explorer' || f.key === 'score_components')
  return (
    <ul className="small" data-testid="feature-availability">
      {shown.map((f) => (
        <li key={f.key}>
          <FeatureBadge feature={f} />{' '}
          {f.name}{!f.available && f.reasons.length > 0 && <span className="muted"> — {f.reasons.join('; ')}</span>}
          {f.available && f.limitations?.length > 0 && <span className="muted"> — {f.limitations.join('; ')}</span>}
        </li>
      ))}
    </ul>
  )
}

export function ExplorerPage() {
  const { season } = useSession()
  const readiness = useLoad<Readiness>(() => api.readiness(season), [season])
  const events = useLoad<EventSummary[]>(() => explorer.seasonEvents(season), [season])
  const [query, setQuery] = useState('')
  const [playedOnly, setPlayedOnly] = useState(true)
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (events.data ?? []).filter((e) => (!playedOnly || e.matches_played > 0)
      && (!q || [e.event_key, e.name, e.city, e.state_prov, e.country].some((v) => (v ?? '').toLowerCase().includes(q))))
  }, [events.data, query, playedOnly])

  return (
    <>
      <Section title={`Historical season — ${season}`}>
        <p className="lede">Real {season} data as synced from The Blue Alliance (matches) and Statbotics (EPA). Nothing
          is filled in: where data is missing, the views say so. Each analysis keeps its own validation status.</p>
        <LoadState loading={readiness.loading} error={readiness.error} />
        {readiness.data && (
          <>
            <CoverageTiles coverage={readiness.data.coverage} season={season} />
            <h3>What works for {season}</h3>
            <FeatureList readiness={readiness.data} />
          </>
        )}
      </Section>
      <Section title="Events">
        <div className="form-row">
          <label>Search<input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search events"
            placeholder="name, key or place" /></label>
          <label className="inline"><input type="checkbox" checked={playedOnly} aria-label="Only events with results"
            onChange={(e) => setPlayedOnly(e.target.checked)} /> Only events with results</label>
        </div>
        <LoadState loading={events.loading} error={events.error} />
        {events.data && events.data.length === 0 && <p className="muted" data-testid="no-events">No {season} events are synced.</p>}
        {events.data && events.data.length > 0 && (
          <>
            <p className="muted small">{filtered.length} of {events.data.length} events</p>
            <div className="table-scroll">
              <table className="grid compact" data-testid="events-table">
                <thead><tr><th>Event</th><th>Dates</th><th>Place</th><th>Teams</th><th>Matches played</th></tr></thead>
                <tbody>
                  {filtered.map((e) => (
                    <tr key={e.event_key}>
                      <td><Link to={`/explorer/events/${e.event_key}`}>{e.name}</Link> <code className="small">{e.event_key}</code></td>
                      <td className="small">{e.start_date ?? '—'}{e.end_date && e.end_date !== e.start_date ? ` – ${e.end_date}` : ''}</td>
                      <td className="small">{[e.city, e.state_prov, e.country].filter(Boolean).join(', ') || '—'}</td>
                      <td>{e.teams}</td><td>{e.matches_played} / {e.matches}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>
    </>
  )
}
