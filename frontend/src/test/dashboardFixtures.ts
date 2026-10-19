// SYNTHETIC fixtures for dashboard tests (P8-Q12). Every object is typed with the generated API types, so the
// compiler rejects a fixture that drifts from the locked contract. None of this is real data: the season 2099, the
// event "2099test" and the team numbers 9901-9906 exist nowhere, and no value here is a model output.

import type {
  CalibratedWinProbability, CandidateOut, CandidatesResponse, EpaSourceInfo, EventAnalysisResponse,
  EventMatchesResponse, EventTeamsResponse, FactorOut, Measure, PickListResponse, PreMatchReportResponse,
  RecommendResponse, SeasonEventsResponse, Strategy, StrategyContextOut, StrategyModelInfo, TeamMetricsResponse,
  TeamStrengthResponse, TeamStrengthView, WinProbabilityResponse,
} from '../api/generated'

export const EVENT = '2099test'
export const RED = [9901, 9902, 9903]
export const BLUE = [9904, 9905, 9906]
export const MATCH = `${EVENT}_qm1`

export const EPA: EpaSourceInfo = { epa_source: 'statbotics', evaluated_configuration: false, provenance: { source: 'synthetic' } }

export const measure = (value: number | null, n = 4, reason: string | null = null): Measure => ({
  value, n, uncertainty: { kind: 'none', reason: 'synthetic' }, absent_reason: value === null ? reason ?? 'synthetic absence' : null,
})

export function strengthView(team: number): TeamStrengthView {
  return {
    team_number: team, event_key: EVENT, as_of: '2099-03-01T10:00:00Z',
    epa: { total: measure(30 + team % 10), auto: measure(5), teleop: measure(20), endgame: measure(5),
      epa_value_source: 'statbotics', epa_source_state: 'current', source_event_key: '2099prior', withheld_reason: null },
    scoring: { average_score: measure(55), score_stddev: measure(8), consistency_rating: measure(70),
      reliability_score: measure(100), good_day_count: measure(1, 4), average_day_count: measure(2, 4), bad_day_count: measure(1, 4),
      matches_considered: 4 },
    auto_points: { this_event: measure(6), season_by_event: [
      { event_key: '2099prior', average_auto_points: measure(4) },
      { event_key: EVENT, average_auto_points: measure(null, 0, 'no_matches_with_a_score_breakdown_before_as_of') }] },
    defense: { score: measure(null, 0, 'insufficient_data: fewer than 2 scouting observations'),
      agreement: measure(null, 0, 'insufficient_data: fewer than 2 scouting observations'), contributing_sources: [],
      validation_status: 'descriptive_definition_pending' },
    feeding: { score: measure(null, 0, 'insufficient_data: fewer than 2 scouting observations'),
      agreement: measure(null, 0, 'insufficient_data: fewer than 2 scouting observations'), contributing_sources: [],
      validation_status: 'not_validated' },
  }
}

export const EVENTS: SeasonEventsResponse = {
  season: 2099, validation: { status: 'descriptive', reasons: ['canonical_tba_record'] },
  events: [
    { event_key: EVENT, season: 2099, name: 'Synthetic Test Event', start_date: '2099-03-01', end_date: '2099-03-02',
      city: 'Testville', state_province: 'TS', country: 'USA' },
    { event_key: '2099other', season: 2099, name: 'Another Synthetic Event', start_date: '2099-02-01', end_date: null,
      city: null, state_province: null, country: null },
  ],
}

export const TEAMS: EventTeamsResponse = {
  event_key: EVENT, validation: { status: 'descriptive', reasons: [] },
  teams: [...RED, ...BLUE].map((t) => ({ team_number: t, name: `Synthetic ${t}`, city: 'Testville', state_province: null,
    country: 'USA', rookie_year: 2090 })),
}

