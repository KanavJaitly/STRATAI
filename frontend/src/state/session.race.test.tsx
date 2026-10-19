// P8-D1 D1.4: the write-access probe's sequence guard. A separate file: the Phase 5 tests stay unchanged.
// Documented behaviour (not debounced): every token change sends one GET /human-inputs/write-access. It is a read
// that stores nothing, carries the token only in a header to the same-origin API, and only the newest answer is
// applied, so a burst of probes cannot leave the session showing a stale verdict.

import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { setWriteToken, WRITE_TOKEN_HEADER } from '../api/client'
import { mockApi } from '../test/mockApi'
import { SessionProvider, useSession } from './session'

afterEach(() => { setWriteToken(''); vi.unstubAllGlobals() })

function Probe() {
  const { token, setToken, access } = useSession()
  const verdict = access === null ? 'unknown' : access.token_accepted ? 'accepted' : 'rejected'
  return <><input aria-label="token" value={token} onChange={(e) => setToken(e.target.value)} /><p>verdict: {verdict}</p></>
}

describe('session write-access probe (D1.4)', () => {
  it('applies only the newest answer: a late answer for an earlier partial token never overwrites it', async () => {
    const pending = new Map<string, (accepted: boolean) => void>()
    const api = mockApi({ 'GET /human-inputs/write-access': (request: { headers: Record<string, string> }) =>
      new Promise((resolve) => {
        pending.set(request.headers[WRITE_TOKEN_HEADER] ?? '', (accepted) =>
          resolve({ writes_enabled: true, token_accepted: accepted }))
      }) })
    render(<SessionProvider><Probe /></SessionProvider>)
    await act(async () => { pending.get('')!(false) })
    expect(screen.getByText('verdict: rejected')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('token'), 'ab') // two keystrokes: probes for "a" then "ab"
    const probes = api.calls.filter((c) => c.path === '/human-inputs/write-access')
    expect(probes.map((c) => c.headers[WRITE_TOKEN_HEADER] ?? '')).toEqual(['', 'a', 'ab']) // one per change, no debounce
    expect(probes.every((c) => c.method === 'GET')).toBe(true) // a read: nothing is stored

    await act(async () => { pending.get('ab')!(true) }) // the newest answer first…
    expect(screen.getByText('verdict: accepted')).toBeInTheDocument()
    await act(async () => { pending.get('a')!(false) }) // …then the stale one for the partial token
    expect(screen.getByText('verdict: accepted')).toBeInTheDocument() // ignored
  })
})
