import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { api, setWriteToken } from '../api/client'
import type { WriteAccess } from '../api/types'

// Who is acting, whether writes are allowed, and which season is open.
// - The name is recorded on every write (created_by, reviewer, author, ...). It is a label, not an identity
//   system, exactly as the API documents.
// - The write token is held in memory only, never in browser storage.
// - The name and the season are remembered per browser as a convenience.

interface Session {
  actor: string
  setActor: (name: string) => void
  token: string
  setToken: (token: string) => void
  access: WriteAccess | null
  refreshAccess: () => Promise<void>
  canWrite: boolean
  season: number
  setSeason: (season: number) => void
}

const SessionContext = createContext<Session | null>(null)

function remembered(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function remember(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // storage unavailable: the value lasts for this page only
  }
}

export function defaultSeason(now: Date = new Date()): number {
  return now.getUTCFullYear() + (now.getUTCMonth() >= 6 ? 1 : 0) // the next season is the one being prepared
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [actor, setActorState] = useState(() => remembered('stratai.actor') ?? '')
  const [token, setTokenState] = useState('')
  const [access, setAccess] = useState<WriteAccess | null>(null)
  const [season, setSeasonState] = useState(() => Number(remembered('stratai.season')) || defaultSeason())

  const refreshAccess = useCallback(async () => {
    try {
      setAccess(await api.writeAccess())
    } catch {
      setAccess(null)
    }
  }, [])

  useEffect(() => {
    void refreshAccess()
  }, [refreshAccess, token])

  const value = useMemo<Session>(() => ({
    actor,
    setActor: (name) => {
      setActorState(name)
      remember('stratai.actor', name)
    },
    token,
    setToken: (next) => {
      setWriteToken(next)
      setTokenState(next)
    },
    access,
    refreshAccess,
    canWrite: Boolean(access?.writes_enabled && access.token_accepted && actor.trim()),
    season,
    setSeason: (next) => {
      setSeasonState(next)
      remember('stratai.season', String(next))
    },
  }), [actor, token, access, refreshAccess, season])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): Session {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useSession outside SessionProvider')
  return session
}
