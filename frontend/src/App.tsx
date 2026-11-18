import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import {
  AccountPage,
  AuthLandingPage,
  ForgotPasswordPage,
  LoginPage,
  ResetPasswordPage,
  SignupPage,
} from './auth/AuthPages'
import { AuthProvider } from './auth/AuthContext'
import { useAuth } from './auth/authState'
import { RequirePermission, RequireSignedIn } from './auth/guards'
import { pageAllowed } from './auth/roles'
import { SessionProvider, useSession } from './state/session'
import { DriveTeamDashboardPage, HomeRedirect, ScoutingDashboardPage } from './workspace/RoleDashboards'
import { LiveDraftPage } from './workspace/LiveDraftPage'
import { TeamManagementPage } from './workspace/TeamManagementPage'
import { Icon } from './components/icons'
import { hasOwnBranding, teamBranding } from './team/branding'
import { OverviewPage } from './pages/OverviewPage'
import { GameSpecPage } from './pages/GameSpecPage'
import { ProfilesPage } from './pages/ProfilesPage'
import { ReviewPage } from './pages/ReviewPage'
import { AlliancePage } from './dashboard/pages/AlliancePage'
import { EventPage } from './dashboard/pages/EventPage'
import { EventsPage } from './dashboard/pages/EventsPage'
import { MatchPage } from './dashboard/pages/MatchPage'
import { NotFoundPage } from './dashboard/pages/NotFoundPage'
import { ReportPage } from './dashboard/pages/ReportPage'
import { StatusPage } from './dashboard/pages/StatusPage'
import { StrategyLabPage } from './dashboard/pages/StrategyLabPage'
import { TeamPage } from './dashboard/pages/TeamPage'
import { ManualsPage } from './pages/ManualsPage'
import { RulesetsPage } from './pages/RulesetsPage'
import { ReadinessPage } from './pages/ReadinessPage'
import { ExplorerPage } from './pages/ExplorerPage'
import { EventPage as ExplorerEventPage } from './pages/EventPage'
import { TeamPage as ExplorerTeamPage } from './pages/TeamPage'
import { SUPPORTED_SEASONS } from './lib/format'

// Three areas share one shell: the dashboard (Phase 8); the human-input pages (Phase 5, under /inputs; the old paths
// redirect); and the season pages (game manuals, rulesets, readiness, the historical explorer), each read for one
// selected season.
const SEASON_AREA = /^\/(manuals|rulesets|readiness|explorer)(\/|$)/

function SessionBar() {
  const { actor, setActor, token, setToken, access, season, setSeason, refreshAccess } = useSession()
  const { pathname } = useLocation()
  // The bar shows only to a signed-in administrator. The app's first write-access check can run before sign-in,
  // when a members-only API refuses it, so check again now that someone allowed is here.
  useEffect(() => { void refreshAccess() }, [refreshAccess])
  const inInputs = pathname.startsWith('/inputs')
  const inSeasonArea = SEASON_AREA.test(pathname)
  let accessText = 'API unreachable'
  if (access) {
    if (!access.writes_enabled) accessText = 'writes disabled on server'
    else accessText = access.token_accepted ? 'write token accepted' : 'read-only (no valid token)'
  }
  // On a phone the fields fold behind a toggle (CSS shows the toggle only on narrow screens); the access state stays
  // visible either way.
  const [expanded, setExpanded] = useState(false)
  return (
    <div className={`session-bar${expanded ? '' : ' collapsed'}`}>
      {inInputs && (
        <label>
          Season
          <input type="number" min={1992} value={season} aria-label="Season"
            onChange={(e) => { const v = Number(e.target.value); if (v >= 1992) setSeason(v) }} />
        </label>
      )}
      {inSeasonArea && (
        <label>
          Season
          <select value={season} aria-label="Season" onChange={(e) => setSeason(Number(e.target.value))}>
            {[...new Set<number>([...SUPPORTED_SEASONS, season])].sort((a, b) => b - a).map((s) => (
              <option key={s} value={s}>{s}{s === 2027 ? ' (preparing)' : ''}</option>
            ))}
          </select>
        </label>
      )}
      <button type="button" className="session-toggle link" aria-expanded={expanded} aria-controls="session-fields"
        onClick={() => setExpanded(!expanded)}>Session</button>
      <div className="session-fields" id="session-fields">
      <label>
        Your name
        <input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="recorded on every change"
          aria-label="Your name" />
      </label>
      <label>
        Write token
        <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off"
          aria-label="Write token" />
      </label>
      </div>
      <span className={`access ${access?.token_accepted ? 'access-ok' : 'access-ro'}`} data-testid="access">
        {accessText}
      </span>
    </div>
  )
}

// The admin pages (system status, historical seasons, the human-input pages) sit behind one "Admin" entry, so the
// navigation shows a handful of choices. It closes on navigation, on Escape and on a click elsewhere.
const ADMIN_AREA = /^\/(status|explorer|inputs|readiness|manuals|rulesets)(\/|$)/

