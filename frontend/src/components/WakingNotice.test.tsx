import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WakingNotice } from './WakingNotice'

afterEach(() => vi.useRealTimers())

describe('the waking-up notice', () => {
  it('stays hidden for a quick answer and appears once the wait passes a few seconds', () => {
    vi.useFakeTimers()
    render(<WakingNotice after={4000} />)
    expect(screen.queryByText(/Waking up the server/)).not.toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(3900) })
    expect(screen.queryByText(/Waking up the server/)).not.toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(200) })
    expect(screen.getByRole('status')).toHaveTextContent(/up to a minute/)
  })
})
