import type { ReactNode } from 'react'

import { ApiRequestError } from '../api/client'
import type { Coverage, Feature } from '../api/managerTypes'
import { formatValue } from '../lib/format'
import { ErrorNotice, StateBadge } from './common'

// What each "not available" code means to a person, so an absent result is explained, never shown as empty.
const EXPLAINED: Record<string, string> = {
  model_not_loaded: 'This API instance has no pinned model for this feature, so it is not served here.',
  epa_source_not_loaded: 'The EPA source is not configured on this API instance.',
  epa_source_incomplete: 'The EPA source does not cover this event or season.',
  epa_source_pending: 'The EPA source has not caught up with this event yet.',
  metrics_not_computed: 'Team metrics have not been computed for this team at this event.',
  team_did_not_attend: 'This team did not play at this event.',
  event_not_found: 'This event is not in the database.',
  team_not_found: 'This team is not in the database.',
  match_not_found: 'This match is not in the database.',
  invalid_as_of: 'The "as of" time is not valid (use an ISO-8601 time with an offset).',
  season_not_supported: 'This season has no verified score-breakdown adapter, so its features are not built (never guessed).',
  insufficient_features: 'No team in this match has any prior evidence (EPA, scoring history or scouting), so no prediction is served.',
}

/** Available, available with limitations, or unavailable: "available" alone would overstate a limited feature. */
export function FeatureBadge({ feature }: { feature: Feature }) {
  if (!feature.available) return <StateBadge state="missing" label="unavailable" />
  return feature.limitations?.length
    ? <StateBadge state="provisional" label="limited" /> : <StateBadge state="approved" label="available" />
}

/** An API error with a plain-language explanation when the code means "not available", not "broken". */
export function Unavailable({ error }: { error: unknown }) {
  if (error instanceof ApiRequestError && EXPLAINED[error.code]) {
    return (
      <div className="notice notice-info" role="status" data-testid="unavailable">
        <strong>Not available:</strong> {EXPLAINED[error.code]} <span className="muted small">({error.code})</span>
      </div>
    )
  }
  return <ErrorNotice error={error} />
}

const STATUS_TONE: Record<string, string> = {
  validated: 'ok', validated_as_measured: 'ok', moderate_held_out: 'wait', descriptive: 'old',
  not_validated: 'warn', descriptive_definition_pending: 'warn', insufficient_data: 'bad',
  machine_extracted_unverified: 'warn',
}

/** A result's own validation status, shown as it was returned. */
export function ValidationBadge({ status }: { status: unknown }) {
  if (typeof status !== 'string' || !status) return null
  return <span className={`badge badge-${STATUS_TONE[status] ?? 'old'}`} title="validation status">{status.replaceAll('_', ' ')}</span>
}

/** A measured value as the API reports it: the value, its sample size and uncertainty, or why it is absent. */
export function Measured({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="muted">—</span>
  if (typeof value !== 'object') return <>{formatValue(value)}</>
  const m = value as { value?: unknown; n?: number; uncertainty?: { kind?: string; value?: number | null }; absent_reason?: string | null }
  if (m.value === null || m.value === undefined) {
    return <span className="muted" title={m.absent_reason ?? undefined}>absent{m.absent_reason ? ` (${m.absent_reason})` : ''}</span>
  }
  const sd = m.uncertainty?.kind === 'sd' && typeof m.uncertainty.value === 'number' ? ` ± ${m.uncertainty.value.toFixed(1)}` : ''
  return <span>{formatValue(m.value)}{sd}{m.n !== undefined && <span className="muted small"> (n={m.n})</span>}</span>
}

/** A table of flat records; nested values are summarized, never hidden silently. */
export function DataTable<T extends Record<string, unknown>>({ rows, columns, caption, empty = 'No rows.',
  render }: { rows: T[]; columns: (keyof T & string)[]; caption?: string; empty?: string;
  render?: Partial<Record<keyof T & string, (row: T) => ReactNode>> }) {
  if (!rows.length) return <p className="muted">{empty}</p>
  return (
    <div className="table-scroll">
      <table className="grid compact">
        {caption && <caption>{caption}</caption>}
        <thead><tr>{columns.map((c) => <th key={c}>{c.replaceAll('_', ' ')}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>{columns.map((c) => <td key={c}>{render?.[c] ? render[c]!(row) : formatValue(row[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The full response, for anyone who needs to check what the API returned. */
export function RawJson({ value, label = 'Full response' }: { value: unknown; label?: string }) {
  return (
    <details className="raw">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}

/** A season's real data, with freshness, so no view looks complete when it is not. */
export function CoverageTiles({ coverage, season }: { coverage: Coverage; season: number }) {
  if (!coverage.has_data) {
    return (
      <div className="notice notice-info" role="status" data-testid="no-season-data">
        No {season} data is synced. {season === 2027
          ? 'The 2027 season has not been played; its data arrives as events happen.'
          : 'Sync the season to use its views.'}
      </div>
    )
  }
  const tiles: [string, number | string][] = [
    ['Events', coverage.events], ['Matches played', `${coverage.matches_played} / ${coverage.matches}`],
    ['Teams', coverage.teams], ['Team EPA rows', coverage.team_event_epa_rows],
    ['Team metrics rows', coverage.team_metrics_rows], ['Scouting observations', coverage.scouting_observations],
  ]
  return (
    <div>
      <div className="tiles" data-testid="coverage">
        {tiles.map(([label, value]) => (
          <div className="tile" key={label}><span className="tile-value">{value}</span><span className="tile-label">{label}</span></div>
        ))}
      </div>
      <p className="muted small">
        Latest match {coverage.latest_match ? new Date(coverage.latest_match).toLocaleDateString() : '—'} · data
        updated {coverage.latest_update ? new Date(coverage.latest_update).toLocaleString() : '—'}
        {!coverage.team_event_epa_rows && ' · no team EPA synced for this season'}
        {!coverage.score_breakdown_adapter && ' · no score-component adapter for this season'}
      </p>
    </div>
  )
}
