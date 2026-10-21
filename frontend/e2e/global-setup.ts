// Starts the four automation servers and writes the checklist's synthetic PDFs, plus byte-distinct copies the
// automation uploads (a trailing PDF comment: same text, so the same expected results; a different sha256, so they
// never dedupe onto the tester's own manuals).
import { execFileSync } from 'node:child_process'
import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'

import {
  API_A, API_B, EVIDENCE, FILES_DIR, PYTHON, REPO, STEPS_FILE, UI_A, UI_B, ensureEvidenceDir, startApi, startUi,
  writeState,
} from './servers'

// Each run's copies are new bytes, so a rerun never lands on an earlier run's manuals (or adds attempts to them).
const RUN_ID = new Date().toISOString()

export default async function globalSetup(): Promise<void> {
  ensureEvidenceDir()
  rmSync(STEPS_FILE, { force: true })
  const filesOutput = execFileSync(PYTHON, ['-m', 'scripts.local_test_env', '--checklist-files', FILES_DIR],
    { cwd: REPO, encoding: 'utf-8' }).split(/\r?\n/).filter(Boolean)
  for (const line of filesOutput) {
    const name = path.basename(line)
    writeFileSync(path.join(FILES_DIR, `auto_${name}`),
      Buffer.concat([readFileSync(line), Buffer.from(`% Checklist Automation copy ${RUN_ID}\n`)]))
  }
  const a = await startApi(API_A)
  const b = await startApi(API_B)
  const uiA = await startUi(UI_A)
  const uiB = await startUi(UI_B)
  writeState({ pids: { apiA: a.pid, apiB: b.pid, uiA, uiB }, startup: { apiA: a.firstLine, apiB: b.firstLine },
    filesOutput })
  writeFileSync(path.join(EVIDENCE, 'started.txt'), new Date().toISOString())
}
