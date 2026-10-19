import { act, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { describe, expect, it } from 'vitest'

import { useResource } from './useResource'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

describe('useResource', () => {
  it('ignores a slow old response once newer parameters have loaded (no stale overwrite)', async () => {
    const pending: Record<string, ReturnType<typeof deferred<string>>> = { a: deferred(), b: deferred() }
    const signals: Record<string, AbortSignal> = {}
    const handle: { setKey?: (k: string) => void } = {}
    function Probe() {
      const [key, set] = useState('a')
      useEffect(() => { handle.setKey = set }, [set])
      const r = useResource((signal) => { signals[key] = signal; return pending[key].promise }, key)
      return <p>{r.loading ? 'loading' : r.data}</p>
    }
    render(<Probe />)
    act(() => handle.setKey!('b'))
    expect(signals.a.aborted).toBe(true) // the old request is cancelled
    await act(async () => { pending.b.resolve('B') })
    await act(async () => { pending.a.resolve('A') }) // arrives late: ignored
    expect(screen.getByText('B')).toBeInTheDocument()
  })

  it('fetches nothing when disabled', () => {
    let calls = 0
    function Probe() {
      const r = useResource(async () => { calls += 1; return 'x' }, 'k', false)
      return <p>{r.loading ? 'loading' : 'idle'}</p>
    }
    render(<Probe />)
    expect(calls).toBe(0)
    expect(screen.getByText('idle')).toBeInTheDocument()
  })

  it('keeps errors for display and refetches on reload', async () => {
    let attempt = 0
    const handle: { reload?: () => void } = {}
    function Probe() {
      const r = useResource(async () => { attempt += 1; if (attempt === 1) throw new Error('boom'); return 'ok' }, 'k')
      useEffect(() => { handle.reload = r.reload })
      return <p>{r.error ? `error: ${(r.error as Error).message}` : r.loading ? 'loading' : r.data}</p>
    }
    render(<Probe />)
    expect(await screen.findByText('error: boom')).toBeInTheDocument()
    act(() => handle.reload!())
    expect(await screen.findByText('ok')).toBeInTheDocument()
  })

  it('aborts the request in flight on unmount', () => {
    let signal!: AbortSignal
    function Probe() {
      useResource((s) => { signal = s; return new Promise<string>(() => {}) }, 'k')
      return null
    }
    const view = render(<Probe />)
    view.unmount()
    expect(signal.aborted).toBe(true)
  })

  it('keeps the previous data visible while a reload of the same key is pending; a new key starts empty', async () => {
    const answers = [deferred<string>(), deferred<string>(), deferred<string>()]
    let attempt = 0
    const handle: { reload?: () => void; setKey?: (k: string) => void } = {}
    function Probe() {
      const [key, setKey] = useState('a')
      const r = useResource(() => answers[attempt++].promise, key)
      useEffect(() => { handle.reload = r.reload; handle.setKey = setKey }, [r.reload])
      return <p>{`${r.loading ? 'loading' : 'settled'}:${r.data ?? 'none'}`}</p>
    }
    render(<Probe />)
    await act(async () => { answers[0].resolve('first') })
    expect(screen.getByText('settled:first')).toBeInTheDocument()
    act(() => handle.reload!())
    expect(screen.getByText('loading:first')).toBeInTheDocument() // reload: the old data stays
    await act(async () => { answers[1].resolve('second') })
    expect(screen.getByText('settled:second')).toBeInTheDocument()
    act(() => handle.setKey!('b'))
    expect(screen.getByText('loading:none')).toBeInTheDocument() // new parameters: never the old key's data
  })
})

