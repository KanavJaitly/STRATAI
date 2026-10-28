import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { dashboardApi } from '../../api/dashboard'
import type { EventAnalysisResponse, EventMatchesResponse, EventTeamsResponse, LabelledTeams, Measure, QualificationForecastResponse, TeamStrengthView } from '../../api/generated'
import { useResource } from '../../components/useResource'
import { AsOfControl } from '../asOf'
import { AllianceTeams, PageHeader, TabPanel, Tabs, TeamChip } from '../common'
import { Absent, CalibratedProbabilityView, EpaSourceNote, MeasureValue, ResourceView, ValidationBadge, When } from '../display'
import { useAsOf } from '../asOfParams'
import { ResultCell } from '../common'
import { formatNumber, sharedAbsence } from '../labels'
import { matchLabel, matchPath, reportPath, seasonOf, teamPath } from '../routing'
import { useTab } from '../useTab'

const TABS = [
  { id: 'rankings', label: 'Rankings & contenders' },
  { id: 'teams', label: 'Teams' },
  { id: 'matches', label: 'Matches' },
  { id: 'forecast', label: 'Qualification forecast' },
]

/** A tab's data is fetched the first time the tab is opened, then kept (no refetch on switching back). */
function useVisited(active: string): (id: string) => boolean {
  const [visited, setVisited] = useState<Set<string>>(() => new Set([active]))
  if (!visited.has(active)) setVisited(new Set([...visited, active]))
  return (id) => visited.has(id) || id === active
}

export function EventPage() {
  const eventKey = useParams().eventKey ?? ''
  const [asOf] = useAsOf()
  const [tab, setTab] = useTab(TABS)
  const visited = useVisited(tab)
  const season = seasonOf(eventKey)
  const events = useResource((signal) => dashboardApi.events(season ?? 0, signal), `events:${season}`, season !== null)
  const event = events.data?.events.find((e) => e.event_key === eventKey)

  const analysis = useResource((s) => dashboardApi.eventAnalysis(eventKey, asOf, s), `analysis:${eventKey}:${asOf}`,
    visited('rankings'))
  const teams = useResource((s) => dashboardApi.eventTeams(eventKey, s), `teams:${eventKey}`, visited('teams'))
  const matches = useResource((s) => dashboardApi.eventMatches(eventKey, asOf, s), `matches:${eventKey}:${asOf}`,
    visited('matches'))
  const forecast = useResource((s) => dashboardApi.qualificationForecast(eventKey, asOf, s),
    `forecast:${eventKey}:${asOf}`, visited('forecast'))

  return (
    <>
      <PageHeader
        crumbs={[{ to: season ? `/?season=${season}` : '/', label: season ? `${season} events` : 'Events' }]}
        title={event?.name ?? eventKey}
        subtitle={<><code>{eventKey}</code>{event?.start_date && <> · {event.start_date}{event.end_date && event.end_date !== event.start_date ? ` – ${event.end_date}` : ''}</>}
          {event && [event.city, event.state_province, event.country].some(Boolean) && <> · {[event.city, event.state_province, event.country].filter(Boolean).join(', ')}</>}</>}
        actions={<span className="header-actions">
          <Link className="button-link" to={`/events/${encodeURIComponent(eventKey)}/alliance-selection`}>Alliance selection</Link>
          <Link className="button-link" to={`/events/${encodeURIComponent(eventKey)}/strategy-lab`}>Strategy lab</Link>
        </span>}
      />
      <AsOfControl defaultNote="Default: now (each part is computed from data available before the moment)." />
      {tab === 'teams' && <p className="small muted">The roster does not depend on the moment.</p>}
      <Tabs tabs={TABS} active={tab} onSelect={setTab} label="Event views" />
      {tab === 'rankings' && <TabPanel id="rankings"><ResourceView resource={analysis} what="event analysis"
        loadingText="Computing the event analysis (this can take several seconds)…">
        {(data) => <AnalysisView data={data} eventKey={eventKey} />}</ResourceView></TabPanel>}
      {tab === 'teams' && <TabPanel id="teams"><ResourceView resource={teams} what="teams">
        {(data) => <TeamsView data={data} />}</ResourceView></TabPanel>}
      {tab === 'matches' && <TabPanel id="matches"><ResourceView resource={matches} what="matches">
        {(data) => <MatchesView data={data} asOf={asOf} />}</ResourceView></TabPanel>}
      {tab === 'forecast' && <TabPanel id="forecast"><ResourceView resource={forecast} what="qualification forecast">
        {(data) => <ForecastView data={data} />}</ResourceView></TabPanel>}
    </>
  )
}

