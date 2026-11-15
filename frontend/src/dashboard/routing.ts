// Dashboard URLs and identifiers (P8-Q9: selection lives in the URL).

export function teamPath(eventKey: string, team: number): string {
  return `/events/${encodeURIComponent(eventKey)}/teams/${team}`
}

export function matchPath(matchKey: string): string {
  return `/matches/${encodeURIComponent(matchKey)}`
}

export function reportPath(matchKey: string, asOf?: string | null): string {
  return `/report/${encodeURIComponent(matchKey)}${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''}`
}

/** The season an event key belongs to (TBA keys start with the year, e.g. 2026mrcmp). */
export function seasonOf(eventKey: string): number | null {
  const match = /^(\d{4})/.exec(eventKey)
  return match ? Number(match[1]) : null
}

/** The event a match key belongs to (e.g. 2026mrcmp_qm1 → 2026mrcmp). */
export function eventOfMatch(matchKey: string): string {
  return matchKey.split('_')[0]
}

/** A short match label: "Qual 12", "Semifinal 2-1", or the key. */
export function matchLabel(match: { match_key: string; competition_level: string | null; match_number: number | null;
  set_number?: number | null }): string {
  const level = match.competition_level
  if (level === 'qualification' && match.match_number != null) return `Qual ${match.match_number}`
  if (level && match.match_number != null) {
    const name = level.charAt(0).toUpperCase() + level.slice(1)
    return match.set_number != null ? `${name} ${match.set_number}-${match.match_number}` : `${name} ${match.match_number}`
  }
  return match.match_key
}

/** The season shown by default: the calendar year (FRC seasons run January–April). */
export function currentSeason(now: Date = new Date()): number {
  return now.getUTCFullYear()
}

/** The `from` value a team page reached from the live draft page carries, so it can offer the way back. */
export const FROM_LIVE_DRAFT = 'live-draft'

/** The live alliance-selection page for one event. */
export function liveDraftPath(eventKey: string): string {
  return `/alliance-selection/live?event=${encodeURIComponent(eventKey)}`
}

/** A team page reached from the live draft page: the return target is in the URL, never in browser storage. */
export function teamPathFromLiveDraft(eventKey: string, team: number, asOf: string | null): string {
  const query = new URLSearchParams({ from: FROM_LIVE_DRAFT, event: eventKey })
  if (asOf) query.set('as_of', asOf)
  return `${teamPath(eventKey, team)}?${query.toString()}`
}
