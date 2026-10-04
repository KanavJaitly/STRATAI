import { useCallback, useEffect, useState } from 'react'

/** Loads data and reloads on demand. Errors are kept to show, never swallowed. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]): {
  data: T | null
  error: unknown
  loading: boolean
  reload: () => Promise<void>
} {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const run = useCallback(load, deps)
  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setData(await run())
      setError(null)
    } catch (caught) {
      setError(caught)
    } finally {
      setLoading(false)
    }
  }, [run])
  useEffect(() => {
    void reload()
  }, [reload])
  return { data, error, loading, reload }
}

/** Runs a write, keeping its error or result message for display. */
export function useAction(): {
  busy: boolean
  error: unknown
  message: string | null
  run: (action: () => Promise<unknown>, success?: string) => Promise<boolean>
  clear: () => void
} {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [message, setMessage] = useState<string | null>(null)
  const run = useCallback(async (action: () => Promise<unknown>, success?: string) => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await action()
      setMessage(success ?? null)
      return true
    } catch (caught) {
      setError(caught)
      return false
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, error, message, run, clear: () => { setError(null); setMessage(null) } }
}
