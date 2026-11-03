import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Shell } from '../App'
import { SessionProvider } from '../state/session'
import { axeViolations } from '../test/dashboard'
import { EVENTS } from '../test/dashboardFixtures'
import { apiError, mockApi } from '../test/mockApi'
import { clearSeasonEvents } from '../workspace/events'
import { AuthProvider } from './AuthContext'
import type { SessionInfo } from './api'

// Team workspaces in the web app: the landing button, registration, sign-in and role redirects, invitations, the
// Admin Dashboard, permissions, the role dashboards and the members-only policy. Synthetic fixture data only.

// The synthetic season's events, for the event chooser and the headings that name the chosen event.
const SEASON_EVENTS = { 'GET /explorer/seasons/2099/events': [
  { event_key: '2099synth', name: 'Synthetic Test Event', event_code: 'synth', event_type: null, start_date: '2099-03-01',
    end_date: '2099-03-03', city: 'Testville', state_prov: 'NJ', country: 'USA', district: 'fma',
    district_name: 'FIRST Mid-Atlantic', matches: 1, matches_played: 0, teams: 6 }] }

const SIGNED_OUT: SessionInfo = { authenticated: false, access_policy: 'open', email_delivery_configured: false }
const ALL_ADMIN = ['team_info', 'match_predictions', 'team_analytics', 'event_analysis', 'qualification_forecast',
  'alliance_selection', 'strategy_tools', 'scouting_forms', 'scouting_submit', 'scouting_view', 'scouting_assign',
  'team_management', 'manage_permissions', 'team_settings', 'activity_log']

function signedIn(role: 'admin' | 'strategy' | 'scouter', permissions: string[],
  status: 'verified' | 'pending_verification' = 'verified'): SessionInfo {
  return { authenticated: true, access_policy: 'open', email_delivery_configured: false,
    user: { id: 1, name: role === 'admin' ? 'Ada Admin' : 'Sam Scout', email: `${role}@example.test` },
    workspace: { team_number: 9999, team_name: 'Synthetic Robotics', verification_status: status }, role,
    role_label: role, permissions }
}
const ADMIN = signedIn('admin', ALL_ADMIN)
const STRATEGY = signedIn('strategy', ['team_info', 'match_predictions', 'team_analytics', 'event_analysis',
  'qualification_forecast', 'alliance_selection', 'strategy_tools', 'scouting_forms', 'scouting_view',
  'scouting_assign'])
const SCOUTER = signedIn('scouter', ['team_info', 'scouting_forms', 'scouting_submit'])

const OVERVIEW = { team_number: 9999, team_name: 'Synthetic Robotics', verification_status: 'verified',
  verified_at: '2026-11-01T10:00:00Z', created_at: '2026-11-01T09:00:00Z',
  settings: { default_event_key: '2099synth', scouting_instructions: 'Watch the defense closely.' },
  active_members: 3, role: 'admin', role_label: 'Administrator', permissions: ALL_ADMIN }
const ANALYTICS = { members_by_role: { admin: { active: 1, suspended: 0 }, strategy: { active: 1, suspended: 0 },
  scouter: { active: 1, suspended: 0 } }, active_last_7_days: 3, never_signed_in: 0, pending_invitations: 1,
  expired_invitations: 0, scouting: { reports: 4, reports_last_7_days: 2, events: 1, open_assignments: 1,
    completed_assignments: 1, top_scouts: [{ name: 'Sam Scout', reports: 4 }] } }