export const MATCHES: EventMatchesResponse = {
  event_key: EVENT, as_of: '2099-03-02T00:00:00Z', validation: { status: 'descriptive', reasons: [] },
  matches: [
    { match_key: MATCH, competition_level: 'qualification', set_number: 1, match_number: 1,
      scheduled_time: '2099-03-01T10:00:00Z', red_team_numbers: RED, blue_team_numbers: BLUE,
      result: { score_red: 61, score_blue: 48, winning_alliance: 'red' }, result_withheld_reason: null },
    { match_key: `${EVENT}_qm2`, competition_level: 'qualification', set_number: 1, match_number: 2,
      scheduled_time: '2099-03-01T11:00:00Z', red_team_numbers: BLUE, blue_team_numbers: RED,
      result: null, result_withheld_reason: 'not_played' },
  ],
}

export const ANALYSIS: EventAnalysisResponse = {
  event_key: EVENT, as_of: '2099-03-01T09:00:00Z', ranking_model_sha256: null, epa: EPA,
  ordering: { model: 'raw_epa', switch_point_passed: false, switch_time: '2099-03-01T15:00:00Z',
    validation_status: 'descriptive', evidence: 'synthetic evidence',
    teams: [...RED, ...BLUE].map((t, i) => ({ rank: i + 1, team_number: t, score: i === 5 ? null : 40 - i,
      epa_value_source: i === 5 ? null : 'statbotics', epa_source_event_key: null, epa_source_state: null })) },
  captain_candidates: { team_numbers: RED, validation_status: 'descriptive', evidence: 'synthetic captains' },
  strongest_teams: { team_numbers: [RED[0], BLUE[0]], validation_status: 'descriptive', evidence: 'synthetic strongest' },
  team_comparison: { validation_status: 'descriptive', teams: [...RED, ...BLUE].map(strengthView) },
}

export const STRENGTH: TeamStrengthResponse = { strength: strengthView(RED[0]), epa: EPA }

export const METRICS: TeamMetricsResponse = {
  team_number: RED[0], event_key: EVENT, season: 2099, computed_at: '2099-03-03T00:00:00Z',
  scoring: { matches_scheduled: 4, matches_used: 4, average_score: 55, score_stddev: 8, consistency_rating: 70,
    reliability_score: 100, good_day_count: 1, average_day_count: 2, bad_day_count: 1 },
  defense_feeding: { defense_score: null, defense_observation_count: 0, defense_agreement: null, defense_insufficient_data: true,
    feeding_score: null, feeding_observation_count: 0, feeding_agreement: null, feeding_insufficient_data: true,
    contributing_sources: [] },
  validation: { scoring: { status: 'descriptive', reasons: ['reliability_score_interim: synthetic'] },
    defense: { status: 'descriptive_definition_pending', reasons: [] }, feeding: { status: 'not_validated', reasons: [] } },
}

const MODEL_INFO = { model_type: 'win_prob_xgb_calibrated', model_version: 'synthetic', model_version_tag: 'synthetic',
  model_sha256: 'a'.repeat(64), training_dataset_hash: 'synthetic', provenance: {} }

export const validatedWin = (value: number): CalibratedWinProbability => ({
  validated_value: value, unvalidated_value: null, unvalidated_reason: null, rounding: 0.05,
  calibration_status: 'm7_gate_failed', model: MODEL_INFO,
  validation: { status: 'approximately_calibrated_qualification', reasons: ['m7_gate_failed'] },
})

export const unvalidatedWin = (value: number, reason = 'playoff_scope'): CalibratedWinProbability => ({
  validated_value: null, unvalidated_value: value, unvalidated_reason: reason, rounding: 0.05,
  calibration_status: 'm7_gate_failed', model: MODEL_INFO,
  validation: { status: 'not_validated', reasons: [reason, 'm7_gate_failed'] },
})

