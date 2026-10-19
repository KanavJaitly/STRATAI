// The match-strategy workbench (P8-M4): the AI recommendation and a coach strategy side by side, through the one
// engine path (P6-DM2). The odds shown are the engine's display strings, with its status and reasons:
// - nothing here computes or compares probabilities; the compare label is the engine's own;
// - both strategies are rendered by the same component, so neither is presented more favourably;
// - `selection_note` (the recommendation is the maximum of many estimates) is always shown with the recommendation.

import { useState, type ReactNode } from 'react'

import type { Side } from '../api/dashboard'
import type { AssessmentOut, CompareResponse, RecommendResponse, RobotPlan, Strategy, StrategyContextOut, StrategyModelInfo } from '../api/generated'
import type { Resource } from '../components/useResource'
import { Absent, EpaSourceNote, OddsView, RefusalNotice, ResourceView, When } from './display'
import { useOnDemand } from '../components/useOnDemand'
import { baselineStrategy, COMPONENTS, strategyProblems } from './strategyModel'

function roleText(robot: RobotPlan): string {
  const role = robot.role ?? 'scoring'
  if (role === 'defense') return `Defense on ${robot.defense_target}`
  if (role === 'feeding') return `Feeding ${robot.feed_target}`
  return 'Scoring'
}

