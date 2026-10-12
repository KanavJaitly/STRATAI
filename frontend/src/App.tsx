import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'

import { SessionProvider, useSession } from './state/session'
import { OverviewPage } from './pages/OverviewPage'
import { GameSpecPage } from './pages/GameSpecPage'
import { ProfilesPage } from './pages/ProfilesPage'
import { ReviewPage } from './pages/ReviewPage'
import { ManualsPage } from './pages/ManualsPage'
import { RulesetsPage } from './pages/RulesetsPage'
import { ReadinessPage } from './pages/ReadinessPage'
import { ExplorerPage } from './pages/ExplorerPage'
import { EventPage } from './pages/EventPage'
import { TeamPage } from './pages/TeamPage'
import { SUPPORTED_SEASONS } from './lib/format'

function SessionBar() {
  const { actor, setActor, token, setToken, access, season, setSeason } = useSession()
  let accessText = 'API unreachable'
  if (access) {
    if (!access.writes_enabled) accessText = 'writes disabled on server'
    else accessText = access.token_accepted ? 'write token accepted' : 'read-only (no valid token)'
  }
  return (
    <div className="session-bar">
      <label>
        Season
        <select value={season} aria-label="Season" onChange={(e) => setSeason(Number(e.target.value))}>
          {[...new Set<number>([...SUPPORTED_SEASONS, season])].sort((a, b) => b - a).map((s) => (
            <option key={s} value={s}>{s}{s === 2027 ? ' (preparing)' : ''}</option>
          ))}
        </select>
      </label>
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
      <span className={`access ${access?.token_accepted ? 'access-ok' : 'access-ro'}`} data-testid="access">
        {accessText}
      </span>
    </div>
  )
}

export function Shell() {
  const { season } = useSession()
  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <strong>STRATAI</strong>
          <span>Game manuals, season rulesets, readiness, historical seasons and human inputs</span>
        </div>
        <nav>
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/readiness">Readiness &amp; tasks</NavLink>
          <NavLink to="/explorer">Historical seasons</NavLink>
          <NavLink to="/manuals">Game manual</NavLink>
          <NavLink to="/rulesets">Season ruleset</NavLink>
          <NavLink to="/game">Game spec</NavLink>
          <NavLink to="/profiles">Team profiles</NavLink>
          <NavLink to="/review">Human review</NavLink>
        </nav>
        <SessionBar />
      </header>
      <main key={season /* a season change remounts every page: no state from another season survives */}>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/game" element={<GameSpecPage />} />
          <Route path="/profiles" element={<ProfilesPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/readiness" element={<ReadinessPage />} />
          <Route path="/manuals" element={<ManualsPage />} />
          <Route path="/rulesets" element={<RulesetsPage />} />
          <Route path="/explorer" element={<ExplorerPage />} />
          <Route path="/explorer/events/:eventKey" element={<EventPage />} />
          <Route path="/explorer/teams/:teamNumber" element={<TeamPage />} />
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
