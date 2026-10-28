import { useMemo, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { dashboardApi, type DraftState } from '../../api/dashboard'
import type { AllianceSynergyResponse, CandidatesResponse, FactorOut, PickListResponse } from '../../api/generated'
import { useResource } from '../../components/useResource'
import { AsOfControl } from '../asOf'
import { PageHeader, TeamChip } from '../common'
import { Absent, ActionStatus, EpaSourceNote, OddsView, RefusalNotice, ResourceView, ValidationBadge, When } from '../display'
import { useOnDemand } from '../../components/useOnDemand'
import { useAsOf } from '../asOfParams'
import { FACTORS, formatNumber, type FactorKey } from '../labels'
import { seasonOf, teamPath } from '../routing'

function parseTeams(value: string): number[] {
  return value.split(/[\s,]+/).map(Number).filter((n) => Number.isInteger(n) && n > 0)
}

function FactorCell({ factor, digits }: { factor: FactorOut; digits: number }) {
  return (
    <span className="factor">
      {factor.value === null ? <Absent reason={(factor.validation.reasons ?? [])[0] ?? null} />
        : <>{formatNumber(factor.value, digits)}{factor.n !== null && <span className="muted small"> (n = {factor.n})</span>}</>}
      {factor.validation.status !== 'descriptive' && <>{' '}<ValidationBadge validation={factor.validation} compact /></>}
    </span>
  )
}

export function AlliancePage() {
  const eventKey = useParams().eventKey ?? ''
  const [params, setParams] = useSearchParams()
  const [asOf] = useAsOf()
  const configuration = parseTeams(params.get('config') ?? '')
  const validConfig = configuration.length === 3 && new Set(configuration).size === 3
  const candidates = useResource(
    (s) => dashboardApi.candidates(eventKey, asOf, validConfig ? configuration : null, s),
    `candidates:${eventKey}:${asOf}:${validConfig ? configuration.join(',') : ''}`)
  const season = seasonOf(eventKey)
  const [configDraft, setConfigDraft] = useState(configuration.join(', '))
  const applyConfig = (event: FormEvent) => {
    event.preventDefault()
    const next = new URLSearchParams(params)
    const teams = parseTeams(configDraft)
    if (teams.length) next.set('config', teams.join(','))
    else next.delete('config')
    setParams(next)
  }

  return (
    <>
      <PageHeader title="Alliance selection"
        crumbs={[{ to: season ? `/?season=${season}` : '/', label: season ? `${season} events` : 'Events' },
          { to: `/events/${encodeURIComponent(eventKey)}`, label: eventKey }]}
        subtitle={<>Candidate profiles and the pick list for <code>{eventKey}</code>.</>} />
      <section className="card" aria-labelledby="candidates-heading">
        <h2 id="candidates-heading">Candidate profiles</h2>
        <AsOfControl defaultNote="Default: the event's selection moment (or now, while it is still ahead)." />
        <form className="inline-form" onSubmit={applyConfig} aria-label="Alliance configuration">
          <label className="inline">Three-team configuration (for synergy and role compatibility)
            <input value={configDraft} onChange={(e) => setConfigDraft(e.target.value)} placeholder="e.g. 11, 1923, 56" />
          </label>
          <button type="submit" className="secondary">Apply</button>
          <span role="status" className="small">{configuration.length > 0 && !validConfig
            && <span className="notice-warn">A configuration is exactly three different teams.</span>}</span>
        </form>
        <ResourceView resource={candidates} what="candidate profiles" loadingText="Building every team's profile (a few seconds)…">
          {(data) => <CandidatesTable data={data} />}
        </ResourceView>
      </section>
      <PickListSection eventKey={eventKey} />
      <SynergySection key={asOf ?? 'default'} eventKey={eventKey} asOf={asOf} />
    </>
  )
}

function CandidatesTable({ data }: { data: CandidatesResponse }) {
  const [sortKey, setSortKey] = useState<FactorKey | 'team_number'>('team_number')
  const rows = useMemo(() => [...data.candidates].sort((a, b) => {
    if (sortKey === 'team_number') return a.team_number - b.team_number
    const av = a[sortKey].value
    const bv = b[sortKey].value
    if (av === null && bv === null) return a.team_number - b.team_number
    if (av === null) return 1 // absent values sort last, never as zero
    if (bv === null) return -1
    return bv - av || a.team_number - b.team_number
  }), [data.candidates, sortKey])
  return (
    <>
      <p className="small">As of <When value={data.as_of} /> ({data.as_of_source.replaceAll('_', ' ')})
        {data.configuration && <> · configuration {data.configuration.join(', ')}</>}.</p>
      <label className="inline">Sort by
        <select value={sortKey} onChange={(e) => setSortKey(e.target.value as FactorKey | 'team_number')}>
          <option value="team_number">Team number</option>
          {FACTORS.map((f) => <option key={f.key} value={f.key}>{f.label} (highest first)</option>)}
        </select>
      </label>
      <div className="table-scroll">
        <table className="grid compact candidates">
          <caption className="visually-hidden">Candidate factors, {rows.length} teams</caption>
          <thead><tr><th scope="col">Team</th>{FACTORS.map((f) => <th scope="col" key={f.key}>{f.label}</th>)}</tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.team_number}>
                <th scope="row"><Link to={teamPath(data.event_key, c.team_number)}>{c.team_number}</Link></th>
                {FACTORS.map((f) => <td key={f.key}><FactorCell factor={c[f.key]} digits={f.digits} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted">Values without a status badge are descriptive; any other status is shown in the cell. Values are as the engine reports them: absent values are never imputed. Reliability is an
        estimate: the share of scheduled matches with a recorded result. Synergy and role compatibility apply only to a three-team configuration.</p>
      <EpaSourceNote epa={data.epa} />
    </>
  )
}

function PickListSection({ eventKey }: { eventKey: string }) {
  const [count, setCount] = useState(8)
  const [seed, setSeed] = useState(1)
  const [alliances, setAlliances] = useState<string[]>(() => Array(8).fill(''))
  const [declined, setDeclined] = useState('')
  const [turns, setTurns] = useState(0)
  const pick = useOnDemand<PickListResponse>()
  const resize = (n: number) => {
    setCount(n)
    setAlliances((prev) => Array.from({ length: n }, (_, i) => prev[i] ?? ''))
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (pick.busy) return // aria-disabled while busy: the guard, not the browser, blocks a second run
    const draft: DraftState = { seed, alliances: alliances.map(parseTeams), declined: parseTeams(declined), turns_taken: turns }
    pick.run((signal) => dashboardApi.pickList(eventKey, draft, signal))
  }
  return (
    <section className="card" aria-labelledby="picklist-heading">
      <h2 id="picklist-heading">Pick list</h2>
      <p className="small">Enter the draft so far. The engine ranks every available pick for the seed whose turn it is, by
        P(the alliance wins the event), from the bracket simulator over the predicted field. It runs only with an
        approved season ruleset and passed playoff-model gates; otherwise it returns the real reason it cannot.</p>
      <form onSubmit={submit} aria-label="Draft state">
        <div className="form-row">
          <label>Alliances <input type="number" min={2} max={16} value={count} onChange={(e) => resize(Math.max(2, Math.min(16, Number(e.target.value) || 2)))} /></label>
          <label>Seed to pick for <input type="number" min={1} max={count} value={seed} onChange={(e) => setSeed(Number(e.target.value) || 1)} /></label>
          <label>Picks made so far <input type="number" min={0} value={turns} onChange={(e) => setTurns(Math.max(0, Number(e.target.value) || 0))} /></label>
        </div>
        <div className="alliance-inputs">
          {alliances.map((value, i) => (
            <label key={i} className="inline">Alliance {i + 1}
              <input value={value} placeholder="captain first, e.g. 11, 56" onChange={(e) => {
                const next = [...alliances]; next[i] = e.target.value; setAlliances(next)
              }} />
            </label>
          ))}
        </div>
        <label>Declined teams <input value={declined} onChange={(e) => setDeclined(e.target.value)} placeholder="e.g. 222" /></label>
        <button type="submit" aria-disabled={pick.busy || undefined}>{pick.busy ? 'Ranking picks…' : 'Rank picks'}</button>
      </form>
      <ActionStatus busy={pick.busy} done={pick.result !== null} failed={pick.error != null}
        busyText="Ranking picks…" doneText="Pick list ready." failedText="The pick list was refused or failed." />
      {pick.error != null && <RefusalNotice error={pick.error} what="Pick list" />}
      {pick.result && <PickListView data={pick.result} />}
    </section>
  )
}

export function PickListView({ data }: { data: PickListResponse }) {
  return (
    <div className="picklist">
      <h3>Picks for seed {data.seed}</h3>
      <p className="small">Label: <ValidationBadge validation={{ status: data.probability_status }} compact /></p>
      <p className="small">At the selection moment <When value={data.as_of} />. Probabilities are display strings, with their
        validation scope on each value.</p>
      <div className="table-scroll">
        <table className="grid compact">
          <caption className="visually-hidden">Ranked picks</caption>
          <thead><tr><th scope="col">Pick</th><th scope="col">Predicted alliance</th><th scope="col">Win event</th>
            <th scope="col">Reach finals</th><th scope="col">Versus the next pick</th></tr></thead>
          <tbody>
            {data.ranked.map((p) => (
              <tr key={p.team_number}>
                <th scope="row"><TeamChip team={p.team_number} eventKey={data.event_key} /></th>
                <td>{p.configuration.join(', ')}</td>
                <td><OddsView odds={p.win_event} /></td>
                <td><OddsView odds={p.reach_finals} /></td>
                <td className="small">{p.vs_next_label
                  ? <>win event: {p.vs_next_label}; reach finals: {p.vs_next_reach_finals_label ?? '—'}</>
                  : <Absent reason={p.vs_next_reason} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Alternative alliance configurations</h3>
      {data.alternatives.length === 0 ? <p className="muted">None.</p> : (
        <ol className="alternatives">
          {data.alternatives.map((field, i) => (
            <li key={i}>
              <span>{field.alliances.map((a, seedIndex) => `#${seedIndex + 1}: ${a.join('-')}`).join(' · ')}</span>
              <span className="small"> — win event <OddsView odds={field.win_event} />; reach finals <OddsView odds={field.reach_finals} /></span>
            </li>
          ))}
        </ol>
      )}
      {data.alternatives_note && <p className="small muted">{data.alternatives_note}</p>}
      <ul className="small muted">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      <dl className="facts small">
        <dt>Ruleset</dt><dd><code title={data.provenance.ruleset_sha256}>{data.provenance.ruleset_sha256.slice(0, 12)}…</code>
          {data.provenance.ruleset_variant && ` (variant ${data.provenance.ruleset_variant})`}</dd>
        <dt>Ordering</dt><dd>{data.provenance.ordering_policy}</dd>
        <dt>Fields evaluated</dt><dd>{data.evaluated_fields}</dd>
        <dt>Playoff models</dt><dd>Selection model <code>{data.models.px1_sha256.slice(0, 12)}…</code>, playoff calibrator <code>{data.models.px2_calibrator_sha256.slice(0, 12)}…</code></dd>
      </dl>
      <EpaSourceNote epa={data.epa} />
    </div>
  )
}

function SynergySection({ eventKey, asOf }: { eventKey: string; asOf: string | null }) {
  const [teams, setTeams] = useState('')
  const synergy = useOnDemand<AllianceSynergyResponse>()
  const parsed = parseTeams(teams)
  const valid = parsed.length === 3 && new Set(parsed).size === 3
  return (
    <section className="card" aria-labelledby="synergy-heading">
      <h2 id="synergy-heading">Alliance synergy</h2>
      <form className="inline-form" aria-label="Synergy teams" onSubmit={(e) => {
        e.preventDefault()
        if (valid && !synergy.busy) synergy.run((signal) => dashboardApi.allianceSynergy({ event_key: eventKey, team_numbers: parsed }, asOf, signal))
      }}>
        <label className="inline">Three teams <input value={teams} onChange={(e) => { setTeams(e.target.value); synergy.reset() }} placeholder="e.g. 11, 1923, 56" /></label>
        <button type="submit" className="secondary" disabled={!valid} aria-disabled={synergy.busy || undefined}>Score synergy</button>
      </form>
      <ActionStatus busy={synergy.busy} done={synergy.result !== null} failed={synergy.error != null}
        busyText="Scoring synergy…" doneText="Synergy scored." failedText="The synergy score was refused or failed." />
      {synergy.error != null && <RefusalNotice error={synergy.error} what="Synergy" />}
      {synergy.result && <><p className="small">Teams {synergy.result.team_numbers.join(', ')} as of <When value={synergy.result.as_of} />.</p>
        <SynergyView data={synergy.result} status={synergy.result.validation_status} />
        <EpaSourceNote epa={synergy.result.epa} /></>}
    </section>
  )
}

export function SynergyView({ data, status }: { data: { overall_score: number | null; role_fit_term: number | null;
  role_fit_axes_used?: string[]; scoring_distribution_term: number | null; scoring_distribution_axes_used?: string[];
  defense_feeding_coverage_term: number | null; defense_feeding_coverage_present_count: number; confidence: number };
  status: string }) {
  const term = (value: number | null) => (value === null ? <Absent reason="inputs absent" /> : formatNumber(value, 3))
  return (
    <dl className="facts">
      <dt>Overall</dt><dd>{term(data.overall_score)} <ValidationBadge validation={{ status }} compact /></dd>
      <dt>Role fit</dt><dd>{term(data.role_fit_term)} <span className="muted small">{(data.role_fit_axes_used ?? []).join(', ')}</span></dd>
      <dt>Scoring distribution</dt><dd>{term(data.scoring_distribution_term)} <span className="muted small">{(data.scoring_distribution_axes_used ?? []).join(', ')}</span></dd>
      <dt>Defense/feeding coverage</dt><dd>{term(data.defense_feeding_coverage_term)} <span className="muted small">({data.defense_feeding_coverage_present_count} of 6 scouting values present)</span></dd>
      <dt>Confidence</dt><dd>{formatNumber(data.confidence, 2)} <span className="muted small">(share of each term's possible evidence that is present)</span></dd>
    </dl>
  )
}
