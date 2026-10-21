// LIVE end-to-end checks (2026-10-11): the real React app (jsdom) against a running local STRATAI API on the isolated
// stratai_test copy (scripts/local_test_env.py). Opt-in: runs only with STRATAI_LIVE_API set, for example
//   STRATAI_LIVE_API=1 VITE_API_BASE=http://127.0.0.1:8765 npx vitest run src/live
// Real 2023-2026 data, read-only, except the manual workflow test, which uploads a SYNTHETIC PDF under season 2099.
// It is not a real browser: layout, CSS and real file pickers still need manual browser checks.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { File as NodeFile } from 'node:buffer'
import { appendFileSync } from 'node:fs'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { Shell } from '../App'
import { setWriteToken } from '../api/client'
import { SessionProvider } from '../state/session'

const LIVE = Boolean(process.env.STRATAI_LIVE_API)
// Which seasons this API instance holds (2023 is served from its own copy, stratai_test_2023), and whether to run the
// 2027 readiness and manual-upload checks (only against the main stratai_test instance).
const SEASONS = (process.env.STRATAI_LIVE_SEASONS ?? '2026,2025,2024,2023').split(',').map(Number)
const HISTORY_ONLY = Boolean(process.env.STRATAI_LIVE_HISTORY_ONLY)
const LONG = 120_000

/** Records an outcome (to STRATAI_LIVE_OUT as JSON lines, when set). */
function record(entry: Record<string, unknown>) {
  console.info('LIVE', JSON.stringify(entry))
  if (process.env.STRATAI_LIVE_OUT) appendFileSync(process.env.STRATAI_LIVE_OUT, JSON.stringify({ at: new Date().toISOString(), ...entry }) + '\n')
}

function open(path: string, season: number) {
  window.localStorage.setItem('stratai.season', String(season))
  window.localStorage.setItem('stratai.actor', 'Live Test')
  return render(<SessionProvider><MemoryRouter initialEntries={[path]}><Shell /></MemoryRouter></SessionProvider>)
}

/** An explained "not available" or a rendered result; an unexplained error fails. */
async function explainedOrShown(tabpanel: HTMLElement, shown: () => HTMLElement | null) {
  await waitFor(() => {
    const ok = shown() ?? within(tabpanel).queryByTestId('unavailable')
    expect(ok).not.toBeNull()
  }, { timeout: LONG })
  expect(within(tabpanel).queryByRole('alert')).toBeNull()
  return within(tabpanel).queryByTestId('unavailable') ? 'unavailable' : 'shown'
}

describe.skipIf(!LIVE)('live: historical seasons through the real UI', () => {
  for (const season of SEASONS) {
    it(`${season}: events, an event's teams and matches, a win probability and the event analysis`, async () => {
      const outcome: Record<string, string> = {}
      const view = open('/explorer', season)
      const table = await screen.findByTestId('events-table', {}, { timeout: LONG })
      const rows = within(table).getAllByRole('row').slice(1)
      expect(rows.length).toBeGreaterThan(0)
      expect(within(table).getAllByRole('link')[0].getAttribute('href')).toContain(`/explorer/events/${season}`)
      outcome.events_listed = String(rows.length)
      outcome.event = String(within(table).getAllByRole('link')[0].getAttribute('href'))
      await userEvent.click(within(table).getAllByRole('link')[0])
      await waitFor(() => expect(screen.getByRole('tab', { name: 'Teams' })).toHaveAttribute('aria-selected', 'true'),
        { timeout: LONG })
      await waitFor(() => expect(screen.getAllByRole('link').some((a) => a.getAttribute('href')?.startsWith('/explorer/teams/'))).toBe(true),
        { timeout: LONG })
      expect(screen.queryByTestId('season-mismatch')).toBeNull()
      const teamHref = screen.getAllByRole('link').map((a) => a.getAttribute('href') ?? '').find((h) => h.startsWith('/explorer/teams/')) as string
      outcome.team = teamHref
      await userEvent.click(screen.getByRole('tab', { name: 'Matches' }))
      const matches = await screen.findByTestId('matches-table', {}, { timeout: LONG })
      expect(within(matches).getAllByRole('row').length).toBeGreaterThan(1)
      outcome.matches_listed = String(within(matches).getAllByRole('row').length - 1)
      await userEvent.click(within(matches).getAllByRole('button', { name: 'Win probability' })[0])
      await waitFor(() => expect(within(matches).queryAllByTestId(/^wp-/).length + within(matches).queryAllByTestId('unavailable').length)
        .toBeGreaterThan(0), { timeout: LONG })
      outcome.win_probability = within(matches).queryAllByTestId(/^wp-/).length ? 'shown' : 'unavailable'
      await userEvent.click(screen.getByRole('tab', { name: 'Event analysis' }))
      const main = view.container.querySelector('main') as HTMLElement
      outcome.analysis = await explainedOrShown(main, () => within(main).queryByText(/Ordering model:/))
      expect(within(main).getByTestId('pre-event')).toBeInTheDocument()  // a past event defaults to before it began
      outcome.analysis_as_of = (within(main).getByLabelText('As of') as HTMLInputElement).value
      await userEvent.click(screen.getByRole('tab', { name: 'Qualification forecast' }))
      outcome.forecast = await explainedOrShown(main, () => within(main).queryByRole('heading', { name: 'Teams' }))
      view.unmount()
      const teamView = open(teamHref, season)
      await screen.findByText(`${season} events`, {}, { timeout: LONG })
      await userEvent.click(screen.getAllByRole('button', { name: 'Strength' })[0])
      const teamMain = teamView.container.querySelector('main') as HTMLElement
      outcome.team_strength = await explainedOrShown(teamMain, () => within(teamMain).queryByTestId('strength-table'))
      teamView.unmount()
      record({ season, ...outcome })
    }, 5 * LONG)
  }

  it.skipIf(HISTORY_ONLY)('2027: readiness lists the Phase 6 tasks and no 2027 data exists', async () => {
    open('/readiness', 2027)
    const tasks = await screen.findByTestId('phase6-tasks', {}, { timeout: LONG })
    expect(within(tasks).getByText('R8')).toBeInTheDocument()
    expect(screen.getByTestId('no-season-data')).toBeInTheDocument()
    record({ season: 2027, readiness: 'phase6 tasks listed, no data' })
  }, LONG)

  it.skipIf(HISTORY_ONLY)('the manual workflow: upload a SYNTHETIC PDF, processing runs automatically, the extraction is reviewable', async () => {
    setWriteToken('local-test-token')
    open('/manuals', 2099)
    const input = await screen.findByLabelText('Manual PDF', {}, { timeout: LONG })
    const pdf = (await import('./syntheticManual')).syntheticManualPdf()
    // Node's own File: jsdom's File is not a body Node's fetch can send (a real browser sends its own File).
    const file = new NodeFile([pdf], 'synthetic-2099.pdf', { type: 'application/pdf' }) as unknown as File
    await userEvent.upload(input, file)
    await userEvent.type(screen.getByLabelText('Game name'), 'SYNTHETICA')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Upload and process' })).toBeEnabled(), { timeout: LONG })
    await userEvent.click(screen.getByRole('button', { name: 'Upload and process' }))
    expect(await screen.findByText(/Machine-extracted and unverified/, {}, { timeout: LONG })).toBeInTheDocument()
    expect(screen.getAllByText(/auto_seconds/).length).toBeGreaterThan(0)
    record({ season: 2099, manual_workflow: 'uploaded, processed, extraction shown' })
  }, 3 * LONG)
})
