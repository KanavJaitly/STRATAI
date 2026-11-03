import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi, type Recorded } from '../test/mockApi'
import { EventChooser } from './EventChooser'
import { clearSeasonEvents, defaultSeason, seasonOf } from './events'

// Choosing an event by year, region and name instead of typing its key. Synthetic fixture events only.

function event(key: string, name: string, district: string | null, districtName: string | null, city: string) {
  return { event_key: key, name, event_code: key.slice(4), event_type: null, start_date: `${key.slice(0, 4)}-03-06`,
    end_date: `${key.slice(0, 4)}-03-08`, city, state_prov: 'NJ', country: 'USA', district, district_name: districtName,
    matches: 0, matches_played: 0, teams: 0 }
}

const EVENTS_2026 = [
  event('2026njwas', 'FMA District Warren Hills Event', 'fma', 'FIRST Mid-Atlantic', 'Washington'),
  event('2026njrob', 'FMA District Robbinsville Event', 'fma', 'FIRST Mid-Atlantic', 'Trenton'),
  event('2026miket', 'FIM District Kettering Event', 'fim', 'FIRST in Michigan', 'Flint'),
  event('2026azfl', 'Arizona East Regional', null, null, 'Flagstaff'),
]
const EVENTS_2025 = [event('2025paca', 'FMA District Bensalem Event', 'fma', 'FIRST Mid-Atlantic', 'Bensalem')]

function Harness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <EventChooser value={value} onChange={setValue} />
      <output data-testid="chosen">{value}</output>
    </>
  )
}

afterEach(() => { clearSeasonEvents(); vi.unstubAllGlobals() })

describe('EventChooser', () => {
  it('chooses an event by region and name, without typing its key', async () => {
    const api = mockApi({ 'GET /explorer/seasons/2026/events': EVENTS_2026 })
    render(<Harness initial="2026azfl" />)
    const user = userEvent.setup()
    expect(screen.getByLabelText('Year')).toHaveValue('2026') // the chosen event's year
    const region = screen.getByLabelText('Region')
    await screen.findByRole('option', { name: 'FMA — FIRST Mid-Atlantic' })
    expect(within(region).getByRole('option', { name: 'FIM — FIRST in Michigan' })).toBeInTheDocument()
    expect(within(region).getByRole('option', { name: 'Regionals and other events (no district)' })).toBeInTheDocument()
    await user.selectOptions(region, 'fma')
    const list = screen.getByRole('list', { name: 'Events in 2026' })
    expect(within(list).getAllByRole('button')).toHaveLength(2)
    await user.type(screen.getByLabelText('Event'), 'warren')
    const options = within(list).getAllByRole('button')
    expect(options).toHaveLength(1)
    await user.click(options[0])
    expect(screen.getByTestId('chosen')).toHaveTextContent('2026njwas')
    const selected = screen.getAllByRole('status').find((el) => el.classList.contains('event-chosen'))
    expect(selected).toHaveTextContent('Selected: FMA District Warren Hills Event')
    expect(api.calls.filter((c) => c.path === '/explorer/seasons/2026/events')).toHaveLength(1)
  })

  it('narrows to events outside any district and matches by city', async () => {
    mockApi({ 'GET /explorer/seasons/2026/events': EVENTS_2026 })
    render(<Harness initial="2026azfl" />)
    const user = userEvent.setup()
    await screen.findByRole('option', { name: 'FMA — FIRST Mid-Atlantic' })
    await user.selectOptions(screen.getByLabelText('Region'), '-')
    const list = () => screen.getByRole('list', { name: 'Events in 2026' })
    expect(within(list()).getAllByRole('button').map((b) => b.textContent)).toEqual([expect.stringContaining('Arizona East')])
    await user.selectOptions(screen.getByLabelText('Region'), '')
    // An event is already chosen and nothing is typed: the list steps aside until the user starts choosing again.
    expect(screen.queryByRole('list', { name: 'Events in 2026' })).not.toBeInTheDocument()
    expect(screen.getByText(/To change it, choose a region or type/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Event'), 'flint')
    expect(within(list()).getAllByRole('button').map((b) => b.textContent)).toEqual([expect.stringContaining('Kettering')])
  })

  it('switches years and reports when nothing matches', async () => {
    mockApi({ 'GET /explorer/seasons/2026/events': EVENTS_2026, 'GET /explorer/seasons/2025/events': EVENTS_2025 })
    render(<Harness initial="2026azfl" />)
    const user = userEvent.setup()
    await screen.findByRole('option', { name: 'FMA — FIRST Mid-Atlantic' })
    await user.selectOptions(screen.getByLabelText('Year'), '2025')
    expect(await screen.findByRole('button', { name: /Bensalem/ })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Event'), 'nowhere at all')
    expect(screen.getByText(/No event matches/)).toBeInTheDocument()
  })

  it('opens on the chosen event’s year, else the current one', () => {
    expect(seasonOf('2025paca')).toBe(2025)
    expect(seasonOf('')).toBeNull()
    expect(defaultSeason('2024abc')).toBe(2024)
    expect(defaultSeason('', new Date('2026-05-01T00:00:00Z'))).toBe(2026)
    expect(defaultSeason('', new Date('2031-05-01T00:00:00Z'))).toBe(2026) // not covered: the latest played season
  })
})

describe('the default event in Team Settings', () => {
  it('is chosen from the list and saved by its key', async () => {
    const { AuthProvider } = await import('../auth/AuthContext')
    const { MemoryRouter } = await import('react-router-dom')
    const { SessionProvider } = await import('../state/session')
    const { Shell } = await import('../App')
    const admin = { authenticated: true, access_policy: 'open', email_delivery_configured: false, accounts_available: true,
      user: { id: 1, name: 'Ada Admin', email: 'a@example.test' },
      workspace: { team_number: 9999, team_name: 'Synthetic', verification_status: 'verified' }, role: 'admin',
      role_label: 'Administrator', permissions: ['team_management', 'team_settings', 'manage_permissions',
        'activity_log', 'team_info'] }
    const api = mockApi({
      'GET /auth/session': admin,
      'GET /workspace/settings': { team_number: 9999, team_name: 'Synthetic', default_event_key: null,
        scouting_instructions: null },
      'POST /workspace/settings': (request: Recorded) => ({ team_number: 9999, team_name: 'Synthetic',
        scouting_instructions: null, ...(request.body as object) }),
      'GET /explorer/seasons/2026/events': EVENTS_2026,
    })
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-04-01T12:00:00Z') })
    render(<SessionProvider><AuthProvider><MemoryRouter initialEntries={['/team?tab=settings']}><Shell /></MemoryRouter>
      </AuthProvider></SessionProvider>)
    const user = userEvent.setup()
    await screen.findByRole('option', { name: 'FMA — FIRST Mid-Atlantic' })
    await user.type(screen.getByLabelText('Event'), 'robbinsville')
    await user.click(screen.getByRole('button', { name: /Robbinsville/ }))
    await user.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() => expect(api.writes()).toHaveLength(1))
    expect(api.writes()[0].body).toMatchObject({ default_event_key: '2026njrob' })
    expect(screen.queryByPlaceholderText(/2026casj/)).not.toBeInTheDocument() // no event key to type anywhere
    vi.useRealTimers()
  })
})
