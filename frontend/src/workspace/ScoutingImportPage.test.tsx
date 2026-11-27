import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ScoutingImportPreview } from '../auth/api'
import { apiError, mockApi } from '../test/mockApi'
import { ScoutingImportPage } from './ScoutingImportPage'
import { checkFile, MAX_FILE_BYTES } from './scoutingImportFile'

// The scouting CSV upload page (audit 2026-11-26, workstream 8). Synthetic files and responses only: invented event,
// teams and scout labels.

const HEADER = 'org_key,year,event_key,match_key,match_number,time,alliance,team_key,scouter,qDefense'
const CSV = `${HEADER}\r\nfrc11,9987,9987zz,9987zz_qm1,1,3/1/2030 10:00:00 AM,red,frc998701,Synthetic Scout,7\r\n`

function preview(overrides: Partial<ScoutingImportPreview> = {}): ScoutingImportPreview {
  return {
    file_sha256: 'a'.repeat(64), filename: 'export.csv', event_key: '9987zz', season: 9987,
    mapping: { defense_rating: { column: 'qDefense', source_min: 1, source_max: 10, not_a_rating: ['0'],
      lowest_rating: 1 }, feeding_rating: null, notes_columns: [] },
    counts: { rows: 3, accepted: 1, rejected: 1, excluded: 0, duplicate: 1, already_imported: 0, conflict: 0 },
    rows: [
      { row: 2, status: 'accepted', reason: null, match_key: '9987zz_qm1', team_number: 998701, defense_rating: 4,
        feeding_rating: null, has_notes: false },
      { row: 3, status: 'duplicate', reason: 'Same match, team and scout as row 2; that row is used.',
        match_key: '9987zz_qm1', team_number: 998701, defense_rating: 4, feeding_rating: null, has_notes: false },
      { row: 4, status: 'rejected', reason: 'Match 9987zz_qm99 is not in StratAI\'s data for 9987zz.',
        match_key: '9987zz_qm99', team_number: 998702, defense_rating: 2, feeding_rating: null, has_notes: false },
    ],
    ...overrides,
  }
}

function renderPage() {
  render(<MemoryRouter><ScoutingImportPage /></MemoryRouter>)
  return userEvent.setup()
}

const file = (text: string, name = 'export.csv') => new File([text], name, { type: 'text/csv' })

afterEach(() => vi.unstubAllGlobals())

describe('checkFile', () => {
  it('accepts a ScoutRadioz export and names what is wrong with anything else', () => {
    expect(checkFile('export.csv', CSV.length, CSV)).toBeNull()
    expect(checkFile('EXPORT.CSV', CSV.length, `﻿${CSV}`)).toBeNull() // any case; a byte-order mark is fine
    expect(checkFile('export.xlsx', 10, CSV)).toMatch(/\.csv file/)
    expect(checkFile('export.csv', 0, '')).toMatch(/empty/)
    expect(checkFile('export.csv', MAX_FILE_BYTES + 1, CSV)).toMatch(/larger than/)
    expect(checkFile('export.csv', 20, 'name,score\r\nx,1\r\n')).toMatch(/missing column\(s\) org_key/)
  })
})

describe('ScoutingImportPage', () => {
  it('previews every row, then imports only after an explicit confirmation', async () => {
    const api = mockApi({
      'POST /workspace/scouting/imports/preview': preview(),
      'POST /workspace/scouting/imports': { ...preview({ counts: { rows: 3, accepted: 0, rejected: 1, excluded: 0,
        duplicate: 1, already_imported: 1, conflict: 0 } }),
        import: { run_id: 7, landed: 1, loaded: 1, not_loaded: [], metrics_recomputed: true } },
    })
    const user = renderPage()
    await user.upload(screen.getByLabelText('CSV file'), file(CSV))
    const tiles = await screen.findByRole('group', { name: 'Rows by outcome' })
    expect(within(tiles).getByText('Will import').previousSibling).toHaveTextContent('1')
    expect(within(tiles).getByText('Duplicate').previousSibling).toHaveTextContent('1')
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(4) // header + 3 rows
    expect(within(table).getByText(/9987zz_qm99 is not in StratAI/)).toBeInTheDocument()
    expect(screen.queryByText(/Synthetic Scout/)).not.toBeInTheDocument()
    expect(api.calls[0].body).toEqual({ filename: 'export.csv', content: CSV })

    const importButton = screen.getByRole('button', { name: 'Import 1 row' })
    expect(importButton).toBeDisabled() // nothing is written until the preview is acknowledged
    expect(api.calls.filter((c) => c.path === '/workspace/scouting/imports')).toHaveLength(0)
    await user.click(screen.getByRole('checkbox', { name: /I have checked the preview/ }))
    await user.click(importButton)
    expect(await screen.findByRole('heading', { name: 'Imported' })).toBeInTheDocument()
    expect(screen.getByText(/1 observation stored for 9987zz/)).toBeInTheDocument()
    const sent = api.calls.find((c) => c.path === '/workspace/scouting/imports')
    expect(sent?.body).toEqual({ filename: 'export.csv', content: CSV, file_sha256: 'a'.repeat(64), confirm: true })
    expect(sent?.headers['X-StratAI-CSRF']).toBe('1')
  })

  it('shows only the rows that will not be imported when asked', async () => {
    mockApi({ 'POST /workspace/scouting/imports/preview': preview() })
    const user = renderPage()
    await user.upload(screen.getByLabelText('CSV file'), file(CSV))
    await screen.findByRole('table')
    await user.click(screen.getByRole('checkbox', { name: /only rows that will not be imported/ }))
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3) // header + 2 problem rows
  })

  it('refuses a file that is not a ScoutRadioz export without sending it', async () => {
    const api = mockApi({})
    const user = renderPage()
    await user.upload(screen.getByLabelText('CSV file'), file('name,score\r\nx,1\r\n'))
    expect(await screen.findByRole('alert')).toHaveTextContent(/not a ScoutRadioz match-scouting export/)
    expect(api.calls).toHaveLength(0)
  })

  it('shows the server refusal, and offers no import when nothing can be imported', async () => {
    mockApi({ 'POST /workspace/scouting/imports/preview': apiError(422, 'mapping_not_configured',
      'No approved column mapping exists for the 9987 scouting form.') })
    const user = renderPage()
    await user.upload(screen.getByLabelText('CSV file'), file(CSV))
    expect(await screen.findByRole('alert')).toHaveTextContent('mapping_not_configured')
    expect(screen.queryByRole('button', { name: /^Import/ })).not.toBeInTheDocument()

    mockApi({ 'POST /workspace/scouting/imports/preview': preview({ counts: { rows: 1, accepted: 0, rejected: 0,
      excluded: 0, duplicate: 0, already_imported: 1, conflict: 0 }, rows: [] }) })
    await user.upload(screen.getByLabelText('CSV file'), file(CSV, 'again.csv'))
    expect(await screen.findByText(/Nothing in this file can be imported/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Import/ })).not.toBeInTheDocument()
  })
})
