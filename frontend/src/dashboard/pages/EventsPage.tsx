import { useMemo, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { dashboardApi } from '../../api/dashboard'
import type { EventOut } from '../../api/generated'
import { useResource } from '../../components/useResource'
import { PageHeader } from '../common'
import { Absent, ResourceView, ValidationBadge } from '../display'
import { currentSeason } from '../routing'

type SortKey = 'start_date' | 'name' | 'event_key'

function location(event: EventOut): string {
  return [event.city, event.state_province, event.country].filter(Boolean).join(', ')
}

function dates(event: EventOut) {
  if (!event.start_date) return <Absent reason="no dates" />
  return <>{event.start_date}{event.end_date && event.end_date !== event.start_date ? ` – ${event.end_date}` : ''}</>
}

/** P8-M2 (a): every event of a season (GET /events), searchable and sortable; the season is in the URL. */
export function EventsPage() {
  const [params, setParams] = useSearchParams()
  const season = Number(params.get('season')) || currentSeason()
  const [draftSeason, setDraftSeason] = useState(String(season))
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<SortKey>('start_date')
  const events = useResource((signal) => dashboardApi.events(season, signal), `events:${season}`)

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const list = (events.data?.events ?? []).filter((e) => !needle
      || [e.event_key, e.name ?? '', location(e)].some((field) => field.toLowerCase().includes(needle)))
    return [...list].sort((a, b) => String(a[sort] ?? '').localeCompare(String(b[sort] ?? '')) || a.event_key.localeCompare(b.event_key))
  }, [events.data, search, sort])

  const chooseSeason = (event: FormEvent) => {
    event.preventDefault()
    const value = Number(draftSeason)
    if (Number.isInteger(value) && value >= 1992) setParams({ season: String(value) })
  }

  return (
    <>
      <PageHeader title="Events" subtitle="Choose an event to see its teams, matches, predicted rankings and playoff contenders." />
      <section className="card" aria-labelledby="events-heading">
        <div className="card-head">
          <h2 id="events-heading">{season} season</h2>
          <form className="inline-form" onSubmit={chooseSeason} aria-label="Choose season">
            <label className="inline">Season
              <input type="number" min={1992} value={draftSeason} onChange={(e) => setDraftSeason(e.target.value)} />
            </label>
            <button type="submit" className="secondary">Show</button>
          </form>
        </div>
        <ResourceView resource={events} what="events">
          {(data) => (
            <>
              <div className="toolbar">
                <label className="inline">Search
                  <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="name, key or place" />
                </label>
                <label className="inline">Sort by
                  <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                    <option value="start_date">Start date</option>
                    <option value="name">Name</option>
                    <option value="event_key">Event key</option>
                  </select>
                </label>
                <ValidationBadge validation={data.validation} compact />
              </div>
              {data.events.length === 0
                ? <p className="empty">StratAI has no events for {season}. Choose another season.</p>
                : shown.length === 0
                  ? <p className="empty">No event matches “{search}”.</p>
                  : (
                    <div className="table-scroll">
                      <table className="grid">
                        <caption className="visually-hidden">Events in {season}, {shown.length} shown</caption>
                        <thead><tr><th scope="col">Event</th><th scope="col">Key</th><th scope="col">Dates</th><th scope="col">Location</th></tr></thead>
                        <tbody>
                          {shown.map((e) => (
                            <tr key={e.event_key}>
                              <th scope="row"><Link to={`/events/${encodeURIComponent(e.event_key)}`}>{e.name ?? e.event_key}</Link></th>
                              <td><code>{e.event_key}</code></td>
                              <td>{dates(e)}</td>
                              <td>{location(e) || <Absent reason="no location" />}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
              <p className="small muted">{shown.length} of {data.events.length} events.</p>
            </>
          )}
        </ResourceView>
      </section>
    </>
  )
}
