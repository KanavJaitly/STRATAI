import type { Role } from './api'

// Where each role lands after signing in: one shell and one navigation, each role's own focused dashboard.
export const ROLE_HOME: Record<Role, string> = {
  admin: '/team',
  strategy: '/drive-team',
  scouter: '/scouting',
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: 'Administrator',
  strategy: 'Drive team / strategy',
  scouter: 'Scouter',
}

export const ROLE_ORDER: Role[] = ['admin', 'strategy', 'scouter']

export function homeFor(role: Role | null | undefined): string {
  return role ? ROLE_HOME[role] : '/'
}

/** A "next" target is followed only if it is a path on this site (never another origin). */
export function safeNext(next: string | null): string | null {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : null
}