export const WIN_PROBABILITY: WinProbabilityResponse = {
  match_key: MATCH, event_key: EVENT, red_team_numbers: RED, blue_team_numbers: BLUE, as_of: '2099-03-01T10:00:00Z',
  probability_scope: 'qualification', competition_level: 'qualification', validation_status: 'approximately_calibrated_qualification',
  not_validated_reason: null, red_win_probability: 0.6, unvalidated_red_win_probability: null, probability_rounding: 0.05,
  calibration_status: 'm7_gate_failed', evidence: 'synthetic evidence', warning: null, model_type: 'win_prob_xgb_calibrated',
  model_version: 'synthetic', model_version_tag: 'synthetic', model: MODEL_INFO, epa: EPA,
  teams: [...RED.map((t) => ({ team_number: t, alliance: 'red', epa_value_source: 'statbotics', epa_source_state: 'current',
    epa_source_event_key: '2099prior', epa_withheld_reason: null }))],
  win_probability: validatedWin(0.6),
}

export const baseline = (teams: number[]): Strategy => ({ vocabulary: 'p6-strategy-v1',
  robots: teams.map((t) => ({ team_number: t, role: 'scoring', components: ['auto', 'teleop', 'endgame'] })) as Strategy['robots'] })

export const STRATEGY_MODEL: StrategyModelInfo = { model_type: 'strategy_outcome_component', model_version: 'synthetic',
  model_version_tag: 'synthetic', model_sha256: 'b'.repeat(64), spec_sha256: 'c'.repeat(64) }

export const CONTEXT: StrategyContextOut = { match_key: MATCH, event_key: EVENT, as_of: '2099-03-01T10:00:00Z',
  match_context: 'qualification', competition_level: 'qualification', red_team_numbers: RED, blue_team_numbers: BLUE,
  coach_observations_applied: 0, coach_observations_invalid_ignored: 0 }

const defenseStrategy: Strategy = { vocabulary: 'p6-strategy-v1', robots: [
  { team_number: RED[0], role: 'scoring', components: ['auto', 'teleop', 'endgame'] },
  { team_number: RED[1], role: 'defense', defense_target: BLUE[0], components: ['auto', 'endgame'] },
  { team_number: RED[2], role: 'scoring', components: ['auto', 'teleop', 'endgame'] }] }

export const RECOMMEND: RecommendResponse = {
  side: 'red', context: CONTEXT, model: STRATEGY_MODEL, epa: EPA,
  recommended: { strategy: defenseStrategy, opponent_strategy: baseline(BLUE),
    odds: { display: '65%', validation: { status: 'not_validated', reasons: ['strategy_effect_unmeasured'] } } },
  alternatives: [],
  baseline: { strategy: baseline(RED), opponent_strategy: baseline(BLUE),
    odds: { display: '55%', validation: { status: 'not_validated', reasons: ['p6_m10_gate_failed'] } } },
  vs_baseline_label: 'differs by at least one display step under the model (not a claim that either strategy is better)',
  candidates_evaluated: 21952,
  selection_note: 'The recommendation is the maximum of many model estimates, not an unbiased probability.',
  unavailable_reasons: [],
}

export const factor = (value: number | null, status = 'descriptive', reason?: string): FactorOut => ({
  value, n: value === null ? null : 4, validation: { status, reasons: reason ? [reason] : [] },
})

export const candidate = (team: number, epa: number | null): CandidateOut => ({
  team_number: team, scoring_epa: factor(epa), average_score: factor(50), reliability: factor(100, 'descriptive', 'reliability_score_interim: synthetic'),
  consistency: factor(70), defense: factor(null, 'insufficient_data', 'too few observations'), feeding: factor(null, 'insufficient_data'),
  synergy: factor(null, 'insufficient_data', 'alliance incomplete'), role_compatibility: factor(null, 'insufficient_data', 'alliance incomplete'),
})

export const CANDIDATES: CandidatesResponse = { event_key: EVENT, as_of: '2099-03-02T00:00:00Z', as_of_source: 'selection_moment',
  configuration: null, epa: EPA, candidates: [candidate(RED[0], 30), candidate(RED[1], null), candidate(BLUE[0], 45)] }

const playoffOdds = (display: string) => ({ display, validation: { status: 'validated_playoff_success',
  reasons: ['px4_scope: synthetic', 'predicted_field_not_validated: synthetic'], evidence: '.agent/phase6/results/p6_m5_px4.json' } })

