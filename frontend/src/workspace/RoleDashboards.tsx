// The drive team / strategy dashboard and the scouter dashboard, plus /home, which sends a signed-in member to their
// role's dashboard. Both live in the same shell and navigation as every other StratAI page and link into the existing
// event, match and team pages; what each shows follows the member's permissions (and the API enforces them).

import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'

import { dashboardApi } from '../api/dashboard'
import type { ScheduledMatchOut } from '../api/generated'
import { ErrorNotice, LoadState, SuccessNotice, useAction, useLoad, When } from '../components/common'
import { PageHeader } from '../dashboard/common'
import { matchPath, teamPath } from '../dashboard/routing'
import { teamScouting, workspace, type Assignment } from '../auth/api'
import { useAuth } from '../auth/authState'
import { homeFor } from '../auth/roles'
import { EventChooser, EventName } from './EventChooser'
import { seasonOf, useEventName } from './events'
import { VerificationBanner } from './TeamManagementPage'

export function HomeRedirect() {
  const { ready, signedIn, role } = useAuth()
  if (!ready) return <p className="muted" role="status">Checking your sign-in…</p>
  return <Navigate to={signedIn ? homeFor(role) : '/auth'} replace />
}

/** The event a dashboard works on: the one chosen on the page, else the team's default event. */
function useEventKey(): [string, (key: string) => void, boolean] {
  const overview = useLoad(() => workspace.overview(), [])
  const [chosen, setChosen] = useState<string | null>(null)
  return [chosen ?? overview.data?.settings.default_event_key ?? '', setChosen, overview.loading]
}

/** The event chooser in a card. Keyed by the event's year, so it opens on the right year whenever the chosen event
 * changes from outside (the team's default event arriving, or "Scout this" on an assignment). */
function EventSection({ eventKey, onChange }: { eventKey: string; onChange: (key: string) => void }) {
  return (
    <section className="card">
      <EventChooser key={seasonOf(eventKey) ?? 'none'} value={eventKey} onChange={onChange} />
      <p className="muted small">Your administrator can set the team&apos;s default event in Team Settings.</p>
    </section>
  )
}

function matchLabel(match: { competition_level: string | null; set_number: number | null; match_number: number | null;
  match_key: string }): string {
  if (match.competition_level === 'qualification' && match.match_number) return `Qualification ${match.match_number}`
  return match.match_key.split('_').pop() ?? match.match_key
}

// --- drive team / strategy ---------------------------------------------------------------------------------------

export function DriveTeamDashboardPage() {
  const { can, session } = useAuth()
  const [eventKey, setEventKey] = useEventKey()
  const eventName = useEventName(eventKey)
  const event = encodeURIComponent(eventKey)
  const tools = [
    { permission: 'event_analysis', title: 'Event analysis', text: 'Rankings, contenders and the event overview.',
      to: `/events/${event}` },
    { permission: 'match_predictions', title: 'Match predictions', text: 'Win probability for every match.',
      to: `/events/${event}?tab=matches` },
    { permission: 'team_analytics', title: 'Team comparisons', text: 'Compare the teams at this event.',
      to: `/events/${event}?tab=teams` },
    { permission: 'qualification_forecast', title: 'Qualification forecast', text: 'Projected final rankings.',
      to: `/events/${event}?tab=forecast` },
    { permission: 'alliance_selection', title: 'Alliance selection', text: 'Candidates and the pick list.',
      to: `/events/${event}/alliance-selection` },
    { permission: 'strategy_tools', title: 'Strategy lab', text: 'Assess and compare match strategies.',
      to: `/events/${event}/strategy-lab` },
  ].filter((tool) => can(tool.permission))

  return (
    <div>
      <PageHeader title="Drive team dashboard" subtitle={`Team ${session.workspace?.team_number} · strategy tools`} />
      <VerificationBanner />
      <EventSection eventKey={eventKey} onChange={setEventKey} />
      {!eventKey ? <p className="notice notice-info">Choose an event to open its tools.</p> : (
        <>
          <section className="card">
            <h2>Tools for {eventName}</h2>
            <div className="tool-grid">
              {tools.map((tool) => (
                <Link key={tool.title} className="tool-card" to={tool.to}>
                  <strong>{tool.title}</strong><span className="muted small">{tool.text}</span>
                </Link>
              ))}
              {tools.length === 0 && <p className="muted">Your role has no strategy tools enabled.</p>}
            </div>
          </section>
          {can('scouting_view') && <ScoutingSummaryCard eventKey={eventKey} />}
          {can('scouting_assign') && <AssignmentsCard eventKey={eventKey} />}
        </>
      )}
    </div>
  )
}

