import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PreMatchReportResponse } from '../../api/generated'
import { axeViolations, currentUrl, renderAt } from '../../test/dashboard'
import { BLUE, CONTEXT, MATCH, RECOMMEND, RED, REPORT, STRATEGY_MODEL, validatedWin } from '../../test/dashboardFixtures'
import { mockApi } from '../../test/mockApi'
import { ReportPage } from './ReportPage'

const PATTERN = '/report/:matchKey'
afterEach(() => vi.unstubAllGlobals())

const WITH_ENGINES: PreMatchReportResponse = {
  ...REPORT,
  win_probability: { probability_scope: 'qualification', value: validatedWin(0.6), absent_code: null, absent_reason: null },
  strategy: { model: STRATEGY_MODEL, context: CONTEXT, absent_code: null, absent_reason: null, sides: [
    { side: 'red', recommended: RECOMMEND.recommended, baseline: RECOMMEND.baseline, vs_baseline_label: RECOMMEND.vs_baseline_label,
      candidates_evaluated: 21952, selection_note: RECOMMEND.selection_note, unavailable_reasons: [] },
    { side: 'blue', recommended: null, baseline: null, vs_baseline_label: null, candidates_evaluated: 0,
      selection_note: RECOMMEND.selection_note, unavailable_reasons: ['insufficient_data'] }] },
}

describe('ReportPage (P8-M6)', () => {
  it('shows every unproduced item as an explicit absence with its meaning (P7-Q12, P8-Q6)', async () => {
    mockApi({ [`GET /matches/${MATCH}/pre-match-report`]: REPORT })
    const { container } = renderAt(PATTERN, `/report/${MATCH}`, <ReportPage />)
    await screen.findByRole('heading', { name: `Pre-match report · ${MATCH}` })
    for (const title of ['Strengths and weaknesses per robot', 'Defensive threats', 'Key risks', 'Predicted flow',
      'Critical matchups', 'Key success factors']) {
      const item = screen.getByRole('heading', { name: title }).closest('.not-produced') as HTMLElement
      expect(within(item).getByText('not produced by any engine')).toBeInTheDocument()
    }
    expect(screen.getByText('Opposing robots likely to play effective defense.')).toBeInTheDocument()
    expect(await axeViolations(container)).toEqual([])
  })

  it('shows absent model parts with their codes, and synergy only where served', async () => {
    mockApi({ [`GET /matches/${MATCH}/pre-match-report`]: REPORT })
    renderAt(PATTERN, `/report/${MATCH}`, <ReportPage />)
    const forecast = (await screen.findByRole('heading', { name: 'Match forecast' })).closest('section') as HTMLElement
    expect(within(forecast).getByText('model_not_loaded')).toBeInTheDocument()
    expect(within(forecast).queryByText(/%/)).toBeNull() // no probability without the model
    const ours = screen.getByRole('heading', { name: /Our alliance/ }).closest('section') as HTMLElement
    expect(within(ours).getByText('0.42')).toBeInTheDocument() // red synergy, served
    const theirs = screen.getByRole('heading', { name: /Opposing alliance/ }).closest('section') as HTMLElement
    expect(within(theirs).getByText('alliance_incomplete')).toBeInTheDocument()
    expect(ours.querySelectorAll('[data-reason="model_not_loaded"]')).toHaveLength(1) // roles absent, stated once
    expect(within(ours).getByText('model not loaded')).toBeInTheDocument()
  })

  it('fills roles from the engine\'s strategy and the forecast from M6/M7 when served', async () => {
    mockApi({ [`GET /matches/${MATCH}/pre-match-report`]: WITH_ENGINES })
    renderAt(PATTERN, `/report/${MATCH}`, <ReportPage />)
    const ours = (await screen.findByRole('heading', { name: /Our alliance/ })).closest('section') as HTMLElement
    expect(within(ours).getByText(`Defense on ${BLUE[0]}`)).toBeInTheDocument()
    expect(within(ours).getByText('65%')).toBeInTheDocument()
    const forecast = screen.getByRole('heading', { name: 'Match forecast' }).closest('section') as HTMLElement
    expect(within(forecast).getByText('60%')).toBeInTheDocument()
    const theirs = screen.getByRole('heading', { name: /Opposing alliance/ }).closest('section') as HTMLElement
    expect(within(theirs).getByText(/The engine gives no probability: insufficient_data/)).toBeInTheDocument()
  })

  it('swaps our alliance through the URL, so the link reproduces the view', async () => {
    mockApi({ [`GET /matches/${MATCH}/pre-match-report`]: REPORT })
    renderAt(PATTERN, `/report/${MATCH}`, <ReportPage />)
    await screen.findByRole('heading', { name: /Our alliance/ })
    await userEvent.click(screen.getByRole('radio', { name: 'Our alliance: Blue' }))
    expect(currentUrl()).toBe(`/report/${MATCH}?side=blue`)
    const ours = screen.getByRole('heading', { name: /Our alliance/ }).closest('section') as HTMLElement
    expect(within(ours).getAllByText(String(BLUE[0])).length).toBeGreaterThan(0)
    expect(within(ours).queryByText(String(RED[0]))).toBeNull()
  })

  it('passes the moment through and copies the link (or shows it when the clipboard is unavailable)', async () => {
    const api = mockApi({ [`GET /matches/${MATCH}/pre-match-report`]: REPORT })
    renderAt(PATTERN, `/report/${MATCH}?as_of=2099-03-01T09%3A00%3A00Z`, <ReportPage />)
    await screen.findByRole('heading', { name: /Pre-match report/ })
    expect(api.calls.find((c) => c.path.endsWith('/pre-match-report'))?.query.get('as_of')).toBe('2099-03-01T09:00:00Z')
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
    await userEvent.click(screen.getByRole('button', { name: 'Copy link' }))
    expect(await screen.findByText(/Copy this link/)).toBeInTheDocument()
  })

  it('opens every collapsed section for printing and restores it afterwards', async () => {
    mockApi({ [`GET /matches/${MATCH}/pre-match-report`]: REPORT })
    const { container } = renderAt(PATTERN, `/report/${MATCH}`, <ReportPage />)
    await screen.findByRole('heading', { name: 'Evidence per robot' })
    const details = [...container.querySelectorAll('details')]
    expect(details.length).toBeGreaterThan(0)
    expect(details.every((d) => !d.open)).toBe(true)
    window.dispatchEvent(new Event('beforeprint'))
    expect(details.every((d) => d.open)).toBe(true)
    window.dispatchEvent(new Event('afterprint'))
    expect(details.every((d) => !d.open)).toBe(true)
    expect(document.title).toBe(`Pre-match report · ${MATCH} · STRATAI`)
  })
})

