import type { ReactNode } from 'react'
import { Link, Navigate, useLocation, type LinkProps } from 'react-router-dom'

import { useAuth } from './authState'
import { pageAllowed } from './roles'

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
          <p><strong>Your role does not include this page.</strong> Ask one of the team&apos;s administrators if you
            need it.</p>
          <p><Link to="/home">Go to your dashboard</Link></p>
        </div>
      )}
    </RequireSignedIn>
  )
}

/** A link to a page of this app, or, when the signed-in member's role cannot open that page, its text alone (or
 * nothing, with hideWhenBlocked), so a base member is never led to a page they cannot use. Anyone not signed in
 * (only possible in a page rendered on its own, as in a test) gets the plain link. */
export function PageLink({ to, children, hideWhenBlocked, ...rest }: LinkProps & { to: string; hideWhenBlocked?: boolean }) {
  const { signedIn, role, session } = useAuth()
  if (!signedIn || pageAllowed(role, to, session.permissions ?? [])) return <Link to={to} {...rest}>{children}</Link>
  if (hideWhenBlocked) return null
  return <span className={rest.className}>{children}</span>
}
