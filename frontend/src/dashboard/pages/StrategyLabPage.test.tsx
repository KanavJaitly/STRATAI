import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { CompareResponse } from '../../api/generated'
import { axeViolations, currentUrl, renderAt } from '../../test/dashboard'
import { BLUE, CONTEXT, EPA, EVENT, RECOMMEND, RED, STRATEGY_MODEL, TEAMS, WIN_PROBABILITY } from '../../test/dashboardFixtures'
import { mockApi } from '../../test/mockApi'
import { localInputToIso } from '../asOfParams'
import { StrategyLabPage } from './StrategyLabPage'

const PATTERN = '/events/:eventKey/strategy-lab'
const URL = `/events/${EVENT}/strategy-lab?red=${RED.join(',')}&blue=${BLUE.join(',')}`

const compare = (r: { body: { first: never; second: never } }): CompareResponse => ({
  side: 'red', context: CONTEXT, model: STRATEGY_MODEL, epa: EPA, opponent_strategy: RECOMMEND.recommended!.opponent_strategy,
  first: { strategy: r.body.first, odds: { display: '65%', validation: { status: 'not_validated', reasons: [] } } },
  second: { strategy: r.body.second, odds: { display: '60%', validation: { status: 'not_validated', reasons: [] } } },
  label: 'within one display step',
})

function routes() {
  return mockApi({ [`GET /events/${EVENT}/teams`]: TEAMS, 'POST /strategy/hypothetical/recommend': RECOMMEND,
    'POST /predictions/win-probability': WIN_PROBABILITY, 'POST /strategy/hypothetical/compare': compare })
}

async function compareNow() {
  await screen.findByRole('heading', { name: 'AI recommendation' })
  await userEvent.click(screen.getByRole('button', { name: 'Evaluate side by side' }))
  expect(await screen.findByText('Same model, same inputs')).toBeInTheDocument()
}

describe('StrategyLabPage (P8-M4 b)', () => {
  it('evaluates the pairing from the URL through the hypothetical routes', async () => {
    const api = routes()
    const { container } = renderAt(PATTERN, URL, <StrategyLabPage />)
    await compareNow()
    const recommend = api.calls.find((c) => c.path === '/strategy/hypothetical/recommend')!
    expect(recommend.body).toEqual({ event_key: EVENT, red_team_numbers: RED, blue_team_numbers: BLUE,
      match_context: 'qualification', side: 'red' })
    expect(recommend.query.has('as_of')).toBe(false)
    expect(await axeViolations(container)).toEqual([])
  })

  it('clears a comparison when the moment changes, and asks again at the new moment', async () => {
    const api = routes()
    renderAt(PATTERN, URL, <StrategyLabPage />)
    await compareNow()
    fireEvent.change(screen.getByLabelText('Moment (as of)'), { target: { value: '2099-03-01T09:30:00' } })
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    const iso = localInputToIso('2099-03-01T09:30:00')!
    expect(currentUrl()).toContain(`as_of=${encodeURIComponent(iso)}`)
    await screen.findByRole('heading', { name: 'AI recommendation' })
    expect(screen.queryByText('Same model, same inputs')).toBeNull() // the old moment's comparison is gone
    expect(api.calls.filter((c) => c.path === '/strategy/hypothetical/recommend').map((c) => c.query.get('as_of')))
      .toContain(iso)
  })

  it('clears a comparison when the match context changes', async () => {
    const api = routes()
    renderAt(PATTERN, URL, <StrategyLabPage />)
    await compareNow()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Match context' }), 'playoff')
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate pairing' }))
    expect(currentUrl()).toContain('context=playoff')
    await screen.findByRole('heading', { name: 'AI recommendation' })
    expect(screen.queryByText('Same model, same inputs')).toBeNull()
    expect(api.calls.filter((c) => c.path === '/strategy/hypothetical/recommend')
      .map((c) => (c.body as { match_context: string }).match_context)).toContain('playoff')
  })
})
