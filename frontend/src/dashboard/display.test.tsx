import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { ApiRequestError } from '../api/client'
import { measure, unvalidatedWin, validatedWin } from '../test/dashboardFixtures'
import { axeViolations } from '../test/dashboard'
import { BarChart } from './charts'
import { reasonText } from './labels'
import { Absent, CalibratedProbabilityView, MeasureValue, OddsView, RefusalNotice, ValidationBadge } from './display'

describe('probability display (P8-Q4)', () => {
  it('shows a validated M6/M7 value as a probability with its label', () => {
    render(<CalibratedProbabilityView value={validatedWin(0.6)} />)
    expect(screen.getByText('60%')).toBeInTheDocument()
    expect(screen.getByText('approximately_calibrated_qualification')).toBeInTheDocument()
    expect(screen.queryByText(/unvalidated model output/i)).not.toBeInTheDocument()
  })

  it('never shows an unvalidated M6/M7 value as a probability', () => {
    const { container } = render(<CalibratedProbabilityView value={unvalidatedWin(0.7, 'playoff_scope')} />)
    expect(screen.getByText(/unvalidated model output/i)).toBeInTheDocument()
    expect(screen.getByText(/not a validated probability \(playoff_scope\)/)).toBeInTheDocument()
    expect(container.querySelector('.prob-value')).toBeNull() // the validated-probability style is not used
    expect(screen.getByText('not_validated')).toBeInTheDocument()
  })

  it('shows strategy odds as the served display string, and none as "No probability" with the reason', () => {
    const { rerender } = render(<OddsView odds={{ display: '<5%', validation: { status: 'not_validated', reasons: ['p6_m10_gate_failed'] } }} />)
    expect(screen.getByText('<5%')).toBeInTheDocument()
    expect(screen.getByText('p6_m10_gate_failed')).toBeInTheDocument()
    rerender(<OddsView odds={{ display: null, validation: { status: 'not_validated', reasons: ['playoff_model_unavailable'] } }} />)
    expect(screen.getByText('No probability')).toBeInTheDocument()
    expect(screen.getByText('playoff_model_unavailable')).toBeInTheDocument()
  })

  it('keeps validated_playoff_success and validated_playoff distinct (P7-D7)', () => {
    render(<>
      <ValidationBadge validation={{ status: 'validated_playoff_success' }} />
      <ValidationBadge validation={{ status: 'validated_playoff' }} />
    </>)
    const success = screen.getByText('validated_playoff_success') // shown verbatim, as served
    const match = screen.getByText('validated_playoff')
    expect(success.getAttribute('title')).toMatch(/PX-4/)
    expect(match.getAttribute('title')).toMatch(/PX-2/)
  })

  it('shows an unknown label verbatim rather than mapping it to a known one', () => {
    render(<ValidationBadge validation={{ status: 'some_new_label' }} />)
    expect(screen.getByText('some_new_label')).toHaveAttribute('title', expect.stringMatching(/shown as served/))
  })
})

describe('absence', () => {
  it('renders a missing measurement as a dash with its reason, never 0', () => {
    const { container } = render(<MeasureValue measure={measure(null, 0, 'no_completed_matches_before_as_of')} />)
    expect(container.textContent).toContain('—')
    expect(container.textContent).toContain('no completed matches before this moment')
    expect(container.querySelector('[data-reason]')?.getAttribute('data-reason')).toBe('no_completed_matches_before_as_of')
    expect(container.textContent).not.toMatch(/\b0\b/)
  })

  it('shows n and the SD with a present value', () => {
    render(<MeasureValue measure={{ value: 12.345, n: 7, uncertainty: { kind: 'sd', value: 2.5 }, absent_reason: null }} />)
    expect(screen.getByText('12.3')).toBeInTheDocument()
    expect(screen.getByText(/± 2.5 \(n = 7\)/)).toBeInTheDocument()
  })

  it('announces an absence to screen readers', () => {
    render(<Absent reason="why" />)
    expect(screen.getByText('not available')).toBeInTheDocument()
  })
})

