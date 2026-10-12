// The browser acceptance checklist (docs/browser_acceptance_checklist.md), automated where it is deterministic and
// safe (2026-10-12). Real Chrome (channel 'chrome') against the local test environment on the isolated copies.
//
// Guarantees, by construction:
// - identity: "Checklist Automation", never the tester's name;
// - uploads: byte-distinct copies of the checklist PDFs, which never dedupe onto the tester's manuals;
// - UI B (stratai_test_2023) never receives the write token;
// - never clicked: Approve, "Return with note", or "Confirm this is the 2027 manual" (human acts).
//
// Each step records its status (automated PASS / automated FAIL / manual verification required) and its evidence in
// <EVIDENCE>/steps.jsonl. A step with a human judgement records "manual verification required" even when its
// automated part passes.
import { type Browser, type Page, expect, test } from '@playwright/test'
import { appendFileSync } from 'node:fs'
import path from 'node:path'

import {
  ACTOR, API_A, EVIDENCE, FILES_DIR, STEPS_FILE, TOKEN, UI_A, UI_B, readState, startApi, stop, writeState,
} from './servers'

type Ui = typeof UI_A
type Status = 'automated PASS' | 'automated FAIL' | 'manual verification required'
const LONG = 240_000

function record(id: string, status: Status, evidence: string[]): void {
  appendFileSync(STEPS_FILE, JSON.stringify({ id, status, evidence, at: new Date().toISOString() }) + '\n')
}

/** One checklist step. `partial`: an automated part plus a human judgement, recorded as manual verification. */
function step(id: string, title: string, kind: 'automated' | 'partial',
  body: (args: { page: Page; browser: Browser }, ev: string[]) => Promise<void>) {
  test(`${id} ${title}`, async ({ page, browser }) => {
    const ev: string[] = []
    try {
      await body({ page, browser }, ev)
      record(id, kind === 'automated' ? 'automated PASS' : 'manual verification required',
        kind === 'automated' ? ev : ['automated part: PASS', ...ev])
    } catch (error) {
      const shot = path.join(EVIDENCE, `${id}_FAIL.png`)
      await page.screenshot({ path: shot, fullPage: true }).catch(() => undefined)
      record(id, 'automated FAIL', [...ev, `error: ${String(error).slice(0, 800)}`, `screenshot: ${shot}`])
      throw error
    }
  })
}

async function snap(page: Page, ev: string[], name: string): Promise<void> {
  const file = path.join(EVIDENCE, `${name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  ev.push(`screenshot: ${file}`)
}

/** Open a route as the automation: its own name on UI A, never a token on UI B. */
async function open(page: Page, ui: Ui, route: string, season: number, token = false): Promise<void> {
  await page.goto(ui.url + '/')
  await page.evaluate(([s, a]) => {
    window.localStorage.setItem('stratai.season', s)
    window.localStorage.setItem('stratai.actor', a)
  }, [String(season), ui === UI_A ? ACTOR : ''])
  await page.goto(ui.url + route)
  if (ui === UI_B) {
    if (token) throw new Error('UI B is read-only: the token is never entered there')
    await expect(page.getByTestId('access')).toContainText('read-only')
  } else if (token) {
    await page.getByLabel('Write token').fill(TOKEN)
    await expect(page.getByTestId('access')).toHaveText('write token accepted')
  }
}

const processingBadge = (page: Page) => page.locator('dd', { hasText: 'manual-proc-v1' }).locator('.badge')

async function upload(page: Page, file: string): Promise<number> {
  await page.getByLabel('Manual PDF').setInputFiles(path.join(FILES_DIR, file))
  await page.getByLabel('Game name').fill('SYNTHETICA')
  await page.getByRole('button', { name: 'Upload and process' }).click()
  const outcome = page.locator('.notice-ok', { hasText: /manual #\d+/ })
  await expect(outcome).toBeVisible({ timeout: 60_000 })
  const id = Number(/#(\d+)/.exec(await outcome.innerText())![1])
  await expect(page.getByRole('heading', { name: `Processing — manual #${id}` })).toBeVisible()
  return id
}

// --- 0. Setup -----------------------------------------------------------------------------------------------------

step('0.1', 'each API prints its database first', 'automated', async (_, ev) => {
  const { startup } = readState()
  ev.push(`API A: ${startup.apiA}`, `API B: ${startup.apiB}`,
    'note: the automation runs its own servers on :8775/:8776 (the checklist names :8765/:8766), same databases')
  expect(startup.apiA).toBe('STRATAI local test API: database stratai_test (isolated copy), http://127.0.0.1:8775')
  expect(startup.apiB).toBe('STRATAI local test API: database stratai_test_2023 (isolated copy), http://127.0.0.1:8776')
})

async function seasonEvents(page: Page, ui: Ui): Promise<Record<string, number>> {
  await page.goto(`${ui.url}/api/seasons`)
  const body = JSON.parse(await page.locator('body').innerText()) as { season: number; coverage: { events: number } }[]
  return Object.fromEntries(body.map((s) => [String(s.season), s.coverage.events]))
}

step('0.2', 'UI A /api/seasons', 'automated', async ({ page }, ev) => {
  const events = await seasonEvents(page, UI_A)
  ev.push(`events per season: ${JSON.stringify(events)}`)
  expect(events).toEqual({ 2023: 0, 2024: 190, 2025: 203, 2026: 215, 2027: 0 })
})

step('0.3', 'UI B /api/seasons', 'automated', async ({ page }, ev) => {
  const events = await seasonEvents(page, UI_B)
  ev.push(`events per season: ${JSON.stringify(events)}`)
  expect(events).toEqual({ 2023: 185, 2024: 190, 2025: 203, 2026: 215, 2027: 0 })
})

step('0.4', 'the synthetic PDFs are generated', 'automated', async (_, ev) => {
  const names = readState().filesOutput.map((line) => path.basename(line))
  ev.push(`command output: ${names.join(', ')}`)
  expect(names.sort()).toEqual(['no_year_2027.pdf', 'not_a_pdf.pdf', 'partial_2027.pdf', 'scanned.pdf',
    'valid_2027.pdf', 'wrong_season_2026.pdf'])
})

step('0.5', 'name and token change the access badge', 'automated', async ({ page }, ev) => {
  await page.goto(UI_A.url + '/manuals')
  await expect(page.getByTestId('access')).toHaveText('read-only (no valid token)')
  await page.getByLabel('Your name').fill(ACTOR)
  await page.getByLabel('Write token').fill(TOKEN)
  await expect(page.getByTestId('access')).toHaveText('write token accepted')
  ev.push(`name "${ACTOR}" (the automation's own identity); badge: read-only (no valid token) -> write token accepted`)
})

// --- 1. /manuals (2027) -----------------------------------------------------------------------------------------

step('1.10', 'a manual without a readable season needs resolution', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/manuals', 2027, true)
  const id = await upload(page, 'auto_no_year_2027.pdf')
  await expect(processingBadge(page)).toHaveText('needs resolution', { timeout: 60_000 })
  await expect(page.getByText('The manual\'s season could not be read from its title pages.')).toBeVisible()
  const confirm = page.getByRole('button', { name: 'Confirm this is the 2027 manual' })
  await expect(confirm).toBeDisabled()
  await page.getByLabel('Resolution note').fill('typed by automation; never confirmed')
  await expect(confirm).toBeEnabled()
  await page.getByLabel('Resolution note').fill('')
  await expect(confirm).toBeDisabled()
  ev.push(`manual #${id} (auto_no_year_2027.pdf): status "needs resolution"; Confirm disabled with no note, enabled with `
    + 'a note, disabled again when cleared; never clicked (1.11 is the tester\'s attestation)')
  await snap(page, ev, '1.10')
})

