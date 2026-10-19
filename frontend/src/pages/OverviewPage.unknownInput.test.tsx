// P8-D1 D1.2 ruling (2026-10-19): an input type the Overview has no page for is listed without a link, so it can never
// send the person to `/` (the dashboard). A separate file: the Phase 5 Overview tests stay unchanged.

import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { OverviewPage } from './OverviewPage'
import { WRITE_OK, mockApi } from '../test/mockApi'
import { renderPage } from '../test/render'

afterEach(() => vi.unstubAllGlobals())

describe('Overview: an unknown input type', () => {
  it('is listed as served with a clear no-page note and no link; known inputs keep their links', async () => {
    mockApi({ ...WRITE_OK, 'GET /human-inputs/seasons/2099/dm1-status': {
      season: 2099, inputs_ready: false, note: '',
      items: [{ artifact: 'game_manual', state: 'missing', provided: false, detail: null },
        { artifact: 'some_future_input', state: 'missing', provided: false, detail: null }],
      done_means: { done_means: 'DM1', met: false, missing_records: [], within_5_days: null, elapsed_hours: null,
        blocked_on: [] } } })
    renderPage(<OverviewPage />)
    const unknown = await screen.findByTestId('dm1-some_future_input')
    expect(within(unknown).getByText('some_future_input')).toBeInTheDocument()
    expect(within(unknown).getByText('no input page for this item in this app')).toBeInTheDocument()
    expect(within(unknown).queryByRole('link')).toBeNull()
    expect(document.querySelector('a[href="/"]')).toBeNull()
    expect(within(screen.getByTestId('dm1-game_manual')).getByRole('link', { name: 'Official game manual (PDF)' }))
      .toHaveAttribute('href', '/game')
  })
})
