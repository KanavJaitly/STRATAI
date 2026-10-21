import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BriefingResponse } from '../api/generated'
import { axeViolations, renderAt } from '../test/dashboard'
import { MATCH, REPORT } from '../test/dashboardFixtures'
import { mockApi } from '../test/mockApi'
import { fallbackText, modelWasCalled } from './briefingText'
import { ReportPage } from './pages/ReportPage'

// SYNTHETIC briefing responses (P9-M5); the shapes come from the generated OpenAPI types.
const PATTERN = '/report/:matchKey'
afterEach(() => vi.unstubAllGlobals())

const FACT = { id: 'match', kind: 'context' as const, section: 'match', statement: `Match ${MATCH}.`, source: 'match_key' }
const DETERMINISTIC: BriefingResponse = {
  match_key: MATCH, event_key: REPORT.event_key, as_of: REPORT.as_of, mode: 'deterministic', fallback_reason: 'disabled',
  model: null, usage: null, facts: [FACT],
  sections: [{ heading: 'Match', sentences: [{ text: `Match ${MATCH}.`, fact_ids: ['match'] }] },
    { heading: 'Not produced by any engine', sentences: [{ text: 'Key risks: not produced by any engine.', fact_ids: ['not_produced.key_risks'] }] }],
  disclaimer: 'A readable summary of the pre-match report.',
}
const LLM: BriefingResponse = {
  ...DETERMINISTIC, mode: 'llm', fallback_reason: null, model: 'claude-opus-5-5',
  usage: { input_tokens: 4000, output_tokens: 900, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, attempts: null },
  sections: [{ heading: 'Match', sentences: [{ text: `Match details: Match ${MATCH}. <img src=x onerror=alert(1)>`, fact_ids: ['match'] }] }],
}

async function openBriefing(response: BriefingResponse, search = '') {
  const api = mockApi({ [`GET /matches/${MATCH}/pre-match-report`]: REPORT, [`GET /matches/${MATCH}/briefing`]: response })
  const view = renderAt(PATTERN, `/report/${MATCH}${search}`, <ReportPage />)
  const button = await screen.findByRole('button', { name: 'Show the readable briefing' })
  return { ...view, api, button }
}

describe('BriefingPanel (P9-M5)', () => {
  it('is not fetched until asked for, then is requested with the report\'s own as_of parameter', async () => {
    const { api, button } = await openBriefing(DETERMINISTIC)
    expect(api.calls.filter((c) => c.path.endsWith('/briefing'))).toHaveLength(0)
    await userEvent.click(button)
    const panel = (await screen.findByRole('heading', { name: 'Readable briefing' })).closest('section') as HTMLElement
    await within(panel).findByText(`Match ${MATCH}.`)
    const [call] = api.calls.filter((c) => c.path.endsWith('/briefing'))
    const [report] = api.calls.filter((c) => c.path.endsWith('/pre-match-report'))
    expect(call.query.get('as_of')).toBe(report.query.get('as_of')) // both absent: the moment is chosen the same way
    expect(within(panel).queryByText(/This briefing was taken at/)).toBeNull() // same moment as the report
  })

  it('passes an explicit as_of through, and says so when the briefing\'s moment differs from the report\'s', async () => {
    const later = { ...DETERMINISTIC, as_of: '2099-12-31T00:00:00Z' }
    const { api, button } = await openBriefing(later, '?as_of=2026-03-01T09:00:00Z')
    await userEvent.click(button)
    const panel = (await screen.findByText('fixed layout')).closest('section') as HTMLElement
    const [call] = api.calls.filter((c) => c.path.endsWith('/briefing'))
    expect(call.query.get('as_of')).toBe('2026-03-01T09:00:00Z')
    expect(within(panel).getByText(/This briefing was taken at/)).toBeInTheDocument()
  })

  it('says a model was called when its arrangement was rejected', async () => {
    const { button } = await openBriefing({ ...DETERMINISTIC, fallback_reason: 'validation_failed:lead_not_allowed' })
    await userEvent.click(button)
    const panel = (await screen.findByText('fixed layout')).closest('section') as HTMLElement
    expect(within(panel).getByText(/A language model was called, but its arrangement was not used/)).toBeInTheDocument()
    expect(within(panel).queryByText(/No language model was used/)).toBeNull()
  })

  it('labels the fixed layout with the reason no language model was used', async () => {
    const { button, container } = await openBriefing(DETERMINISTIC)
    await userEvent.click(button)
    const panel = (await screen.findByText('fixed layout')).closest('section') as HTMLElement
    expect(within(panel).getByText(/No language model was used/)).toBeInTheDocument()
    expect(within(panel).getByText(/the language model is switched off/)).toBeInTheDocument()
    expect(within(panel).getByText('(disabled)')).toBeInTheDocument()
    expect(within(panel).getByRole('heading', { name: 'Not produced by any engine' })).toBeInTheDocument()
    expect(await axeViolations(container)).toEqual([])
  })

  it('labels an LLM arrangement with its model and renders its text as text, never as HTML', async () => {
    const { button, container } = await openBriefing(LLM)
    await userEvent.click(button)
    const panel = (await screen.findByText('arranged by a language model')).closest('section') as HTMLElement
    expect(within(panel).getByText(/claude-opus-5-5 chose the grouping, the order and the topic labels/)).toBeInTheDocument()
    expect(within(panel).getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument()
    expect(container.querySelector('.briefing img')).toBeNull()
    expect(await axeViolations(container)).toEqual([])
  })

  it('shows a refusal of the briefing like any other refusal', async () => {
    mockApi({ [`GET /matches/${MATCH}/pre-match-report`]: REPORT, [`GET /matches/${MATCH}/briefing`]: {
      status: 404, body: { error: { code: 'match_not_found', message: 'no such match', status: 404 } } } })
    renderAt(PATTERN, `/report/${MATCH}`, <ReportPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Show the readable briefing' }))
    const panel = screen.getByRole('heading', { name: 'Readable briefing' }).closest('section') as HTMLElement
    expect((await within(panel).findAllByText(/no such match/)).length).toBeGreaterThan(0)
    expect(within(panel).queryByText('fixed layout')).toBeNull()
  })
})

describe('fallbackText', () => {
  it('explains every served reason, and keeps unknown ones verbatim', () => {
    expect(fallbackText('egress_not_approved')).toMatch(/not approved/)
    expect(fallbackText('api_error:RateLimitError')).toBe('the language-model call failed (RateLimitError)')
    expect(fallbackText('validation_failed:lead_banned_word')).toMatch(/failed a check \(lead_banned_word\)/)
    expect(fallbackText('constructor')).toBe('constructor')
    expect(fallbackText(null)).toBe('')
  })

  it('knows which reasons mean a model was called', () => {
    for (const r of ['disabled', 'egress_not_approved', 'no_credential', 'sdk_unavailable']) expect(modelWasCalled(r)).toBe(false)
    for (const r of ['refusal', 'truncated', 'no_text', 'invalid_json', 'api_error:X', 'validation_failed:schema']) {
      expect(modelWasCalled(r)).toBe(true)
    }
  })
})