step('1.12', 'a scanned PDF fails unreadable_text', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/manuals', 2027, true)
  const id = await upload(page, 'auto_scanned.pdf')
  await expect(processingBadge(page)).toHaveText('failed', { timeout: 60_000 })
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('unreadable_text: only 0 of 3 pages have extractable text')  // without expanding
  await page.getByText(/^Processing attempts \(\d+\)$/).click()
  await expect(page.locator('details.raw li', { hasText: 'unreadable_text' })).toBeVisible()
  await expect(page.getByText(/^Processing attempts \(1\)$/)).toBeVisible()
  ev.push(`manual #${id} (auto_scanned.pdf): status "failed"; shown without expanding: `
    + `"${(await alert.innerText()).replace(/\s+/g, ' ')}"; the history (1 attempt) lists the same reason`)
  await snap(page, ev, '1.12')
})

step('1.13', 'without a token the upload form is replaced', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/manuals', 2027, true)
  await expect(page.getByLabel('Manual PDF')).toBeVisible()
  await page.getByLabel('Write token').fill('')
  await expect(page.getByText('Enter a valid write token (top of the page) to make changes.').first()).toBeVisible()
  await expect(page.getByLabel('Manual PDF')).toHaveCount(0)
  const rows = await page.getByRole('heading', { name: 'Uploaded versions' }).locator('..').locator('..')
    .locator('tbody tr').count()
  expect(rows).toBeGreaterThan(0)
  ev.push(`token cleared: the form is replaced by "Enter a valid write token…"; ${rows} uploaded versions still listed`)
})

test('D1 re-check in the browser (not a checklist step): a retry is attempt #2', async ({ page }) => {
  const ev: string[] = []
  let status: Status = 'automated PASS'
  try {
    await open(page, UI_A, '/manuals', 2027, true)
    const id = await upload(page, 'auto_wrong_season_2026.pdf')
    await expect(processingBadge(page)).toHaveText('failed', { timeout: 60_000 })
    await page.getByRole('button', { name: 'Retry processing' }).click()
    await expect(page.getByText(/^Processing attempts \(2\)$/)).toBeVisible({ timeout: 60_000 })
    await expect(processingBadge(page)).toHaveText('failed', { timeout: 60_000 })  // the retry has finished
    await page.getByText(/^Processing attempts \(2\)$/).click()
    const items = page.locator('details.raw li')
    await expect.poll(async () => (await items.allInnerTexts()).every((e) => e.includes('failed')
      && e.includes('wrong_season')), { timeout: 30_000 }).toBe(true)
    const entries = await items.allInnerTexts()
    expect(entries.map((e) => e.split(' ')[0])).toEqual(['#1', '#2'])
    ev.push(`manual #${id} (auto_wrong_season_2026.pdf), build with the D1 fix: ${entries.join(' | ')}`)
    await snap(page, ev, 'D1-browser')
  } catch (error) {
    status = 'automated FAIL'
    ev.push(`error: ${String(error).slice(0, 800)}`)
    throw error
  } finally {
    record('D1-browser', status, ev)
  }
})

