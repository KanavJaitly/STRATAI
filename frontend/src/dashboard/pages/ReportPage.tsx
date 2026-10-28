import { useEffect, useLayoutEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { dashboardApi, type Side } from '../../api/dashboard'
import type { AssessmentOut, NotProduced, PreMatchReportResponse, PreMatchTeam, RobotPlan, StrategySide } from '../../api/generated'
import { useResource } from '../../components/useResource'
import { AllianceTeams } from '../common'
import { Absent, CalibratedProbabilityView, EpaSourceNote, MeasureValue, OddsView, ResourceView, ValidationBadge, When } from '../display'
import { BriefingPanel } from '../briefing'
import { StrategyTable } from '../strategy'
import { SynergyView } from './AlliancePage'
import { StrengthView } from './TeamPage'
import { useAsOf } from '../asOfParams'
import { reasonText } from '../labels'
import { eventOfMatch, matchPath } from '../routing'

/**
 * P8-M6: the shareable pre-match report (GET /matches/{m}/pre-match-report). Everything comes from that one response,
 * taken at one moment. The six items no engine produces are explicit absences with their meaning (P7-Q12, P8-Q6):
 * nothing is derived, guessed or written here. The URL (match, `as_of`, our alliance) reproduces the report exactly.
 */
export function ReportPage() {
  const matchKey = useParams().matchKey ?? ''
  const [asOf] = useAsOf()
  const [params, setParams] = useSearchParams()
  const ours: Side = params.get('side') === 'blue' ? 'blue' : 'red'
  const report = useResource((s) => dashboardApi.preMatchReport(matchKey, asOf, s), `report:${matchKey}:${asOf}`)
  useEffect(() => { document.title = `Pre-match report · ${matchKey} · STRATAI` }, [matchKey])
  const setOurs = (side: Side) => { const next = new URLSearchParams(params); next.set('side', side); setParams(next) }
  return (
    <article className="report">
      <ResourceView resource={report} what="pre-match report" loadingText="Assembling the pre-match report (a few seconds)…">
        {(data) => <Report data={data} ours={ours} setOurs={setOurs} asOf={asOf} />}
      </ResourceView>
    </article>
  )
}

function ShareBar() {
  const [copied, setCopied] = useState<'idle' | 'ok' | 'failed'>('idle')
  const url = window.location.href
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied('ok')
    } catch {
      setCopied('failed')
    }
  }
  return (
    <div className="share-bar no-print">
      <button type="button" className="secondary" onClick={() => void copy()}>Copy link</button>
      <button type="button" className="secondary" onClick={() => window.print()}>Print</button>
      <span role="status" className="small muted">
        {copied === 'ok' ? 'Link copied.' : copied === 'failed' ? <>Copy this link: <code>{url}</code></> : 'The link reproduces this report, at this moment.'}
      </span>
    </div>
  )
}

function NotProducedItem({ title, item }: { title: string; item: NotProduced }) {
  return (
    <div className="not-produced">
      <h4>{title}</h4>
      <p><span className="badge badge-old">not produced by any engine</span></p>
      <p className="small muted">{item.semantics}</p>
    </div>
  )
}

function AbsentPart({ code, reason }: { code: string | null; reason: string | null }) {
  return <p className="notice notice-info absent-part"><strong>Not available</strong>{code && <> ({reasonText(code)})</>}{reason ? `: ${reason}` : ''}</p>
}

/** Printing shows every collapsed section: each closed <details> in the report opens for the print and closes after. */
// A layout effect: the listener is attached during the commit that renders the report, so there is no moment when
// the report is on screen but printing would not open its sections. Repeated beforeprint events add to the list
// rather than replacing it, so afterprint always restores every section it opened.
function useOpenDetailsForPrint() {
  useLayoutEffect(() => {
    let opened: HTMLDetailsElement[] = []
    const before = () => {
      const closed = [...document.querySelectorAll<HTMLDetailsElement>('.report details:not([open])')]
      closed.forEach((d) => { d.open = true })
      opened = [...opened, ...closed]
    }
    const after = () => { opened.forEach((d) => { d.open = false }); opened = [] }
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => { window.removeEventListener('beforeprint', before); window.removeEventListener('afterprint', after) }
  }, [])
}

/** The strategy the report shows for one side: the engine's recommendation, else its baseline. */
function planFor(side: StrategySide | undefined): { plan: AssessmentOut | null; label: string } {
  if (side?.recommended) return { plan: side.recommended, label: 'AI recommendation' }
  if (side?.baseline) return { plan: side.baseline, label: 'baseline' }
  return { plan: null, label: '' }
}

