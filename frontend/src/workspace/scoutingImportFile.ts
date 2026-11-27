// The checks the scouting CSV upload page makes before sending a file (audit 2026-11-26, workstream 8). The server
// repeats every one (data/metrics/scoutradioz_upload.py); these only spare a round trip for the obvious mistakes.

// The server's limits (data/metrics/scoutradioz_upload.py MAX_UPLOAD_BYTES) and ScoutRadioz's own export columns.
export const MAX_FILE_BYTES = 900_000
export const REQUIRED_COLUMNS = ['org_key', 'event_key', 'match_key', 'match_number', 'time', 'alliance', 'team_key',
  'scouter']

/** A reason the file cannot be sent, or null. Checks the name, size and header only; rows are the server's job. */
export function checkFile(name: string, size: number, text: string): string | null {
  if (!/\.csv$/i.test(name)) return 'Choose a .csv file (ScoutRadioz: Export data → match scouting, CSV).'
  if (size === 0 || !text.trim()) return 'The file is empty.'
  if (size > MAX_FILE_BYTES) return `The file is larger than ${MAX_FILE_BYTES.toLocaleString()} bytes; export one event at a time.`
  const header = text.replace(/^﻿/, '').split(/\r?\n/, 1)[0]
  const columns = header.split(',').map((cell) => cell.trim().replace(/^"|"$/g, ''))
  const missing = REQUIRED_COLUMNS.filter((column) => !columns.includes(column))
  if (missing.length) return `This is not a ScoutRadioz match-scouting export: missing column(s) ${missing.join(', ')}.`
  return null
}

