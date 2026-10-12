// The one place the web app talks to the API. Every route it calls is listed in ENDPOINTS, and
// tests/test_frontend_api_contract.py checks each (method, path) against the API's OpenAPI schema.

import type {
  Artifact,
  ArtifactKind,
  CapabilityPayload,
  DesignExample,
  Dm1Status,
  GameSpecDraft,
  KappaStatus,
  Manual,
  Profile,
  Recommendation,
  SeasonWorkflow,
  SpecVersion,
  WriteAccess,
} from './types'
import type {
  AnalysisBody,
  ChecklistInfo,
  EventInfo,
  EventMatch,
  EventSummary,
  EventTeam,
  Extraction,
  PageText,
  ProcessingState,
  Readiness,
  RulesetVersion,
  SeasonSummary,
  TeamSeason,
  Worksheet,
} from './managerTypes'

export const WRITE_TOKEN_HEADER = 'X-StratAI-Write-Token'
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api'

type Method = 'GET' | 'POST' | 'PUT'

export const ENDPOINTS = {
  writeAccess: ['GET', '/human-inputs/write-access'],
  listManuals: ['GET', '/human-inputs/game-manuals'],
  uploadManual: ['POST', '/human-inputs/game-manuals'],
  manualFile: ['GET', '/human-inputs/game-manuals/{manual_id}/file'],
  workflow: ['GET', '/human-inputs/seasons/{season}/workflow'],
  listSpecs: ['GET', '/human-inputs/seasons/{season}/specs'],
  saveSpec: ['POST', '/human-inputs/seasons/{season}/specs'],
  submitSpec: ['POST', '/human-inputs/specs/{spec_id}/submit'],
  reviewSpec: ['POST', '/human-inputs/specs/{spec_id}/review'],
  listProfiles: ['GET', '/human-inputs/capability-profiles'],
  createProfile: ['POST', '/human-inputs/capability-profiles'],
  editProfile: ['PUT', '/human-inputs/capability-profiles/{profile_key}'],
  profileHistory: ['GET', '/human-inputs/capability-profiles/{profile_key}/history'],
  duplicateProfile: ['POST', '/human-inputs/capability-profiles/{profile_key}/duplicate'],
  archiveProfile: ['POST', '/human-inputs/capability-profiles/{profile_key}/archive'],
  recommendation: ['GET', '/human-inputs/capability-profiles/{profile_key}/recommendation'],
  designExamples: ['GET', '/human-inputs/reference/design-examples'],
  listArtifacts: ['GET', '/human-inputs/seasons/{season}/artifacts'],
  submitArtifact: ['POST', '/human-inputs/seasons/{season}/artifacts'],
  establishArtifact: ['POST', '/human-inputs/artifacts/{artifact_id}/establish'],
  kappa: ['GET', '/human-inputs/seasons/{season}/kappa'],
  dm1Status: ['GET', '/human-inputs/seasons/{season}/dm1-status'],
  processingStatus: ['GET', '/human-inputs/game-manuals/{manual_id}/processing'],
  startProcessing: ['POST', '/human-inputs/game-manuals/{manual_id}/processing'],
  resolveIdentity: ['POST', '/human-inputs/game-manuals/{manual_id}/identity-resolution'],
  extraction: ['GET', '/human-inputs/game-manuals/{manual_id}/extraction'],
  pages: ['GET', '/human-inputs/game-manuals/{manual_id}/pages'],
  listRulesets: ['GET', '/human-inputs/rulesets'],
  getRuleset: ['GET', '/human-inputs/rulesets/{ruleset_id}'],
  saveRuleset: ['POST', '/human-inputs/rulesets'],
  submitRuleset: ['POST', '/human-inputs/rulesets/{ruleset_id}/submit'],
  reviewRuleset: ['POST', '/human-inputs/rulesets/{ruleset_id}/review'],
  rulesetChecklist: ['GET', '/human-inputs/ruleset-review-checklist'],
  rulesetWorksheet: ['GET', '/human-inputs/seasons/{season}/ruleset-worksheet'],
  readiness: ['GET', '/human-inputs/seasons/{season}/readiness'],
} as const satisfies Record<string, readonly [Method, string]>

// The historical explorer (Kanav, 2026-10-11): read-only GETs of season data and the existing analysis endpoints,
// kept apart from the human-input routes above. tests/test_frontend_api_contract.py checks both lists.
export const EXPLORER_ENDPOINTS = {
  seasons: ['GET', '/seasons'],
  seasonEvents: ['GET', '/seasons/{season}/events'],
  eventTeams: ['GET', '/events/{event_key}/teams'],
  eventMatches: ['GET', '/events/{event_key}/matches'],
  teamSeason: ['GET', '/teams/{team_number}/seasons/{season}'],
  teamMetrics: ['GET', '/teams/{team_number}/events/{event_key}/metrics'],
  teamStrength: ['GET', '/teams/{team_number}/events/{event_key}/strength'],
  eventAnalysis: ['GET', '/events/{event_key}/analysis'],
  qualificationForecast: ['GET', '/events/{event_key}/qualification-forecast'],
  eventRanking: ['GET', '/predictions/events/{event_key}/ranking'],
  matchWinProbability: ['GET', '/predictions/matches/{match_key}/win-probability'],
} as const satisfies Record<string, readonly ['GET', string]>