// --- 2. /rulesets -----------------------------------------------------------------------------------------------

for (const season of [2026, 2025, 2024]) {
  step(`2.1-${season}`, 'the season shows its own approved ruleset', 'automated', async ({ page }, ev) => {
    await open(page, UI_A, '/rulesets', season)
    const approvedLine = page.getByText(/^Approved: version \d+ by /)
    await expect(approvedLine).toBeVisible()
    const row = page.locator('tbody tr', { has: page.locator('.badge', { hasText: /^approved$/ }) })
    await row.getByRole('button', { name: 'Open' }).click()
    const json = JSON.parse(await page.locator('details.raw', { hasText: 'Stored ruleset JSON' }).locator('pre')
      .textContent() as string) as { season: number }
    expect(json.season).toBe(season)
    ev.push(`${(await approvedLine.innerText()).replace(/\s+/g, ' ')}; the stored JSON's season = ${json.season}`)
  })
}

test('2.0 setup (not a checklist step): a complete synthetic 2027 manual, processed', async ({ page }) => {
  // The worksheet uses the most recent successfully processed manual; this run's own complete synthetic copy.
  await open(page, UI_A, '/manuals', 2027, true)
  const id = await upload(page, 'auto_valid_2027.pdf')
  await expect(processingBadge(page)).toHaveText('succeeded', { timeout: 60_000 })
  record('2.0-setup', 'automated PASS', [`manual #${id} (auto_valid_2027.pdf, uploaded by "${ACTOR}") succeeded`])
})

/** The worksheet's own section (the selected version's section has a button with the same name). */
const worksheetSection = (page: Page) => page.locator('section', { has: page.getByRole('heading', { name: /^Season ruleset — / }) })

