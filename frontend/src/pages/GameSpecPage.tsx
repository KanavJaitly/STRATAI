import { useState } from 'react'

import { api } from '../api/client'
import type { Manual, SpecState, SpecVersion } from '../api/types'
import {
  ErrorNotice, LoadState, Section, Sha, StateBadge, SuccessNotice, When, WriteGate, useAction, useLoad,
} from '../components/common'
import { RowsEditor } from '../components/RowsEditor'
import { sha256Hex } from '../lib/sha256'
import { useSession } from '../state/session'
import {
  emptyAction, emptyElement, emptyRule, emptySpecForm, fromSpecJson, toSpecJson,
  type ActionRow, type ElementRow, type RuleRow, type SpecForm,
} from './specForm'

const STAGES: { state: SpecState | 'source_uploaded'; label: string }[] = [
  { state: 'source_uploaded', label: 'Source uploaded' },
  { state: 'structured_spec_incomplete', label: 'Structured spec incomplete' },
  { state: 'draft_complete_not_submitted', label: 'Complete draft, not submitted' },
  { state: 'awaiting_human_review', label: 'Awaiting human review' },
  { state: 'reviewed_approved', label: 'Reviewed / approved' },
]

function ManualUpload({ season, onUploaded }: { season: number; onUploaded: () => void }) {
  const { actor } = useSession()
  const [file, setFile] = useState<File | null>(null)
  const [gameName, setGameName] = useState('')
  const [localSha, setLocalSha] = useState<string | null>(null)
  const [result, setResult] = useState<{ manual: Manual; created: boolean } | null>(null)
  const action = useAction()

  const choose = async (chosen: File | null) => {
    setFile(chosen)
    setResult(null)
    setLocalSha(chosen ? await sha256Hex(await chosen.arrayBuffer()) : null)
  }

  const upload = () => action.run(async () => {
    if (!file) throw new Error('Choose the manual PDF first.')
    const response = await api.uploadManual({ season, game_name: gameName, filename: file.name, uploaded_by: actor }, file)
    if (localSha && response.manual.content_sha256 !== localSha) {
      throw new Error(`The server's checksum ${response.manual.content_sha256} does not match this file's ${localSha}.`)
    }
    setResult(response)
    onUploaded()
  })

  return (
    <WriteGate>
      <form className="form-row" onSubmit={(e) => { e.preventDefault(); void upload() }}>
        <label>
          Manual PDF
          <input type="file" accept="application/pdf,.pdf" aria-label="Manual PDF"
            onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
        </label>
        <label>
          Game name
          <input value={gameName} onChange={(e) => setGameName(e.target.value)} aria-label="Game name" required />
        </label>
        <button type="submit" disabled={action.busy || !file || !gameName.trim()}>Upload manual</button>
      </form>
      {localSha && <p className="small">This file's sha256: <code>{localSha}</code></p>}
      <ErrorNotice error={action.error} />
      {result && (
        <div className={`notice ${result.created ? 'notice-ok' : 'notice-info'}`} role="status">
          {result.created
            ? `Stored as manual #${result.manual.id} (sha256 ${result.manual.content_sha256.slice(0, 12)}…).`
            : `This exact file is already manual #${result.manual.id}. Nothing was replaced or duplicated.`}
        </div>
      )}
      <p className="muted small">
        Uploading keeps the original PDF unchanged, with its checksum. It does not validate anything, and nothing
        reads the PDF automatically: the structured specification below is entered and reviewed by people. A
        different file is stored as a new manual; an existing manual is never replaced.
      </p>
    </WriteGate>
  )
}

const PERIODS = ['auto', 'teleop', 'endgame'] as const

function SpecEditor({ season, manuals, base, onSaved }: {
  season: number; manuals: Manual[]; base: SpecVersion | null; onSaved: (saved: SpecVersion) => void
}) {
  const { actor } = useSession()
  const [form, setForm] = useState<SpecForm>(() => (base ? fromSpecJson(base.spec_json) : emptySpecForm()))
  const [manualId, setManualId] = useState<string>(() => String(base?.manual_id ?? manuals.at(-1)?.id ?? ''))
  const action = useAction()
  const set = (patch: Partial<SpecForm>) => setForm((f) => ({ ...f, ...patch }))
  const elementIds = form.field_elements.map((e) => e.element_id).filter(Boolean)

  const save = () => action.run(async () => {
    const saved = await api.saveSpec(season, {
      spec_json: toSpecJson(form), created_by: actor, manual_id: manualId ? Number(manualId) : null,
      based_on_id: base?.id ?? null,
    })
    onSaved(saved)
  }, 'Saved as a new version.')

  return (
    <form onSubmit={(e) => { e.preventDefault(); void save() }} className="spec-editor">
      <p className="muted small">
        {base ? `Starting from version ${base.version}. Saving creates a new version; version ${base.version} is kept unchanged.`
          : 'Starting from a blank specification. Enter what the manual says, citing its sections.'}
      </p>
      <div className="form-grid">
        <label>Game name<input value={form.game_name} onChange={(e) => set({ game_name: e.target.value })} aria-label="Spec game name" /></label>
        <label>Manual title<input value={form.manual_title} onChange={(e) => set({ manual_title: e.target.value })} aria-label="Manual title" /></label>
        <label>Manual version<input value={form.manual_version} onChange={(e) => set({ manual_version: e.target.value })} aria-label="Manual version" /></label>
        <label>
          Entered from manual
          <select value={manualId} onChange={(e) => setManualId(e.target.value)} aria-label="Entered from manual">
            <option value="">(not linked)</option>
            {manuals.map((m) => <option key={m.id} value={m.id}>#{m.id} {m.filename}</option>)}
          </select>
        </label>
        <label>Auto (s)<input value={form.auto_seconds} inputMode="numeric" onChange={(e) => set({ auto_seconds: e.target.value })} aria-label="Auto seconds" /></label>
        <label>Teleop incl. endgame (s)<input value={form.teleop_seconds} inputMode="numeric" onChange={(e) => set({ teleop_seconds: e.target.value })} aria-label="Teleop seconds" /></label>
        <label>Endgame (s)<input value={form.endgame_seconds} inputMode="numeric" onChange={(e) => set({ endgame_seconds: e.target.value })} aria-label="Endgame seconds" /></label>
      </div>
      <datalist id="element-ids">{elementIds.map((id) => <option key={id} value={id} />)}</datalist>
      <RowsEditor<ElementRow> label="Field elements" rows={form.field_elements} newRow={emptyElement}
        onChange={(rows) => set({ field_elements: rows })}
        columns={[
          { key: 'element_id', label: 'ID' }, { key: 'name', label: 'Name' },
          { key: 'count', label: 'Count', type: 'number', width: '5em' }, { key: 'element_type', label: 'Type' },
          { key: 'manual_section', label: 'Manual §' },
        ]} />
      <RowsEditor<ActionRow> label="Scoring actions" rows={form.scoring_actions} newRow={emptyAction}
        onChange={(rows) => set({ scoring_actions: rows })}
        columns={[
          { key: 'action_id', label: 'ID' }, { key: 'name', label: 'Name' },
          { key: 'period', label: 'Period', type: 'select', options: PERIODS },
          { key: 'points', label: 'Points', type: 'number', width: '5em' }, { key: 'unit', label: 'Unit' },
          { key: 'field_element_id', label: 'Element', list: 'element-ids' },
          { key: 'action_type', label: 'Action type' }, { key: 'manual_section', label: 'Manual §' },
        ]} />
      <RowsEditor<RuleRow> label="Ranking-point rules" rows={form.ranking_point_rules} newRow={emptyRule}
        onChange={(rows) => set({ ranking_point_rules: rows })}
        columns={[
          { key: 'rule_id', label: 'ID' }, { key: 'description', label: 'Description' },
          { key: 'ranking_points', label: 'RP', type: 'number', width: '5em' }, { key: 'manual_section', label: 'Manual §' },
        ]} />
      <button type="submit" disabled={action.busy}>Save as new version</button>
      <ErrorNotice error={action.error} />
      <SuccessNotice message={action.message} />
    </form>
  )
}

function VersionDetail({ spec, onChanged, onEdit }: { spec: SpecVersion; onChanged: () => void; onEdit: () => void }) {
  const { actor } = useSession()
  const [note, setNote] = useState('')
  const action = useAction()
  return (
    <div className="detail" data-testid="spec-detail">
      <h3>Version {spec.version} <StateBadge state={spec.status} /></h3>
      <dl className="facts">
        <dt>Entered by</dt><dd>{spec.created_by}, <When value={spec.created_at} /></dd>
        <dt>Complete</dt><dd>{spec.complete ? 'yes: satisfies the GameSpec schema' : 'no'}</dd>
        <dt>sha256</dt><dd><Sha value={spec.spec_sha256} /></dd>
        <dt>Based on</dt><dd>{spec.based_on_id ? `#${spec.based_on_id}` : '—'}</dd>
        <dt>Manual</dt><dd>{spec.manual_id ? `#${spec.manual_id}` : 'not linked'}</dd>
        {spec.reviewed_by && <><dt>Reviewed</dt><dd>{spec.reviewed_by}, <When value={spec.reviewed_at} />{spec.review_note && `: “${spec.review_note}”`}</dd></>}
      </dl>
      {spec.validation_errors.length > 0 && (
        <div className="notice notice-warn">
          <strong>Still incomplete ({spec.validation_errors.length}):</strong>
          <ul>{spec.validation_errors.map((e, i) => <li key={i}><code>{e.field || '(spec)'}</code>: {e.message}</li>)}</ul>
        </div>
      )}
      <WriteGate>
        <div className="actions">
          <button type="button" className="secondary" onClick={onEdit}>Start a new version from this one</button>
          {spec.status === 'draft' && (
            <button type="button" disabled={!spec.complete || action.busy}
              title={spec.complete ? '' : 'An incomplete spec cannot go to review'}
              onClick={() => void action.run(async () => { await api.submitSpec(spec.id); onChanged() }, 'Sent for review.')}>
              Submit for human review
            </button>
          )}
        </div>
        {spec.status === 'awaiting_review' && (
          <div className="review-box">
            <p className="small">
              Reviewing as <strong>{actor}</strong>. Approving makes this version authoritative for {spec.season} and
              supersedes any earlier approved version.
            </p>
            <label>Review note<textarea value={note} onChange={(e) => setNote(e.target.value)} aria-label="Review note" /></label>
            <div className="actions">
              <button type="button" disabled={action.busy}
                onClick={() => void action.run(async () => { await api.reviewSpec(spec.id, { reviewer: actor, approve: true, note }); onChanged() }, 'Approved.')}>
                Approve
              </button>
              <button type="button" className="secondary" disabled={action.busy || !note.trim()}
                title={note.trim() ? '' : 'Returning a spec needs a note'}
                onClick={() => void action.run(async () => { await api.reviewSpec(spec.id, { reviewer: actor, approve: false, note }); onChanged() }, 'Returned for changes.')}>
                Return for changes
              </button>
            </div>
          </div>
        )}
      </WriteGate>
      <ErrorNotice error={action.error} />
      <SuccessNotice message={action.message} />
    </div>
  )
}

export function GameSpecPage() {
  const { season } = useSession()
  const workflow = useLoad(() => api.workflow(season), [season])
  const manuals = useLoad(() => api.listManuals(season), [season])
  const specs = useLoad(() => api.listSpecs(season), [season])
  const [selected, setSelected] = useState<number | null>(null)
  const [editing, setEditing] = useState<{ base: SpecVersion | null; key: number } | null>(null)
  const reloadAll = async () => { await Promise.all([workflow.reload(), manuals.reload(), specs.reload()]) }
  const current = specs.data?.find((s) => s.id === selected) ?? null
  const state = workflow.data?.spec_state

  return (
    <>
      <Section title={`Game manual & specification · ${season}`}>
        <LoadState loading={workflow.loading && !workflow.data} error={workflow.error} />
        {workflow.data && (
          <>
            <ol className="stages" aria-label="Workflow state">
              {STAGES.map((s) => {
                const reached = s.state === 'source_uploaded' ? workflow.data!.source_uploaded : s.state === state
                return <li key={s.state} className={reached ? 'reached' : ''} aria-current={reached ? 'step' : undefined}>{s.label}</li>
              })}
            </ol>
            <p className="small">
              Current state: <StateBadge state={workflow.data.spec_state} />{' '}
              {workflow.data.approved_version !== null && <>· approved version {workflow.data.approved_version} </>}
              {workflow.data.entry_started_at && <>· spec entry began <When value={workflow.data.entry_started_at} /> (DM1's 5-day clock)</>}
            </p>
            <p className="muted small">{workflow.data.note}</p>
          </>
        )}
      </Section>

      <Section title="Official manual (source artifact)">
        <LoadState loading={manuals.loading && !manuals.data} error={manuals.error} />
        {manuals.data && manuals.data.length === 0 && <p className="muted">No manual uploaded for {season}.</p>}
        {manuals.data && manuals.data.length > 0 && (
          <table className="grid">
            <thead><tr><th>#</th><th>File</th><th>Game</th><th>Size</th><th>sha256</th><th>Uploaded</th></tr></thead>
            <tbody>
              {manuals.data.map((m) => (
                <tr key={m.id}>
                  <td>{m.id}</td>
                  <td><a href={api.manualFileUrl(m.id)}>{m.filename}</a></td>
                  <td>{m.game_name}</td>
                  <td>{(m.byte_size / 1024).toFixed(0)} KB</td>
                  <td><Sha value={m.content_sha256} /></td>
                  <td>{m.uploaded_by}, <When value={m.uploaded_at} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <ManualUpload season={season} onUploaded={() => void reloadAll()} />
      </Section>

      <Section title="Structured specification versions"
        actions={<WriteGate><button type="button" className="secondary" onClick={() => setEditing({ base: null, key: Date.now() })}>New blank version</button></WriteGate>}>
        <LoadState loading={specs.loading && !specs.data} error={specs.error} />
        {specs.data && specs.data.length === 0 && <p className="muted">No structured specification yet.</p>}
        {specs.data && specs.data.length > 0 && (
          <table className="grid">
            <thead><tr><th>Version</th><th>Status</th><th>Complete</th><th>Entered by</th><th>Reviewed by</th><th>sha256</th><th /></tr></thead>
            <tbody>
              {[...specs.data].reverse().map((s) => (
                <tr key={s.id} className={s.id === selected ? 'selected' : ''}>
                  <td>{s.version}</td>
                  <td><StateBadge state={s.status} /></td>
                  <td>{s.complete ? 'yes' : `no (${s.validation_errors.length})`}</td>
                  <td>{s.created_by}</td>
                  <td>{s.reviewed_by ?? '—'}</td>
                  <td><Sha value={s.spec_sha256} /></td>
                  <td><button type="button" className="link" onClick={() => setSelected(s.id)}>view</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {current && (
          <VersionDetail spec={current} onChanged={() => void reloadAll()}
            onEdit={() => setEditing({ base: current, key: Date.now() })} />
        )}
      </Section>

      {editing && (
        <Section title={editing.base ? `New version from version ${editing.base.version}` : 'New version'}
          actions={<button type="button" className="link" onClick={() => setEditing(null)}>close</button>}>
          <WriteGate>
            <SpecEditor key={editing.key} season={season} manuals={manuals.data ?? []} base={editing.base}
              onSaved={(saved) => { setSelected(saved.id); void reloadAll() }} />
          </WriteGate>
        </Section>
      )}
    </>
  )
}
