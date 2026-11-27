import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Shell } from '../App'
import { SessionProvider } from '../state/session'
import { ADMIN_PERMISSIONS, ADMIN_SESSION, BASE_PERMISSIONS, BASE_SESSION } from '../test/auth'
import { axeViolations } from '../test/dashboard'
import { EVENT, EVENTS, TEAMS } from '../test/dashboardFixtures'
import { apiError, mockApi } from '../test/mockApi'
import { clearSeasonEvents } from '../workspace/events'
import { AuthProvider } from './AuthContext'
import type { SessionInfo } from './api'
import { landingFor, pageAllowed } from './roles'

// Team 11's accounts in the web app: the whole site behind sign-in, sign-up with the join code, sign-in and the role
// landing pages, password reset by code, what a base member may see, and Team Management. Synthetic data only.

// The synthetic season's events, for the event chooser and the headings that name the chosen event.
const SEASON_EVENTS = { 'GET /explorer/seasons/2099/events': [
  { event_key: '2099synth', name: 'Synthetic Test Event', event_code: 'synth', event_type: null, start_date: '2099-03-01',
    end_date: '2099-03-03', city: 'Testville', state_prov: 'NJ', country: 'USA', district: 'fma',
    district_name: 'FIRST Mid-Atlantic', matches: 1, matches_played: 0, teams: 6 }] }

const SIGNED_OUT: SessionInfo = { authenticated: false, access_policy: 'members', email_delivery_configured: true,
  signup_open: true }

const OVERVIEW = { team_number: 11, team_name: 'MORT', verification_status: 'verified',
  verified_at: '2026-11-01T10:00:00Z', created_at: '2026-11-01T09:00:00Z',
  settings: { default_event_key: '2099synth', scouting_instructions: 'Watch the defense closely.' },
  active_members: 2, role: 'admin', role_label: 'Administrator', permissions: ADMIN_PERMISSIONS }
const ANALYTICS = { members_by_role: { admin: { active: 1, suspended: 0 }, base: { active: 1, suspended: 0 } },
  active_last_7_days: 2, never_signed_in: 0, scouting: { reports: 4, reports_last_7_days: 2, events: 1,
    open_assignments: 1, completed_assignments: 1, top_scouts: [{ name: 'Ada Admin', reports: 4 }] } }
const MEMBERS = {
  members: [
    { membership_id: 1, user_id: 1, name: 'Ada Admin', email: 'ada@example.test', role: 'admin',
      role_label: 'Administrator', status: 'active', last_login_at: '2026-11-01T10:00:00Z',
      joined_at: '2026-11-01T09:00:00Z', is_self: true },
    { membership_id: 2, user_id: 2, name: 'Bo Base', email: 'bo@example.test', role: 'base', role_label: 'Member',
      status: 'active', last_login_at: null, joined_at: '2026-11-01T09:30:00Z', is_self: false },
  ],
}
const MATCHES = { as_of: '2026-11-01T00:00:00Z', event_key: '2099synth', validation: {}, matches: [
  { match_key: '2099synth_qm1', competition_level: 'qualification', set_number: 1, match_number: 1,
    scheduled_time: '2099-03-01T10:00:00Z', red_team_numbers: [9001, 9002, 9003], blue_team_numbers: [9004, 9005, 9006],
    result: null, result_withheld_reason: 'not_played' },
] }
// What the admin landing page (/team) and the events page (/) read.
// What every member reads from the team's settings (Our events, the current event, the instructions for scouters).
const TEAM_EVENTS = { team_events: [{ event_key: '2099synth', name: 'Synthetic Regional', start_date: '2099-03-01',
  end_date: '2099-03-03', status: 'upcoming' }], pinned_event_key: null, current_event_key: '2099synth',
  current_reason: 'next', scouting_instructions: 'Watch the defense closely.' }

const LANDING = { 'GET /workspace': OVERVIEW, 'GET /workspace/team-events': TEAM_EVENTS, 'GET /workspace/analytics': ANALYTICS, 'GET /events': EVENTS,
  ...SEASON_EVENTS }

