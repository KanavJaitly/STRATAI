import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import {
  AcceptInvitationPage,
  AccountPage,
  AuthLandingPage,
  ForgotPasswordPage,
  LoginPage,
  RegisterTeamPage,
  ResetPasswordPage,
} from './auth/AuthPages'
import { AuthProvider } from './auth/AuthContext'
import { useAuth } from './auth/authState'
import { RequirePermission, RequireSignedIn } from './auth/guards'
import { SessionProvider, useSession } from './state/session'
import { DriveTeamDashboardPage, HomeRedirect, ScoutingDashboardPage } from './workspace/RoleDashboards'
import { LiveDraftPage } from './workspace/LiveDraftPage'
import { TeamManagementPage } from './workspace/TeamManagementPage'
import './styles/workspace.css'
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
import Velaris from './components/ui/velaris'

// Three areas share one shell: the dashboard (Phase 8); the human-input pages (Phase 5, under /inputs; the old paths
// redirect); and the season pages (game manuals, rulesets, readiness, the historical explorer), each read for one
// selected season.
const SEASON_AREA = /^\/(manuals|rulesets|readiness|explorer)(\/|$)/

function SessionBar() {
  const { actor, setActor, token, setToken, access, season, setSeason } = useSession()
  const { pathname } = useLocation()
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
      <button type="button" className="session-toggle link" aria-expanded={expanded} aria-controls="session-fields"
        onClick={() => setExpanded(!expanded)}>Session</button>
      <div className="session-fields" id="session-fields">
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

// The sign-in pages, and the team-workspace pages, which have their own sign-in rules.
const AUTH_AREA = /^\/auth(\/|$)/
// The live alliance-selection page (Phase 11) is a team page too: the team header, not the public pages' session bar.
const WORKSPACE_AREA = /^\/(auth|account|home|team|drive-team|scouting|alliance-selection\/live)(\/|$)/

/** Sign in / register when nobody is signed in; otherwise who is signed in, to which team, with sign-out. */
function AccountArea() {
  const { ready, signedIn, session, signOut } = useAuth()
  const navigate = useNavigate()
  if (!ready) return null
  if (!signedIn) {
    return <Link className="button auth-cta" to="/auth">Login / Register to Your Team&apos;s StratAI</Link>
  }
  return (
    <div className="account-area">
      <span><strong>{session.user?.name}</strong> · team {session.workspace?.team_number} · {session.role_label}</span>
      <Link to="/account">Account</Link>
      <button type="button" className="link" onClick={async () => { await signOut(); navigate('/auth', { replace: true }) }}>
        Log out</button>
    </div>
  )
}

// The hero's animated gradient: burnt amber, dusk violet and cobalt over the black canvas, dark enough that the
// white text on it stays readable.
const HERO_COLORS = ['#9a3412', '#4c3a9e', '#1e3a8a', '#0a0a0a']

/** The landing page's invitation to the team workspaces, for anyone not signed in. */
function TeamWorkspaceCallout() {
  return (
    <section className="auth-callout no-print" aria-labelledby="team-workspace-callout">
      <Velaris bg="#0a0a0a" colors={HERO_COLORS} speed={1.2} grain={0.25} />
      <div>
        <h2 id="team-workspace-callout">Your team&apos;s own StratAI</h2>
        <p>Give every member of your FRC team their own account, with roles for administrators, the drive team and
          scouters, and keep your team&apos;s scouting private to your team.</p>
      </div>
      <Link className="button auth-cta" to="/auth">Login / Register to Your Team&apos;s StratAI</Link>
    </section>
  )
}

export function Shell() {
  const { pathname, search } = useLocation()
  const { season } = useSession()
  const { ready, signedIn, role, can, session } = useAuth()
  const inInputs = pathname.startsWith('/inputs')
  const inEvents = EVENTS_AREA.test(pathname)
  const inSeasonArea = SEASON_AREA.test(pathname)
  const inWorkspace = WORKSPACE_AREA.test(pathname)
  useFocusMainOnNavigation(pathname)
  // Signed-in members see the existing features their role may use; the platform-wide human-input and season tools
  // stay visible to visitors (as before) and to administrators. The API enforces all of this on its own.
  const showPublic = !signedIn || can('team_info')
  const showPlatformTools = !signedIn || role === 'admin'
  const showDriveTeam = signedIn && ['event_analysis', 'match_predictions', 'strategy_tools', 'scouting_view',
    'alliance_selection'].some(can)
  // Under ACCESS_POLICY=members nothing but the sign-in pages is open to a visitor.
  const membersOnly = ready && !signedIn && session.access_policy === 'members' && !AUTH_AREA.test(pathname)
  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="top no-print">
        <div className="brand">
          <strong>STRATAI</strong>
          <span>{inWorkspace ? (signedIn ? `Team ${session.workspace?.team_number} workspace` : 'Team workspaces')
            : inInputs ? 'Human inputs'
            : inSeasonArea ? 'Game manuals, season rulesets, readiness and historical seasons' : 'Strategy dashboard'}</span>
        </div>
        <nav aria-label="Main">
          {showPublic && (
            <Link to="/" className={inEvents ? 'active' : undefined} aria-current={inEvents ? 'page' : undefined}>
              Events</Link>
          )}
          {can('team_management') && <NavLink to="/team">Team Management</NavLink>}
          {showDriveTeam && <NavLink to="/drive-team">Drive team</NavLink>}
          {can('scouting_forms') && <NavLink to="/scouting">Scouting</NavLink>}
          <NavLink to="/status">System status</NavLink>
          {showPublic && <NavLink to="/explorer">Historical seasons</NavLink>}
          {showPlatformTools && (
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
        </nav>
        <AccountArea />
        {!inWorkspace && <SessionBar />}
      </header>
      {/* A season change remounts the page: no state from another season survives. */}
      <main id="main" tabIndex={-1} key={season}>
        {/* Members-only and signed out: only the redirect renders, so no page starts a request the API would refuse. */}
        {membersOnly ? <Navigate to={`/auth/login?next=${encodeURIComponent(pathname + search)}`} replace /> : (<>
        {pathname === '/' && ready && !signedIn && <TeamWorkspaceCallout />}
        <Routes>
          <Route path="/auth" element={<AuthLandingPage />} />
          <Route path="/auth/register" element={<RegisterTeamPage />} />
          <Route path="/auth/login" element={<LoginPage />} />
          <Route path="/auth/forgot" element={<ForgotPasswordPage />} />
          <Route path="/auth/reset" element={<ResetPasswordPage />} />
          <Route path="/auth/invite" element={<AcceptInvitationPage />} />
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
