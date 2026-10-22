// Local servers for the browser checklist automation (2026-10-12). Its own ports, the same isolated databases as the
// manual checklist: UI A -> stratai_test, UI B -> stratai_test_2023 (read-only: never given the write token).
import { execFileSync, spawn } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const REPO = path.resolve(FRONTEND, '..')
export const PYTHON = path.join(REPO, '.venv', 'Scripts', 'python.exe')
export const EVIDENCE = process.env.STRATAI_E2E_OUT ?? 'C:/Dev/StratAI-artifacts/local_test/playwright'
export const STATE_FILE = path.join(EVIDENCE, 'servers.json')
export const STEPS_FILE = path.join(EVIDENCE, 'steps.jsonl')
export const FILES_DIR = path.join(EVIDENCE, 'files')

export const API_A = { port: 8775, database: 'stratai_test' }
export const API_B = { port: 8776, database: 'stratai_test_2023' }
export const UI_A = { port: 5183, api: API_A.port, url: 'http://localhost:5183' }
export const UI_B = { port: 5184, api: API_B.port, url: 'http://localhost:5184' }
export const ACTOR = 'Checklist Automation'
export const TOKEN = 'local-test-token'

export interface ServerState { pids: Record<string, number>; startup: Record<string, string>; filesOutput: string[] }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function waitFor(url: string, timeoutMs = 120_000): Promise<void> {
  const until = Date.now() + timeoutMs
  while (Date.now() < until) {
    try { if ((await fetch(url)).ok) return } catch { /* not up yet */ }
    await sleep(500)
  }
  throw new Error(`${url} did not become ready in ${timeoutMs} ms`)
}

/** Start the local test API on an isolated copy; resolves with its pid and its first stdout line. */
export async function startApi(api: { port: number; database: string }): Promise<{ pid: number; firstLine: string }> {
  const args = ['-m', 'scripts.local_test_env', '--serve', '--port', String(api.port)]
  if (api.database !== 'stratai_test') args.push('--database', api.database)
  const child = spawn(PYTHON, args, { cwd: REPO, env: { ...process.env, PYTHONUNBUFFERED: '1' }, windowsHide: true })
  let output = ''
  child.stdout.on('data', (d) => { output += String(d) })
  child.stderr.on('data', (d) => { appendFileSync(path.join(EVIDENCE, `api_${api.port}.log`), String(d)) })
  await waitFor(`http://127.0.0.1:${api.port}/ready`)
  return { pid: child.pid as number, firstLine: output.split(/\r?\n/)[0] }
}

export async function startUi(ui: { port: number; api: number }): Promise<number> {
  const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--port', String(ui.port), '--strictPort'],
    { cwd: FRONTEND, env: { ...process.env, STRATAI_API_URL: `http://127.0.0.1:${ui.api}` }, windowsHide: true })
  child.stdout.on('data', () => undefined)
  child.stderr.on('data', (d) => { appendFileSync(path.join(EVIDENCE, `ui_${ui.port}.log`), String(d)) })
  await waitFor(`http://localhost:${ui.port}/api/ready`)
  return child.pid as number
}

export function stop(pid: number): void {
  try { execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' }) } catch { /* already gone */ }
}

export function readState(): ServerState { return JSON.parse(readFileSync(STATE_FILE, 'utf-8')) }
export function writeState(state: ServerState): void { writeFileSync(STATE_FILE, JSON.stringify(state, null, 1)) }

export function ensureEvidenceDir(): void { if (!existsSync(EVIDENCE)) mkdirSync(EVIDENCE, { recursive: true }) }
