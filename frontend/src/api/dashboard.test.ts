import { afterEach, describe, expect, it, vi } from 'vitest'

import { baseline } from '../test/dashboardFixtures'
import { mockApi } from '../test/mockApi'
import { setWriteToken, WRITE_TOKEN_HEADER } from './client'
import { DASHBOARD_QUERY_PARAMS, dashboardApi, dashboardPath, queryString } from './dashboard'

afterEach(() => { setWriteToken(''); vi.useRealTimers(); vi.unstubAllGlobals() })

describe('dashboard client', () => {
  it('encodes path parameters', () => {
    expect(dashboardPath('preMatchReport', { match_key: '2099x_qm1' })).toBe('/matches/2099x_qm1/pre-match-report')
    expect(dashboardPath('eventTeams', { event_key: 'a/b' })).toBe('/events/a%2Fb/teams')
    expect(() => dashboardPath('eventTeams')).toThrow(/missing path parameter/)
  })

  it('repeats list query parameters and omits empty ones', () => {
    expect(queryString({ as_of: null, configuration: [1, 2, 3], x: undefined, y: '' })).toBe('?configuration=1&configuration=2&configuration=3')
    expect(queryString({})).toBe('')
  })

  it('sends the moment as as_of only when set', async () => {
    const api = mockApi({ 'GET /events/2099x/analysis': { ok: true } })
    await dashboardApi.eventAnalysis('2099x', null)
    await dashboardApi.eventAnalysis('2099x', '2099-03-01T00:00:00.000Z')
    expect(api.calls[0].query.has('as_of')).toBe(false)
    expect(api.calls[1].query.get('as_of')).toBe('2099-03-01T00:00:00.000Z')
  })

  it('never sends the write token on reads, and sends it on coach writes', async () => {
    setWriteToken('secret-token')
    const api = mockApi({ 'GET /events': { events: [] }, 'POST /strategy/matches/m/recommend': {},
      'POST /strategy/coach-observations': { observation: {} } })
    await dashboardApi.events(2099)
    await dashboardApi.matchRecommend('m', { side: 'red' })
    await dashboardApi.coachObservation({ event_key: 'e', team_number: 1, kind: 'robot_unavailable',
      observed_at: '2099-01-01T00:00:00Z', observer: 'x' })
    expect(api.calls[0].headers[WRITE_TOKEN_HEADER]).toBeUndefined()
    expect(api.calls[1].headers[WRITE_TOKEN_HEADER]).toBeUndefined()
    expect(api.calls[2].headers[WRITE_TOKEN_HEADER]).toBe('secret-token')
  })

  it('sends the write token on no read or engine call: every dashboardApi method except the two coach writes', async () => {
    setWriteToken('secret-token')
    const seen: { url: string; headers: Record<string, string> }[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      seen.push({ url, headers: (init.headers ?? {}) as Record<string, string> })
      return new Response('{}', { status: 200 })
    }))
    const strategy = baseline([1, 2, 3])
    const pairing = { event_key: 'e', red_team_numbers: [1, 2, 3], blue_team_numbers: [4, 5, 6],
      match_context: 'qualification' as const }
    const reads: Record<string, () => Promise<unknown>> = {
      health: () => dashboardApi.health(), ready: () => dashboardApi.ready(), events: () => dashboardApi.events(2099),
      eventTeams: () => dashboardApi.eventTeams('e'), eventMatches: () => dashboardApi.eventMatches('e', null),
      eventAnalysis: () => dashboardApi.eventAnalysis('e', null),
      qualificationForecast: () => dashboardApi.qualificationForecast('e', null),
      teamMetrics: () => dashboardApi.teamMetrics(1, 'e'), teamStrength: () => dashboardApi.teamStrength(1, 'e', null),
      matchWinProbability: () => dashboardApi.matchWinProbability('m'),
      allianceWinProbability: () => dashboardApi.allianceWinProbability(pairing, null),
      allianceSynergy: () => dashboardApi.allianceSynergy({ event_key: 'e', team_numbers: [1, 2, 3] }, null),
      candidates: () => dashboardApi.candidates('e', null, null),
      pickList: () => dashboardApi.pickList('e', { seed: 1, alliances: [], declined: [], turns_taken: 0 }),
      matchAssess: () => dashboardApi.matchAssess('m', { side: 'red', strategy }),
      matchRecommend: () => dashboardApi.matchRecommend('m', { side: 'red' }),
      matchCompare: () => dashboardApi.matchCompare('m', { side: 'red', first: strategy, second: strategy }),
      hypotheticalAssess: () => dashboardApi.hypotheticalAssess({ ...pairing, side: 'red', strategy }, null),
      hypotheticalRecommend: () => dashboardApi.hypotheticalRecommend({ ...pairing, side: 'red' }, null),
      hypotheticalCompare: () => dashboardApi.hypotheticalCompare({ ...pairing, side: 'red', first: strategy, second: strategy }, null),
      preMatchReport: () => dashboardApi.preMatchReport('m', null),
    }
    // every method is covered: a new one must be added here (or is a write)
    expect(Object.keys(reads).sort()).toEqual(Object.keys(dashboardApi).filter((k) => !k.startsWith('coach')).sort())
    for (const call of Object.values(reads)) await call()
    expect(seen).toHaveLength(Object.keys(reads).length)
    for (const request of seen) expect(request.headers[WRITE_TOKEN_HEADER], request.url).toBeUndefined()
  })

  it('sends the coach strategy with the token and the body as given', async () => {
    setWriteToken('secret-token')
    const api = mockApi({ 'POST /strategy/coach-strategies': { status: 201, body: {} } })
    const body = { event_key: 'e', match_key: 'm', author: 'A', strategy: baseline([1, 2, 3]) }
    await dashboardApi.coachStrategy(body)
    expect(api.calls[0].headers[WRITE_TOKEN_HEADER]).toBe('secret-token')
    expect(api.calls[0].body).toEqual(body)
  })

  it('refuses a query parameter the operation does not declare (FastAPI would silently ignore it)', () => {
    const declared = DASHBOARD_QUERY_PARAMS.eventAnalysis
    const params = DASHBOARD_QUERY_PARAMS as Record<string, readonly string[]>
    params.eventAnalysis = []
    try {
      expect(() => dashboardApi.eventAnalysis('e', '2099-01-01T00:00:00Z')).toThrow(/does not declare query parameter\(s\) as_of/)
    } finally {
      params.eventAnalysis = declared
    }
  })

  it('lets a coach write wait past the read timeout (no client-side timeout that could invite a duplicate)', async () => {
    vi.useFakeTimers()
    let resolve!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit = {}) => new Promise<Response>((r, reject) => {
      resolve = r
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))) // as fetch does
    })))
    const outcome = dashboardApi.coachObservation({ event_key: 'e', team_number: 1, kind: 'robot_unavailable',
      observed_at: '2099-01-01T00:00:00Z', observer: 'x' }).then(() => 'stored', (e: { code?: string }) => e.code)
    await vi.advanceTimersByTimeAsync(120_000)
    resolve(new Response('{}', { status: 201 }))
    expect(await outcome).toBe('stored')
    const read = dashboardApi.events(2099).then(() => 'ok', (e: { code?: string }) => e.code)
    await vi.advanceTimersByTimeAsync(30_001)
    expect(await read).toBe('timeout')
  })
})
