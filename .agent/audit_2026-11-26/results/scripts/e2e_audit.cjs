// Audit 2026-11-26: every section of the web app, as each role, against the API on stratai_test_e2e (port 5196).
// Run: NODE_PATH=frontend/node_modules node e2e_audit.cjs
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const UI = 'http://localhost:5196'
const OUT = path.join(__dirname, 'e2e')
const EVENT = process.env.AUDIT_EVENT || '2026mose'
const results = []
const note = (role, step, ok, detail = '') => {
  results.push({ role, step, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'} [${role}] ${step}${detail ? ' — ' + detail : ''}`)
}
const PASSWORD = 'Audit-Password-2026!'
const HEADERS = { 'X-StratAI-CSRF': '1' }

async function signup(request, who, code) {
  const r = await request.post(`${UI}/api/auth/signup`, { headers: HEADERS,
    data: { full_name: `Audit ${who}`, email: `${who}@audit.example.test`, password: PASSWORD, join_code: code } })
  if (r.status() === 409) {
    return request.post(`${UI}/api/auth/login`, { headers: HEADERS, data: { email: `${who}@audit.example.test`, password: PASSWORD } })
  }
  return r
}

async function newSession(browser, who, code) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  const issues = { pageErrors: [], console: [], server: [] }
  page.on('pageerror', (e) => issues.pageErrors.push(String(e).slice(0, 200)))
  page.on('console', (m) => { if (m.type() === 'error') issues.console.push(m.text().slice(0, 200)) })
  page.on('response', (r) => { if (r.status() >= 500) issues.server.push(`${r.status()} ${r.url().replace(UI, '')}`) })
  const res = await signup(page.request, who, code)
  return { context, page, issues, ok: res.ok(), status: res.status() }
}

async function visit(s, role, url, expectAllowed, check) {
  const before = { p: s.issues.pageErrors.length, s: s.issues.server.length }
  await s.page.goto(UI + url)
  await s.page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => undefined)
  await s.page.waitForTimeout(400)
  const body = await s.page.locator('body').innerText()
  const blocked = /Your role does not include this page/.test(body)
  const newPageErrors = s.issues.pageErrors.slice(before.p)
  const newServer = s.issues.server.slice(before.s)
  let extra = ''
  let ok = blocked === !expectAllowed && newPageErrors.length === 0 && newServer.length === 0
  if (ok && check && expectAllowed) {
    try { extra = (await check(s.page, body)) || '' } catch (e) { ok = false; extra = String(e).slice(0, 200) }
  }
  note(role, `${expectAllowed ? 'open' : 'refused'} ${url}`, ok,
    [blocked && expectAllowed ? 'unexpectedly blocked' : '', !blocked && !expectAllowed ? 'NOT blocked' : '',
      newPageErrors.join(' | '), newServer.join(' | '), extra].filter(Boolean).join('; '))
  const name = `${role}_${url.replace(/[^a-z0-9]+/gi, '_').slice(0, 60)}.png`
  await s.page.screenshot({ path: path.join(OUT, name), fullPage: false }).catch(() => undefined)
  return body
}

const expectText = (re, what) => async (page) => {
  await page.getByText(re).first().waitFor({ timeout: 30000 })
  return what || ''
}