function roleOf(robot: RobotPlan | undefined): string {
  if (!robot) return ''
  const role = robot.role ?? 'scoring'
  if (role === 'defense') return `Defense on ${robot.defense_target}`
  if (role === 'feeding') return `Feeding ${robot.feed_target}`
  return `Scoring (${(robot.components ?? ['auto', 'teleop', 'endgame']).join(', ') || 'none'})`
}

function AllianceSection({ data, side, title, perRobotItem, allianceItems }: { data: PreMatchReportResponse; side: Side;
  title: string; perRobotItem: { title: string; item: NotProduced }; allianceItems: { title: string; item: NotProduced }[] }) {
  const teams = data.teams.filter((t) => t.alliance === side)
  const strategySide = data.strategy.sides.find((s) => s.side === side)
  const { plan, label } = planFor(strategySide)
  const synergy = data.synergy.find((s) => s.alliance === side)
  // When every EPA cell is absent for one reason, the reason is stated once instead of in each cell.
  const epaCells = teams.flatMap((t) => [t.strength.epa.total, t.strength.epa.auto, t.strength.epa.teleop, t.strength.epa.endgame])
  const sharedEpaReason = epaCells.length > 0 && epaCells.every((m) => m.value === null
    && m.absent_reason === epaCells[0].absent_reason) ? epaCells[0].absent_reason : null
  const hide = sharedEpaReason !== null
  return (
    <section className={`card report-alliance alliance-border-${side}`} aria-labelledby={`report-${side}`}>
      <h2 id={`report-${side}`}>{title} <AllianceTeams teams={teams.map((t) => t.team_number)} eventKey={data.event_key} tone={side} /></h2>
      <div className="table-scroll">
        <table className="grid compact">
          <caption className="visually-hidden">{title}: role and expected contribution per robot</caption>
          <thead><tr><th scope="col">Robot</th><th scope="col">Role{label ? ` (${label})` : ''}</th>
            <th scope="col">EPA total</th><th scope="col">Auto</th><th scope="col">Teleop</th><th scope="col">Endgame</th></tr></thead>
          <tbody>
            {teams.map((t: PreMatchTeam) => (
              <tr key={t.team_number}>
                <th scope="row">{t.team_number}</th>
                <td>{plan ? roleOf(plan.strategy.robots.find((r) => r.team_number === t.team_number)) : <Absent />}</td>
                <td><MeasureValue measure={t.strength.epa.total} hideReason={hide} /></td>
                <td><MeasureValue measure={t.strength.epa.auto} hideReason={hide} /></td>
                <td><MeasureValue measure={t.strength.epa.teleop} hideReason={hide} /></td>
                <td><MeasureValue measure={t.strength.epa.endgame} hideReason={hide} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sharedEpaReason && <p className="small">No EPA for these robots: <Absent reason={sharedEpaReason} /></p>}
      {!plan && <p className="small">No roles: <Absent reason={data.strategy.absent_code ?? 'no strategy'} /></p>}
      <p className="small muted">Expected scoring contribution: each robot's EPA by phase (points), with its n; strategy roles are the
        strategy model's; its odds carry their served validation status.</p>
      {plan && strategySide && <p className="small">Odds for this alliance under its {label}: <OddsView odds={plan.odds} /></p>}
      {strategySide && strategySide.unavailable_reasons.length > 0 && (
        <p className="small muted">The engine gives no probability: {strategySide.unavailable_reasons.join(', ')}.</p>
      )}
      <h3>Synergy</h3>
      {synergy?.score ? <SynergyView data={synergy.score} status={synergy.validation.status} />
        : <AbsentPart code={synergy?.absent_code ?? null} reason={synergy?.absent_reason ?? null} />}
      <h3>Not produced by any engine</h3>
      <div className="not-produced-grid">
        <NotProducedItem title={perRobotItem.title} item={perRobotItem.item} />
        {allianceItems.map((i) => <NotProducedItem key={i.title} title={i.title} item={i.item} />)}
      </div>
    </section>
  )
}

function Report({ data, ours, setOurs, asOf }: { data: PreMatchReportResponse; ours: Side; setOurs: (s: Side) => void;
  asOf: string | null }) {
  const theirs: Side = ours === 'red' ? 'blue' : 'red'
  const eventKey = data.event_key ?? eventOfMatch(data.match_key)
  const np = data.not_produced
  const win = data.win_probability
  useOpenDetailsForPrint()
  return (
    <>
      <header className="report-header">
        <p className="small muted no-print"><Link to={`/events/${encodeURIComponent(eventKey)}`}>{eventKey}</Link> ·{' '}
          <Link to={matchPath(data.match_key)}>match strategy</Link></p>
        <h1>Pre-match report · {data.match_key}</h1>
        <p>Scheduled <When value={data.scheduled_time} /> · {data.competition_level ?? 'level unknown'} · taken at <When value={data.as_of} /> (
          {data.as_of_source === 'scheduled_time' ? 'the scheduled time' : data.as_of_source === 'requested' ? 'the requested moment' : 'now: the match is still ahead'})</p>
        <p><AllianceTeams teams={data.red_team_numbers} eventKey={eventKey} tone="red" /> <span className="muted">vs</span>{' '}
          <AllianceTeams teams={data.blue_team_numbers} eventKey={eventKey} tone="blue" /></p>
        <fieldset className="side-choice no-print">
          <legend>Our alliance</legend>
          {(['red', 'blue'] as Side[]).map((s) => (
            <label key={s} className="inline">
              <input type="radio" name="ours" value={s} checked={ours === s} onChange={() => setOurs(s)}
                aria-label={`Our alliance: ${s === 'red' ? 'Red' : 'Blue'}`} />
              {s === 'red' ? 'Red' : 'Blue'}
            </label>
          ))}
        </fieldset>
        <ShareBar />
      </header>
      <AllianceSection data={data} side={ours} title="Our alliance"
        perRobotItem={{ title: 'Strengths and weaknesses per robot', item: np.strengths_and_weaknesses }} allianceItems={[]} />
      <AllianceSection data={data} side={theirs} title="Opposing alliance"
        perRobotItem={{ title: 'Defensive threats', item: np.defensive_threats }}
        allianceItems={[{ title: 'Key risks', item: np.key_risks }]} />
      <section className="card" aria-labelledby="forecast-heading">
        <h2 id="forecast-heading">Match forecast</h2>
        <h3>Win probability (statistical model)</h3>
        {win.value ? <CalibratedProbabilityView value={win.value} /> : <AbsentPart code={win.absent_code} reason={win.absent_reason} />}
        <p className="small muted">Scope: {win.probability_scope}. A separate model from the strategy odds; the two are never combined.</p>
        <h3>Not produced by any engine</h3>
        <div className="not-produced-grid">
          <NotProducedItem title="Predicted flow" item={np.predicted_flow} />
          <NotProducedItem title="Critical matchups" item={np.critical_matchups} />
          <NotProducedItem title="Key success factors" item={np.key_success_factors} />
        </div>
      </section>
      <section className="card" aria-labelledby="strategy-heading">
        <h2 id="strategy-heading">Strategy detail</h2>
        {data.strategy.absent_code ? <AbsentPart code={data.strategy.absent_code} reason={data.strategy.absent_reason} /> : (
          data.strategy.sides.map((s) => {
            const { plan, label } = planFor(s)
            return (
              <div key={s.side}>
                <h3>{s.side === 'red' ? 'Red' : 'Blue'}: {label || 'no strategy'}</h3>
                {plan && <StrategyTable strategy={plan.strategy} caption={`${s.side} strategy`} />}
                {s.recommended && <p className="small muted">{s.selection_note}{s.vs_baseline_label && ` · versus the baseline: ${s.vs_baseline_label}`}</p>}
              </div>
            )
          })
        )}
      </section>
      <section className="card" aria-labelledby="evidence-heading">
        <h2 id="evidence-heading">Evidence per robot</h2>
        <p className="small muted">Each robot's full point-in-time strength view at the report's moment (defense and feeding are
          scouting-only; reliability is an estimate from recorded results).</p>
        {data.teams.map((t) => (
          <details key={t.team_number}>
            <summary>Team {t.team_number} ({t.alliance}) <ValidationBadge validation={t.validation} compact
              interactive={false} /></summary>
            <StrengthView view={t.strength} compact level={3} />
          </details>
        ))}
      </section>
      <BriefingPanel matchKey={data.match_key} asOf={asOf} reportAsOf={data.as_of} />
      <footer className="report-footer small muted">
        <EpaSourceNote epa={data.epa} />
        <p>Generated by StratAI from its engines' structured outputs; no item of the report is written by an LLM (the readable
          briefing can only be arranged by one, and says so). Items marked “not produced
          by any engine” have no engine behind them yet.</p>
      </footer>
    </>
  )
}
