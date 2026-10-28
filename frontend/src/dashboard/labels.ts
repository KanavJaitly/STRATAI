// Plain-language labels and number formatting for API values (P8-Q4).

import type { CandidateOut, Measure } from '../api/generated'

/** Plain names and explanations of the validation labels the API serves. The badge shows the name; the served label
 * stays on the element (data-status). An unknown label is shown with its underscores as spaces. */
export const VALIDATION_LABELS: Record<string, { name: string; text: string; tone: 'ok' | 'wait' | 'warn' | 'bad' | 'old' }> = {
  approximately_calibrated_qualification: { tone: 'ok', name: 'Validated (qualification)',
    text: 'Validated: approximately calibrated for qualification matches with full EPA (not validated for other matches).' },
  validated_playoff_success: { tone: 'ok', name: 'Validated (playoff event outcomes)',
    text: 'Validated playoff success: the bracket simulator\'s event outcomes passed their accuracy check, in the scope stated.' },
  validated_playoff: { tone: 'ok', name: 'Validated (single playoff match)',
    text: 'Validated playoff match probability: single playoff-match probabilities passed their accuracy check.' },
  validated: { tone: 'ok', name: 'Validated', text: 'Validated against real results.' },
  validated_as_measured: { tone: 'ok', name: 'Validated (as measured)',
    text: 'Validated: its accuracy was measured against real results, as the note describes.' },
  moderate_held_out: { tone: 'wait', name: 'Moderately accurate order',
    text: 'An ordering with moderate accuracy on held-out data; only the order is meaningful.' },
  descriptive: { tone: 'old', name: 'Recorded fact', text: 'A recorded or computed fact, not a prediction.' },
  descriptive_definition_pending: { tone: 'warn', name: 'Definition pending',
    text: 'A recorded fact, but how this metric is defined is still an open decision.' },
  not_validated: { tone: 'warn', name: 'Not validated', text: 'A model output that has not passed its accuracy check.' },
  not_validated_against_outcomes: { tone: 'warn', name: 'Rule of thumb',
    text: 'A documented rule of thumb, not checked against match outcomes.' },
  heuristic_not_validated_against_outcomes: { tone: 'warn', name: 'Rule of thumb',
    text: 'A documented rule of thumb, not checked against match outcomes.' },
  insufficient_data: { tone: 'bad', name: 'Too little data', text: 'Too few observations to report a value.' },
}

/** A served code with no plain text: underscores become spaces, so no raw identifier is shown. */
export function plainCode(code: string): string {
  return code.replaceAll('_', ' ')
}

export function statusName(status: string): string {
  return Object.hasOwn(VALIDATION_LABELS, status) ? VALIDATION_LABELS[status].name : plainCode(status)
}

/** Plain names for the EPA sources and per-team EPA states the API serves. */
const EPA_TEXT: Record<string, string> = {
  d18_statbotics_primary: 'Statbotics season snapshot',
  p5_live_statbotics: 'live Statbotics',
  statbotics: 'Statbotics',
  fallback_stratai: 'StratAI estimate',
  current: 'current',
  stale: 'out of date',
  withheld: 'withheld',
}

export function epaText(code: string): string {
  return Object.hasOwn(EPA_TEXT, code) ? EPA_TEXT[code] : plainCode(code)
}

export function formatNumber(value: number, digits = 1): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

export type FactorKey = Exclude<keyof CandidateOut, 'team_number'>

export const FACTORS: { key: FactorKey; label: string; digits: number }[] = [
  { key: 'scoring_epa', label: 'Scoring EPA', digits: 1 },
  { key: 'average_score', label: 'Average score', digits: 1 },
  { key: 'reliability', label: 'Reliability (estimate)', digits: 1 },
  { key: 'consistency', label: 'Consistency', digits: 1 },
  { key: 'defense', label: 'Defense', digits: 2 },
  { key: 'feeding', label: 'Feeding', digits: 2 },
  { key: 'synergy', label: 'Synergy', digits: 2 },
  { key: 'role_compatibility', label: 'Role compatibility', digits: 2 },
]

