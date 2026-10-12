// Game Manual Manager, season rulesets and readiness (2026-10-11). SYNTHETIC fixture data through a mocked API.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { setWriteToken } from '../api/client'
import { sha256Hex } from '../lib/sha256'
import { WRITE_OFF, WRITE_OK, mockApi } from '../test/mockApi'
import { renderPage } from '../test/render'
import { checkManualFile, countMarkers } from '../lib/manualChecks'
import { ManualsPage } from './ManualsPage'
import { ReadinessPage } from './ReadinessPage'
import { RulesetsPage } from './RulesetsPage'

const MANUAL = { id: 7, season: 2099, game_name: 'SYNTHETICA', filename: 'manual.pdf', media_type: 'application/pdf',
  byte_size: 2048, content_sha256: 'a'.repeat(64), uploaded_by: 'Test Person', uploaded_at: '2099-01-06T12:00:00Z' }
const REPORT = { status: 'succeeded', processor_version: 'manual-proc-v1', manual_sha256: 'a'.repeat(64), season: 2099,
  page_count: 6, text_pages: 6, identity: { seasons_found: [2099], season: 2099, revision: '1.0', team_update: null,
    date: 'January 6, 2099', title_line: 'Game Manual', declared_season: 2099, decision: 'identified',
    reason: 'the title pages name 2099' }, sections: 9, suggestions: 2, extraction_sha256: 'b'.repeat(64),
  warnings: [{ code: 'topic_not_found', topic: 'endgame', message: 'no page mentions endgame' }], authoritative: false,
  note: 'Extraction and suggestions are review aids.' }
const state = (status: string, extra = {}) => ({ manual_id: 7, season: 2099, content_sha256: 'a'.repeat(64),
  processor_version: 'manual-proc-v1', status, attempts: [], report: status === 'succeeded' ? REPORT : null,
  identity_resolution: null, retry_allowed: ['failed', 'not_started'].includes(status), ...extra })
const EXTRACTION = { processor_version: 'manual-proc-v1', manual_sha256: 'a'.repeat(64), season: 2099, page_count: 6,
  identity: REPORT.identity, pages: [], sections: [{ number: '6.1', title: 'Match periods', page: 3 }],
  topics: { scoring: { pages: [4], top_pages: [4], mentions: 3 } },
  suggestions: [{ rule: 'auto_seconds', target: 'game_spec.match_length.auto_seconds', value: 15, page: 3,
    snippet: 'The AUTO period lasts 15 seconds.', status: 'machine_extracted_unverified' }] }
const READINESS = (season: number, extra = {}) => ({ season, coverage: { events: 0, matches: 0, matches_played: 0,
  qualification_matches_played: 0, playoff_matches_played: 0, teams: 0, team_event_epa_rows: 0, team_metrics_rows: 0,
  events_with_metrics: 0, scouting_observations: 0, latest_update: null, latest_match: null,
  score_breakdown_adapter: false, has_data: false },
human_inputs: { manuals: [], game_spec: null, ruleset: { approved: null, latest: null } },
features: [{ key: 'game_manual', name: 'Game manual processing', consumes: ['uploaded manual'], available: false,
  reasons: ['no manual has been uploaded and processed for this season'], route: '/manuals', requires_human: 'upload the official manual' }],
automation_boundary: { automatic: ['manual validation'], never_automatic: ['season ruleset approval (P6-M1)'] }, ...extra })

function pdf(name = 'manual.pdf', body = '%PDF-1.7 synthetic', type = 'application/pdf') {
  return new File([body], name, { type })
}

afterEach(() => { setWriteToken(''); vi.useRealTimers() })

describe('checkManualFile', () => {
  it('accepts a PDF and refuses empty, oversized, wrong-type and headerless files', async () => {
    expect(await checkManualFile(pdf())).toBeNull()
    expect(await checkManualFile(pdf('m.pdf', ''))).toMatch(/empty/)
    expect(await checkManualFile(pdf('notes.txt', '%PDF-1.7', 'text/plain'))).toMatch(/PDF file/)
    expect(await checkManualFile(pdf('m.pdf', 'GIF89a not a pdf'))).toMatch(/does not start with %PDF-/)
    const big = pdf()
    Object.defineProperty(big, 'size', { value: 101 * 1024 * 1024 })
    expect(await checkManualFile(big)).toMatch(/limit is 100 MB/)
  })
})

