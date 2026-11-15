import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Shell } from '../App'
import { AuthProvider } from '../auth/AuthContext'
import type { DraftRecommendations, DraftRecord, SessionInfo } from '../auth/api'
import { SessionProvider } from '../state/session'
import { EPA, EVENTS, measure, strengthView } from '../test/dashboardFixtures'
import { axeViolations } from '../test/dashboard'
import { apiError, mockApi } from '../test/mockApi'
import { clearSeasonEvents } from './events'
import { LiveDraftPage } from './LiveDraftPage'

// Phase 11: the live alliance-selection page. Synthetic fixture data only (season 2099, teams 1-24): nothing here is
// evidence about any real team or event.

const EVENT = '2099synth'
const BASE = '/workspace/alliance-selection/drafts'
const SEASON_EVENTS = { 'GET /explorer/seasons/2099/events': [
  { event_key: EVENT, name: 'Synthetic Test Event', event_code: 'synth', event_type: null, start_date: '2099-03-01',
    end_date: '2099-03-03', city: 'Testville', state_prov: 'NJ', country: 'USA', district: 'fma',
    district_name: 'FIRST Mid-Atlantic', matches: 1, matches_played: 1, teams: 24 }] }

function session(role: 'admin' | 'strategy' | 'scouter', permissions: string[]): SessionInfo {
  return { authenticated: true, access_policy: 'open', email_delivery_configured: false,
    user: { id: 1, name: 'Ada Admin', email: 'ada@example.test' },
    workspace: { team_number: 1, team_name: 'Synthetic Robotics', verification_status: 'verified' }, role,
    role_label: role, permissions }
}
const ADMIN = session('admin', ['team_info', 'alliance_selection', 'alliance_selection_record', 'team_management'])
const STRATEGY = session('strategy', ['team_info', 'alliance_selection', 'strategy_tools'])
const SCOUTER = session('scouter', ['team_info', 'scouting_forms'])

const TEAMS = Array.from({ length: 24 }, (_, i) => i + 1)

function draft(overrides: Partial<DraftRecord> = {}): DraftRecord {
  const taken = new Set([1])
  return {
    record_id: 5, record_uid: '00000000-0000-4000-8000-000000000005', event_key: EVENT,
    created_at: '2099-03-03T16:00:00Z', created_by: 'Ada Admin', can_record: true, team_number: 1, record_seq: 2,
    status: 'open', configured: true,
    setup: { rules: { n_alliances: 8, picks_per_alliance: 2, declined_team_may_be_picked_later: false,
      declined_team_may_become_captain: true, captain_may_accept_higher_alliance: true, backup_robots: false,
      source: 'approved_ruleset', ruleset_sha256: 'ab'.repeat(32), ruleset_variant: null,
      captain_rule_established: true }, ranks: TEAMS.map((t) => [t, t]), pool: TEAMS, missing: [], provenance: {} },
    value_kind: 'observed',
    alliances: Array.from({ length: 8 }, (_, i) => ({ seed: i + 1, captain: i === 0 ? 1 : null, picks: [],
      projected_captain: i === 0 ? null : i + 1 })),
    turn: { index: 0, round: 1, seed: 1, captain_named: true, expected_captain: null, expected_captain_reason: null },
    complete: false,
    available: TEAMS.filter((t) => !taken.has(t)).map((t) => ({ team_number: t, rank: t,
      projected_captain_of: t <= 8 ? t : null, declined_earlier: false })),
    unavailable: [{ team_number: 1, reason: 'captain', rank: 1, seed: 1 }],
    declined: [], backups: [], flags: [],
    effective: [{ action_id: 'a-captain', slot_action_id: 'a-captain', seq: 2, type: 'captain', seed: 1,
      team_number: 1, status: 'accepted', violation: null, override_reason: null, notes: [],
      summary: "Alliance 1's captain is team 1", recorded_by: 'Ada Admin', recorded_at: '2099-03-03T16:00:05Z' }],
    history: [
      { action_id: 'a-config', seq: 1, type: 'configure', summary: 'Record configured', override_reason: null,
        in_effect: true, superseded_by: null, recorded_by: 'Ada Admin', recorded_at: '2099-03-03T16:00:00Z',
        source: 'manual', mode: 'online' },
      { action_id: 'a-captain', seq: 2, type: 'captain', summary: "Alliance 1's captain is team 1",
        override_reason: null, in_effect: true, superseded_by: null, recorded_by: 'Ada Admin',
        recorded_at: '2099-03-03T16:00:05Z', source: 'manual', mode: 'online' }],
    ...overrides,
  }
}