const MEMBERS = {
  members: [
    { membership_id: 1, user_id: 1, name: 'Ada Admin', email: 'ada@example.test', role: 'admin', role_label: 'Administrator',
      status: 'active', invitation_status: 'accepted', last_login_at: '2026-11-01T10:00:00Z',
      joined_at: '2026-11-01T09:00:00Z', is_self: true },
    { membership_id: 2, user_id: 2, name: 'Sam Scout', email: 'sam@example.test', role: 'scouter', role_label: 'Scouter',
      status: 'active', invitation_status: 'accepted', last_login_at: null, joined_at: '2026-11-01T09:30:00Z',
      is_self: false },
  ],
  invitations: [{ invitation_id: 7, email: 'pat@example.test', name: 'Pat Pending', role: 'strategy',
    role_label: 'Drive team / strategy', expires_at: '2099-01-01T00:00:00Z', invited_at: '2026-11-01T11:00:00Z',
    invited_by: 'Ada Admin', invitation_status: 'pending' }],
}
const MATCHES = { as_of: '2026-11-01T00:00:00Z', event_key: '2099synth', validation: {}, matches: [
  { match_key: '2099synth_qm1', competition_level: 'qualification', set_number: 1, match_number: 1,
    scheduled_time: '2099-03-01T10:00:00Z', red_team_numbers: [9001, 9002, 9003], blue_team_numbers: [9004, 9005, 9006],
    result: null, result_withheld_reason: 'not_played' },
] }

function renderApp(url: string) {
  return render(
    <SessionProvider><AuthProvider><MemoryRouter initialEntries={[url]}><Shell /></MemoryRouter></AuthProvider></SessionProvider>,
  )
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); clearSeasonEvents() })

