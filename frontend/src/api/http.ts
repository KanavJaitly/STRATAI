// The one fetch core both API clients use (the human-input client.ts and the dashboard client dashboard.ts).
// It turns every failure into a typed ApiRequestError, so a page can always show what happened:
// - an API error in the envelope {"error": {code, message, status, request_id}}: the server's code and message;
// - no response at all (network down, API not running): code `network_error`, status 0;
// - no response within the timeout: code `timeout`, status 0;
// - a 2xx whose body is not JSON: code `malformed_response`.
// A request cancelled by its caller (unmount, changed parameters) rejects with an AbortError, which callers ignore.

/** An error in the API's envelope, or a transport failure given the same shape. */
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

export const DEFAULT_TIMEOUT_MS = 30_000

export interface RequestOptions {
  method: string
  headers?: Record<string, string>
  body?: BodyInit
  /** The caller's cancellation; aborting it rejects with an AbortError. */
  signal?: AbortSignal
  /** Rejects with ApiRequestError('timeout') after this many milliseconds; 0 disables it. */
  timeoutMs?: number
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

/** Sends one request and parses its JSON body. A 2xx with an empty body resolves to null. The timeout and the caller's
 * cancellation cover the whole exchange, including reading the body. */
export async function requestJson<T>(url: string, options: RequestOptions): Promise<T> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const controller = new AbortController()
  let timedOut = false
  const onCallerAbort = () => controller.abort()
  if (options.signal) {
    if (options.signal.aborted) throw new DOMException('The request was cancelled.', 'AbortError')
    options.signal.addEventListener('abort', onCallerAbort, { once: true })
  }
  const timer = timeoutMs > 0 ? setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs) : null
  let response: Response
  let text: string
  try {
    response = await fetch(url, { method: options.method, headers: options.headers, body: options.body,
      signal: controller.signal })
    text = await response.text()
  } catch (caught) {
    if (timedOut) {
      throw new ApiRequestError('timeout', `No response within ${Math.round(timeoutMs / 1000)} s.`, 0, null)
    }
    if (options.signal?.aborted) throw new DOMException('The request was cancelled.', 'AbortError')
    const detail = caught instanceof Error ? caught.message : String(caught)
    // A write may have reached the server before the connection failed: say so, so nobody resubmits blindly.
    const write = options.method.toUpperCase() !== 'GET'
    throw new ApiRequestError('network_error', `The API could not be reached (${detail}).`
      + (write ? ' The request may still have been stored: check before submitting it again.' : ''), 0, null)
  } finally {
    if (timer) clearTimeout(timer)
    options.signal?.removeEventListener('abort', onCallerAbort)
  }
  let parsed: unknown = null
  let malformed = false
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      malformed = true
    }
  }
  if (!response.ok) {
    const error = (parsed as { error?: { code?: string; message?: string; request_id?: string } } | null)?.error
    throw new ApiRequestError(error?.code ?? 'http_error', error?.message ?? `HTTP ${response.status}`,
      response.status, error?.request_id ?? null)
  }
  if (malformed) {
    // The server answered with success: for a write, it has been stored. Say so, so nobody resubmits.
    throw new ApiRequestError('malformed_response', `The API answered with success (HTTP ${response.status}), so the `
      + 'request was accepted, but its response is not valid JSON.', response.status, null)
  }
  return parsed as T
}
