import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError, isAbortError, requestJson } from './http'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

function stubFetch(impl: (url: string, init: RequestInit) => Promise<Response>) {
  const mock = vi.fn(impl)
  vi.stubGlobal('fetch', mock)
  return mock
}

describe('requestJson', () => {
  it('parses a JSON body', async () => {
    stubFetch(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }))
    await expect(requestJson('/x', { method: 'GET' })).resolves.toEqual({ ok: 1 })
  })

  it('resolves an empty 2xx body to null', async () => {
    stubFetch(async () => new Response(null, { status: 204 }))
    await expect(requestJson('/x', { method: 'GET' })).resolves.toBeNull()
  })

  it('turns the error envelope into an ApiRequestError with the server code, status and request id', async () => {
    stubFetch(async () => new Response(JSON.stringify({ error: { code: 'model_not_loaded', message: 'no model', status: 404,
      request_id: 'r1' } }), { status: 404 }))
    const error = await requestJson('/x', { method: 'GET' }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiRequestError)
    expect(error).toMatchObject({ code: 'model_not_loaded', status: 404, requestId: 'r1', message: 'no model' })
  })

  it('names a non-envelope HTTP error by its status', async () => {
    stubFetch(async () => new Response('Bad gateway', { status: 502 }))
    await expect(requestJson('/x', { method: 'GET' })).rejects.toMatchObject({ code: 'http_error', status: 502 })
  })

  it('reports a 2xx that is not JSON as malformed, never as data', async () => {
    stubFetch(async () => new Response('<html>', { status: 200 }))
    await expect(requestJson('/x', { method: 'GET' })).rejects.toMatchObject({ code: 'malformed_response' })
  })

  it('reports a network failure as network_error (status 0)', async () => {
    stubFetch(async () => { throw new TypeError('Failed to fetch') })
    await expect(requestJson('/x', { method: 'GET' })).rejects.toMatchObject({ code: 'network_error', status: 0 })
  })

  it('times out with a typed error', async () => {
    vi.useFakeTimers()
    stubFetch((_url, init) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const pending = requestJson('/x', { method: 'GET', timeoutMs: 1000 }).catch((e) => e)
    await vi.advanceTimersByTimeAsync(1001)
    expect(await pending).toMatchObject({ code: 'timeout', status: 0 })
  })

  it('rejects with an AbortError when the caller cancels, which is not an API error', async () => {
    stubFetch((_url, init) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const controller = new AbortController()
    const pending = requestJson('/x', { method: 'GET', signal: controller.signal }).catch((e) => e)
    controller.abort()
    const error = await pending
    expect(isAbortError(error)).toBe(true)
    expect(error).not.toBeInstanceOf(ApiRequestError)
  })

  it('does not even send a request whose signal is already aborted', async () => {
    const mock = stubFetch(async () => new Response('{}'))
    const controller = new AbortController()
    controller.abort()
    await expect(requestJson('/x', { method: 'GET', signal: controller.signal })).rejects.toSatisfy(isAbortError)
    expect(mock).not.toHaveBeenCalled()
  })
})