;(async () => {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.launch({ channel: 'chrome', headless: true })

  // --- admin --------------------------------------------------------------------------------------------------
  const admin = await newSession(browser, 'admin', 'audit-admin-code')
  note('admin', 'sign up with the admin join code', admin.ok, String(admin.status))
  const sessions = { admin }
  for (const role of ['strategy', 'drive', 'scout', 'base']) {
    const s = await newSession(browser, role, 'audit-join-code')
    note(role, 'sign up with the team join code', s.ok, String(s.status))
    sessions[role] = s
  }
  const members = await (await admin.page.request.get(`${UI}/api/workspace/members`)).json()
  for (const role of ['strategy', 'drive', 'scout']) {
    const m = members.members.find((x) => x.email === `${role}@audit.example.test`)
    const r = await admin.page.request.post(`${UI}/api/workspace/members/${m.membership_id}/role`, { headers: HEADERS, data: { role } })
    note('admin', `set ${role} role`, r.ok(), String(r.status()))
  }
  // The workspace must be verified for scouting and recording; the single-team model creates it verified (0015).

  const A = (url, allowed, check) => visit(admin, 'admin', url, allowed, check)
  await A('/', true, expectText(/Events|events/))
  await A(`/?season=2026`, true, async (page) => {
    await page.getByRole('searchbox').or(page.getByLabel(/Search/)).first().fill('mose')
    await page.getByText(/mose|Ozark|Missouri/i).first().waitFor({ timeout: 15000 })
    return 'search filters'
  })
  for (const tab of ['', '?tab=teams', '?tab=matches', '?tab=forecast']) {
    await A(`/events/${EVENT}${tab}`, true)
  }
  const teams = await (await admin.page.request.get(`${UI}/api/events/${EVENT}/teams`)).json()
  const team = teams.teams[0].team_number
  await A(`/events/${EVENT}/teams/${team}`, true, expectText(/Strength|EPA/))
  await A(`/events/${EVENT}/strategy-lab`, true)
  const matches = await (await admin.page.request.get(`${UI}/api/events/${EVENT}/matches`)).json()
  const qm = matches.matches.find((m) => m.competition_level === 'qualification' && m.result)
  await A(`/matches/${qm.match_key}`, true, expectText(/probabilit|Probabilit|not validated|calibrat/i))
  await A(`/report/${qm.match_key}`, true)
  await A(`/events/${EVENT}/alliance-selection`, true, async (page, body) => {
    if (/Alliance selection/.test(await page.locator('h1').first().innerText().catch(() => ''))) throw new Error('old page still renders')
    return 'old page gone (404 page)'
  })
  for (const tab of ['', '?tab=members', '?tab=analytics', '?tab=settings', '?tab=activity']) await A(`/team${tab}`, true)
  await A('/drive-team', true)
  await A('/scouting', true)
  await A(`/alliance-selection/live?event=${EVENT}`, true)
  for (const p of ['/status', '/explorer', '/inputs', '/readiness', '/manuals', '/rulesets', '/inputs/game',
    '/inputs/profiles', '/inputs/review', '/account']) await A(p, true)

  // --- strategy -------------------------------------------------------------------------------------------------
  const st = sessions.strategy
  const S = (url, allowed, check) => visit(st, 'strategy', url, allowed, check)
  await S('/drive-team', true, async (page) => {
    // The event chooser lists the season's events by name (audit fix: it read an admin-only route before).
    const chooser = page.getByRole('button', { name: /Another event/i })
    if (await chooser.count()) await chooser.first().click()
    await page.waitForTimeout(1500)
    const body = await page.locator('body').innerText()
    if (/permission_denied|403/.test(body)) throw new Error('event chooser refused')
    return 'event chooser loads'
  })
  await S(`/alliance-selection/live?event=${EVENT}`, true)
  await S(`/events/${EVENT}/strategy-lab`, true)
  await S(`/report/${qm.match_key}`, true)
  await S(`/events/${EVENT}/alliance-selection`, false)
  await S('/team', false)
  await S('/explorer', false)

  // --- drive ----------------------------------------------------------------------------------------------------
  const dr = sessions.drive
  const D = (url, allowed, check) => visit(dr, 'drive', url, allowed, check)
  await D('/drive-team', true)
  await D(`/matches/${qm.match_key}`, true)
  await D(`/events/${EVENT}/teams/${team}`, true)
  await D(`/report/${qm.match_key}`, false)
  await D(`/alliance-selection/live?event=${EVENT}`, false)
  await D('/scouting', false)

  // --- scout ----------------------------------------------------------------------------------------------------
  const sc = sessions.scout
  const C = (url, allowed, check) => visit(sc, 'scout', url, allowed, check)
  await C('/scouting', true)
  // Submit a report through the API as the scout (the form posts the same body), twice: idempotent (audit fix).
  const body = { match_key: qm.match_key, team_number: qm.red_team_numbers[0], defense_rating: 3, feeding_rating: null, notes: 'audit' }
  const r1 = await sc.page.request.post(`${UI}/api/workspace/scouting/reports`, { headers: HEADERS, data: body })
  const r2 = await sc.page.request.post(`${UI}/api/workspace/scouting/reports`, { headers: HEADERS, data: body })
  const j1 = await r1.json(); const j2 = await r2.json()
  note('scout', 'submit a scouting report (and the same again)', r1.status() === 201 && j1.report_id === j2.report_id,
    `${r1.status()} ${r2.status()} ids ${j1.report_id} ${j2.report_id}`)
  const bad = await sc.page.request.post(`${UI}/api/workspace/scouting/reports`, { headers: HEADERS,
    data: { ...body, defense_rating: 9 } })
  note('scout', 'an out-of-range rating is refused (422)', bad.status() === 422, String(bad.status()))
  const offRoster = await sc.page.request.post(`${UI}/api/workspace/scouting/reports`, { headers: HEADERS,
    data: { ...body, team_number: 99999 } })
  note('scout', 'a team not in the match is refused', offRoster.status() >= 400 && offRoster.status() < 500, String(offRoster.status()))
  const noCsrf = await sc.page.request.post(`${UI}/api/workspace/scouting/reports`, { data: body })
  note('scout', 'a write without the CSRF header is refused', noCsrf.status() === 403, String(noCsrf.status()))
  const summary = await sessions.strategy.page.request.get(`${UI}/api/workspace/scouting/summary?event_key=${EVENT}`)
  const sj = await summary.json()
  const t = sj.teams.find((x) => x.team_number === body.team_number)
  note('strategy', 'scouting summary counts the double submit once', t && t.reports === 1, JSON.stringify(t && t.reports))
  await C('/drive-team', false)
  await C(`/matches/${qm.match_key}`, false)
  await C(`/events/${EVENT}`, true)

  // --- base -----------------------------------------------------------------------------------------------------
  const b = sessions.base
  const B = (url, allowed, check) => visit(b, 'base', url, allowed, check)
  await B('/', true)
  await B(`/events/${EVENT}`, true)
  await B(`/events/${EVENT}/teams/${team}`, false)
  await B('/drive-team', false)
  await B('/scouting', false)
  await B('/team', false)
  // Backend enforcement, not just hidden pages: direct API calls refused.
  for (const [url, method] of [[`/api/teams/${team}/events/${EVENT}/strength`, 'get'], ['/api/workspace/members', 'get'],
    [`/api/predictions/matches/${qm.match_key}/win-probability`, 'get'], ['/api/explorer/seasons', 'get']]) {
    const r = await b.page.request[method](UI + url)
    note('base', `API refuses ${url.replace(/\/api/, '')}`, r.status() === 403, String(r.status()))
  }
  const ev = await b.page.request.get(`${UI}/api/explorer/seasons/2026/events`)
  note('base', 'API allows the season event list (event chooser)', ev.status() === 200, String(ev.status()))

  // --- unauthenticated --------------------------------------------------------------------------------------------
  const anon = await browser.newContext()
  const ap = await anon.newPage()
  const r = await ap.request.get(`${UI}/api/events/${EVENT}/analysis`)
  note('anonymous', 'API refuses analysis without a session (401)', r.status() === 401, String(r.status()))
  await ap.goto(UI + `/events/${EVENT}`)
  await ap.waitForTimeout(1500)
  note('anonymous', 'the app sends a signed-out visitor to log in', /\/auth\/login/.test(ap.url()), ap.url().replace(UI, ''))

  const summaryAll = Object.fromEntries(Object.entries(sessions).map(([k, v]) => [k, v.issues]))
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ results, issues: summaryAll }, null, 1))
  const failed = results.filter((x) => !x.ok)
  console.log(`\n${results.length - failed.length} of ${results.length} checks passed`)
  for (const [role, v] of Object.entries(summaryAll)) {
    console.log(role, 'console errors:', v.console.length, v.console.slice(0, 3).join(' | '))
  }
  await browser.close()
})().catch((e) => { console.error('ERROR', e); process.exit(1) })
