// Our pick list: the team's own order of every candidate at an event, for alliance selection. It starts in scoring-EPA
// order (absent values last). Reorder with the up/down buttons (a thumb), by tapping a rank and typing a new one, or by
// dragging a row on a laptop. Saved in this browser per event and NOT synced between devices; "Copy list" and
// "Import list" move it by text. Server syncing is a follow-up (docs/pick_list_sync.md). It only orders teams: every
// value shown is the candidate profile's, as served.

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type DragEvent, type FormEvent, type KeyboardEvent } from 'react'

import type { CandidateOut, CandidatesResponse, FactorOut } from '../api/generated'
import { PageLink } from '../auth/guards'
import { Icon } from '../components/icons'
import { OursMark } from '../team/OursMark'
import { ourRowClass, useOurTeam } from '../team/ours'
import { formatNumber } from './labels'
import { teamPath } from './routing'

const KEY_METRICS: { key: 'scoring_epa' | 'average_score' | 'defense'; label: string; digits: number }[] = [
  { key: 'scoring_epa', label: 'EPA', digits: 1 },
  { key: 'average_score', label: 'Avg score', digits: 1 },
  { key: 'defense', label: 'Defense', digits: 2 },
]

const storageKey = (eventKey: string) => `stratai.picklist.${eventKey}`

function readStored(eventKey: string): number[] {
  try {
    const raw = window.localStorage.getItem(storageKey(eventKey))
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((n): n is number => Number.isInteger(n)) : []
  } catch {
    return [] // private window, blocked storage: start from the default order
  }
}

function writeStored(eventKey: string, order: number[]) {
  try { window.localStorage.setItem(storageKey(eventKey), JSON.stringify(order)) } catch { /* not saved; still usable */ }
}

/** Scoring EPA, highest first; teams without one last, by number. */
function defaultOrder(candidates: CandidateOut[]): number[] {
  return [...candidates].sort((a, b) => {
    const av = a.scoring_epa.value
    const bv = b.scoring_epa.value
    if (av === null && bv === null) return a.team_number - b.team_number
    if (av === null) return 1
    if (bv === null) return -1
    return bv - av || a.team_number - b.team_number
  }).map((c) => c.team_number)
}

/** `wanted` kept to teams on this roster (each once), then every roster team it lacks, in `fallback` order. */
function onRoster(wanted: number[], roster: number[], fallback: number[]): number[] {
  const allowed = new Set(roster)
  const seen = new Set<number>()
  const kept = wanted.filter((t) => allowed.has(t) && !seen.has(t) && seen.add(t))
  return [...kept, ...fallback.filter((t) => !seen.has(t))]
}

/** Move the team at `from` to position `to` (both 0-based), shifting the teams between. */
function moved(order: number[], from: number, to: number): number[] {
  const next = [...order]
  const [team] = next.splice(from, 1)
  next.splice(Math.max(0, Math.min(to, next.length)), 0, team)
  return next
}

/** One line that pastes anywhere (a message, a note) and imports back: the event, then the teams in order. */
function listText(eventKey: string, order: number[]): string {
  return `StratAI pick list ${eventKey}: ${order.join(', ')}`
}

function parseList(text: string, eventKey: string): number[] {
  const body = text.replace(`StratAI pick list ${eventKey}:`, '').replace(/StratAI pick list \S+:/, '')
  return (body.match(/\d+/g) ?? []).map(Number).filter((n) => Number.isInteger(n) && n > 0)
}

function Metric({ factor, label, digits }: { factor: FactorOut; label: string; digits: number }) {
  return (
    <span className="pick-metric">
      <span className="pick-metric-value">{factor.value === null ? '—' : formatNumber(factor.value, digits)}</span>
      <span className="pick-metric-label">{label}</span>
    </span>
  )
}