describe('refusals (P8-Q5)', () => {
  it('explains a known refusal and keeps the code, status, message and request id visible', () => {
    render(<RefusalNotice what="Strategy" error={new ApiRequestError('model_not_loaded', 'No P6-M10 model', 404, 'req-9')} />)
    const notice = screen.getByRole('status')
    expect(within(notice).getByText(/Strategy: Model not loaded/)).toBeInTheDocument()
    expect(within(notice).getByText(/nothing is shown in its place/)).toBeInTheDocument()
    expect(notice.textContent).toContain('model_not_loaded')
    expect(notice.textContent).toContain('No P6-M10 model')
    expect(notice.textContent).toContain('req-9')
  })

  it('treats a transport failure as an alert', () => {
    render(<RefusalNotice error={new ApiRequestError('network_error', 'unreachable', 0, null)} />)
    expect(screen.getByRole('alert')).toHaveTextContent('API unreachable')
  })

  it('falls back to the server message for an unknown code', () => {
    render(<RefusalNotice error={new ApiRequestError('brand_new_code', 'The server explains it', 409, null)} />)
    expect(screen.getByRole('alert')).toHaveTextContent('The server explains it')
  })
})

describe('charts', () => {
  it('plots only served values, lists missing ones as missing, and has a text alternative', async () => {
    const { container } = render(<BarChart title="Alliance score" unit="points" points={[
      { label: 'Q1', value: 60 }, { label: 'Q2', value: null, note: 'not played' }, { label: 'Q3', value: 45 }]} />)
    expect(container.querySelectorAll('rect.chart-bar')).toHaveLength(2) // nothing drawn for the missing point
    expect(screen.getByRole('img')).toHaveAccessibleName(/2 values in points, from 45 to 60; 1 missing/)
    expect(screen.getByText(/missing \(not played\)/)).toBeInTheDocument()
    expect(await axeViolations(container)).toEqual([])
  })

  it('says there is nothing to plot rather than drawing an empty chart', () => {
    const { container } = render(<BarChart title="T" unit="points" points={[{ label: 'a', value: null }]} />)
    expect(container.querySelector('svg')).toBeNull()
    expect(screen.getAllByText(/No values to plot/).length).toBeGreaterThan(0)
  })

describe('label explanations', () => {
  it('reveal the plain explanation inline on activation, not only as a tooltip', async () => {
    render(<ValidationBadge validation={{ status: 'validated_playoff_success' }} />)
    const badge = screen.getByRole('button', { name: 'validated_playoff_success' })
    expect(badge).toHaveAttribute('aria-expanded', 'false')
    expect(badge).toHaveAccessibleDescription(/.+/)
    await userEvent.click(badge)
    expect(badge).toHaveAttribute('aria-expanded', 'true')
    expect(document.querySelector('.label-explain')?.textContent).toBe(badge.getAttribute('title'))
  })
})

describe('absence reasons in plain words', () => {
  it('maps known reasons, keeps unknown ones verbatim (even object-prototype names), and keeps the raw reason', () => {
    expect(reasonText('withheld_no_prior_event')).toBe('no EPA: no qualifying earlier event with an EPA')
    expect(reasonText('fewer_than_3_completed_matches_before_as_of')).toBe('fewer than 3 completed matches before this moment')
    expect(reasonText('insufficient_data: fewer than 2 scouting observations')).toBe('too few observations: fewer than 2 scouting observations')
    expect(reasonText('constructor')).toBe('constructor')
    expect(reasonText('some_new_reason')).toBe('some_new_reason')
  })

  it('shows the plain explanation first and the raw served code as visible text (D1.7 ruling, no hover needed)', () => {
    const { container } = render(<Absent reason="no_prior_concluded_event_epa" />)
    const plain = screen.getByText('no EPA: no qualifying earlier event with an EPA')
    const code = screen.getByText('(no_prior_concluded_event_epa)')
    expect(plain).toBeVisible()
    expect(code).toBeVisible()
    expect(code.tagName).toBe('CODE')
    expect(code.closest('.visually-hidden')).toBeNull() // visible text, not a screen-reader-only or hover-only copy
    expect(plain.compareDocumentPosition(code) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy() // plain words first
    expect(container.querySelector('[title]')).toBeNull() // nothing depends on a tooltip
    expect(container.textContent).toContain('not available') // the absence itself is announced
  })

  it('does not repeat a reason that has no plain-word mapping (it is already shown verbatim)', () => {
    const { container } = render(<Absent reason="some_new_reason" />)
    expect(screen.getByText('some_new_reason')).toBeVisible()
    expect(container.querySelector('code.reason-code')).toBeNull()
  })
})
})