describe('ManualsPage', () => {
  it('uploads, starts processing automatically, polls to success and shows the unverified extraction', async () => {
    let status = 'running'
    const api = mockApi({
      ...WRITE_OK,
      'GET /human-inputs/game-manuals': () => (status === 'idle' ? [] : [MANUAL]),
      'POST /human-inputs/game-manuals': { status: 201, body: { manual: MANUAL, created: true } },
      'POST /human-inputs/game-manuals/7/processing': state('running', { claimed: true }),
      'GET /human-inputs/game-manuals/7/processing': () => state(status),
      'GET /human-inputs/game-manuals/7/extraction': EXTRACTION,
      'GET /human-inputs/game-manuals/7/pages': [{ page: 3, chars: 40, text_sha256: 'c'.repeat(64), error: null,
        text: 'The AUTO period lasts 15 seconds.' }],
      'GET /human-inputs/seasons/2099/readiness': READINESS(2099),
    })
    setWriteToken('t')
    renderPage(<ManualsPage />)
    await waitFor(() => expect(screen.getByLabelText('Manual PDF')).toBeInTheDocument())
    await userEvent.type(screen.getByLabelText('Game name'), 'SYNTHETICA')
    expect(api.writes()).toHaveLength(0)
    status = 'succeeded'
    await waitFor(() => expect(screen.getByText(/Processing — manual #7/)).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText(/the title pages name 2099/)).toBeInTheDocument(), { timeout: 4000 })
    expect(screen.getByText(/no page mentions endgame/)).toBeInTheDocument()
    expect(await screen.findByText(/Machine-extracted and unverified/)).toBeInTheDocument()
    expect(screen.getByText('The AUTO period lasts 15 seconds.')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'p. 3' })[0])
    expect(await screen.findByTestId('page-text')).toHaveTextContent('The AUTO period lasts 15 seconds.')
  })

  it('refuses to process when the server checksum differs from the file checksum', async () => {
    const api = mockApi({
      ...WRITE_OK,
      'GET /human-inputs/game-manuals': [],
      'POST /human-inputs/game-manuals': { status: 201, body: { manual: { ...MANUAL, content_sha256: 'x' }, created: true } },
      'GET /human-inputs/seasons/2099/readiness': READINESS(2099),
    })
    setWriteToken('t')
    renderPage(<ManualsPage />)
    await screen.findByLabelText('Manual PDF')
    fireEvent.change(screen.getByLabelText('Manual PDF'), { target: { files: [pdf()] } })
    await userEvent.type(screen.getByLabelText('Game name'), 'SYNTHETICA')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Upload and process' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Upload and process' }))
    expect(await screen.findByText(/does not match this file's/)).toBeInTheDocument()
    expect(api.writes().map((w) => w.path)).toEqual(['/human-inputs/game-manuals']) // no processing request
  })

  it('posts the upload then the processing request, never more', async () => {
    const file = pdf()
    const sha = await sha256Hex(await file.arrayBuffer())
    const api = mockApi({
      ...WRITE_OK,
      'GET /human-inputs/game-manuals': [],
      'POST /human-inputs/game-manuals': { status: 201, body: { manual: { ...MANUAL, content_sha256: sha }, created: true } },
      'POST /human-inputs/game-manuals/7/processing': state('running', { claimed: true }),
      'GET /human-inputs/game-manuals/7/processing': state('running'),
      'GET /human-inputs/seasons/2099/readiness': READINESS(2099),
    })
    setWriteToken('t')
    renderPage(<ManualsPage />)
    await screen.findByLabelText('Manual PDF')
    fireEvent.change(screen.getByLabelText('Manual PDF'), { target: { files: [file] } })
    await userEvent.type(screen.getByLabelText('Game name'), 'SYNTHETICA')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Upload and process' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Upload and process' }))
    await waitFor(() => expect(api.writes().map((w) => `${w.method} ${w.path}`)).toEqual(
      ['POST /human-inputs/game-manuals', 'POST /human-inputs/game-manuals/7/processing']))
    expect(api.writes()[1].body).toEqual({ requested_by: 'Test Person' })
  })

  it('refuses a non-PDF before any request', async () => {
    const api = mockApi({ ...WRITE_OK, 'GET /human-inputs/game-manuals': [],
      'GET /human-inputs/seasons/2099/readiness': READINESS(2099) })
    setWriteToken('t')
    renderPage(<ManualsPage />)
    await screen.findByLabelText('Manual PDF')
    fireEvent.change(screen.getByLabelText('Manual PDF'), { target: { files: [pdf('notes.txt', 'hello', 'text/plain')] } })
    expect(await screen.findByText('Choose a PDF file.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload and process' })).toBeDisabled()
    expect(api.writes()).toHaveLength(0)
  })

  it('offers a retry after a failure and shows the error', async () => {
    mockApi({ ...WRITE_OK, 'GET /human-inputs/game-manuals': [MANUAL],
      'GET /human-inputs/game-manuals/7/processing': state('failed', { attempts: [{ attempt: 1, status: 'failed',
        error: { code: 'wrong_season', message: 'the title pages name [2098]' } }] }),
      'GET /human-inputs/seasons/2099/readiness': READINESS(2099) })
    setWriteToken('t')
    renderPage(<ManualsPage />)
    expect(await screen.findByRole('button', { name: 'Retry processing' })).toBeInTheDocument()
    await userEvent.click(screen.getByText(/Processing attempts/))
    expect(screen.getByText(/wrong_season: the title pages name \[2098\]/)).toBeInTheDocument()
  })

  it('asks a named person to resolve an unidentifiable season', async () => {
    const api = mockApi({ ...WRITE_OK, 'GET /human-inputs/game-manuals': [MANUAL],
      'GET /human-inputs/game-manuals/7/processing': state('needs_resolution'),
      'POST /human-inputs/game-manuals/7/identity-resolution': state('needs_resolution', { retry_allowed: true }),
      'POST /human-inputs/game-manuals/7/processing': state('running', { claimed: true }),
      'GET /human-inputs/seasons/2099/readiness': READINESS(2099) })
    setWriteToken('t')
    renderPage(<ManualsPage />)
    const button = await screen.findByRole('button', { name: 'Confirm this is the 2099 manual' })
    expect(button).toBeDisabled() // a note is required
    await userEvent.type(screen.getByLabelText('Resolution note'), 'Checked the cover and footer')
    await userEvent.click(button)
    await waitFor(() => expect(api.writes()[0].body).toEqual({ season: 2099, resolved_by: 'Test Person',
      note: 'Checked the cover and footer' }))
  })

  it('hides every write control without write access', async () => {
    mockApi({ ...WRITE_OFF, 'GET /human-inputs/game-manuals': [MANUAL],
      'GET /human-inputs/game-manuals/7/processing': state('failed'),
      'GET /human-inputs/seasons/2099/readiness': READINESS(2099) })
    renderPage(<ManualsPage />)
    expect((await screen.findAllByText(/Writes are disabled on this server/)).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('Manual PDF')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Retry processing' })).toBeNull()
  })
})