function Labelled({ title, teams, eventKey }: { title: string; teams: LabelledTeams; eventKey: string }) {
  return (
    <div className="contender-group">
      <h3>{title}</h3>
      <p className="small">Label: <ValidationBadge validation={{ status: teams.validation_status }} compact /></p>
      {teams.team_numbers.length
        ? <p className="chips">{teams.team_numbers.map((t) => <TeamChip key={t} team={t} eventKey={eventKey} />)}</p>
        : <p className="muted">None.</p>}
      <p className="small muted">{teams.evidence}</p>
    </div>
  )
}

export function AnalysisView({ data, eventKey }: { data: EventAnalysisResponse; eventKey: string }) {
  const ordering = data.ordering
  const columns: { name: string; of: (v: TeamStrengthView) => Measure; digits?: number }[] = [
    { name: 'EPA total', of: (v) => v.epa.total }, { name: 'Average score', of: (v) => v.scoring.average_score },
    { name: 'Consistency', of: (v) => v.scoring.consistency_rating },
    { name: 'Reliability (estimate)', of: (v) => v.scoring.reliability_score },
    { name: 'Defense', of: (v) => v.defense.score, digits: 2 },
  ]
  const shared = Object.fromEntries(columns.map((c) => [c.name, sharedAbsence(data.team_comparison.teams.map(c.of))]))
  const [sortKey, setSortKey] = useState('team_number')
  const [descending, setDescending] = useState(false)
  const sorted = useMemo(() => {
    const column = columns.find((c) => c.name === sortKey)
    const sign = descending ? -1 : 1
    return [...data.team_comparison.teams].sort((a, b) => {
      if (!column) return sign * (a.team_number - b.team_number)
      const av = column.of(a).value
      const bv = column.of(b).value
      if (av === null && bv === null) return a.team_number - b.team_number
      if (av === null) return 1 // absent values sort last in either direction, never as zero
      if (bv === null) return -1
      return sign * (av - bv) || a.team_number - b.team_number
    })
  }, [data.team_comparison.teams, sortKey, descending]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <section className="card" aria-labelledby="ordering-heading">
        <div className="card-head">
          <h2 id="ordering-heading">Predicted rankings</h2>
          <ValidationBadge validation={{ status: ordering.validation_status }} compact />
        </div>
        <p className="small">
          Ordered by <strong>{ordering.model === 'raw_epa' ? 'raw EPA' : 'the trained ranking model'}</strong>
          {ordering.switch_time && <> · switch point <When value={ordering.switch_time} /> ({ordering.switch_point_passed ? 'passed' : 'not reached'}: before it the
          policy orders by raw EPA, after it by the trained ranking model)</>}. As of <When value={data.as_of} />.
        </p>
        <p className="small muted">{ordering.evidence}</p>
        <div className="table-scroll">
          <table className="grid compact">
            <caption className="visually-hidden">Predicted ranking, {ordering.teams.length} teams</caption>
            <thead><tr><th scope="col">Rank</th><th scope="col">Team</th><th scope="col">Score</th><th scope="col">EPA source</th></tr></thead>
            <tbody>
              {ordering.teams.map((t) => (
                <tr key={t.team_number}>
                  <td>{t.rank}</td>
                  <th scope="row"><Link to={teamPath(eventKey, t.team_number)}>{t.team_number}</Link></th>
                  <td>{t.score === null ? <Absent reason="no score (no EPA)" /> : formatNumber(t.score, 2)}</td>
                  <td className="small">{t.epa_value_source ?? <Absent />}{t.epa_source_event_key ? ` · ${t.epa_source_event_key}` : ''}
                    {t.epa_source_state ? ` · ${t.epa_source_state}` : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">The score orders teams; only the order is meaningful.</p>
      </section>
      <section className="card" aria-labelledby="contenders-heading">
        <h2 id="contenders-heading">Playoff contenders</h2>
        <div className="two-col">
          <Labelled title="Likely alliance captains" teams={data.captain_candidates} eventKey={eventKey} />
          <Labelled title="Strongest teams" teams={data.strongest_teams} eventKey={eventKey} />
        </div>
      </section>
      <section className="card" aria-labelledby="comparison-heading">
        <div className="card-head">
          <h2 id="comparison-heading">Team comparison</h2>
          <ValidationBadge validation={{ status: data.team_comparison.validation_status }} compact />
        </div>
        <div className="sort-controls">
          <label className="inline">Sort by
            <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
              <option value="team_number">Team number</option>
              {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>{' '}
          <label className="inline">Order
            <select value={descending ? 'desc' : 'asc'} onChange={(e) => setDescending(e.target.value === 'desc')}>
              <option value="asc">Lowest to highest</option>
              <option value="desc">Highest to lowest</option>
            </select>
          </label>
        </div>
        <div className="table-scroll">
          <table className="grid compact">
            <caption className="visually-hidden">Strength of every attending team</caption>
            <thead><tr><th scope="col">Team</th><th scope="col">EPA total</th><th scope="col">Average score</th>
              <th scope="col">Consistency</th><th scope="col">Reliability (estimate)</th><th scope="col">Defense</th></tr></thead>
            <tbody>
              {sorted.map((v) => (
                <tr key={v.team_number}>
                  <th scope="row"><Link to={teamPath(eventKey, v.team_number)}>{v.team_number}</Link></th>
                  {columns.map((c) => <td key={c.name}><MeasureValue measure={c.of(v)} digits={c.digits} hideReason={!!shared[c.name]} /></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {columns.filter((c) => shared[c.name]).map((c) => (
          <p key={c.name} className="small">{c.name}, every team: <Absent reason={shared[c.name]} /></p>
        ))}
        <p className="small muted">Reliability is an estimate: the share of scheduled matches with a recorded result, not a robot-failure measure.</p>
      </section>
      <EpaSourceNote epa={data.epa} />
    </>
  )
}

function TeamsView({ data }: { data: EventTeamsResponse }) {
  const [search, setSearch] = useState('')
  const needle = search.trim().toLowerCase()
  const shown = data.teams.filter((t) => !needle || String(t.team_number).includes(needle)
    || (t.name ?? '').toLowerCase().includes(needle))
  return (
    <section className="card" aria-labelledby="teams-heading">
      <div className="card-head">
        <h2 id="teams-heading">Teams ({data.teams.length})</h2>
        <ValidationBadge validation={data.validation} compact />
      </div>
      <label className="inline">Find a team
        <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="number or name" />
      </label>
      {shown.length === 0 ? <p className="empty">{data.teams.length ? `No team matches “${search}”.` : 'No teams are rostered for this event.'}</p> : (
        <div className="table-scroll">
          <table className="grid compact">
            <caption className="visually-hidden">Teams at {data.event_key}</caption>
            <thead><tr><th scope="col">Team</th><th scope="col">Name</th><th scope="col">From</th><th scope="col">Rookie year</th></tr></thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.team_number}>
                  <th scope="row"><Link to={teamPath(data.event_key, t.team_number)}>{t.team_number}</Link></th>
                  <td>{t.name ?? <Absent reason="no details" />}</td>
                  <td>{[t.city, t.state_province, t.country].filter(Boolean).join(', ') || <Absent />}</td>
                  <td>{t.rookie_year ?? <Absent />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function MatchesView({ data, asOf }: { data: EventMatchesResponse; asOf: string | null }) {
  const [level, setLevel] = useState('all')
  const levels = [...new Set(data.matches.map((m) => m.competition_level ?? 'unknown'))]
  const shown = data.matches.filter((m) => level === 'all' || (m.competition_level ?? 'unknown') === level)
  return (
    <section className="card" aria-labelledby="matches-heading">
      <div className="card-head">
        <h2 id="matches-heading">Matches ({data.matches.length})</h2>
        <ValidationBadge validation={data.validation} compact />
      </div>
      <p className="small muted">As of <When value={data.as_of} />: results scheduled after the moment, and playoff
        matches before alliance selection, are withheld.</p>
      {levels.length > 1 && (
        <label className="inline">Level
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="all">All</option>
            {levels.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>
      )}
      {shown.length === 0 ? <p className="empty">No matches available at this moment.</p> : (
        <div className="table-scroll">
          <table className="grid compact">
            <caption className="visually-hidden">Matches at {data.event_key}</caption>
            <thead><tr><th scope="col">Match</th><th scope="col">Scheduled</th><th scope="col">Red</th><th scope="col">Blue</th>
              <th scope="col">Result</th><th scope="col">Pre-match</th></tr></thead>
            <tbody>
              {shown.map((m) => (
                <tr key={m.match_key}>
                  <th scope="row"><Link to={matchPath(m.match_key)}>{matchLabel(m)}</Link></th>
                  <td><When value={m.scheduled_time} /></td>
                  <td><AllianceTeams teams={m.red_team_numbers} eventKey={data.event_key} tone="red" /></td>
                  <td><AllianceTeams teams={m.blue_team_numbers} eventKey={data.event_key} tone="blue" /></td>
                  <td><ResultCell match={m} /></td>
                  <td><Link to={reportPath(m.match_key, asOf)} aria-label={`Pre-match report for ${matchLabel(m)}`}>Report</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function ForecastView({ data }: { data: QualificationForecastResponse }) {
  return (
    <>
      <section className="card" aria-labelledby="records-heading">
        <h2 id="records-heading">Expected qualification records</h2>
        <p className="small muted">{data.record_evidence}</p>
        <p className="small muted">{data.range_evidence}</p>
        {data.low_confidence && <p className="notice notice-warn">Low confidence: the forecast is early in the season (Statbotics week {data.statbotics_week ?? 'unknown'}).</p>}
        <div className="table-scroll">
          <table className="grid compact">
            <caption className="visually-hidden">Expected wins per team</caption>
            <thead><tr><th scope="col">Team</th><th scope="col">Quals</th><th scope="col">Expected wins</th>
              <th scope="col">80% range</th><th scope="col">Record status</th><th scope="col">Range status</th></tr></thead>
            <tbody>
              {data.teams.map((t) => (
                <tr key={t.team_number}>
                  <th scope="row"><Link to={teamPath(data.event_key, t.team_number)}>{t.team_number}</Link></th>
                  <td>{t.qualification_matches}</td>
                  <td>{formatNumber(t.expected_wins, 1)}</td>
                  <td>{t.range80_low}–{t.range80_high}</td>
                  <td><ValidationBadge validation={{ status: t.record_validation_status, reasons: t.record_not_validated_reason ? [t.record_not_validated_reason] : [] }} /></td>
                  <td><ValidationBadge validation={{ status: t.range_validation_status, reasons: t.range_not_validated_reason ? [t.range_not_validated_reason] : [] }} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card" aria-labelledby="forecast-matches-heading">
        <h2 id="forecast-matches-heading">Qualification matches</h2>
        <div className="table-scroll">
          <table className="grid compact">
            <caption className="visually-hidden">Win probability per qualification match</caption>
            <thead><tr><th scope="col">Match</th><th scope="col">Scheduled</th><th scope="col">Red</th><th scope="col">Blue</th><th scope="col">Win probability</th></tr></thead>
            <tbody>
              {data.matches.map((m) => (
                <tr key={m.match_key}>
                  <th scope="row"><Link to={matchPath(m.match_key)}>{m.match_key.split('_')[1] ?? m.match_key}</Link></th>
                  <td><When value={m.scheduled_time} /></td>
                  <td><AllianceTeams teams={m.red_team_numbers} eventKey={data.event_key} tone="red" /></td>
                  <td><AllianceTeams teams={m.blue_team_numbers} eventKey={data.event_key} tone="blue" /></td>
                  <td><CalibratedProbabilityView value={m.win_probability} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <EpaSourceNote epa={data.epa} />
    </>
  )
}
