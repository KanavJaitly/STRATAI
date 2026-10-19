// Plain-language labels and number formatting for API values (P8-Q4).

import type { CandidateOut, Measure } from '../api/generated'

/** Plain explanations of the validation labels the API serves (unknown labels are shown as-is). */
export const VALIDATION_LABELS: Record<string, { text: string; tone: 'ok' | 'wait' | 'warn' | 'bad' | 'old' }> = {
  approximately_calibrated_qualification: { tone: 'ok',
    text: 'Validated: approximately calibrated for qualification matches with full EPA (the M7 gate failed overall).' },
  validated_playoff_success: { tone: 'ok',
    text: 'Validated playoff success: the bracket simulator\'s event outcomes passed PX-4, in the scope stated.' },
  validated_playoff: { tone: 'ok',
    text: 'Validated playoff match probability: single playoff-match probabilities passed PX-2.' },
  moderate_held_out: { tone: 'wait', text: 'An ordering with moderate held-out accuracy; only the order is meaningful.' },
  descriptive: { tone: 'old', text: 'Descriptive: a recorded or computed fact, not a prediction.' },
  descriptive_definition_pending: { tone: 'warn',
    text: 'Descriptive, but the metric\'s definition is still an open decision.' },
  not_validated: { tone: 'warn', text: 'Not validated: a model output that has not passed its validation gate.' },
  not_validated_against_outcomes: { tone: 'warn', text: 'A documented heuristic, not validated against match outcomes.' },
  heuristic_not_validated_against_outcomes: { tone: 'warn',
    text: 'A documented heuristic, not validated against match outcomes.' },
  insufficient_data: { tone: 'bad', text: 'Insufficient data: too few observations to report a value.' },
}

export function formatNumber(value: number, digits = 1): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

export type FactorKey = Exclude<keyof CandidateOut, 'team_number'>

export const FACTORS: { key: FactorKey; label: string; digits: number }[] = [
  { key: 'scoring_epa', label: 'Scoring EPA', digits: 1 },
  { key: 'average_score', label: 'Average score', digits: 1 },
  { key: 'reliability', label: 'Reliability (INTERIM)', digits: 1 },
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
}

export function reasonText(reason: string): string {
  if (Object.hasOwn(REASON_TEXT, reason)) return REASON_TEXT[reason]
  const colon = reason.indexOf(':')
  if (colon > 0 && Object.hasOwn(REASON_TEXT, reason.slice(0, colon).trim())) {
    return `${REASON_TEXT[reason.slice(0, colon).trim()]}:${reason.slice(colon + 1)}`
  }
  const fewer = /^fewer_than_(\d+)_completed_matches_before_as_of$/.exec(reason)
  if (fewer) return `fewer than ${fewer[1]} completed matches before this moment`
  return reason // an unknown reason is shown exactly as served
}

/** The one reason every measure in a group is absent for, or null when any is present or the reasons differ. A view
 * states that reason once and hides it in the cells (`hideReason`), so the reason is never lost. */
export function sharedAbsence(measures: Measure[]): string | null {
  if (!measures.length || measures.some((m) => m.value !== null)) return null
  const reason = measures[0].absent_reason
  return reason && measures.every((m) => m.absent_reason === reason) ? reason : null
}