function AdminMenu({ pathname, children }: { pathname: string; children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null)
  useEffect(() => { if (ref.current) ref.current.open = false }, [pathname])
  useEffect(() => {
    const close = (event: Event) => {
      const menu = ref.current
      if (!menu?.open) return
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !menu.contains(event.target as Node)) {
        menu.open = false
      }
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', close) }
  }, [])
  return (
    <details ref={ref} className={`nav-more${ADMIN_AREA.test(pathname) ? ' has-active' : ''}`}>
      <summary><Icon name="admin" />Admin<Icon name="chevron-down" className="chevron" /></summary>
      <div className="nav-menu">{children}</div>
    </details>
  )
}

/** After a client-side navigation to another page, move focus to the main region so keyboard and screen-reader
 * users start at the new page (not on the link they left). Search-parameter changes (tabs, as_of) keep focus. */
function useFocusMainOnNavigation(pathname: string) {
  const first = useRef(true)
  // A page without its own title (the human-input pages, a page still loading) must not keep the previous page's:
  // reset first; a page's PageHeader then sets its own in a passive effect, which runs after this layout effect.
  useLayoutEffect(() => { document.title = 'STRATAI' }, [pathname])
  useEffect(() => {
    if (first.current) { first.current = false; return }
    document.getElementById('main')?.focus()
  }, [pathname])
}

const EVENTS_AREA = /^\/($|events\/|matches\/|report\/)/

// The only pages open without signing in: /auth (which forwards to sign-in), sign-in, sign-up and password reset.
// Every other page needs a signed-in member (Shell), whatever the API's ACCESS_POLICY.
const AUTH_AREA = /^\/auth(\/(login|signup|forgot|reset))?\/?$/
// The live alliance-selection page (Phase 11) is a team page too: the team header, not the public pages' session bar.
const WORKSPACE_AREA = /^\/(auth|account|home|team|drive-team|scouting|alliance-selection\/live)(\/|$)/

/** The product name, with the signed-in team's logo and name when it has them (team branding is a per-team setting,
 * src/team/branding.ts); the field mark otherwise. "Team 11 · MORT" appears here and nowhere else in the chrome. */
function Brand() {
  const { signedIn, session } = useAuth()
  const team = signedIn ? session.workspace : null
  const branding = teamBranding(team?.team_number) // MORT's when signed out, or for a team without its own
  const logo = branding.logo
  useTabIcon(hasOwnBranding(team?.team_number) ? branding.tabIcon : undefined)
  return (
    <div className="brand">
      <img className="team-logo" src={logo.src} srcSet={logo.srcSet} width={logo.width} height={logo.height} alt={logo.alt} />
      <strong>STRATAI</strong>
      {team && <span>Team {team.team_number} · {team.team_name}</span>}
    </div>
  )
}

/** The browser tab shows index.html's icons (MORT's), unless the signed-in team has its own: then its icon, until it
 * signs out. */
function useTabIcon(icon: { src32: string; src64: string } | undefined) {
  useEffect(() => {
    if (!icon) return undefined
    const links = [...document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]')]
    const saved = links.map((l) => [l.href, l.type] as const)
    for (const link of links) {
      link.type = 'image/png'
      link.href = window.devicePixelRatio > 1 ? icon.src64 : icon.src32
    }
    return () => links.forEach((link, i) => { link.href = saved[i][0]; link.type = saved[i][1] })
  }, [icon])
}

/** A sign-in link when nobody is signed in; otherwise who is signed in, with their account and sign-out. */
function AccountArea() {
  const { ready, signedIn, session, signOut } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  if (!ready) return null
  if (!signedIn) {
    // The sign-in pages carry their own form: a second "Log in" in the header would be a duplicate choice.
    if (AUTH_AREA.test(pathname)) return null
    return <Link className="button auth-cta" to="/auth/login">Log in</Link>
  }
  return (
    <div className="account-area">
      <span><strong>{session.user?.name}</strong><span className="account-role"> · {session.role_label}</span></span>
      <Link to="/account">Account</Link>
      <button type="button" className="link" onClick={async () => { await signOut(); navigate('/auth/login', { replace: true }) }}>
        Log out</button>
    </div>
  )
}

