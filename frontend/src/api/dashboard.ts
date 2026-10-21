// The dashboard's one door to the Phase 7 API (P8-M1). Every route the dashboard calls is listed in
// DASHBOARD_ENDPOINTS, and tests/test_phase8_frontend_contract.py checks each (method, path) against the API's
// OpenAPI schema in both directions. Request and response types come from generated.ts, which is generated from
// the same OpenAPI document the Phase 7 contract lock pins (P8-Q2).
//
// Reads never send the write token. The two coach writes send the session's in-memory token (P8-Q8) and are
// never retried automatically.

import { API_BASE, getWriteToken, WRITE_TOKEN_HEADER } from './client'
import type {
  AllianceSynergyRequestBody,
  AllianceSynergyResponse,
  AssessBody,
  AssessResponse,
  BriefingResponse,
  CandidatesResponse,
  CoachObservationStored,
  CoachStrategyStored,
  CompareBody,
  CompareResponse,
  DraftStateBody,
  EventAnalysisResponse,
  EventMatchesResponse,
  EventTeamsResponse,
  HealthResponse,
  HypotheticalAssessBody,
  HypotheticalCompareBody,
  HypotheticalRecommendBody,
  PickListResponse,
  PreMatchReportResponse,
  QualificationForecastResponse,
  ReadinessResponse,
  RecommendBody,
  RecommendResponse,
  SeasonEventsResponse,
  Strategy,
  TeamMetricsResponse,
  TeamStrengthResponse,
  WinProbabilityByAlliancesRequestBody,
  WinProbabilityResponse,
} from './generated'
import { requestJson } from './http'

type Method = 'GET' | 'POST'

export const DASHBOARD_ENDPOINTS = {
  health: ['GET', '/health'],
  ready: ['GET', '/ready'],
  events: ['GET', '/events'],
  eventTeams: ['GET', '/events/{event_key}/teams'],
  eventMatches: ['GET', '/events/{event_key}/matches'],
  eventAnalysis: ['GET', '/events/{event_key}/analysis'],
  qualificationForecast: ['GET', '/events/{event_key}/qualification-forecast'],
  teamMetrics: ['GET', '/teams/{team_number}/events/{event_key}/metrics'],
  teamStrength: ['GET', '/teams/{team_number}/events/{event_key}/strength'],
  matchWinProbability: ['GET', '/predictions/matches/{match_key}/win-probability'],
  allianceWinProbability: ['POST', '/predictions/win-probability'],
  allianceSynergy: ['POST', '/predictions/alliance-synergy'],
  candidates: ['GET', '/events/{event_key}/alliance-selection/candidates'],
  pickList: ['POST', '/events/{event_key}/alliance-selection/pick-list'],
  matchAssess: ['POST', '/strategy/matches/{match_key}/assess'],
  matchRecommend: ['POST', '/strategy/matches/{match_key}/recommend'],
  matchCompare: ['POST', '/strategy/matches/{match_key}/compare'],
  hypotheticalAssess: ['POST', '/strategy/hypothetical/assess'],
  hypotheticalRecommend: ['POST', '/strategy/hypothetical/recommend'],
  hypotheticalCompare: ['POST', '/strategy/hypothetical/compare'],
  coachStrategy: ['POST', '/strategy/coach-strategies'],
  coachObservation: ['POST', '/strategy/coach-observations'],
  preMatchReport: ['GET', '/matches/{match_key}/pre-match-report'],
  briefing: ['GET', '/matches/{match_key}/briefing'],
} as const satisfies Record<string, readonly [Method, string]>

/** The query parameters the dashboard sends per operation. call() refuses any other key, and
 * tests/test_phase8_frontend_contract.py checks each list against the parameters OpenAPI declares, so a renamed
 * parameter (FastAPI ignores unknown ones) can never silently fall back to a default such as "now". */