/** The rank: a button that turns into a number field to jump the team to another rank. */
function RankControl({ team, rank, total, onJump }: { team: number; rank: number; total: number;
  onJump: (to: number) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(rank))
  if (!editing) {
    return (
      <button type="button" className="pick-rank" onClick={() => { setDraft(String(rank)); setEditing(true) }}
        aria-label={`Rank ${rank}: move ${team} to another rank`}>{rank}</button>
    )
  }
  const commit = (event?: FormEvent) => {
    event?.preventDefault()
    if (!editing) return
    const to = Number(draft)
    if (Number.isInteger(to) && to >= 1 && to <= total && to !== rank) onJump(to)
    setEditing(false)
  }
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') setEditing(false)
    if (event.key === 'Enter') { event.preventDefault(); commit() }
  }
  return (
    <form className="pick-rank-form" onSubmit={commit}>
      <input type="number" inputMode="numeric" min={1} max={total} value={draft} autoFocus aria-label={`New rank for ${team}`}
        onChange={(e) => setDraft(e.target.value)} onBlur={() => commit()} onKeyDown={onKey} />
    </form>
  )
}

export function TeamPickList({ data }: { data: CandidatesResponse }) {
  const ours = useOurTeam()
  const roster = useMemo(() => data.candidates.map((c) => c.team_number), [data.candidates])
  const byTeam = useMemo(() => new Map(data.candidates.map((c) => [c.team_number, c])), [data.candidates])
  const [order, setOrder] = useState(() => onRoster(readStored(data.event_key), roster, defaultOrder(data.candidates)))
  const [last, setLast] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [importing, setImporting] = useState(false)
  const [importText, setImportText] = useState('')
  const [dragging, setDragging] = useState<number | null>(null)
  const [dropAt, setDropAt] = useState<number | null>(null)
  useEffect(() => { writeStored(data.event_key, order) }, [data.event_key, order])
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return undefined
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  // Reordering animates so you can see which team moved (FLIP): after the new order renders, each row that changed
  // place starts at its old position and slides to the new one. The order itself is already final; the motion only
  // shows it. Off for reduced motion.
  const rows = useRef(new Map<number, HTMLLIElement>())
  const tops = useRef(new Map<number, number>())
  useLayoutEffect(() => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? true
    const next = new Map<number, number>()
    for (const [team, el] of rows.current) {
      const top = el.getBoundingClientRect().top - (el.parentElement?.getBoundingClientRect().top ?? 0) // within the list
      next.set(team, top)
      const before = tops.current.get(team)
      if (!reduce && before !== undefined && before !== top && typeof el.animate === 'function') {
        el.animate([{ transform: `translateY(${before - top}px)` }, { transform: 'translateY(0)' }],
          { duration: 250, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' })
      }
    }
    tops.current = next
  }, [order])

  const place = (from: number, to: number) => {
    if (from === to || to < 0 || to >= order.length) return
    const next = moved(order, from, to)
    setOrder(next)
    setLast(next[to])
    setMessage(`${next[to]} is now number ${to + 1}`)
  }
  const reset = () => { setOrder(defaultOrder(data.candidates)); setLast(null); setMessage('Back to scoring EPA order') }

  const copy = async () => {
    const text = listText(data.event_key, order)
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setMessage('Copied. Paste it into Import list on the other device.')
    } catch {
      setImportText(text) // no clipboard access: show the text to copy by hand
      setImporting(true)
      setMessage('Copy the text below by hand.')
    }
  }
  const applyImport = (event: FormEvent) => {
    event.preventDefault()
    const wanted = parseList(importText, data.event_key)
    if (wanted.length === 0) { setMessage('No team numbers found in that text.'); return }
    const allowed = new Set(roster)
    const skipped = [...new Set(wanted.filter((t) => !allowed.has(t)))]
    setOrder(onRoster(wanted, roster, order))
    setImporting(false)
    setImportText('')
    setLast(null)
    setMessage(`Imported ${wanted.length - skipped.length} teams in order${skipped.length
      ? `; skipped ${skipped.length} not at this event (${skipped.join(', ')})` : ''}`)
  }

  // Dragging rows (a mouse or trackpad; touch uses the buttons and the rank field)
  const onDragStart = (event: DragEvent, index: number) => {
    setDragging(index)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(order[index]))
  }
  const onDragOver = (event: DragEvent, index: number) => {
    if (dragging === null) return
    event.preventDefault()
    if (dropAt !== index) setDropAt(index)
  }
  const onDrop = (event: DragEvent, index: number) => {
    event.preventDefault()
    if (dragging !== null) place(dragging, index)
    setDragging(null)
    setDropAt(null)
  }

  return (
    <section className="card pick-list-card" aria-labelledby="our-picklist-heading">
      <div className="card-head">
        <h2 id="our-picklist-heading">Our pick list</h2>
        <div className="header-actions">
          <button type="button" className="secondary" onClick={() => void copy()}>
            <span className={`icon-swap${copied ? ' is-swapped' : ''}`} aria-hidden="true">
              <Icon name="copy" className="icon-a" /><Icon name="check" className="icon-b" /></span>Copy list</button>
          <button type="button" className="secondary" aria-expanded={importing} onClick={() => setImporting(!importing)}>
            Import list</button>
          <button type="button" className="secondary" onClick={reset}>Reset to EPA order</button>
        </div>
      </div>
      <p className="small muted">Saved on this device only, not synced between devices yet: use Copy list and Import list to
        move it. Tap a rank to type a new one; on a laptop, drag a row.</p>
      {importing && (
        <form className="pick-import" onSubmit={applyImport} aria-label="Import a pick list">
          <label>Paste a copied pick list (or any team numbers, in order)
            <textarea value={importText} onChange={(e) => setImportText(e.target.value)} rows={3} />
          </label>
          <div className="actions">
            <button type="submit">Use this order</button>
            <button type="button" className="secondary" onClick={() => { setImporting(false); setImportText('') }}>Cancel</button>
          </div>
        </form>
      )}
      <p role="status" className="pick-message small">{message}</p>
      <ol className="pick-list" aria-label="Our pick list, in order">
        {order.map((team, i) => {
          const c = byTeam.get(team)
          if (!c) return null
          const classes = [ourRowClass(team, ours), last === team ? 'just-moved' : '', dragging === i ? 'dragging' : '',
            dropAt === i && dragging !== null && dragging !== i ? (dragging < i ? 'drop-below' : 'drop-above') : '']
          return (
            <li key={team} className={classes.filter(Boolean).join(' ') || undefined} draggable
              ref={(el) => { if (el) rows.current.set(team, el); else rows.current.delete(team) }}
              onDragStart={(e) => onDragStart(e, i)} onDragOver={(e) => onDragOver(e, i)} onDrop={(e) => onDrop(e, i)}
              onDragEnd={() => { setDragging(null); setDropAt(null) }}>
              <span className="pick-grip" aria-hidden="true"><Icon name="grip" /></span>
              <RankControl team={team} rank={i + 1} total={order.length} onJump={(to) => place(i, to - 1)} />
              <span className="pick-team">
                <PageLink to={teamPath(data.event_key, team)}>{team}</PageLink><OursMark team={team} ours={ours} />
              </span>
              <span className="pick-metrics">
                {KEY_METRICS.map((m) => <Metric key={m.key} factor={c[m.key]} label={m.label} digits={m.digits} />)}
              </span>
              <span className="pick-move">
                <button type="button" className="secondary icon-button" onClick={() => place(i, i - 1)} disabled={i === 0}
                  aria-label={`Move ${team} up to ${i}`}><Icon name="arrow-up" /></button>
                <button type="button" className="secondary icon-button" onClick={() => place(i, i + 1)} disabled={i === order.length - 1}
                  aria-label={`Move ${team} down to ${i + 2}`}><Icon name="arrow-down" /></button>
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