export function Shell() {
  const { pathname, search } = useLocation()
  const { season } = useSession()
  const { ready, signedIn, role, can, session } = useAuth()
  const inEvents = EVENTS_AREA.test(pathname)
  const inWorkspace = WORKSPACE_AREA.test(pathname)
  useFocusMainOnNavigation(pathname)
  // Each nav item shows only to a member whose role may use it: a base member sees Events alone (and their account).
  // The API enforces all of this on its own; hiding a link is a convenience, not a control.
  const isAdmin = role === 'admin'
  const showDriveTeam = ['match_predictions', 'strategy_tools', 'scouting_view', 'alliance_selection'].some(can)
  // The whole site is behind sign-in: a visitor is sent to sign in (and back afterwards), and a member only sees the
  // pages their role may open. Until the session is known, no page renders, so none starts a request.
  const onAuthPage = AUTH_AREA.test(pathname)
  const waiting = !ready && !onAuthPage
  const needsSignIn = ready && !signedIn && !onAuthPage
  const blocked = ready && signedIn && !onAuthPage && pathname !== '/home' && !pageAllowed(role, pathname, session.permissions ?? [])
  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="top no-print">
        <Brand />
        <nav aria-label="Main" className="main-nav">
          {can('team_info') && (
            <Link to="/" className={inEvents ? 'active' : undefined} aria-current={inEvents ? 'page' : undefined}>
              <Icon name="events" />Events</Link>
          )}
          {can('team_management') && (
            <NavLink to="/team"><Icon name="team" />Team</NavLink>
          )}
          {showDriveTeam && <NavLink to="/drive-team"><Icon name="drive" />Drive team</NavLink>}
          {can('scouting_forms') && <NavLink to="/scouting"><Icon name="scouting" />Scouting</NavLink>}
          {(isAdmin || can('season_explorer') || can('platform_inputs')) && (
            <AdminMenu pathname={pathname}>
              {isAdmin && <NavLink to="/status">System status</NavLink>}
              {can('season_explorer') && <NavLink to="/explorer">Historical seasons</NavLink>}
              {can('platform_inputs') && (
                <>
                  <span className="nav-sep" aria-hidden="true" />
                  <NavLink to="/inputs" end>Inputs overview</NavLink>
                  <NavLink to="/readiness">Readiness &amp; tasks</NavLink>
                  <NavLink to="/manuals">Game manual</NavLink>
                  <NavLink to="/rulesets">Season ruleset</NavLink>
                  <NavLink to="/inputs/game">Game manual &amp; spec</NavLink>
                  <NavLink to="/inputs/profiles">Team profiles</NavLink>
                  <NavLink to="/inputs/review">Human review</NavLink>
                </>
              )}
            </AdminMenu>
          )}
        </nav>
        <AccountArea />
        {!inWorkspace && isAdmin && <SessionBar />}
      </header>
      {/* A season change remounts the page: no state from another season survives. */}
      <main id="main" tabIndex={-1} key={season}>
        {waiting ? <p className="muted" role="status">Checking your sign-in…</p>
          : needsSignIn ? <Navigate to={`/auth/login?next=${encodeURIComponent(pathname + search)}`} replace />
          : blocked ? (
            <div className="notice notice-warn" role="alert">
              <p><strong>Your role does not include this page.</strong> Ask one of the team&apos;s administrators if
                you need it.</p>
              <p><Link to="/">Go to the events</Link></p>
            </div>
          ) : (<>
        <Routes>
          <Route path="/auth" element={<AuthLandingPage />} />
          <Route path="/auth/login" element={<LoginPage />} />
          <Route path="/auth/signup" element={<SignupPage />} />
          <Route path="/auth/forgot" element={<ForgotPasswordPage />} />
          <Route path="/auth/reset" element={<ResetPasswordPage />} />
          <Route path="/account" element={<RequireSignedIn><AccountPage /></RequireSignedIn>} />
          <Route path="/home" element={<HomeRedirect />} />
          <Route path="/team" element={<RequirePermission permission="team_management"><TeamManagementPage /></RequirePermission>} />
          <Route path="/drive-team" element={<RequireSignedIn><DriveTeamDashboardPage /></RequireSignedIn>} />
          <Route path="/alliance-selection/live" element={<RequirePermission permission="alliance_selection"><LiveDraftPage /></RequirePermission>} />
          <Route path="/scouting" element={<RequirePermission permission="scouting_forms"><ScoutingDashboardPage /></RequirePermission>} />
          <Route path="/" element={<EventsPage />} />
          <Route path="/events/:eventKey" element={<EventPage />} />
          <Route path="/events/:eventKey/teams/:team" element={<TeamPage />} />
          <Route path="/events/:eventKey/alliance-selection" element={<AlliancePage />} />
          <Route path="/events/:eventKey/strategy-lab" element={<StrategyLabPage />} />
          <Route path="/matches/:matchKey" element={<MatchPage />} />
          <Route path="/report/:matchKey" element={<ReportPage />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="/inputs" element={<OverviewPage />} />
          <Route path="/inputs/game" element={<GameSpecPage />} />
          <Route path="/inputs/profiles" element={<ProfilesPage />} />
          <Route path="/inputs/review" element={<ReviewPage />} />
          <Route path="/readiness" element={<ReadinessPage />} />
          <Route path="/manuals" element={<ManualsPage />} />
          <Route path="/rulesets" element={<RulesetsPage />} />
          <Route path="/explorer" element={<ExplorerPage />} />
          <Route path="/explorer/events/:eventKey" element={<ExplorerEventPage />} />
          <Route path="/explorer/teams/:teamNumber" element={<ExplorerTeamPage />} />
          <Route path="/game" element={<Navigate to="/inputs/game" replace />} />
          <Route path="/profiles" element={<Navigate to="/inputs/profiles" replace />} />
          <Route path="/review" element={<Navigate to="/inputs/review" replace />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
        </>)}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <SessionProvider>
      <AuthProvider>
        <BrowserRouter>
          <Shell />
        </BrowserRouter>
      </AuthProvider>
    </SessionProvider>
  )
}