function recs(overrides: Partial<DraftRecommendations> = {}): DraftRecommendations {
  return {
    record_id: 5, record_seq: 2, computed_at: '2099-03-03T16:00:06Z', status: 'current', withheld: null,
    value_kind: 'model_prediction', source: 'fallback_p11_fb1',
    validation: { status: 'not_validated', reasons: ['P11-FB1: ranks available teams by the P5-M4 team-strength '
      + 'ordering; it is not validated as a pick recommendation and gives no P(win event)'] },
    engine_refusal: { code: 'playoff_models_not_accepted', message: 'PX gates not passed: PX-1, PX-2, PX-4' },
    seed: 1, selecting_as: 'on_alliance', turns_before: 0,
    primary: { team_number: 24, ordering_position: 1, win_event: null, reach_finals: null, configuration: null,
      profile: null },
    backups: [23, 22, 21].map((t, i) => ({ team_number: t, ordering_position: i + 2, win_event: null,
      reach_finals: null, configuration: null, profile: null })),
    unranked_available: [], excluded: [], movement: [], provenance: {}, timing_ms: { total: 3 },
    ...overrides,
  }
}

function renderAt(url: string) {
  return render(
    <SessionProvider><AuthProvider><MemoryRouter initialEntries={[url]}><Shell /></MemoryRouter></AuthProvider></SessionProvider>)
}

const URL = `/alliance-selection/live?event=${EVENT}`
const LISTED = { [`GET ${BASE}`]: [{ record_id: 5, record_uid: 'x', event_key: EVENT, created_at: '2099-03-03T16:00:00Z',
  created_by: 'Ada Admin', record_seq: 2, status: 'open', picks_made: 0, complete: false }] }

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); clearSeasonEvents() })

