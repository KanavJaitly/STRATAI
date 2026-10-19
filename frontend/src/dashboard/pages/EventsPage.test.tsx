import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { axeViolations, currentUrl, renderAt } from '../../test/dashboard'
import { EVENTS } from '../../test/dashboardFixtures'
import { apiError, mockApi } from '../../test/mockApi'
import { EventsPage } from './EventsPage'

describe('EventsPage (P8-M2 a)', () => {
  it('lists the season from GET /events, sorted by start date, with links to each event', async () => {
    const api = mockApi({ 'GET /events': EVENTS })
    const { container } = renderAt('/', '/?season=2099', <EventsPage />)
    expect(await screen.findByRole('link', { name: 'Synthetic Test Event' })).toHaveAttribute('href', '/events/2099test')
    expect(api.calls.find((c) => c.path === '/events')?.query.get('season')).toBe('2099')
    const rows = screen.getAllByRole('row').slice(1).map((r) => r.textContent)
    expect(rows[0]).toContain('Another Synthetic Event') // 2099-02-01 before 2099-03-01
    expect(screen.queryByText(/no dates/)).toBeNull() // both events have a start date
    expect(await axeViolations(container)).toEqual([])
  })

  it('filters by search text and says when nothing matches', async () => {
    mockApi({ 'GET /events': EVENTS })
    renderAt('/', '/?season=2099', <EventsPage />)
    await screen.findByText('Synthetic Test Event')
    await userEvent.type(screen.getByRole('searchbox'), 'zzz')
    expect(screen.getByText(/No event matches/)).toBeInTheDocument()
  })

  it('says a season has no events, rather than showing an empty table', async () => {
    mockApi({ 'GET /events': { ...EVENTS, events: [] } })
    renderAt('/', '/?season=2099', <EventsPage />)
    expect(await screen.findByText(/StratAI has no events for 2099/)).toBeInTheDocument()
  })

  it('keeps the chosen season in the URL', async () => {
    mockApi({ 'GET /events': EVENTS })
    renderAt('/', '/?season=2099', <EventsPage />)
    const input = await screen.findByRole('spinbutton')
    await userEvent.clear(input)
    await userEvent.type(input, '2098')
    await userEvent.click(screen.getByRole('button', { name: 'Show' }))
    expect(currentUrl()).toBe('/?season=2098')
  })

  it('shows a failure with a retry', async () => {
    mockApi({ 'GET /events': apiError(500, 'internal_error', 'Internal server error') })
    renderAt('/', '/?season=2099', <EventsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Server error')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
