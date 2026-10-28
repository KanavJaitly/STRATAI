import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { axeViolations, currentUrl, renderAt } from '../../test/dashboard'
import { ANALYSIS, EVENT, EVENTS, MATCHES, TEAMS } from '../../test/dashboardFixtures'
import { apiError, mockApi } from '../../test/mockApi'
import { EventPage } from './EventPage'

const PATTERN = '/events/:eventKey'

describe('EventPage (P8-M2 b)', () => {
  it('shows predicted rankings and playoff contenders from the analysis, with the ordering model and labels', async () => {
    const api = mockApi({ 'GET /events': EVENTS, [`GET /events/${EVENT}/analysis`]: ANALYSIS })
    const { container } = renderAt(PATTERN, `/events/${EVENT}`, <EventPage />)
    expect(await screen.findByRole('heading', { name: 'Synthetic Test Event' })).toBeInTheDocument()
    const ranking = await screen.findByRole('table', { name: /Predicted ranking/ })
    expect(within(ranking).getAllByRole('row')).toHaveLength(7)
    expect(within(ranking).getByText(/no score \(no EPA\)/)).toBeInTheDocument() // a null score is an absence
    expect(screen.getByText('raw EPA')).toBeInTheDocument()
    expect(screen.getByText(/Likely alliance captains/)).toBeInTheDocument()
    expect(screen.getByText('synthetic captains')).toBeInTheDocument()
    expect(screen.getByText(/share of scheduled matches with a recorded result/)).toBeInTheDocument()
    expect(api.calls.filter((c) => c.path.endsWith('/analysis'))).toHaveLength(1)
    expect(await axeViolations(container)).toEqual([])
  })

  it('shows model_not_loaded as an explained unavailable state, not a crash', async () => {
    mockApi({ 'GET /events': EVENTS, [`GET /events/${EVENT}/analysis`]: apiError(404, 'model_not_loaded',
      'No ranking_xgb_v2 (M5 v2) model of record is pinned/loadable.') })
    renderAt(PATTERN, `/events/${EVENT}`, <EventPage />)
    const notice = (await screen.findByText(/Model not loaded/)).closest('.refusal') as HTMLElement
    expect(notice).toHaveAttribute('role', 'status')
    expect(notice).toHaveTextContent('ranking_xgb_v2')
  })

  it('switches tabs through the URL, fetches each tab once, and keeps it', async () => {
    const api = mockApi({ 'GET /events': EVENTS, [`GET /events/${EVENT}/analysis`]: ANALYSIS,
      [`GET /events/${EVENT}/teams`]: TEAMS, [`GET /events/${EVENT}/matches`]: MATCHES })
    renderAt(PATTERN, `/events/${EVENT}`, <EventPage />)
    await screen.findByRole('table', { name: /Predicted ranking/ })
    await userEvent.click(screen.getByRole('tab', { name: 'Matches' }))
    expect(currentUrl()).toBe(`/events/${EVENT}?tab=matches`)
    const table = await screen.findByRole('table', { name: /Matches at/ })
    expect(within(table).getByText('not played yet')).toBeInTheDocument() // a withheld result shows its reason
    expect(within(table).getByRole('link', { name: 'Qual 1' })).toHaveAttribute('href', `/matches/${EVENT}_qm1`)
    await userEvent.click(screen.getByRole('tab', { name: 'Rankings & contenders' }))
    await screen.findByRole('table', { name: /Predicted ranking/ })
    expect(api.calls.filter((c) => c.path.endsWith('/analysis'))).toHaveLength(1)
  })

  it('moves focus with the arrow keys and opens a tab only on Enter or Space (manual activation, P8-R9)', async () => {
    const api = mockApi({ 'GET /events': EVENTS, [`GET /events/${EVENT}/analysis`]: ANALYSIS, [`GET /events/${EVENT}/teams`]: TEAMS,
      [`GET /events/${EVENT}/matches`]: MATCHES })
    renderAt(PATTERN, `/events/${EVENT}`, <EventPage />)
    await screen.findByRole('table', { name: /Predicted ranking/ })
    const first = screen.getByRole('tab', { name: 'Rankings & contenders' })
    first.focus()
    await userEvent.keyboard('{ArrowRight}{ArrowRight}') // past Teams to Matches: focus only
    expect(screen.getByRole('tab', { name: 'Matches' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Matches' })).toHaveAttribute('aria-selected', 'false')
    expect(first).toHaveAttribute('aria-selected', 'true')
    expect(currentUrl()).toBe(`/events/${EVENT}`) // nothing opened
    expect(api.calls.filter((c) => c.path.endsWith('/teams') || c.path.endsWith('/matches'))).toHaveLength(0) // no fetch
    await userEvent.keyboard('{Enter}')
    expect(screen.getByRole('tab', { name: 'Matches' })).toHaveAttribute('aria-selected', 'true')
    expect(currentUrl()).toBe(`/events/${EVENT}?tab=matches`)
    await userEvent.keyboard('{End}') // Home/End also move focus only
    expect(screen.getByRole('tab', { name: 'Qualification forecast' })).toHaveFocus()
    await userEvent.keyboard('{Home}{ArrowRight}[Space]')
    expect(screen.getByRole('tab', { name: 'Teams' })).toHaveAttribute('aria-selected', 'true')
    expect(api.calls.filter((c) => c.path.endsWith('/teams'))).toHaveLength(1) // fetched once, on activation
    expect(api.calls.filter((c) => c.path.endsWith('/qualification-forecast'))).toHaveLength(0) // never opened
  })

  it('passes the moment to the time-dependent routes', async () => {
    const api = mockApi({ 'GET /events': EVENTS, [`GET /events/${EVENT}/analysis`]: ANALYSIS })
    renderAt(PATTERN, `/events/${EVENT}?as_of=2099-03-01T08%3A00%3A00.000Z`, <EventPage />)
    await screen.findByRole('table', { name: /Predicted ranking/ })
    expect(api.calls.find((c) => c.path.endsWith('/analysis'))?.query.get('as_of')).toBe('2099-03-01T08:00:00.000Z')
  })
})
