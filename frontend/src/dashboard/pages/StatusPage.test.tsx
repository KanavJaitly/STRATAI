import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { axeViolations, renderAt } from '../../test/dashboard'
import { apiError, mockApi } from '../../test/mockApi'
import { StatusPage } from './StatusPage'

describe('StatusPage (P8-M1 g)', () => {
  it('reports liveness and readiness exactly as the probes do', async () => {
    mockApi({ 'GET /health': { status: 'ok', env: 'development' }, 'GET /ready': { status: 'ready', checks: { database: 'ok' } } })
    const { container } = renderAt('/status', '/status', <StatusPage />)
    expect(await screen.findByText('ready')).toBeInTheDocument()
    expect(screen.getByText('database')).toBeInTheDocument()
    expect(screen.getByText(/environment development/)).toBeInTheDocument()
    expect(await axeViolations(container)).toEqual([])
  })

  it('shows a not-ready probe as such', async () => {
    mockApi({ 'GET /health': { status: 'ok', env: 'development' }, 'GET /ready': apiError(503, 'service_unavailable', 'Service unavailable') })
    renderAt('/status', '/status', <StatusPage />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('service_unavailable')
    expect(alert).toHaveTextContent('(503)')
  })
})