step('2.2', 'the 2027 worksheet carries UNVERIFIED markers and empties event lists', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/rulesets', 2027, true)
  await page.getByRole('button', { name: 'Start from a worksheet' }).click()
  await expect(page.getByText(/built from the approved 2026 ruleset's structure/)).toBeVisible({ timeout: 60_000 })
  const manual = page.getByText(/The uploaded manual #\d+ supplies the suggestions below/)
  await expect(manual).toBeVisible()
  const suggestions = await page.locator('td div.small', { hasText: /^p\. \d+:/ }).count()
  expect(suggestions).toBeGreaterThan(0)
  const manualId = (await manual.innerText()).match(/manual #\d+/)?.[0]  // read before the panel closes
  await worksheetSection(page).getByRole('button', { name: 'Edit as a new draft' }).click()
  const text = await page.getByLabel('Ruleset JSON').inputValue()
  const proposal = JSON.parse(text) as Record<string, unknown>
  const markers = (text.match(/UNVERIFIED \(carried from 2026/g) ?? []).length
  expect(markers).toBeGreaterThan(0)
  expect(proposal.selection_variants).toEqual([])
  expect(proposal.event_exclusions).toEqual([])
  ev.push(`template from 2026; ${manualId} supplies ${suggestions} page-cited `
    + `suggestions; ${markers} "UNVERIFIED (carried from 2026)" markers; selection_variants and event_exclusions empty`)
})

let draftLabel = ''

step('2.3', 'saving the worksheet as a synthetic draft (marker warning shown)', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/rulesets', 2027, true)
  await page.getByRole('button', { name: 'Start from a worksheet' }).click()
  await worksheetSection(page).getByRole('button', { name: 'Edit as a new draft' }).click()
  const warning = page.locator('.notice-warn', { hasText: 'still carry' })
  await expect(warning).toBeVisible()
  const warningText = (await warning.innerText()).replace(/\s+/g, ' ')
  await page.getByRole('button', { name: 'Save as draft' }).click()
  await expect(page.getByText('Draft saved as a new version.')).toBeVisible({ timeout: 60_000 })
  const row = page.locator('tbody tr', { hasText: ACTOR }).filter({ has: page.locator('.badge', { hasText: /^draft$/ }) })
    .last()
  draftLabel = (await row.locator('td').first().innerText()).trim()
  ev.push(`warning: "${warningText.slice(0, 70)}…"; saved ${draftLabel} as a draft authored by "${ACTOR}" `
    + '(synthetic automation data, authorized for 2.3-2.6)')
})

async function openDraft(page: Page): Promise<void> {
  if (!draftLabel) throw new Error('blocked: step 2.3 did not create the draft')
  await open(page, UI_A, '/rulesets', 2027, true)
  await page.locator('tbody tr', { hasText: draftLabel }).getByRole('button', { name: 'Open' }).click()
}

step('2.4', 'submitting shows the review form and the marker refusal', 'automated', async ({ page }, ev) => {
  await openDraft(page)
  await page.getByRole('button', { name: 'Submit for review' }).click()
  await expect(page.getByText('Submitted for review.')).toBeVisible({ timeout: 60_000 })
  const form = page.getByTestId('review-form')
  await expect(form).toBeVisible()
  await expect(form.getByLabel('Reviewer')).toHaveValue(ACTOR)
  await expect(form.getByLabel('Reviewer')).toHaveAttribute('readonly', '')
  await expect(form.getByLabel('Qualification')).toBeVisible()
  for (let i = 1; i <= 14; i += 1) await expect(form.getByLabel(`R${i}`, { exact: true })).toBeVisible()
  await expect(form.getByLabel('Verified sha256')).toBeVisible()
  const refusal = form.locator('.notice-error', { hasText: /still has \d+ UNVERIFIED marker/ })
  await expect(refusal).toBeVisible()
  ev.push(`${draftLabel} submitted; reviewer read-only "${ACTOR}"; qualification field; R1-R14; sha256 field; `
    + `"${(await refusal.innerText()).slice(0, 80)}…"`)
})

async function reviewForm(page: Page) {
  await openDraft(page)
  const form = page.getByTestId('review-form')
  await expect(form).toBeVisible()
  return form
}

step('2.5', 'a wrong sha256 keeps Approve disabled', 'automated', async ({ page }, ev) => {
  const form = await reviewForm(page)
  for (let i = 1; i <= 14; i += 1) await form.getByLabel(`R${i}`, { exact: true }).check()
  await form.getByLabel('Qualification').fill('SYNTHETIC automation input; not a person and not a qualified reviewer')
  await form.getByLabel('Verified sha256').fill('0'.repeat(64))
  await expect(form.getByText('Does not match the stored sha256.')).toBeVisible()
  await expect(form.getByRole('button', { name: 'Approve' })).toBeDisabled()
  ev.push('R1-R14 ticked, a synthetic qualification typed (never submitted), sha256 0x64: "Does not match the stored '
    + 'sha256."; Approve disabled; Approve never clicked')
})

step('2.6', 'the correct sha256 still leaves Approve disabled (markers)', 'automated', async ({ page }, ev) => {
  const form = await reviewForm(page)
  for (let i = 1; i <= 14; i += 1) await form.getByLabel(`R${i}`, { exact: true }).check()
  await form.getByLabel('Qualification').fill('SYNTHETIC automation input; not a person and not a qualified reviewer')
  const sha = (await page.getByTestId('stored-sha').innerText()).trim()
  await form.getByLabel('Verified sha256').fill(sha)
  await expect(form.getByText('Matches the stored sha256.')).toBeVisible()
  await expect(form.getByRole('button', { name: 'Approve' })).toBeDisabled()
  ev.push(`stored sha256 ${sha.slice(0, 12)}… entered: "Matches the stored sha256."; Approve still disabled (markers); `
    + 'never clicked')
})

step('2.7', '"Return with note" needs a note (the Return itself is the tester\'s)', 'partial', async ({ page }, ev) => {
  const form = await reviewForm(page)
  await expect(form.getByLabel('Review note')).toHaveValue('')
  await expect(form.getByRole('button', { name: 'Return with note' })).toBeDisabled()
  ev.push(`${draftLabel}: "Return with note" disabled with an empty note. Not clicked: the Return action is left to the `
    + 'tester')
})

// --- 3. /readiness ----------------------------------------------------------------------------------------------

step('3.1', '2027: no data, manual present, ruleset not approved', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/readiness', 2027)
  await expect(page.getByText('No 2027 data is synced. The 2027 season has not been played')).toBeVisible({ timeout: 60_000 })
  const inputs = page.locator('section', { has: page.getByRole('heading', { name: 'Human inputs' }) }).first()
  const manualLine = (await inputs.locator('dd').nth(0).innerText()).replace(/\s+/g, ' ')
  const rulesetLine = (await inputs.locator('dd').nth(2).innerText()).replace(/\s+/g, ' ')
  expect(manualLine).toMatch(/#\d+/)
  expect(rulesetLine).not.toMatch(/^approved v/)
  ev.push(`game manual: "${manualLine}"; season ruleset: "${rulesetLine}"`)
})

step('3.2', '2027: the Phase 6 tasks', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/readiness', 2027)
  const rows = page.getByTestId('phase6-tasks').locator('tbody tr')
  await expect(rows).toHaveCount(14, { timeout: 60_000 })
  const tasks: Record<string, string> = {}
  for (const row of await rows.all()) {
    const id = (await row.locator('td').first().innerText()).split('\n')[0].trim()
    tasks[id] = (await row.locator('.badge').innerText()).trim()
  }
  ev.push(`statuses: ${JSON.stringify(tasks)}`)
  expect(Object.keys(tasks)).toEqual(['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9', 'R10', 'M1', 'M2', 'M3', 'M4'])
  expect(tasks.R8).toBe('done')
  expect(tasks.R1).toBe('your action')
  for (const [id, label] of Object.entries(tasks)) {
    if (id !== 'R8' && id !== 'R1') expect(['waiting for 2027 data', 'blocked']).toContain(label)
  }
})

step('3.3', 'done-means, no run buttons, the automation boundary', 'partial', async ({ page }, ev) => {
  await open(page, UI_A, '/readiness', 2027)
  const dm = page.locator('li', { hasText: /^P6-DM/ })
  await expect(dm.first()).toBeVisible({ timeout: 60_000 })
  const lines = (await dm.allInnerTexts()).map((t) => t.replace(/\s+/g, ' '))
  expect(lines.find((l) => l.startsWith('P6-DM1'))).toMatch(/not met$/)
  expect(lines.find((l) => l.startsWith('P6-DM2'))).toMatch(/: met$/)
  const buttons = await page.locator('main button').count()
  const never = await page.locator('section', { has: page.getByRole('heading', { name: /never does/ }) })
    .locator('h4:has-text("Never automatic") + ul li').allInnerTexts()
  expect(never.join(' | ')).toMatch(/ruleset approval/)
  expect(never.join(' | ')).toMatch(/serving/)
  expect(buttons).toBe(0)
  ev.push(`done-means: ${lines.join(' | ')}`, `buttons in the page body: ${buttons}`, `never automatic: ${never.join(' | ')}`,
    'judgement left to the tester: whether any wording implies acceptance or authorization')
  await snap(page, ev, '3.3')
})

step('3.4', '2026: no Phase 6 task list', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/readiness', 2026)
  await expect(page.getByRole('heading', { name: 'Features' })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('phase6-tasks')).toHaveCount(0)
  ev.push('2026 readiness: coverage and features shown; no Phase 6 task table')
})

// --- 4. /explorer and season switching --------------------------------------------------------------------------

const SEASONS = {
  2026: { ui: UI_A, event: '2026tuis', team: 9483, qm1: 'shown' },
  2025: { ui: UI_A, event: '2025isde1', team: 1690, qm1: 'shown' },
  2024: { ui: UI_A, event: '2024isde1', team: 1690, qm1: 'unavailable' },
  2023: { ui: UI_B, event: '2023isde1', team: 1574, qm1: 'unavailable' },
} as const

async function writeSnapshot(page: Page): Promise<string> {
  const out: Record<string, unknown> = {}
  for (const ui of [UI_A, UI_B]) {
    for (const season of [2023, 2024, 2025, 2026, 2027]) {
      await page.goto(`${ui.url}/api/human-inputs/game-manuals?season=${season}`)
      const manuals = JSON.parse(await page.locator('body').innerText()) as { id: number }[]
      const attempts = []
      for (const m of manuals) {
        await page.goto(`${ui.url}/api/human-inputs/game-manuals/${m.id}/processing`)
        attempts.push(`${m.id}:${(JSON.parse(await page.locator('body').innerText()) as { attempts: unknown[] }).attempts.length}`)
      }
      out[`${ui.port}/${season}`] = attempts
    }
    await page.goto(`${ui.url}/api/human-inputs/rulesets?season=2027`)
    out[`${ui.port}/rulesets2027`] = (JSON.parse(await page.locator('body').innerText()) as unknown[]).length
  }
  return JSON.stringify(out)
}

let before = ''
test('4.0 snapshot before browsing (not a checklist step)', async ({ page }) => { before = await writeSnapshot(page) })

for (const [seasonText, s] of Object.entries(SEASONS)) {
  const season = Number(seasonText)
  const eventUrl = `/explorer/events/${s.event}`

  step(`4.1-${season}`, 'explorer: coverage, features, events', 'automated', async ({ page }, ev) => {
    await open(page, s.ui, '/explorer', season)
    await expect(page.getByTestId('coverage')).toBeVisible({ timeout: 60_000 })
    const features = (await page.getByTestId('feature-availability').innerText()).replace(/\s+/g, ' ')
    const table = page.getByTestId('events-table')
    await expect(table).toBeVisible({ timeout: 60_000 })
    const hrefs = await table.locator('a').evaluateAll((as) => as.map((a) => a.getAttribute('href') ?? ''))
    expect(hrefs.length).toBeGreaterThan(0)
    expect(hrefs.every((h) => h.startsWith(`/explorer/events/${season}`))).toBe(true)
    ev.push(`${hrefs.length} event links, all ${season}; features: ${features.slice(0, 400)}`)
  })

  step(`4.2-${season}`, 'event: teams, matches, level filter', 'automated', async ({ page }, ev) => {
    await open(page, s.ui, eventUrl, season)
    await expect(page.getByRole('tab', { name: 'Teams' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('a[href^="/explorer/teams/"]').first()).toBeVisible({ timeout: 60_000 })
    const teams = await page.locator('a[href^="/explorer/teams/"]').count()
    await expect(page.getByTestId('season-mismatch')).toHaveCount(0)
    await page.getByRole('tab', { name: 'Matches' }).click()
    const rows = page.getByTestId('matches-table').locator('tbody tr')
    const all = await rows.count()
    await page.getByLabel('Match level').selectOption('playoff')
    const playoffs = await page.getByTestId('matches-table').locator('tbody tr').count()
    await page.getByLabel('Match level').selectOption('qualification')
    const quals = await page.getByTestId('matches-table').locator('tbody tr').count()
    expect(all).toBeGreaterThan(0)
    expect(quals + playoffs).toBe(all)
    ev.push(`${teams} team links; matches all/qualification/playoff = ${all}/${quals}/${playoffs}; no mismatch banner`)
  })

  async function probability(page: Page, match: string): Promise<string> {
    await open(page, s.ui, eventUrl, season)
    await page.getByRole('tab', { name: 'Matches' }).click()
    const row = page.getByTestId('matches-table').locator('tbody tr', { has: page.locator('code', { hasText: new RegExp(`^${match}$`) }) })
    await row.getByRole('button', { name: 'Win probability' }).click()
    const result = row.locator(`[data-testid="wp-${s.event}_${match}"], [data-testid="unavailable"]`)
    await expect(result).toBeVisible({ timeout: LONG })
    return (await result.innerText()).replace(/\s+/g, ' ')
  }

  step(`4.3-${season}`, 'qm1 win probability', 'automated', async ({ page }, ev) => {
    const text = await probability(page, 'qm1')
    ev.push(`qm1: ${text}`)
    if (s.qm1 === 'shown') {
      expect(text).toMatch(/^red|red /)
      expect(text).not.toMatch(/Not available/)
    } else {
      expect(text).toMatch(/Not available.*prior evidence/)
    }
  })

  if (season === 2024 || season === 2023) {
    step(`4.4-${season}`, 'qm20 win probability', 'automated', async ({ page }, ev) => {
      const text = await probability(page, 'qm20')
      ev.push(`qm20: ${text}`)
      if (season === 2024) expect(text).not.toMatch(/Not available/)
      else expect(text).toMatch(/Not available.*score-breakdown adapter/)
    })
  }

  step(`4.5-${season}`, 'event analysis defaults to pre-event', 'automated', async ({ page }, ev) => {
    await open(page, s.ui, eventUrl, season)
    await page.getByRole('tab', { name: 'Event analysis' }).click()
    const asOf = await page.getByLabel('As of').inputValue()
    expect(asOf).toMatch(new RegExp(`^${season}-\\d{2}-\\d{2}T00:00:00\\+14:00$`))
    await expect(page.getByTestId('pre-event')).toBeVisible()
    const started = Date.now()
    const result = page.locator('main').getByText(/^Ordering model:/).or(page.locator('main').getByTestId('unavailable'))
    await expect(result.first()).toBeVisible({ timeout: LONG })
    ev.push(`as of ${asOf}; "${(await result.first().innerText()).replace(/\s+/g, ' ').slice(0, 160)}" after `
      + `${Math.round((Date.now() - started) / 1000)} s`)
    await snap(page, ev, `4.5-${season}`)
  })

  step(`4.6-${season}`, 'clearing "As of" warns it is not a historical test', 'automated', async ({ page }, ev) => {
    await open(page, s.ui, eventUrl, season)
    await page.getByRole('tab', { name: 'Event analysis' }).click()
    await page.getByLabel('As of').fill('')
    await page.getByRole('button', { name: 'Apply' }).click()
    await expect(page.getByTestId('as-of-now')).toContainText('not a historical test')
    ev.push(`"${(await page.getByTestId('as-of-now').innerText()).replace(/\s+/g, ' ')}"`)
  })

  step(`4.7-${season}`, 'qualification forecast (pre-event, loading visible)', 'automated', async ({ page }, ev) => {
    await open(page, s.ui, eventUrl, season)
    await page.getByRole('tab', { name: 'Qualification forecast' }).click()
    const started = Date.now()
    await expect(page.getByTestId('pre-event')).toBeVisible()
    const loadingSeen = await page.getByText('Loading…').first().isVisible()
    const result = page.locator('main').getByRole('heading', { name: 'Teams' })
      .or(page.locator('main').getByTestId('unavailable'))
    await expect(result.first()).toBeVisible({ timeout: LONG })
    ev.push(`loading state visible at start: ${loadingSeen}; result "${(await result.first().innerText()).slice(0, 120)}" `
      + `after ${Math.round((Date.now() - started) / 1000)} s`)
    expect(loadingSeen).toBe(true)
  })

  step(`4.8-${season}`, 'ranking prediction says it is always as of now', 'automated', async ({ page }, ev) => {
    await open(page, s.ui, eventUrl, season)
    await page.getByRole('tab', { name: 'Ranking prediction' }).click()
    await expect(page.getByTestId('ranking-now')).toContainText('always as of now')
    const result = page.locator('main table').or(page.locator('main').getByTestId('unavailable'))
    await expect(result.first()).toBeVisible({ timeout: LONG })
    ev.push(`notice shown; result: ${(await result.first().innerText()).replace(/\s+/g, ' ').slice(0, 120)}`)
  })

  step(`4.9-${season}`, 'team strength (pre-event) and metrics', 'automated', async ({ page }, ev) => {
    await open(page, s.ui, `/explorer/teams/${s.team}`, season)
    await page.getByRole('button', { name: 'Strength' }).first().click()
    const strength = page.getByTestId('strength-table').or(page.getByTestId('unavailable'))
    await expect(strength.first()).toBeVisible({ timeout: LONG })
    await expect(page.getByText(/As of before the event began/)).toBeVisible()
    await page.getByRole('button', { name: 'Metrics' }).first().click()
    const metrics = page.getByText(/have not been computed/).or(page.getByText('Team metrics (Phase 3)'))
    await expect(metrics.first()).toBeVisible({ timeout: LONG })
    ev.push(`strength: ${(await strength.first().innerText()).replace(/\s+/g, ' ').slice(0, 160)}`,
      `metrics: ${(await metrics.first().innerText()).replace(/\s+/g, ' ').slice(0, 120)}`)
  })
}

step('4.10', 'switching season on an event page shows the mismatch banner', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/explorer/events/2026tuis', 2026)
  await expect(page.getByTestId('season-mismatch')).toHaveCount(0)
  await page.getByLabel('Season', { exact: true }).selectOption('2024')
  const banner = page.getByTestId('season-mismatch')
  await expect(banner).toContainText('This event is from 2026, but 2024 is selected')
  await expect(banner.getByRole('button', { name: 'Switch to 2026' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /\(2026tuis\)/ })).toBeVisible()
  ev.push(`"${(await banner.innerText()).replace(/\s+/g, ' ')}"; the page still shows 2026tuis (2026 data)`)
})

step('4.11', 'switching season on /explorer leaves no old rows', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/explorer', 2024)
  for (const next of [2025, 2026]) {
    await page.getByLabel('Season', { exact: true }).selectOption(String(next))
    const table = page.getByTestId('events-table')
    await expect(table.locator('a').first()).toHaveAttribute('href', new RegExp(`^/explorer/events/${next}`), { timeout: 60_000 })
    const hrefs = await table.locator('a').evaluateAll((as) => as.map((a) => a.getAttribute('href') ?? ''))
    expect(hrefs.every((h) => h.startsWith(`/explorer/events/${next}`))).toBe(true)
    ev.push(`-> ${next}: ${hrefs.length} links, all ${next}`)
  }
})

step('4.12', 'UI A with 2023 says plainly it has no 2023 data', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/explorer', 2023)
  await expect(page.getByTestId('no-season-data')).toHaveText('No 2023 data is synced. Sync the season to use its views.',
    { timeout: 60_000 })
  ev.push('"No 2023 data is synced. Sync the season to use its views."')
})

