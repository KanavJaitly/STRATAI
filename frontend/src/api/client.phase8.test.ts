// The Phase 5 client on the shared fetch core (P8-D1 D1.3). The Phase 5 tests in client.test.ts are unchanged; these
// pin what changed: reads time out, writes (and the manual upload) never do, nothing is retried, and errors are typed.

import { afterEach, describe, expect, it, vi } from 'vitest'

import type { CapabilityPayload } from './types'
import { api, ApiRequestError, ENDPOINTS, setWriteToken, WRITE_TOKEN_HEADER } from './client'

afterEach(() => { setWriteToken(''); vi.useRealTimers(); vi.unstubAllGlobals() })

/** A fetch that never answers until released, and rejects on abort as fetch does. */
function hangingFetch() {
  const calls: { method: string; headers: Record<string, string> }[] = []
  let release: (response: Response) => void = () => {}
  vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit = {}) => new Promise<Response>((resolve, reject) => {
    calls.push({ method: init.method ?? 'GET', headers: (init.headers ?? {}) as Record<string, string> })
    release = resolve
    init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })))
  return { calls, release: (r: Response) => release(r) }
}

const profile = { profile_key: 'k', payload: {} as CapabilityPayload, created_by: 'Test Person' }

describe('Phase 5 client on the shared core', () => {
  it('times a read out after 30 s with a typed error, sent once', async () => {
    vi.useFakeTimers()
    const fetchState = hangingFetch()
    const outcome = api.dm1Status(2099).then(() => 'ok', (e: ApiRequestError) => `${e.code}:${e.status}`)
    await vi.advanceTimersByTimeAsync(30_001)
    expect(await outcome).toBe('timeout:0')
    expect(fetchState.calls).toHaveLength(1)
  })

  it('lets a write wait for the server however long it takes (no client timeout to invite a duplicate)', async () => {
    vi.useFakeTimers()
    setWriteToken('token')
    const fetchState = hangingFetch()
    const outcome = api.createProfile(profile).then(() => 'stored', (e: ApiRequestError) => e.code)
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    fetchState.release(new Response(JSON.stringify({ profile_key: 'k' }), { status: 201 }))
    expect(await outcome).toBe('stored')
    expect(fetchState.calls).toHaveLength(1) // never retried
    expect(fetchState.calls[0].headers[WRITE_TOKEN_HEADER]).toBe('token')
  })

  it('lets the manual upload wait too', async () => {
    vi.useFakeTimers()
    const fetchState = hangingFetch()
    const outcome = api.uploadManual({ season: 2099, game_name: 'g', filename: 'm.pdf', uploaded_by: 'x' },
      new Blob(['%PDF'])).then(() => 'uploaded', (e: ApiRequestError) => e.code)
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    fetchState.release(new Response(JSON.stringify({ manual: {}, created: true }), { status: 201 }))
    expect(await outcome).toBe('uploaded')
  })

  it('reports a failed connection on a write as a typed network_error, once, with no retry', async () => {
    const fetchMock = vi.fn(async () => { throw new TypeError('Failed to fetch') })
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.createProfile(profile)).rejects.toMatchObject({ code: 'network_error', status: 0 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('says a malformed success on a write was accepted, so nobody resubmits it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>', { status: 201 })))
    const error = await api.createProfile(profile).catch((e: ApiRequestError) => e)
    expect(error).toBeInstanceOf(ApiRequestError)
    expect(error).toMatchObject({ code: 'malformed_response', status: 201 })
    expect((error as Error).message).toMatch(/request was accepted/)
  })

  it('keeps the envelope error of a refused write as served', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'write_not_authorized',
      message: 'Token rejected', status: 403, request_id: 'r1' } }), { status: 403 })))
    await expect(api.createProfile(profile)).rejects.toMatchObject({ code: 'write_not_authorized', status: 403, requestId: 'r1' })
  })

  // Every Phase 5 write, named, so a new write cannot slip past this check (the list must equal ENDPOINTS' non-GETs).
  const WRITES: Record<string, () => Promise<unknown>> = {
    uploadManual: () => api.uploadManual({ season: 2099, game_name: 'g', filename: 'm.pdf', uploaded_by: 'x' }, new Blob(['%PDF'])),
    saveSpec: () => api.saveSpec(2099, {} as never),
    submitSpec: () => api.submitSpec(1),
    reviewSpec: () => api.reviewSpec(1, { reviewer: 'r', approve: true, note: '' }),
    createProfile: () => api.createProfile(profile),
    editProfile: () => api.editProfile('k', { payload: {} as CapabilityPayload, created_by: 'x' }),
    duplicateProfile: () => api.duplicateProfile('k', { new_key: 'k2', created_by: 'x' }),
    archiveProfile: () => api.archiveProfile('k', { archived_by: 'x' }),
    submitArtifact: () => api.submitArtifact(2099, { kind: 'codebook' as never, author: 'x', payload: {} }),
    establishArtifact: () => api.establishArtifact(1, { established_by: 'x', note: '' }),
    // The game manual manager and season rulesets (2026-10-11), merged after Phase 8: the same guarantees.
    startProcessing: () => api.startProcessing(1, 'x'),
    resolveIdentity: () => api.resolveIdentity(1, { season: 2099, resolved_by: 'x', note: 'n' }),
    saveRuleset: () => api.saveRuleset({ ruleset_json: {}, created_by: 'x' }),
    submitRuleset: () => api.submitRuleset(1),
    reviewRuleset: () => api.reviewRuleset(1, { reviewer: 'r', approve: false, note: 'n', reviewer_qualification: '',
      checklist: null, verified_sha256: '' }),
  }

  it('covers every Phase 5 write operation', () => {
    const writes = Object.entries(ENDPOINTS).filter(([, [method]]) => method !== 'GET').map(([name]) => name).sort()
    expect(Object.keys(WRITES).sort()).toEqual(writes)
  })

  it.each(Object.keys(WRITES))('%s waits for the server (no client timeout), is sent once, and is never retried', async (name) => {
    vi.useFakeTimers()
    const fetchState = hangingFetch()
    const outcome = WRITES[name]().then(() => 'answered', (e: ApiRequestError) => e.code)
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    expect(fetchState.calls).toHaveLength(1)
    fetchState.release(new Response('{}', { status: 200 }))
    expect(await outcome).toBe('answered')
    expect(fetchState.calls).toHaveLength(1)
  })

  it('tells the person a failed write may still have been stored, and a failed read only that the API was unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const write = await api.duplicateProfile('k', { new_key: 'k2', created_by: 'x' }).catch((e: Error) => e)
    expect((write as Error).message).toMatch(/may still have been stored: check before submitting it again/)
    const read = await api.dm1Status(2099).catch((e: Error) => e)
    expect((read as Error).message).not.toMatch(/stored/)
  })
})

