import { Link, useParams, useSearchParams } from 'react-router-dom'

import { dashboardApi, type Side } from '../../api/dashboard'
import type { WinProbabilityResponse } from '../../api/generated'
import { useResource } from '../../components/useResource'
import { RecordObservation, SaveCoachStrategy } from '../coachInputs'
import { AllianceTeams, PageHeader } from '../common'
import { CalibratedProbabilityView, EpaSourceNote, ResourceView, When } from '../display'
import { StrategyWorkbench } from '../strategy'
import { ResultCell } from '../common'
import { eventOfMatch, matchLabel, reportPath, seasonOf } from '../routing'

/** P8-M4: the match strategy view for one scheduled match, plus its M6/M7 win probability (a separate model). */
export function MatchPage() {
  const matchKey = useParams().matchKey ?? ''
  const eventKey = eventOfMatch(matchKey)
  const [params, setParams] = useSearchParams()
  const side: Side = params.get('side') === 'blue' ? 'blue' : 'red'
  const matches = useResource((s) => dashboardApi.eventMatches(eventKey, null, s), `matches:${eventKey}:now`)
  const match = matches.data?.matches.find((m) => m.match_key === matchKey) ?? null
  const recommendation = useResource((s) => dashboardApi.matchRecommend(matchKey, { side }, s), `recommend:${matchKey}:${side}`)
  const winProbability = useResource((s) => dashboardApi.matchWinProbability(matchKey, s), `winprob:${matchKey}`)

  const red = recommendation.data?.context.red_team_numbers ?? match?.red_team_numbers ?? []
  const blue = recommendation.data?.context.blue_team_numbers ?? match?.blue_team_numbers ?? []
  const ours = side === 'red' ? red : blue
  const theirs = side === 'red' ? blue : red
  const season = seasonOf(eventKey)
  const setSide = (next: Side) => {
    const nextParams = new URLSearchParams(params)
    nextParams.set('side', next)
    setParams(nextParams)
  }

  return (
    <>
      <PageHeader title={match ? `${matchLabel(match)} · ${eventKey}` : matchKey}
        crumbs={[{ to: season ? `/?season=${season}` : '/', label: season ? `${season} events` : 'Events' },
          { to: `/events/${encodeURIComponent(eventKey)}?tab=matches`, label: eventKey }]}
        subtitle={match ? <>Scheduled <When value={match.scheduled_time} /> · result: <ResultCell match={match} /></> : undefined}
        actions={<Link className="button-link" to={reportPath(matchKey)}>Pre-match report</Link>} />
      {matches.error != null && !match && <ResourceView resource={matches} what="match list">{() => null}</ResourceView>}
      {(red.length > 0 || blue.length > 0) && (
        <p className="alliances-line"><AllianceTeams teams={red} eventKey={eventKey} tone="red" />{' '}
          <span className="muted">vs</span>{' '}<AllianceTeams teams={blue} eventKey={eventKey} tone="blue" /></p>
      )}
      <fieldset className="side-choice">
        <legend>Plan for</legend>
        {(['red', 'blue'] as Side[]).map((s) => (
          <label key={s} className="inline">
            <input type="radio" name="side" value={s} checked={side === s} onChange={() => setSide(s)} />
            {s === 'red' ? 'Red alliance' : 'Blue alliance'}
          </label>
        ))}
      </fieldset>
      {ours.length === 3 || recommendation.loading || recommendation.error
        ? <StrategyWorkbench key={`${side}:${ours.join(',')}`} side={side} recommendation={recommendation} ours={ours} theirs={theirs}
            ops={{ compare: (body, signal) => dashboardApi.matchCompare(matchKey, body, signal) }}
            coachActions={(coach, valid) => ours.length === 3
              ? <SaveCoachStrategy eventKey={eventKey} matchKey={matchKey} strategy={coach} valid={valid} /> : null} />
        : matches.loading ? <p className="loading" role="status">Loading the match…</p>
          : <p className="notice notice-warn">This match does not have three teams per alliance at this moment, so no strategy can be built.</p>}
      <section className="card" aria-labelledby="winprob-heading">
        <h2 id="winprob-heading">Match win probability (statistical model, no strategy)</h2>
        <p className="small muted">The statistical model's chance of each alliance winning, from both alliances' data. It is a separate model from
          the strategy odds above and is never combined with them.</p>
        <ResourceView resource={winProbability} what="win probability">
          {(data) => <WinProbabilityView data={data} />}
        </ResourceView>
      </section>
      {red.length + blue.length > 0 && (
        <section className="card" aria-labelledby="coach-heading">
          <h2 id="coach-heading">Coach inputs</h2>
          <RecordObservation eventKey={eventKey} teams={[...red, ...blue]} />
        </section>
      )}
    </>
  )
}

export function WinProbabilityView({ data }: { data: WinProbabilityResponse }) {
  return (
    <>
      <CalibratedProbabilityView value={data.win_probability} />
      <p className="small">Scope: {data.probability_scope}{data.competition_level ? ` (${data.competition_level})` : ''} · features as of <When value={data.as_of} /></p>
      {data.warning && <p className="notice notice-warn">{data.warning}</p>}
      <p className="small muted">{data.evidence}</p>
      <details>
        <summary>EPA provenance per team</summary>
        <div className="table-scroll">
        <table className="grid compact">
          <thead><tr><th scope="col">Team</th><th scope="col">Alliance</th><th scope="col">EPA from</th><th scope="col">State</th></tr></thead>
          <tbody>
            {data.teams.map((t) => (
              <tr key={t.team_number}>
                <th scope="row">{t.team_number}</th><td>{t.alliance ?? '—'}</td>
                <td>{t.epa_value_source ?? '—'}{t.epa_source_event_key ? ` · ${t.epa_source_event_key}` : ''}</td>
                <td>{t.epa_source_state ?? t.epa_withheld_reason ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </details>
      <EpaSourceNote epa={data.epa} />
    </>
  )
}