function renderApp(url: string) {
  return render(
    <SessionProvider><AuthProvider><MemoryRouter initialEntries={[url]}><Shell /></MemoryRouter></AuthProvider></SessionProvider>,
  )
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); clearSeasonEvents() })

describe('roles', () => {
  it('lets a base member open only the events list, an event page and their account', () => {
    for (const path of ['/', '/?season=2026', '/events/2026njfla', '/events/2026njfla?tab=teams', '/account']) {
      expect(pageAllowed('base', path, BASE_PERMISSIONS)).toBe(true)
    }
    for (const path of ['/team', '/explorer', '/status', '/inputs', '/events/2026njfla/teams/11',
      '/alliance-selection/live', '/matches/2026njfla_qm1', '/report/2026njfla_qm1', '/drive-team']) {
      expect(pageAllowed('base', path, BASE_PERMISSIONS)).toBe(false)
      expect(pageAllowed('admin', path)).toBe(true)
    }
  })

  it('no longer has the old standalone alliance selection page (removed 2026-11-26; live alliance selection replaces it)', () => {
    expect(pageAllowed('strategy', '/events/2026njfla/alliance-selection',
      [...BASE_PERMISSIONS, 'alliance_selection', 'strategy_tools'])).toBe(false)
  })

  it('opens each new role the pages its permissions allow, and nothing that manages the team', () => {
    const drive = [...BASE_PERMISSIONS, 'match_predictions', 'team_analytics', 'match_plan_view']
    const scout = [...BASE_PERMISSIONS, 'scouting_forms', 'scouting_submit']
    const strategy = [...drive, 'strategy_tools', 'alliance_selection', 'alliance_selection_record', 'scouting_view',
      'scouting_assign']
    for (const path of ['/drive-team', '/events/2026njfla/teams/11', '/matches/2026njfla_qm1']) {
      expect(pageAllowed('drive', path, drive)).toBe(true)
    }
    for (const path of ['/alliance-selection/live', '/report/2026njfla_qm1', '/scouting', '/team']) {
      expect(pageAllowed('drive', path, drive)).toBe(false)
    }
    expect(pageAllowed('scout', '/scouting', scout)).toBe(true)
    expect(pageAllowed('scout', '/drive-team', scout)).toBe(false)
    for (const path of ['/alliance-selection/live', '/events/2026njfla/strategy-lab',
      '/report/2026njfla_qm1', '/drive-team']) {
      expect(pageAllowed('strategy', path, strategy)).toBe(true)
    }
    for (const path of ['/team', '/explorer', '/status', '/inputs']) expect(pageAllowed('strategy', path, strategy)).toBe(false)
    expect(landingFor('drive', null, drive)).toBe('/drive-team')
    expect(landingFor('scout', null, scout)).toBe('/scouting')
  })

  it('follows next after sign-in only when the role may open it', () => {
    expect(landingFor('admin', null)).toBe('/team')
    expect(landingFor('base', null, BASE_PERMISSIONS)).toBe('/')
    expect(landingFor('base', '/events/2099synth', BASE_PERMISSIONS)).toBe('/events/2099synth')
    expect(landingFor('base', '/team', BASE_PERMISSIONS)).toBe('/')
    expect(landingFor('admin', '/explorer')).toBe('/explorer')
    expect(landingFor('admin', '//evil.example')).toBe('/team')
  })
})

