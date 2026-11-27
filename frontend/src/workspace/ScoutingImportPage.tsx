// Importing a ScoutRadioz scouting CSV export (audit 2026-11-26, workstream 8). Administrators only: the import writes
// the shared scouting data that defense ratings come from. Choose a file, read the row-by-row preview, then confirm.
// The server checks everything again (data/metrics/scoutradioz_upload.py); the checks here only catch the obvious
// mistakes before a file is sent.

import { useMemo, useRef, useState, type ChangeEvent } from 'react'

import {
  scoutingImport,
  type ImportRow,
  type ImportRowStatus,
  type ScoutingImportPreview,
  type ScoutingImportResult,
} from '../auth/api'
import { ErrorNotice, useAction } from '../components/common'
import { PageHeader } from '../dashboard/common'
import { checkFile, MAX_FILE_BYTES } from './scoutingImportFile'

const STATUS_LABEL: Record<ImportRowStatus, string> = {
  accepted: 'Will import',
  rejected: 'Rejected',
  excluded: 'No rating',
  duplicate: 'Duplicate',
  already_imported: 'Already imported',
  conflict: 'Conflict',
}
const STATUS_TONE: Record<ImportRowStatus, string> = {
  accepted: 'ok', rejected: 'bad', excluded: 'old', duplicate: 'warn', already_imported: 'old', conflict: 'bad',
}
const ORDER: ImportRowStatus[] = ['accepted', 'rejected', 'conflict', 'duplicate', 'already_imported', 'excluded']

interface Chosen {
  name: string
  text: string
}

export function ScoutingImportPage() {
  const input = useRef<HTMLInputElement>(null)
  const [chosen, setChosen] = useState<Chosen | null>(null)
  const [fileProblem, setFileProblem] = useState<string | null>(null)
  const [preview, setPreview] = useState<ScoutingImportPreview | null>(null)
  const [result, setResult] = useState<ScoutingImportResult | null>(null)
  const [understood, setUnderstood] = useState(false)
  const [problemsOnly, setProblemsOnly] = useState(false)
  const previewing = useAction()
  const importing = useAction()

  function reset() {
    setChosen(null); setFileProblem(null); setPreview(null); setResult(null); setUnderstood(false)
    previewing.clear(); importing.clear()
    if (input.current) input.current.value = ''
  }

  async function onChoose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    setPreview(null); setResult(null); setUnderstood(false); previewing.clear(); importing.clear()
    if (!file) { setChosen(null); return }
    const text = file.size <= MAX_FILE_BYTES ? await file.text() : ''
    const problem = checkFile(file.name, file.size, text)
    setFileProblem(problem)
    if (problem) { setChosen(null); return }
    setChosen({ name: file.name, text })
    await previewing.run(async () => setPreview(await scoutingImport.preview({ filename: file.name, content: text })))
  }

  async function onImport() {
    if (!chosen || !preview) return
    await importing.run(async () => {
      const done = await scoutingImport.confirm({ filename: chosen.name, content: chosen.text,
        file_sha256: preview.file_sha256 })
      setResult(done)
      setPreview(done)
    })
  }

  const accepted = preview?.counts.accepted ?? 0
  return (
    <div>
      <PageHeader title="Import scouting CSV"
        subtitle="Add a ScoutRadioz match-scouting export to the team's scouting data. Nothing is written until you confirm." />

      <section className="card" aria-labelledby="choose">
        <h2 id="choose">1. Choose the export</h2>
        <p className="muted small">One event per file, exported from your own team's ScoutRadioz organization. Scouts'
          names in the file are used to tell scouts apart and are never shown here.</p>
        <label className="form-row">
          <span>CSV file</span>
          <input ref={input} type="file" accept=".csv,text/csv" onChange={(e) => void onChoose(e)}
            disabled={previewing.busy || importing.busy} />
        </label>
        {fileProblem && <div className="notice notice-error" role="alert">{fileProblem}</div>}
        {previewing.busy && <p className="muted" role="status">Checking every row…</p>}
        <ErrorNotice error={previewing.error} />
      </section>

      {preview && (
        <PreviewSection preview={preview} problemsOnly={problemsOnly} onProblemsOnly={setProblemsOnly} />
      )}

      {preview && !result && (
        <section className="card" aria-labelledby="confirm">
          <h2 id="confirm">3. Confirm</h2>
          {accepted === 0 ? (
            <p>Nothing in this file can be imported: every row is shown above with its reason.</p>
          ) : (
            <>
              <label className="check">
                <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />
                {' '}I have checked the preview. Import {accepted} {accepted === 1 ? 'observation' : 'observations'} for{' '}
                {preview.event_key} into the team's scouting data.
              </label>
              <p>
                <button type="button" className="primary" disabled={!understood || importing.busy}
                  onClick={() => void onImport()}>
                  {importing.busy ? 'Importing…' : `Import ${accepted} ${accepted === 1 ? 'row' : 'rows'}`}
                </button>{' '}
                <button type="button" onClick={reset} disabled={importing.busy}>Cancel</button>
              </p>
            </>
          )}
          <ErrorNotice error={importing.error} />
        </section>
      )}

      {result && (
        <section className="card" aria-labelledby="done">
          <h2 id="done">Imported</h2>
          <div className="notice notice-ok" role="status">
            {result.import.loaded} {result.import.loaded === 1 ? 'observation' : 'observations'} stored for{' '}
            {result.event_key}.{' '}
            {result.import.metrics_recomputed ? 'Team metrics for the event were recomputed.' : 'Nothing new was stored.'}
          </div>
          {result.import.not_loaded.length > 0 && (
            <>
              <p>Not stored at the last step:</p>
              <ul>{result.import.not_loaded.map((r, i) => (
                <li key={i}>{r.match_key} team {r.team_number ?? '?'}: {r.reason}</li>))}</ul>
            </>
          )}
          <p className="muted small">Importing the same file again changes nothing.</p>
          <button type="button" onClick={reset}>Import another file</button>
        </section>
      )}
    </div>
  )
}

