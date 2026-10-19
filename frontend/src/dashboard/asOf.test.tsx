import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { AsOfControl } from './asOf'
import { isoToLocalInput, localInputToIso } from './asOfParams'

const seen = { url: '' }
function Page() {
  const location = useLocation()
  useEffect(() => { seen.url = location.pathname + location.search })
  return <AsOfControl defaultNote="Default: now." />
}

function renderAt(url: string) {
  const router = createMemoryRouter([{ path: '/x', element: <Page /> }], { initialEntries: [url] })
  render(<RouterProvider router={router} />)
  return router
}

const input = () => screen.getByLabelText('Moment (as of)') as HTMLInputElement

describe('AsOfControl (P8-Q9, P8-Q11)', () => {
  it('shows the URL moment to the second, and Apply without a change keeps the exact URL moment', async () => {
    const exact = '2099-03-01T09:30:15.250Z' // sub-second: not representable in the input
    renderAt(`/x?as_of=${encodeURIComponent(exact)}&tab=teams`)
    expect(input().value).toBe(isoToLocalInput(exact))
    expect(input().value).toMatch(/:15$/)
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(new URLSearchParams(seen.url.split('?')[1]).get('as_of')).toBe(exact)
  })

  it('applies a new moment as an ISO instant and keeps the other parameters; Use default removes it', async () => {
    renderAt('/x?tab=teams')
    expect(screen.getByText('Default: now.')).toBeInTheDocument()
    fireEvent.change(input(), { target: { value: '2099-03-02T08:00:05' } })
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    const params = new URLSearchParams(seen.url.split('?')[1])
    expect(params.get('as_of')).toBe(localInputToIso('2099-03-02T08:00:05'))
    expect(params.get('tab')).toBe('teams')
    await userEvent.click(screen.getByRole('button', { name: 'Use default' }))
    expect(new URLSearchParams(seen.url.split('?')[1]).has('as_of')).toBe(false)
    expect(input().value).toBe('')
  })

  it('follows the URL on back and forward', async () => {
    const router = renderAt('/x')
    fireEvent.change(input(), { target: { value: '2099-03-02T08:00:00' } })
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    const applied = localInputToIso('2099-03-02T08:00:00')
    // compared as instants: the input normalises a zero seconds field away ("08:00")
    expect(localInputToIso(input().value)).toBe(applied)
    await act(async () => { await router.navigate(-1) })
    expect(input().value).toBe('')
    await act(async () => { await router.navigate(1) })
    expect(localInputToIso(input().value)).toBe(applied)
  })
})
