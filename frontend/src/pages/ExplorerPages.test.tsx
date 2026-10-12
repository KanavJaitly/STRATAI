// The historical season explorer and season switching (2026-10-11). SYNTHETIC fixture data through a mocked API.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { Shell } from '../App'
import { preEventAsOf } from '../lib/format'
import { SessionProvider } from '../state/session'
import { WRITE_OFF, apiError, mockApi } from '../test/mockApi'
import { EventPage } from './EventPage'
import { ExplorerPage } from './ExplorerPage'
import { TeamPage } from './TeamPage'

const coverage = (season: number, hasData = true) => ({ events: hasData ? 2 : 0, matches: hasData ? 10 : 0,
  matches_played: hasData ? 8 : 0, qualification_matches_played: 6, playoff_matches_played: 2, teams: hasData ? 12 : 0,
  team_event_epa_rows: hasData && season !== 2023 ? 12 : 0, team_metrics_rows: 0, events_with_metrics: 0,
  scouting_observations: 0, latest_update: '2026-10-11T00:00:00Z', latest_match: `${season}-04-01T00:00:00Z`,
  score_breakdown_adapter: season >= 2024 && season <= 2026, has_data: hasData })
const readiness = (season: number, hasData = true) => ({ season, coverage: coverage(season, hasData),
  human_inputs: { manuals: [], game_spec: null, ruleset: { approved: null, latest: null } },
  features: [
    { key: 'event_browser', name: 'Events, teams and matches', consumes: ['events'], available: hasData,
      reasons: hasData ? [] : [`no ${season} event data is synced`], route: '/explorer', requires_human: null },
    { key: 'event_analysis', name: 'Event analysis and ranking (P5-M4..M6)', consumes: ['ranking model'], available: false,
      reasons: ['no ranking model is pinned on this API instance'], route: '/explorer', requires_human: null },
    { key: 'team_strength', name: 'Team strength (EPA source)', consumes: ['EPA source'], available: hasData, reasons: [],
      limitations: season === 2023 ? ['no score-breakdown adapter for 2023: an answer that needs this event’s played '
        + 'matches is refused (season_not_supported)'] : [], route: '/explorer', requires_human: null }],
  automation_boundary: { automatic: [], never_automatic: [] } })
const events = (season: number) => [
  { event_key: `${season}abc`, name: `Alpha Regional ${season}`, event_code: 'abc', event_type: null, start_date: `${season}-03-01`,
    end_date: `${season}-03-03`, city: 'Austin', state_prov: 'TX', country: 'USA', matches: 6, matches_played: 6, teams: 6 },
  { event_key: `${season}xyz`, name: `Zeta District ${season}`, event_code: 'xyz', event_type: null, start_date: `${season}-03-08`,
    end_date: null, city: 'Detroit', state_prov: 'MI', country: 'USA', matches: 4, matches_played: 0, teams: 6 }]
const EVENT = { event_key: '2025abc', season: 2025, name: 'Alpha Regional 2025', start_date: '2025-03-01', end_date: '2025-03-03',
  city: 'Austin', state_prov: 'TX', country: 'USA' }
const TEAMS = { event: EVENT, epa_source: 'Statbotics team_event_stats as synced', teams: [
  { team_number: 254, name: 'Cheesy Poofs', city: null, state_province: null, country: null, epa_total: '61.20', epa_auto: '12.10',
    epa_teleop: '40.00', epa_endgame: '9.10', wins: 9, losses: 1, ties: 0, matches_played: 10, metrics_computed: false }] }
const MATCHES = { event: EVENT, matches: [
  { match_key: '2025abc_qm1', competition_level: 'qualification', set_number: 1, match_number: 1, scheduled_time: null,
    score_red: 100, score_blue: 90, winning_alliance: 'red', red: [254, 1, 2], blue: [3, 4, 5] },
  { match_key: '2025abc_f1m1', competition_level: 'final', set_number: 1, match_number: 1, scheduled_time: null,
    score_red: null, score_blue: null, winning_alliance: null, red: [254, 1, 2], blue: [3, 4, 5] }] }

function renderAt(path: string, routes = true) {
  return render(
    <SessionProvider>
      <MemoryRouter initialEntries={[path]}>
        {routes ? (
          <Routes>
            <Route path="/explorer" element={<ExplorerPage />} />
            <Route path="/explorer/events/:eventKey" element={<EventPage />} />
            <Route path="/explorer/teams/:teamNumber" element={<TeamPage />} />
          </Routes>
        ) : <Shell />}
      </MemoryRouter>
    </SessionProvider>,
  )
}

function asSeason(season: number) {
  window.localStorage.setItem('stratai.season', String(season))
  window.localStorage.setItem('stratai.actor', 'Test Person')
}

