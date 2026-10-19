// Coach writes (P8-M4 (d), P8-Q8): the request each sends, refusals shown as returned, never a second POST on its own,
// and a warning (not a retry) when the outcome is unknown. All data is synthetic.

import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { setWriteToken, WRITE_TOKEN_HEADER } from '../api/client'
import { useState } from 'react'

import type { Strategy } from '../api/generated'
import { renderAt } from '../test/dashboard'
import { baseline, EVENT, MATCH, RED } from '../test/dashboardFixtures'
import { apiError, mockApi, WRITE_OK } from '../test/mockApi'
import { localInputToIso } from './asOfParams'
import { RecordObservation, SaveCoachStrategy } from './coachInputs'

afterEach(() => { setWriteToken(''); vi.unstubAllGlobals() })

const STORED_OBSERVATION = (body: { team_number: number; kind: string; component?: string; observed_at: string }) => ({
  status: 201, body: { observation: { event_key: EVENT, team_number: body.team_number, kind: body.kind,
    component: body.component ?? null, observed_at: body.observed_at, observer: 'Test Person',
    created_at: '2099-03-01T09:31:00Z' } },
})

function observationForm() {
  renderAt('/', '/', <RecordObservation eventKey={EVENT} teams={RED} />)
}

describe('RecordObservation', () => {
  it('sends the local moment as an ISO instant, with the token, and no component for a robot observation', async () => {
    const api = mockApi({ ...WRITE_OK, 'POST /strategy/coach-observations': (r: { body: never }) => STORED_OBSERVATION(r.body) })
    setWriteToken('token')
    observationForm()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Team' }), String(RED[1]))
    const button = await screen.findByRole('button', { name: 'Record observation' })
    expect(button).toBeDisabled() // no moment yet
    await userEvent.type(screen.getByLabelText('Observed at'), '2099-03-01T09:30')
    await userEvent.click(button)
    expect(await screen.findByText(/Recorded: team 9902/)).toBeInTheDocument()
    const posts = api.writes().filter((c) => c.path === '/strategy/coach-observations')
    expect(posts).toHaveLength(1)
    expect(posts[0].headers[WRITE_TOKEN_HEADER]).toBe('token')
    expect(posts[0].body).toEqual({ event_key: EVENT, team_number: RED[1], kind: 'robot_unavailable',
      observed_at: localInputToIso('2099-03-01T09:30'), observer: 'Test Person' })
  })

  it('sends the phase only for a mechanism observation', async () => {
    const api = mockApi({ ...WRITE_OK, 'POST /strategy/coach-observations': (r: { body: never }) => STORED_OBSERVATION(r.body) })
    setWriteToken('token')
    observationForm()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Observation' }), 'component_unavailable')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Phase' }), 'teleop')
    await userEvent.type(screen.getByLabelText('Observed at'), '2099-03-01T09:30')
    await userEvent.click(await screen.findByRole('button', { name: 'Record observation' }))
    expect(await screen.findByText(/\(teleop\)/)).toBeInTheDocument()
    expect(api.writes()[0].body).toMatchObject({ kind: 'component_unavailable', component: 'teleop' })
  })

  it('shows a refusal as returned (write_not_authorized) and does not post again by itself', async () => {
    const api = mockApi({ ...WRITE_OK, 'POST /strategy/coach-observations': apiError(403, 'write_not_authorized', 'Token rejected') })
    setWriteToken('token')
    observationForm()
    await userEvent.type(screen.getByLabelText('Observed at'), '2099-03-01T09:30')
    await userEvent.click(await screen.findByRole('button', { name: 'Record observation' }))
    expect(await screen.findByText(/write_not_authorized/)).toBeInTheDocument()
    expect(screen.queryByText(/may have been stored/)).toBeNull() // a refusal is a known outcome
    await new Promise((r) => setTimeout(r, 50))
    expect(api.writes()).toHaveLength(1)
  })
})