describe('live alliance selection', () => {
  it('shows the board and the fallback picks labelled not validated, with no probability', async () => {
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft({ can_record: false }), [`GET ${BASE}/5/recommendations`]: recs() })
    renderAt(URL)
    const picks = await screen.findByRole('region', { name: 'Your picks' })
    expect(await within(picks).findByText('24')).toBeInTheDocument()
    expect(within(picks).getByText(/Fallback rule P11-FB1/)).toBeInTheDocument()
    expect(within(picks).getByText('not validated')).toBeInTheDocument()
    expect(within(picks).queryByText(/P\(win event\) \d/)).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Record an action' })).not.toBeInTheDocument()
    expect(screen.getByText(/You can watch the board/)).toBeInTheDocument()
  })

  it('is shown as a team page: the team header, without the public pages\' name and write-token bar', async () => {
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft({ can_record: false }), [`GET ${BASE}/5/recommendations`]: recs() })
    renderAt(URL)
    await screen.findByRole('region', { name: 'Your picks' })
    expect(screen.getByText('Team 1 workspace')).toBeInTheDocument()
    expect(screen.queryByLabelText('Write token')).not.toBeInTheDocument()
  })

  it('records a pick by tapping a listed team, with CSRF and a client action id', async () => {
    const after = draft({ record_seq: 3, turn: { index: 1, round: 1, seed: 2, captain_named: false,
      expected_captain: 2, expected_captain_reason: null } })
    const api = mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft(), [`GET ${BASE}/5/recommendations`]: recs(),
      [`POST ${BASE}/5/actions`]: after })
    renderAt(URL)
    const grid = await screen.findByRole('group', { name: 'Available teams' })
    await userEvent.click(within(grid).getByRole('button', { name: /^24/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Alliance 1 picks 24' }))
    await waitFor(() => expect(api.writes()).toHaveLength(1))
    const write = api.writes()[0]
    expect(write.headers['X-StratAI-CSRF']).toBe('1')
    expect(write.body).toMatchObject({ type: 'pick', seed: 1, team_number: 24, override_reason: null })
    expect((write.body as { action_id: string }).action_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(await screen.findByRole('button', { name: 'Confirm alliance 2 captain: 2' })).toBeInTheDocument()
  })

  it('offers an override with a reason when the rules refuse an action', async () => {
    let attempt = 0
    const api = mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft(), [`GET ${BASE}/5/recommendations`]: recs(),
      [`POST ${BASE}/5/actions`]: () => (attempt++ === 0
        ? apiError(409, 'team_declined', 'team 7 declined an invitation, and the event\'s rules do not let it be picked later')
        : draft({ record_seq: 3 })) })
    renderAt(URL)
    const grid = await screen.findByRole('group', { name: 'Available teams' })
    await userEvent.click(within(grid).getByRole('button', { name: /^7/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Alliance 1 picks 7' }))
    const form = await screen.findByRole('form', { name: 'Override' })
    expect(within(form).getByText(/declined an invitation/)).toBeInTheDocument()
    const submit = within(form).getByRole('button', { name: 'Record with override' })
    expect(submit).toBeDisabled()
    await userEvent.type(within(form).getByRole('textbox'), 'event-specific rule')
    await userEvent.click(submit)
    await waitFor(() => expect(api.writes()).toHaveLength(2))
    expect(api.writes()[1].body).toMatchObject({ type: 'pick', team_number: 7, override_reason: 'event-specific rule' })
  })

  it('marks recommendations from an older record version as stale, never current', async () => {
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft({ can_record: false, record_seq: 4 }),
      [`GET ${BASE}/5/recommendations`]: recs({ record_seq: 3 }) })
    renderAt(URL)
    const picks = await screen.findByRole('region', { name: 'Your picks' })
    expect(await within(picks).findByText('Stale')).toBeInTheDocument()
    expect(within(picks).getByText(/reflect record #3/)).toBeInTheDocument()
  })

  it('keeps the last recommendation, marked stale with the reason, when a refresh fails', async () => {
    let calls = 0
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: () => draft({ can_record: false, record_seq: calls > 0 ? 3 : 2 }),
      [`GET ${BASE}/5/recommendations`]: () => (calls++ === 0 ? recs()
        : apiError(409, 'live_draft_unavailable', 'Live alliance selection needs database migration 0013')) })
    render(
      <SessionProvider><AuthProvider><MemoryRouter initialEntries={[URL]}><ShellWithFastPoll /></MemoryRouter>
      </AuthProvider></SessionProvider>)
    const picks = await screen.findByRole('region', { name: 'Your picks' })
    expect(await within(picks).findByText('24')).toBeInTheDocument()
    expect(await within(picks).findByText(/refresh failed/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(within(picks).getByText('Stale')).toBeInTheDocument()
    expect(within(picks).getByText('24')).toBeInTheDocument()
  })

  it('never highlights a stale primary on the team grid', async () => {
    mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft({ record_seq: 4 }), [`GET ${BASE}/5/recommendations`]: recs({ record_seq: 3 }) })
    renderAt(URL)
    const grid = await screen.findByRole('group', { name: 'Available teams' })
    await within(await screen.findByRole('region', { name: 'Your picks' })).findByText('Stale')
    expect(within(grid).getByRole('button', { name: /^24/ })).not.toHaveClass('recommended')
  })

  it('keeps the last picks, marked stale, when a recalculation is withheld for a missing input', async () => {
    let calls = 0
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: () => draft({ can_record: false, record_seq: calls > 0 ? 3 : 2 }),
      [`GET ${BASE}/5/recommendations`]: () => (calls++ === 0 ? recs() : recs({ record_seq: 3, status: 'withheld',
        primary: null, backups: [], source: null, validation: null,
        withheld: { code: 'epa_source_not_loaded', message: 'the EPA source is not loaded' } })) })
    render(
      <SessionProvider><AuthProvider><MemoryRouter initialEntries={[URL]}><ShellWithFastPoll /></MemoryRouter>
      </AuthProvider></SessionProvider>)
    const picks = await screen.findByRole('region', { name: 'Your picks' })
    expect(await within(picks).findByText(/epa_source_not_loaded/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(within(picks).getByText('Stale')).toBeInTheDocument()
    expect(within(picks).getByText('24')).toBeInTheDocument()
  })

  it('shows a withheld recommendation with its reason', async () => {
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft({ can_record: false }),
      [`GET ${BASE}/5/recommendations`]: recs({ status: 'withheld', primary: null, backups: [], source: null,
        validation: null, withheld: { code: 'team_not_selecting', message: 'team 1 is not on an alliance' } }) })
    renderAt(URL)
    expect(await screen.findByText(/No recommendation: team 1 is not on an alliance/)).toBeInTheDocument()
  })

  it('asks for the event\'s rules when no approved ruleset covers it', async () => {
    let starts = 0
    const api = mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, [`GET ${BASE}`]: [],
      [`POST ${BASE}`]: () => (starts++ === 0
        ? apiError(422, 'rules_required', 'No approved ruleset gives this event\'s rules (not_approved).')
        : { status: 201, body: draft() }) })
    renderAt(URL)
    await userEvent.click(await screen.findByRole('button', { name: 'Start live alliance selection' }))
    const form = await screen.findByRole('form', { name: "The event's rules" })
    await userEvent.click(within(form).getByRole('button', { name: 'Start with these rules' }))
    await waitFor(() => expect(api.writes()).toHaveLength(2))
    expect(api.writes()[1].body).toMatchObject({ event_key: EVENT, manual_rules: { n_alliances: 8,
      picks_per_alliance: 2, declined_team_may_become_captain: null } })
  })

  it('has no detectable accessibility violations on the recording board', async () => {
    mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft(), [`GET ${BASE}/5/recommendations`]: recs() })
    const { container } = renderAt(URL)
    await screen.findByRole('group', { name: 'Available teams' })
    await within(await screen.findByRole('region', { name: 'Your picks' })).findByText('24')
    expect(await axeViolations(container)).toEqual([])
  })

  it('lets a team be entered by number when the event\'s roster is not stored', async () => {
    const api = mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft({ available: [] }), [`GET ${BASE}/5/recommendations`]: recs(),
      [`POST ${BASE}/5/actions`]: draft({ record_seq: 3 }) })
    renderAt(URL)
    const form = await screen.findByRole('form', { name: 'Enter a team number' })
    expect(within(form).getByText(/not stored yet/)).toBeInTheDocument()
    await userEvent.type(within(form).getByRole('textbox'), '4567')
    await userEvent.click(within(form).getByRole('button', { name: 'Choose' }))
    await userEvent.click(screen.getByRole('button', { name: 'Alliance 1 picks 4567' }))
    await waitFor(() => expect(api.writes()).toHaveLength(1))
    expect(api.writes()[0].body).toMatchObject({ type: 'pick', seed: 1, team_number: 4567 })
  })

  it('is refused to a role without alliance_selection', async () => {
    mockApi({ 'GET /auth/session': SCOUTER, 'GET /events': EVENTS, ...SEASON_EVENTS })
    renderAt(URL)
    expect(await screen.findByText(/Your role does not include this page/)).toBeInTheDocument()
  })
})