export const DASHBOARD_QUERY_PARAMS: Record<keyof typeof DASHBOARD_ENDPOINTS, readonly string[]> = {
  health: [], ready: [], events: ['season'], eventTeams: [], eventMatches: ['as_of'], eventAnalysis: ['as_of'],
  qualificationForecast: ['as_of'], teamMetrics: [], teamStrength: ['as_of'], matchWinProbability: [],
  allianceWinProbability: ['as_of'], allianceSynergy: ['as_of'], candidates: ['as_of', 'configuration'], pickList: [],
  matchAssess: [], matchRecommend: [], matchCompare: [], hypotheticalAssess: ['as_of'], hypotheticalRecommend: ['as_of'],
  hypotheticalCompare: ['as_of'], coachStrategy: [], coachObservation: [], preMatchReport: ['as_of'],
  briefing: ['as_of'],
}

/** Locked operations the dashboard deliberately does not call, with the reason (checked by the contract test). */
export const NOT_CALLED = {
  'GET /predictions/events/{event_key}/ranking': 'deprecated (P7-Q2); the canonical ranking is the analysis ordering',
} as const

type EndpointName = keyof typeof DASHBOARD_ENDPOINTS
type Query = Record<string, string | number | boolean | readonly (string | number)[] | undefined | null>

export function dashboardPath(name: EndpointName, params: Record<string, string | number> = {}): string {
  return DASHBOARD_ENDPOINTS[name][1].replace(/\{(\w+)\}/g, (_, key: string) => {
    if (!(key in params)) throw new Error(`missing path parameter ${key}`)
    return encodeURIComponent(String(params[key]))
  })
}