describe('signed out', () => {
  it.each(['/', '/events/2099synth', '/team', '/explorer', '/status', '/account'])(
    'sends a visitor at %s to sign in, with next', async (path) => {
      mockApi({ 'GET /auth/session': SIGNED_OUT })
      renderApp(path)
      expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
      const nav = screen.getByRole('navigation', { name: 'Main' })
      expect(within(nav).queryAllByRole('link')).toEqual([])
    })

  it('forwards /auth to the sign-in page', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT })
    renderApp('/auth')
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  })

  it('has no accessibility violations on the sign-in page', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT })
    const { container } = renderApp('/auth/login')
    await screen.findByRole('heading', { name: 'Log in' })
    expect(await axeViolations(container, { region: true })).toEqual([])
  })

  it('says so when the API answering predates accounts (its /auth/session is a 404)', async () => {
    mockApi({}) // every route unmocked: GET /auth/session answers the unmatched-route 404, as an older API does
    renderApp('/auth/login')
    expect(await screen.findByText(/This StratAI server does not have accounts yet/)).toBeInTheDocument()
  })

  it("says so when the server's database lacks the account migrations", async () => {
    mockApi({ 'GET /auth/session': { ...SIGNED_OUT, accounts_available: false } })
    renderApp('/auth/signup')
    expect(await screen.findByText(/Accounts are not set up on this server/)).toBeInTheDocument()
    expect(screen.getByText('0015_single_team_auth.sql')).toBeInTheDocument()
  })

  it('has no registration, invitation or team-number fields anywhere', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT })
    for (const path of ['/auth/login', '/auth/signup', '/auth/forgot', '/auth/reset']) {
      const { unmount } = renderApp(path)
      await screen.findByRole('main')
      await waitFor(() => expect(screen.queryByText(/Checking your sign-in/)).not.toBeInTheDocument())
      expect(screen.queryByLabelText(/team number/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/Register/)).not.toBeInTheDocument()
      unmount()
    }
    for (const path of ['/auth/register', '/auth/invite']) {
      const { unmount } = renderApp(path)
      expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument() // not a public page
      unmount()
    }
  })
})

describe('sign-up', () => {
  async function fill(code: string, password = 'eight888', confirm = password) {
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Full name'), 'Bo Base')
    await user.type(screen.getByLabelText('Email address'), 'Bo@Example.test')
    await user.type(screen.getByLabelText(/^Password/), password)
    await user.type(screen.getByLabelText('Confirm password'), confirm)
    await user.type(screen.getByLabelText(/^Team join code/), code)
    await user.click(screen.getByRole('button', { name: 'Create account' }))
  }

  it('creates the account with the join code, signs in and opens the events for a base member', async () => {
    const api = mockApi({ 'GET /auth/session': SIGNED_OUT, 'POST /auth/signup': { status: 201, body: BASE_SESSION },
      ...LANDING })
    renderApp('/auth/signup')
    await fill('the-code')
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
    const signup = api.writes().find((c) => c.path === '/auth/signup')!
    expect(signup.body).toEqual({ full_name: 'Bo Base', email: 'Bo@Example.test', password: 'eight888',
      join_code: 'the-code' })
    expect(signup.headers['X-StratAI-CSRF']).toBe('1')
  })

  it('opens the team page when the API makes the account an administrator (ADMIN_EMAILS)', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT, 'POST /auth/signup': { status: 201, body: ADMIN_SESSION }, ...LANDING })
    renderApp('/auth/signup')
    await fill('the-code')
    expect(await screen.findByRole('heading', { name: 'Team' })).toBeInTheDocument()
  })

  it('shows a clear error for a wrong join code', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT, 'POST /auth/signup': apiError(403, 'invalid_join_code',
      "That team join code is not correct. Ask one of the team's administrators for it.") })
    renderApp('/auth/signup')
    await fill('wrong-code')
    expect(await screen.findByText(/That team join code is not correct/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
  })

  it('checks the password (8 characters, matching) before calling the API', async () => {
    const api = mockApi({ 'GET /auth/session': SIGNED_OUT })
    renderApp('/auth/signup')
    await fill('the-code', 'seven77')
    expect(await screen.findByText('Use at least 8 characters.')).toBeInTheDocument()
    expect(api.writes()).toEqual([])
  })

  it('says sign-up is closed when no join code is configured', async () => {
    mockApi({ 'GET /auth/session': { ...SIGNED_OUT, signup_open: false } })
    renderApp('/auth/signup')
    expect(await screen.findByText(/Sign-up is not open on this server/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create account' })).toBeDisabled()
  })
})