// The page with a fast poll, for the refresh-failure test.
function ShellWithFastPoll() {
  return <Routes><Route path="/alliance-selection/live" element={<LiveDraftPage pollMs={150} />} /></Routes>
}

// --- Phase 11 follow-up: team profiles on the live draft page ---------------------------------------------------------

const MOMENT = '2099-03-03T15:59:00Z'
const PRIOR = '2099prior'

function strengthAt(team: number, event: string) {
  const view = strengthView(team)
  return { epa: EPA, strength: { ...view, event_key: event, as_of: MOMENT,
    scoring: { ...view.scoring, average_score: measure(event === PRIOR ? 41 : 55) },
    auto_points: { ...view.auto_points, season_by_event: [{ event_key: PRIOR, average_auto_points: measure(4) },
      { event_key: EVENT, average_auto_points: measure(6) }] } } }
}

const EVENT_MATCHES = { event_key: EVENT, as_of: MOMENT, validation: { status: 'descriptive', reasons: [] },
  matches: [
    { match_key: `${EVENT}_qm1`, competition_level: 'qualification', set_number: 1, match_number: 1,
      scheduled_time: '2099-03-03T10:00:00Z', red_team_numbers: [23, 2, 3], blue_team_numbers: [4, 5, 6],
      result: { score_red: 61, score_blue: 48, winning_alliance: 'red' }, result_withheld_reason: null },
    { match_key: `${EVENT}_qm2`, competition_level: 'qualification', set_number: 1, match_number: 2,
      scheduled_time: '2099-03-03T11:00:00Z', red_team_numbers: [7, 8, 9], blue_team_numbers: [23, 10, 11],
      result: { score_red: 70, score_blue: 52, winning_alliance: 'red' }, result_withheld_reason: null }] }

