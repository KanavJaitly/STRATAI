// A season's events (GET /explorer/seasons/{season}/events), loaded once per season per page load and shared by the
// event chooser and every heading that names the chosen event, so nobody types or reads an event key.

import { explorer } from '../api/client'
import type { EventSummary } from '../api/managerTypes'
import { useLoad } from '../components/common'
import { SUPPORTED_SEASONS } from '../lib/format'

const cache = new Map<number, Promise<EventSummary[]>>()

export function seasonEvents(season: number): Promise<EventSummary[]> {
  let found = cache.get(season)
  if (!found) {
    found = explorer.seasonEvents(season)
    found.catch(() => cache.delete(season)) // a failed load is retried next time, not remembered
    cache.set(season, found)
  }
  return found
}

/** For tests: forget every loaded season. */
export function clearSeasonEvents(): void {
  cache.clear()
}

export function useSeasonEvents(season: number | null) {
  return useLoad<EventSummary[]>(() => (season ? seasonEvents(season) : Promise.resolve([])), [season])
}

/** The season an event key belongs to (its first four digits), or null. */
export function seasonOf(eventKey: string | null | undefined): number | null {
  const year = Number(eventKey?.slice(0, 4))
  return Number.isInteger(year) && year >= 1992 ? year : null
}

/** The season the chooser opens on: the event's, else this calendar year if StratAI covers it, else the latest. */
export function defaultSeason(eventKey: string | null | undefined, now: Date = new Date()): number {
  const fromEvent = seasonOf(eventKey)
  if (fromEvent) return fromEvent
  const year = now.getFullYear()
  return (SUPPORTED_SEASONS as readonly number[]).includes(year) ? year : SUPPORTED_SEASONS[1]
}

/** "FMA" for a district, or the plain label for an event outside one. */
export function regionLabel(event: Pick<EventSummary, 'district' | 'district_name'>): string {
  return event.district ? event.district.toUpperCase() : 'No district'
}

export function eventPlace(event: EventSummary): string {
  return [event.city, event.state_prov, event.country].filter(Boolean).join(', ')
}

/** The chosen event's name, for headings; the key only until the season's list has loaded. */
export function useEventName(eventKey: string): string {
  const events = useSeasonEvents(seasonOf(eventKey))
  return events.data?.find((e) => e.event_key === eventKey)?.name ?? eventKey
}
