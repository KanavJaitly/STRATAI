// One map from the API's refusal codes to what a person should understand (P8-Q5). A refusal is a truthful
// state of the system, not a crash. The code and the server's own message are always shown with it, and an
// unknown code falls back to the server's message.

export type RefusalKind =
  | 'unavailable' // a model, data source or record the result needs is not available here
  | 'blocked' // a governance gate has not passed (rulesets, PX gates)
  | 'not_found' // the thing asked for does not exist
  | 'input' // the request itself cannot be answered as asked
  | 'failure' // the API failed or could not be reached

export interface RefusalInfo {
  title: string
  explanation: string
  kind: RefusalKind
}

export const REFUSALS: Record<string, RefusalInfo> = {
  model_not_loaded: { kind: 'unavailable', title: 'Model not loaded',
    explanation: 'The trained model this result needs is not installed on this server, so nothing is shown in its '
      + 'place. The result appears once the model is installed.' },
  epa_source_not_loaded: { kind: 'unavailable', title: 'EPA source not loaded',
    explanation: 'The configured EPA source is not loaded on this server, so no EPA-based result can be built.' },
  epa_source_incomplete: { kind: 'unavailable', title: 'EPA data incomplete',
    explanation: 'The EPA source has no valid value for a required prior event; an older event is never silently '
      + 'used instead.' },
  epa_source_pending: { kind: 'unavailable', title: 'EPA data pending',
    explanation: 'A required prior event ended recently and its EPA has not been processed yet.' },
  insufficient_features: { kind: 'unavailable', title: 'No evidence',
    explanation: 'Every team involved has no features at all (or the match has no scheduled time), so no '
      + 'prediction is made.' },
  rankings_unavailable: { kind: 'unavailable', title: 'Final ranks not available',
    explanation: 'The event\'s final qualification ranks are not landed, are older than the last qualification '
      + 'result, or miss a team.' },
  selection_time_unavailable: { kind: 'unavailable', title: 'Selection moment not reached',
    explanation: 'Qualification is not finished (or the event has no scheduled qualification match), so there is '
      + 'no alliance-selection moment yet.' },
  playoff_inputs_insufficient: { kind: 'unavailable', title: 'Playoff inputs insufficient',
    explanation: 'The playoff model lacks an input for a team; the engine never imputes one.' },

  not_approved: { kind: 'blocked', title: 'No approved ruleset',
    explanation: 'Alliance selection needs the season\'s game rules entered from the manual and approved by a '
      + 'named, qualified reviewer. Until then the pick list is not available.' },
  playoff_models_not_accepted: { kind: 'blocked', title: 'Playoff models not accepted',
    explanation: 'The playoff models have not passed their accuracy checks, or their records do not name the '
      + 'served model files.' },
  storage_integrity: { kind: 'blocked', title: 'Stored record failed its integrity check',
    explanation: 'A stored record does not match its recorded hash or schema, so it is not used.' },
  event_excluded: { kind: 'blocked', title: 'Event excluded',
    explanation: 'The approved ruleset excludes this event: its rules cannot be represented faithfully.' },
  not_covered: { kind: 'blocked', title: 'Rules do not cover this event',
    explanation: 'The approved ruleset has no alliance-count or bracket rule for this event\'s roster.' },
  not_established: { kind: 'blocked', title: 'Rule not established',
    explanation: 'A selection rule this draft depends on is not established by an authoritative source.' },
  not_supported: { kind: 'blocked', title: 'Draft format not supported',
    explanation: 'The draft model represents serpentine, highest-ranked-available drafts only.' },
  wrong_season: { kind: 'blocked', title: 'Wrong season',
    explanation: 'The event is not covered by the season ruleset.' },

  event_not_found: { kind: 'not_found', title: 'Event not found', explanation: 'StratAI has no such event.' },
  team_not_found: { kind: 'not_found', title: 'Team not found',
    explanation: 'The team is not on this event\'s roster (or not in its qualification pool).' },
  team_did_not_attend: { kind: 'not_found', title: 'Team did not attend',
    explanation: 'The team is known, but not on this event\'s roster.' },
  metrics_not_computed: { kind: 'unavailable', title: 'Metrics not computed yet',
    explanation: 'The stored metrics for this team and event have not been computed yet.' },
  match_not_found: { kind: 'not_found', title: 'Match not found', explanation: 'StratAI has no such match.' },

  match_not_scheduled: { kind: 'input', title: 'Match not scheduled',
    explanation: 'The match has no scheduled time, so no pre-match moment exists.' },
  match_context_unknown: { kind: 'input', title: 'Match context unknown',
    explanation: 'The match has no competition level, so it is neither a known qualification nor a playoff match.' },
  alliance_incomplete: { kind: 'input', title: 'Alliance incomplete',
    explanation: 'An alliance does not have three teams; the model needs 3 v 3.' },
  mixed_season_scale: { kind: 'input', title: 'Mixed season scale',
    explanation: 'The six teams disagree on the season scale, which the strategy model cannot combine.' },
  invalid_strategy: { kind: 'input', title: 'Strategy does not fit this match',
    explanation: 'The strategy names teams or assignments that do not fit the match.' },
  invalid_state: { kind: 'input', title: 'Draft state not valid',
    explanation: 'The draft state is not one the event\'s rules and serpentine order can produce.' },
  infeasible: { kind: 'input', title: 'Draft infeasible', explanation: 'No team is available for a required pick.' },
  invalid_as_of: { kind: 'input', title: 'Invalid moment',
    explanation: 'The moment must be an ISO-8601 time with an offset, and not in the future.' },
  validation_error: { kind: 'input', title: 'Request not valid', explanation: 'The request does not match the API.' },
  invalid_coach_input: { kind: 'input', title: 'Coach input not valid',
    explanation: 'The submission was recorded but failed validation, so it is never applied.' },
  writes_disabled: { kind: 'blocked', title: 'Writes disabled',
    explanation: 'No write token is configured on the server, so every write is refused.' },
  write_not_authorized: { kind: 'blocked', title: 'Write not authorized',
    explanation: 'The write token is missing or wrong. Enter it in the header (it is kept in memory only).' },

  internal_error: { kind: 'failure', title: 'Server error', explanation: 'The API failed. Retry, or check its logs.' },
  network_error: { kind: 'failure', title: 'API unreachable',
    explanation: 'The API could not be reached. Check that it is running and that /api is routed to it.' },
  timeout: { kind: 'failure', title: 'No response', explanation: 'The API did not answer in time. Retry.' },
  malformed_response: { kind: 'failure', title: 'Malformed response',
    explanation: 'The API answered with something that is not valid JSON.' },
}

export function refusalInfo(code: string, serverMessage: string): RefusalInfo {
  return REFUSALS[code] ?? { kind: 'failure', title: code.replaceAll('_', ' '), explanation: serverMessage }
}
