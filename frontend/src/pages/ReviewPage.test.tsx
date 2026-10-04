import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Artifact, KappaStatus } from '../api/types'
import { ReviewPage } from './ReviewPage'
import { WRITE_OK, mockApi } from '../test/mockApi'
import { renderPage } from '../test/render'

afterEach(() => vi.unstubAllGlobals())

// Synthetic fixtures: three made-up reference rows and a two-function codebook. Not DM1 evidence.
const examples = [1, 2, 3].map((row_id) => ({ row_id, year: 2090, team: 9000 + row_id, game_name: 'Synthetic',
  micro_archetype: `design ${row_id}`, technical_specifications: 'synthetic', key_characteristic: 'synthetic',
  label: 'curated_reference_unverified' }))

const artifact = (patch: Partial<Artifact>): Artifact => ({ id: 1, kind: 'codebook', season: 2099, author: 'Author',
  version: 1, payload: {}, payload_sha256: 'd'.repeat(64), status: 'submitted', created_at: '2099-01-07T00:00:00Z',
  established_by: null, established_at: null, note: null, ...patch })

const codebook = artifact({ id: 1, status: 'established', established_by: 'Mentor',
  payload: { version: 'cb1', authored_by: 'Author', functions: { intake: 'acquire', shooter: 'score' } } })

const computed: KappaStatus = { state: 'computed', coders: ['Coder A', 'Coder B'], rows: 3, pooled_kappa: 0.71,
  per_function_kappa: { intake: 0.8, shooter: 0.4 },
  status: { overall: 'categories', functions: { intake: 'categories', shooter: 'provisional' } } }

function routes(artifacts: Artifact[], kappa: KappaStatus, extra: Record<string, unknown> = {}) {
  return {
    ...WRITE_OK,
    'GET /human-inputs/seasons/2099/artifacts': artifacts,
    'GET /human-inputs/seasons/2099/kappa': kappa,
    'GET /human-inputs/reference/design-examples': examples,
    'GET /human-inputs/seasons/2099/specs': [],
    'GET /human-inputs/capability-profiles': [],
    ...extra,
  }
}

describe('Human review workflow', () => {
  it('submits an independent coding that labels every reference row', async () => {
    const mock = mockApi(routes([codebook], { state: 'awaiting_codings', coders: [], needed: 'two codings' },
      { 'POST /human-inputs/seasons/2099/artifacts': { status: 201, body: artifact({ kind: 'coding' }) } }))
    renderPage(<ReviewPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByLabelText('row 2 shooter'))
    await user.click(screen.getByRole('button', { name: /Submit independent coding \(3 rows\)/ }))
    await vi.waitFor(() => expect(mock.writes()).toHaveLength(1))
    expect(mock.writes()[0].body).toEqual({ kind: 'coding', author: 'Test Person',
      payload: { labels: { 1: [], 2: ['shooter'], 3: [] } } })
  })

  it('offers the consensus coding only after κ is computed', async () => {
    mockApi(routes([codebook], { state: 'awaiting_codings', coders: ['Coder A'], needed: 'two codings' }))
    renderPage(<ReviewPage />)
    const option = await screen.findByRole('option', { name: /Consensus-meeting coding \(after κ\)/ })
    expect(option).toBeDisabled()
    expect(screen.getByTestId('stage-coding')).toHaveTextContent('incomplete')
  })

  it('shows pooled and per-function κ, with a weak function provisional', async () => {
    mockApi(routes([codebook], computed))
    renderPage(<ReviewPage />)
    const kappa = await screen.findByTestId('kappa')
    expect(kappa).toHaveTextContent('0.710')
    const shooterRow = within(kappa).getByText('shooter').closest('tr')!
    expect(shooterRow).toHaveTextContent('provisional')
  })

  it('lets a named person establish a submitted rubric, and never offers sign-off for codings or reviews', async () => {
    const rubric = artifact({ id: 9, kind: 'rubric', author: 'Rubric Author' })
    const coding = artifact({ id: 10, kind: 'coding', author: 'Coder A' })
    const mock = mockApi(routes([codebook, rubric, coding], computed, {
      'POST /human-inputs/artifacts/9/establish': { ...rubric, status: 'established', established_by: 'Test Person' },
    }))
    renderPage(<ReviewPage />)
    const rubricHistory = await screen.findByTestId('history-rubric')
    expect(within(screen.getByTestId('history-coding')).queryByRole('button', { name: 'Establish' })).not.toBeInTheDocument()
    await userEvent.click(within(rubricHistory).getByRole('button', { name: 'Establish' }))
    await vi.waitFor(() => expect(mock.writes()).toHaveLength(1))
    expect(mock.writes()[0].path).toBe('/human-inputs/artifacts/9/establish')
    expect(mock.writes()[0].body).toEqual({ established_by: 'Test Person', note: '' })
  })

  it('reads every stage from the stored artifacts', async () => {
    mockApi(routes([codebook], computed))
    renderPage(<ReviewPage />)
    expect(await screen.findByTestId('stage-codebook')).toHaveTextContent('established')
    expect(screen.getByTestId('stage-mentor_review')).toHaveTextContent('missing')
    expect(screen.getByTestId('stage-consensus_coding')).toHaveTextContent('missing')
  })
})