/** Builds a query string; arrays repeat the key (FastAPI list parameters); null and undefined are omitted. */
export function queryString(query: Query = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) for (const item of value) search.append(key, String(item))
    else search.append(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

interface CallOptions {
  params?: Record<string, string | number>
  query?: Query
  body?: unknown
  signal?: AbortSignal
  write?: boolean
}

// The probes sit outside API_PREFIX on the server, but the dev proxy and same-origin deployment route /api/* to
// the API with the prefix stripped, so they are reached the same way as every other route.
function call<T>(name: EndpointName, options: CallOptions = {}): Promise<T> {
  const [method] = DASHBOARD_ENDPOINTS[name]
  const unknown = Object.keys(options.query ?? {}).filter((key) => !DASHBOARD_QUERY_PARAMS[name].includes(key))
  if (unknown.length) throw new Error(`${name} does not declare query parameter(s) ${unknown.join(', ')}`)
  const url = API_BASE + dashboardPath(name, options.params) + queryString(options.query)
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (options.write) {
    const token = getWriteToken()
    if (token) headers[WRITE_TOKEN_HEADER] = token
  }
  // A coach write is not idempotent: a client-side timeout could fire after the server stored it and invite a
  // duplicate, so writes wait for the server's answer (P8-Q8).
  return requestJson<T>(url, { method, headers, body, signal: options.signal, timeoutMs: options.write ? 0 : undefined })
}

export type Side = 'red' | 'blue'

export type DraftState = DraftStateBody

/** The pairing part every hypothetical body shares. */
export type HypotheticalAlliances = Pick<HypotheticalRecommendBody, 'event_key' | 'red_team_numbers' | 'blue_team_numbers'
  | 'match_context'>

export const dashboardApi = {
  health: (signal?: AbortSignal) => call<HealthResponse>('health', { signal }),
  ready: (signal?: AbortSignal) => call<ReadinessResponse>('ready', { signal }),

  events: (season: number, signal?: AbortSignal) => call<SeasonEventsResponse>('events', { query: { season }, signal }),
  eventTeams: (eventKey: string, signal?: AbortSignal) =>
    call<EventTeamsResponse>('eventTeams', { params: { event_key: eventKey }, signal }),
  eventMatches: (eventKey: string, asOf: string | null, signal?: AbortSignal) =>
    call<EventMatchesResponse>('eventMatches', { params: { event_key: eventKey }, query: { as_of: asOf }, signal }),
  eventAnalysis: (eventKey: string, asOf: string | null, signal?: AbortSignal) =>
    call<EventAnalysisResponse>('eventAnalysis', { params: { event_key: eventKey }, query: { as_of: asOf }, signal }),
  qualificationForecast: (eventKey: string, asOf: string | null, signal?: AbortSignal) =>
    call<QualificationForecastResponse>('qualificationForecast',
      { params: { event_key: eventKey }, query: { as_of: asOf }, signal }),

  teamMetrics: (team: number, eventKey: string, signal?: AbortSignal) =>
    call<TeamMetricsResponse>('teamMetrics', { params: { team_number: team, event_key: eventKey }, signal }),
  teamStrength: (team: number, eventKey: string, asOf: string | null, signal?: AbortSignal) =>
    call<TeamStrengthResponse>('teamStrength',
      { params: { team_number: team, event_key: eventKey }, query: { as_of: asOf }, signal }),

  matchWinProbability: (matchKey: string, signal?: AbortSignal) =>
    call<WinProbabilityResponse>('matchWinProbability', { params: { match_key: matchKey }, signal }),
  allianceWinProbability: (body: WinProbabilityByAlliancesRequestBody, asOf: string | null, signal?: AbortSignal) =>
    call<WinProbabilityResponse>('allianceWinProbability', { body, query: { as_of: asOf }, signal }),
  allianceSynergy: (body: AllianceSynergyRequestBody, asOf: string | null, signal?: AbortSignal) =>
    call<AllianceSynergyResponse>('allianceSynergy', { body, query: { as_of: asOf }, signal }),

  candidates: (eventKey: string, asOf: string | null, configuration: number[] | null, signal?: AbortSignal) =>
    call<CandidatesResponse>('candidates',
      { params: { event_key: eventKey }, query: { as_of: asOf, configuration }, signal }),
  pickList: (eventKey: string, draft: DraftState, signal?: AbortSignal) =>
    call<PickListResponse>('pickList', { params: { event_key: eventKey }, body: draft, signal }),

  matchAssess: (matchKey: string, body: AssessBody, signal?: AbortSignal) => call<AssessResponse>('matchAssess', { params: { match_key: matchKey }, body, signal }),
  matchRecommend: (matchKey: string, body: RecommendBody, signal?: AbortSignal) =>
    call<RecommendResponse>('matchRecommend', { params: { match_key: matchKey }, body, signal }),
  matchCompare: (matchKey: string, body: CompareBody, signal?: AbortSignal) =>
    call<CompareResponse>('matchCompare', { params: { match_key: matchKey }, body, signal }),
  hypotheticalAssess: (body: HypotheticalAssessBody, asOf: string | null, signal?: AbortSignal) =>
    call<AssessResponse>('hypotheticalAssess', { body, query: { as_of: asOf }, signal }),
  hypotheticalRecommend: (body: HypotheticalRecommendBody, asOf: string | null, signal?: AbortSignal) =>
    call<RecommendResponse>('hypotheticalRecommend', { body, query: { as_of: asOf }, signal }),
  hypotheticalCompare: (body: HypotheticalCompareBody, asOf: string | null, signal?: AbortSignal) =>
    call<CompareResponse>('hypotheticalCompare', { body, query: { as_of: asOf }, signal }),

  coachStrategy: (body: { event_key: string; match_key: string | null; author: string; strategy: Strategy }) =>
    call<CoachStrategyStored>('coachStrategy', { body, write: true }),
  coachObservation: (body: { event_key: string; team_number: number; kind: 'component_unavailable' |
    'robot_unavailable'; component?: 'auto' | 'teleop' | 'endgame'; observed_at: string; observer: string }) =>
    call<CoachObservationStored>('coachObservation', { body, write: true }),

  preMatchReport: (matchKey: string, asOf: string | null, signal?: AbortSignal) =>
    call<PreMatchReportResponse>('preMatchReport', { params: { match_key: matchKey }, query: { as_of: asOf }, signal }),
  briefing: (matchKey: string, asOf: string | null, signal?: AbortSignal) =>
    call<BriefingResponse>('briefing', { params: { match_key: matchKey }, query: { as_of: asOf }, signal }),
}
