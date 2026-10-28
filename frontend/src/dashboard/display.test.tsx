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
    expect(screen.getByText('Red 60%')).toBeInTheDocument()
    expect(screen.getByText('Validated (qualification)')).toHaveAttribute('data-status', 'approximately_calibrated_qualification')
    expect(screen.queryByText(/unvalidated model output/i)).not.toBeInTheDocument()
  })

  it('names the favoured alliance, so a blue favourite reads as blue', () => {
    render(<CalibratedProbabilityView value={validatedWin(0.16)} />)
    expect(screen.getByText('Blue 84%')).toBeInTheDocument()
  })

  it('never shows an unvalidated M6/M7 value as a probability', () => {
    const { container } = render(<CalibratedProbabilityView value={unvalidatedWin(0.7, 'playoff_scope')} />)
    expect(screen.getByText(/unvalidated model output/i)).toBeInTheDocument()
    expect(screen.getByText(/not a validated probability \(a playoff match; the model is validated for qualification matches only\)/)).toBeInTheDocument()
    expect(container.querySelector('.prob-value')).toBeNull() // the validated-probability style is not used
    expect(screen.getByText('Not validated')).toBeInTheDocument()
  })

  it('shows strategy odds as the served display string, and none as "No probability" with the reason', () => {
    const { rerender } = render(<OddsView odds={{ display: '<5%', validation: { status: 'not_validated', reasons: ['p6_m10_gate_failed'] } }} />)
    expect(screen.getByText('<5%')).toBeInTheDocument()
    expect(screen.getByText('the strategy model did not pass its accuracy check')).toHaveAttribute('data-reason', 'p6_m10_gate_failed')
    rerender(<OddsView odds={{ display: null, validation: { status: 'not_validated', reasons: ['playoff_model_unavailable'] } }} />)
    expect(screen.getByText('No probability')).toBeInTheDocument()
    expect(screen.getByText('the playoff model is not available')).toBeInTheDocument()
  })

  it('keeps validated_playoff_success and validated_playoff distinct (P7-D7)', () => {
    render(<>
      <ValidationBadge validation={{ status: 'validated_playoff_success' }} />
      <ValidationBadge validation={{ status: 'validated_playoff' }} />
    </>)
    const success = screen.getByText('Validated (playoff event outcomes)') // distinct plain names, served label kept
    const match = screen.getByText('Validated (single playoff match)')
    expect(success).toHaveAttribute('data-status', 'validated_playoff_success')
    expect(match).toHaveAttribute('data-status', 'validated_playoff')
    expect(success.getAttribute('title')).toMatch(/event outcomes passed/)
    expect(match.getAttribute('title')).toMatch(/single playoff-match probabilities passed/)
  })

  it('shows an unknown label as plain words rather than mapping it to a known one', () => {
    render(<ValidationBadge validation={{ status: 'some_new_label' }} />)
    expect(screen.getByText('some new label')).toHaveAttribute('title', expect.stringMatching(/shown as served/))
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
    const badge = screen.getByRole('button', { name: 'Validated (playoff event outcomes)' })
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
    expect(reasonText('m7_gate_failed')).toMatch(/qualification matches with full EPA/)
    expect(reasonText('some_new_reason')).toBe('some new reason') // unknown: underscores as spaces
  })

  it('shows the plain explanation only, keeping the raw served code on the element (supersedes D1.7, 2026-10-28)', () => {
    const { container } = render(<Absent reason="no_prior_concluded_event_epa" />)
    const plain = screen.getByText('no EPA: no qualifying earlier event with an EPA')
    expect(plain).toBeVisible()
    expect(container.textContent).not.toContain('no_prior_concluded_event_epa')
    expect(container.querySelector('[data-reason="no_prior_concluded_event_epa"]')).not.toBeNull()
    expect(container.querySelector('[title]')).toBeNull() // nothing depends on a tooltip
    expect(container.textContent).toContain('not available') // the absence itself is announced
  })

  it('shows a reason with no plain-word mapping as plain words, once', () => {
    const { container } = render(<Absent reason="some_new_reason" />)
    expect(screen.getByText('some new reason')).toBeVisible()
    expect(container.querySelector('code.reason-code')).toBeNull()
  })
})
})