function rating(score: number | null, agreement: number | null, insufficient: boolean, count: number) {
  if (insufficient || score === null) return <span className="muted">insufficient ({count} rating{count === 1 ? '' : 's'})</span>
  return <>{score.toFixed(1)} <span className="muted small">· agreement {agreement === null ? '—'
    : `${Math.round(agreement * 100)}%`} · {count} ratings</span></>
}

export function ScoutingSummaryCard({ eventKey }: { eventKey: string }) {
  const summary = useLoad(() => teamScouting.summary(eventKey), [eventKey])
  const eventName = useEventName(eventKey)
  return (
    <section className="card">
      <h2>Your team&apos;s scouting at {eventName}</h2>
      <p className="muted small">Only your own scouts&apos; reports, private to your team. Defense and feeding come only from
        what scouts recorded (median, 0–5); below two ratings a value is shown as insufficient, never estimated.</p>
      <LoadState loading={summary.loading} error={summary.error} />
      {summary.data && (summary.data.teams.length === 0 ? <p className="muted">No reports yet for this event.</p> : (
        <div className="table-scroll">
          <table>
            <thead><tr><th scope="col">Team</th><th scope="col">Reports</th><th scope="col">Defense</th>
              <th scope="col">Feeding</th></tr></thead>
            <tbody>
              {summary.data.teams.map((t) => (
                <tr key={t.team_number}>
                  <th scope="row"><Link to={teamPath(eventKey, t.team_number)}>{t.team_number}</Link></th>
                  <td>{t.reports} <span className="muted small">({t.scouts} scout{t.scouts === 1 ? '' : 's'})</span></td>
                  <td>{rating(t.profile.defense_score, t.profile.defense_agreement, t.profile.defense_insufficient_data,
                    t.profile.defense_observation_count)}</td>
                  <td>{rating(t.profile.feeding_score, t.profile.feeding_agreement, t.profile.feeding_insufficient_data,
                    t.profile.feeding_observation_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  )
}

function useMatches(eventKey: string) {
  return useLoad(async () => (eventKey ? (await dashboardApi.eventMatches(eventKey, null)).matches : []), [eventKey])
}

function teamsOf(match: ScheduledMatchOut | undefined): { team: number; color: 'red' | 'blue' }[] {
  if (!match) return []
  return [...match.red_team_numbers.map((team) => ({ team, color: 'red' as const })),
    ...match.blue_team_numbers.map((team) => ({ team, color: 'blue' as const }))]
}

function AssignmentsCard({ eventKey }: { eventKey: string }) {
  const { session } = useAuth()
  const matches = useMatches(eventKey)
  const scouts = useLoad(() => teamScouting.scouts(), [])
  const assignments = useLoad(() => teamScouting.assignments({ mine: false, event_key: eventKey }), [eventKey])
  const action = useAction()
  const [form, setForm] = useState({ match: '', team: '', scout: '' })
  const match = matches.data?.find((m) => m.match_key === form.match)
  const verified = session.workspace?.verification_status === 'verified'

  async function submit(event: FormEvent) {
    event.preventDefault()
    const ok = await action.run(() => teamScouting.createAssignment({ match_key: form.match,
      team_number: Number(form.team), membership_id: Number(form.scout) }), 'Assignment created.')
    if (ok) { setForm({ ...form, team: '' }); await assignments.reload() }
  }

  return (
    <section className="card">
      <h2>Scouting assignments</h2>
      {verified ? (
        <form onSubmit={submit} className="form-row" aria-label="Assign a scout">
          <label>Match
            <select value={form.match} required onChange={(e) => setForm({ ...form, match: e.target.value, team: '' })}>
              <option value="">Choose…</option>
              {(matches.data ?? []).map((m) => <option key={m.match_key} value={m.match_key}>{matchLabel(m)}</option>)}
            </select>
          </label>
          <label>Team
            <select value={form.team} required onChange={(e) => setForm({ ...form, team: e.target.value })}>
              <option value="">Choose…</option>
              {teamsOf(match).map(({ team, color }) => <option key={team} value={team}>{team} ({color})</option>)}
            </select>
          </label>
          <label>Scout
            <select value={form.scout} required onChange={(e) => setForm({ ...form, scout: e.target.value })}>
              <option value="">Choose…</option>
              {(scouts.data ?? []).map((s) => <option key={s.membership_id} value={s.membership_id}>{s.name}</option>)}
            </select>
          </label>
          <button type="submit" disabled={action.busy}>Assign</button>
        </form>
      ) : <p className="muted">Assignments open once your workspace is verified.</p>}
      <ErrorNotice error={action.error} />
      <SuccessNotice message={action.message} />
      <LoadState loading={assignments.loading} error={assignments.error || matches.error} />
      {assignments.data && assignments.data.length > 0 && (
        <table>
          <thead><tr><th scope="col">Match</th><th scope="col">Team</th><th scope="col">Scout</th><th scope="col" /></tr></thead>
          <tbody>
            {assignments.data.map((a) => (
              <tr key={a.assignment_id}>
                <td>{matchLabel(a)}</td><td>{a.team_number}</td><td>{a.assigned_to}</td>
                <td><button type="button" className="link" disabled={action.busy} onClick={async () => {
                  if (await action.run(() => teamScouting.cancelAssignment(a.assignment_id), 'Assignment cancelled.')) {
                    await assignments.reload()
                  }
                }}>Cancel</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

// --- scouter -------------------------------------------------------------------------------------------------------

const RATINGS = [0, 1, 2, 3, 4, 5]

export function ScoutingDashboardPage() {
  const { can, session } = useAuth()
  const overview = useLoad(() => workspace.overview(), [])
  const [eventKey, setEventKey] = useEventKey()
  const mine = useLoad(() => teamScouting.assignments({ mine: true }), [])
  const history = useLoad(() => teamScouting.reports({ mine: true }), [])
  const [selected, setSelected] = useState<Assignment | null>(null)
  const instructions = overview.data?.settings.scouting_instructions

  return (
    <div>
      <PageHeader title="Scouting dashboard" subtitle={`Team ${session.workspace?.team_number} · ${session.user?.name}`} />
      <VerificationBanner />
      {instructions && <div className="notice notice-info"><strong>From your team:</strong> {instructions}</div>}
      <section className="card">
        <h2>Your upcoming assignments</h2>
        <LoadState loading={mine.loading} error={mine.error} />
        {mine.data && (mine.data.length === 0 ? <p className="muted">No open assignments. You can still scout any match
          below.</p> : (
          <ul className="assignment-list">
            {mine.data.map((a) => (
              <li key={a.assignment_id}>
                <span><strong>{matchLabel(a)}</strong> at <EventName eventKey={a.event_key} /> · team {a.team_number}
                  {a.alliance_color && <span className={`alliance-${a.alliance_color}`}> ({a.alliance_color})</span>}
                  {a.scheduled_time && <> · <When value={a.scheduled_time} /></>}</span>
                <button type="button" onClick={() => { setSelected(a); setEventKey(a.event_key) }}>Scout this</button>
              </li>
            ))}
          </ul>
        ))}
      </section>
      <EventSection eventKey={eventKey} onChange={(key) => { setEventKey(key); setSelected(null) }} />
      {eventKey && can('scouting_submit') && (
        <ScoutingForm eventKey={eventKey} assignment={selected} onSubmitted={async () => {
          setSelected(null)
          await Promise.all([mine.reload(), history.reload()])
        }} />
      )}
      {eventKey && can('team_info') && <EventTeamsCard eventKey={eventKey} />}
      <section className="card">
        <h2>Your submissions</h2>
        <LoadState loading={history.loading} error={history.error} />
        {history.data && (history.data.length === 0 ? <p className="muted">Nothing submitted yet.</p> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th scope="col">When</th><th scope="col">Match</th><th scope="col">Team</th>
                <th scope="col">Defense</th><th scope="col">Feeding</th><th scope="col">Notes</th></tr></thead>
              <tbody>
                {history.data.map((r) => (
                  <tr key={r.report_id}><td><When value={r.submitted_at} /></td><td>{r.match_key}</td>
                    <td>{r.team_number}</td><td>{r.defense_rating ?? '—'}</td><td>{r.feeding_rating ?? '—'}</td>
                    <td className="small">{r.notes ?? ''}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </section>
    </div>
  )
}

function RatingField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label>{label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Not observed</option>
        {RATINGS.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>
    </label>
  )
}

export function ScoutingForm({ eventKey, assignment, onSubmitted }: { eventKey: string; assignment: Assignment | null;
  onSubmitted: () => Promise<void> }) {
  const { session } = useAuth()
  const matches = useMatches(eventKey)
  const action = useAction()
  const blank = { match: '', team: '', defense: '', feeding: '', notes: '' }
  const [form, setForm] = useState(blank)
  useEffect(() => {
    if (assignment) setForm({ ...blank, match: assignment.match_key, team: String(assignment.team_number) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignment])
  const match = useMemo(() => matches.data?.find((m) => m.match_key === form.match), [matches.data, form.match])
  const verified = session.workspace?.verification_status === 'verified'
  const problem = form.defense === '' && form.feeding === '' ? 'Rate defense, feeding, or both.' : null

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (problem) return
    const ok = await action.run(() => teamScouting.submitReport({
      match_key: form.match, team_number: Number(form.team),
      defense_rating: form.defense === '' ? null : Number(form.defense),
      feeding_rating: form.feeding === '' ? null : Number(form.feeding),
      notes: form.notes.trim() || null,
      assignment_id: assignment && assignment.match_key === form.match && String(assignment.team_number) === form.team
        ? assignment.assignment_id : null,
    }), 'Report submitted. Thank you!')
    if (ok) { setForm(blank); await onSubmitted() }
  }

  const eventName = useEventName(eventKey)

  return (
    <section className="card">
      <h2>Scouting form · {eventName}</h2>
      {!verified ? <p className="muted">Scouting opens once your team&apos;s workspace is verified.</p> : (
        <form onSubmit={submit} aria-label="Scouting report">
          <div className="form-grid">
            <label>Match
              <select value={form.match} required onChange={(e) => setForm({ ...form, match: e.target.value, team: '' })}>
                <option value="">Choose…</option>
                {(matches.data ?? []).map((m) => <option key={m.match_key} value={m.match_key}>{matchLabel(m)}</option>)}
              </select>
            </label>
            <label>Team
              <select value={form.team} required onChange={(e) => setForm({ ...form, team: e.target.value })}>
                <option value="">Choose…</option>
                {teamsOf(match).map(({ team, color }) => <option key={team} value={team}>{team} ({color})</option>)}
              </select>
            </label>
            <RatingField label="Defense (0–5)" value={form.defense} onChange={(v) => setForm({ ...form, defense: v })} />
            <RatingField label="Feeding (0–5)" value={form.feeding} onChange={(v) => setForm({ ...form, feeding: v })} />
          </div>
          <label>Notes<textarea rows={3} maxLength={2000} value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
          {form.match && problem && <p className="muted small">{problem}</p>}
          <LoadState loading={matches.loading} error={matches.error} />
          <ErrorNotice error={action.error} />
          <SuccessNotice message={action.message} />
          <div className="actions">
            <button type="submit" disabled={action.busy || !form.match || !form.team || Boolean(problem)}>
              Submit report</button>
            {form.match && <Link to={matchPath(form.match)}>Match details</Link>}
          </div>
        </form>
      )}
    </section>
  )
}

function EventTeamsCard({ eventKey }: { eventKey: string }) {
  const teams = useLoad(() => dashboardApi.eventTeams(eventKey), [eventKey])
  const eventName = useEventName(eventKey)
  return (
    <section className="card">
      <h2>Teams at {eventName}</h2>
      <LoadState loading={teams.loading} error={teams.error} />
      {teams.data && (
        <ul className="team-chips">
          {teams.data.teams.map((t) => <li key={t.team_number}><span className="team-chip">{t.team_number}</span>
            {t.name && <span className="muted small"> {t.name}</span>}</li>)}
        </ul>
      )}
    </section>
  )
}
