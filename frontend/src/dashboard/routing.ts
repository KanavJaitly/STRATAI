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
