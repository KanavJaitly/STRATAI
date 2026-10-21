/// <reference types="node" />
// P8-R9 regression tests: persistent status regions, busy actions that keep focus and stay guarded, the sticky first
// column and readable chart ticks on phones. (Manual tab activation is tested in EventPage.test.tsx.) jsdom has no
// layout, so the two CSS items are checked in the stylesheet source here and measured in a real browser separately
// (.agent/phase8 R9 record). All data is synthetic.

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { CompareResponse } from '../api/generated'
import type { Resource } from '../components/useResource'
import { renderAt } from '../test/dashboard'
import { CANDIDATES, CONTEXT, EPA, EVENT, MATCH, MATCHES, PICK_LIST, RECOMMEND, RED, STRATEGY_MODEL, WIN_PROBABILITY } from '../test/dashboardFixtures'
import { mockApi } from '../test/mockApi'
import { ResourceView } from './display'
import { AlliancePage } from './pages/AlliancePage'
import { MatchPage } from './pages/MatchPage'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

const resource = <T,>(state: Partial<Resource<T>>): Resource<T> =>
  ({ data: null, error: null, loading: false, reload: () => {}, ...state })

describe('persistent status regions (P8-R9)', () => {
  it('ResourceView keeps one status element through loading and loaded, changing only its text', () => {
    const view = render(<ResourceView resource={resource<string>({ loading: true })} what="teams">{(d) => <p>{d}</p>}</ResourceView>)
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Loading teams…')
    view.rerender(<ResourceView resource={resource<string>({ data: 'loaded' })} what="teams">{(d) => <p>{d}</p>}</ResourceView>)
    expect(screen.getByText('loaded')).toBeInTheDocument()
    expect(status.isConnected).toBe(true) // the same element, still in the document
    expect(screen.getByRole('status')).toBe(status)
    expect(status).toHaveTextContent('')
  })
})

describe('busy actions keep focus and stay guarded (P8-R9)', () => {
  it('Evaluate side by side: aria-disabled while busy, focus kept, a second click sends nothing, and the result is announced', async () => {
    const pending = deferred<CompareResponse>()
    const api = mockApi({ [`GET /events/${EVENT}/matches`]: MATCHES, [`POST /strategy/matches/${MATCH}/recommend`]: RECOMMEND,
      [`GET /predictions/matches/${MATCH}/win-probability`]: WIN_PROBABILITY,
      [`POST /strategy/matches/${MATCH}/compare`]: () => pending.promise })
    const { container } = renderAt('/matches/:matchKey', `/matches/${MATCH}`, <MatchPage />)
    await screen.findByRole('heading', { name: 'AI recommendation' })
    const regionsBefore = new Set(container.querySelectorAll('[role="status"]'))
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate side by side' }))
    const busy = screen.getByRole('button', { name: 'Evaluating…' })
    expect(busy).toHaveAttribute('aria-disabled', 'true')
    expect(busy).toBeEnabled() // not `disabled`: it stays focusable
    expect(busy).toHaveFocus()
    await userEvent.click(busy)
    expect(api.calls.filter((c) => c.path.endsWith('/compare'))).toHaveLength(1) // guarded
    const announcing = screen.getByText('Evaluating both strategies…')
    expect(regionsBefore.has(announcing)).toBe(true) // the region existed before the action
    pending.resolve({ side: 'red', context: CONTEXT, model: STRATEGY_MODEL, epa: EPA,
      opponent_strategy: RECOMMEND.recommended!.opponent_strategy, label: 'within one display step',
      first: { strategy: RECOMMEND.recommended!.strategy, odds: { display: '65%', validation: { status: 'not_validated', reasons: [] } } },
      second: { strategy: RECOMMEND.recommended!.strategy, odds: { display: '65%', validation: { status: 'not_validated', reasons: [] } } } })
    expect(await screen.findByText('Comparison ready.')).toBe(announcing)
    expect(container.querySelector('.comparison[aria-live]')).toBeNull() // the result is no longer its own live region
  })

  it('Rank picks: aria-disabled while busy, focus kept, one request, and the outcome is announced in a persistent region', async () => {
    const pending = deferred<unknown>()
    const api = mockApi({ [`GET /events/${EVENT}/alliance-selection/candidates`]: CANDIDATES,
      [`POST /events/${EVENT}/alliance-selection/pick-list`]: () => pending.promise })
    const { container } = renderAt('/events/:eventKey/alliance-selection', `/events/${EVENT}/alliance-selection`, <AlliancePage />)
    const button = await screen.findByRole('button', { name: 'Rank picks' })
    const regionsBefore = new Set(container.querySelectorAll('[role="status"]'))
    await userEvent.click(button)
    const busy = screen.getByRole('button', { name: 'Ranking picks…' })
    expect(busy).toHaveAttribute('aria-disabled', 'true')
    expect(busy).toBeEnabled()
    expect(busy).toHaveFocus()
    await userEvent.click(busy)
    await userEvent.keyboard('{Enter}') // keyboard submit while busy is guarded too
    expect(api.calls.filter((c) => c.path.endsWith('/pick-list'))).toHaveLength(1)
    pending.resolve(PICK_LIST)
    const done = await screen.findByText('Pick list ready.')
    expect(regionsBefore.has(done)).toBe(true)
    expect(container.querySelector('.picklist[aria-live]')).toBeNull()
  })

  it('Score synergy: aria-disabled while busy, focus kept, one request', async () => {
    const pending = deferred<unknown>()
    const api = mockApi({ [`GET /events/${EVENT}/alliance-selection/candidates`]: CANDIDATES,
      'POST /predictions/alliance-synergy': () => pending.promise })
    renderAt('/events/:eventKey/alliance-selection', `/events/${EVENT}/alliance-selection`, <AlliancePage />)
    const form = await screen.findByRole('form', { name: 'Synergy teams' })
    await userEvent.type(within(form).getByRole('textbox'), RED.join(', '))
    await userEvent.click(within(form).getByRole('button', { name: 'Score synergy' }))
    const busy = within(form).getByRole('button', { name: 'Score synergy' })
    expect(busy).toHaveAttribute('aria-disabled', 'true')
    expect(busy).toBeEnabled()
    expect(busy).toHaveFocus()
    await userEvent.click(busy)
    expect(api.calls.filter((c) => c.path === '/predictions/alliance-synergy')).toHaveLength(1)
    expect(screen.getByText('Scoring synergy…')).toBeInTheDocument()
  })
})

