// Display primitives for API values (P8-M1). Their rules (P8-Q4):
// - A probability is shown exactly as served. Strategy and playoff odds are the server's display strings.
// - An M6/M7 value is shown as a percentage only when validated. An unvalidated value is a separately styled
//   "unvalidated model output", always with its reason.
// - The client never computes, rounds, clips or compares a probability.
// - Validation labels are shown verbatim, with a plain explanation. `validated_playoff_success` and
//   `validated_playoff` are distinct labels and are never merged.
// - An absent value is "—" with its reason, never 0.

import { useId, useState, type ReactNode } from 'react'

import { ApiRequestError } from '../api/client'
import type { CalibratedWinProbability, EpaSourceInfo, Measure, StrategyOdds, Validation } from '../api/generated'
import type { Resource } from '../components/useResource'
import { refusalInfo } from './refusals'
import { formatNumber, reasonText, VALIDATION_LABELS } from './labels'

/**
 * A validation label, shown verbatim as served. The badge is a toggle that reveals the plain explanation inline
 * (reachable by keyboard and touch), and screen readers get the explanation as its description. Inside a
 * <summary> or another control, pass `interactive={false}` (a button cannot nest there); the explanation then stays
 * a description only.
 */
export function ValidationBadge({ validation, compact = false, interactive = true }: { validation: Validation;
  compact?: boolean; interactive?: boolean }) {
  const known = VALIDATION_LABELS[validation.status]
  const explanation = known?.text ?? 'A label this dashboard has no explanation for; shown as served.'
  const reasons = validation.reasons ?? []
  const [open, setOpen] = useState(false)
  const id = useId()
  const tone = `badge badge-${known?.tone ?? 'old'}`
  return (
    <span className="validation">
      {interactive ? (
        <button type="button" className={`${tone} badge-button`} aria-expanded={open} aria-describedby={`${id}-x`}
          title={explanation} onClick={() => setOpen(!open)}>{validation.status}<span className="badge-icon"
            aria-hidden="true"> ⓘ</span></button>
      ) : <span className={tone} title={explanation} aria-describedby={`${id}-x`}>{validation.status}</span>}
      <span id={`${id}-x`} className={open ? 'label-explain' : 'visually-hidden'}>{explanation}</span>
      {!compact && reasons.length > 0 && (
        <ul className="reasons" aria-label="Qualifiers">
          {reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      )}
    </span>
  )
}

/** An explicit absence: a dash plus the reason, readable by a screen reader. */
/**
 * "—" for a missing value, with the reason: plain words first, then the raw served code as visible secondary text
 * (no hover needed, so it works on touch and is read by screen readers). A reason with no plain-word mapping is
 * already shown verbatim, so its code is not repeated (P8-D1 D1.7, ruling of 2026-10-19).
 */
export function Absent({ reason }: { reason?: string | null }) {
  const text = reason ? reasonText(reason) : null
  return (
    <span className="absent" data-reason={reason ?? undefined}>
      <span aria-hidden="true">—</span>
      <span className="visually-hidden">not available</span>
      {reason && text ? (
        <span className="absent-reason"> <span className="absent-text">{text}</span>
          {text !== reason && <> <code className="reason-code">({reason})</code></>}</span>
      ) : null}
    </span>
  )
}

/** A Phase 3/5 measurement: its value with n and uncertainty, or its absence with the reason. */
export function MeasureValue({ measure, digits = 1, unit, hideReason = false }: { measure: Measure; digits?: number;
  unit?: string; hideReason?: boolean }) {
  // hideReason: the section states the shared reason once instead of in every cell
  if (measure.value === null) return <Absent reason={hideReason ? null : measure.absent_reason} />
  const sd = measure.uncertainty.kind === 'sd' && measure.uncertainty.value != null
    ? ` ± ${formatNumber(measure.uncertainty.value, digits)}` : ''
  return (
    <span className="measure">
      <span className="measure-value">{formatNumber(measure.value, digits)}{unit ? ` ${unit}` : ''}</span>
      <span className="muted small">{sd} (n = {measure.n})</span>
    </span>
  )
}

/** Strategy or playoff odds: the served display string, or the engine's reason there is none. */
export function OddsView({ odds }: { odds: StrategyOdds }) {
  return (
    <span className="odds">
      {odds.display !== null
        ? <strong className="odds-value">{odds.display}</strong>
        : <span className="odds-none">No probability</span>}{' '}
      <ValidationBadge validation={odds.validation} />
    </span>
  )
}

/** The M6/M7 win probability (P7-Q3): a validated value is a probability; an unvalidated value is not. */
export function CalibratedProbabilityView({ value, side = 'red' }: { value: CalibratedWinProbability;
  side?: 'red' }) {
  if (value.validated_value !== null) {
    return (
      <div className="calibrated">
        <div><strong className="prob-value">{Math.round(value.validated_value * 100)}%</strong>{' '}
          <span className="muted">P({side} wins)</span></div>
        <ValidationBadge validation={value.validation} />
      </div>
    )
  }
  return (
    <div className="calibrated calibrated-unvalidated">
      <div>
        <span className="unvalidated-tag">Unvalidated model output</span>{' '}
        <span className="unvalidated-value">{value.unvalidated_value !== null
          ? `${Math.round(value.unvalidated_value * 100)}%` : '—'}</span>{' '}
        <span className="muted">for {side}, not a validated probability ({value.unvalidated_reason ?? 'no reason given'})</span>
      </div>
      <ValidationBadge validation={value.validation} />
    </div>
  )
}

/** Which EPA source a result used, and its flags (e.g. live_refresh_not_yet_validated). */
export function EpaSourceNote({ epa }: { epa: EpaSourceInfo }) {
  const flags = epa.validation_flags ?? []
  return (
    <p className="epa-note small muted">
      EPA source <code>{epa.epa_source}</code>
      {epa.evaluated_configuration ? ' (the evaluated configuration)' : ' (not the configuration the models were evaluated on)'}
      {flags.length > 0 && <> · {flags.join(', ')}</>}
    </p>
  )
}

/** A refusal or failure, explained (P8-Q5), with the code and request id kept visible. */
export function RefusalNotice({ error, what }: { error: unknown; what?: string }) {
  if (error instanceof ApiRequestError) {
    const info = refusalInfo(error.code, error.message)
    const tone = info.kind === 'failure' ? 'notice-error' : info.kind === 'input' ? 'notice-warn' : 'notice-info'
    return (
      <div className={`notice ${tone} refusal`} role={info.kind === 'failure' ? 'alert' : 'status'}>
        <strong>{what ? `${what}: ` : ''}{info.title}</strong>
        <p className="refusal-text">{info.explanation}</p>
        <p className="small muted">
          <code>{error.code}</code>{error.status ? ` (${error.status})` : ''}: {error.message}
          {error.requestId && <> · request <code>{error.requestId}</code></>}
        </p>
      </div>
    )
  }
  return <div className="notice notice-error" role="alert">{String((error as Error)?.message ?? error)}</div>
}

/** Loading → refusal/error → content, for one resource. */
export function ResourceView<T>({ resource, what, children, loadingText }: { resource: Resource<T>; what?: string;
  loadingText?: string; children: (data: T) => ReactNode }) {
  if (resource.loading && resource.data === null) {
    return <p className="loading" role="status" aria-live="polite">{loadingText ?? `Loading${what ? ` ${what}` : ''}…`}</p>
  }
  if (resource.error) {
    const failure = resource.error instanceof ApiRequestError && refusalInfo(resource.error.code, '').kind === 'failure'
    return (
      <div>
        <RefusalNotice error={resource.error} what={what} />
        {failure && <button type="button" className="secondary" onClick={resource.reload}>Retry</button>}
      </div>
    )
  }
  if (resource.data === null) return null
  return <>{children(resource.data)}</>
}

export function When({ value }: { value: string | null | undefined }) {
  if (!value) return <Absent />
  return <time dateTime={value} title={value}>{new Date(value).toLocaleString()}</time>
}
