// P11A (experimental): the expected-score plan beside the Phase 11 recommendation. It is a separate panel, closed by
// default, and fetched only while open. It never changes "Your picks" (P11-Q1). Every value is an expected alliance
// score in points under the season scoring configuration, not a chance of winning; nothing here is validated or
// calibrated, and the panel says so.

import { useEffect, useState } from 'react'

import { ApiRequestError } from '../api/http'
import { liveDraft, type AlliancePlanResponse, type P11ACard, type P11APlan } from '../auth/api'

const WITHHELD_TEXT: Record<string, string> = {
  scoring_config_not_approved: 'No season scoring configuration has been reviewed and approved, so alliance scores '
    + 'cannot be computed.',
  game_spec_not_approved: 'The season GameSpec is not approved.',
  snapshot_unavailable: 'No event snapshot has been exported for this event.',
  snapshot_invalid: 'The event snapshot failed its integrity or leakage check.',
  estimator_fit_unreliable: 'The robot-contribution fit is unreliable for this event, so no plan is shown.',
}

function usePlan(recordId: number, seq: number, open: boolean) {
  const [plan, setPlan] = useState<AlliancePlanResponse | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  useEffect(() => {
    if (!open) return
    let live = true
    liveDraft.plan(recordId).then(
      (data) => { if (live) { setPlan(data); setFailure(null) } },
      (caught: unknown) => {
        if (live) setFailure(caught instanceof ApiRequestError ? `${caught.code}: ${caught.message}` : String(caught))
      })
    return () => { live = false }
  }, [recordId, seq, open])
  return { plan, failure }
}

export function ExpectedScorePlan({ recordId, seq }: { recordId: number; seq: number }) {
  const [open, setOpen] = useState(false)
  const { plan, failure } = usePlan(recordId, seq, open)
  return (
    <section className="card" aria-label="Expected-score plan (experimental)">
      <details onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary><strong>Expected-score plan</strong> <span className="badge badge-wait">experimental</span>{' '}
          <span className="muted small">separate from Your picks</span></summary>
        {failure !== null && <p className="notice notice-warn" role="status">Could not load the plan. {failure}</p>}
        {open && plan === null && failure === null && <p className="muted">Loading…</p>}
        {plan !== null && <PlanBody response={plan} stale={plan.record_seq !== seq} />}
      </details>
    </section>
  )
}

function PlanBody({ response, stale }: { response: AlliancePlanResponse; stale: boolean }) {
  if (response.status === 'withheld' || response.plan === null) {
    const w = response.withheld
    return (
      <p className="notice notice-info" role="status">
        No plan: {w ? WITHHELD_TEXT[w.code] ?? w.message : 'withheld'} <span className="muted small">({w?.code})</span>
      </p>
    )
  }
  const plan = response.plan
  return (
    <>
      <p className="small">
        Ranked by <strong>expected alliance score (points)</strong>, not by chance of winning · not validated ·
        intervals not calibrated · availability before your turn not modelled · record #{response.record_seq}
        {stale && <strong> · out of date</strong>}
      </p>
      {plan.mode === 'non_captain' ? <Destinations plan={plan} /> : <Cards plan={plan} />}
      <details>
        <summary className="small">Known limitations</summary>
        <ul className="small">{plan.known_limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      </details>
    </>
  )
}

function Cards({ plan }: { plan: P11APlan }) {
  const cards = plan.cards ?? []
  const title = plan.stage === 'first_pick' ? 'First pick (with the best second pick for each)'
    : plan.stage === 'fourth_member' ? 'Fourth member (best three-robot lineup)' : 'Next pick'
  return (
    <div className="table-scroll">
      <table>
        <caption className="small">{title}</caption>
        <thead><tr><th scope="col">#</th><th scope="col">Team</th><th scope="col">Expected score</th>
          <th scope="col">Estimation range (80%, not calibrated)</th>
          {plan.stage === 'first_pick' && <th scope="col">Then pick</th>}</tr></thead>
        <tbody>{cards.map((c) => <CardRow key={c.team_number} card={c} firstPick={plan.stage === 'first_pick'} />)}
        </tbody>
      </table>
      {(plan.comparisons ?? []).length > 0 && (
        <p className="muted small">Adjacent teams are not declared different: no comparison threshold is approved, so
          every comparison is unresolved.</p>
      )}
    </div>
  )
}

function CardRow({ card, firstPick }: { card: P11ACard; firstPick: boolean }) {
  const seconds = (card.conditional_seconds ?? []).slice(0, 3).map((s) => s.team_number).join(', ')
  return (
    <tr>
      <td>{card.rank}</td>
      <th scope="row" title={card.statements.join('\n')}>{card.team_number}</th>
      <td>{card.expected_alliance_score.toFixed(1)} pts</td>
      <td>{card.estimation_interval_80[0].toFixed(1)}–{card.estimation_interval_80[1].toFixed(1)}</td>
      {firstPick && <td>{seconds || '—'}</td>}
    </tr>
  )
}

function Destinations({ plan }: { plan: P11APlan }) {
  return (
    <>
      <p className="small">{plan.note} Invitation likelihood is not estimated.</p>
      <ul className="small">
        {(plan.destinations ?? []).map((d) => (
          <li key={d.seed}>Alliance {d.seed} ({d.members.join(', ')}):{' '}
            {d.expected_alliance_score != null ? `${d.expected_alliance_score.toFixed(1)} pts expected`
              : `not computed (${d.reason ?? 'withheld'})`}</li>
        ))}
      </ul>
    </>
  )
}