// Read from disk: the test config sets `css: false`, which empties CSS imports, even `?raw` ones.
const CSS = readFileSync(resolve(process.cwd(), 'src/styles/dashboard.css'), 'utf8') // vitest runs from frontend/

describe('layout rules a browser applies (P8-R9; measured in a real browser in the R9 record)', () => {
  it('keeps the first column of a scrolling table in view, and drops that for print', () => {
    expect(CSS.length).toBeGreaterThan(1000)
    expect(CSS).toMatch(/\.table-scroll > table\.grid tr > :first-child \{[^}]*position: sticky;[^}]*left: 0;[^}]*background: var\(--surface\)/)
    const print = CSS.slice(CSS.indexOf('@media print'))
    expect(print).toMatch(/\.table-scroll > table\.grid tr > :first-child \{ position: static; \}/)
  })

  it('enlarges chart ticks on phones so they render at a readable size from the 420 px minimum chart width', () => {
    const rule = /@media \(max-width: 600px\) \{ \.chart-tick \{ font-size: (\d+)px; \}/.exec(CSS)
    expect(rule).not.toBeNull()
    const rendered = (Number(rule![1]) * 420) / 640 // viewBox units -> CSS px at the minimum width
    expect(rendered).toBeGreaterThanOrEqual(11)
  })
})

describe('report print pagination (P8-R11; verified on A4 in a real browser in the R11 record)', () => {
  const print = CSS.slice(CSS.indexOf('@media print'))
  it('lets large sections break across pages instead of pushing whole cards to the next page', () => {
    expect(print).toMatch(/\.card \{[^}]*break-inside: auto;/)
    expect(print).not.toMatch(/\.card \{[^}]*break-inside: avoid;/)
  })
  it('keeps table rows, small items and the footer whole, and keeps headings with what follows', () => {
    expect(print).toMatch(/tr, \.not-produced, \.notice, \.absent-part, \.facts dt, \.facts dd, \.card-head, \.report-footer \{ break-inside: avoid; \}/)
    expect(print).toMatch(/h1, h2, h3, h4, \.report details > summary, \.card-head \{ break-after: avoid; \}/)
  })
})