function profileRoutes(team: number) {
  return {
    [`GET /teams/${team}/events/${EVENT}/strength`]: strengthAt(team, EVENT),
    [`GET /teams/${team}/events/${PRIOR}/strength`]: strengthAt(team, PRIOR),
    [`GET /events/${EVENT}/matches`]: EVENT_MATCHES,
    [`GET /teams/${team}/events/${EVENT}/metrics`]: apiError(404, 'metrics_not_computed', 'not computed'),
  }
}

const RECS_WITH_MOMENT = recs({ provenance: { rule: 'P11-FB1', ordering_policy: 'ranking_xgb_v2',
  selection_moment: MOMENT } })

describe('team profiles on the live draft page', () => {
  it('opens a pool tile profile in a drawer without losing the selected tile, and returns focus on Escape', async () => {
    mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft(), [`GET ${BASE}/5/recommendations`]: RECS_WITH_MOMENT, ...profileRoutes(23) })
    renderAt(URL)
    const grid = await screen.findByRole('group', { name: 'Available teams' })
    await userEvent.click(within(grid).getByRole('button', { name: /^24/ }))
    const info = within(grid).getByRole('button', { name: 'Team 23 profile' })
    await userEvent.click(info)
    const drawer = await screen.findByRole('dialog', { name: 'Team 23' })
    expect(within(drawer).getByRole('button', { name: 'Close' })).toHaveFocus()
    expect(within(drawer).getByText(/Qualification rank:/)).toHaveTextContent('Qualification rank: 23')
    expect(await within(drawer).findByText(/Record:/)).toHaveTextContent('Record: 1–1–0 (won–lost–tied) in 2 played')
    // The board underneath is still mounted, with its selection and pending action.
    expect(within(grid).getByRole('button', { name: /^24/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Alliance 1 picks 24' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(info).toHaveFocus()
    expect(within(grid).getByRole('button', { name: /^24/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('reads every view strictly before the record selection moment and says so', async () => {
    const api = mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft({ can_record: false }), [`GET ${BASE}/5/recommendations`]: RECS_WITH_MOMENT,
      ...profileRoutes(23) })
    renderAt(URL)
    const picks = await screen.findByRole('region', { name: 'Your picks' })
    await userEvent.click(await within(picks).findByRole('button', { name: 'Team 23 profile' }))
    const drawer = await screen.findByRole('dialog', { name: 'Team 23' })
    await within(drawer).findByText(/Average alliance score by event/)
    const reads = api.calls.filter((c) => c.path.startsWith('/teams/23') || c.path === `/events/${EVENT}/matches`)
    expect(reads.map((c) => c.path).sort()).toEqual([`/events/${EVENT}/matches`, `/teams/23/events/${PRIOR}/strength`,
      `/teams/23/events/${EVENT}/strength`])
    for (const read of reads) expect(read.query.get('as_of')).toBe(MOMENT)
    expect(within(drawer).getByText(/As of the selection moment/)).toBeInTheDocument()
    expect(within(drawer).getByText('Backup 1.')).toBeInTheDocument()
    expect(within(drawer).getByText(/Position #2 in the team-strength ordering P11-FB1 uses \(ranking_xgb_v2\)/))
      .toBeInTheDocument()
    expect(within(drawer).getByText(/P11-FB1, orders teams by strength and does not project alliance scores/))
      .toBeInTheDocument()
    expect(within(drawer).getAllByText(/not enough scouting/)).toHaveLength(2)
  })

  it('opens from the alliances table, the unavailable chips and the history', async () => {
    const history = draft().history.map((h) => (h.type === 'captain' ? { ...h, team_number: 1, seed: 1 } : h))
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft({ can_record: false, history }), [`GET ${BASE}/5/recommendations`]: RECS_WITH_MOMENT,
      ...profileRoutes(1) })
    renderAt(URL)
    const alliances = await screen.findByRole('region', { name: 'Alliances' })
    for (const scope of [alliances, screen.getByRole('list', { name: 'Unavailable teams' }),
      screen.getByRole('region', { name: 'History' })]) {
      await userEvent.click(within(scope).getByRole('button', { name: 'Team 1 profile' }))
      const drawer = await screen.findByRole('dialog', { name: 'Team 1' })
      await userEvent.click(within(drawer).getByRole('button', { name: 'Close' }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    }
  })

  it('keeps focus inside the drawer and keeps polling with the stale notice visible', async () => {
    let reads = 0
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: () => { reads++; return draft({ can_record: false, record_seq: reads > 1 ? 3 : 2 }) },
      [`GET ${BASE}/5/recommendations`]: (r: { path: string }) => (reads > 1 ? new Promise(() => { void r })
        : RECS_WITH_MOMENT), ...profileRoutes(23) })
    render(<SessionProvider><AuthProvider><MemoryRouter initialEntries={[URL]}><ShellWithFastPoll /></MemoryRouter>
    </AuthProvider></SessionProvider>)
    const picks = await screen.findByRole('region', { name: 'Your picks' })
    await userEvent.click(await within(picks).findByRole('button', { name: 'Team 23 profile' }))
    const drawer = await screen.findByRole('dialog', { name: 'Team 23' })
    await within(drawer).findByText(/Average alliance score by event/)
    await userEvent.tab({ shift: true })
    expect(within(drawer).getByRole('link', { name: 'View full profile' })).toHaveFocus()
    await userEvent.tab()
    expect(within(drawer).getByRole('button', { name: 'Close' })).toHaveFocus()
    await waitFor(() => expect(within(drawer).getByText(/Board: record #3/)).toBeInTheDocument(), { timeout: 3000 })
    expect(within(drawer).getByText('(stale)')).toBeInTheDocument()
  })

  it('goes to the full profile and back with the selected tile and scroll position restored', async () => {
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    Object.defineProperty(window, 'scrollY', { value: 420, configurable: true })
    mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft(), [`GET ${BASE}/5/recommendations`]: RECS_WITH_MOMENT, ...profileRoutes(23) })
    renderAt(URL)
    const grid = await screen.findByRole('group', { name: 'Available teams' })
    await userEvent.click(within(grid).getByRole('button', { name: /^24/ }))
    await userEvent.click(within(grid).getByRole('button', { name: 'Team 23 profile' }))
    const drawer = await screen.findByRole('dialog', { name: 'Team 23' })
    const full = within(drawer).getByRole('link', { name: 'View full profile' })
    expect(full).toHaveAttribute('href',
      `/events/${EVENT}/teams/23?from=live-draft&event=${EVENT}&as_of=${encodeURIComponent(MOMENT)}`)
    await userEvent.click(full)
    expect(await screen.findByRole('heading', { level: 1, name: 'Team 23' })).toBeInTheDocument()
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true })
    await userEvent.click(screen.getByRole('link', { name: '← Back to live alliance selection' }))
    const back = await screen.findByRole('group', { name: 'Available teams' })
    expect(within(back).getByRole('button', { name: /^24/ })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 420))
  })

  it('shows no back link on a team page reached any other way', async () => {
    mockApi({ 'GET /auth/session': STRATEGY, 'GET /events': EVENTS, ...SEASON_EVENTS, ...profileRoutes(23) })
    renderAt(`/events/${EVENT}/teams/23`)
    expect(await screen.findByRole('heading', { level: 1, name: 'Team 23' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Back to live alliance selection/ })).not.toBeInTheDocument()
  })

  it('has no detectable accessibility violations with the drawer open', async () => {
    mockApi({ 'GET /auth/session': ADMIN, 'GET /events': EVENTS, ...SEASON_EVENTS, ...LISTED,
      [`GET ${BASE}/5`]: draft(), [`GET ${BASE}/5/recommendations`]: RECS_WITH_MOMENT, ...profileRoutes(23) })
    const { container } = renderAt(URL)
    const grid = await screen.findByRole('group', { name: 'Available teams' })
    await userEvent.click(within(grid).getByRole('button', { name: 'Team 23 profile' }))
    const drawer = await screen.findByRole('dialog', { name: 'Team 23' })
    await within(drawer).findByText(/Average alliance score by event/)
    expect(await axeViolations(container)).toEqual([])
  })
})