describe('SaveCoachStrategy', () => {
  it('sends the strategy as shown, with the token and the session name', async () => {
    const api = mockApi({ ...WRITE_OK, 'POST /strategy/coach-strategies': { status: 201, body: { event_key: EVENT,
      match_key: MATCH, strategy: baseline(RED), strategy_sha256: 'e'.repeat(64), origin: 'human_entered',
      author: 'Test Person', created_at: '2099-03-01T09:00:00Z' } } })
    setWriteToken('token')
    renderAt('/', '/', <SaveCoachStrategy eventKey={EVENT} matchKey={MATCH} strategy={baseline(RED)} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Save as a coach strategy' }))
    expect(await screen.findByText(/Stored by Test Person/)).toBeInTheDocument()
    const [post] = api.writes()
    expect(post.headers[WRITE_TOKEN_HEADER]).toBe('token')
    expect(post.body).toEqual({ event_key: EVENT, match_key: MATCH, author: 'Test Person', strategy: baseline(RED) })
  })

  it('warns that a write may have been stored when the connection fails, keeps the button usable, never retries', async () => {
    let release!: () => void
    const api = mockApi({ ...WRITE_OK, 'POST /strategy/coach-strategies': () => new Promise((_, reject) => {
      release = () => reject(new TypeError('connection reset'))
    }) })
    setWriteToken('token')
    renderAt('/', '/', <SaveCoachStrategy eventKey={EVENT} matchKey={MATCH} strategy={baseline(RED)} />)
    const save = await screen.findByRole('button', { name: 'Save as a coach strategy' })
    await userEvent.click(save)
    const busy = screen.getByRole('button', { name: 'Saving…' })
    expect(busy).toHaveAttribute('aria-disabled', 'true') // focus stays on it
    await userEvent.click(busy) // ignored while in flight
    release()
    expect(await screen.findByText(/may have been stored before the connection failed/)).toBeInTheDocument()
    expect(screen.getByText(/network_error/)).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 50))
    expect(api.writes()).toHaveLength(1)
  })

  it('keeps a write in flight across edits: still busy, no second POST, and the outcome says edits are unsaved', async () => {
    let release!: () => void
    const api = mockApi({ ...WRITE_OK, 'POST /strategy/coach-strategies': () => new Promise((resolve) => {
      release = () => resolve({ status: 201, body: { event_key: EVENT, match_key: MATCH, strategy: baseline(RED),
        strategy_sha256: 'f'.repeat(64), origin: 'human_entered', author: 'Test Person', created_at: '2099-03-01T09:00:00Z' } })
    }) })
    setWriteToken('token')
    const original = baseline(RED)
    const edited: Strategy = { ...original, robots: [original.robots[0], original.robots[1],
      { ...original.robots[2], components: ['auto'] }] }
    function Editor() { // the editor changes the strategy prop while the write is in flight, as MatchPage does
      const [strategy, setStrategy] = useState(original)
      return <><button type="button" onClick={() => setStrategy(edited)}>edit</button>
        <SaveCoachStrategy eventKey={EVENT} matchKey={MATCH} strategy={strategy} /></>
    }
    renderAt('/', '/', <Editor />)
    await userEvent.click(await screen.findByRole('button', { name: 'Save as a coach strategy' }))
    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    const busy = await screen.findByRole('button', { name: 'Saving…' }) // the same write, not a fresh instance
    await userEvent.click(busy)
    expect(api.writes()).toHaveLength(1)
    release()
    expect(await screen.findByText(/Stored by Test Person/)).toBeInTheDocument()
    expect(screen.getByText(/your edits\s+since then are not saved/)).toBeInTheDocument()
    expect(api.writes()[0].body).toMatchObject({ strategy: baseline(RED) })
  })

  it('says an accepted write with an unreadable reply was stored, and does not post again', async () => {
    const api = mockApi({ ...WRITE_OK })
    setWriteToken('token')
    renderAt('/', '/', <SaveCoachStrategy eventKey={EVENT} matchKey={MATCH} strategy={baseline(RED)} />)
    const save = await screen.findByRole('button', { name: 'Save as a coach strategy' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>', { status: 201 }))) // after the access probe
    await userEvent.click(save)
    expect(await screen.findByText(/The server accepted the write, but its reply could not be read/)).toBeInTheDocument()
    expect(screen.getByText(/malformed_response/)).toBeInTheDocument()
    expect(api.writes()).toHaveLength(0) // the one POST went to the replaced fetch, once
    expect((globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls).toHaveLength(1)
  })
})