const RULESET = { id: 41, season: 2099, version: 2, ruleset_json: { game_name: 'SYNTHETICA', manual: { title: 'M', version: '1' },
  alliance_counts: [{ min_teams: 1, max_teams: null, alliances: 8 }], brackets: [{}], selection_variants: [], event_exclusions: [],
  tie_rule: 'replay' }, ruleset_sha256: 'f'.repeat(64), status: 'awaiting_review', created_by: 'Author A',
created_at: '2099-01-07T00:00:00Z', submitted_at: '2099-01-07T01:00:00Z', reviewed_by: null, reviewed_at: null, review_note: null }
const CHECKLIST = { items: Array.from({ length: 14 }, (_, i) => ({ id: `R${i + 1}`, title: `item ${i + 1}` })),
  guide: 'guide', control: 'control', r15: 'r15' }

describe('RulesetsPage', () => {
  it('counts UNVERIFIED markers', () => {
    expect(countMarkers('a UNVERIFIED (carried from 2026): x and UNVERIFIED (carried from 2026): y')).toBe(2)
  })

  it('approves only with a qualification, every checklist item and the exact sha256', async () => {
    const api = mockApi({ ...WRITE_OK, 'GET /human-inputs/rulesets': [RULESET],
      'GET /human-inputs/ruleset-review-checklist': CHECKLIST,
      'POST /human-inputs/rulesets/41/review': { ruleset: { ...RULESET, status: 'approved' },
        approval_record: { path: 'P6_M1_APPROVAL_2099_v2.json', next_step: 'commit' } } })
    setWriteToken('t')
    renderPage(<RulesetsPage />)
    const form = await screen.findByTestId('review-form')
    const approve = within(form).getByRole('button', { name: 'Approve' })
    expect(approve).toBeDisabled()
    await userEvent.type(within(form).getByLabelText('Qualification'), 'SYNTHETIC qualification')
    for (let i = 1; i <= 14; i += 1) await userEvent.click(within(form).getByLabelText(`R${i}`))
    expect(approve).toBeDisabled() // no sha yet
    await userEvent.type(within(form).getByLabelText('Verified sha256'), '0'.repeat(64))
    expect(approve).toBeDisabled() // wrong sha
    await userEvent.clear(within(form).getByLabelText('Verified sha256'))
    await userEvent.type(within(form).getByLabelText('Verified sha256'), 'f'.repeat(64))
    expect(approve).toBeEnabled()
    await userEvent.click(approve)
    await waitFor(() => expect(api.writes()).toHaveLength(1))
    expect(api.writes()[0].body).toMatchObject({ reviewer: 'Test Person', approve: true, verified_sha256: 'f'.repeat(64) })
    expect(await screen.findByText(/commit it \(R15\)/)).toBeInTheDocument()
  })

  it('never offers approval for a version with UNVERIFIED markers', async () => {
    const marked = { ...RULESET, ruleset_json: { ...RULESET.ruleset_json, tie_rule: 'UNVERIFIED (carried from 2026): replay' } }
    mockApi({ ...WRITE_OK, 'GET /human-inputs/rulesets': [marked], 'GET /human-inputs/ruleset-review-checklist': CHECKLIST })
    setWriteToken('t')
    renderPage(<RulesetsPage />)
    expect(await screen.findByText(/cannot be approved/)).toBeInTheDocument()
    expect(within(screen.getByTestId('review-form')).getByRole('button', { name: 'Approve' })).toBeDisabled()
  })

  it('starts a draft from the worksheet and saves it under the person\'s name', async () => {
    const api = mockApi({ ...WRITE_OK, 'GET /human-inputs/rulesets': [], 'GET /human-inputs/ruleset-review-checklist': CHECKLIST,
      'GET /human-inputs/seasons/2099/ruleset-worksheet': { season: 2099, template_from_season: 2026, template_ruleset_id: 6,
        manual: null, proposal: { season: 2099, tie_rule: 'UNVERIFIED (carried from 2026): replay' }, schema_errors: [],
        verify: [{ path: 'tie_rule', reason: 'carried from 2026; marked', suggestions: [], manual_pages: [] }],
        unverified_marker: 'UNVERIFIED (carried from', saved: false, note: 'n' },
      'POST /human-inputs/rulesets': { status: 201, body: { ...RULESET, status: 'draft' } } })
    setWriteToken('t')
    renderPage(<RulesetsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Start from a worksheet' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Edit as a new draft' }))
    expect(await screen.findByText(/still carry an/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save as draft' }))
    await waitFor(() => expect(api.writes()[0]?.body).toMatchObject({ created_by: 'Test Person',
      ruleset_json: { season: 2099 } }))
  })
})