describe('sign-in', () => {
  async function logIn() {
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email address'), 'x@example.test')
    await user.type(screen.getByLabelText('Password'), 'member passphrase')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
  }

  it.each([
    ['an administrator', ADMIN_SESSION, 'Team'],
    ['a base member', BASE_SESSION, 'Events'],
  ])('sends %s to their home page, with email and password only', async (_who, session, heading) => {
    const api = mockApi({ 'GET /auth/session': SIGNED_OUT, 'POST /auth/login': session, ...LANDING })
    renderApp('/auth/login')
    await logIn()
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
    expect(api.writes()[0].body).toEqual({ email: 'x@example.test', password: 'member passphrase' })
  })

  it("does not follow next to a page a base member's role cannot open", async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT, 'POST /auth/login': BASE_SESSION, ...LANDING })
    renderApp('/auth/login?next=%2Fteam')
    await logIn()
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
  })

  it('shows the API refusal for wrong credentials', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT,
      'POST /auth/login': apiError(401, 'invalid_credentials', 'The email or password is not correct.') })
    renderApp('/auth/login')
    await logIn()
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid_credentials')
  })
})

describe('password reset by code', () => {
  it('asks for a code by email, then sets a new password with it and signs in', async () => {
    const api = mockApi({ 'GET /auth/session': SIGNED_OUT,
      'POST /auth/password/forgot': { status: 202, body: { accepted: true, email_delivery_configured: true } },
      'POST /auth/password/reset': BASE_SESSION, ...LANDING })
    renderApp('/auth/forgot')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email address'), 'bo@example.test')
    await user.click(screen.getByRole('button', { name: 'Send code' }))
    expect(await screen.findByText(/a 6-digit code is on its way/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Enter the code' }))
    expect(await screen.findByLabelText('Email address')).toHaveValue('bo@example.test')
    await user.type(screen.getByLabelText(/^6-digit code/), '012345')
    await user.type(screen.getByLabelText(/^New password/, { selector: 'input' }), 'new pass 1')
    await user.type(screen.getByLabelText('Confirm new password'), 'new pass 1')
    await user.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
    expect(api.writes().map((c) => c.body)).toEqual([
      { email: 'bo@example.test' },
      { email: 'bo@example.test', code: '012345', new_password: 'new pass 1' },
    ])
    // The code travels only in a request body, never in a URL.
    expect(api.calls.every((c) => !c.path.includes('012345') && !c.query.toString().includes('012345'))).toBe(true)
  })

  it('refuses a code that is not 6 digits before calling the API', async () => {
    const api = mockApi({ 'GET /auth/session': SIGNED_OUT })
    renderApp('/auth/reset')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email address'), 'bo@example.test')
    await user.type(screen.getByLabelText(/^6-digit code/), '123')
    await user.type(screen.getByLabelText(/^New password/, { selector: 'input' }), 'new pass 1')
    await user.type(screen.getByLabelText('Confirm new password'), 'new pass 1')
    await user.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByText('Enter the 6-digit code from the email.')).toBeInTheDocument()
    expect(api.writes()).toEqual([])
  })

  it('shows the refusal for a wrong, expired or used code', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT, 'POST /auth/password/reset': apiError(410, 'reset_code_invalid',
      'That code is not correct, has expired or was already used. Ask for a new code.') })
    renderApp('/auth/reset')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email address'), 'bo@example.test')
    await user.type(screen.getByLabelText(/^6-digit code/), '999999')
    await user.type(screen.getByLabelText(/^New password/, { selector: 'input' }), 'new pass 1')
    await user.type(screen.getByLabelText('Confirm new password'), 'new pass 1')
    await user.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByText(/has expired or was already used/)).toBeInTheDocument()
  })
})

describe('what a base member sees', () => {
  it('shows only Events in the navigation, and no write-token bar', async () => {
    mockApi({ 'GET /auth/session': BASE_SESSION, ...LANDING })
    renderApp('/?season=2099')
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Events'])
    expect(screen.queryByLabelText('Write token')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Account' })).toBeInTheDocument()
  })

  it.each(['/team', '/explorer', '/status', '/inputs', '/drive-team', `/events/${EVENT}/strategy-lab`,
    `/matches/${EVENT}_qm1`])('refuses %s without loading it', async (path) => {
    const api = mockApi({ 'GET /auth/session': BASE_SESSION })
    renderApp(path)
    expect(await screen.findByText(/Your role does not include this page/)).toBeInTheDocument()
    // Nothing of the page is requested (the app-wide write-access probe of the session bar is not page data).
    expect(api.calls.map((c) => c.path).filter((path) => path !== '/human-inputs/write-access'))
      .toEqual(['/auth/session'])
  })

  it("shows an event's teams as plain text, with no links to pages it cannot open", async () => {
    mockApi({ 'GET /auth/session': BASE_SESSION, 'GET /events': EVENTS, [`GET /events/${EVENT}/teams`]: TEAMS })
    renderApp(`/events/${EVENT}?tab=teams`)
    const team = String(TEAMS.teams[0].team_number)
    expect(await screen.findByText(team)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: team })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Alliance selection' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Strategy lab' })).not.toBeInTheDocument()
  })
})

