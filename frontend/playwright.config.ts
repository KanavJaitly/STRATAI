// Browser checklist automation (docs/browser_acceptance_checklist.md), run against the local test environment on
// the isolated copies only. Uses the installed Chrome (channel 'chrome'); no browser is downloaded.
//   npx playwright test
import { defineConfig } from '@playwright/test'

import { EVIDENCE } from './e2e/servers'

export default defineConfig({
  testDir: './e2e',
  testMatch: '*.e2e.ts',
  outputDir: `${EVIDENCE}/test-output`,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 6 * 60_000,
  globalTimeout: 40 * 60_000, // the permanent 45-minute limit, with margin
  expect: { timeout: 15_000 },
  reporter: [['list'], ['json', { outputFile: `${EVIDENCE}/report.json` }]],
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
  use: { channel: 'chrome', headless: true, viewport: { width: 1280, height: 900 }, screenshot: 'only-on-failure',
    actionTimeout: 60_000 },
})
