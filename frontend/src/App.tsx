import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'

import { SessionProvider, useSession } from './state/session'
import { OverviewPage } from './pages/OverviewPage'
import { GameSpecPage } from './pages/GameSpecPage'
import { ProfilesPage } from './pages/ProfilesPage'
import { ReviewPage } from './pages/ReviewPage'

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
        <input type="number" min={1992} value={season} aria-label="Season"
          onChange={(e) => { const v = Number(e.target.value); if (v >= 1992) setSeason(v) }} />
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
  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <strong>STRATAI</strong>
          <span>Human inputs · P5-M8 / P5-M9 / DM1</span>
        </div>
        <nav>
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/game">Game manual &amp; spec</NavLink>
          <NavLink to="/profiles">Team profiles</NavLink>
          <NavLink to="/review">Human review</NavLink>
        </nav>
        <SessionBar />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/game" element={<GameSpecPage />} />
          <Route path="/profiles" element={<ProfilesPage />} />
          <Route path="/review" element={<ReviewPage />} />
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