describe('signed out', () => {
  it('shows the Login / Register button on the landing page and opens the two choices', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT, 'GET /events': EVENTS })
    renderApp('/?season=2099')
    const buttons = await screen.findAllByRole('link', { name: "Login / Register to Your Team's StratAI" })
    expect(buttons.length).toBeGreaterThanOrEqual(1)
    await userEvent.click(buttons[0])
    expect(await screen.findByRole('heading', { name: 'Register a New Team' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Log In to an Existing Team' })).toBeInTheDocument()
  })

  it('has no accessibility violations on the sign-in choice', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT })
    const { container } = renderApp('/auth')
    await screen.findByRole('heading', { name: 'Register a New Team' })
    expect(await axeViolations(container, { region: true })).toEqual([])
  })

  it('says so when the API answering predates team accounts (its /auth/session is a 404)', async () => {
    mockApi({}) // every route unmocked: GET /auth/session answers the unmatched-route 404, as an older API does
    renderApp('/auth/register')
    expect(await screen.findByText(/This StratAI server does not have team accounts yet/)).toBeInTheDocument()
    expect(screen.getByText(/running\s+an older version of StratAI/)).toBeInTheDocument()
  })

  it("says so when the server's database lacks the team-account migration", async () => {
    mockApi({ 'GET /auth/session': { ...SIGNED_OUT, accounts_available: false } })
    renderApp('/auth/login')
    expect(await screen.findByText(/Team accounts are not set up on this server/)).toBeInTheDocument()
    expect(screen.getByText('0012_team_workspaces.sql')).toBeInTheDocument()
  })

  it('shows no such notice when the server is ready for accounts', async () => {
    mockApi({ 'GET /auth/session': { ...SIGNED_OUT, accounts_available: true } })
    renderApp('/auth/register')
    expect(await screen.findByRole('heading', { name: 'Register a new team' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('sends a visitor to sign in when the server is members-only', async () => {
    mockApi({ 'GET /auth/session': { ...SIGNED_OUT, access_policy: 'members' } })
    renderApp('/events/2099synth')
    expect(await screen.findByRole('heading', { name: 'Log in to your team' })).toBeInTheDocument()
  })
})

describe('registration', () => {
  it('registers a team, creates the first administrator and opens the Admin Dashboard', async () => {
    const api = mockApi({
      'GET /auth/session': SIGNED_OUT,
      'POST /auth/teams/register': { status: 201, body: { team_number: 9999, team_name: 'Synthetic Robotics',
        verification_status: 'pending_verification', known_frc_team: false, frc_team_name: null } },
      'POST /auth/teams/initial-admin': { status: 201, body: signedIn('admin', ALL_ADMIN, 'pending_verification') },
      'GET /workspace': { ...OVERVIEW, verification_status: 'pending_verification' },
      'GET /workspace/analytics': ANALYTICS,
    })
    renderApp('/auth/register')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('FRC team number'), '9999')
    await user.type(screen.getByLabelText('Team name'), 'Synthetic Robotics')
    await user.type(screen.getByLabelText(/^Team setup password/), 'setup passphrase 1')
    await user.type(screen.getByLabelText('Confirm the setup password'), 'setup passphrase 1')
    await user.click(screen.getByRole('button', { name: 'Register team' }))
    expect(await screen.findByText(/is registered and/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Full name'), 'Ada Admin')
    await user.type(screen.getByLabelText('Email address'), 'ada@example.test')
    await user.type(screen.getByLabelText(/^Password/), 'admin passphrase 1')
    await user.type(screen.getByLabelText('Confirm password'), 'admin passphrase 1')
    await user.click(screen.getByRole('button', { name: /Create account/ }))
    expect(await screen.findByRole('heading', { name: 'Admin Dashboard' })).toBeInTheDocument()
    expect(screen.getAllByText(/Pending verification/).length).toBeGreaterThan(0)
    const admin = api.writes().find((c) => c.path === '/auth/teams/initial-admin')!
    expect(admin.body).toEqual({ team_number: 9999, setup_password: 'setup passphrase 1', full_name: 'Ada Admin',
      email: 'ada@example.test', password: 'admin passphrase 1' })
    for (const write of api.writes()) expect(write.headers['X-StratAI-CSRF']).toBe('1')
  })

  it('refuses mismatched setup passwords before calling the API', async () => {
    const api = mockApi({ 'GET /auth/session': SIGNED_OUT })
    renderApp('/auth/register')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('FRC team number'), '9999')
    await user.type(screen.getByLabelText('Team name'), 'X')
    await user.type(screen.getByLabelText(/^Team setup password/), 'setup passphrase 1')
    await user.type(screen.getByLabelText('Confirm the setup password'), 'setup passphrase 2')
    await user.click(screen.getByRole('button', { name: 'Register team' }))
    expect(await screen.findByText('The two passwords do not match.')).toBeInTheDocument()
    expect(api.writes()).toEqual([])
  })
})

describe('sign-in', () => {
  it.each([
    ['admin', ADMIN, 'Admin Dashboard'],
    ['strategy', STRATEGY, 'Drive team dashboard'],
    ['scouter', SCOUTER, 'Scouting dashboard'],
  ])('sends a %s to their own dashboard', async (_role, session, heading) => {
    mockApi({
      'GET /auth/session': SIGNED_OUT, 'POST /auth/login': session,
      'GET /workspace': OVERVIEW, ...SEASON_EVENTS, 'GET /workspace/analytics': ANALYTICS,
      'GET /workspace/scouting/assignments': [], 'GET /workspace/scouting/reports': [],
      'GET /workspace/scouting/summary': { event_key: '2099synth', teams: [], source: '', method: '' },
      'GET /workspace/scouting/scouts': [], 'GET /events/2099synth/matches': MATCHES,
      'GET /events/2099synth/teams': { event_key: '2099synth', teams: [], validation: {} },
    })
    renderApp('/auth/login')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('FRC team number'), '9999')
    await user.type(screen.getByLabelText('Email address'), 'x@example.test')
    await user.type(screen.getByLabelText('Password'), 'member passphrase 1')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
  })

  it('shows the API refusal for wrong credentials', async () => {
    mockApi({ 'GET /auth/session': SIGNED_OUT,
      'POST /auth/login': apiError(401, 'invalid_credentials', 'The team number, email or password is not correct.') })
    renderApp('/auth/login')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('FRC team number'), '9999')
    await user.type(screen.getByLabelText('Email address'), 'x@example.test')
    await user.type(screen.getByLabelText('Password'), 'wrong passphrase 1')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid_credentials')
  })

  it('accepts an invitation from the link fragment and opens the role dashboard', async () => {
    const api = mockApi({
      'GET /auth/session': SIGNED_OUT,
      'POST /auth/invitations/preview': { team_number: 9999, team_name: 'Synthetic Robotics', email: 'sam@example.test',
        full_name: 'Sam Scout', role: 'scouter', role_label: 'Scouter', expires_at: '2099-01-01T00:00:00Z',
        existing_account: false },
      'POST /auth/invitations/accept': { status: 201, body: SCOUTER },
      'GET /workspace': OVERVIEW, ...SEASON_EVENTS, 'GET /workspace/scouting/assignments': [], 'GET /workspace/scouting/reports': [],
      'GET /events/2099synth/matches': MATCHES, 'GET /events/2099synth/teams': { event_key: '2099synth', teams: [],
        validation: {} },
    })
    renderApp('/auth/invite#token=secret-token-value')
    expect(await screen.findByText(/You are invited to team/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/^Choose a password/), 'scout passphrase 1')
    await user.type(screen.getByLabelText('Confirm password'), 'scout passphrase 1')
    await user.click(screen.getByRole('button', { name: 'Create my account' }))
    expect(await screen.findByRole('heading', { name: 'Scouting dashboard' })).toBeInTheDocument()
    expect(api.calls.find((c) => c.path === '/auth/invitations/preview')!.body).toEqual({ token: 'secret-token-value' })
    // The token travels only in request bodies, never in a URL.
    expect(api.calls.every((c) => !c.path.includes('secret-token-value') && !c.query.toString().includes('secret'))).toBe(true)
  })
})

describe('navigation and permissions', () => {
  it('shows Team Management only to administrators and blocks it for a scouter', async () => {
    mockApi({ 'GET /auth/session': SCOUTER, 'GET /workspace': OVERVIEW, ...SEASON_EVENTS, 'GET /workspace/scouting/assignments': [],
      'GET /workspace/scouting/reports': [] })
    renderApp('/team')
    expect(await screen.findByText(/Your role does not include this page/)).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).queryByRole('link', { name: 'Team Management' })).not.toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Scouting' })).toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Inputs overview' })).not.toBeInTheDocument()
  })

  it('gives an administrator the Team Management tab and the full navigation', async () => {
    mockApi({ 'GET /auth/session': ADMIN, 'GET /workspace': OVERVIEW, ...SEASON_EVENTS, 'GET /workspace/analytics': ANALYTICS })
    renderApp('/team')
    expect(await screen.findByRole('heading', { name: 'Admin Dashboard' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    for (const name of ['Events', 'Team Management', 'Drive team', 'Scouting', 'Inputs overview']) {
      expect(within(nav).getByRole('link', { name })).toBeInTheDocument()
    }
    expect(screen.getByText(/Ada Admin/)).toBeInTheDocument()
  })
})

describe('Team Management', () => {
  it('lists members and invitations, filters them, and invites a member with a copyable link', async () => {
    const api = mockApi({
      'GET /auth/session': ADMIN, 'GET /workspace/members': MEMBERS,
      'POST /workspace/invitations': { status: 201, body: { invitation_id: 8, email: 'new@example.test',
        name: 'New Scout', role: 'scouter', expires_at: '2099-01-01T00:00:00Z',
        invitation_link: '/auth/invite#token=abc', emailed: false, email_channel: null } },
    })
    renderApp('/team?tab=members')
    const table = await screen.findByRole('table')
    expect(within(table).getByText('Sam Scout')).toBeInTheDocument()
    expect(within(table).getByText('Pat Pending')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Search'), 'pat')
    expect(within(table).queryByText('Sam Scout')).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText('Search'))
    await user.click(screen.getByRole('button', { name: 'Add Team Member' }))
    const form = screen.getByRole('form', { name: 'Add team member' })
    await user.type(within(form).getByLabelText('Full name'), 'New Scout')
    await user.type(within(form).getByLabelText('Email address'), 'new@example.test')
    await user.click(within(form).getByRole('button', { name: 'Send invitation' }))
    const link = await screen.findByLabelText('Link')
    expect((link as HTMLInputElement).value).toBe(`${window.location.origin}/auth/invite#token=abc`)
    expect(api.writes().find((c) => c.path === '/workspace/invitations')!.body).toEqual({
      full_name: 'New Scout', email: 'new@example.test', role: 'scouter' })
  })

  it('changes a role and suspends a member after confirmation', async () => {
    const api = mockApi({ 'GET /auth/session': ADMIN, 'GET /workspace/members': MEMBERS,
      'POST /workspace/members/2/role': { membership_id: 2, role: 'strategy' },
      'POST /workspace/members/2/status': { membership_id: 2, status: 'suspended' } })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp('/team?tab=members')
    const user = userEvent.setup()
    await user.selectOptions(await screen.findByLabelText('Role of Sam Scout'), 'strategy')
    await waitFor(() => expect(api.writes().some((c) => c.path === '/workspace/members/2/role')).toBe(true))
    await user.click(screen.getByRole('button', { name: 'Suspend' }))
    await waitFor(() => expect(api.writes().find((c) => c.path === '/workspace/members/2/status')!.body)
      .toEqual({ status: 'suspended' }))
    expect(screen.queryByLabelText('Role of Ada Admin')).toBeInTheDocument()
  })

  it('saves only the permissions that changed, and never offers administrative ones to other roles', async () => {
    const matrix = { roles: [], permissions: [
      { permission: 'match_predictions', description: 'Match predictions', admin_only: false,
        roles: { admin: { granted: true, editable: false }, strategy: { granted: true, editable: true },
          scouter: { granted: false, editable: true } } },
      { permission: 'team_management', description: 'Team Management', admin_only: true,
        roles: { admin: { granted: true, editable: false }, strategy: { granted: false, editable: false },
          scouter: { granted: false, editable: false } } },
    ] }
    const api = mockApi({ 'GET /auth/session': ADMIN, 'GET /workspace/permissions': matrix,
      'POST /workspace/permissions': { role: 'scouter', changed: {} } })
    renderApp('/team?tab=permissions')
    const user = userEvent.setup()
    expect(await screen.findByLabelText('Scouter: Team Management')).toBeDisabled()
    expect(screen.getByLabelText('Administrator: Match predictions')).toBeDisabled()
    await user.click(screen.getByLabelText('Scouter: Match predictions'))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.writes()).toHaveLength(1))
    expect(api.writes()[0].body).toEqual({ role: 'scouter', grants: { match_predictions: true } })
  })
})

