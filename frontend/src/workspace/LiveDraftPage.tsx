// Phase 11: live alliance selection (docs/phase11.md). The team's private draft record for one event: the live board,
// the controls to record each real action as it happens (administrators, or a role granted alliance_selection_record),
// the team's primary and backup picks recalculated after every action, and the full history with undo and correction.
//
// Everything is read from and written to the API (src/auth/api.ts liveDraft). The record on the server is the single
// source of truth: this page never computes availability or recommendations itself. Other devices' changes arrive by
// polling every 2 s while the page is visible. A recommendation that reflects an older record version, or whose
// refresh failed, stays visible but is marked stale with its reason; it is never shown as current.

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiRequestError } from '../api/http'
import { ErrorNotice, LoadState, SuccessNotice, useAction, useLoad, When } from '../components/common'
import { PageHeader } from '../dashboard/common'
import { teamPath } from '../dashboard/routing'
import {
  liveDraft, newActionId, type DraftActionType, type DraftEffectiveAction, type DraftRecommendations, type DraftRecord,
  type ManualDraftRules, type RecommendedTeam,
} from '../auth/api'
import { useAuth } from '../auth/authState'
import { EventChooser } from './EventChooser'
import { seasonOf, useEventName } from './events'

const POLL_MS = 2000
const RULE_REFUSALS = new Set(['wrong_turn', 'team_on_alliance', 'team_declined', 'team_not_in_pool', 'wrong_captain',
  'captain_not_named', 'captain_already_named', 'captain_rule_not_established', 'no_eligible_captain',
  'alliance_full', 'captain_not_pickable', 'draft_complete', 'draft_incomplete', 'backups_not_used', 'already_backup',
  'unknown_alliance'])

const REASON_LABEL: Record<string, string> = { captain: 'captain', picked: 'picked', declined: 'declined',
  backup: 'backup robot', projected_captain: 'will captain a lower alliance' }
// Withheld for a reason that is the record's real state, not a failed recalculation: shown as the current answer.
const STATE_WITHHOLDS = new Set(['team_not_selecting', 'no_remaining_turn', 'not_configured'])

export function LiveDraftPage({ pollMs = POLL_MS }: { pollMs?: number }) {
  const [params, setParams] = useSearchParams()
  const eventKey = params.get('event') ?? ''
  const eventName = useEventName(eventKey)
  const { session } = useAuth()
  const choose = (key: string) => setParams(key ? { event: key } : {})
  return (
    <div className="live-draft">
      <PageHeader title="Live alliance selection"
        subtitle={`Team ${session.workspace?.team_number ?? ''} · record each pick as it happens`}
        crumbs={[{ to: '/drive-team', label: 'Drive team dashboard' }]} />
      <section className="card">
        <EventChooser key={seasonOf(eventKey) ?? 'none'} value={eventKey} onChange={choose} />
      </section>
      {!eventKey ? <p className="notice notice-info">Choose the event where alliance selection is happening.</p>
        : <EventDraft key={eventKey} eventKey={eventKey} eventName={eventName} pollMs={pollMs} />}
    </div>
  )
}

function EventDraft({ eventKey, eventName, pollMs }: { eventKey: string; eventName: string; pollMs: number }) {
  const list = useLoad(() => liveDraft.list(eventKey), [eventKey])
  const existing = list.data?.[0]
  if (list.loading && !list.data) return <LoadState loading error={null} />
  if (list.error) return <ErrorNotice error={list.error} />
  if (!existing) return <StartDraft eventKey={eventKey} eventName={eventName} onStarted={() => void list.reload()} />
  return <DraftBoard recordId={existing.record_id} eventKey={eventKey} pollMs={pollMs} />
}

// --- starting a record ------------------------------------------------------------------------------------------

const EMPTY_RULES: ManualDraftRules = { n_alliances: 8, picks_per_alliance: 2, declined_team_may_be_picked_later: false,
  declined_team_may_become_captain: null, captain_may_accept_higher_alliance: true, backup_robots: false }

