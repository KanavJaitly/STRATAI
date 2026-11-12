import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AlliancePlanResponse, P11APlan } from '../auth/api'
import { axeViolations } from '../test/dashboard'
import { apiError, mockApi } from '../test/mockApi'
import { ExpectedScorePlan } from './ExpectedScorePlan'

// P11A (experimental) panel. Synthetic fixture data only (teams 1-24): nothing here is evidence about any real team.

const PATH = 'GET /workspace/alliance-selection/drafts/5/plan'

function envelope(overrides: Partial<AlliancePlanResponse> = {}): AlliancePlanResponse {
  return { record_id: 5, record_seq: 2, computed_at: '2099-03-03T16:00:06Z', source: 'p11a_expected_score_plan',
    experimental: true, relation_to_recommendations: 'separate', status: 'current', withheld: null,
    timing_ms: { total: 40 }, plan: null, ...overrides }
}

function plan(overrides: Partial<P11APlan> = {}): P11APlan {
  const card = (rank: number, team: number, value: number) => ({
    rank, team_number: team, expected_alliance_score: value, estimation_interval_80: [value - 4, value + 4],
    interval_note: 'not calibrated', lineup: [1, team, 20],
    robot: { team_number: team, labels: [], n: 10, partners: 18, components: {} },
    availability: 'confirmed_available' as const, statements: ['Expected alliance score ... (not a chance of winning)'],
    scouting: null, conditional_seconds: [{ team_number: 20, expected_alliance_score: value }] })
  return {
    snapshot_id: 'ab'.repeat(32), record_seq: 2, event_key: '2099synth', as_of: '2099-03-03T15:00:00Z',
    mode: 'captain', seed: 1, members: [1], picks_remaining: 2, turns_before: 0,
    objective: 'expected_alliance_score', unit: 'points',
    win_probability: { status: 'not_available', reason: 'no validated opponent model' },
    validation_status: 'not_validated', interval_status: 'not_calibrated', thresholds_status: 'candidate_unapproved',
    availability_model: 'not_modelled',
    availability: { confirmed_available: [2, 3], confirmed_unavailable: [], no_estimate: [], predicted: null },
    fit_diagnostics: Object.fromEntries(['auto', 'teleop', 'endgame'].map((c) => [c, { sigma2: 30, tau2: 40, rows: 80,
      degenerate: false, sigma2_zero_lr: 100, residual_df: 56, collapse_screen: { ratio: 0.2, threshold: 0.05,
        flagged: false, status: 'non_authoritative' as const, note: 'non-authoritative' } }])),
    versions: {}, known_limitations: ['E2 benchmark: nominal 80% intervals covered 68%'], stage: 'first_pick',
    cards: [card(1, 24, 151.2), card(2, 23, 149.8)],
    comparisons: [{ a: 24, b: 23, compared: 'difference', p_delta_positive: 0.71, delta_mean: 1.4,
      delta_interval_80: [-2, 5], outcome: 'unresolved', reason: 'comparison_threshold_not_approved' }],
    backup_combinations: [], combinations_note: null, ...overrides }
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('expected-score plan (P11A, experimental)', () => {
  it('is closed by default and makes no request until opened', async () => {
    const api = mockApi({ [PATH]: envelope({ plan: plan() }) })
    render(<ExpectedScorePlan recordId={5} seq={2} />)
    expect(screen.getByText('experimental')).toBeInTheDocument()
    expect(api.calls).toHaveLength(0)
    await userEvent.click(screen.getByText('Expected-score plan'))
    const region = screen.getByRole('region', { name: 'Expected-score plan (experimental)' })
    expect(await within(region).findByText('24')).toBeInTheDocument()
    expect(api.calls).toHaveLength(1)
  })

  it('labels expected points, not a chance of winning, and declares nothing different', async () => {
    mockApi({ [PATH]: envelope({ plan: plan() }) })
    const { container } = render(<ExpectedScorePlan recordId={5} seq={2} />)
    await userEvent.click(screen.getByText('Expected-score plan'))
    expect(await screen.findByText('151.2 pts')).toBeInTheDocument()
    expect(screen.getByText(/not by chance of winning/)).toBeInTheDocument()
    expect(screen.getByText(/every comparison is unresolved/)).toBeInTheDocument()
    expect(screen.queryByText(/\d+(\.\d+)?\s*%\s*(chance|win)/i)).not.toBeInTheDocument()
    expect(await axeViolations(container)).toEqual([])
  })

  it('says why the plan is withheld (no approved scoring configuration)', async () => {
    mockApi({ [PATH]: envelope({ status: 'withheld', withheld: { code: 'scoring_config_not_approved',
      message: 'x' } }) })
    render(<ExpectedScorePlan recordId={5} seq={2} />)
    await userEvent.click(screen.getByText('Expected-score plan'))
    expect(await screen.findByText(/No season scoring configuration has been reviewed and approved/))
      .toBeInTheDocument()
  })

  it('shows a non-captain the alliances it could join, without an invitation likelihood', async () => {
    mockApi({ [PATH]: envelope({ plan: plan({ mode: 'non_captain', stage: null, cards: null, comparisons: null,
      destinations: [{ seed: 2, members: [2], expected_alliance_score: 140.3, lineup: [2, 1, 9] }],
      invitation_likelihood: { status: 'withheld', reason: 'pick_model_unavailable' },
      note: 'You do not choose your partners.' }) }) })
    render(<ExpectedScorePlan recordId={5} seq={2} />)
    await userEvent.click(screen.getByText('Expected-score plan'))
    expect(await screen.findByText(/Alliance 2 \(2\): 140.3 pts expected/)).toBeInTheDocument()
    expect(screen.getByText(/Invitation likelihood is not estimated/)).toBeInTheDocument()
  })

  it('keeps the previous plan visible, marked out of date with the reason, when a refresh fails (criterion 12)',
    async () => {
      let fail = false
      mockApi({ [PATH]: () => (fail ? apiError(500, 'internal_error', 'recalculation failed') : envelope({ plan: plan() })) })
      const { rerender } = render(<ExpectedScorePlan recordId={5} seq={2} />)
      await userEvent.click(screen.getByText('Expected-score plan'))
      expect(await screen.findByText('151.2 pts')).toBeInTheDocument()
      expect(screen.queryByText(/out of date/)).not.toBeInTheDocument()
      fail = true
      rerender(<ExpectedScorePlan recordId={5} seq={3} />) // a new action was recorded; its recalculation fails
      expect(await screen.findByText(/Could not load the plan/)).toBeInTheDocument()
      expect(screen.getByText('151.2 pts')).toBeInTheDocument() // the previous plan stays visible...
      expect(screen.getByText(/out of date/)).toBeInTheDocument() // ...never as current
    })

  it('marks weakly identified and prior-dominated estimates on their cards (spec §11)', async () => {
    const p = plan()
    p.cards![0].robot.labels = ['weakly_identified', 'prior_dominated']
    mockApi({ [PATH]: envelope({ plan: p }) })
    const { container } = render(<ExpectedScorePlan recordId={5} seq={2} />)
    await userEvent.click(screen.getByText('Expected-score plan'))
    expect(await screen.findByText(/weakly identified/)).toBeInTheDocument()
    expect(screen.getByText(/prior-dominated/)).toBeInTheDocument()
    expect(await axeViolations(container)).toEqual([])
  })

  it("opens a card's own profile in one tap, with the card's reasons in full (criterion 13, G3)", async () => {
    const profile = { team_number: 24, event_key: '2099synth', snapshot_id: 'ab'.repeat(32), as_of: '2099-03-03T15:00Z',
      data_through: null, last_updated: '2099-03-03T14:50:00Z', validation_status: 'not_validated',
      thresholds_status: 'candidate_unapproved', rank: { value: 3, status: 'observed', fetched_at: null },
      matches_played: 10, matches: [], consistency: { kind: 'observed_alliance', alliance_points_mean: 140,
        alliance_points_sd: 9, n: 10 },
      estimates: { team_number: 24, labels: [], n: 10, partners: 18, validation_status: 'not_validated', note: 'x',
        components: { auto: { estimate: 12.3, sd: 2.1, kind: 'estimated', prior_kind: 'current_event_joint',
          w_eff: 0.8, labels: [], label_reasons: [] } } },
      estimates_absent_reason: null, fit_diagnostics: null, prior: null, prior_absent_reason: 'none',
      scouting: null, scouting_absent_reason: 'none', alliance_fit: null, alliance_fit_absent_reason: 'none',
      strengths_and_weaknesses_absent_reason: 'not produced', provenance: {} }
    const api = mockApi({ [PATH]: envelope({ plan: plan() }),
      'GET /workspace/alliance-selection/drafts/5/teams/24/profile': { ...envelope(), profile } })
    const { container } = render(<ExpectedScorePlan recordId={5} seq={2} />)
    await userEvent.click(screen.getByText('Expected-score plan'))
    await userEvent.click(await screen.findByRole('button', { name: 'Profile of team 24' }))
    const panel = await screen.findByRole('region', { name: 'Team 24 profile' })
    expect(await within(panel).findByText('12.3 ± 2.1')).toBeInTheDocument()
    expect(within(panel).getByText("estimated from this event's own matches")).toBeInTheDocument()
    expect(within(panel).getByText(/not a chance of winning/)).toBeInTheDocument() // the card's reason, visible
    expect(api.calls.map((c) => c.path)).toContain('/workspace/alliance-selection/drafts/5/teams/24/profile')
    expect(await axeViolations(container)).toEqual([])
  })
})

