// Shared constants and formatting for the season views (2026-10-11).

/** The seasons STRATAI supports (Kanav, 2026-10-11): 2027 is being prepared; 2023-2026 are historical. */
export const SUPPORTED_SEASONS = [2027, 2026, 2025, 2024, 2023] as const

/** A value as returned, readably: numbers trimmed, numeric strings to 2 places, lists joined. Never invents one. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, '')
  if (typeof value === 'string' && /^-?\d+\.\d+$/.test(value)) return Number(value).toFixed(2)
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/**
 * The default "as of" for a time-sensitive view of an event: before the event when it has ended, so a historical
 * view uses only what was known then; '' (meaning now) for a current or future event. "Before" is the earliest local
 * midnight of the start date anywhere (UTC+14), so no match of the event can precede it. Without an end date an
 * event is treated as ended a week after it started.
 */
export function preEventAsOf(startDate: string | null | undefined, endDate?: string | null, today: Date = new Date()): string {
  if (!startDate || !/^\d{4}-\d{2}-\d{2}$/.test(startDate)) return ''
  const end = endDate ?? new Date(Date.parse(`${startDate}T00:00:00Z`) + 6 * 86_400_000).toISOString().slice(0, 10)
  return end < today.toISOString().slice(0, 10) ? `${startDate}T00:00:00+14:00` : ''
}
