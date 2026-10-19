import { useCallback, useEffect, useEffectEvent, useState } from 'react'

import { isAbortError } from '../api/http'

export interface Resource<T> {
  data: T | null
  error: unknown
  loading: boolean
  /** Fetch again with the same parameters (a user-initiated retry; nothing retries automatically). */
  reload: () => void
}

interface Settled<T> {
  data: T | null
  error: unknown
  key: string
  token: string
}

/**
 * Loads one resource for a view (P8-Q10).
 * - Every load gets its own AbortController. A new key (changed parameters), a reload or an unmount aborts the
 *   previous request.
 * - A response that arrives after a newer load started is ignored, so a slow old answer never overwrites a newer
 *   one.
 * - `loading` is derived, not stored: a load is pending until a response for its own token has settled. While a
 *   reload of the same key is pending, the previous data stays visible; a new key starts empty.
 * - When `enabled` is false, nothing is fetched and the state is empty and not loading.
 * - Errors are kept for display, never swallowed. Cancellations are not errors.
 */
export function useResource<T>(load: (signal: AbortSignal) => Promise<T>, key: string, enabled = true): Resource<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null)
  const [generation, setGeneration] = useState(0)
  const token = `${key}#${generation}`
  const fetchNow = useEffectEvent((signal: AbortSignal) => load(signal))

  useEffect(() => {
    if (!enabled) return undefined
    const controller = new AbortController()
    let current = true
    fetchNow(controller.signal).then(
      (data) => { if (current) setSettled({ data, error: null, key, token }) },
      (error: unknown) => {
        if (current && !isAbortError(error)) setSettled({ data: null, error, key, token })
      },
    )
    return () => {
      current = false
      controller.abort()
    }
  }, [token, key, enabled])

  const reload = useCallback(() => setGeneration((g) => g + 1), [])
  if (!enabled) return { data: null, error: null, loading: false, reload }
  if (settled?.token === token) return { data: settled.data, error: settled.error, loading: false, reload }
  return { data: settled?.key === key && !settled.error ? settled.data : null, error: null, loading: true, reload }
}
