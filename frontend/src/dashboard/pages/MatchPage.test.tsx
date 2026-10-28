import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { setWriteToken } from '../../api/client'
import type { CompareResponse } from '../../api/generated'
import { axeViolations, currentUrl, renderAt } from '../../test/dashboard'
import { BLUE, CONTEXT, EPA, EVENT, MATCH, MATCHES, RECOMMEND, RED, STRATEGY_MODEL, WIN_PROBABILITY } from '../../test/dashboardFixtures'
import { apiError, mockApi, WRITE_OFF, WRITE_OK } from '../../test/mockApi'
import { MatchPage } from './MatchPage'

const PATTERN = '/matches/:matchKey'
afterEach(() => setWriteToken(''))

const compareResult = (body: { first: CompareResponse['first']['strategy']; second: CompareResponse['second']['strategy'] }): CompareResponse => ({
  side: 'red', context: CONTEXT, model: STRATEGY_MODEL, epa: EPA, opponent_strategy: RECOMMEND.recommended!.opponent_strategy,
  first: { strategy: body.first, odds: { display: '65%', validation: { status: 'not_validated', reasons: ['strategy_effect_unmeasured'] } } },
  second: { strategy: body.second, odds: { display: '55%', validation: { status: 'not_validated', reasons: ['p6_m10_gate_failed'] } } },
  label: 'differs by at least one display step under the model (not a claim that either strategy is better)',
})

function routes(extra: Record<string, unknown> = {}) {
  return { [`GET /events/${EVENT}/matches`]: MATCHES, [`POST /strategy/matches/${MATCH}/recommend`]: RECOMMEND,
    [`GET /predictions/matches/${MATCH}/win-probability`]: WIN_PROBABILITY, ...extra }
}

