// Alliance synergy terms (Phase 4 M9), as the pre-match report shows them. Moved here from the old standalone
// alliance selection page when that page was removed (2026-11-26).

import { Absent, ValidationBadge } from './display'
import { formatNumber } from './labels'

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
