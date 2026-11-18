// Our pick list (alliance selection): order, reordering by buttons and by typed rank, saving per event in this browser,
// and moving it between devices by text. Synthetic data only.

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { CandidateOut, CandidatesResponse, FactorOut } from '../api/generated'
import { SignedInAs } from '../test/auth'
import { EPA } from '../test/dashboardFixtures'
import { TeamPickList } from './teamPickList'

const EVENT = '2099synth'
const factor = (value: number | null): FactorOut => ({ value, n: value === null ? null : 12,
  validation: { status: 'descriptive', reasons: [] } }) as unknown as FactorOut
const candidate = (team: number, epa: number | null): CandidateOut => ({ team_number: team, scoring_epa: factor(epa),
  average_score: factor(epa === null ? null : epa + 100), reliability: factor(100), consistency: factor(60),
  defense: factor(null), feeding: factor(null), synergy: factor(null), role_compatibility: factor(null) })
const DATA: CandidatesResponse = { event_key: EVENT, as_of: '2099-03-03T16:00:00Z', as_of_source: 'selection_moment',
  configuration: null, epa: EPA, candidates: [candidate(9001, 20), candidate(9002, 50), candidate(9003, null), candidate(9004, 35)] }

const order = () => within(screen.getByRole('list', { name: /Our pick list/ })).getAllByRole('listitem')
  .map((li) => Number(within(li).getByRole('link').textContent))

function renderList(data: CandidatesResponse = DATA) {
  return render(<MemoryRouter><SignedInAs><TeamPickList data={data} /></SignedInAs></MemoryRouter>)
}

beforeEach(() => window.localStorage.clear())
afterEach(() => window.localStorage.clear())

describe('our pick list', () => {
  it('starts in scoring EPA order, teams without an EPA last, showing each value as served', () => {
    renderList()
    expect(order()).toEqual([9002, 9004, 9001, 9003])
    expect(screen.getByText('150')).toBeInTheDocument() // 9002's average score, unrounded
    expect(screen.getByText(/not synced between devices yet/)).toBeInTheDocument()
  })

  it('moves a team with the buttons and by typing a new rank, and keeps the order for this event', async () => {
    const user = userEvent.setup()
    const { unmount } = renderList()
    await user.click(screen.getByRole('button', { name: 'Move 9001 up to 2' }))
    expect(order()).toEqual([9002, 9001, 9004, 9003])
    await user.click(screen.getByRole('button', { name: 'Rank 4: move 9003 to another rank' }))
    const field = screen.getByRole('spinbutton', { name: 'New rank for 9003' })
    await user.clear(field)
    await user.type(field, '1{Enter}')
    expect(order()).toEqual([9003, 9002, 9001, 9004])
    expect(screen.getByRole('status')).toHaveTextContent('9003 is now number 1')
    unmount()
    renderList()
    expect(order()).toEqual([9003, 9002, 9001, 9004]) // saved in this browser
  })

  it('imports a copied list, skipping teams not at this event and keeping the rest in place', async () => {
    const user = userEvent.setup()
    renderList()
    await user.click(screen.getByRole('button', { name: 'Import list' }))
    await user.type(screen.getByLabelText(/Paste a copied pick list/), `StratAI pick list ${EVENT}: 9003, 7777, 9001`)
    await user.click(screen.getByRole('button', { name: 'Use this order' }))
    expect(order()).toEqual([9003, 9001, 9002, 9004])
    expect(screen.getByRole('status')).toHaveTextContent('Imported 2 teams in order; skipped 1 not at this event (7777)')
  })

  it('shows the text to copy by hand when the clipboard is not available', async () => {
    const user = userEvent.setup()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: () => Promise.reject(new Error('denied')) },
      configurable: true })
    renderList()
    await user.click(screen.getByRole('button', { name: 'Copy list' }))
    expect(screen.getByLabelText(/Paste a copied pick list/)).toHaveValue(`StratAI pick list ${EVENT}: 9002, 9004, 9001, 9003`)
  })
})
