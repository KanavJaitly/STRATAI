// Shared dashboard building blocks: page header, tabs whose selection lives in the URL, and team/match links.

import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { ScheduledMatchOut } from '../api/generated'
import { Absent } from './display'
import { teamPath } from './routing'
import type { TabDef } from './useTab'

export function PageHeader({ title, subtitle, actions, crumbs }: { title: ReactNode; subtitle?: ReactNode;
  actions?: ReactNode; crumbs?: { to: string; label: string }[] }) {
  // The browser tab and history name the page (WCAG 2.4.2); taken from the rendered heading so it never disagrees.
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    const text = heading.current?.textContent?.trim()
    document.title = text ? `${text} · STRATAI` : 'STRATAI'
  })
  return (
    <div className="page-header">
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="crumbs">
          <ol>{crumbs.map((c) => <li key={c.to}><Link to={c.to}>{c.label}</Link></li>)}</ol>
        </nav>
      )}
      <div className="page-title-row">
        <h1 ref={heading}>{title}</h1>
        {actions}
      </div>
      {subtitle && <p className="page-subtitle muted">{subtitle}</p>}
    </div>
  )
}

export function Tabs({ tabs, active, onSelect, label }: { tabs: TabDef[]; active: string; onSelect: (id: string) => void;
  label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  // Manual activation (ARIA tabs): arrow keys, Home and End only move focus; Enter or Space (the button's click) opens
  // the tab. Arrowing past a tab therefore never starts that tab's (possibly slow) fetch (P8-R9).
  const onKey = (event: KeyboardEvent, index: number) => {
    const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    const jump = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null
    if (!delta && jump === null) return
    event.preventDefault()
    const next = jump ?? (index + delta + tabs.length) % tabs.length
    refs.current[next]?.focus()
  }
  return (
    <div role="tablist" aria-label={label} className="tabs">
      {tabs.map((tab, i) => (
        <button key={tab.id} type="button" role="tab" id={`tab-${tab.id}`} aria-selected={tab.id === active}
          aria-controls={tab.id === active ? `panel-${tab.id}` : undefined} tabIndex={tab.id === active ? 0 : -1} className="tab"
          ref={(el) => { refs.current[i] = el }} onClick={() => onSelect(tab.id)} onKeyDown={(e) => onKey(e, i)}>
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} className="tab-panel">{children}</div>
}

export function TeamChip({ team, eventKey, tone }: { team: number; eventKey: string; tone?: 'red' | 'blue' }) {
  return <Link to={teamPath(eventKey, team)} className={`chip${tone ? ` chip-${tone}` : ''}`}>{team}</Link>
}

/** One alliance as team chips, labelled with its colour in text (colour is never the only signal). */
export function AllianceTeams({ teams, eventKey, tone }: { teams: number[]; eventKey: string; tone: 'red' | 'blue' }) {
  return (
    <span className="alliance">
      <span className={`alliance-label alliance-${tone}`}>{tone === 'red' ? 'Red' : 'Blue'}</span>
      {teams.length ? teams.map((t) => <TeamChip key={t} team={t} eventKey={eventKey} tone={tone} />)
        : <span className="muted">no teams</span>}
    </span>
  )
}

/** A match's result as served, or why it is withheld at this moment. */
export function ResultCell({ match }: { match: ScheduledMatchOut }) {
  if (!match.result) return <Absent reason={match.result_withheld_reason ?? 'no result'} />
  const { score_red: red, score_blue: blue, winning_alliance: winner } = match.result
  return <span><span className="score-red">{red}</span> – <span className="score-blue">{blue}</span>
    {winner && <span className="muted small"> ({winner === 'tie' ? 'tie' : `${winner} won`})</span>}</span>
}