describe('administrators', () => {
  it('get the team page and the full navigation', async () => {
    mockApi({ 'GET /auth/session': ADMIN_SESSION, ...LANDING })
    renderApp('/team')
    expect(await screen.findByRole('heading', { name: 'Team' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    for (const name of ['Events', 'Team', 'Drive team', 'Scouting', 'System status', 'Historical seasons',
      'Inputs overview']) {
      expect(within(nav).getByRole('link', { name })).toBeInTheDocument()
    }
    expect(screen.queryByRole('tab', { name: 'Permissions' })).not.toBeInTheDocument()
  })

  it('see an event with its team links', async () => {
    mockApi({ 'GET /auth/session': ADMIN_SESSION, 'GET /events': EVENTS, [`GET /events/${EVENT}/teams`]: TEAMS })
    renderApp(`/events/${EVENT}?tab=teams`)
    const team = String(TEAMS.teams[0].team_number)
    expect(await screen.findByRole('link', { name: team })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Live alliance selection' }))
      .toHaveAttribute('href', `/alliance-selection/live?event=${EVENT}`)
  })
})

describe('the write-token bar after sign-in', () => {
  it('checks write access again once an administrator has signed in, instead of showing the API as unreachable',
    async () => {
      let signedIn = false
      mockApi({
        'GET /auth/session': () => (signedIn ? ADMIN_SESSION : SIGNED_OUT),
        'POST /auth/login': () => { signedIn = true; return ADMIN_SESSION },
        // A members-only API refuses the check until someone allowed is signed in.
        'GET /human-inputs/write-access': () => (signedIn ? { writes_enabled: false, token_accepted: false }
          : apiError(401, 'not_authenticated', 'Sign in to StratAI to continue.')),
        ...LANDING,
      })
      renderApp('/auth/login?next=%2F%3Fseason%3D2099')
      const user = userEvent.setup()
      await user.type(await screen.findByLabelText('Email address'), 'ada@example.test')
      await user.type(screen.getByLabelText('Password'), 'member passphrase')
      await user.click(screen.getByRole('button', { name: 'Log in' }))
      expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
      await waitFor(() => expect(screen.getByTestId('access')).toHaveTextContent('writes disabled on server'))
    })
})

describe('Team Management', () => {
  it('lists the members, filters them, and says how new members join', async () => {
    mockApi({ 'GET /auth/session': ADMIN_SESSION, 'GET /workspace/members': MEMBERS })
    renderApp('/team?tab=members')
    const table = await screen.findByRole('table')
    expect(within(table).getByText('Bo Base')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '/auth/signup' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add Team Member|Reset password|invitation/i })).not.toBeInTheDocument()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Search'), 'ada')
    expect(within(table).queryByText('Bo Base')).not.toBeInTheDocument()
  })

  it('changes a role, and removes a member after confirmation', async () => {
    const api = mockApi({ 'GET /auth/session': ADMIN_SESSION, 'GET /workspace/members': MEMBERS,
      'POST /workspace/members/2/role': { membership_id: 2, role: 'admin' },
      'POST /workspace/members/2/remove': { membership_id: 2, status: 'removed' } })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp('/team?tab=members')
    const user = userEvent.setup()
    const roles = await screen.findByLabelText('Role of Bo Base')
    expect(within(roles).getAllByRole('option').map((o) => o.textContent)).toEqual(['Administrator', 'Strategy team', 'Drive team', 'Scout', 'Member'])
    await user.selectOptions(roles, 'admin')
    await waitFor(() => expect(api.writes().find((c) => c.path === '/workspace/members/2/role')!.body)
      .toEqual({ role: 'admin' }))
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(api.writes().some((c) => c.path === '/workspace/members/2/remove')).toBe(true))
    // An administrator cannot change their own role here.
    expect(screen.queryByLabelText('Role of Ada Admin')).not.toBeInTheDocument()
  })
})

describe('admin dashboards', () => {
  it('let an administrator submit a scouting report for an assignment', async () => {
    const assignment = { assignment_id: 5, event_key: '2099synth', match_key: '2099synth_qm1',
      competition_level: 'qualification', set_number: 1, match_number: 1, scheduled_time: '2099-03-01T10:00:00Z',
      team_number: 9002, alliance_color: 'red', assigned_user_id: 1, assigned_to: 'Ada Admin', status: 'assigned',
      created_at: '2026-11-01T00:00:00Z', report_submitted: false }
    const api = mockApi({
      'GET /auth/session': ADMIN_SESSION, 'GET /workspace': OVERVIEW, 'GET /workspace/team-events': TEAM_EVENTS,
      ...SEASON_EVENTS, 'GET /workspace/scouting/assignments': [assignment], 'GET /workspace/scouting/reports': [],
      'GET /workspace/scouting/scouts': [], 'GET /workspace/scouting/summary': { event_key: '2099synth', teams: [],
        source: '', method: '' },
      'GET /events/2099synth/matches': MATCHES,
      'GET /events/2099synth/teams': { event_key: '2099synth', teams: [{ team_number: 9002, name: 'Synthetic Two',
        city: null, country: null, rookie_year: null, state_province: null }], validation: {} },
      'POST /workspace/scouting/reports': { status: 201, body: { report_id: 1 } },
    })
    renderApp('/scouting')
    expect(await screen.findByText('Watch the defense closely.')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Scout this' }))
    await waitFor(() => expect(screen.getByLabelText('Team')).toHaveValue('9002'))
    await user.selectOptions(screen.getByLabelText('Defense (0–5)'), '4')
    await user.click(screen.getByRole('button', { name: 'Submit report' }))
    await waitFor(() => expect(api.writes()).toHaveLength(1))
    expect(api.writes()[0].body).toEqual({ match_key: '2099synth_qm1', team_number: 9002, defense_rating: 4,
      feeding_rating: null, notes: null, assignment_id: 5 })
  })
})

describe('our events and the new roles', () => {
  const DRIVE_SESSION: SessionInfo = { ...BASE_SESSION, user: { id: 3, name: 'Dee Drive', email: 'drive@example.test' },
    role: 'drive', role_label: 'Drive team', permissions: [...BASE_PERMISSIONS, 'match_predictions', 'team_analytics',
      'match_plan_view'] }

  it('lists our events first on the events page and marks them in the full list', async () => {
    mockApi({ 'GET /auth/session': BASE_SESSION, 'GET /events': EVENTS, 'GET /workspace/team-events': TEAM_EVENTS })
    renderApp('/?season=2099')
    const ours = await screen.findByRole('region', { name: 'Our events' })
    expect(within(ours).getByRole('link', { name: 'Synthetic Regional' })).toHaveAttribute('href', '/events/2099synth')
    expect(within(ours).getByText(/current/)).toBeInTheDocument()
  })

  it('sends the drive team to their page, on the current event, with our events one tap away', async () => {
    mockApi({ 'GET /auth/session': DRIVE_SESSION, 'GET /workspace/team-events': TEAM_EVENTS, ...SEASON_EVENTS,
      'GET /events/2099synth/matches': MATCHES })
    renderApp('/home')
    expect(await screen.findByRole('heading', { name: 'Drive team' })).toBeInTheDocument()
    const switcher = await screen.findByRole('group', { name: 'Our events' })
    expect(within(switcher).getByRole('button', { name: /Synthetic Regional/ })).toHaveAttribute('aria-pressed', 'true')
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Drive team' })).toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Team' })).not.toBeInTheDocument()
    expect(within(nav).queryByText('Admin')).not.toBeInTheDocument()
  })
})