step('4.13', 'the selected season persists across a reload', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/explorer', 2025)
  await page.reload()
  await expect(page.getByLabel('Season', { exact: true })).toHaveValue('2025')
  ev.push('2025 selected, reloaded: still 2025')
})

step('4.14', 'browsing created nothing', 'automated', async ({ page }, ev) => {
  const after = await writeSnapshot(page)
  ev.push(`manual ids:attempt counts and 2027 ruleset counts, before section 4 = after: ${after === before}`, `snapshot: ${after}`)
  expect(after).toBe(before)
})

// --- 5. Layout, keyboard and errors -----------------------------------------------------------------------------

const LAYOUT = `(() => {
  const w = document.documentElement.clientWidth
  const scrolls = (el) => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX)
  const unscrollable = []
  for (const t of document.querySelectorAll('table')) {
    if (t.getBoundingClientRect().right <= w + 1 && t.scrollWidth <= t.clientWidth + 1) continue
    let a = t.parentElement, ok = scrolls(t) && t.getBoundingClientRect().right <= w + 1
    while (!ok && a) { if (scrolls(a) && a.getBoundingClientRect().right <= w + 1) ok = true; a = a.parentElement }
    if (!ok) unscrollable.push(t.className || 'table')
  }
  const small = [...document.querySelectorAll('button, [role=tab], select, input:not([type=checkbox])')]
    .filter((b) => b.getClientRects().length && b.getBoundingClientRect().height < 24)
    .map((b) => (b.innerText || b.getAttribute('aria-label') || b.tagName).slice(0, 30))
  return { width: w, pageScroll: document.documentElement.scrollWidth > w + 1, unscrollable, small }
})()`