function PreviewSection({ preview, problemsOnly, onProblemsOnly }: {
  preview: ScoutingImportPreview
  problemsOnly: boolean
  onProblemsOnly: (value: boolean) => void
}) {
  const rows = useMemo<ImportRow[]>(
    () => (problemsOnly ? preview.rows.filter((r) => r.status !== 'accepted') : preview.rows),
    [preview.rows, problemsOnly])
  const defense = preview.mapping.defense_rating
  return (
    <section className="card" aria-labelledby="preview">
      <h2 id="preview">2. Preview</h2>
      <p>
        <strong>{preview.filename ?? 'File'}</strong>: event <strong>{preview.event_key}</strong> ({preview.season}),{' '}
        {preview.counts.rows} {preview.counts.rows === 1 ? 'row' : 'rows'}.
      </p>
      <div className="tiles" role="group" aria-label="Rows by outcome">
        {ORDER.map((status) => (
          <div key={status} className="tile">
            <span className="tile-value">{preview.counts[status]}</span>
            <span className="tile-label">{STATUS_LABEL[status]}</span>
          </div>
        ))}
      </div>
      {defense && (
        <p className="muted small">
          Defense is read from column <code>{defense.column}</code> ({defense.source_min}–{defense.source_max}); value
          {defense.not_a_rating.length ? ` ${defense.not_a_rating.join(', ')} means no rating` : 's are all ratings'}.
          {preview.mapping.feeding_rating ? '' : ' This season’s form has no feeding question, so feeding is not imported.'}
        </p>
      )}
      <label className="check">
        <input type="checkbox" checked={problemsOnly} onChange={(e) => onProblemsOnly(e.target.checked)} />
        {' '}Show only rows that will not be imported
      </label>
      <div className="table-scroll">
        <table className="grid compact">
          <caption className="visually-hidden">Every row of the file and what importing it would do</caption>
          <thead>
            <tr><th scope="col">Row</th><th scope="col">Outcome</th><th scope="col">Match</th><th scope="col">Team</th>
              <th scope="col">Defense</th><th scope="col">Reason</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.row}>
                <td>{r.row}</td>
                <td><span className={`badge badge-${STATUS_TONE[r.status]}`}>{STATUS_LABEL[r.status]}</span></td>
                <td>{r.match_key ?? '—'}</td>
                <td>{r.team_number ?? '—'}</td>
                <td>{r.defense_rating ?? '—'}</td>
                <td>{r.reason ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
