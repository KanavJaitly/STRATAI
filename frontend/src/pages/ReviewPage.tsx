import { useMemo, useState } from 'react'

import { api } from '../api/client'
import type {
  ActionMapPayload, Artifact, ArtifactKind, CodebookPayload, CodingPayload, DesignExample, KappaStatus, Profile,
} from '../api/types'
import {
  ErrorNotice, LoadState, Section, Sha, StateBadge, SuccessNotice, When, WriteGate, useAction, useLoad,
} from '../components/common'
import { RowsEditor } from '../components/RowsEditor'
import { useSession } from '../state/session'
import { LEVELS } from './profileForm'
import {
  actionMapPayload, codebookPayload, codingPayload, reviewStages, rubricPayload,
  type ArchetypeRow, type FunctionRow,
} from './reviewForms'

const ESTABLISHABLE: ArtifactKind[] = ['codebook', 'consensus_coding', 'action_function_map', 'rubric']

/** Every version of one kind, with sign-off for the kinds a named person establishes. */
function ArtifactHistory({ kind, artifacts, onChanged }: { kind: ArtifactKind; artifacts: Artifact[]; onChanged: () => void }) {
  const { actor } = useSession()
  const [note, setNote] = useState('')
  const action = useAction()
  const rows = artifacts.filter((a) => a.kind === kind)
  if (!rows.length) return <p className="muted small">Nothing submitted yet.</p>
  const canEstablish = ESTABLISHABLE.includes(kind)
  return (
    <>
      <table className="grid compact" data-testid={`history-${kind}`}>
        <thead><tr><th>#</th><th>Author</th><th>Version</th><th>Status</th><th>sha256</th><th>Submitted</th><th>Established</th>{canEstablish && <th />}</tr></thead>
        <tbody>
          {[...rows].reverse().map((a) => (
            <tr key={a.id}>
              <td>{a.id}</td><td>{a.author}</td><td>{a.version}</td><td><StateBadge state={a.status} /></td>
              <td><Sha value={a.payload_sha256} /></td><td><When value={a.created_at} /></td>
              <td>{a.established_by ? <>{a.established_by}, <When value={a.established_at} /></> : '—'}</td>
              {canEstablish && (
                <td>
                  {a.status === 'submitted' && (
                    <WriteGate>
                      <button type="button" className="secondary" disabled={action.busy}
                        onClick={() => void action.run(async () => {
                          await api.establishArtifact(a.id, { established_by: actor, note })
                          onChanged()
                        }, `Established #${a.id}.`)}>
                        Establish
                      </button>
                    </WriteGate>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {canEstablish && rows.some((a) => a.status === 'submitted') && (
        <WriteGate>
          <label className="small">Sign-off note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} aria-label={`${kind} sign-off note`} /></label>
          <p className="muted small">Establishing is your named sign-off as {actor || '—'}. It supersedes any previously established {kind.replaceAll('_', ' ')}.</p>
        </WriteGate>
      )}
      <ErrorNotice error={action.error} />
      <SuccessNotice message={action.message} />
    </>
  )
}

function CodebookEditor({ season, onSaved }: { season: number; onSaved: () => void }) {
  const { actor } = useSession()
  const [version, setVersion] = useState('')
  const [rows, setRows] = useState<FunctionRow[]>([])
  const action = useAction()
  return (
    <WriteGate>
      <form onSubmit={(e) => {
        e.preventDefault()
        void action.run(async () => {
          await api.submitArtifact(season, { kind: 'codebook', author: actor, payload: codebookPayload(version, rows) })
          onSaved()
        }, 'Codebook submitted. It needs a named sign-off before coding can start.')
      }}>
        <label>Codebook version<input value={version} onChange={(e) => setVersion(e.target.value)} aria-label="Codebook version" /></label>
        <RowsEditor<FunctionRow> label="Functions" rows={rows} onChange={setRows} newRow={() => ({ function: '', family: '' })}
          columns={[{ key: 'function', label: 'Function' }, { key: 'family', label: 'Family' }]} />
        <button type="submit" disabled={action.busy}>Submit codebook</button>
        <ErrorNotice error={action.error} />
        <SuccessNotice message={action.message} />
      </form>
    </WriteGate>
  )
}

function CodingGrid({ season, codebook, examples, artifacts, kappa, onSaved }: {
  season: number; codebook: CodebookPayload | null; examples: DesignExample[]; artifacts: Artifact[]
  kappa: KappaStatus | null; onSaved: () => void
}) {
  const { actor } = useSession()
  const [kind, setKind] = useState<'coding' | 'consensus_coding'>('coding')
  const [checked, setChecked] = useState<Record<number, Set<string>>>({})
  const action = useAction()
  if (!codebook) return <p className="notice notice-info">Coding starts once a codebook is established.</p>
  const functions = Object.keys(codebook.functions).sort()
  const consensusAllowed = kappa?.state === 'computed'
  const mine = artifacts.filter((a) => a.kind === kind && a.author === actor && a.status !== 'superseded').at(-1)
  const toggle = (row: number, fn: string) => setChecked((current) => {
    const next = new Set(current[row] ?? [])
    if (next.has(fn)) next.delete(fn)
    else next.add(fn)
    return { ...current, [row]: next }
  })
  const loadMine = () => {
    const labels = (mine?.payload as CodingPayload | undefined)?.labels ?? {}
    setChecked(Object.fromEntries(Object.entries(labels).map(([k, v]) => [Number(k), new Set(v)])))
  }
  return (
    <WriteGate>
      <div className="form-row">
        <label>
          Coding type
          <select value={kind} aria-label="Coding type" onChange={(e) => { setKind(e.target.value as typeof kind); setChecked({}) }}>
            <option value="coding">Independent coding (as {actor || '—'})</option>
            <option value="consensus_coding" disabled={!consensusAllowed}>Consensus-meeting coding{consensusAllowed ? '' : ' (after κ)'}</option>
          </select>
        </label>
        {mine && <button type="button" className="secondary" onClick={loadMine}>Load my last {kind === 'coding' ? 'coding' : 'consensus coding'} (v{mine.version})</button>}
      </div>
      <p className="muted small">
        {kind === 'coding'
          ? 'Code every row independently: do not look at another coder\'s labels. A row may have no function. The rows are a curated reference, not verified data.'
          : 'Record the labels agreed in the consensus meeting held after the independent codings and κ. These, never one coder\'s labels, are served (P5-D13).'}
      </p>
      <div className="table-scroll coding-grid">
        <table className="grid compact">
          <thead>
            <tr><th>Row</th><th>Design (curated_reference_unverified)</th>{functions.map((f) => <th key={f} className="rot">{f}</th>)}</tr>
          </thead>
          <tbody>
            {examples.map((ex) => (
              <tr key={ex.row_id}>
                <td>{ex.row_id}</td>
                <td className="small"><strong>{ex.year} · {ex.team}</strong> {ex.micro_archetype}<div className="muted">{ex.technical_specifications}</div></td>
                {functions.map((f) => (
                  <td key={f} className="center">
                    <input type="checkbox" aria-label={`row ${ex.row_id} ${f}`} checked={checked[ex.row_id]?.has(f) ?? false}
                      onChange={() => toggle(ex.row_id, f)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="button" disabled={action.busy || !examples.length} onClick={() => void action.run(async () => {
        await api.submitArtifact(season, { kind, author: actor,
          payload: codingPayload(examples.map((e) => e.row_id), checked) })
        onSaved()
      }, kind === 'coding' ? 'Coding submitted.' : 'Consensus coding submitted; it needs a named sign-off.')}>
        Submit {kind === 'coding' ? 'independent coding' : 'consensus coding'} ({examples.length} rows)
      </button>
      <ErrorNotice error={action.error} />
      <SuccessNotice message={action.message} />
    </WriteGate>
  )
}

function KappaView({ kappa }: { kappa: KappaStatus | null }) {
  if (!kappa) return null
  if (kappa.state !== 'computed') return <p><StateBadge state={kappa.state} /> {kappa.needed}</p>
  return (
    <div data-testid="kappa">
      <p>
        Coders {kappa.coders.join(' and ')} over {kappa.rows} rows. Pooled κ{' '}
        <strong>{kappa.pooled_kappa === null ? 'undefined' : kappa.pooled_kappa.toFixed(3)}</strong> (gate 0.6):
        labels overall <StateBadge state={kappa.status.overall} />
      </p>
      <table className="grid compact">
        <thead><tr><th>Function</th><th>κ</th><th>Labels</th></tr></thead>
        <tbody>
          {Object.entries(kappa.per_function_kappa).map(([fn, k]) => (
            <tr key={fn}><td>{fn}</td><td>{k === null ? 'undefined' : k.toFixed(3)}</td><td><StateBadge state={kappa.status.functions[fn]} /></td></tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">A function whose own κ is below 0.6 (or undefined) is served provisional even when the pooled κ passes.</p>
    </div>
  )
}

function ActionMapEditor({ season, codebook, actionTypes, onSaved }: {
  season: number; codebook: CodebookPayload | null; actionTypes: string[]; onSaved: () => void
}) {
  const { actor } = useSession()
  const [version, setVersion] = useState('')
  const [rows, setRows] = useState<{ type: string; functions: Set<string> }[]>([])
  const action = useAction()
  if (!codebook) return <p className="notice notice-info">The action map is authored against an established codebook.</p>
  const functions = Object.keys(codebook.functions).sort()
  const update = (i: number, patch: Partial<{ type: string; functions: Set<string> }>) =>
    setRows((r) => r.map((row, j) => (j === i ? { ...row, ...patch } : row)))
  return (
    <WriteGate>
      <form onSubmit={(e) => {
        e.preventDefault()
        void action.run(async () => {
          const payload: ActionMapPayload = actionMapPayload(version, Object.fromEntries(rows.map((r) => [r.type, r.functions])))
          await api.submitArtifact(season, { kind: 'action_function_map', author: actor, payload })
          onSaved()
        }, 'Action map submitted; it needs a named sign-off.')
      }}>
        <label>Map version<input value={version} onChange={(e) => setVersion(e.target.value)} aria-label="Map version" /></label>
        <datalist id="action-types">{actionTypes.map((t) => <option key={t} value={t} />)}</datalist>
        {rows.map((row, i) => (
          <fieldset key={i} className="map-row">
            <legend>Action type {i + 1}</legend>
            <input value={row.type} list="action-types" aria-label={`Action type ${i + 1}`} onChange={(e) => update(i, { type: e.target.value })} />
            {functions.map((f) => (
              <label key={f} className="inline">
                <input type="checkbox" checked={row.functions.has(f)} aria-label={`action type ${i + 1} ${f}`} onChange={() => {
                  const next = new Set(row.functions)
                  if (next.has(f)) next.delete(f)
                  else next.add(f)
                  update(i, { functions: next })
                }} /> {f}
              </label>
            ))}
            <button type="button" className="link danger" onClick={() => setRows((r) => r.filter((_, j) => j !== i))}>remove</button>
          </fieldset>
        ))}
        <div className="actions">
          <button type="button" className="secondary" onClick={() => setRows((r) => [...r, { type: '', functions: new Set() }])}>Add action type</button>
          <button type="submit" disabled={action.busy}>Submit action map</button>
        </div>
        <ErrorNotice error={action.error} />
        <SuccessNotice message={action.message} />
      </form>
    </WriteGate>
  )
}

const LEVEL_OPTIONS = LEVELS.map((l) => String(l.value))

function RubricEditor({ season, onSaved }: { season: number; onSaved: () => void }) {
  const { actor } = useSession()
  const [version, setVersion] = useState('')
  const [rows, setRows] = useState<ArchetypeRow[]>([])
  const action = useAction()
  return (
    <WriteGate>
      <form onSubmit={(e) => {
        e.preventDefault()
        void action.run(async () => {
          await api.submitArtifact(season, { kind: 'rubric', author: actor, payload: rubricPayload(version, rows) })
          onSaved()
        }, 'Rubric submitted; it needs a named sign-off.')
      }}>
        <label>Rubric version<input value={version} onChange={(e) => setVersion(e.target.value)} aria-label="Rubric version" /></label>
        <RowsEditor<ArchetypeRow> label="Archetypes" rows={rows} onChange={setRows}
          newRow={() => ({ archetype: '', tier: '', priority: '', min_budget_usd: '', manufacturing: '', programming: '', mentoring: '', achievable_features: '' })}
          columns={[
            { key: 'archetype', label: 'Archetype' }, { key: 'tier', label: 'Tier', type: 'number', width: '4em' },
            { key: 'priority', label: 'Priority', type: 'number', width: '4em' },
            { key: 'min_budget_usd', label: 'Min budget', type: 'number', width: '6em' },
            { key: 'manufacturing', label: 'Min mfg', type: 'select', options: LEVEL_OPTIONS },
            { key: 'programming', label: 'Min prog', type: 'select', options: LEVEL_OPTIONS },
            { key: 'mentoring', label: 'Min mentor', type: 'select', options: LEVEL_OPTIONS },
            { key: 'achievable_features', label: 'Features (comma-separated)' },
          ]} />
        <p className="muted small">Higher tier = more demanding; lower priority is preferred among feasible candidates. The rubric is human-authored and is not fit to outcomes.</p>
        <button type="submit" disabled={action.busy}>Submit rubric</button>
        <ErrorNotice error={action.error} />
        <SuccessNotice message={action.message} />
      </form>
    </WriteGate>
  )
}

function MentorReviewForm({ season, profiles, onSaved }: { season: number; profiles: Profile[]; onSaved: () => void }) {
  const { actor } = useSession()
  const [reviewedAt, setReviewedAt] = useState('')
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [notes, setNotes] = useState('')
  const action = useAction()
  return (
    <WriteGate>
      <form onSubmit={(e) => {
        e.preventDefault()
        void action.run(async () => {
          if (!reviewedAt) throw new Error('Enter when the review took place.')
          await api.submitArtifact(season, { kind: 'mentor_review', author: actor, payload: {
            reviewed_at: new Date(reviewedAt).toISOString(), profiles_reviewed: [...chosen].sort(), notes } })
          onSaved()
        }, 'Mentor review recorded.')
      }}>
        <p className="small">Recorded as the review of mentor <strong>{actor || '—'}</strong>.</p>
        <label>Reviewed at<input type="datetime-local" value={reviewedAt} onChange={(e) => setReviewedAt(e.target.value)} aria-label="Reviewed at" /></label>
        <fieldset>
          <legend>Profiles reviewed</legend>
          {profiles.length === 0 && <p className="muted small">No active profiles.</p>}
          {profiles.map((p) => (
            <label key={p.profile_key} className="inline">
              <input type="checkbox" checked={chosen.has(p.profile_key)} onChange={() => setChosen((c) => {
                const next = new Set(c)
                if (next.has(p.profile_key)) next.delete(p.profile_key)
                else next.add(p.profile_key)
                return next
              })} /> {p.profile_key}
            </label>
          ))}
        </fieldset>
        <label>Review notes<textarea value={notes} onChange={(e) => setNotes(e.target.value)} aria-label="Review notes" /></label>
        <button type="submit" disabled={action.busy}>Record mentor review</button>
        <ErrorNotice error={action.error} />
        <SuccessNotice message={action.message} />
      </form>
    </WriteGate>
  )
}

export function ReviewPage() {
  const { season } = useSession()
  const artifacts = useLoad(() => api.listArtifacts(season), [season])
  const kappa = useLoad(() => api.kappa(season), [season])
  const examples = useLoad(() => api.designExamples(), [])
  const specs = useLoad(() => api.listSpecs(season), [season])
  const profiles = useLoad(() => api.listProfiles(false), [])
  const reload = () => { void artifacts.reload(); void kappa.reload() }
  const all = artifacts.data ?? []
  const codebook = (all.filter((a) => a.kind === 'codebook' && a.status === 'established').at(-1)?.payload ?? null) as CodebookPayload | null
  const actionTypes = useMemo(() => {
    const latest = specs.data?.at(-1)?.spec_json.scoring_actions ?? []
    return [...new Set(latest.map((a) => a.action_type).filter(Boolean))].sort()
  }, [specs.data])
  const stages = reviewStages(all, kappa.data)

  return (
    <>
      <Section title={`Human review · ${season}`}>
        <p className="lede">
          DM1's human artifacts. Each is entered by a named person; codebooks, consensus codings, action maps and
          rubrics become <em>established</em> only by a named person's sign-off. Nothing here marks DM1 complete.
        </p>
        <LoadState loading={artifacts.loading && !artifacts.data} error={artifacts.error} />
        <ol className="stage-list" aria-label="Review stages">
          {stages.map((s) => (
            <li key={s.key} data-testid={`stage-${s.key}`}><span>{s.title}</span> <StateBadge state={s.state} /> <span className="muted small">{s.detail}</span></li>
          ))}
        </ol>
      </Section>

      <Section title="1 · Codebook">
        <ArtifactHistory kind="codebook" artifacts={all} onChanged={reload} />
        <CodebookEditor season={season} onSaved={reload} />
      </Section>

      <Section title="2 · Independent codings and 4 · consensus coding">
        <LoadState loading={examples.loading && !examples.data} error={examples.error} />
        <CodingGrid season={season} codebook={codebook} examples={examples.data ?? []} artifacts={all} kappa={kappa.data} onSaved={reload} />
        <h3>Independent codings</h3>
        <ArtifactHistory kind="coding" artifacts={all} onChanged={reload} />
        <h3>Consensus codings</h3>
        <ArtifactHistory kind="consensus_coding" artifacts={all} onChanged={reload} />
      </Section>

      <Section title="3 · Codebook agreement (κ)">
        <LoadState loading={kappa.loading && !kappa.data} error={kappa.error} />
        <KappaView kappa={kappa.data} />
      </Section>

      <Section title="5 · Action → function map">
        <ArtifactHistory kind="action_function_map" artifacts={all} onChanged={reload} />
        <ActionMapEditor season={season} codebook={codebook} actionTypes={actionTypes} onSaved={reload} />
      </Section>

      <Section title="6 · Feasibility rubric">
        <ArtifactHistory kind="rubric" artifacts={all} onChanged={reload} />
        <RubricEditor season={season} onSaved={reload} />
      </Section>

      <Section title="7 · Mentor review">
        <ArtifactHistory kind="mentor_review" artifacts={all} onChanged={reload} />
        <MentorReviewForm season={season} profiles={profiles.data ?? []} onSaved={reload} />
      </Section>
    </>
  )
}
