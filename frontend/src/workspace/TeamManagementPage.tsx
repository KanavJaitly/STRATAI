// The Admin Dashboard: overview, Team Management (members: change a role, suspend, remove), analytics, team settings
// and the activity log. Every action here is checked again by the API (workspaces/management.py); this page
// only arranges it.

import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ErrorNotice, LoadState, SuccessNotice, useAction, useLoad, When } from '../components/common'
import { PageHeader, TabPanel, Tabs } from '../dashboard/common'
import { useTab } from '../dashboard/useTab'
import { workspace, type ActivityPage, type Member, type Role } from '../auth/api'
import { useAuth } from '../auth/authState'
import { ROLE_LABEL, ROLE_ORDER } from '../auth/roles'
import { EventChooser, EventName } from './EventChooser'
import { seasonOf } from './events'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'members', label: 'Team Management' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'settings', label: 'Team Settings' },
  { id: 'activity', label: 'Activity Log' },
]

export function TeamManagementPage() {
  const { session } = useAuth()
  const [active, select] = useTab(TABS)
  return (
    <div>
      <PageHeader title="Admin Dashboard"
        subtitle={`Team ${session.workspace?.team_number} · ${session.workspace?.team_name}`} />
      <Tabs tabs={TABS} active={active} onSelect={select} label="Admin Dashboard sections" />
      <TabPanel id={active}>
        {active === 'overview' && <OverviewTab onOpen={select} />}
        {active === 'members' && <MembersTab />}
        {active === 'analytics' && <AnalyticsTab />}
        {active === 'settings' && <SettingsTab />}
        {active === 'activity' && <ActivityTab />}
      </TabPanel>
    </div>
  )
}

function Tile({ value, label }: { value: number | string; label: string }) {
  return <div className="tile"><span className="tile-value">{value}</span><span className="tile-label">{label}</span></div>
}

function OverviewTab({ onOpen }: { onOpen: (tab: string) => void }) {
  const overview = useLoad(() => workspace.overview(), [])
  const analytics = useLoad(() => workspace.analytics(), [])
  const data = overview.data
  return (
    <>
      <LoadState loading={overview.loading} error={overview.error} />
      {data && (
        <section className="card">
          <h2>Team {data.team_number} · {data.team_name}</h2>
          <dl className="facts">
            <dt>Active members</dt><dd>{data.active_members}</dd>
            <dt>Default event</dt><dd>{data.settings.default_event_key
              ? <EventName eventKey={data.settings.default_event_key} /> : <span className="muted">not set</span>}</dd>
          </dl>
          <div className="actions">
            <button type="button" onClick={() => onOpen('members')}>Manage members</button>
            <Link className="button button-secondary" to="/drive-team">Drive team dashboard</Link>
            <Link className="button button-secondary" to={data.settings.default_event_key
              ? `/alliance-selection/live?event=${encodeURIComponent(data.settings.default_event_key)}`
              : '/alliance-selection/live'}>Live alliance selection</Link>
            <Link className="button button-secondary" to="/scouting">Scouting dashboard</Link>
            <Link className="button button-secondary" to="/">All StratAI features</Link>
          </div>
        </section>
      )}
      {analytics.data && (
        <section className="card">
          <h2>At a glance</h2>
          <div className="tiles">
            {ROLE_ORDER.map((role) => (
              <Tile key={role} value={analytics.data!.members_by_role[role].active} label={`${ROLE_LABEL[role]}s`} />
            ))}
            <Tile value={analytics.data.scouting.reports_last_7_days} label="Scouting reports, last 7 days" />
          </div>
        </section>
      )}
    </>
  )
}

// --- members ----------------------------------------------------------------------------------------------------

type SortKey = 'role' | 'name' | 'last_login'
const ROLE_RANK: Record<Role, number> = { admin: 0, base: 1 }

interface Row {
  key: string
  name: string
  email: string
  role: Role
  status: string
  lastLogin: string | null
  member: Member
}

function rowsOf(members: Member[]): Row[] {
  return members.map((m) => ({ key: `m${m.membership_id}`, name: m.name, email: m.email, role: m.role,
    status: m.status, lastLogin: m.last_login_at, member: m }))
}

