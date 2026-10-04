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
} as const satisfies Record<string, readonly [Method, string]>

type EndpointName = keyof typeof ENDPOINTS

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
  return ENDPOINTS[name][1].replace(/\{(\w+)\}/g, (_, key: string) => {
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
  const [method] = ENDPOINTS[name]
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
}