describe('ReadinessPage', () => {
  it('shows the 2027 Phase 6 tasks with the next human action and the done-means as recorded', async () => {
    const task = (id: string, status: string, extra = {}) => ({ id, title: `task ${id}`, actor: 'Kanav', kind: 'authorization',
      status, evidence: `decisions/${id}.json`, evidence_exists: status === 'done', depends_on: [], waiting_on: [],
      automatic: false, authorizes: 'nothing', never_by_manual_upload: true, ...extra })
    mockApi({ ...WRITE_OK, 'GET /human-inputs/seasons/2099/readiness': READINESS(2099, { phase6: {
      tasks: [task('R1', 'ready_for_human', { title: 'Approve the 2027 season ruleset (P6-M1)' }), task('R8', 'done'),
        task('R5', 'blocked', { waiting_on: ['R4'] })],
      done_means: [{ done_means: 'P6-DM1', met: false }, { done_means: 'P6-DM2', met: true }],
      status: 'waiting for the 2027 manual; Phase 6 is not complete' } }) })
    renderPage(<ReadinessPage />)
    expect(await screen.findByText(/Your next action/)).toBeInTheDocument()
    expect(screen.getByText(/R1 — Approve the 2027 season ruleset/)).toBeInTheDocument()
    expect(within(screen.getByTestId('phase6-tasks')).getByText('blocked')).toBeInTheDocument()
    expect(screen.getByText(/P6-DM1/).parentElement).toHaveTextContent('not met')
    expect(screen.getByText(/Uploading a manual never completes or authorizes any of these/)).toBeInTheDocument()
    expect(screen.getByTestId('no-season-data')).toBeInTheDocument()
  })
})
