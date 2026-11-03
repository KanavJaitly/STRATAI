import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiRequestError } from '../api/http'
import { auth, type SessionInfo } from './api'
import { AuthContext, makeAuth, SIGNED_OUT } from './authState'

/** A 404 for GET /auth/session means the API answering has no team-account routes: it runs older code. */
function isOutdatedApi(caught: unknown): boolean {
  return caught instanceof ApiRequestError && caught.status === 404
}

/** Provides the signed-in member (authState.ts) to the whole app. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionInfo>(SIGNED_OUT)
  const [ready, setReady] = useState(false)
  const [apiOutdated, setApiOutdated] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setSession(await auth.session())
      setApiOutdated(false)
    } catch (caught) {
      setSession(SIGNED_OUT) // the API is unreachable or outdated: show the signed-out view rather than nothing
      setApiOutdated(isOutdatedApi(caught))
    } finally {
      setReady(true)
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      await auth.logout()
    } finally {
      await refresh()
    }
  }, [refresh])

  // The first load: state is set only in the promise's callbacks, and not after unmounting.
  useEffect(() => {
    let live = true
    auth.session().then(
      (found) => { if (live) { setSession(found); setReady(true) } },
      (caught: unknown) => { if (live) { setSession(SIGNED_OUT); setApiOutdated(isOutdatedApi(caught)); setReady(true) } },
    )
    return () => { live = false }
  }, [])

  const value = useMemo(() => makeAuth(ready, session, setSession, refresh, signOut, apiOutdated),
    [ready, session, refresh, signOut, apiOutdated])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
