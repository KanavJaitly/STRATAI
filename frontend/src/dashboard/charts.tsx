import { formatNumber } from './labels'
// Small inline-SVG charts (P8-Q3: no chart library). Every chart:
// - plots only served values; missing points are listed as missing, never drawn as zero;
// - has a labelled value axis with units and a zero baseline (bars never start above zero);
// - carries a text alternative (role="img" with a summary) and a visible data table, so nothing is conveyed by
//   the picture alone.


export interface ChartPoint {
  label: string
  value: number | null
  /** Optional per-point note (e.g. why it is missing). */
  note?: string | null
  tone?: 'red' | 'blue' | 'neutral'
}

const WIDTH = 640
const BAR_GAP = 6
const MAX_BAR = 48 // a chart with few points keeps narrow, centred bars instead of one bar across the plot
// Margins fit the tick text at its phone size too (18 viewBox units, P8-R9): rotated x labels of up to about 12
// characters below the axis, and four-digit y ticks clear of the rotated unit title.
const PAD = { top: 22, right: 12, bottom: 96, left: 80 }

function niceMax(max: number): number {
  if (max <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(max))
  const scaled = max / magnitude
  const nice = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10
  return nice * magnitude
}

export function BarChart({ title, points, unit, height = 220, digits = 1 }: { title: string; points: ChartPoint[];
  unit: string; height?: number; digits?: number }) {
  const present = points.filter((p): p is ChartPoint & { value: number } => p.value !== null)
  const missing = points.filter((p) => p.value === null)
  const min = Math.min(0, ...present.map((p) => p.value))
  const max = niceMax(Math.max(0, ...present.map((p) => p.value)))
  const span = max - min || 1
  const plotW = WIDTH - PAD.left - PAD.right
  const plotH = height - PAD.top - PAD.bottom
  const slot = points.length ? plotW / points.length : 0
  const barW = points.length ? Math.min(MAX_BAR, Math.max(4, slot - BAR_GAP)) : 0
  const y = (v: number) => PAD.top + plotH - ((v - min) / span) * plotH
  const ticks = [min, min + span / 2, max]
  const summary = present.length
    ? `${title}: ${present.length} value${present.length === 1 ? '' : 's'} in ${unit}, from `
      + `${formatNumber(Math.min(...present.map((p) => p.value)), digits)} to `
      + `${formatNumber(Math.max(...present.map((p) => p.value)), digits)}`
      + (missing.length ? `; ${missing.length} missing` : '') + '. The values are in the table below.'
    : `${title}: no values to plot.`
  return (
    <figure className="chart">
      <figcaption className="chart-title">{title} <span className="muted small">({unit})</span></figcaption>
      {present.length > 0 && (
        <div className="chart-scroll">
        <svg viewBox={`0 0 ${WIDTH} ${height}`} role="img" aria-label={summary} className="chart-svg"
          preserveAspectRatio="xMidYMid meet">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(t)} y2={y(t)} className="chart-grid" />
              <text x={PAD.left - 6} y={y(t) + 4} textAnchor="end" className="chart-tick">{formatNumber(t, digits)}</text>
            </g>
          ))}
          <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(0)} y2={y(0)} className="chart-axis" />
          <text x={22} y={PAD.top + plotH / 2} transform={`rotate(-90 22 ${PAD.top + plotH / 2})`} textAnchor="middle"
            className="chart-tick">{unit}</text>
          {points.map((p, i) => {
            const x = PAD.left + i * slot + (slot - barW) / 2
            const label = <text x={x + barW / 2} y={height - PAD.bottom + 14} textAnchor="end"
              transform={`rotate(-35 ${x + barW / 2} ${height - PAD.bottom + 14})`} className="chart-tick">{p.label}</text>
            if (p.value === null) {
              return <g key={p.label + i}>{label}<text x={x + barW / 2} y={y(0) - 4} textAnchor="middle"
                className="chart-missing">×</text></g>
            }
            const top = y(Math.max(0, p.value))
            const h = Math.abs(y(p.value) - y(0))
            return (
              <g key={p.label + i}>
                <rect x={x} y={top} width={barW} height={Math.max(h, 1)} className={`chart-bar tone-${p.tone ?? 'neutral'}`}>
                  <title>{`${p.label}: ${formatNumber(p.value, digits)} ${unit}`}</title>
                </rect>
                {label}
              </g>
            )
          })}
        </svg>
        </div>
      )}
      <details className="chart-data">
        <summary>Data table</summary>
        <div className="table-scroll">
        <table className="grid compact">
          <thead><tr><th scope="col">Point</th><th scope="col">Value ({unit})</th></tr></thead>
          <tbody>
            {points.map((p, i) => (
              <tr key={p.label + i}>
                <th scope="row">{p.label}</th>
                <td>{p.value === null ? <span className="muted">missing{p.note ? ` (${p.note})` : ''}</span>
                  : formatNumber(p.value, digits)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </details>
      {present.length === 0 && <p className="muted small">No values to plot.</p>}
    </figure>
  )
}
