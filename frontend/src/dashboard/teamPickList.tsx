// Our pick list: the team's own order of every candidate at an event, for alliance selection. It starts in scoring-EPA
// order (absent values last) and is reordered with large up/down buttons a thumb can reach. Saved in this browser,
// per event, so it is not shared between devices; a shared list needs the API. It only orders teams: every value
// shown is the candidate profile's, as served.

import { useEffect, useMemo, useState } from 'react'

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

/** The stored order, kept to teams on this roster, with any team it lacks appended in the default order. */
function initialOrder(eventKey: string, candidates: CandidateOut[]): number[] {
  const roster = new Set(candidates.map((c) => c.team_number))
  const stored = readStored(eventKey).filter((t) => roster.has(t))
  const seen = new Set(stored)
  return [...stored, ...defaultOrder(candidates).filter((t) => !seen.has(t))]
}

function Metric({ factor, label, digits }: { factor: FactorOut; label: string; digits: number }) {
  return (
    <span className="pick-metric">
      <span className="pick-metric-value">{factor.value === null ? '—' : formatNumber(factor.value, digits)}</span>
      <span className="pick-metric-label">{label}</span>
    </span>
  )
}

export function TeamPickList({ data }: { data: CandidatesResponse }) {
  const ours = useOurTeam()
  const byTeam = useMemo(() => new Map(data.candidates.map((c) => [c.team_number, c])), [data.candidates])
  const [order, setOrder] = useState(() => initialOrder(data.event_key, data.candidates))
  const [moved, setMoved] = useState<number | null>(null)
  useEffect(() => { writeStored(data.event_key, order) }, [data.event_key, order])

  const move = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= order.length) return
    const next = [...order]
    ;[next[index], next[target]] = [next[target], next[index]]
    setOrder(next)
    setMoved(next[target])
  }
  const reset = () => { setOrder(defaultOrder(data.candidates)); setMoved(null) }

  return (
    <section className="card pick-list-card" aria-labelledby="our-picklist-heading">
      <div className="card-head">
        <h2 id="our-picklist-heading">Our pick list</h2>
        <button type="button" className="secondary" onClick={reset}>Reset to EPA order</button>
      </div>
      <p className="small muted">Saved on this device. Starts in scoring EPA order; move teams with the arrows.</p>
      <ol className="pick-list" aria-label="Our pick list, in order">
        {order.map((team, i) => {
          const c = byTeam.get(team)
          if (!c) return null
          return (
            <li key={team} className={[ourRowClass(team, ours), moved === team ? 'just-moved' : ''].filter(Boolean).join(' ') || undefined}>
              <span className="pick-rank" aria-hidden="true">{i + 1}</span>
              <span className="pick-team">
                <PageLink to={teamPath(data.event_key, team)}>{team}</PageLink><OursMark team={team} ours={ours} />
              </span>
              <span className="pick-metrics">
                {KEY_METRICS.map((m) => <Metric key={m.key} factor={c[m.key]} label={m.label} digits={m.digits} />)}
              </span>
              <span className="pick-move">
                <button type="button" className="secondary icon-button" onClick={() => move(i, -1)} disabled={i === 0}
                  aria-label={`Move ${team} up to ${i}`}><Icon name="arrow-up" /></button>
                <button type="button" className="secondary icon-button" onClick={() => move(i, 1)} disabled={i === order.length - 1}
                  aria-label={`Move ${team} down to ${i + 2}`}><Icon name="arrow-down" /></button>
              </span>
            </li>
          )
        })}
      </ol>
      <p role="status" className="visually-hidden">{moved !== null ? `${moved} is now number ${order.indexOf(moved) + 1}` : ''}</p>
    </section>
  )
}
