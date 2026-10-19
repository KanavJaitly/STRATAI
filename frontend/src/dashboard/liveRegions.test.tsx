/// <reference types="node" />
// Regression guard (review R4-2): the coach-write status regions must stay in the accessibility tree while idle, so
// a later message is announced. jsdom does not apply stylesheets, so the rule is checked in the CSS source, and the
// idle region is checked in the DOM.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { setWriteToken } from '../api/client'
import { renderAt } from '../test/dashboard'
import { baseline, EVENT, MATCH, RED } from '../test/dashboardFixtures'
import { mockApi, WRITE_OK } from '../test/mockApi'
import { RecordObservation, SaveCoachStrategy } from './coachInputs'

afterEach(() => setWriteToken(''))

// Read from disk: the test config sets `css: false`, which empties CSS imports, even `?raw` ones.
const STYLES = ['../index.css', '../styles/dashboard.css'] // every stylesheet main.tsx loads
  .map((file) => readFileSync(fileURLToPath(new URL(file, import.meta.url)), 'utf8')).join('\n')

describe('persistent status regions', () => {
  it('no stylesheet rule hides a status region (display:none or visibility:hidden)', () => {
    expect(STYLES).toMatch(/\.live-status|\.badge/) // the stylesheets were really read (never a vacuous pass)
    const rules = [...STYLES.matchAll(/([^{}]*)\{([^}]*)\}/g)]
      .filter(([, selector]) => /\.live-status|\[role=['"]?status/.test(selector))
    for (const [, selector, body] of rules) {
      expect(body, selector.trim()).not.toMatch(/display\s*:\s*none|visibility\s*:\s*hidden/)
    }
  })

  it('renders each coach-write status region before any message, empty', async () => {
    mockApi({ ...WRITE_OK })
    renderAt('/', '/', <><SaveCoachStrategy eventKey={EVENT} matchKey={MATCH} strategy={baseline(RED)} />
      <RecordObservation eventKey={EVENT} teams={RED} /></>)
    await screen.findByRole('button', { name: 'Save as a coach strategy' })
    const regions = document.querySelectorAll('.live-status[role="status"]')
    expect(regions).toHaveLength(2)
    for (const region of regions) expect(region.textContent).toBe('')
  })
})
