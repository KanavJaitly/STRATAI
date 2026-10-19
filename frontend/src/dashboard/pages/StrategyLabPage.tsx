import { useState, type FormEvent } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'

import { dashboardApi, type HypotheticalAlliances, type Side } from '../../api/dashboard'
import { useResource } from '../../components/useResource'
import { AsOfControl } from '../asOf'
import { PageHeader } from '../common'
import { ResourceView } from '../display'
import { StrategyWorkbench } from '../strategy'
import { WinProbabilityView } from './MatchPage'
import { useAsOf } from '../asOfParams'
import { seasonOf } from '../routing'

function parseTeams(value: string | null): number[] {
  return (value ?? '').split(',').map((v) => Number(v.trim())).filter((n) => Number.isInteger(n) && n > 0)
}

/** P8-M4 (b): a hypothetical 3 v 3 pairing at an event, through the same engine path as a scheduled match. */
export function StrategyLabPage() {
  const eventKey = useParams().eventKey ?? ''
  const [params, setParams] = useSearchParams()
  const [asOf] = useAsOf()
  const red = parseTeams(params.get('red'))
  const blue = parseTeams(params.get('blue'))
  const context = params.get('context') === 'playoff' ? 'playoff' : 'qualification'
  const side: Side = params.get('side') === 'blue' ? 'blue' : 'red'
  const roster = useResource((s) => dashboardApi.eventTeams(eventKey, s), `teams:${eventKey}`)
  const all = [...red, ...blue]
  const ready = red.length === 3 && blue.length === 3 && new Set(all).size === 6
  const pairing: HypotheticalAlliances = { event_key: eventKey, red_team_numbers: red, blue_team_numbers: blue, match_context: context }
  const key = `${eventKey}:${red.join(',')}:${blue.join(',')}:${context}:${asOf}`
  const recommendation = useResource((s) => dashboardApi.hypotheticalRecommend({ ...pairing, side }, asOf, s),
    `hyp:${key}:${side}`, ready)
  const winProbability = useResource((s) => dashboardApi.allianceWinProbability(pairing, asOf, s), `hypwin:${key}`, ready)
  const season = seasonOf(eventKey)

  const [draft, setDraft] = useState({ red: red.map(String), blue: blue.map(String), context })
  const choose = (event: FormEvent) => {
    event.preventDefault()
    const next = new URLSearchParams(params)
    next.set('red', draft.red.filter(Boolean).join(','))
    next.set('blue', draft.blue.filter(Boolean).join(','))
    next.set('context', draft.context)
    setParams(next)
  }
  const teamOptions = roster.data?.teams.map((t) => t.team_number) ?? []
  const picker = (color: 'red' | 'blue') => [0, 1, 2].map((i) => (
    <label key={`${color}${i}`} className="inline">{color === 'red' ? 'Red' : 'Blue'} {i + 1}
      <select value={draft[color][i] ?? ''} onChange={(e) => {
        const list = [...draft[color]]
        list[i] = e.target.value
        setDraft({ ...draft, [color]: list })
      }}>
        <option value="">—</option>
        {teamOptions.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
    </label>
  ))
  const draftTeams = [...draft.red, ...draft.blue].filter(Boolean)
  const draftValid = draft.red.filter(Boolean).length === 3 && draft.blue.filter(Boolean).length === 3
    && new Set(draftTeams).size === 6

  return (
    <>
      <PageHeader title="Strategy lab" subtitle="A hypothetical pairing, evaluated by the same engine and model as a scheduled match."
        crumbs={[{ to: season ? `/?season=${season}` : '/', label: season ? `${season} events` : 'Events' },
          { to: `/events/${encodeURIComponent(eventKey)}`, label: eventKey }]} />
      <section className="card" aria-labelledby="pairing-heading">
        <h2 id="pairing-heading">Pairing</h2>
        <ResourceView resource={roster} what="event roster">
          {() => (
            <form onSubmit={choose}>
              <div className="form-row">{picker('red')}</div>
              <div className="form-row">{picker('blue')}</div>
              <div className="form-row">
                <label className="inline">Match context
                  <select value={draft.context} onChange={(e) => setDraft({ ...draft, context: e.target.value as typeof context })}>
                    <option value="qualification">Qualification</option>
                    <option value="playoff">Playoff</option>
                  </select>
                </label>
                <button type="submit" disabled={!draftValid}>Evaluate pairing</button>
              </div>
              <p className="small muted">Choose six different teams, three per alliance.</p>
            </form>
          )}
        </ResourceView>
        <AsOfControl defaultNote="Default: now." />
      </section>
      {ready && (
        <>
          <fieldset className="side-choice">
            <legend>Plan for</legend>
            {(['red', 'blue'] as Side[]).map((s) => (
              <label key={s} className="inline">
                <input type="radio" name="side" value={s} checked={side === s}
                  onChange={() => { const next = new URLSearchParams(params); next.set('side', s); setParams(next) }} />
                {s === 'red' ? 'Red alliance' : 'Blue alliance'}
              </label>
            ))}
          </fieldset>
          <StrategyWorkbench key={`${side}:${red.join(',')}:${blue.join(',')}:${context}:${asOf}`} side={side} recommendation={recommendation} ours={side === 'red' ? red : blue}
            theirs={side === 'red' ? blue : red}
            ops={{ compare: (body, signal) => dashboardApi.hypotheticalCompare({ ...pairing, ...body }, asOf, signal) }} />
          <section className="card" aria-labelledby="hyp-winprob">
            <h2 id="hyp-winprob">Win probability for this pairing (statistical model, no strategy)</h2>
            <ResourceView resource={winProbability} what="win probability">
              {(data) => <WinProbabilityView data={data} />}
            </ResourceView>
          </section>
        </>
      )}
    </>
  )
}
