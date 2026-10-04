import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { Dm1Item } from '../api/types'
import { LoadState, Section, StateBadge, useLoad } from '../components/common'
import { useSession } from '../state/session'

const LABELS: Record<string, { title: string; where: string; page: string }> = {
  game_manual: { title: 'Official game manual (PDF)', where: 'source artifact', page: '/game' },
  game_spec: { title: 'Structured game specification', where: 'entered and reviewed by people', page: '/game' },
  catalog_specs: { title: 'Catalog specs (earlier seasons)', where: 'approved specs before this season', page: '/game' },
  codebook: { title: 'Codebook', where: 'established by a named person', page: '/review' },
  independent_codings: { title: 'Two independent codings', where: 'two different coders', page: '/review' },
  codebook_agreement: { title: 'Codebook agreement (κ)', where: 'computed from the codings', page: '/review' },
  consensus_coding: { title: 'Consensus coding', where: 'after κ, from the consensus meeting', page: '/review' },
  action_function_map: { title: 'Action → function map', where: 'established by a named person', page: '/review' },
  rubric: { title: 'Feasibility rubric', where: 'established by a named person', page: '/review' },
  team_profiles: { title: 'Team capability profiles (≥ 10)', where: 'entered by people', page: '/profiles' },
  mentor_review: { title: 'Mentor review', where: 'a named mentor', page: '/review' },
}

function detailText(item: Dm1Item): string | null {
  const d = item.detail as Record<string, unknown> | string | null
  if (d === null || d === undefined) return null
  if (typeof d === 'string') return d
  if (item.artifact === 'team_profiles') return `${d.active} active of ${d.required} required`
  if (item.artifact === 'catalog_specs') {
    const seasons = d.seasons as number[]
    return seasons.length ? `approved: ${seasons.join(', ')}` : null
  }
  if (item.artifact === 'independent_codings') {
    const coders = d.coders as string[]
    return coders.length ? `coders: ${coders.join(', ')}` : null
  }
  if (item.artifact === 'codebook_agreement' && typeof d === 'object' && 'overall' in d) {
    return `labels overall: ${String(d.overall)}`
  }
  if ('by' in d) return `by ${String(d.by)}`
  if ('reviewer' in d) return `by ${String(d.reviewer)}`
  if (item.artifact === 'game_spec') return `${String(d.spec_versions)} version(s)`
  return null
}

export function OverviewPage() {
  const { season } = useSession()
  const status = useLoad(() => api.dm1Status(season), [season])
  const data = status.data

  return (
    <>
      <Section title={`DM1 inputs · season ${season}`}>
        <p className="lede">
          Everything DM1 needs from people, and where it stands. These states describe what has been entered; they
          do not decide DM1. <strong>DM1 is met only by the write-once dry-run, score and mentor-review
          records</strong>, never by entered data alone.
        </p>
        <LoadState loading={status.loading && !data} error={status.error} />
        {data && (
          <table className="grid">
            <thead>
              <tr><th>Input</th><th>State</th><th>Provided</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {data.items.map((item) => {
                const label = LABELS[item.artifact] ?? { title: item.artifact, where: '', page: '/' }
                return (
                  <tr key={item.artifact} data-testid={`dm1-${item.artifact}`}>
                    <td><Link to={label.page}>{label.title}</Link><div className="muted small">{label.where}</div></td>
                    <td><StateBadge state={item.state} /></td>
                    <td>{item.provided ? 'yes' : 'no'}</td>
                    <td className="small">{detailText(item)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Section>

      {data && (
        <Section title="DM1 done-means (authoritative)">
          <div className={`verdict ${data.done_means.met ? 'verdict-ok' : 'verdict-bad'}`} data-testid="dm1-verdict">
            DM1: {data.done_means.met ? 'MET' : 'NOT MET'}
          </div>
          <dl className="facts">
            <dt>Inputs entered for the run</dt>
            <dd>{data.inputs_ready ? 'all present' : 'not yet: see the table above'}</dd>
            <dt>Missing records</dt>
            <dd>{data.done_means.missing_records.length ? data.done_means.missing_records.join(', ') : 'none'}</dd>
            <dt>Within 5 days</dt>
            <dd>{data.done_means.within_5_days === null ? 'no dry run recorded' : String(data.done_means.within_5_days)}</dd>
          </dl>
          {data.done_means.blocked_on.map((b) => <p key={b} className="notice notice-info">Blocked on {b}</p>)}
          <p className="muted small">{data.note}</p>
        </Section>
      )}
    </>
  )
}
