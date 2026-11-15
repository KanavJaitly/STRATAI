// Phase 11 follow-up (docs/phase11.md §"Team profiles on the live draft page"): one team's profile in a slide-over
// drawer on the live draft page. The page underneath stays mounted, so its draft state is kept: the selected tile, a
// pending action, the scroll position, the record, the recommendations, and the polling with its stale and updated
// indicators.
//
// Everything shown comes from locked read operations, the same ones the team page uses, read as of the record's
// selection moment (strictly before it):
// - GET /teams/{team}/events/{event}/strength: EPA, scoring, consistency, reliability, defense and feeding;
// - GET /events/{event}/matches: the per-match scores and the won / lost / tied record;
// - the same strength operation at the team's earlier events this season, for the trend by event.
// Nothing is computed here that the server did not serve, except counting wins and losses.

import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { dashboardApi } from '../api/dashboard'
import type { EventMatchesResponse, ScoutingView, TeamStrengthResponse } from '../api/generated'
import { useResource } from '../components/useResource'
import { BarChart, type ChartPoint } from '../dashboard/charts'
import { Absent, EpaSourceNote, MeasureValue, ResourceView, ValidationBadge, When } from '../dashboard/display'
import { matchLabel } from '../dashboard/routing'
import { outcome, ownColour, teamResults } from '../dashboard/teamResults'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea, '
  + 'summary, [tabindex]:not([tabindex="-1"])'

/** Whether Tab can reach the element: not hidden, and not inside a closed <details> (other than its own summary). */
function reachable(el: HTMLElement): boolean {
  if (el.closest('[hidden]')) return false
  const closed = el.closest('details:not([open])')
  return !closed || (el.tagName === 'SUMMARY' && el.parentElement === closed)
}

export interface ProfileContextInfo {
  /** The team's final qualification rank from the record's setup. */
  rank: number | null
  /** Where the team stands on the board right now (e.g. "available", "picked by alliance 3"). */
  standing: string
  /** Why the team is (or is not) in the current picks, as served. */
  why: string[]
  /** The projected score with your alliance, or why there is none. */
  projection: ReactNode
}

export function TeamProfileDrawer({ team, eventKey, asOf, asOfNote, info, boardStatus, onClose, fullProfileTo,
  onFullProfile }: {
  team: number
  eventKey: string
  /** The as-of every read uses (the selection moment), or null for now. */
  asOf: string | null
  asOfNote: string
  info: ProfileContextInfo
  /** The board's record version and the picks' freshness, so they stay visible while the drawer is open. */
  boardStatus: ReactNode
  onClose: () => void
  /** The team page, carrying the way back (?from=live-draft&event=…). */
  fullProfileTo: string
  /** Opens it, after stamping the live page's history entry with its selected tile and scroll position. */
  onFullProfile: () => void
}) {
  const panel = useRef<HTMLDivElement>(null)
  const close = useRef<HTMLButtonElement>(null)
  const heading = `profile-title-${team}`
  // Focus moves into the drawer when it opens or shows another team (the page re-keys it by team).
  useEffect(() => { close.current?.focus() }, [])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab' || !panel.current) return
    const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(reachable)
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }

  const strength = useResource((s) => dashboardApi.teamStrength(team, eventKey, asOf, s),
    `drawer-strength:${team}:${eventKey}:${asOf}`)
  const matches = useResource((s) => dashboardApi.eventMatches(eventKey, asOf, s), `drawer-matches:${eventKey}:${asOf}`)
  const earlier = (strength.data?.strength.auto_points.season_by_event ?? []).map((e) => e.event_key)
    .filter((key) => key !== eventKey)
  const season = useResource((s) => Promise.all(earlier.map((key) => dashboardApi.teamStrength(team, key, asOf, s))),
    `drawer-season:${team}:${earlier.join(',')}:${asOf}`, strength.data !== null)

  return (
    <>
      <div className="profile-backdrop" aria-hidden="true" onClick={onClose} />
      <div ref={panel} className="profile-drawer" role="dialog" aria-modal="true" aria-labelledby={heading}
        onKeyDown={onKeyDown}>
        <div className="drawer-head">
          <h2 id={heading}>Team {team}</h2>
          <button ref={close} type="button" className="button-secondary drawer-close" onClick={onClose}>Close</button>
        </div>
        <p className="small">Qualification rank: {info.rank !== null ? <strong>{info.rank}</strong>
          : <Absent reason="not in the record's final ranks" />} · {info.standing}</p>
        <p className="small muted">{asOfNote}</p>
        <div className="small drawer-board-status">{boardStatus}</div>

        <section aria-labelledby={`${heading}-why`}>
          <h3 id={`${heading}-why`}>In your picks</h3>
          <ul className="small">{info.why.map((line) => <li key={line}>{line}</li>)}</ul>
        </section>
        <section aria-labelledby={`${heading}-projection`}>
          <h3 id={`${heading}-projection`}>Projected score with your alliance</h3>
          {info.projection}
        </section>

        <ResourceView resource={matches} what="match history">
          {(data) => <MatchesPart data={data} team={team} heading={heading} />}
        </ResourceView>
        <ResourceView resource={strength} what="strength view">
          {(data) => <StrengthPart data={data} heading={heading} />}
        </ResourceView>
        {strength.data && (
          <ResourceView resource={season} what="earlier events this season">
            {(data) => <SeasonPart current={strength.data!} earlier={data} heading={heading} />}
          </ResourceView>
        )}

        <p className="drawer-foot">
          <Link to={fullProfileTo} className="button button-secondary"
            onClick={(e) => { e.preventDefault(); onFullProfile() }}>View full profile</Link>
        </p>
      </div>
    </>
  )
}