const LAYOUT_PAGES: [string, Ui, string, number, string | null][] = [
  ['manuals', UI_A, '/manuals', 2027, null], ['rulesets', UI_A, '/rulesets', 2027, null],
  ['readiness', UI_A, '/readiness', 2027, null], ['explorer', UI_A, '/explorer', 2026, null],
  ['event-teams', UI_A, '/explorer/events/2026tuis', 2026, null],
  ['event-matches', UI_A, '/explorer/events/2026tuis', 2026, 'Matches'],
  ['event-analysis', UI_A, '/explorer/events/2026tuis', 2026, 'Event analysis'],
  ['event-forecast', UI_A, '/explorer/events/2026tuis', 2026, 'Qualification forecast'],
  ['event-ranking', UI_A, '/explorer/events/2026tuis', 2026, 'Ranking prediction'],
  ['team', UI_A, '/explorer/teams/9483', 2026, null], ['explorer-2023', UI_B, '/explorer', 2023, null],
]

async function settle(page: Page): Promise<void> {
  await expect(page.getByText('Loading…')).toHaveCount(0, { timeout: LONG })
  await page.waitForTimeout(300)
}

step('5.1', 'desktop width (readability is the tester\'s judgement)', 'partial', async ({ page }, ev) => {
  for (const [name, ui, route, season, tab] of LAYOUT_PAGES) {
    await open(page, ui, route, season)
    if (tab) await page.getByRole('tab', { name: tab }).click()
    await settle(page)
    const layout = await page.evaluate(LAYOUT) as { pageScroll: boolean; unscrollable: string[] }
    expect(layout.pageScroll, `${name}: page-level horizontal scroll`).toBe(false)
    await snap(page, ev, `5.1-${name}`)
  }
  ev.push(`1280x900: ${LAYOUT_PAGES.length} views, none scrolls horizontally; readability and overlap: the tester's judgement `
    + 'from the screenshots or the browser')
})

