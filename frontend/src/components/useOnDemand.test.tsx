import { act, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { describe, expect, it } from 'vitest'

import { useOnDemand } from './useOnDemand'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

type Handle = ReturnType<typeof useOnDemand<string>>

const handle: { current?: Handle } = {}

function Probe() {
  const demand = useOnDemand<string>()
  useEffect(() => { handle.current = demand })
  return <p>{demand.busy ? 'busy' : demand.error ? `error: ${(demand.error as Error).message}` : demand.result ?? 'idle'}</p>
}

describe('useOnDemand', () => {
  it('a newer call aborts the older one, and the older answer never shows', async () => {
    render(<Probe />)
    const first = deferred<string>()
    const second = deferred<string>()
    const signals: AbortSignal[] = []
    act(() => handle.current!.run((s) => { signals.push(s); return first.promise }))
    act(() => handle.current!.run((s) => { signals.push(s); return second.promise }))
    expect(signals[0].aborted).toBe(true)
    expect(signals[1].aborted).toBe(false)
    await act(async () => { second.resolve('second') })
    await act(async () => { first.resolve('first') }) // late: ignored
    expect(screen.getByText('second')).toBeInTheDocument()
  })

  it('keeps an error for display, ignores cancellations, and reset clears and aborts', async () => {
    render(<Probe />)
    const failing = deferred<string>()
    act(() => handle.current!.run(() => failing.promise))
    await act(async () => { failing.reject(new Error('refused')) })
    expect(screen.getByText('error: refused')).toBeInTheDocument()
    const pending = deferred<string>()
    let signal!: AbortSignal
    act(() => handle.current!.run((s) => { signal = s; return pending.promise }))
    expect(screen.getByText('busy')).toBeInTheDocument()
    act(() => handle.current!.reset())
    expect(signal.aborted).toBe(true)
    await act(async () => { pending.reject(new DOMException('cancelled', 'AbortError')) })
    expect(screen.getByText('idle')).toBeInTheDocument()
  })

  it('aborts the call in flight on unmount', () => {
    const view = render(<Probe />)
    let signal!: AbortSignal
    act(() => handle.current!.run((s) => { signal = s; return new Promise(() => {}) }))
    view.unmount()
    expect(signal.aborted).toBe(true)
  })
})
