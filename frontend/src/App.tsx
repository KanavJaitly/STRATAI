import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'

import { SessionProvider, useSession } from './state/session'
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

// Two areas share one shell: the dashboard (Phase 8) and the human-input pages (Phase 5, unchanged apart from
// living under /inputs; the old paths redirect).

function SessionBar() {
  const { actor, setActor, token, setToken, access, season, setSeason } = useSession()
  const inInputs = useLocation().pathname.startsWith('/inputs')
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

export function Shell() {
  const { pathname } = useLocation()
  const inInputs = pathname.startsWith('/inputs')
  const inEvents = EVENTS_AREA.test(pathname)
  useFocusMainOnNavigation(pathname)
  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="top no-print">
        <div className="brand">
          <strong>STRATAI</strong>
          <span>{inInputs ? 'Human inputs · P5-M8 / P5-M9 / DM1' : 'Strategy dashboard'}</span>
        </div>
        <nav aria-label="Main">
          <Link to="/" className={inEvents ? 'active' : undefined} aria-current={inEvents ? 'page' : undefined}>
            Events</Link>
          <NavLink to="/status">System status</NavLink>
          <span className="nav-sep" aria-hidden="true" />
          <NavLink to="/inputs" end>Inputs overview</NavLink>
          <NavLink to="/inputs/game">Game manual &amp; spec</NavLink>
          <NavLink to="/inputs/profiles">Team profiles</NavLink>
          <NavLink to="/inputs/review">Human review</NavLink>
        </nav>
        <SessionBar />
      </header>
      <main id="main" tabIndex={-1}>
        <Routes>
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
          <Route path="/game" element={<Navigate to="/inputs/game" replace />} />
          <Route path="/profiles" element={<Navigate to="/inputs/profiles" replace />} />
          <Route path="/review" element={<Navigate to="/inputs/review" replace />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </SessionProvider>
  )
}
