// Coach writes (P8-M4 (d), P8-Q8): store a coach strategy or a coach observation.
// - The write token and the name come from the session (memory only; the name is a label, not an identity).
// - Writes are gated (WriteGate). While one is in flight the button is aria-disabled (it keeps focus) and a
//   synchronous guard ignores further clicks, so a double click cannot submit twice.
// - The outcome is announced through a status region that is always rendered (a region inserted together with its
//   message is often not read).
// - Nothing is retried automatically. The server's stored result, or its refusal, is shown as returned.

import { useRef, useState, type FormEvent } from 'react'

import { ApiRequestError } from '../api/client'
import { dashboardApi } from '../api/dashboard'
import type { CoachObservationStored, CoachStrategyStored, Strategy } from '../api/generated'
import { WriteGate } from '../components/common'
import { useSession } from '../state/session'
import { RefusalNotice, When } from './display'
import { StrategyTable } from './strategy'
import { localInputToIso } from './asOfParams'

/** A write whose fate is unknown (the connection failed after sending) must not be repeated blindly. */
function WriteError({ error, what }: { error: unknown; what: string }) {
  // network_error/timeout: the fate is unknown. malformed_response is a 2xx: the write was accepted.
  const unknownOutcome = error instanceof ApiRequestError && (error.code === 'network_error' || error.code === 'timeout'
    || error.code === 'malformed_response')
  const accepted = error instanceof ApiRequestError && error.code === 'malformed_response'
  return (
    <>
      <RefusalNotice error={error} what={what} />
      {unknownOutcome && <p className="notice notice-warn">{accepted
        ? 'The server accepted the write, but its reply could not be read, so it has been stored.'
        : 'The write may have been stored before the connection failed.'} Check (e.g. reload the match) before
        submitting again: a second submission stores a second record.</p>}
    </>
  )
}

function useWrite<T>() {
  const [state, setState] = useState<{ busy: boolean; result: T | null; error: unknown }>({ busy: false, result: null, error: null })
  const inFlight = useRef(false) // synchronous: a second click in the same frame cannot submit twice
  const submit = async (write: () => Promise<T>) => {
    if (inFlight.current) return
    inFlight.current = true
    setState({ busy: true, result: null, error: null })
    try {
      setState({ busy: false, result: await write(), error: null })
    } catch (error) {
      setState({ busy: false, result: null, error })
    } finally {
      inFlight.current = false
    }
  }
  return { ...state, submit }
}

/**
 * Stays mounted while the coach edits (a remount would lose a write still in flight and its outcome). The outcome
 * always describes the strategy that was sent; when the editor has changed since, that is said explicitly.
 */
export function SaveCoachStrategy({ eventKey, matchKey, strategy, valid = true }: { eventKey: string; matchKey: string;
  strategy: Strategy; valid?: boolean }) {
  const { actor } = useSession()
  const write = useWrite<CoachStrategyStored>()
  const [sent, setSent] = useState<string | null>(null)
  const current = JSON.stringify(strategy)
  const save = () => {
    if (!valid || write.busy) return // a click while in flight must not overwrite what was sent
    setSent(current)
    void write.submit(() => dashboardApi.coachStrategy({ event_key: eventKey, match_key: matchKey, author: actor.trim(),
      strategy }))
  }
  const edited = sent !== null && sent !== current
  return (
    <div className="coach-write">
      <h3>Save the coach strategy</h3>
      <StrategyTable strategy={strategy} caption="Strategy to save" />
      <WriteGate>
        <button type="button" disabled={!valid && !write.busy} aria-disabled={write.busy || undefined} onClick={save}>
          {write.busy ? 'Saving…' : 'Save as a coach strategy'}
        </button>
      </WriteGate>
      {!valid && <p className="small muted">Fix the strategy above before saving it.</p>}
      <div role="status" className="live-status">
      {write.error != null && <WriteError error={write.error} what="Saving the strategy" />}
      {write.result && (
        <p className="notice notice-ok">Stored by {write.result.author} (<code title={write.result.strategy_sha256}>
          {write.result.strategy_sha256.slice(0, 12)}…</code>) at <When value={write.result.created_at} />.</p>
      )}
      {(write.busy || write.result || write.error != null) && edited && (
        <p className="notice notice-info">This outcome is for the strategy as it was when you pressed Save; your edits
          since then are not saved.</p>
      )}
      </div>
    </div>
  )
}

export function RecordObservation({ eventKey, teams }: { eventKey: string; teams: number[] }) {
  const { actor } = useSession()
  const write = useWrite<CoachObservationStored>()
  const [team, setTeam] = useState(teams[0] ?? 0)
  const [kind, setKind] = useState<'robot_unavailable' | 'component_unavailable'>('robot_unavailable')
  const [component, setComponent] = useState<'auto' | 'teleop' | 'endgame'>('auto')
  const [observedAt, setObservedAt] = useState('')
  const observedIso = localInputToIso(observedAt)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!observedIso) return
    void write.submit(() => dashboardApi.coachObservation({ event_key: eventKey, team_number: team, kind,
      ...(kind === 'component_unavailable' ? { component } : {}), observed_at: observedIso, observer: actor.trim() }))
  }
  return (
    <form className="coach-write" onSubmit={submit} aria-labelledby="observation-heading">
      <h3 id="observation-heading">Record a coach observation</h3>
      <p className="small muted">An observation counts for a match only once it was both observed and stored before
        that match's moment, so a back-dated entry never changes an earlier evaluation.</p>
      <div className="form-row">
        <label>Team
          <select value={team} onChange={(e) => setTeam(Number(e.target.value))}>
            {teams.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label>Observation
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="robot_unavailable">Robot unavailable</option>
            <option value="component_unavailable">Mechanism unavailable for one phase</option>
          </select>
        </label>
        {kind === 'component_unavailable' && (
          <label>Phase
            <select value={component} onChange={(e) => setComponent(e.target.value as typeof component)}>
              <option value="auto">auto</option><option value="teleop">teleop</option><option value="endgame">endgame</option>
            </select>
          </label>
        )}
        <label>Observed at
          <input type="datetime-local" value={observedAt} onChange={(e) => setObservedAt(e.target.value)} required />
        </label>
      </div>
      <WriteGate>
        <button type="submit" disabled={!observedIso} aria-disabled={write.busy || undefined}>{write.busy ? 'Recording…' : 'Record observation'}</button>
      </WriteGate>
      <div role="status" className="live-status">
      {write.error != null && <WriteError error={write.error} what="Recording the observation" />}
      {write.result && (
        <p className="notice notice-ok">Recorded: team {write.result.observation.team_number},{' '}
          {write.result.observation.kind.replaceAll('_', ' ')}{write.result.observation.component ? ` (${write.result.observation.component})` : ''},
          observed <When value={write.result.observation.observed_at} /> by {write.result.observation.observer}.</p>
      )}
      </div>
    </form>
  )
}