describe('MatchPage (P8-M4)', () => {
  it('shows the AI recommendation with its selection note, and the M6/M7 probability in its own panel', async () => {
    const api = mockApi(routes())
    const { container } = renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    const ai = (await screen.findByRole('heading', { name: 'AI recommendation' })).closest('.assessed') as HTMLElement
    expect(within(ai).getByText('65%')).toBeInTheDocument()
    expect(within(ai).getByText('the effect of the chosen strategy is not measured')).toBeInTheDocument()
    expect(within(ai).getByText(/Defense on 9904/)).toBeInTheDocument()
    expect(within(ai).getByText(/maximum of many model estimates/)).toBeInTheDocument()
    const panel = screen.getByRole('heading', { name: /Match win probability/ }).closest('section') as HTMLElement
    expect(within(panel).getByText('Red 60%')).toBeInTheDocument()
    expect(within(panel).queryByText('65%')).toBeNull() // the two models never share a field
    expect(api.calls.find((c) => c.path.endsWith('/recommend'))?.body).toEqual({ side: 'red' })
    expect(await axeViolations(container)).toEqual([])
  })

  it('evaluates the coach strategy against the AI one through the compare route, rendered alike', async () => {
    const api = mockApi(routes({ [`POST /strategy/matches/${MATCH}/compare`]: (r: { body: { first: never; second: never } }) =>
      compareResult(r.body) }))
    renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    await screen.findByRole('heading', { name: 'AI recommendation' })
    const editor = screen.getByRole('group', { name: /Coach strategy for red/ })
    await userEvent.selectOptions(within(editor).getByRole('combobox', { name: `Team ${RED[2]} role` }), 'feeding')
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate side by side' }))
    const result = (await screen.findByText('Same model, same inputs')).closest('.comparison') as HTMLElement
    expect(within(result).getByText(/not a claim that either strategy is better/)).toBeInTheDocument()
    const sent = api.calls.find((c) => c.path.endsWith('/compare'))?.body as { first: unknown; second: { robots: { role: string; feed_target: number }[] } }
    expect(sent.first).toEqual(RECOMMEND.recommended!.strategy)
    expect(sent.second.robots[2]).toMatchObject({ role: 'feeding', feed_target: RED[0] })
    expect(within(result).getAllByText('Odds of winning:')).toHaveLength(2)
  })

  it('blocks a coach strategy the engine would reject (teleop without the scoring role)', async () => {
    mockApi(routes())
    renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    await screen.findByRole('heading', { name: 'AI recommendation' })
    const editor = screen.getByRole('group', { name: /Coach strategy for red/ })
    await userEvent.selectOptions(within(editor).getByRole('combobox', { name: `Team ${RED[0]} role` }), 'defense')
    const teleop = within(within(editor).getByRole('group', { name: `Team ${RED[0]} scores in` })).getByRole('checkbox', { name: `Team ${RED[0]} teleop` })
    expect(teleop).toBeDisabled()
    expect(teleop).not.toBeChecked()
  })

  it('shows model_not_loaded for the strategy and still shows the alliances and the win probability', async () => {
    mockApi(routes({ [`POST /strategy/matches/${MATCH}/recommend`]: apiError(404, 'model_not_loaded', 'No strategy model') }))
    renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    expect(await screen.findByText(/AI recommendation: Model not loaded/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Evaluate side by side' })).toBeDisabled()
    expect(await screen.findByText('Red 60%')).toBeInTheDocument()
    expect(screen.getAllByText(String(BLUE[0])).length).toBeGreaterThan(0)
  })

  it('keeps the planned side in the URL and asks the engine for that side', async () => {
    const api = mockApi(routes())
    renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    await screen.findByRole('heading', { name: 'AI recommendation' })
    await userEvent.click(screen.getByRole('radio', { name: 'Blue alliance' }))
    expect(currentUrl()).toBe(`/matches/${MATCH}?side=blue`)
    expect(api.calls.filter((c) => c.path.endsWith('/recommend')).map((c) => (c.body as { side: string }).side)).toContain('blue')
  })

  it('gates coach writes: none without access; with access, a double click stores once', async () => {
    mockApi({ ...routes(), ...WRITE_OFF })
    const first = renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    await screen.findByRole('heading', { name: 'AI recommendation' })
    expect(await screen.findAllByText(/Writes are disabled on this server/)).not.toHaveLength(0)
    first.unmount()

    let release!: () => void
    const api = mockApi({ ...routes(), ...WRITE_OK, 'POST /strategy/coach-strategies': () => new Promise((resolve) => {
      release = () => resolve({ status: 201, body: { event_key: EVENT, match_key: MATCH, strategy: RECOMMEND.baseline!.strategy,
        strategy_sha256: 'd'.repeat(64), origin: 'human_entered', author: 'Test Person', created_at: '2099-03-01T09:00:00Z' } })
    }) })
    setWriteToken('token')
    renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    const save = await screen.findByRole('button', { name: 'Save as a coach strategy' })
    await userEvent.dblClick(save)
    expect(api.calls.filter((c) => c.path === '/strategy/coach-strategies')).toHaveLength(1)
    release()
    expect(await screen.findByText(/Stored by Test Person/)).toBeInTheDocument()
  })

  it('builds the coach editor once the alliances arrive after mount (regression: it stayed empty)', async () => {
    let release!: () => void
    mockApi(routes({
      [`POST /strategy/matches/${MATCH}/recommend`]: apiError(404, 'model_not_loaded', 'No strategy model'),
      [`GET /events/${EVENT}/matches`]: () => new Promise((resolve) => { release = () => resolve(MATCHES) }),
    }))
    renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    await screen.findByText(/AI recommendation: Model not loaded/)
    release()
    expect(await screen.findByRole('combobox', { name: `Team ${RED[2]} role` })).toBeInTheDocument()
    const editor = screen.getByRole('group', { name: /Coach strategy for red/ })
    expect(within(editor).getAllByRole('combobox')).toHaveLength(3)
  })

  it('saves the edited coach strategy (not the AI one), with the token', async () => {
    const api = mockApi({ ...routes(), ...WRITE_OK, 'POST /strategy/coach-strategies': (r: { body: { strategy: never } }) => ({
      status: 201, body: { event_key: EVENT, match_key: MATCH, strategy: r.body.strategy, strategy_sha256: 'a'.repeat(64),
        origin: 'human_entered', author: 'Test Person', created_at: '2099-03-01T09:00:00Z' } }) })
    setWriteToken('token')
    renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    await screen.findByRole('heading', { name: 'AI recommendation' })
    const editor = screen.getByRole('group', { name: /Coach strategy for red/ })
    await userEvent.selectOptions(within(editor).getByRole('combobox', { name: `Team ${RED[2]} role` }), 'feeding')
    await userEvent.click(screen.getByRole('button', { name: 'Save as a coach strategy' }))
    expect(await screen.findByText(/Stored by Test Person/)).toBeInTheDocument()
    const [post] = api.writes().filter((c) => c.path === '/strategy/coach-strategies')
    expect(post.headers['X-StratAI-Write-Token']).toBe('token')
    const body = post.body as { event_key: string; match_key: string; author: string; strategy: { robots: { team_number: number; role: string }[] } }
    expect(body).toMatchObject({ event_key: EVENT, match_key: MATCH, author: 'Test Person' })
    expect(body.strategy.robots[2]).toMatchObject({ team_number: RED[2], role: 'feeding' })
  })

  it('keeps a save in flight when the coach edits the strategy (regression: a remount lost it and re-enabled Save)', async () => {
    let release!: () => void
    const api = mockApi({ ...routes(), ...WRITE_OK, 'POST /strategy/coach-strategies': (r: { body: { strategy: never } }) =>
      new Promise((resolve) => { release = () => resolve({ status: 201, body: { event_key: EVENT, match_key: MATCH,
        strategy: r.body.strategy, strategy_sha256: 'b'.repeat(64), origin: 'human_entered', author: 'Test Person',
        created_at: '2099-03-01T09:00:00Z' } }) }) })
    setWriteToken('token')
    renderAt(PATTERN, `/matches/${MATCH}`, <MatchPage />)
    await screen.findByRole('heading', { name: 'AI recommendation' })
    await userEvent.click(screen.getByRole('button', { name: 'Save as a coach strategy' }))
    const editor = screen.getByRole('group', { name: /Coach strategy for red/ })
    await userEvent.selectOptions(within(editor).getByRole('combobox', { name: `Team ${RED[2]} role` }), 'feeding')
    const busy = screen.getByRole('button', { name: 'Saving…' }) // the same write is still in flight
    await userEvent.click(busy)
    release()
    expect(await screen.findByText(/Stored by Test Person/)).toBeInTheDocument() // its outcome is not lost
    expect(screen.getByText(/your edits\s+since then are not saved/)).toBeInTheDocument()
    expect(api.writes().filter((c) => c.path === '/strategy/coach-strategies')).toHaveLength(1)
  })
})

