import { createContext, useContext } from 'react'

import type { Role, SessionInfo } from './api'

// Who is signed in, and what their role may do. AuthProvider (AuthContext.tsx) loads it from GET /auth/session when the
// app starts and replaces it with the answer of every sign-in, sign-out, registration and invitation acceptance.
//
// This decides what the interface shows. It is never what protects anything: every permission is checked again by
// the API on every request (api/session.py, workspaces/), so hiding a link is a convenience, not a control.

export const SIGNED_OUT: SessionInfo = { authenticated: false, access_policy: 'open', email_delivery_configured: false }

export interface Auth {
  /** False until the first GET /auth/session has answered. */
  ready: boolean
  session: SessionInfo
  signedIn: boolean
  role: Role | null
  can: (permission: string) => boolean
  /** Replace the session with an answer the API just gave (sign-in, registration, invitation acceptance). */
  setSession: (session: SessionInfo) => void
  refresh: () => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<Auth | null>(null)

export function makeAuth(ready: boolean, session: SessionInfo, setSession: (s: SessionInfo) => void,
  refresh: () => Promise<void>, signOut: () => Promise<void>): Auth {
  const permissions = new Set(session.permissions ?? [])
  return {
    ready, session, setSession, refresh, signOut,
    signedIn: session.authenticated,
    role: session.authenticated ? session.role ?? null : null,
    can: (permission) => session.authenticated && permissions.has(permission),
  }
}

// Without a provider (a page rendered on its own in a test), the app behaves as it always has: nobody is signed in
// and the public routes are open.
const FALLBACK = makeAuth(true, SIGNED_OUT, () => {}, async () => {}, async () => {})

export function useAuth(): Auth {
  return useContext(AuthContext) ?? FALLBACK
}
