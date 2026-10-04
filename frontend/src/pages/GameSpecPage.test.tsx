import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SpecVersion } from '../api/types'
import { GameSpecPage } from './GameSpecPage'
import { sha256Hex } from '../lib/sha256'
import { WRITE_OFF, WRITE_OK, apiError, mockApi } from '../test/mockApi'
import { renderPage } from '../test/render'

afterEach(() => vi.unstubAllGlobals())

const workflow = (spec_state: string, extra = {}) => ({
  season: 2099, source_uploaded: false, manuals: 0, spec_versions: 0, spec_state, approved_version: null,
  entry_started_at: null, note: 'Uploading the manual validates nothing.', ...extra,
})

const version = (patch: Partial<SpecVersion>): SpecVersion => ({
  id: 7, season: 2099, version: 1, spec_json: { game_name: 'Synthetic' }, complete: false,
  validation_errors: [{ field: 'match_length', message: 'Field required' }], spec_sha256: null, manual_id: null,
  based_on_id: null, status: 'draft', created_by: 'Test Person', created_at: '2099-01-05T12:00:00Z',
  entry_started_at: '2099-01-05T12:00:00Z', submitted_at: null, reviewed_by: null, reviewed_at: null, review_note: null,
  ...patch,
})

const manual = { id: 3, season: 2099, game_name: 'Synthetic', filename: 'manual.pdf', media_type: 'application/pdf',
  byte_size: 2048, content_sha256: 'a'.repeat(64), uploaded_by: 'Test Person', uploaded_at: '2099-01-04T00:00:00Z' }

async function chooseAndUpload(content: string) {
  const user = userEvent.setup()
  await user.upload(await screen.findByLabelText('Manual PDF'), new File([content], 'manual.pdf', { type: 'application/pdf' }))
  await user.type(screen.getByLabelText('Game name'), 'Synthetic')
  await screen.findByText(/This file's sha256/)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Upload manual' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'Upload manual' }))
}

function base(specs: SpecVersion[] = [], state = 'no_structured_spec', access: object = WRITE_OK) {
  return {
    ...access,
    'GET /human-inputs/seasons/2099/workflow': workflow(state),
    'GET /human-inputs/game-manuals': [],
    'GET /human-inputs/seasons/2099/specs': specs,
  }
}

describe('Game manual and spec workflow', () => {
  it('shows the workflow state and that an upload validates nothing', async () => {
    mockApi(base())
    renderPage(<GameSpecPage />)
    expect(await screen.findByText(/Uploading the manual validates nothing/)).toBeInTheDocument()
    expect(screen.getByLabelText('Workflow state')).toHaveTextContent('Source uploaded')
  })

  it('uploads the PDF with its metadata and reports a re-upload as the existing manual, not a replacement', async () => {
    const bytes = '%PDF-1.7 synthetic'
    const sha = await sha256Hex(new TextEncoder().encode(bytes).buffer as ArrayBuffer)
    const mock = mockApi({ ...base(), 'POST /human-inputs/game-manuals':
      { status: 200, body: { manual: { ...manual, content_sha256: sha }, created: false } } })
    renderPage(<GameSpecPage />)
    await chooseAndUpload(bytes)
    expect(await screen.findByText(/already manual #3. Nothing was replaced or duplicated/)).toBeInTheDocument()
    const upload = mock.writes()[0]
    expect(upload.headers['Content-Type']).toBe('application/pdf')
    expect(upload.query.get('uploaded_by')).toBe('Test Person')
    expect(upload.query.get('season')).toBe('2099')
  })

  it("refuses to report success when the server's checksum differs from the file's", async () => {
    mockApi({ ...base(), 'POST /human-inputs/game-manuals': { status: 201, body: { manual, created: true } } })
    renderPage(<GameSpecPage />)
    await chooseAndUpload('%PDF-1.7 synthetic')
    expect(await screen.findByRole('alert')).toHaveTextContent(/does not match this file's/)
    expect(screen.queryByText(/Stored as manual/)).not.toBeInTheDocument()
  })

  it('saves a blank-started draft as a new version without inventing any rules', async () => {
    const saved = version({})
    const mock = mockApi({ ...base(), 'POST /human-inputs/seasons/2099/specs': { status: 201, body: saved } })
    renderPage(<GameSpecPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'New blank version' }))
    await user.type(screen.getByLabelText('Spec game name'), 'Synthetic')
    await user.click(screen.getByRole('button', { name: 'Save as new version' }))
    await screen.findByText('Saved as a new version.')
    const body = mock.writes()[0].body as { spec_json: Record<string, unknown>; created_by: string; based_on_id: null }
    expect(body.created_by).toBe('Test Person')
    expect(body.based_on_id).toBeNull()
    expect(body.spec_json).toEqual({ game_name: 'Synthetic', match_length: {}, scoring_actions: [], ranking_point_rules: [],
      field_elements: [], source: {} })
  })

  it('keeps an incomplete draft out of review and lists what is missing', async () => {
    mockApi(base([version({})], 'structured_spec_incomplete'))
    renderPage(<GameSpecPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'view' }))
    const detail = screen.getByTestId('spec-detail')
    expect(within(detail).getByText(/Still incomplete/)).toBeInTheDocument()
    expect(within(detail).getByText('match_length')).toBeInTheDocument()
    expect(within(detail).getByRole('button', { name: 'Submit for human review' })).toBeDisabled()
  })

  it('needs a note to return a spec, and records the named reviewer on approval', async () => {
    const awaiting = version({ status: 'awaiting_review', complete: true, validation_errors: [], spec_sha256: 'b'.repeat(64) })
    const mock = mockApi({
      ...base([awaiting], 'awaiting_human_review'),
      'POST /human-inputs/specs/7/review': { ...awaiting, status: 'approved', reviewed_by: 'Test Person' },
    })
    renderPage(<GameSpecPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'view' }))
    expect(screen.getByRole('button', { name: 'Return for changes' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Review note'), { target: { value: 'checked against §6' } })
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await screen.findByText('Approved.')
    expect(mock.writes()[0].body).toEqual({ reviewer: 'Test Person', approve: true, note: 'checked against §6' })
  })

  it('shows the server refusing a state change', async () => {
    const draft = version({ complete: true, validation_errors: [] })
    mockApi({ ...base([draft], 'draft_complete_not_submitted'),
      'POST /human-inputs/specs/7/submit': apiError(409, 'invalid_state', 'spec 7 is approved, not draft') })
    renderPage(<GameSpecPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'view' }))
    await userEvent.click(screen.getByRole('button', { name: 'Submit for human review' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid_state')
  })

  it('offers no write controls when the server has writes disabled', async () => {
    mockApi(base([], 'no_structured_spec', WRITE_OFF))
    renderPage(<GameSpecPage />)
    expect((await screen.findAllByText(/Writes are disabled on this server/)).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('Manual PDF')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New blank version' })).not.toBeInTheDocument()
  })
})
