import { useEffect, useRef, useState } from 'react'

import { isAbortError } from '../api/http'

/** Runs one engine call on demand; a newer call or an unmount cancels the older one. */
export function useOnDemand<T>(): { result: T | null; error: unknown; busy: boolean;
  run: (call: (signal: AbortSignal) => Promise<T>) => void; reset: () => void } {
  const [state, setState] = useState<{ result: T | null; error: unknown; busy: boolean }>({ result: null, error: null, busy: false })
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const run = (call: (signal: AbortSignal) => Promise<T>) => {
    controller.current?.abort()
    const mine = new AbortController()
    controller.current = mine
    setState({ result: null, error: null, busy: true })
    call(mine.signal).then(
      (result) => { if (controller.current === mine) setState({ result, error: null, busy: false }) },
      (error: unknown) => {
        if (isAbortError(error) || controller.current !== mine) return
        setState({ result: null, error, busy: false })
      },
    )
  }
  const reset = () => { controller.current?.abort(); setState({ result: null, error: null, busy: false }) }
  return { ...state, run, reset }
}
