import { useSearchParams } from 'react-router-dom'

/** "2026-04-14T09:30" (the browser's local time) → "2026-04-14T13:30:00.000Z"; null when empty or invalid. */
export function localInputToIso(local: string): string | null {
  if (!local) return null
  const date = new Date(local)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

/** ISO instant → the value a datetime-local input shows, in the browser's local time. */
export function isoToLocalInput(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** The `as_of` URL parameter (null = the server's default) and a setter that keeps every other parameter. */
export function useAsOf(): [string | null, (iso: string | null) => void] {
  const [params, setParams] = useSearchParams()
  const asOf = params.get('as_of')
  const set = (iso: string | null) => {
    const next = new URLSearchParams(params)
    if (iso) next.set('as_of', iso)
    else next.delete('as_of')
    setParams(next)
  }
  return [asOf, set]
}
