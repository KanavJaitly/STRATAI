import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { Extraction, PageText, ProcessingState } from '../api/managerTypes'
import type { Manual } from '../api/types'
import {
  ErrorNotice, LoadState, Section, Sha, StateBadge, SuccessNotice, When, WriteGate, useAction, useLoad,
} from '../components/common'
import { DataTable, ValidationBadge } from '../components/seasonUi'
import { checkManualFile } from '../lib/manualChecks'
import { sha256Hex } from '../lib/sha256'
import { formatValue } from '../lib/format'
import { useSession } from '../state/session'

const PROCESSING_TONE: Record<string, string> = {
  succeeded: 'approved', running: 'awaiting_review', failed: 'missing', needs_resolution: 'incomplete',
  not_started: 'draft',
}

function Upload({ season, onUploaded }: { season: number; onUploaded: (manual: Manual) => void }) {
  const { actor } = useSession()
  const [file, setFile] = useState<File | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [localSha, setLocalSha] = useState<string | null>(null)
  const [gameName, setGameName] = useState('')
  const [outcome, setOutcome] = useState<string | null>(null)
  const action = useAction()

  const choose = async (chosen: File | null) => {
    setFile(chosen)
    setOutcome(null)
    setLocalSha(null)
    setProblem(chosen ? await checkManualFile(chosen) : null)
    if (chosen && !(await checkManualFile(chosen))) setLocalSha(await sha256Hex(await chosen.arrayBuffer()))
  }

  const upload = () => action.run(async () => {
    if (!file || problem) throw new Error(problem ?? 'Choose the manual PDF first.')
    const response = await api.uploadManual({ season, game_name: gameName.trim(), filename: file.name,
      uploaded_by: actor }, file)
    if (localSha && response.manual.content_sha256 !== localSha) {
      throw new Error(`The server's checksum ${response.manual.content_sha256} does not match this file's ${localSha}.`)
    }
    await api.startProcessing(response.manual.id, actor) // idempotent: an already-processed manual is not redone
    setOutcome(response.created
      ? `Stored as manual #${response.manual.id}; processing started.`
      : `This exact file is already manual #${response.manual.id}. Nothing was replaced or duplicated.`)
    onUploaded(response.manual)
  })

  return (
    <WriteGate>
      <form className="form-row" onSubmit={(e) => { e.preventDefault(); void upload() }}>
        <label>
          Official manual (PDF, up to 100 MB)
          <input type="file" accept="application/pdf,.pdf" aria-label="Manual PDF"
            onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
        </label>
        <label>
          Game name
          <input value={gameName} onChange={(e) => setGameName(e.target.value)} aria-label="Game name" required />
        </label>
        <button type="submit" disabled={action.busy || !file || Boolean(problem) || !gameName.trim()}>
          Upload and process
        </button>
      </form>
      {problem && <div className="notice notice-error" role="alert">{problem}</div>}
      {localSha && <p className="small">This file's sha256: <code>{localSha}</code></p>}
      <ErrorNotice error={action.error} />
      {outcome && <div className="notice notice-ok" role="status">{outcome}</div>}
    </WriteGate>
  )
}

function Progress({ state }: { state: ProcessingState }) {
  if (state.status !== 'running') return null
  return <div className="progress" aria-label="Processing"><span /></div>
}

function ProcessingPanel({ manual, state, onChange }: { manual: Manual; state: ProcessingState;
  onChange: () => void }) {
  const { actor, season } = useSession()
  const action = useAction()
  const [note, setNote] = useState('')
  const report = state.report
  const lastFailure = [...state.attempts].reverse().find((a) => a.error)
  return (
    <div>
      <dl className="facts">
        <dt>Manual</dt><dd>#{manual.id} · {manual.filename} · {manual.game_name}</dd>
        <dt>Season</dt><dd>{manual.season}</dd>
        <dt>sha256</dt><dd><code>{manual.content_sha256}</code></dd>
        <dt>Size</dt><dd>{(manual.byte_size / 1048576).toFixed(2)} MB</dd>
        <dt>Uploaded</dt><dd>{manual.uploaded_by} · <When value={manual.uploaded_at} /></dd>
        <dt>Processing</dt>
        <dd><StateBadge state={PROCESSING_TONE[state.status]} label={state.status.replaceAll('_', ' ')} />
          <span className="muted small"> · {state.processor_version}</span></dd>
      </dl>
      <Progress state={state} />
      {state.status === 'failed' && lastFailure && (  // why it failed, without expanding the history (D3, 2026-10-12)
        <div className="notice notice-error" role="alert">
          Attempt #{lastFailure.attempt} failed: <strong>{lastFailure.error?.code}</strong>: {lastFailure.error?.message}
        </div>
      )}
      <div className="actions">
        <a href={api.manualFileUrl(manual.id)} target="_blank" rel="noreferrer">Open the original PDF</a>
        {state.retry_allowed && (
          <WriteGate>
            <button type="button" className="secondary" disabled={action.busy}
              onClick={() => void action.run(async () => { await api.startProcessing(manual.id, actor); onChange() },
                'Processing restarted.')}>
              {state.status === 'not_started' ? 'Start processing' : 'Retry processing'}
            </button>
          </WriteGate>
        )}
      </div>
      <ErrorNotice error={action.error} />
      <SuccessNotice message={action.message} />
      {report && (
        <>
          <h3>Report</h3>
          <dl className="facts">
            <dt>Identity</dt>
            <dd>{report.identity.decision} — {report.identity.reason}
              {report.identity.revision && <> · revision {report.identity.revision}</>}
              {report.identity.date && <> · {report.identity.date}</>}</dd>
            <dt>Pages</dt><dd>{report.page_count} ({report.text_pages} with text)</dd>
            <dt>Sections / suggestions</dt><dd>{report.sections} / {report.suggestions}</dd>
            <dt>Extraction sha256</dt><dd><Sha value={report.extraction_sha256} /></dd>
          </dl>
          <p className="notice notice-info small">{report.note}</p>
          {report.warnings.length > 0 && (
            <div className="notice notice-warn">
              <strong>{report.warnings.length} warning(s)</strong>
              <ul>{report.warnings.map((w, i) => <li key={i}>{w.page ? `page ${w.page}: ` : ''}{w.message}</li>)}</ul>
            </div>
          )}
        </>
      )}
      {state.status === 'needs_resolution' && !state.identity_resolution && (
        <div className="review-box">
          <p><strong>The manual's season could not be read from its title pages.</strong> Confirm it is the {season}
            {' '}manual only if you have checked the document itself.</p>
          <WriteGate>
            <label>Note (what you checked)<textarea value={note} onChange={(e) => setNote(e.target.value)}
              aria-label="Resolution note" /></label>
            <button type="button" disabled={action.busy || !note.trim()}
              onClick={() => void action.run(async () => {
                await api.resolveIdentity(manual.id, { season: manual.season, resolved_by: actor, note })
                await api.startProcessing(manual.id, actor)
                onChange()
              }, 'Season confirmed; processing restarted.')}>
              Confirm this is the {manual.season} manual
            </button>
          </WriteGate>
        </div>
      )}
      <details className="raw">
        <summary>Processing attempts ({state.attempts.length})</summary>
        <ul>{state.attempts.map((a, i) => (
          <li key={i}>#{a.attempt} {a.status}{a.requested_by ? ` by ${a.requested_by}` : ''}
            {a.started_at ? ` · started ${new Date(a.started_at).toLocaleString()}` : ''}
            {a.finished_at ? ` · finished ${new Date(a.finished_at).toLocaleString()}` : ''}
            {a.error ? ` · ${a.error.code}: ${a.error.message}` : ''}</li>
        ))}</ul>
      </details>
    </div>
  )
}

function ExtractionView({ manual }: { manual: Manual }) {
  const { data, error, loading } = useLoad<Extraction>(() => api.extraction(manual.id), [manual.id])
  const [tab, setTab] = useState<'sections' | 'topics' | 'suggestions' | 'text'>('suggestions')
  const [page, setPage] = useState(1)
  const [text, setText] = useState<PageText | null>(null)
  const [textError, setTextError] = useState<unknown>(null)
  const show = async (n: number) => {
    setPage(n)
    setTab('text')
    try {
      setText((await api.pages(manual.id, n, n))[0] ?? null)
      setTextError(null)
    } catch (caught) {
      setTextError(caught)
    }
  }
  const pageLink = (n: number) => (
    <span>
      <button type="button" className="link" onClick={() => void show(n)}>p. {n}</button>
      <a className="small" href={`${api.manualFileUrl(manual.id)}#page=${n}`} target="_blank" rel="noreferrer">PDF</a>
    </span>
  )
  if (loading || error || !data) return <LoadState loading={loading} error={error} />
  const tabs = [['suggestions', `Suggestions (${data.suggestions.length})`], ['sections', `Sections (${data.sections.length})`],
    ['topics', 'Topics'], ['text', 'Page text']] as const
  return (
    <div>
      <div className="tabs" role="tablist">
        {tabs.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === 'suggestions' && (
        <>
          <p className="notice notice-warn small">Machine-extracted and unverified. Each value comes with the page and
            the exact text it was read from. Check it against the manual before entering it into the game spec or the
            ruleset; nothing here is entered or approved automatically.</p>
          <DataTable rows={data.suggestions as unknown as Record<string, unknown>[]}
            columns={['rule', 'target', 'value', 'page', 'snippet', 'status']}
            empty="No suggestions were found in this manual."
            render={{ page: (r) => pageLink(r.page as number), value: (r) => formatValue(r.value),
              status: (r) => <ValidationBadge status={r.status} /> }} />
        </>
      )}
      {tab === 'sections' && (
        <DataTable rows={data.sections as unknown as Record<string, unknown>[]} columns={['number', 'title', 'page']}
          empty="No numbered sections were found." render={{ page: (r) => pageLink(r.page as number) }} />
      )}
      {tab === 'topics' && (
        <DataTable rows={Object.entries(data.topics).map(([topic, t]) => ({ topic, mentions: t.mentions,
          top_pages: t.top_pages }))} columns={['topic', 'mentions', 'top_pages']}
          render={{ top_pages: (r) => (r.top_pages as number[]).length
            ? <>{(r.top_pages as number[]).map((n) => <span key={n}>{pageLink(n)} </span>)}</>
            : <span className="muted">not found</span> }} />
      )}
      {tab === 'text' && (
        <div>
          <div className="form-row">
            <label>Page<input type="number" min={1} max={data.page_count} value={page} aria-label="Page number"
              onChange={(e) => setPage(Number(e.target.value))} /></label>
            <button type="button" className="secondary" onClick={() => void show(page)}>Show page</button>
          </div>
          <ErrorNotice error={textError} />
          {text && (
            <>
              <p className="small muted">Page {text.page} · {text.chars} characters · sha256 <Sha value={text.text_sha256} />
                {text.error && <> · error: {text.error}</>}</p>
              <pre className="page-text" data-testid="page-text">{text.text || '(no extractable text on this page)'}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function DependentFeatures({ season }: { season: number }) {
  const { data, error, loading } = useLoad(() => api.readiness(season), [season])
  if (loading || error || !data) return <LoadState loading={loading} error={error} />
  const dependent = data.features.filter((f) => ['game_manual', 'game_analysis', 'season_ruleset', 'score_components']
    .includes(f.key))
  return (
    <>
      <DataTable rows={dependent as unknown as Record<string, unknown>[]} columns={['name', 'available', 'reasons', 'requires_human']}
        render={{ available: (r) => <StateBadge state={r.available ? 'approved' : 'missing'} label={r.available ? 'ready' : 'not yet'} />,
          reasons: (r) => (r.reasons as string[]).join('; ') || '—', requires_human: (r) => (r.requires_human as string) ?? '—' }} />
      <p className="small">
        Next: <Link to="/game">enter the game spec</Link> · <Link to="/rulesets">draft the season ruleset</Link> ·{' '}
        <Link to="/readiness">see every remaining task</Link>
      </p>
    </>
  )
}

export function ManualsPage() {
  const { season } = useSession()
  const manuals = useLoad<Manual[]>(() => api.listManuals(season), [season])
  const [selected, setSelected] = useState<number | null>(null)
  const current = manuals.data?.find((m) => m.id === selected) ?? manuals.data?.[manuals.data.length - 1] ?? null
  const currentId = current?.id ?? null
  const processing = useLoad<ProcessingState | null>(
    () => (currentId === null ? Promise.resolve(null) : api.processingStatus(currentId)), [currentId])
  const state = processing.data
  const stateError = processing.error
  const { reload } = processing
  useEffect(() => { // poll while a run is in progress
    if (state?.status !== 'running') return undefined
    const timer = window.setInterval(() => void reload(), 1500)
    return () => window.clearInterval(timer)
  }, [state?.status, reload])
  const refresh = () => void reload()

  return (
    <>
      <Section title={`Game manual — ${season}`}>
        <p className="lede">Upload the season's official game manual. STRATAI keeps the original unchanged with its
          checksum, then processes it automatically: integrity checks, page text, the season and revision on its title
          pages, a section and topic index, and unverified suggestions with page references. People then enter the
          game spec and the season ruleset from it, and a named reviewer approves them. No step here approves
          anything or runs a model.</p>
        <Upload season={season} onUploaded={(m) => { setSelected(m.id); void manuals.reload() }} />
      </Section>
      <Section title="Uploaded versions">
        <LoadState loading={manuals.loading} error={manuals.error} />
        {manuals.data && manuals.data.length === 0 && <p className="muted">No manual has been uploaded for {season}.</p>}
        {manuals.data && manuals.data.length > 0 && (
          <div className="table-scroll">
            <table className="grid compact">
              <thead><tr><th>#</th><th>File</th><th>Game</th><th>sha256</th><th>Uploaded</th><th /></tr></thead>
              <tbody>
                {manuals.data.map((m) => (
                  <tr key={m.id} className={m.id === current?.id ? 'selected' : undefined}>
                    <td>{m.id}</td><td>{m.filename}</td><td>{m.game_name}</td><td><Sha value={m.content_sha256} /></td>
                    <td>{m.uploaded_by} · <When value={m.uploaded_at} /></td>
                    <td><button type="button" className="link" onClick={() => setSelected(m.id)}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      {current && (
        <Section title={`Processing — manual #${current.id}`}>
          <ErrorNotice error={stateError} />
          {state && state.manual_id === current.id && (
            <ProcessingPanel manual={current} state={state} onChange={refresh} />
          )}
        </Section>
      )}
      {current && state?.status === 'succeeded' && state.manual_id === current.id && (
        <Section title="Extracted structure (review aid)">
          <ExtractionView manual={current} />
        </Section>
      )}
      <Section title="What this manual feeds">
        <DependentFeatures season={season} />
      </Section>
    </>
  )
}