export const PICK_LIST: PickListResponse = {
  event_key: EVENT, seed: 1, as_of: '2099-03-02T00:00:00Z', probability_status: 'validated_playoff_success',
  ranked: [
    { team_number: BLUE[0], configuration: [RED[0], BLUE[0], BLUE[1]], win_event: playoffOdds('35%'), reach_finals: playoffOdds('50%'),
      vs_next_label: 'indistinguishable at model resolution', vs_next_reach_finals_label: 'indistinguishable at model resolution',
      vs_next_reason: null, profile: null },
    { team_number: BLUE[1], configuration: [RED[0], BLUE[1], BLUE[2]], win_event: playoffOdds('30%'), reach_finals: playoffOdds('45%'),
      vs_next_label: null, vs_next_reach_finals_label: null, vs_next_reason: 'last_candidate: no next-best candidate to compare with', profile: null },
  ],
  alternatives: [{ alliances: [[RED[0], BLUE[1], BLUE[2]], [RED[1], RED[2], BLUE[0]]], win_event: playoffOdds('30%'), reach_finals: playoffOdds('45%') }],
  alternatives_note: 'only 1 distinct feasible alternative configuration(s) exist from this draft state',
  evaluated_fields: 12, notes: ['objective: synthetic'],
  models: { px1_sha256: '1'.repeat(64), px2_calibrator_sha256: '2'.repeat(64), ranking_model_sha256: null },
  provenance: { ruleset_sha256: '3'.repeat(64), ruleset_variant: null, ordering_policy: 'raw_epa' }, epa: EPA,
}

const notProduced = (semantics: string) => ({ value: null, reason: 'not_produced_by_any_engine' as const, semantics })

export const REPORT: PreMatchReportResponse = {
  match_key: MATCH, event_key: EVENT, competition_level: 'qualification', scheduled_time: '2099-03-01T10:00:00Z',
  as_of: '2099-03-01T10:00:00Z', as_of_source: 'scheduled_time', red_team_numbers: RED, blue_team_numbers: BLUE, epa: EPA,
  teams: [...RED.map((t) => ({ team_number: t, alliance: 'red' as const, strength: strengthView(t),
    validation: { status: 'descriptive', reasons: ['reliability_score_interim: synthetic'] } })),
    ...BLUE.map((t) => ({ team_number: t, alliance: 'blue' as const, strength: strengthView(t),
      validation: { status: 'descriptive', reasons: ['reliability_score_interim: synthetic'] } }))],
  synergy: [
    { alliance: 'red', team_numbers: RED, score: { overall_score: 0.42, role_fit_term: 0.5, role_fit_axes_used: ['auto', 'teleop'],
      scoring_distribution_term: 0.3, scoring_distribution_axes_used: ['auto'], defense_feeding_coverage_term: null,
      defense_feeding_coverage_present_count: 0, confidence: 0.4 }, absent_code: null, absent_reason: null,
      validation: { status: 'not_validated_against_outcomes' } },
    { alliance: 'blue', team_numbers: BLUE, score: null, absent_code: 'alliance_incomplete',
      absent_reason: 'synergy needs three teams on the alliance', validation: { status: 'not_validated_against_outcomes' } },
  ],
  win_probability: { probability_scope: 'qualification', value: null, absent_code: 'model_not_loaded',
    absent_reason: 'win_prob_xgb_calibrated (M6/M7) is not pinned/loadable' },
  strategy: { model: null, context: null, sides: [], absent_code: 'model_not_loaded',
    absent_reason: 'the P6-M10 strategy model is not pinned/loadable' },
  not_produced: {
    strengths_and_weaknesses: notProduced('Per-team labels of what a team does well or poorly.'),
    defensive_threats: notProduced('Opposing robots likely to play effective defense.'),
    key_risks: notProduced('Events that would most reduce the chance of winning.'),
    predicted_flow: notProduced('The expected sequence of the match by phase.'),
    critical_matchups: notProduced('Robot-versus-robot interactions that most influence the outcome.'),
    key_success_factors: notProduced('The conditions under which this alliance wins.'),
  },
}
