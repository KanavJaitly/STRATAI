// A fetch stand-in for component tests: routes "METHOD /path" (query string ignored) to canned responses and
// records every request. All data here is synthetic fixture data. It is not DM1 evidence and never reaches
// any database.

import { vi } from 'vitest'

export interface Recorded {
  method: string
  path: string
  query: URLSearchParams
  headers: Record<string, string>
  body: unknown
  rawBody: unknown
}

type Handler = (request: Recorded) => { status?: number; body: unknown } | unknown

export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: Recorded[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init.method ?? 'GET').toUpperCase()
    const path = url.pathname.replace(/^\/api/, '')
    const headers = Object.fromEntries(Object.entries((init.headers ?? {}) as Record<string, string>))
    let body: unknown = null
    if (typeof init.body === 'string') {
      try { body = JSON.parse(init.body) } catch { body = init.body }
    }
    const request: Recorded = { method, path, query: url.searchParams, headers, body, rawBody: init.body }
    calls.push(request)
    const key = `${method} ${path}`
    if (!(key in routes)) {
      return new Response(JSON.stringify({ error: { code: 'not_found', message: `unmocked ${key}`, status: 404 } }),
        { status: 404 })
    }
    const route = routes[key]
    const result = typeof route === 'function' ? (route as Handler)(request) : route
    const shaped = (result && typeof result === 'object' && 'body' in (result as object) && 'status' in (result as object))
      ? result as { status: number; body: unknown } : { status: 200, body: result }
    return new Response(JSON.stringify(shaped.body), { status: shaped.status })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock, writes: () => calls.filter((c) => c.method !== 'GET') }
}

export const WRITE_OK = { 'GET /human-inputs/write-access': { writes_enabled: true, token_accepted: true } }
export const WRITE_OFF = { 'GET /human-inputs/write-access': { writes_enabled: false, token_accepted: false } }

export function apiError(status: number, code: string, message: string) {
  return { status, body: { error: { code, message, status, request_id: 'req-test' } } }
}
