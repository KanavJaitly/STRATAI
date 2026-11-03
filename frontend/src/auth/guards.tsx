import type { ReactNode } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'

import { useAuth } from './authState'

/** Shows children to a signed-in member; sends anyone else to sign in, and back here afterwards. */
export function RequireSignedIn({ children }: { children: ReactNode }) {
  const { ready, signedIn } = useAuth()
  const { pathname, search } = useLocation()
  if (!ready) return <p className="muted" role="status">Checking your sign-in…</p>
  if (!signedIn) return <Navigate to={`/auth/login?next=${encodeURIComponent(pathname + search)}`} replace />
  return <>{children}</>
}

/** Shows children only to a member whose role holds permission. (The API refuses the same requests regardless.) */
export function RequirePermission({ permission, children }: { permission: string; children: ReactNode }) {
  const { can } = useAuth()
  return (
    <RequireSignedIn>
      {can(permission) ? children : (
        <div className="notice notice-warn" role="alert">
          <p><strong>Your role does not include this page.</strong> Ask one of your team&apos;s administrators if
            you need it.</p>
          <p><Link to="/home">Go to your dashboard</Link></p>
        </div>
      )}
    </RequireSignedIn>
  )
}
