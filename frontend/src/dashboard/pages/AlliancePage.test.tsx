import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { axeViolations, renderAt } from '../../test/dashboard'
import { BLUE, CANDIDATES, EVENT, PICK_LIST, RED } from '../../test/dashboardFixtures'
import { apiError, mockApi } from '../../test/mockApi'
import { AlliancePage, PickListView } from './AlliancePage'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const PATTERN = '/events/:eventKey/alliance-selection'

describe('AlliancePage (P8-M5)', () => {
  it('shows candidate factors with n and status; absent values sort last, never as zero', async () => {
    mockApi({ [`GET /events/${EVENT}/alliance-selection/candidates`]: CANDIDATES })
    const { container } = renderAt(PATTERN, `/events/${EVENT}/alliance-selection`, <AlliancePage />)
    const table = await screen.findByRole('table', { name: /Candidate factors/ })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Sort by' }), 'scoring_epa')
    const order = within(table).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('link')[0].textContent)
    expect(order).toEqual([String(BLUE[0]), String(RED[0]), String(RED[1])]) // 45, 30, then the absent one
    expect(within(table).getAllByText('needs a full three-team alliance').length).toBeGreaterThan(0)
    expect(await axeViolations(container)).toEqual([])
  })

  it('sends a configuration only when it is three distinct teams', async () => {
    const api = mockApi({ [`GET /events/${EVENT}/alliance-selection/candidates`]: CANDIDATES })
    renderAt(PATTERN, `/events/${EVENT}/alliance-selection?config=${RED.join(',')}`, <AlliancePage />)
    await screen.findByRole('table', { name: /Candidate factors/ })
    expect(api.calls.find((c) => c.path.endsWith('/candidates'))?.query.getAll('configuration')).toEqual(RED.map(String))
  })

  it('shows the real refusal when the pick list cannot run (not_approved, P6-DM1)', async () => {
    const api = mockApi({ [`GET /events/${EVENT}/alliance-selection/candidates`]: CANDIDATES,
      [`POST /events/${EVENT}/alliance-selection/pick-list`]: apiError(409, 'not_approved', 'no approved 2099 ruleset') })
    renderAt(PATTERN, `/events/${EVENT}/alliance-selection`, <AlliancePage />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Alliance 1' }), `${RED[0]}`)
    await userEvent.click(screen.getByRole('button', { name: 'Rank picks' }))
    const notice = (await screen.findByText(/No approved ruleset/)).closest('.refusal') as HTMLElement
    expect(notice).toHaveTextContent('pick list is not available')
    expect(notice).toHaveTextContent('not_approved')
    const body = api.calls.find((c) => c.path.endsWith('/pick-list'))?.body as { alliances: number[][]; seed: number; turns_taken: number }
    expect(body).toMatchObject({ seed: 1, turns_taken: 0 })
    expect(body.alliances).toHaveLength(8)
    expect(body.alliances[0]).toEqual([RED[0]])
  })
})

describe('PickListView (synthetic success, labelled synthetic)', () => {
  it('renders ranked picks with served odds, the validated_playoff_success scope, labels and provenance', async () => {
    const { container } = render(<MemoryRouter><PickListView data={PICK_LIST} /></MemoryRouter>)
    expect(screen.getAllByText('validated_playoff_success').length).toBeGreaterThan(1)
    expect(screen.getByText('35%')).toBeInTheDocument()
    expect(screen.getAllByText(/px4_scope/).length).toBeGreaterThan(0)
    expect(screen.getByText(/last_candidate/)).toBeInTheDocument()
    expect(screen.getByText(/only 1 distinct feasible alternative/)).toBeInTheDocument()
    expect(screen.queryByText('validated_playoff')).toBeNull() // never relabelled
    expect(await axeViolations(container)).toEqual([])
  })
})