step('5.2', 'phone width 390x844 (emulated)', 'automated', async ({ browser }, ev) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    deviceScaleFactor: 3 })
  const page = await context.newPage()
  const problems: string[] = []
  for (const [name, ui, route, season, tab] of LAYOUT_PAGES) {
    await open(page, ui, route, season)
    if (tab) await page.getByRole('tab', { name: tab }).click()
    await settle(page)
    const layout = await page.evaluate(LAYOUT) as { width: number; pageScroll: boolean; unscrollable: string[]; small: string[] }
    if (layout.pageScroll) problems.push(`${name}: page-level horizontal scroll`)
    if (layout.unscrollable.length) problems.push(`${name}: wide table not in a scroll box (${layout.unscrollable})`)
    if (layout.small.length) problems.push(`${name}: controls under 24 px high (${layout.small.join(', ')})`)
    const file = path.join(EVIDENCE, `5.2-${name}.png`)
    await page.screenshot({ path: file, fullPage: true })
  }
  await context.close()
  ev.push(`emulated 390x844 (isMobile, touch; not a real phone): ${LAYOUT_PAGES.length} views; screenshots 5.2-*.png`,
    problems.length ? `problems: ${problems.join(' | ')}` : 'no page-level horizontal scroll; wide tables scroll inside '
      + 'their own box; every button, tab, select and input is at least 24 px high')
  expect(problems).toEqual([])
})

