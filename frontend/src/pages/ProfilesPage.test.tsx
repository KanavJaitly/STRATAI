import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Profile } from '../api/types'
import { ProfilesPage } from './ProfilesPage'
import { WRITE_OK, apiError, mockApi } from '../test/mockApi'
import { renderPage } from '../test/render'

afterEach(() => vi.unstubAllGlobals())

const profile = (patch: Partial<Profile> = {}): Profile => ({
  id: 1, profile_key: 'synthetic-a', version: 2, raw_payload_id: 10, based_on_id: null, status: 'active',
  created_by: 'Test Person', created_at: '2099-01-06T00:00:00Z',
  payload: { profile_id: 'synthetic-a', submitted_at: '2099-01-06T00:00:00Z', team_number: null, budget_usd: 5000,
    manufacturing: 2, programming: 1, mentoring: 2, notes: '' },
  ...patch,
})

const recommendation = {
  label: 'heuristic_not_validated_against_outcomes', profile_id: 'synthetic-a', profile_version: 2, season: 2099,
  rubric_version: 'r1', rubric_sha256: 'c'.repeat(64), realistic_ceiling_tier: 2, recommended_archetype: 'arch-b',
  achievable_features: ['feature-1'], candidate_archetypes: ['arch-b'], candidates_note: 'from the action map',
  limitations: ['the rubric is human-authored and deterministic; it is not fit to outcomes'],
  explanation: [
    { archetype: 'arch-a', tier: 3, priority: 1, feasible: false, candidate: false, requirements_met: [],
      requirements_unmet: ['programming >= 3 (have 1)'], achievable_features: [] },
    { archetype: 'arch-b', tier: 2, priority: 2, feasible: true, candidate: true,
      requirements_met: ['budget >= 1000 (have 5000)'], requirements_unmet: [], achievable_features: ['feature-1'] },
  ],
}

function routes(extra: Record<string, unknown> = {}) {
  return {
    ...WRITE_OK,
    'GET /human-inputs/capability-profiles': [profile()],
    'GET /human-inputs/capability-profiles/synthetic-a/history': [profile({ version: 1, status: 'superseded' }), profile()],
    'GET /human-inputs/capability-profiles/synthetic-a/recommendation': recommendation,
    ...extra,
  }
}

describe('Team capability profiles', () => {
  it('creates a profile with the M9 fields', async () => {
    const mock = mockApi(routes({ 'POST /human-inputs/capability-profiles': { status: 201, body: profile({ profile_key: 'new-one' }) } }))
    renderPage(<ProfilesPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'New profile' }))
    await user.type(screen.getByLabelText('Profile key'), 'new-one')
    await user.type(screen.getByLabelText('Budget'), '2500')
    await user.selectOptions(screen.getByLabelText('manufacturing'), '1')
    await user.selectOptions(screen.getByLabelText('programming'), '2')
    await user.selectOptions(screen.getByLabelText('mentoring'), '0')
    await user.click(screen.getByRole('button', { name: 'Create profile' }))
    await vi.waitFor(() => expect(mock.writes()).toHaveLength(1))
    expect(mock.writes()[0].body).toEqual({ profile_key: 'new-one', created_by: 'Test Person',
      payload: { team_number: null, budget_usd: 2500, manufacturing: 1, programming: 2, mentoring: 0, notes: '' } })
  })

  it('edits by saving a new version (PUT), never in place', async () => {
    const mock = mockApi(routes({ 'PUT /human-inputs/capability-profiles/synthetic-a': profile({ version: 3 }) }))
    renderPage(<ProfilesPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'view' }))
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    expect(screen.getByText(/Saving creates version 3; version 2 is kept/)).toBeInTheDocument()
    const budget = screen.getByLabelText('Budget')
    await user.clear(budget)
    await user.type(budget, '6000')
    await user.click(screen.getByRole('button', { name: 'Save new version' }))
    await vi.waitFor(() => expect(mock.writes()).toHaveLength(1))
    expect(mock.writes()[0].method).toBe('PUT')
    expect((mock.writes()[0].body as { payload: { budget_usd: number } }).payload.budget_usd).toBe(6000)
  })

  it('duplicates under a new key and archives by a named person', async () => {
    const mock = mockApi(routes({
      'POST /human-inputs/capability-profiles/synthetic-a/duplicate': { status: 201, body: profile({ profile_key: 'copy' }) },
      'POST /human-inputs/capability-profiles/synthetic-a/archive': profile({ status: 'archived' }),
    }))
    renderPage(<ProfilesPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'view' }))
    await user.click(screen.getByRole('button', { name: 'Duplicate' }))
    await user.type(screen.getByLabelText('New profile key'), 'copy')
    await user.click(screen.getByRole('button', { name: 'Create copy' }))
    await vi.waitFor(() => expect(mock.writes()).toHaveLength(1))
    expect(mock.writes()[0].body).toEqual({ new_key: 'copy', created_by: 'Test Person' })
  })

  it('shows the deterministic M9 output with its heuristic label, limitations and reasoning', async () => {
    mockApi(routes())
    renderPage(<ProfilesPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'view' }))
    const rec = await screen.findByTestId('recommendation')
    expect(rec).toHaveTextContent('heuristic_not_validated_against_outcomes')
    expect(rec).toHaveTextContent('tier 2')
    expect(rec).toHaveTextContent('arch-b')
    expect(rec).toHaveTextContent('it is not fit to outcomes')
    expect(within(rec).getByText('programming >= 3 (have 1)')).toBeInTheDocument()
  })

  it('says why there is no recommendation instead of guessing one', async () => {
    mockApi(routes({ 'GET /human-inputs/capability-profiles/synthetic-a/recommendation':
      apiError(409, 'prerequisite_missing', 'no established 2099 feasibility rubric yet') }))
    renderPage(<ProfilesPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'view' }))
    expect(await screen.findByText(/no established 2099 feasibility rubric yet/)).toBeInTheDocument()
    expect(screen.queryByTestId('recommendation')).not.toBeInTheDocument()
  })
})
