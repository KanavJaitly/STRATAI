import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { Feature, Phase6Task, Readiness, TaskStatus } from '../api/managerTypes'
import { LoadState, Section, StateBadge, useLoad } from '../components/common'
import { CoverageTiles, DataTable, FeatureBadge } from '../components/seasonUi'
import { useSession } from '../state/session'

const TASK_STATE: Record<TaskStatus, string> = {
  done: 'approved', failed: 'missing', ready_for_human: 'awaiting_review', ready_to_run: 'awaiting_review',
  blocked: 'draft', waiting_for_2027_data: 'superseded',
}

const TASK_LABEL: Record<TaskStatus, string> = {
  done: 'done', failed: 'failed', ready_for_human: 'your action', ready_to_run: 'ready to run',
  blocked: 'blocked', waiting_for_2027_data: 'waiting for 2027 data',
}

function Tasks({ tasks }: { tasks: Phase6Task[] }) {
  const mine = tasks.filter((t) => t.status === 'ready_for_human')
  return (
    <>
      {mine.length > 0 && (
        <div className="notice notice-info" role="status">
          <strong>Your next action{mine.length > 1 ? 's' : ''}:</strong>
          <ul>{mine.map((t) => <li key={t.id}>{t.id} — {t.title} ({t.actor})</li>)}</ul>
        </div>
      )}
      <div className="table-scroll">
        <table className="grid compact task-list" data-testid="phase6-tasks">
          <thead><tr><th>Task</th><th>Status</th><th>Who</th><th>Kind</th><th>Waiting on</th><th>Evidence</th><th>Authorizes</th></tr></thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id}>
                <td>{t.id}<div className="small" style={{ fontWeight: 400 }}>{t.title}</div></td>
                <td><StateBadge state={TASK_STATE[t.status]} label={TASK_LABEL[t.status]} /></td>
                <td>{t.actor}</td><td>{t.kind.replaceAll('_', ' ')}</td>
                <td>{t.waiting_on.length ? t.waiting_on.join(', ') : '—'}</td>
                <td>{t.evidence ? <code className="small">{t.evidence}</code> : 'the approved ruleset'}
                  {t.evidence_exists && <span className="muted small"> (exists)</span>}</td>
                <td className="small">{t.authorizes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Uploading a manual never completes or authorizes any of these. Each is done only by
        the named person's own file or decision, or by the run's own write-once record.</p>
    </>
  )
}

export function ReadinessPage() {
  const { season } = useSession()
  const { data, error, loading } = useLoad<Readiness>(() => api.readiness(season), [season])
  if (loading || error || !data) return <Section title={`Readiness — ${season}`}><LoadState loading={loading} error={error} /></Section>
  const inputs = data.human_inputs
  const manual = inputs.manuals[inputs.manuals.length - 1]
  return (
    <>
      <Section title={`Readiness — ${season}`}>
        <h3>Season data</h3>
        <CoverageTiles coverage={data.coverage} season={season} />
        <h3>Human inputs</h3>
        <dl className="facts">
          <dt>Game manual</dt>
          <dd>{manual ? <>#{manual.id} {manual.filename} · <StateBadge state={manual.processing.status === 'succeeded' ? 'approved' : 'draft'}
            label={manual.processing.status.replaceAll('_', ' ')} /></> : 'none uploaded'} · <Link to="/manuals">manage</Link></dd>
          <dt>Game spec</dt>
          <dd>{inputs.game_spec ? <StateBadge state={inputs.game_spec.status} /> : 'none'} · <Link to="/game">open</Link></dd>
          <dt>Season ruleset</dt>
          <dd>{inputs.ruleset.approved ? <>approved v{inputs.ruleset.approved.version} by {inputs.ruleset.approved.reviewed_by}</>
            : inputs.ruleset.latest ? <StateBadge state={inputs.ruleset.latest.status} /> : 'none'} · <Link to="/rulesets">open</Link></dd>
        </dl>
      </Section>
      <Section title="Features">
        <DataTable rows={data.features as unknown as Record<string, unknown>[]} columns={['name', 'available', 'reasons', 'consumes']}
          render={{ available: (r) => <FeatureBadge feature={r as unknown as Feature} />,
            reasons: (r) => [...(r.reasons as string[]), ...((r.limitations as string[] | undefined) ?? [])].join('; ') || '—', consumes: (r) => (r.consumes as string[]).join(', ') }} />
      </Section>
      {data.phase6 && (
        <Section title="2027 season tasks and approvals">
          <p><strong>{data.phase6.status}</strong></p>
          <ul>{data.phase6.done_means.map((d) => (
            <li key={d.done_means}>{d.done_means}: <StateBadge state={d.met ? 'met' : 'not_met'} label={d.met ? 'met' : 'not met'} /></li>
          ))}</ul>
          <Tasks tasks={data.phase6.tasks} />
        </Section>
      )}
      <Section title="What runs automatically, and what never does">
        <h4>Automatic</h4><ul>{data.automation_boundary.automatic.map((a) => <li key={a}>{a}</li>)}</ul>
        <h4>Never automatic</h4><ul>{data.automation_boundary.never_automatic.map((a) => <li key={a}>{a}</li>)}</ul>
      </Section>
    </>
  )
}