describe('ExplorerPage', () => {
  it('shows real coverage, unavailable features with reasons, and filters events', async () => {
    asSeason(2025)
    mockApi({ ...WRITE_OFF, 'GET /human-inputs/seasons/2025/readiness': readiness(2025), 'GET /seasons/2025/events': events(2025) })
    renderAt('/explorer')
    expect(await screen.findByTestId('coverage')).toHaveTextContent('Events')
    expect(screen.getByTestId('feature-availability')).toHaveTextContent('no ranking model is pinned')
    const table = await screen.findByTestId('events-table')
    expect(within(table).getByText('Alpha Regional 2025')).toBeInTheDocument()
    expect(within(table).queryByText('Zeta District 2025')).toBeNull() // no results yet: hidden by default
    await userEvent.click(screen.getByLabelText('Only events with results'))
    expect(within(screen.getByTestId('events-table')).getByText('Zeta District 2025')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Search events'), 'detroit')
    expect(within(screen.getByTestId('events-table')).queryByText('Alpha Regional 2025')).toBeNull()
  })

  it('marks a callable but limited feature as limited, with what it cannot answer', async () => {
    asSeason(2023)
    mockApi({ ...WRITE_OFF, 'GET /human-inputs/seasons/2023/readiness': readiness(2023), 'GET /seasons/2023/events': events(2023) })
    renderAt('/explorer')
    const features = await screen.findByTestId('feature-availability')
    const strength = within(features).getByText(/Team strength/).closest('li') as HTMLElement
    expect(strength).toHaveTextContent('limited')
    expect(strength).toHaveTextContent('season_not_supported')
    expect(strength).not.toHaveTextContent(/^available/)
  })

  it('says plainly when a season has no data', async () => {
    asSeason(2027)
    mockApi({ ...WRITE_OFF, 'GET /human-inputs/seasons/2027/readiness': readiness(2027, false), 'GET /seasons/2027/events': [] })
    renderAt('/explorer')
    expect(await screen.findByTestId('no-season-data')).toHaveTextContent('has not been played')
    expect(await screen.findByTestId('no-events')).toBeInTheDocument()
  })
})

describe('EventPage', () => {
  it('shows teams and matches and explains unavailable analyses instead of showing empty results', async () => {
    asSeason(2025)
    const api = mockApi({ ...WRITE_OFF, 'GET /events/2025abc/teams': TEAMS, 'GET /events/2025abc/matches': MATCHES,
      'GET /events/2025abc/analysis': apiError(404, 'model_not_loaded', 'no ranking model'),
      'GET /events/2025abc/qualification-forecast': apiError(422, 'season_not_supported', 'no adapter'),
      'GET /predictions/matches/2025abc_qm1/win-probability': { validation_status: 'not_validated',
        not_validated_reason: 'epa_incomplete', red_win_probability: null, unvalidated_red_win_probability: 0.7 } })
    renderAt('/explorer/events/2025abc')
    expect(await screen.findByText('Cheesy Poofs')).toBeInTheDocument()
    expect(screen.getByText('61.20')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Matches' }))
    const table = await screen.findByTestId('matches-table')
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    await userEvent.selectOptions(screen.getByLabelText('Match level'), 'playoff')
    expect(within(screen.getByTestId('matches-table')).getAllByRole('row')).toHaveLength(2)
    await userEvent.selectOptions(screen.getByLabelText('Match level'), 'qualification')
    await userEvent.click(within(screen.getByTestId('matches-table')).getByRole('button', { name: 'Win probability' }))
    const wp = await screen.findByTestId('wp-2025abc_qm1')
    expect(wp).toHaveTextContent('not a validated probability')
    expect(wp).toHaveTextContent('epa_incomplete')
    await userEvent.click(screen.getByRole('tab', { name: 'Event analysis' }))
    expect(await screen.findByTestId('unavailable')).toHaveTextContent('no pinned model')
    // a past event is analysed as of before it began, never silently "now" (which would use later evidence)
    expect(screen.getByTestId('pre-event')).toBeInTheDocument()
    expect(api.calls.find((c) => c.path === '/events/2025abc/analysis')?.query.get('as_of')).toBe('2025-03-01T00:00:00+14:00')
    await userEvent.clear(screen.getByLabelText('As of'))
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(await screen.findByTestId('as-of-now')).toHaveTextContent('not a historical test')
    expect(api.calls.filter((c) => c.path === '/events/2025abc/analysis').at(-1)?.query.has('as_of')).toBe(false)
    await userEvent.click(screen.getByRole('tab', { name: 'Qualification forecast' }))
    expect(await screen.findByTestId('unavailable')).toHaveTextContent('no verified score-breakdown adapter')
    await userEvent.click(screen.getByRole('tab', { name: 'Ranking prediction' }))
    expect(await screen.findByTestId('ranking-now')).toHaveTextContent('always as of now')
  })

  it('warns when the event belongs to another season than the one selected, and can switch', async () => {
    asSeason(2026)
    mockApi({ ...WRITE_OFF, 'GET /events/2025abc/teams': TEAMS, 'GET /events/2025abc/matches': MATCHES })
    renderAt('/explorer/events/2025abc')
    const banner = await screen.findByTestId('season-mismatch')
    expect(banner).toHaveTextContent('This event is from 2025, but 2026 is selected')
    await userEvent.click(within(banner).getByRole('button', { name: 'Switch to 2025' }))
    await waitFor(() => expect(screen.queryByTestId('season-mismatch')).toBeNull())
    expect(window.localStorage.getItem('stratai.season')).toBe('2025')
  })
})

describe('TeamPage', () => {
  it('lists the team’s events of the selected season and shows measured strength with its statuses', async () => {
    asSeason(2025)
    const api = mockApi({ ...WRITE_OFF, 'GET /teams/254/seasons/2025': { season: 2025, team: { team_number: 254, name: 'Cheesy Poofs',
      city: 'San Jose', state_province: 'CA', country: 'USA', rookie_year: 1999 }, events: [{ event_key: '2025abc',
      name: 'Alpha Regional 2025', start_date: '2025-03-01', epa_total: '61.20', epa_auto: null, epa_teleop: null,
      epa_endgame: null, wins: 9, losses: 1, ties: 0, matches_played: 10, metrics_computed: false }] },
    'GET /teams/254/events/2025abc/strength': { strength: { as_of: '2025-03-04T00:00:00Z',
      epa: { total: { value: 61.2, n: 10, uncertainty: { kind: 'none', value: null }, absent_reason: null },
        validation_status: 'descriptive', source_event_key: '2025xyz' },
      scoring: { average_score: { value: 95.5, n: 10, uncertainty: { kind: 'sd', value: 12.3 }, absent_reason: null },
        validation_status: 'descriptive' },
      auto_points: { this_event: { value: null, n: 0, absent_reason: 'no score breakdown' }, validation_status: 'descriptive' },
      defense: { score: null, validation_status: 'descriptive_definition_pending' },
      feeding: { score: null, validation_status: 'not_validated' } } },
    'GET /teams/254/events/2025abc/metrics': apiError(404, 'metrics_not_computed', 'not computed') })
    renderAt('/explorer/teams/254')
    expect(await screen.findByText(/Team 254 — Cheesy Poofs/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Strength' }))
    const table = await screen.findByTestId('strength-table')
    expect(api.calls.find((c) => c.path.endsWith('/strength'))?.query.get('as_of')).toBe('2025-03-01T00:00:00+14:00')
    expect(table).toHaveTextContent('95.5 ± 12.3')
    expect(table).toHaveTextContent('absent (no score breakdown)')
    expect(table).toHaveTextContent('descriptive definition pending')
    await userEvent.click(screen.getByRole('button', { name: 'Metrics' }))
    expect(await screen.findByTestId('unavailable')).toHaveTextContent('have not been computed')
  })
})

describe('season switching (the app shell)', () => {
  it('re-fetches for the new season, never shows the previous season’s data, and browsing history writes nothing', async () => {
    asSeason(2026)
    const api = mockApi({ ...WRITE_OFF,
      'GET /human-inputs/seasons/2026/readiness': readiness(2026), 'GET /seasons/2026/events': events(2026),
      'GET /human-inputs/seasons/2024/readiness': readiness(2024), 'GET /seasons/2024/events': events(2024) })
    renderAt('/explorer', false)
    expect(await screen.findByText('Alpha Regional 2026')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Season'), '2024')
    expect(await screen.findByText('Alpha Regional 2024')).toBeInTheDocument()
    expect(screen.queryByText('Alpha Regional 2026')).toBeNull()
    expect(api.calls.some((c) => c.path === '/seasons/2024/events')).toBe(true)
    expect(api.writes()).toHaveLength(0)
    expect(api.calls.some((c) => c.path.includes('/processing'))).toBe(false)
  })

  it('offers exactly the supported seasons', async () => {
    asSeason(2026)
    mockApi({ ...WRITE_OFF, 'GET /human-inputs/seasons/2026/readiness': readiness(2026), 'GET /seasons/2026/events': [] })
    renderAt('/explorer', false)
    const options = within(await screen.findByLabelText('Season')).getAllByRole('option').map((o) => o.getAttribute('value'))
    expect(options).toEqual(['2027', '2026', '2025', '2024', '2023'])
  })
})

describe('preEventAsOf', () => {
  const today = new Date('2026-10-12T12:00:00Z')
  it('is before the event for a past event, and now for a current, future or undated one', () => {
    expect(preEventAsOf('2025-03-01', '2025-03-03', today)).toBe('2025-03-01T00:00:00+14:00')
    expect(preEventAsOf('2026-10-10', '2026-10-12', today)).toBe('')
    expect(preEventAsOf('2027-03-01', '2027-03-03', today)).toBe('')
    expect(preEventAsOf('2026-10-08', null, today)).toBe('')  // no end date: treated as ended a week after it started
    expect(preEventAsOf('2026-09-01', undefined, today)).toBe('2026-09-01T00:00:00+14:00')
    expect(preEventAsOf(null, null, today)).toBe('')
  })
})
