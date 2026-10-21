import { useState } from 'react'

import { api } from '../api/client'
import type { ChecklistInfo, RulesetVersion, Worksheet } from '../api/managerTypes'
import {
  ErrorNotice, LoadState, Section, Sha, StateBadge, SuccessNotice, When, WriteGate, useAction, useLoad,
} from '../components/common'
import { RawJson } from '../components/seasonUi'
import { UNVERIFIED, countMarkers } from '../lib/manualChecks'
import { useSession } from '../state/session'

/** Edit a ruleset's JSON and save it as a new draft version under the person's own name. */
function DraftEditor({ initial, onSaved, onCancel }: { initial: Record<string, unknown>; onSaved: () => void;
  onCancel: () => void }) {
  const { actor } = useSession()
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2))
  const action = useAction()
  let parseError: string | null = null
  try { JSON.parse(text) } catch (caught) { parseError = (caught as Error).message }
  const markers = countMarkers(text)
  return (
    <div className="review-box">
      <p className="small">Saving creates a new immutable draft version, authored by <strong>{actor || '—'}</strong>.
        The server validates it against the season-ruleset schema. A draft is not authoritative.</p>
      {markers > 0 && (
        <div className="notice notice-warn" role="status">
          {markers} value(s) still carry an <code>{UNVERIFIED} …)</code> marker. A draft may keep them, but approval
          is refused until each is verified against the official manual and replaced.
        </div>
      )}
      <textarea aria-label="Ruleset JSON" value={text} onChange={(e) => setText(e.target.value)} rows={22}
        spellCheck={false} style={{ fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '0.8rem' }} />
      {parseError && <div className="notice notice-error">JSON: {parseError}</div>}
      <ErrorNotice error={action.error} />
      <WriteGate>
        <div className="actions">
          <button type="button" disabled={action.busy || Boolean(parseError)}
            onClick={() => void action.run(async () => {
              await api.saveRuleset({ ruleset_json: JSON.parse(text), created_by: actor })
              onSaved()
            })}>Save as draft</button>
          <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
        </div>
      </WriteGate>
    </div>
  )
}