describe('role dashboards', () => {
  it('lets a scouter submit a report for an assignment', async () => {
    const assignment = { assignment_id: 5, event_key: '2099synth', match_key: '2099synth_qm1',
      competition_level: 'qualification', set_number: 1, match_number: 1, scheduled_time: '2099-03-01T10:00:00Z',
      team_number: 9002, alliance_color: 'red', assigned_user_id: 2, assigned_to: 'Sam Scout', status: 'assigned',
      created_at: '2026-11-01T00:00:00Z', report_submitted: false }
    const api = mockApi({
      'GET /auth/session': SCOUTER, 'GET /workspace': OVERVIEW, ...SEASON_EVENTS,
      'GET /workspace/scouting/assignments': [assignment], 'GET /workspace/scouting/reports': [],
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

  it('shows the drive team only the tools its permissions include', async () => {
    mockApi({ 'GET /auth/session': { ...STRATEGY, permissions: ['team_info', 'event_analysis'] },
      'GET /workspace': OVERVIEW, ...SEASON_EVENTS })
    renderApp('/drive-team')
    expect(await screen.findByRole('link', { name: /Event analysis/ })).toHaveAttribute('href', '/events/2099synth')
    expect(screen.queryByRole('link', { name: /Alliance selection/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /scouting at/ })).not.toBeInTheDocument()
  })
})