function MatchesPart({ data, team, heading }: { data: EventMatchesResponse; team: number; heading: string }) {
  const r = teamResults(data, team)
  return (
    <section aria-labelledby={`${heading}-matches`}>
      <h3 id={`${heading}-matches`}>Matches at this event</h3>
      {r.mine.length === 0 ? <p className="empty small">No matches for this team before this moment.</p> : (
        <>
          <p className="small">Record: <strong>{r.wins}–{r.losses}–{r.ties}</strong> (won–lost–tied) in {r.played.length}
            {' '}played{r.noWinner > 0 ? ` · ${r.noWinner} without a recorded winner` : ''}
            {r.mine.length > r.played.length ? ` · ${r.mine.length - r.played.length} without a result yet` : ''}.</p>
          <BarChart title="Alliance score in each match" unit="points" points={r.points} digits={0} height={180} />
          <div className="table-scroll">
            <table className="grid compact">
              <caption className="visually-hidden">Team {team}&apos;s matches: its alliance and score</caption>
              <thead><tr><th scope="col">Match</th><th scope="col">Alliance</th><th scope="col">Alliance score</th>
                <th scope="col">Result</th></tr></thead>
              <tbody>
                {r.mine.map((m) => {
                  const colour = ownColour(m, team)
                  const score = m.result ? (colour === 'red' ? m.result.score_red : m.result.score_blue) : null
                  return (
                    <tr key={m.match_key}>
                      <th scope="row">{matchLabel(m)}</th>
                      <td>{colour === 'red' ? 'Red' : 'Blue'}</td>
                      <td>{score === null ? <Absent reason={m.result_withheld_reason ?? 'no result'} /> : score}</td>
                      <td>{m.result ? outcome(m, team) : <span className="muted">—</span>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="small muted">Scores are the whole alliance&apos;s, not this team&apos;s own.</p>
        </>
      )}
    </section>
  )
}

function ScoutingLine({ label, view }: { label: string; view: ScoutingView }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{view.score.value === null ? <>not enough scouting <Absent reason={view.score.absent_reason} /></>
        : <><MeasureValue measure={view.score} digits={2} /> · agreement <MeasureValue measure={view.agreement} digits={2} />
          {' '}<ValidationBadge validation={{ status: view.validation_status }} compact /></>}</dd>
    </>
  )
}

function StrengthPart({ data, heading }: { data: TeamStrengthResponse; heading: string }) {
  const view = data.strength
  const epa = view.epa
  const s = view.scoring
  const withheld = !!epa.withheld_reason
  return (
    <>
      <section aria-labelledby={`${heading}-epa`}>
        <h3 id={`${heading}-epa`}>EPA</h3>
        {withheld && <p className="small">EPA withheld: <Absent reason={epa.withheld_reason} /></p>}
        <dl className="facts">
          <dt>Total</dt><dd><MeasureValue measure={epa.total} hideReason={withheld} /></dd>
          <dt>Auto</dt><dd><MeasureValue measure={epa.auto} hideReason={withheld} /></dd>
          <dt>Teleop</dt><dd><MeasureValue measure={epa.teleop} hideReason={withheld} /></dd>
          <dt>Endgame</dt><dd><MeasureValue measure={epa.endgame} hideReason={withheld} /></dd>
          <dt>Source</dt><dd className="small">{[epa.epa_value_source, epa.source_event_key && `from ${epa.source_event_key}`,
            epa.epa_source_state].filter(Boolean).join(' · ') || <Absent />}</dd>
        </dl>
        <EpaSourceNote epa={data.epa} />
      </section>
      <section aria-labelledby={`${heading}-scoring`}>
        <h3 id={`${heading}-scoring`}>Scoring at this event</h3>
        <dl className="facts">
          <dt>Average score</dt><dd><MeasureValue measure={s.average_score} /></dd>
          <dt>Spread (SD)</dt><dd><MeasureValue measure={s.score_stddev} /></dd>
          <dt>Consistency</dt><dd><MeasureValue measure={s.consistency_rating} /></dd>
          <dt>Reliability (estimate)</dt><dd><MeasureValue measure={s.reliability_score} /></dd>
          <dt>Matches considered</dt><dd>{s.matches_considered}</dd>
        </dl>
        <p className="small muted">Phase 3 measures from the alliance&apos;s score in each match. Consistency is
          100 × (1 − SD / average); reliability is the share of scheduled matches with a recorded result. Neither is
          shown for fewer matches than Phase 3 needs; neither is ever filled in.</p>
      </section>
      <section aria-labelledby={`${heading}-scouting`}>
        <h3 id={`${heading}-scouting`}>Defense and feeding</h3>
        <dl className="facts">
          <ScoutingLine label="Defense" view={view.defense} />
          <ScoutingLine label="Feeding" view={view.feeding} />
        </dl>
        <p className="small muted">Measured only from scouting observations, never inferred from scoring.</p>
      </section>
      <p className="small muted">Strength view as of <When value={view.as_of} />.</p>
    </>
  )
}

function SeasonPart({ current, earlier, heading }: { current: TeamStrengthResponse; earlier: TeamStrengthResponse[];
  heading: string }) {
  const views = [...earlier.map((e) => e.strength), current.strength]
  const points: ChartPoint[] = views.map((v) => ({ label: v.event_key, value: v.scoring.average_score.value,
    note: v.scoring.average_score.absent_reason }))
  return (
    <section aria-labelledby={`${heading}-season`}>
      <h3 id={`${heading}-season`}>This season, by event</h3>
      {views.length < 2 ? <p className="small muted">No earlier event this season before this moment.</p> : (
        <BarChart title="Average alliance score by event" unit="points" points={points} height={180} />
      )}
    </section>
  )
}
