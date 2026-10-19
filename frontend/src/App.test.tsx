import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { Shell } from './App'
import { SessionProvider } from './state/session'
import { axeViolations } from './test/dashboard'
import { EVENTS } from './test/dashboardFixtures'
import { mockApi } from './test/mockApi'

function renderShell(url: string) {
  return render(<SessionProvider><MemoryRouter initialEntries={[url]}><Shell /></MemoryRouter></SessionProvider>)
}

describe('app shell', () => {
  it('opens on the dashboard, with landmarks, a skip link and both areas in the navigation', async () => {
    mockApi({ 'GET /events': EVENTS })
    const { container } = renderShell('/?season=2099')
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main')
    expect(screen.getByRole('link', { name: 'Inputs overview' })).toHaveAttribute('href', '/inputs')
    await screen.findByText('Synthetic Test Event')
    expect(await axeViolations(container, { region: true })).toEqual([])
  })

  it('redirects the old human-input paths to /inputs', () => {
    mockApi({})
    renderShell('/game')
    expect(screen.getByRole('heading', { name: /Game manual/i })).toBeInTheDocument()
  })

  it.each([['/game', '/inputs/game'], ['/profiles', '/inputs/profiles'], ['/review', '/inputs/review']])(
    'redirects %s to its page under /inputs, replacing the history entry', async (old, target) => {
      mockApi({})
      const router = createMemoryRouter([{ path: '*', element: <SessionProvider><Shell /></SessionProvider> }],
        { initialEntries: ['/status', old], initialIndex: 1 })
      render(<RouterProvider router={router} />)
      expect(await screen.findByRole('link', { name: 'Inputs overview' })).toBeInTheDocument()
      expect(router.state.location.pathname).toBe(target)
      expect(screen.queryByText('Page not found')).toBeNull()
      expect(screen.getByRole('main').textContent).not.toBe('')
      await act(async () => { await router.navigate(-1) }) // Back skips the old path: no redirect loop
      expect(router.state.location.pathname).toBe('/status')
    })

  it('keeps the Phase 5 overview links to the old paths working through the redirects', async () => {
    const items = ['game_manual', 'codebook', 'team_profiles']
    window.localStorage.setItem('stratai.season', '2099')
    mockApi({ 'GET /human-inputs/seasons/2099/dm1-status': { season: 2099, inputs_ready: false, note: '',
      items: items.map((artifact) => ({ artifact, state: 'missing', provided: false, detail: null })),
      done_means: { done_means: 'DM1', met: false, missing_records: [], within_5_days: null, elapsed_hours: null,
        blocked_on: [] } } })
    const router = createMemoryRouter([{ path: '*', element: <SessionProvider><Shell /></SessionProvider> }],
      { initialEntries: ['/inputs'] })
    render(<RouterProvider router={router} />)
    await userEvent.click(await screen.findByRole('link', { name: 'Official game manual (PDF)' }))
    expect(router.state.location.pathname).toBe('/inputs/game')
    await act(async () => { await router.navigate('/inputs') })
    await userEvent.click(await screen.findByRole('link', { name: 'Codebook' }))
    expect(router.state.location.pathname).toBe('/inputs/review')
    await act(async () => { await router.navigate('/inputs') })
    await userEvent.click(await screen.findByRole('link', { name: /Team capability profiles/ }))
    expect(router.state.location.pathname).toBe('/inputs/profiles')
  })

  it('shows a not-found page for an unknown path', () => {
    mockApi({})
    renderShell('/nowhere')
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('moves focus to the main region and names the page after a navigation (WCAG 2.4.3, 2.4.2)', async () => {
    mockApi({ 'GET /events': EVENTS, 'GET /health': { status: 'ok', env: 'test' }, 'GET /ready': { status: 'ready', checks: {} } })
    renderShell('/?season=2099')
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
    expect(document.title).toBe('Events · STRATAI')
    expect(screen.getByRole('link', { name: 'Events' })).toHaveAttribute('aria-current', 'page')
    await userEvent.click(screen.getByRole('link', { name: 'System status' }))
    expect(await screen.findByRole('heading', { name: 'System status' })).toBeInTheDocument()
    expect(document.activeElement).toBe(screen.getByRole('main'))
    expect(document.title).toBe('System status · STRATAI')
    expect(screen.getByRole('link', { name: 'Events' })).not.toHaveAttribute('aria-current')
  })

  it('keeps the Events navigation current on event, match and report pages', () => {
    mockApi({})
    renderShell('/matches/2099test_qm1')
    expect(screen.getByRole('link', { name: 'Events' })).toHaveAttribute('aria-current', 'page')
  })

  it('does not keep the previous page title on a page without its own', async () => {
    mockApi({ 'GET /health': { status: 'ok', env: 'test' }, 'GET /ready': { status: 'ready', checks: {} } })
    renderShell('/status')
    await screen.findByRole('heading', { name: 'System status' })
    expect(document.title).toBe('System status · STRATAI')
    await userEvent.click(screen.getByRole('link', { name: 'Inputs overview' }))
    expect(document.title).toBe('STRATAI')
  })
})
