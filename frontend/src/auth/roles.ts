import type { Role } from './api'

// Where each role lands after signing in. An administrator keeps the Admin Dashboard; a base member sees the events.
export const ROLE_HOME: Record<Role, string> = {
  admin: '/team',
  base: '/',
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: 'Administrator',
  base: 'Member',
}

export const ROLE_ORDER: Role[] = ['admin', 'base']

export function homeFor(role: Role | null | undefined): string {
  return role ? ROLE_HOME[role] : '/'
}

/** A "next" target is followed only if it is a path on this site (never another origin). */
export function safeNext(next: string | null): string | null {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : null
}

/** The pages a base member may open: the events list, an event's page, and their own account. (The API refuses
 * everything else for them regardless; this only keeps the interface from leading them to a refusal.) */
export function basePageAllowed(path: string): boolean {
  const pathname = path.split(/[?#]/)[0]
  return pathname === '/' || pathname === '/account' || /^\/events\/[^/]+\/?$/.test(pathname)
}

/** Whether a signed-in member of role may open the page at path. Administrators may open every page. */
export function pageAllowed(role: Role | null | undefined, path: string): boolean {
  if (role === 'admin') return true
  if (role === 'base') return basePageAllowed(path)
  return false
}

/** Where to go after signing in: next when it is safe and this role may open it, otherwise the role's home. */
export function landingFor(role: Role | null | undefined, next: string | null): string {
  const target = safeNext(next)
  if (target && pageAllowed(role, target)) return target
  return homeFor(role)
}