function StartDraft({ eventKey, eventName, onStarted }: { eventKey: string; eventName: string; onStarted: () => void }) {
  const { can } = useAuth()
  const action = useAction()
  const [needsRules, setNeedsRules] = useState<string | null>(null)
  const [rules, setRules] = useState<ManualDraftRules>(EMPTY_RULES)
  if (!can('alliance_selection_record')) {
    return <p className="notice notice-info">No live draft has been started for {eventName}. An administrator (or a
      member they allow to record) starts it when alliance selection begins.</p>
  }
  const start = async (event?: FormEvent) => {
    event?.preventDefault()
    const ok = await action.run(async () => {
      try {
        await liveDraft.start({ event_key: eventKey, manual_rules: needsRules ? rules : null })
      } catch (caught) {
        if (caught instanceof ApiRequestError && caught.code === 'rules_required') setNeedsRules(caught.message)
        throw caught
      }
    })
    if (ok) onStarted()
  }
  const refusal = action.error instanceof ApiRequestError ? action.error : null
  const flag = (name: keyof ManualDraftRules, label: string) => (
    <label className="checkbox"><input type="checkbox" checked={rules[name] === true}
      onChange={(e) => setRules({ ...rules, [name]: e.target.checked })} /> {label}</label>)
  return (
    <section className="card">
      <h2>Start live alliance selection at {eventName}</h2>
      <p className="muted small">The record starts from the event&apos;s final qualification ranks, its roster and its
        approved ruleset. Anything missing is listed, and you can still record every action.</p>
      {needsRules && (
        <form onSubmit={(e) => void start(e)} aria-label="The event's rules">
          <p className="notice notice-warn">{needsRules} Enter them as the event announces them; they are stored as
            entered by you.</p>
          <div className="form-grid">
            <label>Alliances <input type="number" min={2} max={16} value={rules.n_alliances}
              onChange={(e) => setRules({ ...rules, n_alliances: Number(e.target.value) })} /></label>
            <label>Picks per alliance (after the captain) <input type="number" min={1} max={4}
              value={rules.picks_per_alliance}
              onChange={(e) => setRules({ ...rules, picks_per_alliance: Number(e.target.value) })} /></label>
          </div>
          {flag('declined_team_may_be_picked_later', 'A team that declines may still be picked later')}
          <label>A team that declines may become a captain{' '}
            <select value={String(rules.declined_team_may_become_captain)} onChange={(e) => setRules({ ...rules,
              declined_team_may_become_captain: e.target.value === 'null' ? null : e.target.value === 'true' })}>
              <option value="null">not stated by the event</option><option value="true">yes</option>
              <option value="false">no</option>
            </select></label>
          {flag('captain_may_accept_higher_alliance', 'A captain may accept an invitation from a higher alliance')}
          {flag('backup_robots', 'The event uses backup robots')}
          <div className="actions"><button type="submit" disabled={action.busy}>Start with these rules</button></div>
        </form>
      )}
      {!needsRules && (
        <div className="actions">
          <button type="button" className="big-button" disabled={action.busy} onClick={() => void start()}>
            Start live alliance selection</button>
        </div>
      )}
      {refusal?.code !== 'rules_required' && <ErrorNotice error={action.error} />}
    </section>
  )
}

// --- the live board -------------------------------------------------------------------------------------------------

function usePolledDraft(recordId: number, pollMs: number) {
  const [draft, setDraftState] = useState<DraftRecord | null>(null)
  const [error, setError] = useState<unknown>(null)
  // A response for an older record version (a poll that was in flight while an action was recorded) never replaces
  // a newer board.
  const setDraft = useCallback((next: DraftRecord) => setDraftState((current) =>
    current && current.record_id === next.record_id && current.record_seq > next.record_seq ? current : next), [])
  const refresh = useCallback(async () => {
    try {
      setDraft(await liveDraft.get(recordId))
      setError(null)
    } catch (caught) {
      setError(caught)
    }
  }, [recordId, setDraft])
  useEffect(() => {
    // Polling the server (an external system): the first read at once, then every pollMs while the page is visible.
    const first = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void refresh()
    }, pollMs)
    return () => { window.clearTimeout(first); window.clearInterval(timer) }
  }, [refresh, pollMs])
  return { draft, setDraft, error, refresh }
}

interface RecState { data: DraftRecommendations | null; failure: string | null; failedAt: string | null }

