import type { Role } from './api'

// Where each role lands after signing in: the page that role uses most.
export const ROLE_HOME: Record<Role, string> = {
  admin: '/team',
  strategy: '/drive-team',
  drive: '/drive-team',
  scout: '/scouting',
  base: '/',
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: 'Administrator',
  strategy: 'Strategy team',
  drive: 'Drive team',
  scout: 'Scout',
  base: 'Member',
}

/** The order roles are listed in (most access first). */
export const ROLE_ORDER: Role[] = ['admin', 'strategy', 'drive', 'scout', 'base']

export function homeFor(role: Role | null | undefined): string {
  return role ? ROLE_HOME[role] : '/'
}

/** A "next" target is followed only if it is a path on this site (never another origin). */
export function safeNext(next: string | null): string | null {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : null
}

// Which permission (any of) a page needs, matched by path. The API refuses everything else on its own; this only keeps
// the interface from leading a member to a page their role cannot use. The permissions come from the session, so a
// role's pages follow its grants in workspaces/permissions.py without being repeated here.
const ANYONE = '*'
const PAGE_PERMISSIONS: [RegExp, string[]][] = [
  [/^\/(account|home)\/?$/, [ANYONE]],
  [/^\/$/, ['team_info']],
  [/^\/events\/[^/]+\/?$/, ['team_info']],
  [/^\/events\/[^/]+\/teams\/[^/]+\/?$/, ['team_analytics']],
  [/^\/events\/[^/]+\/strategy-lab\/?$/, ['strategy_tools']],
  [/^\/matches\/[^/]+\/?$/, ['match_predictions', 'strategy_tools']],
  [/^\/report\/[^/]+\/?$/, ['strategy_tools']],
  [/^\/alliance-selection\/live\/?$/, ['alliance_selection']],
  [/^\/drive-team\/?$/, ['match_predictions', 'strategy_tools', 'scouting_view', 'alliance_selection']],
  [/^\/scouting\/?$/, ['scouting_forms']],
  [/^\/scouting\/import\/?$/, ['scouting_import']],
  [/^\/team\/?$/, ['team_management']],
  [/^\/explorer(\/|$)/, ['season_explorer']],
  [/^\/(inputs|readiness|manuals|rulesets)(\/|$)/, ['platform_inputs']],
]

/** The pages a base member may open: the events list, an event's page, and their own account. */
export function basePageAllowed(path: string): boolean {
  return pageAllowed('base', path, ['team_info', 'event_analysis', 'qualification_forecast'])
}

/** Whether a signed-in member of role, holding permissions, may open the page at path. Administrators may open every
 * page; any other role, a page whose permission it holds. */
export function pageAllowed(role: Role | null | undefined, path: string, permissions: readonly string[] = []): boolean {
  if (role === 'admin') return true
  if (!role) return false
  const pathname = path.split(/[?#]/)[0]
  const rule = PAGE_PERMISSIONS.find(([pattern]) => pattern.test(pathname))
  if (!rule) return false // status page and anything unlisted: administrators only
  return rule[1].some((p) => p === ANYONE || permissions.includes(p))
}

/** Where to go after signing in: next when it is safe and this role may open it, otherwise the role's home. */
export function landingFor(role: Role | null | undefined, next: string | null, permissions: readonly string[] = []): string {
  const target = safeNext(next)
  if (target && pageAllowed(role, target, permissions)) return target
  return homeFor(role)
}