function WorksheetPanel({ season, onUse }: { season: number; onUse: (proposal: Record<string, unknown>) => void }) {
  const { data, error, loading } = useLoad<Worksheet>(() => api.rulesetWorksheet(season), [season])
  if (loading || error || !data) return <LoadState loading={loading} error={error} />
  return (
    <div>
      <p className="small">A starting point built from the approved <strong>{data.template_from_season}</strong>{' '}
        ruleset's structure. Every citation and the tie rule are marked <code>{data.unverified_marker} …)</code>, and
        another season's event lists are emptied. {data.manual
          ? `The uploaded manual #${data.manual.id} ${data.manual.processed ? 'supplies the suggestions below' : 'is not processed yet'}.`
          : `No ${season} manual is uploaded, so there are no suggestions yet.`} Nothing is saved until you save it.</p>
      {data.schema_errors.length > 0 && <div className="notice notice-error">The proposal does not validate:
        {' '}{JSON.stringify(data.schema_errors)}</div>}
      <table className="grid compact">
        <thead><tr><th>Field</th><th>Why to verify</th><th>Manual pages</th><th>Unverified suggestions</th></tr></thead>
        <tbody>
          {data.verify.map((v) => (
            <tr key={v.path}>
              <td><code>{v.path}</code></td><td>{v.reason}</td>
              <td>{v.manual_pages.length ? v.manual_pages.join(', ') : <span className="muted">—</span>}</td>
              <td>{v.suggestions.length
                ? v.suggestions.map((s, i) => <div key={i} className="small">p. {s.page}: {JSON.stringify(s.value)}</div>)
                : <span className="muted">none</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <WriteGate>
        <div className="actions"><button type="button" onClick={() => onUse(data.proposal)}>Edit as a new draft</button></div>
      </WriteGate>
    </div>
  )
}

function ReviewForm({ ruleset, checklist, onDone }: { ruleset: RulesetVersion; checklist: ChecklistInfo;
  onDone: (message: string) => void }) {
  const { actor } = useSession()
  const [qualification, setQualification] = useState('')
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [sha, setSha] = useState('')
  const [note, setNote] = useState('')
  const action = useAction()
  const allChecked = checklist.items.every((i) => checked[i.id])
  const shaMatches = sha.trim() === ruleset.ruleset_sha256
  const markers = countMarkers(JSON.stringify(ruleset.ruleset_json))
  const submit = (approve: boolean) => action.run(async () => {
    const response = await api.reviewRuleset(ruleset.id, { reviewer: actor, approve, note,
      reviewer_qualification: qualification, checklist: approve ? checked : null, verified_sha256: approve ? sha.trim() : '' })
    onDone(approve
      ? `Approved by ${actor}. Approval record written: ${response.approval_record?.path} — commit it (R15).`
      : 'Returned to draft with your note.')
  })
  return (
    <div className="review-box" data-testid="review-form">
      <p className="small">P6-M1 review control: a named, qualified FRC reviewer independently verifies the stored
        ruleset against the official FIRST sources ({checklist.guide}). You may be the author. Approval is refused
        unless every item below is completed, the full sha256 you verified matches, and no UNVERIFIED marker remains.</p>
      {markers > 0 && <div className="notice notice-error">This version still has {markers} UNVERIFIED marker(s):
        it cannot be approved. Return it, or save a corrected version.</div>}
      <label>Reviewer<input value={actor} readOnly aria-label="Reviewer" /></label>
      <label>Your FRC-domain qualification (stated accurately)
        <input value={qualification} onChange={(e) => setQualification(e.target.value)} aria-label="Qualification" />
      </label>
      <fieldset>
        <legend>Checklist (R1–R14; R15 is the approval record this writes)</legend>
        {checklist.items.map((item) => (
          <label className="inline" key={item.id}>
            <input type="checkbox" checked={Boolean(checked[item.id])} aria-label={item.id}
              onChange={(e) => setChecked({ ...checked, [item.id]: e.target.checked })} />
            {item.id} {item.title}
          </label>
        ))}
      </fieldset>
      <label>The full stored sha256 you verified
        <input value={sha} onChange={(e) => setSha(e.target.value)} aria-label="Verified sha256" spellCheck={false} />
      </label>
      {sha && <p className={`small ${shaMatches ? '' : 'muted'}`}>{shaMatches ? 'Matches the stored sha256.' : 'Does not match the stored sha256.'}</p>}
      <label>Note<textarea value={note} onChange={(e) => setNote(e.target.value)} aria-label="Review note" /></label>
      <ErrorNotice error={action.error} />
      <WriteGate>
        <div className="actions">
          <button type="button" disabled={action.busy || !qualification.trim() || !allChecked || !shaMatches || markers > 0}
            onClick={() => void submit(true)}>Approve</button>
          <button type="button" className="secondary" disabled={action.busy || !note.trim()}
            onClick={() => void submit(false)}>Return with note</button>
        </div>
      </WriteGate>
    </div>
  )
}

function summary(ruleset: RulesetVersion): [string, string][] {
  const json = ruleset.ruleset_json as Record<string, unknown>
  const counts = (json.alliance_counts as { min_teams: number; max_teams: number | null; alliances: number }[] | undefined) ?? []
  const manual = json.manual as { title?: string; version?: string } | undefined
  return [
    ['Game', String(json.game_name ?? '—')],
    ['Manual', manual ? `${manual.title} · ${manual.version}` : '—'],
    ['Alliance counts', counts.map((c) => `${c.min_teams}–${c.max_teams ?? '∞'} teams: ${c.alliances}`).join('; ') || '—'],
    ['Bracket formats', String(((json.brackets as unknown[]) ?? []).length)],
    ['Selection variants', String(((json.selection_variants as unknown[]) ?? []).length)],
    ['Event exclusions', String(((json.event_exclusions as unknown[]) ?? []).length)],
    ['UNVERIFIED markers', String(countMarkers(JSON.stringify(json)))],
  ]
}

export function RulesetsPage() {
  const { season } = useSession()
  const versions = useLoad<RulesetVersion[]>(() => api.listRulesets(season), [season])
  const checklist = useLoad<ChecklistInfo>(() => api.rulesetChecklist(), [])
  const [selected, setSelected] = useState<number | null>(null)
  const [editing, setEditing] = useState<Record<string, unknown> | null>(null)
  const [showWorksheet, setShowWorksheet] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const submit = useAction()
  const list = versions.data ?? []
  const current = list.find((v) => v.id === selected) ?? list[list.length - 1] ?? null
  const approved = list.find((v) => v.status === 'approved')
  const reload = async () => { await versions.reload() }

  return (
    <>
      <Section title={`Season ruleset — ${season}`}>
        <p className="lede">Alliance-selection and playoff rules (P6-M1). Every Phase 6 playoff and selection engine
          reads only the season's <strong>approved</strong> ruleset, never a draft and never another season's rules.
          People enter it from the official manual; a named, qualified reviewer approves it.</p>
        <p>{approved
          ? <>Approved: version {approved.version} by {approved.reviewed_by} · sha256 <Sha value={approved.ruleset_sha256} /></>
          : <strong>No approved ruleset for {season}.</strong>}</p>
        <SuccessNotice message={message} />
        <div className="actions">
          <button type="button" className="secondary" onClick={() => setShowWorksheet(!showWorksheet)}>
            {showWorksheet ? 'Hide the worksheet' : 'Start from a worksheet'}
          </button>
        </div>
        {showWorksheet && <WorksheetPanel season={season} onUse={(p) => { setEditing(p); setShowWorksheet(false) }} />}
        {editing && <DraftEditor initial={editing} onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); setMessage('Draft saved as a new version.'); void reload() }} />}
      </Section>
      <Section title="Versions">
        <LoadState loading={versions.loading} error={versions.error} />
        {versions.data && list.length === 0 && <p className="muted">No ruleset versions for {season}.</p>}
        {list.length > 0 && (
          <table className="grid compact">
            <thead><tr><th>Version</th><th>Status</th><th>sha256</th><th>Author</th><th>Reviewer</th><th /></tr></thead>
            <tbody>
              {list.map((v) => (
                <tr key={v.id} className={v.id === current?.id ? 'selected' : undefined}>
                  <td>v{v.version} (#{v.id})</td><td><StateBadge state={v.status} /></td><td><Sha value={v.ruleset_sha256} /></td>
                  <td>{v.created_by} · <When value={v.created_at} /></td><td>{v.reviewed_by ?? '—'}</td>
                  <td><button type="button" className="link" onClick={() => setSelected(v.id)}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      {current && (
        <Section title={`Version ${current.version} (#${current.id})`}>
          <dl className="facts">
            {summary(current).map(([k, v]) => <div key={k} style={{ display: 'contents' }}><dt>{k}</dt><dd>{v}</dd></div>)}
            <dt>Full sha256</dt><dd><code data-testid="stored-sha">{current.ruleset_sha256}</code></dd>
          </dl>
          <RawJson value={current.ruleset_json} label="Stored ruleset JSON" />
          {current.review_note && <RawJson value={current.review_note} label="Review record" />}
          <ErrorNotice error={submit.error} />
          <WriteGate>
            <div className="actions">
              <button type="button" className="secondary" onClick={() => setEditing(current.ruleset_json)}>Edit as a new draft</button>
              {current.status === 'draft' && (
                <button type="button" disabled={submit.busy}
                  onClick={() => void submit.run(async () => { await api.submitRuleset(current.id); await reload() },
                    'Submitted for review.')}>Submit for review</button>
              )}
            </div>
          </WriteGate>
          <SuccessNotice message={submit.message} />
          {current.status === 'awaiting_review' && checklist.data && (
            <ReviewForm ruleset={current} checklist={checklist.data}
              onDone={(m) => { setMessage(m); void reload() }} />
          )}
        </Section>
      )}
    </>
  )
}