/** One strategy as a table of role assignments and scoring priorities. */
export function StrategyTable({ strategy, caption }: { strategy: Strategy; caption: string }) {
  return (
    <div className="table-scroll">
      <table className="grid compact">
        <caption className="visually-hidden">{caption}</caption>
        <thead><tr><th scope="col">Robot</th><th scope="col">Teleop role</th><th scope="col">Scores in</th></tr></thead>
        <tbody>
          {strategy.robots.map((robot) => (
            <tr key={robot.team_number}>
              <th scope="row">{robot.team_number}</th>
              <td>{roleText(robot)}</td>
              <td>{(robot.components ?? COMPONENTS).length ? (robot.components ?? COMPONENTS).join(', ') : <Absent reason="no scoring" />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** An assessed strategy: the plan and its odds (the same rendering for the AI and the coach path). */
export function AssessedStrategy({ title, assessment, note }: { title: string; assessment: { strategy: Strategy;
  odds: AssessmentOut['odds'] }; note?: ReactNode }) {
  return (
    <div className="assessed">
      <h3>{title}</h3>
      <p className="odds-line">Odds of winning: <OddsView odds={assessment.odds} /></p>
      <StrategyTable strategy={assessment.strategy} caption={title} />
      {note}
    </div>
  )
}

export function ContextFacts({ context, model }: { context: StrategyContextOut; model: StrategyModelInfo }) {
  return (
    <dl className="facts small">
      <dt>Moment</dt><dd><When value={context.as_of} /></dd>
      <dt>Context</dt><dd>{context.match_context}{context.competition_level ? ` (${context.competition_level})` : ''}</dd>
      <dt>Coach observations applied</dt><dd>{context.coach_observations_applied}
        {context.coach_observations_invalid_ignored > 0 && <span className="muted"> · {context.coach_observations_invalid_ignored} invalid ignored</span>}</dd>
      <dt>Model</dt><dd>{model.model_type} {model.model_version_tag} <code title={model.model_sha256}>{model.model_sha256.slice(0, 12)}…</code></dd>
    </dl>
  )
}

/** Edits one alliance's strategy, with the rules the engine enforces explained inline. */
export function StrategyEditor({ value, onChange, allies, opponents, label }: { value: Strategy;
  onChange: (next: Strategy) => void; allies: number[]; opponents: number[]; label: string }) {
  const update = (index: number, patch: Partial<RobotPlan>) => {
    const robots = value.robots.map((r, i) => (i === index ? { ...r, ...patch } : r)) as Strategy['robots']
    onChange({ ...value, robots })
  }
  return (
    <fieldset className="strategy-editor">
      <legend>{label}</legend>
      {value.robots.map((robot, index) => {
        const role = robot.role ?? 'scoring'
        const components = robot.components ?? COMPONENTS
        return (
          <div key={robot.team_number} className="robot-row">
            <strong className="robot-team">{robot.team_number}</strong>
            <label className="inline">Role
              <select value={role} aria-label={`Team ${robot.team_number} role`} onChange={(e) => {
                const next = e.target.value as RobotPlan['role']
                update(index, {
                  role: next,
                  defense_target: next === 'defense' ? opponents[0] ?? null : null,
                  feed_target: next === 'feeding' ? allies.find((a) => a !== robot.team_number) ?? null : null,
                  components: next === 'scoring' ? components : components.filter((c) => c !== 'teleop'),
                })
              }}>
                <option value="scoring">Scoring</option>
                <option value="defense">Defense</option>
                <option value="feeding">Feeding</option>
              </select>
            </label>
            {role === 'defense' && (
              <label className="inline">Defend
                <select value={robot.defense_target ?? ''} aria-label={`Team ${robot.team_number} defends`}
                  onChange={(e) => update(index, { defense_target: Number(e.target.value) })}>
                  {opponents.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
            )}
            {role === 'feeding' && (
              <label className="inline">Feed
                <select value={robot.feed_target ?? ''} aria-label={`Team ${robot.team_number} feeds`}
                  onChange={(e) => update(index, { feed_target: Number(e.target.value) })}>
                  {allies.filter((t) => t !== robot.team_number).map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
            )}
            <span className="component-boxes" role="group" aria-label={`Team ${robot.team_number} scores in`}>
              {COMPONENTS.map((c) => (
                <label key={c} className="inline">
                  <input type="checkbox" checked={components.includes(c)} disabled={c === 'teleop' && role !== 'scoring'}
                    onChange={(e) => update(index, {
                      components: e.target.checked ? COMPONENTS.filter((x) => x === c || components.includes(x))
                        : components.filter((x) => x !== c),
                    })} aria-label={`Team ${robot.team_number} ${c}`} />
                  {c}
                </label>
              ))}
            </span>
          </div>
        )
      })}
      <p className="small muted">Teleop scoring needs the scoring role: a defender or feeder spends teleop on its role.</p>
    </fieldset>
  )
}

export interface StrategyOps {
  compare: (body: { side: Side; first: Strategy; second: Strategy }, signal: AbortSignal) => Promise<CompareResponse>
}

/**
 * The side-by-side comparison. The recommendation comes in as a loaded resource. The coach strategy starts as the
 * baseline and is edited here. Evaluating sends both to the engine's compare route, so both odds come from one
 * call, with one context.
 */
export function StrategyWorkbench({ side, recommendation, ours, theirs, ops, coachActions }: { side: Side;
  recommendation: Resource<RecommendResponse>; ours: number[]; theirs: number[]; ops: StrategyOps;
  coachActions?: (coach: Strategy, valid: boolean) => ReactNode }) {
  const [coach, setCoach] = useState<Strategy>(() => baselineStrategy(ours))
  const comparison = useOnDemand<CompareResponse>()
  const [comparedTitle, setComparedTitle] = useState('') // what `first` was when it was sent, not what it is now
  const [lastSide, setLastSide] = useState(side)
  const coachTeams = coach.robots.map((r) => r.team_number).join(',')
  if (side !== lastSide || coachTeams !== ours.join(',')) { // a new side, or the teams arrived/changed: start over
    setLastSide(side)
    setCoach(baselineStrategy(ours))
    comparison.reset()
  }
  const problems = strategyProblems(coach, ours, theirs)
  const rec = recommendation.data
  const aiStrategy = rec?.recommended?.strategy ?? rec?.baseline?.strategy ?? null

  return (
    <section className="card" aria-labelledby="workbench-heading">
      <h2 id="workbench-heading">AI and coach strategies, side by side ({side} alliance)</h2>
      <ResourceView resource={recommendation} what="AI recommendation"
        loadingText="Searching every strategy for the recommendation (a few seconds)…">
        {(r) => (
          <>
            <ContextFacts context={r.context} model={r.model} />
            {r.unavailable_reasons.length > 0 && (
              <div className="notice notice-info" role="status">
                <strong>The engine gives no probability for this match.</strong>
                <ul>{r.unavailable_reasons.map((reason) => <li key={reason}><code>{reason}</code></li>)}</ul>
              </div>
            )}
          </>
        )}
      </ResourceView>
      <div className="side-by-side">
        <div className="side ai-side">
          {rec?.recommended
            ? <AssessedStrategy title="AI recommendation" assessment={rec.recommended}
                note={<p className="small muted selection-note">{rec.selection_note}
                  {rec.vs_baseline_label && <> · versus the baseline: {rec.vs_baseline_label}</>}
                  {' '}({rec.candidates_evaluated.toLocaleString()} strategies evaluated)</p>} />
            : rec ? <p className="muted">No recommendation{rec.unavailable_reasons.length ? ' (see above)' : ''}.</p>
              : recommendation.error != null && <p className="muted unavailable-side">The AI recommendation is unavailable (see above). The coach strategy can still be entered and saved; evaluating it needs the engine.</p>}
          {rec?.baseline && <AssessedStrategy title="Baseline (every robot scores everything)" assessment={rec.baseline} />}
          {rec && rec.alternatives.length > 0 && (
            <details>
              <summary>Next-best alternatives ({rec.alternatives.length})</summary>
              {rec.alternatives.map((alt, i) => <AssessedStrategy key={i} title={`Alternative ${i + 1}`} assessment={alt} />)}
            </details>
          )}
        </div>
        <div className="side coach-side">
          <StrategyEditor value={coach} onChange={(next) => { setCoach(next); comparison.reset() }} allies={ours} opponents={theirs}
            label={`Coach strategy for ${side}`} />
          {problems.length > 0 && <ul className="notice notice-warn">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          <button type="button" disabled={!aiStrategy || problems.length > 0 || comparison.busy}
            onClick={() => {
              if (!aiStrategy) return
              setComparedTitle(rec?.recommended ? 'AI recommendation' : 'Baseline')
              comparison.run((signal) => ops.compare({ side, first: aiStrategy, second: coach }, signal))
            }}>
            {comparison.busy ? 'Evaluating…' : 'Evaluate side by side'}
          </button>
          {!aiStrategy && !recommendation.loading && <p className="small muted">Evaluation needs the engine (see the AI side).</p>}
          {coachActions?.(coach, problems.length === 0)}
        </div>
      </div>
      {comparison.error != null && <RefusalNotice error={comparison.error} what="Comparison" />}
      {comparison.result && <ComparisonResult result={comparison.result} firstTitle={comparedTitle} />}
    </section>
  )
}

function ComparisonResult({ result, firstTitle }: { result: CompareResponse; firstTitle: string }) {
  return (
    <div className="comparison" aria-live="polite">
      <h3>Same model, same inputs</h3>
      <p className="compare-label"><strong>{result.label}</strong></p>
      <div className="side-by-side">
        <AssessedStrategy title={firstTitle} assessment={result.first} />
        <AssessedStrategy title="Coach strategy" assessment={result.second} />
      </div>
      <p className="small muted">Opponent strategy (both): {result.opponent_strategy.robots.map((r) => `${r.team_number} ${roleText(r).toLowerCase()}`).join(' · ')}</p>
      <EpaSourceNote epa={result.epa} />
    </div>
  )
}
