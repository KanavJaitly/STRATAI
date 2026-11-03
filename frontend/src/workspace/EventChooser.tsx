// Choosing an event without knowing its key: pick the year, narrow by region (FMA, FIM, ... or events outside a
// district), type part of the event's name or city, then pick it from the list.

import { useId, useMemo, useState } from 'react'

import type { EventSummary } from '../api/managerTypes'
import { LoadState } from '../components/common'
import { SUPPORTED_SEASONS } from '../lib/format'
import { defaultSeason, eventPlace, regionLabel, seasonOf, useEventName, useSeasonEvents } from './events'

const ALL = ''
const NO_DISTRICT = '-'
const MAX_SHOWN = 12

function dates(event: EventSummary): string {
  if (!event.start_date) return ''
  const day = (iso: string) => new Date(`${iso}T12:00:00`)
  const format = (iso: string) => day(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  if (!event.end_date || event.end_date === event.start_date) return format(event.start_date)
  // "Mar 4–7" within one month, "Mar 30–Apr 1" across two.
  return day(event.start_date).getMonth() === day(event.end_date).getMonth()
    ? `${format(event.start_date)}–${day(event.end_date).getDate()}` : `${format(event.start_date)}–${format(event.end_date)}`
}

/** An event shown by its name (its key only until the season's list has loaded). */
export function EventName({ eventKey }: { eventKey: string }) {
  return <>{useEventName(eventKey)}</>
}

/** value: the chosen event's key ('' for none). onChange receives the newly chosen key. */
export function EventChooser({ value, onChange, legend = 'Choose the event' }: { value: string;
  onChange: (eventKey: string) => void; legend?: string }) {
  const [season, setSeason] = useState(() => defaultSeason(value))
  const [region, setRegion] = useState(ALL)
  const [query, setQuery] = useState('')
  const events = useSeasonEvents(season)
  const listId = useId()

  const regions = useMemo(() => {
    const found = new Map<string, string>()
    for (const event of events.data ?? []) if (event.district) found.set(event.district, event.district_name ?? '')
    return [...found.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [events.data])
  const hasNoDistrict = (events.data ?? []).some((e) => !e.district)

  const matches = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    return (events.data ?? []).filter((event) => {
      if (region === NO_DISTRICT ? event.district : region && event.district !== region) return false
      const text = `${event.name} ${eventPlace(event)} ${event.district ?? ''} ${event.district_name ?? ''}`.toLowerCase()
      return words.every((word) => text.includes(word))
    })
  }, [events.data, region, query])
  const chosen = (events.data ?? []).find((e) => e.event_key === value)
  // The list shows while choosing: with nothing chosen yet, or once a name, region or other year is entered.
  const browsing = !value || query.trim() !== '' || region !== ALL || seasonOf(value) !== season

  return (
    <fieldset className="event-chooser">
      <legend>{legend}</legend>
      <div className="form-row">
        <label>Year
          <select value={season} onChange={(e) => { setSeason(Number(e.target.value)); setRegion(ALL) }}>
            {[...new Set<number>([...SUPPORTED_SEASONS, season])].sort((a, b) => b - a)
              .map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>Region
          <select value={region} onChange={(e) => setRegion(e.target.value)} disabled={!events.data}>
            <option value={ALL}>All regions</option>
            {regions.map(([abbreviation, name]) => (
              <option key={abbreviation} value={abbreviation}>{abbreviation.toUpperCase()}{name ? ` — ${name}` : ''}</option>
            ))}
            {hasNoDistrict && <option value={NO_DISTRICT}>Regionals and other events (no district)</option>}
          </select>
        </label>
        <label className="event-search">Event
          <input type="search" value={query} placeholder="Type the event's name or city" aria-controls={listId}
            onChange={(e) => setQuery(e.target.value)} />
        </label>
      </div>
      {value && (
        <p className="event-chosen" role="status">
          Selected: <strong>{chosen?.name ?? value}</strong>
          {chosen && <span className="muted small"> · {regionLabel(chosen)} · {eventPlace(chosen)} {dates(chosen)}</span>}
        </p>
      )}
      <LoadState loading={events.loading} error={events.error} />
      {events.data && (events.data.length === 0 ? (
        <p className="muted">StratAI has no events for {season} yet.</p>
      ) : !browsing ? (
        <p className="muted small">To change it, choose a region or type part of another event&apos;s name.</p>
      ) : (
        <>
          <ul className="event-results" id={listId} aria-label={`Events in ${season}`}>
            {matches.slice(0, MAX_SHOWN).map((event) => (
              <li key={event.event_key}>
                <button type="button" className={event.event_key === value ? 'event-option selected' : 'event-option'}
                  aria-pressed={event.event_key === value} onClick={() => onChange(event.event_key)}>
                  <span className="event-option-name">{event.name}</span>
                  <span className="muted small">{regionLabel(event)} · {eventPlace(event)}{dates(event) && ` · ${dates(event)}`}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="muted small">
            {matches.length === 0 ? 'No event matches. Try another year, region or name.'
              : matches.length > MAX_SHOWN ? `Showing ${MAX_SHOWN} of ${matches.length} events: type more of the name, `
                + 'or choose a region, to narrow it.' : `${matches.length} event${matches.length === 1 ? '' : 's'}.`}
          </p>
        </>
      ))}
    </fieldset>
  )
}
