import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { auth, type SessionInfo } from './api'
import { AuthContext, makeAuth, SIGNED_OUT } from './authState'

/** Provides the signed-in member (authState.ts) to the whole app. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionInfo>(SIGNED_OUT)
  const [ready, setReady] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setSession(await auth.session())
    } catch {
      setSession(SIGNED_OUT) // the API is unreachable: show the signed-out view rather than nothing
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
      () => { if (live) { setSession(SIGNED_OUT); setReady(true) } },
    )
    return () => { live = false }
  }, [])

  const value = useMemo(() => makeAuth(ready, session, setSession, refresh, signOut),
    [ready, session, refresh, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
