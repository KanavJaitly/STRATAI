import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { OverviewPage } from './OverviewPage'
import { WRITE_OK, mockApi } from '../test/mockApi'
import { renderPage } from '../test/render'

afterEach(() => vi.unstubAllGlobals())

const items = ['game_manual', 'game_spec', 'catalog_specs', 'codebook', 'independent_codings', 'codebook_agreement',
  'consensus_coding', 'action_function_map', 'rubric', 'team_profiles', 'mentor_review']

function status(provided: boolean, met: boolean) {
  return {
    season: 2099, inputs_ready: provided, note: 'DM1 is met only by the write-once records.',
    items: items.map((artifact) => ({ artifact, state: provided ? 'established' : 'missing', provided, detail: null })),
    done_means: { done_means: 'DM1', met, missing_records: met ? [] : ['dm1_dry_run.json'], within_5_days: null,
      elapsed_hours: null, blocked_on: met ? [] : ['required human input'] },
  }
}

describe('Overview', () => {
  it('lists every DM1 input with its state', async () => {
    mockApi({ ...WRITE_OK, 'GET /human-inputs/seasons/2099/dm1-status': status(false, false) })
    renderPage(<OverviewPage />)
    expect(await screen.findByTestId('dm1-codebook')).toHaveTextContent('missing')
    for (const item of items) expect(screen.getByTestId(`dm1-${item}`)).toBeInTheDocument()
  })

  it('shows DM1 not met even when every input is entered: only the write-once records decide', async () => {
    mockApi({ ...WRITE_OK, 'GET /human-inputs/seasons/2099/dm1-status': status(true, false) })
    renderPage(<OverviewPage />)
    expect(await screen.findByTestId('dm1-verdict')).toHaveTextContent('DM1: NOT MET')
    expect(screen.getByText('all present')).toBeInTheDocument()
  })
})