step('5.4', 'keyboard: reachability and focus ring (order is the tester\'s judgement)', 'partial', async ({ page }, ev) => {
  const findings: string[] = []
  for (const [name, route, season, token] of [['event', '/explorer/events/2026tuis', 2026, false],
    ['manuals', '/manuals', 2027, true], ['readiness', '/readiness', 2027, false]] as const) {
    await open(page, UI_A, route, season, token)
    await settle(page)
    const targets = await page.evaluate(() => [...document.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary')]
      .filter((e) => e.getClientRects().length).length)
    await page.locator('body').click({ position: { x: 1, y: 1 } })
    const seen = new Set<string>()
    const order: string[] = []
    const noRing: string[] = []
    for (let i = 0; i < 400; i += 1) {
      await page.keyboard.press('Tab')
      const info = await page.evaluate(() => {
        const e = document.activeElement as HTMLElement | null
        if (!e || e === document.body) return null
        const cs = getComputedStyle(e)
        const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none'
        const all = [...document.querySelectorAll('a[href], button, input, select, textarea, summary')]
        return { key: `${e.tagName}:${all.indexOf(e)}`, label: (e.getAttribute('aria-label') || e.innerText || e.tagName)
          .replace(/\s+/g, ' ').slice(0, 25), ring }
      })
      if (!info) continue
      if (seen.has(info.key)) break
      seen.add(info.key)
      order.push(info.label)
      if (!info.ring) noRing.push(info.label)
    }
    findings.push(`${name}: ${seen.size} of ${targets} visible controls reached by Tab; without a focus ring: `
      + `${noRing.length ? noRing.join(', ') : 'none'}; order: ${order.join(' > ').slice(0, 600)}`)
    expect(noRing, `${name}: focused without a visible ring`).toEqual([])
    expect(seen.size, `${name}: not every control is reachable`).toBeGreaterThanOrEqual(targets)
  }
  await open(page, UI_A, '/explorer/events/2026tuis', 2026)
  await page.getByRole('tab', { name: 'Matches' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('tab', { name: 'Matches' })).toHaveAttribute('aria-selected', 'true')
  await page.getByLabel('Season', { exact: true }).focus()
  await page.keyboard.press('ArrowDown')
  const changed = await page.getByLabel('Season', { exact: true }).inputValue()
  await open(page, UI_A, '/manuals', 2027, true)
  await page.getByLabel('Manual PDF').focus()
  const chooser = page.waitForEvent('filechooser', { timeout: 5000 })
  await page.keyboard.press('Space')
  await chooser
  findings.push(`Enter on a focused tab selects it; ArrowDown on the season select changes it (2026 -> ${changed}); Space `
    + 'on the focused file input opens the file chooser')
  ev.push(...findings, 'judgement left to the tester: whether the order is sensible and comfortable')
})

step('5.5', 'refusals are visible as text with their code', 'automated', async ({ page }, ev) => {
  await open(page, UI_A, '/explorer/events/2024isde1', 2024)
  await page.getByRole('tab', { name: 'Matches' }).click()
  const row = page.getByTestId('matches-table').locator('tbody tr', { has: page.locator('code', { hasText: /^qm1$/ }) })
  await row.getByRole('button', { name: 'Win probability' }).click()
  const unavailable = row.getByTestId('unavailable')
  await expect(unavailable).toContainText('(insufficient_features)', { timeout: LONG })
  ev.push(`explorer refusal: "${(await unavailable.innerText()).replace(/\s+/g, ' ')}"`)
  await open(page, UI_A, '/manuals', 2027, true)
  const scanned = page.locator('tbody tr', { hasText: 'auto_scanned.pdf' }).last()
  await scanned.getByRole('button', { name: 'Open' }).click()
  await expect(processingBadge(page)).toHaveText('failed', { timeout: 60_000 })
  const reasonVisible = await page.getByRole('alert').filter({ hasText: 'unreadable_text:' }).isVisible()
  ev.push(`processing failure (auto_scanned.pdf): status badge "failed"; the reason and its code visible without `
    + `expanding "Processing attempts": ${reasonVisible}`)
  expect(reasonVisible, 'the failure reason is visible only after expanding "Processing attempts"').toBe(true)
})

step('5.6', 'with the API down the page shows an error, then recovers', 'automated', async ({ page }, ev) => {
  const state = readState()
  await open(page, UI_A, '/explorer', 2026)
  await expect(page.getByTestId('events-table')).toBeVisible({ timeout: 60_000 })
  stop(state.pids.apiA)
  await page.reload()
  const error = page.locator('[role=alert]').first()
  await expect(error).toBeVisible({ timeout: 60_000 })
  const shown = (await error.innerText()).replace(/\s+/g, ' ')
  const restarted = await startApi(API_A)
  writeState({ ...state, pids: { ...state.pids, apiA: restarted.pid } })
  await page.reload()
  await expect(page.getByTestId('events-table')).toBeVisible({ timeout: 60_000 })
  ev.push(`API A stopped: "${shown.slice(0, 160)}"; restarted (${restarted.firstLine}); the events table loads again`)
})