/** A withheld answer that is a failed recalculation (an input missing, the record needing review), not the record's
 * real state: the last current recommendation stays visible, marked stale with this reason (§5). */
function withheldAsFailure(next: DraftRecommendations): string | null {
  return next.status === 'withheld' && next.withheld && !STATE_WITHHOLDS.has(next.withheld.code)
    ? `${next.withheld.code}: ${next.withheld.message}` : null
}

function useRecommendations(recordId: number, seq: number | undefined) {
  const [state, setState] = useState<RecState>({ data: null, failure: null, failedAt: null })
  useEffect(() => {
    if (seq === undefined) return
    let live = true
    liveDraft.recommendations(recordId).then(
      (data) => {
        if (!live) return
        const failure = withheldAsFailure(data)
        setState((previous) => failure && previous.data?.status === 'current'
          ? { ...previous, failure, failedAt: new Date().toISOString() } : { data, failure: null, failedAt: null })
      },
      (caught: unknown) => {
        if (!live) return
        const reason = caught instanceof ApiRequestError ? `${caught.code}: ${caught.message}` : String(caught)
        setState((previous) => ({ ...previous, failure: reason, failedAt: new Date().toISOString() }))
      })
    return () => { live = false }
  }, [recordId, seq])
  return state
}

function DraftBoard({ recordId, eventKey, pollMs }: { recordId: number; eventKey: string; pollMs: number }) {
  const { draft, setDraft, error, refresh } = usePolledDraft(recordId, pollMs)
  const recs = useRecommendations(recordId, draft?.record_seq)
  if (!draft) return error ? <ErrorNotice error={error} /> : <LoadState loading error={null} />
  const recordable = draft.can_record && draft.status === 'open'
  return (
    <>
      {error !== null && <p className="notice notice-warn" role="status">Could not refresh the board; showing the
        version from record #{draft.record_seq}. <ErrorDetail error={error} /></p>}
      <SetupNotes draft={draft} />
      <TurnBanner draft={draft} />
      <div className="live-draft-grid">
        <section className="card" aria-label="Alliances">
          <h2>Alliances</h2>
          <AllianceTable draft={draft} eventKey={eventKey} />
        </section>
        <RecommendationPanel draft={draft} recs={recs} />
      </div>
      {recordable && <Recorder draft={draft} onChange={setDraft}
        recommendation={recs.data && recs.failure === null && recs.data.record_seq === draft.record_seq
          && recs.data.status === 'current' ? recs.data : null} />}
      {!draft.can_record && <p className="muted small">You can watch the board. Recording is for administrators, and
        for members an administrator allows to record.</p>}
      <PoolLists draft={draft} eventKey={eventKey} />
      <History draft={draft} onChange={setDraft} recordable={recordable} />
      <RecordControls draft={draft} onChange={(next) => { setDraft(next); void refresh() }} />
    </>
  )
}

function ErrorDetail({ error }: { error: unknown }) {
  return <span className="muted small">{error instanceof ApiRequestError ? `${error.code}: ${error.message}`
    : String(error)}</span>
}

function SetupNotes({ draft }: { draft: DraftRecord }) {
  const setup = draft.setup
  if (!setup) return null
  const rules = setup.rules
  return (
    <section className="card">
      <p className="small">
        Rules: {rules.n_alliances} alliances, {rules.picks_per_alliance} pick{rules.picks_per_alliance === 1 ? '' : 's'}
        {' '}each, serpentine · {rules.source === 'approved_ruleset' ? 'from the approved ruleset'
          : 'entered at the event (manual)'}
        {rules.backup_robots ? ' · backup robots used' : ''} · record #{draft.record_seq}
        {draft.status === 'closed' && <strong> · closed</strong>}
      </p>
      {setup.missing.length > 0 && (
        <div className="notice notice-warn"><strong>Missing:</strong>
          <ul>{setup.missing.map((m) => <li key={m}>{m}</li>)}</ul>
          Recording works; checks that need the missing data are marked unchecked.</div>
      )}
      {draft.flags.length > 0 && (
        <div className="notice notice-error" role="alert"><strong>Needs review:</strong> these recorded actions became
          invalid after a correction or a setup change. Correct them in the history.
          <ul>{draft.flags.map((f) => <li key={f.action_id}>{f.message ?? f.code} ({f.status.replace('_', ' ')})</li>)}</ul>
        </div>
      )}
    </section>
  )
}

function TurnBanner({ draft }: { draft: DraftRecord }) {
  if (draft.complete) return <p className="notice notice-ok turn-banner" role="status">Every pick is recorded.</p>
  if (!draft.turn) return null
  const { turn } = draft
  return (
    <p className="notice notice-info turn-banner" role="status" aria-live="polite">
      Round {turn.round} · <strong>Alliance {turn.seed}</strong>{' '}
      {turn.captain_named ? 'is picking' : turn.expected_captain !== null
        ? `— confirm its captain (the rules name team ${turn.expected_captain})`
        : `— record its captain${turn.expected_captain_reason ? ` (${turn.expected_captain_reason})` : ''}`}
    </p>
  )
}

function AllianceTable({ draft, eventKey }: { draft: DraftRecord; eventKey: string }) {
  const team = (t: number) => <Link to={teamPath(eventKey, t)}>{t}</Link>
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th scope="col">Alliance</th><th scope="col">Captain</th><th scope="col">Picks</th></tr></thead>
        <tbody>
          {draft.alliances.map((a) => (
            <tr key={a.seed} className={draft.turn?.seed === a.seed ? 'row-current' : undefined}>
              <th scope="row">{a.seed}</th>
              <td>{a.captain !== null ? team(a.captain) : a.projected_captain !== null
                ? <span className="muted" title="Projected from the rules and ranks; not yet recorded">
                  {a.projected_captain} (projected)</span> : <span className="muted">—</span>}</td>
              <td>{a.picks.length ? a.picks.map((t, i) => <span key={t}>{i ? ', ' : ''}{team(t)}</span>)
                : <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- recommendations ------------------------------------------------------------------------------------------------

function RecommendationPanel({ draft, recs }: { draft: DraftRecord; recs: RecState }) {
  const data = recs.data
  const stale = data !== null && (data.record_seq !== draft.record_seq || recs.failure !== null)
  return (
    <section className="card" aria-label="Your picks">
      <h2>Your picks</h2>
      {!data && !recs.failure && <p className="muted">Calculating…</p>}
      {!data && recs.failure && <p className="notice notice-error">Could not calculate: {recs.failure}</p>}
      {data && stale && (
        <p className="notice notice-warn" role="status"><strong>Stale</strong>: these reflect record #{data.record_seq}
          , not #{draft.record_seq}{recs.failure ? ` — refresh failed at ${new Date(recs.failedAt ?? '').toLocaleTimeString()}: ${recs.failure}` : ' — updating…'}.</p>
      )}
      {data?.status === 'withheld' && data.withheld && (
        <p className="notice notice-info">No recommendation: {data.withheld.message}.</p>)}
      {data?.status === 'current' && (
        <>
          <p className="small">
            {data.source === 'engine_p6_m7' ? 'From the alliance selection engine' : 'Fallback rule P11-FB1: '
              + 'available teams in team-strength order'} for alliance {data.seed}
            {data.selecting_as === 'projected_captain' ? ' (your projected alliance)' : ''} ·{' '}
            <span className="badge badge-warn">{data.validation?.status.replaceAll('_', ' ')}</span>
            {data.turns_before ? ` · ${data.turns_before} pick${data.turns_before === 1 ? '' : 's'} before your turn` : ' · your turn'}
          </p>
          {data.primary && <RecommendedRow label="Primary" team={data.primary} primary />}
          {data.backups.length > 0 && (
            <ol className="backup-list" aria-label="Backup picks">
              {data.backups.map((t) => <li key={t.team_number}><RecommendedRow label="Backup" team={t} /></li>)}
            </ol>)}
          {data.movement.length > 0 && <ul className="movement small">{data.movement.map((m) => <li key={m}>{m}</li>)}</ul>}
          {data.source === 'fallback_p11_fb1' && (
            <details className="small"><summary>Why this is not validated</summary>
              <ul>{data.validation?.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              {data.unranked_available.length > 0 && <p>Not in the ordering (never recommended):{' '}
                {data.unranked_available.join(', ')}</p>}
            </details>)}
        </>
      )}
      {data && <p className="muted small">Calculated <When value={data.computed_at} /> for record #{data.record_seq}</p>}
    </section>
  )
}

function RecommendedRow({ label, team, primary = false }: { label: string; team: RecommendedTeam; primary?: boolean }) {
  return (
    <p className={primary ? 'primary-pick' : undefined}>
      <span className="muted small">{label}</span> <strong>{team.team_number}</strong>
      {team.ordering_position !== null && <span className="muted small"> · strength order #{team.ordering_position}</span>}
      {team.win_event?.display && <span className="small"> · P(win event) {team.win_event.display}</span>}
    </p>
  )
}

// --- recording ----------------------------------------------------------------------------------------------------

interface Pending { type: DraftActionType; seed: number | null; team: number; refusal?: ApiRequestError }

function Recorder({ draft, onChange, recommendation }: { draft: DraftRecord; onChange: (d: DraftRecord) => void;
  recommendation: DraftRecommendations | null }) {
  const action = useAction()
  const [selected, setSelected] = useState<number | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [reason, setReason] = useState('')
  const turn = draft.turn
  const backupsOpen = draft.complete && draft.setup?.rules.backup_robots

  // The same action sent again (after a lost response) carries the same id, so the server records it once.
  const attempt = useRef<{ key: string; id: string } | null>(null)
  const submit = async (p: Pending, override?: string) => {
    let refusal: ApiRequestError | undefined
    const key = `${draft.record_seq}:${p.type}:${p.seed}:${p.team}:${override ?? ''}`
    if (attempt.current?.key !== key) attempt.current = { key, id: newActionId() }
    const actionId = attempt.current.id
    const ok = await action.run(async () => {
      try {
        onChange(await liveDraft.record(draft.record_id, { type: p.type, seed: p.seed, team_number: p.team,
          override_reason: override ?? null, action_id: actionId }))
      } catch (caught) {
        if (caught instanceof ApiRequestError && RULE_REFUSALS.has(caught.code)) refusal = caught
        throw caught
      }
    })
    if (ok) { attempt.current = null; setSelected(null); setPending(null); setReason('') }
    else if (refusal) setPending({ ...p, refusal })
  }

  const available = draft.available
  return (
    <section className="card recorder" aria-label="Record an action">
      <h2>Record</h2>
      {turn && !turn.captain_named && (
        <div className="actions">
          {turn.expected_captain !== null && (
            <button type="button" className="big-button" disabled={action.busy}
              onClick={() => void submit({ type: 'captain', seed: turn.seed, team: turn.expected_captain! })}>
              Confirm alliance {turn.seed} captain: {turn.expected_captain}</button>)}
          {selected !== null && (
            <button type="button" className="big-button button-secondary" disabled={action.busy}
              onClick={() => void submit({ type: 'captain', seed: turn.seed, team: selected })}>
              Record {selected} as alliance {turn.seed}&apos;s captain</button>)}
        </div>
      )}
      {(turn || backupsOpen) && (
        <>
          <p className="muted small">Tap a team, then what happened.</p>
          <div className="team-grid" role="group" aria-label="Available teams">
            {available.map((t) => (
              <button key={t.team_number} type="button" aria-pressed={selected === t.team_number}
                className={`team-tile${selected === t.team_number ? ' selected' : ''}${
                  recommendation?.primary?.team_number === t.team_number ? ' recommended' : ''}`}
                onClick={() => { setSelected(t.team_number); setPending(null); action.clear() }}>
                <strong>{t.team_number}</strong>
                <span className="small">{t.rank !== null ? `rank ${t.rank}` : 'unranked'}
                  {t.projected_captain_of !== null ? ` · proj. captain ${t.projected_captain_of}` : ''}</span>
              </button>
            ))}
          </div>
          <UnlistedTeam onChoose={(team) => { setSelected(team); setPending(null); action.clear() }}
            hint={available.length === 0 ? 'The event\u2019s roster and ranks are not stored yet, so no team is listed: '
              + 'enter the team number.' : 'Not listed? Enter the team number.'} />
          {selected !== null && turn && turn.captain_named && (
            <div className="actions">
              <button type="button" className="big-button" disabled={action.busy}
                onClick={() => void submit({ type: 'pick', seed: turn.seed, team: selected })}>
                Alliance {turn.seed} picks {selected}</button>
              <button type="button" className="big-button button-secondary" disabled={action.busy}
                onClick={() => void submit({ type: 'decline', seed: turn.seed, team: selected })}>
                {selected} declines alliance {turn.seed}</button>
            </div>
          )}
          {selected !== null && backupsOpen && (
            <div className="actions">
              <button type="button" className="big-button" disabled={action.busy}
                onClick={() => void submit({ type: 'backup', seed: null, team: selected })}>
                {selected} is a backup robot</button>
            </div>
          )}
        </>
      )}
      {pending?.refusal ? (
        <form className="notice notice-error" aria-label="Override"
          onSubmit={(e) => { e.preventDefault(); void submit(pending, reason) }}>
          <p role="alert"><strong>Refused:</strong> {pending.refusal.message}</p>
          <label>If the room really did this, say why and record it as an override:
            <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} /></label>
          <div className="actions">
            <button type="submit" disabled={!reason.trim() || action.busy}>Record with override</button>
            <button type="button" className="button-secondary" onClick={() => { setPending(null); action.clear() }}>
              Cancel</button>
          </div>
        </form>
      ) : <ErrorNotice error={action.error} />}
    </section>
  )
}

function UnlistedTeam({ onChoose, hint }: { onChoose: (team: number) => void; hint: string }) {
  const [value, setValue] = useState('')
  const team = Number(value)
  return (
    <form className="inline-form" aria-label="Enter a team number"
      onSubmit={(e) => { e.preventDefault(); if (Number.isInteger(team) && team > 0) onChoose(team) }}>
      <label className="small">{hint} <input inputMode="numeric" value={value} size={6}
        onChange={(e) => setValue(e.target.value.replace(/\D/g, ''))} /></label>
      <button type="submit" className="button-secondary" disabled={!(team > 0)}>Choose</button>
    </form>
  )
}

function PoolLists({ draft, eventKey }: { draft: DraftRecord; eventKey: string }) {
  return (
    <section className="card">
      <h2>Unavailable teams</h2>
      {draft.unavailable.length === 0 ? <p className="muted">None yet.</p> : (
        <ul className="chips" aria-label="Unavailable teams">
          {draft.unavailable.map((u) => (
            <li key={u.team_number} className="chip"><Link to={teamPath(eventKey, u.team_number)}>{u.team_number}</Link>
              {' '}{REASON_LABEL[u.reason]}{u.seed !== null ? ` (alliance ${u.seed})` : ''}</li>
          ))}
        </ul>
      )}
      <p className="muted small">{draft.available.length} team{draft.available.length === 1 ? '' : 's'} still available.</p>
    </section>
  )
}

// --- history, undo and correction ------------------------------------------------------------------------------------

function History({ draft, onChange, recordable }: { draft: DraftRecord; onChange: (d: DraftRecord) => void;
  recordable: boolean }) {
  const action = useAction()
  const [correcting, setCorrecting] = useState<DraftEffectiveAction | null>(null)
  const last = draft.effective[draft.effective.length - 1]
  const effective = useMemo(() => new Map(draft.effective.map((e) => [e.action_id, e])), [draft.effective])
  return (
    <section className="card" aria-label="History">
      <h2>History</h2>
      {recordable && last && (
        <div className="actions">
          <button type="button" className="button-secondary" disabled={action.busy}
            onClick={() => void action.run(async () => onChange(await liveDraft.undo(draft.record_id, last.action_id)),
              'Undone. It stays in the history.')}>Undo last: {last.summary}</button>
        </div>
      )}
      <SuccessNotice message={action.message} />
      <ErrorNotice error={action.error} />
      {correcting && <Correction draft={draft} target={correcting} onDone={(next) => { setCorrecting(null);
        if (next) onChange(next) }} />}
      <ol className="history-list">
        {[...draft.history].reverse().map((h) => {
          const live = effective.get(h.action_id)
          return (
            <li key={h.action_id} className={h.in_effect ? undefined : 'superseded'}>
              <span className="muted small">#{h.seq}</span> {h.summary}
              {live && live.status !== 'accepted' && <span className="badge badge-warn"> {live.status.replace('_', ' ')}</span>}
              {h.override_reason && <span className="small"> · override: {h.override_reason}</span>}
              {!h.in_effect && <span className="muted small"> · superseded</span>}
              <span className="muted small"> · {h.recorded_by} · <When value={h.recorded_at} /></span>
              {recordable && live && (
                <button type="button" className="link-button small" onClick={() => setCorrecting(live)}>Correct</button>)}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function Correction({ draft, target, onDone }: { draft: DraftRecord; target: DraftEffectiveAction;
  onDone: (next: DraftRecord | null) => void }) {
  const action = useAction()
  const [type, setType] = useState<DraftActionType | 'none'>(target.type)
  const [seed, setSeed] = useState<number | null>(target.seed)
  const [team, setTeam] = useState<number>(target.team_number)
  const [reason, setReason] = useState('')
  const candidates = useMemo(() => {
    const teams = new Set<number>([target.team_number, ...draft.available.map((t) => t.team_number),
      ...draft.unavailable.map((t) => t.team_number)])
    return [...teams].sort((a, b) => a - b)
  }, [draft, target])
  const first = useRef<HTMLSelectElement>(null)
  useEffect(() => { first.current?.focus() }, [])
  const save = (event: FormEvent) => {
    event.preventDefault()
    void action.run(async () => onDone(await liveDraft.correct(draft.record_id, {
      target_action_id: target.action_id, override_reason: reason.trim() || null,
      replacement: type === 'none' ? null : { type, seed: type === 'backup' ? seed : seed ?? 1, team_number: team } })))
  }
  return (
    <form className="card correction" onSubmit={save} aria-label="Correct an action">
      <h3>Correct: {target.summary}</h3>
      <p className="muted small">The original stays in the history. Later actions are re-checked, and any that no longer
        fit is flagged for review.</p>
      <div className="form-grid">
        <label>What happened <select ref={first} value={type}
          onChange={(e) => setType(e.target.value as DraftActionType | 'none')}>
          <option value="captain">captain named</option><option value="pick">pick</option>
          <option value="decline">decline</option><option value="backup">backup robot</option>
          <option value="none">it did not happen</option></select></label>
        {type !== 'none' && <label>Alliance <select value={seed ?? ''} onChange={(e) =>
          setSeed(e.target.value ? Number(e.target.value) : null)}>
          {type === 'backup' && <option value="">none</option>}
          {draft.alliances.map((a) => <option key={a.seed} value={a.seed}>{a.seed}</option>)}</select></label>}
        {type !== 'none' && <label>Team <select value={team} onChange={(e) => setTeam(Number(e.target.value))}>
          {candidates.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>}
        <label>Override reason (only if the rules refuse it) <input value={reason} maxLength={500}
          onChange={(e) => setReason(e.target.value)} /></label>
      </div>
      <div className="actions">
        <button type="submit" disabled={action.busy}>Save correction</button>
        <button type="button" className="button-secondary" onClick={() => onDone(null)}>Cancel</button>
      </div>
      <ErrorNotice error={action.error} />
    </form>
  )
}

function RecordControls({ draft, onChange }: { draft: DraftRecord; onChange: (d: DraftRecord) => void }) {
  const action = useAction()
  if (!draft.can_record) return null
  return (
    <section className="card">
      <div className="actions">
        {draft.status === 'open' ? (
          <>
            <button type="button" className="button-secondary" disabled={action.busy}
              onClick={() => void action.run(async () => onChange(await liveDraft.refreshSetup(draft.record_id)),
                'Setup refreshed from the event’s current data.')}>Refresh ranks and rules</button>
            <button type="button" className="button-secondary" disabled={action.busy}
              onClick={() => void action.run(async () => onChange(await liveDraft.close(draft.record_id)),
                'Closed. Reopen it to make changes.')}>Close the record</button>
          </>
        ) : (
          <button type="button" disabled={action.busy}
            onClick={() => void action.run(async () => onChange(await liveDraft.reopen(draft.record_id)),
              'Reopened.')}>Reopen the record</button>
        )}
      </div>
      <SuccessNotice message={action.message} />
      <ErrorNotice error={action.error} />
    </section>
  )
}
