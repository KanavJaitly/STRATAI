import type { ReactNode } from 'react'

import { ApiRequestError } from '../api/client'
import { useSession } from '../state/session'

export { useAction, useLoad } from './hooks'

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null
  if (error instanceof ApiRequestError) {
    return (
      <div className="notice notice-error" role="alert">
        <strong>{error.code}</strong> ({error.status}): {error.message}
        {error.requestId && <span className="muted"> · request {error.requestId}</span>}
      </div>
    )
  }
  return <div className="notice notice-error" role="alert">{String((error as Error)?.message ?? error)}</div>
}

export function SuccessNotice({ message }: { message: string | null }) {
  return message ? <div className="notice notice-ok" role="status">{message}</div> : null
}

const TONES: Record<string, string> = {
  // done / authoritative
  reviewed_approved: 'ok', approved: 'ok', established: 'ok', active: 'ok', complete: 'ok', computed: 'ok',
  categories: 'ok', recorded: 'ok', uploaded: 'ok', submitted_ok: 'ok', met: 'ok',
  // waiting on a person
  awaiting_human_review: 'wait', awaiting_review: 'wait', awaiting_sign_off: 'wait', submitted: 'wait',
  draft_complete_not_submitted: 'wait', awaiting_codings: 'wait',
  // incomplete or provisional
  structured_spec_incomplete: 'warn', draft: 'warn', incomplete: 'warn', provisional: 'warn', stale_codings: 'warn',
  // missing / not met
  missing: 'bad', no_structured_spec: 'bad', not_met: 'bad',
  // history
  superseded: 'old', archived: 'old',
}

export function StateBadge({ state, label }: { state: string; label?: string }) {
  return <span className={`badge badge-${TONES[state] ?? 'old'}`}>{label ?? state.replaceAll('_', ' ')}</span>
}

export function Sha({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>
  return <code title={value} className="sha">{value.slice(0, 12)}…</code>
}

export function When({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>
  return <time dateTime={value} title={value}>{new Date(value).toLocaleString()}</time>
}

export function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      <header className="card-head">
        <h2>{title}</h2>
        {actions}
      </header>
      {children}
    </section>
  )
}

/** Shown in place of write controls when this browser cannot write, with the reason. */
export function WriteGate({ children }: { children: ReactNode }) {
  const { access, canWrite, actor } = useSession()
  if (canWrite) return <>{children}</>
  let reason = 'Checking write access…'
  if (access && !access.writes_enabled) reason = 'Writes are disabled on this server: no write token is configured.'
  else if (access && !access.token_accepted) reason = 'Enter a valid write token (top of the page) to make changes.'
  else if (access && !actor.trim()) reason = 'Enter your name (top of the page): every change records who made it.'
  else if (!access) reason = 'The API is unreachable, so changes cannot be made.'
  return <p className="notice notice-info">{reason}</p>
}

export function LoadState({ loading, error }: { loading: boolean; error: unknown }) {
  if (error) return <ErrorNotice error={error} />
  return loading ? <p className="muted">Loading…</p> : null
}