/** Plain text for the API's absence reasons. The raw reason stays on the element (title and data-reason); an unknown
 * reason is shown exactly as served. */
const REASON_TEXT: Record<string, string> = {
  // both mean: no qualifying earlier event with an EPA (ml/ratings/provider.py, epa_states.py, D13)
  no_prior_concluded_event_epa: 'no EPA: no qualifying earlier event with an EPA',
  withheld_no_prior_event: 'no EPA: no qualifying earlier event with an EPA',
  no_completed_matches_before_as_of: 'no completed matches before this moment',
  undefined_for_these_scores: 'undefined for these scores',
  no_matches_with_a_score_breakdown_before_as_of: 'no score breakdowns before this moment',
  not_played: 'not played yet',
  not_scheduled_before_as_of: 'scheduled after this moment',
  no_scheduled_time: 'no scheduled time',
  model_not_loaded: 'model not loaded',
  alliance_incomplete: 'needs a full three-team alliance',
  'alliance incomplete': 'needs a full three-team alliance',
  insufficient_data: 'too few observations',
  // validation qualifiers and refusal codes
  m7_gate_failed: 'calibrated only for qualification matches with full EPA; it did not pass the overall check',
  p6_m10_gate_failed: 'the strategy model did not pass its accuracy check',
  p6_m10b_not_accepted: 'the newer strategy model is not accepted yet',
  p6_m10_evaluation_not_recorded: 'the strategy model\'s evaluation is not recorded',
  playoff_scope: 'a playoff match; the model is validated for qualification matches only',
  playoff_model_unavailable: 'the playoff model is not available',
  range_coverage_not_measured: 'how often the real result falls inside this range has not been measured',
  canonical_tba_record: 'the official result from The Blue Alliance',
  epa_incomplete: 'some teams have no EPA',
  schedule_includes_epa_incomplete_match: 'the schedule includes a match where a team has no EPA',
  epa_source_incomplete: 'EPA data is incomplete for this event',
  epa_source_not_loaded: 'EPA data is not loaded',
  epa_source_pending: 'EPA data is still loading',
  epa_source_later_season: 'the EPA comes from a later season',
  epa_source_unresolvable: 'the EPA source could not be found',
  live_refresh_not_yet_validated: 'live EPA refresh not yet validated',
  statbotics_unprocessed_72h: 'Statbotics has not processed this event for 72 hours, so StratAI\'s own estimate is used',
  strategy_effect_unmeasured: 'the effect of the chosen strategy is not measured',
  coach_observation_effect_unmeasured: 'the effect of coach observations is not measured',
  defense_effect_insufficient_data: 'too little scouting data to measure defense',
  feeding_effect_insufficient_data: 'too little scouting data to measure feeding',
  unspecified_context: 'the match context is not specified',
  prediction_season_absent: 'no data for this season',
  probit_index_not_finite: 'the model could not produce a number',
  not_produced_by_any_engine: 'not produced yet',
  not_approved: 'the season rules are not approved',
  refusal_only: 'not available yet',
  writes_disabled: 'saving is turned off on this site',
}

export function reasonText(reason: string): string {
  if (Object.hasOwn(REASON_TEXT, reason)) return REASON_TEXT[reason]
  const colon = reason.indexOf(':')
  if (colon > 0 && Object.hasOwn(REASON_TEXT, reason.slice(0, colon).trim())) {
    return `${REASON_TEXT[reason.slice(0, colon).trim()]}:${reason.slice(colon + 1)}`
  }
  const fewer = /^fewer_than_(\d+)_completed_matches_before_as_of$/.exec(reason)
  if (fewer) return `fewer than ${fewer[1]} completed matches before this moment`
  return plainCode(reason) // an unknown reason: underscores as spaces, otherwise as served
}

/** The one reason every measure in a group is absent for, or null when any is present or the reasons differ. A view
 * states that reason once and hides it in the cells (`hideReason`), so the reason is never lost. */
export function sharedAbsence(measures: Measure[]): string | null {
  if (!measures.length || measures.some((m) => m.value !== null)) return null
  const reason = measures[0].absent_reason
  return reason && measures.every((m) => m.absent_reason === reason) ? reason : null
}