const ALL_ENDPOINTS = { ...ENDPOINTS, ...EXPLORER_ENDPOINTS }
type EndpointName = keyof typeof ALL_ENDPOINTS

/** An error in the API's envelope: {"error": {code, message, status, request_id}}. */
export class ApiRequestError extends Error {
  readonly code: string
  readonly status: number
  readonly requestId: string | null

  constructor(code: string, message: string, status: number, requestId: string | null) {
    super(message)
    this.name = 'ApiRequestError'
    this.code = code
    this.status = status
    this.requestId = requestId
  }
}

let writeToken = ''

/** The token is held in memory only; the page asks for it again after a reload. */
export function setWriteToken(token: string): void {
  writeToken = token
}

export function buildPath(name: EndpointName, params: Record<string, string | number> = {}): string {
  return ALL_ENDPOINTS[name][1].replace(/\{(\w+)\}/g, (_, key: string) => {
    if (!(key in params)) throw new Error(`missing path parameter ${key}`)
    return encodeURIComponent(String(params[key]))
  })
}

interface CallOptions {
  params?: Record<string, string | number>
  query?: Record<string, string | number | boolean | undefined>
  body?: unknown
  raw?: { data: BodyInit; contentType: string }
}

async function call<T>(name: EndpointName, options: CallOptions = {}): Promise<T> {
  const [method] = ALL_ENDPOINTS[name]
  let url = API_BASE + buildPath(name, options.params)
  const query = Object.entries(options.query ?? {}).filter(([, v]) => v !== undefined)
  if (query.length) url += '?' + new URLSearchParams(query.map(([k, v]) => [k, String(v)])).toString()
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined
  if (options.raw) {
    headers['Content-Type'] = options.raw.contentType
    body = options.raw.data
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (method !== 'GET' && writeToken) headers[WRITE_TOKEN_HEADER] = writeToken
  if (name === 'writeAccess' && writeToken) headers[WRITE_TOKEN_HEADER] = writeToken
  const response = await fetch(url, { method, headers, body })
  const text = await response.text()
  let parsed: unknown = null
  try {
    parsed = text ? JSON.parse(text) : null
  } catch {
    parsed = null
  }
  if (!response.ok) {
    const error = (parsed as { error?: { code?: string; message?: string; request_id?: string } } | null)?.error
    throw new ApiRequestError(error?.code ?? 'http_error', error?.message ?? `HTTP ${response.status}`,
      response.status, error?.request_id ?? null)
  }
  return parsed as T
}

export const api = {
  writeAccess: () => call<WriteAccess>('writeAccess'),

  listManuals: (season?: number) => call<Manual[]>('listManuals', { query: { season } }),
  uploadManual: (meta: { season: number; game_name: string; filename: string; uploaded_by: string }, file: Blob) =>
    call<{ manual: Manual; created: boolean }>('uploadManual', {
      query: meta,
      raw: { data: file, contentType: 'application/pdf' },
    }),
  manualFileUrl: (manualId: number) => API_BASE + buildPath('manualFile', { manual_id: manualId }),

  workflow: (season: number) => call<SeasonWorkflow>('workflow', { params: { season } }),
  listSpecs: (season: number) => call<SpecVersion[]>('listSpecs', { params: { season } }),
  saveSpec: (season: number, body: { spec_json: GameSpecDraft; created_by: string; manual_id: number | null;
    based_on_id: number | null }) => call<SpecVersion>('saveSpec', { params: { season }, body }),
  submitSpec: (specId: number) => call<SpecVersion>('submitSpec', { params: { spec_id: specId } }),
  reviewSpec: (specId: number, body: { reviewer: string; approve: boolean; note: string }) =>
    call<SpecVersion>('reviewSpec', { params: { spec_id: specId }, body }),

  listProfiles: (includeArchived: boolean) =>
    call<Profile[]>('listProfiles', { query: { include_archived: includeArchived } }),
  createProfile: (body: { profile_key: string; payload: CapabilityPayload; created_by: string }) =>
    call<Profile>('createProfile', { body }),
  editProfile: (profileKey: string, body: { payload: CapabilityPayload; created_by: string }) =>
    call<Profile>('editProfile', { params: { profile_key: profileKey }, body }),
  profileHistory: (profileKey: string) => call<Profile[]>('profileHistory', { params: { profile_key: profileKey } }),
  duplicateProfile: (profileKey: string, body: { new_key: string; created_by: string }) =>
    call<Profile>('duplicateProfile', { params: { profile_key: profileKey }, body }),
  archiveProfile: (profileKey: string, body: { archived_by: string }) =>
    call<Profile>('archiveProfile', { params: { profile_key: profileKey }, body }),
  recommendation: (profileKey: string, season: number) =>
    call<Recommendation>('recommendation', { params: { profile_key: profileKey }, query: { season } }),

  designExamples: () => call<DesignExample[]>('designExamples'),
  listArtifacts: (season: number, kind?: ArtifactKind) =>
    call<Artifact[]>('listArtifacts', { params: { season }, query: { kind } }),
  submitArtifact: (season: number, body: { kind: ArtifactKind; author: string; payload: unknown }) =>
    call<Artifact>('submitArtifact', { params: { season }, body }),
  establishArtifact: (artifactId: number, body: { established_by: string; note: string }) =>
    call<Artifact>('establishArtifact', { params: { artifact_id: artifactId }, body }),
  kappa: (season: number) => call<KappaStatus>('kappa', { params: { season } }),
  dm1Status: (season: number) => call<Dm1Status>('dm1Status', { params: { season } }),

  processingStatus: (manualId: number) => call<ProcessingState>('processingStatus', { params: { manual_id: manualId } }),
  startProcessing: (manualId: number, requestedBy: string) =>
    call<ProcessingState>('startProcessing', { params: { manual_id: manualId }, body: { requested_by: requestedBy } }),
  resolveIdentity: (manualId: number, body: { season: number; resolved_by: string; note: string }) =>
    call<ProcessingState>('resolveIdentity', { params: { manual_id: manualId }, body }),
  extraction: (manualId: number) => call<Extraction>('extraction', { params: { manual_id: manualId } }),
  pages: (manualId: number, first: number, last: number) =>
    call<PageText[]>('pages', { params: { manual_id: manualId }, query: { first, last } }),
  listRulesets: (season?: number) => call<RulesetVersion[]>('listRulesets', { query: { season } }),
  getRuleset: (rulesetId: number) => call<RulesetVersion>('getRuleset', { params: { ruleset_id: rulesetId } }),
  saveRuleset: (body: { ruleset_json: Record<string, unknown>; created_by: string }) =>
    call<RulesetVersion>('saveRuleset', { body }),
  submitRuleset: (rulesetId: number) => call<RulesetVersion>('submitRuleset', { params: { ruleset_id: rulesetId } }),
  reviewRuleset: (rulesetId: number, body: { reviewer: string; approve: boolean; note: string;
    reviewer_qualification: string; checklist: Record<string, boolean> | null; verified_sha256: string }) =>
    call<{ ruleset: RulesetVersion; approval_record: { path: string; next_step: string } | null }>(
      'reviewRuleset', { params: { ruleset_id: rulesetId }, body }),
  rulesetChecklist: () => call<ChecklistInfo>('rulesetChecklist'),
  rulesetWorksheet: (season: number) => call<Worksheet>('rulesetWorksheet', { params: { season } }),
  readiness: (season: number) => call<Readiness>('readiness', { params: { season } }),
}

/** Read-only historical season data and the existing analysis endpoints (never writes). */
export const explorer = {
  seasons: () => call<SeasonSummary[]>('seasons'),
  seasonEvents: (season: number) => call<EventSummary[]>('seasonEvents', { params: { season } }),
  eventTeams: (eventKey: string) =>
    call<{ event: EventInfo; teams: EventTeam[]; epa_source: string }>('eventTeams', { params: { event_key: eventKey } }),
  eventMatches: (eventKey: string) =>
    call<{ event: EventInfo; matches: EventMatch[] }>('eventMatches', { params: { event_key: eventKey } }),
  teamSeason: (teamNumber: number, season: number) =>
    call<TeamSeason>('teamSeason', { params: { team_number: teamNumber, season } }),
  teamMetrics: (teamNumber: number, eventKey: string) =>
    call<AnalysisBody>('teamMetrics', { params: { team_number: teamNumber, event_key: eventKey } }),
  teamStrength: (teamNumber: number, eventKey: string, asOf?: string) =>
    call<AnalysisBody>('teamStrength', { params: { team_number: teamNumber, event_key: eventKey }, query: { as_of: asOf } }),
  eventAnalysis: (eventKey: string, asOf?: string) =>
    call<AnalysisBody>('eventAnalysis', { params: { event_key: eventKey }, query: { as_of: asOf } }),
  qualificationForecast: (eventKey: string, asOf?: string) =>
    call<AnalysisBody>('qualificationForecast', { params: { event_key: eventKey }, query: { as_of: asOf } }),
  eventRanking: (eventKey: string) => call<AnalysisBody>('eventRanking', { params: { event_key: eventKey } }),
  matchWinProbability: (matchKey: string) =>
    call<AnalysisBody>('matchWinProbability', { params: { match_key: matchKey } }),
}

/** The season an event key belongs to (its first four digits), or null. */
export function seasonOfEvent(eventKey: string): number | null {
  const match = /^(\d{4})[a-z0-9]+$/.exec(eventKey)
  return match ? Number(match[1]) : null
}