export function MembersTab() {
  const list = useLoad(() => workspace.members(), [])
  const action = useAction()
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState<'all' | Role>('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sort, setSort] = useState<SortKey>('role')

  const rows = useMemo(() => {
    if (!list.data) return []
    const needle = query.trim().toLowerCase()
    return rowsOf(list.data.members)
      .filter((r) => !needle || r.name.toLowerCase().includes(needle) || r.email.toLowerCase().includes(needle))
      .filter((r) => roleFilter === 'all' || r.role === roleFilter)
      .filter((r) => statusFilter === 'all' || r.status === statusFilter)
      .sort((a, b) => {
        if (sort === 'role') return ROLE_RANK[a.role] - ROLE_RANK[b.role] || a.name.localeCompare(b.name)
        if (sort === 'last_login') return (b.lastLogin ?? '').localeCompare(a.lastLogin ?? '')
        return a.name.localeCompare(b.name)
      })
  }, [list.data, query, roleFilter, statusFilter, sort])

  async function act(run: () => Promise<unknown>, success: string) {
    if (await action.run(run, success)) await list.reload()
  }

  return (
    <section className="card">
      <header className="card-head">
        <h2>Team members</h2>
      </header>
      <p className="muted">New members create their own account at <Link to="/auth/signup">/auth/signup</Link> with
        the team join code, and start as members (events only). Emails listed in ADMIN_EMAILS start as
        administrators. Change a role here; a removed member is restored with{' '}
        <code>python -m scripts.set_role &lt;email&gt; base</code>.</p>
      <div className="form-row" role="search" aria-label="Find members">
        <label>Search<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="name or email" /></label>
        <label>Role
          <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as 'all' | Role)}>
            <option value="all">All roles</option>
            {ROLE_ORDER.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
        </label>
        <label>Status
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">All</option><option value="active">Active</option>
            <option value="suspended">Suspended</option>
          </select>
        </label>
        <label>Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="role">Role</option><option value="name">Name</option>
            <option value="last_login">Last login</option>
          </select>
        </label>
      </div>
      <ErrorNotice error={action.error} />
      <SuccessNotice message={action.message} />
      <LoadState loading={list.loading} error={list.error} />
      {list.data && (
        <div className="table-scroll">
          <table className="members-table">
            <caption className="muted small">{rows.length} shown</caption>
            <thead>
              <tr><th scope="col">Name</th><th scope="col">Email</th><th scope="col">Role</th>
                <th scope="col">Account</th><th scope="col">Last login</th>
                <th scope="col">Actions</th></tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key}>
                  <th scope="row">{row.name}{row.member?.is_self && <span className="muted"> (you)</span>}</th>
                  <td>{row.email}</td>
                  <td>{!row.member.is_self ? (
                    <select aria-label={`Role of ${row.name}`} value={row.role} disabled={action.busy}
                      onChange={(e) => act(() => workspace.changeRole(row.member!.membership_id, e.target.value as Role),
                        `${row.name} is now ${ROLE_LABEL[e.target.value as Role]}.`)}>
                      {ROLE_ORDER.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                    </select>
                  ) : ROLE_LABEL[row.role]}</td>
                  <td><span className={`badge badge-${row.status === 'active' ? 'ok' : row.status === 'suspended'
                    ? 'bad' : 'wait'}`}>{row.status}</span></td>
                  <td>{row.lastLogin ? <When value={row.lastLogin} /> : <span className="muted">never</span>}</td>
                  <td className="row-actions">
                    {!row.member.is_self && <MemberActions member={row.member} busy={action.busy} act={act} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function MemberActions({ member, busy, act }: { member: Member; busy: boolean;
  act: (run: () => Promise<unknown>, success: string) => Promise<void> }) {
  return (
    <>
      <button type="button" className="link" disabled={busy} onClick={() => {
        const name = window.prompt(`Name shown for ${member.email}`, member.name)
        if (name && name.trim() && name.trim() !== member.name) {
          void act(() => workspace.editMember(member.membership_id, name.trim()), 'Name updated.')
        }
      }}>Edit</button>
      {member.status === 'active' ? (
        <button type="button" className="link" disabled={busy} onClick={() => {
          if (window.confirm(`Suspend ${member.name}? They are signed out at once and cannot sign in.`)) {
            void act(() => workspace.setStatus(member.membership_id, 'suspended'), `${member.name} is suspended.`)
          }
        }}>Suspend</button>
      ) : (
        <button type="button" className="link" disabled={busy}
          onClick={() => act(() => workspace.setStatus(member.membership_id, 'active'), `${member.name} is active again.`)}>
          Reactivate</button>
      )}
      <button type="button" className="link danger" disabled={busy} onClick={() => {
        if (window.confirm(`Remove ${member.name} from the team? They are signed out at once. Their scouting stays.`)) {
          void act(() => workspace.removeMember(member.membership_id), `${member.name} was removed.`)
        }
      }}>Remove</button>
    </>
  )
}

// --- analytics, settings, activity -------------------------------------------------------------------------------

function AnalyticsTab() {
  const analytics = useLoad(() => workspace.analytics(), [])
  const data = analytics.data
  return (
    <section className="card">
      <h2>Team analytics</h2>
      <p className="muted">How your workspace is being used. For match and event analysis, use the{' '}
        <Link to="/drive-team">drive team dashboard</Link> and the <Link to="/">event pages</Link>.</p>
      <LoadState loading={analytics.loading} error={analytics.error} />
      {data && (
        <>
          <h3>Members</h3>
          <div className="tiles">
            {ROLE_ORDER.map((role) => (
              <Tile key={role} value={`${data.members_by_role[role].active} active · ${data.members_by_role[role].suspended} suspended`}
                label={ROLE_LABEL[role]} />
            ))}
            <Tile value={data.active_last_7_days} label="Signed in, last 7 days" />
            <Tile value={data.never_signed_in} label="Never signed in" />
          </div>
          <h3>Scouting</h3>
          <div className="tiles">
            <Tile value={data.scouting.reports} label="Reports, all time" />
            <Tile value={data.scouting.reports_last_7_days} label="Reports, last 7 days" />
            <Tile value={data.scouting.events} label="Events scouted" />
            <Tile value={data.scouting.open_assignments} label="Open assignments" />
            <Tile value={data.scouting.completed_assignments} label="Completed assignments" />
          </div>
          {data.scouting.top_scouts.length > 0 && (
            <table>
              <caption>Most active scouts</caption>
              <thead><tr><th scope="col">Scout</th><th scope="col">Reports</th></tr></thead>
              <tbody>{data.scouting.top_scouts.map((s) => <tr key={s.name}><td>{s.name}</td><td>{s.reports}</td></tr>)}</tbody>
            </table>
          )}
        </>
      )}
    </section>
  )
}

function SettingsTab() {
  const { refresh } = useAuth()
  const settings = useLoad(() => workspace.settings(), [])
  const action = useAction()
  const [form, setForm] = useState<{ team_name: string; default_event_key: string; scouting_instructions: string } | null>(null)
  const current = form ?? (settings.data ? {
    team_name: settings.data.team_name, default_event_key: settings.data.default_event_key ?? '',
    scouting_instructions: settings.data.scouting_instructions ?? '' } : null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!current) return
    const ok = await action.run(() => workspace.saveSettings({ team_name: current.team_name.trim(),
      default_event_key: current.default_event_key.trim() || null,
      scouting_instructions: current.scouting_instructions.trim() || null }), 'Settings saved.')
    if (ok) { setForm(null); await settings.reload(); await refresh() }
  }

  return (
    <section className="card">
      <h2>Team settings</h2>
      <LoadState loading={settings.loading} error={settings.error} />
      {current && settings.data && (
        <form onSubmit={submit}>
          <p className="muted">Team number {settings.data.team_number} (fixed).</p>
          <label>Team name<input value={current.team_name} required maxLength={100}
            onChange={(e) => setForm({ ...current, team_name: e.target.value })} /></label>
          <EventChooser key={seasonOf(current.default_event_key) ?? 'none'} legend="Default event"
            value={current.default_event_key}
            onChange={(eventKey) => setForm({ ...current, default_event_key: eventKey })} />
          <div className="actions">
            <span className="muted small">The event the drive team and scouting dashboards open on.</span>
            {current.default_event_key && (
              <button type="button" className="link" onClick={() => setForm({ ...current, default_event_key: '' })}>
                Clear the default event</button>
            )}
          </div>
          <label>Instructions shown to scouters
            <textarea rows={4} maxLength={2000} value={current.scouting_instructions}
              onChange={(e) => setForm({ ...current, scouting_instructions: e.target.value })} />
          </label>
          <ErrorNotice error={action.error} />
          <SuccessNotice message={action.message} />
          <div className="actions"><button type="submit" disabled={action.busy}>Save settings</button></div>
        </form>
      )}
    </section>
  )
}

function describe(details: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(details)) {
    if (value && typeof value === 'object' && 'from' in (value as object) && 'to' in (value as object)) {
      const change = value as { from: unknown; to: unknown }
      parts.push(`${key}: ${String(change.from)} → ${String(change.to)}`)
    } else if (key === 'changes' && value && typeof value === 'object') {
      parts.push(Object.entries(value as Record<string, { to: boolean }>)
        .map(([p, c]) => `${p} ${c.to ? 'granted' : 'removed'}`).join(', '))
    } else if (typeof value !== 'object') {
      parts.push(`${key}: ${String(value)}`)
    }
  }
  return parts.join('; ')
}

export function ActivityTab() {
  const [filter, setFilter] = useState('')
  const [pages, setPages] = useState(1)
  const log = useLoad<ActivityPage>(() => workspace.activity({ limit: 50 * pages, action: filter || undefined }),
    [filter, pages])
  return (
    <section className="card">
      <header className="card-head">
        <h2>Activity log</h2>
        <label>Action
          <select value={filter} onChange={(e) => { setFilter(e.target.value); setPages(1) }}>
            <option value="">All actions</option>
            {(log.data?.actions ?? []).map((a) => <option key={a.action} value={a.action}>{a.label}</option>)}
          </select>
        </label>
      </header>
      <LoadState loading={log.loading} error={log.error} />
      {log.data && (
        <div className="table-scroll">
          <table>
            <thead><tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">Action</th>
              <th scope="col">Affected</th><th scope="col">Details</th></tr></thead>
            <tbody>
              {log.data.entries.map((e) => (
                <tr key={e.id}><td><When value={e.at} /></td><td>{e.actor}</td><td>{e.action_label}</td>
                  <td>{e.target ?? <span className="muted">—</span>}</td><td className="small">{describe(e.details)}</td></tr>
              ))}
            </tbody>
          </table>
          {log.data.entries.length === 0 && <p className="muted">Nothing recorded yet.</p>}
          {log.data.has_more && <button type="button" onClick={() => setPages(pages + 1)}>Show more</button>}
        </div>
      )}
    </section>
  )
}
