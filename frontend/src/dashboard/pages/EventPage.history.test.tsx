// P8-D1 D1.6: switching tabs replaces the history entry (the tab stays in the URL and shareable), while the moment
// (`as_of`) still pushes one, so Back undoes a moment change but leaves the page rather than stepping through tabs.

import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SessionProvider } from '../../state/session'
import { ANALYSIS, EVENT, EVENTS, MATCHES, TEAMS } from '../../test/dashboardFixtures'
import { mockApi } from '../../test/mockApi'
import { localInputToIso } from '../asOfParams'
import { EventPage } from './EventPage'

afterEach(() => vi.unstubAllGlobals())

function renderWithHistory(initial: string[]) {
  mockApi({ 'GET /events': EVENTS, [`GET /events/${EVENT}/analysis`]: ANALYSIS, [`GET /events/${EVENT}/teams`]: TEAMS,
    [`GET /events/${EVENT}/matches`]: MATCHES })
  const router = createMemoryRouter([{ path: '/events/:eventKey', element: <EventPage /> },
    { path: '*', element: <p>previous page</p> }], { initialEntries: initial, initialIndex: initial.length - 1 })
  render(<SessionProvider><RouterProvider router={router} /></SessionProvider>)
  const at = () => router.state.location.pathname + router.state.location.search
  return { router, at }
}

describe('EventPage tabs and browser history (D1.6)', () => {
  it('keeps each tab in the URL but replaces the entry, so Back leaves the page', async () => {
    const { router, at } = renderWithHistory(['/previous', `/events/${EVENT}`])
    await screen.findByRole('table', { name: /Predicted ranking/ })
    await userEvent.click(screen.getByRole('tab', { name: 'Teams' }))
    expect(at()).toBe(`/events/${EVENT}?tab=teams`)
    await userEvent.click(screen.getByRole('tab', { name: 'Matches' }))
    expect(at()).toBe(`/events/${EVENT}?tab=matches`)
    expect(screen.getByRole('tab', { name: 'Matches' })).toHaveAttribute('aria-selected', 'true')
    await act(async () => { await router.navigate(-1) })
    expect(at()).toBe('/previous') // not ?tab=teams: tab changes added no history entries
    await act(async () => { await router.navigate(1) })
    expect(at()).toBe(`/events/${EVENT}?tab=matches`) // Forward restores the tab from the URL
    expect(await screen.findByRole('tab', { name: 'Matches' })).toHaveAttribute('aria-selected', 'true')
  })

  it('opens the tab named in a shared link, and the moment still pushes a history entry', async () => {
    const { router, at } = renderWithHistory([`/events/${EVENT}?tab=teams`])
    expect(await screen.findByRole('tab', { name: 'Teams' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.change(screen.getByLabelText('Moment (as of)'), { target: { value: '2099-03-01T09:30:00' } })
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    const iso = localInputToIso('2099-03-01T09:30:00')!
    expect(new URLSearchParams(router.state.location.search).get('as_of')).toBe(iso)
    expect(new URLSearchParams(router.state.location.search).get('tab')).toBe('teams') // the tab is kept
    await act(async () => { await router.navigate(-1) })
    expect(at()).toBe(`/events/${EVENT}?tab=teams`) // Back undoes the moment change
  })
})
