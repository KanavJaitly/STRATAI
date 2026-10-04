import { Fragment, useState } from 'react'

import { api } from '../api/client'
import type { Profile } from '../api/types'
import {
  ErrorNotice, LoadState, Section, StateBadge, SuccessNotice, When, WriteGate, useAction, useLoad,
} from '../components/common'
import { useSession } from '../state/session'
import { CAPABILITIES, LEVELS, blankForm, formFrom, payloadFrom, type ProfileForm } from './profileForm'

function ProfileEditor({ existing, onSaved, onCancel }: {
  existing: Profile | null; onSaved: (key: string) => void; onCancel: () => void
}) {
  const { actor } = useSession()
  const [key, setKey] = useState('')
  const [form, setForm] = useState<ProfileForm>(() => (existing ? formFrom(existing.payload) : blankForm()))
  const action = useAction()
  const set = (patch: Partial<ProfileForm>) => setForm((f) => ({ ...f, ...patch }))
  const save = () => action.run(async () => {
    if (existing) {
      await api.editProfile(existing.profile_key, { payload: payloadFrom(form), created_by: actor })
      onSaved(existing.profile_key)
    } else {
      await api.createProfile({ profile_key: key.trim(), payload: payloadFrom(form), created_by: actor })
      onSaved(key.trim())
    }
  })
  return (
    <form onSubmit={(e) => { e.preventDefault(); void save() }}>
      <p className="muted small">
        {existing ? `Saving creates version ${existing.version + 1}; version ${existing.version} is kept in the history.`
          : 'A new profile. The submission is stored raw first, then validated against the P5-M9 intake fields.'}
      </p>
      <div className="form-grid">
        {!existing && <label>Profile key<input value={key} onChange={(e) => setKey(e.target.value)} aria-label="Profile key" required /></label>}
        <label>Team number (optional)<input value={form.team_number} inputMode="numeric" onChange={(e) => set({ team_number: e.target.value })} aria-label="Team number" /></label>
        <label>Budget (USD)<input value={form.budget_usd} inputMode="decimal" onChange={(e) => set({ budget_usd: e.target.value })} aria-label="Budget" /></label>
        {CAPABILITIES.map((c) => (
          <label key={c}>
            {c[0].toUpperCase() + c.slice(1)}
            <select value={form[c]} onChange={(e) => set({ [c]: e.target.value })} aria-label={c}>
              <option value="">—</option>
              {LEVELS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
            </select>
          </label>
        ))}
      </div>
      <label>Notes<textarea value={form.notes} onChange={(e) => set({ notes: e.target.value })} aria-label="Notes" /></label>
      <div className="actions">
        <button type="submit" disabled={action.busy}>{existing ? 'Save new version' : 'Create profile'}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <ErrorNotice error={action.error} />
    </form>
  )
}

function RecommendationView({ profileKey }: { profileKey: string }) {
  const { season } = useSession()
  const rec = useLoad(() => api.recommendation(profileKey, season), [profileKey, season])
  if (rec.error || (rec.loading && !rec.data)) return <LoadState loading={rec.loading} error={rec.error} />
  const r = rec.data!
  return (
    <div className="recommendation" data-testid="recommendation">
      <p><StateBadge state="provisional" label={r.label} /> Deterministic rubric output for season {r.season}: a heuristic, not validated against outcomes.</p>
      <dl className="facts">
        <dt>Realistic ceiling</dt><dd>{r.realistic_ceiling_tier === null ? 'no feasible archetype' : `tier ${r.realistic_ceiling_tier}`}</dd>
        <dt>Recommended archetype</dt><dd>{r.recommended_archetype ?? 'none (no feasible candidate)'}</dd>
        <dt>Achievable features</dt><dd>{r.achievable_features.length ? r.achievable_features.join(', ') : '—'}</dd>
        <dt>Candidates</dt><dd>{r.candidate_archetypes.length ? r.candidate_archetypes.join(', ') : 'none'} <span className="muted small">({r.candidates_note})</span></dd>
        <dt>Rubric</dt><dd>{r.rubric_version} · profile version {r.profile_version}</dd>
      </dl>
      <h4>Limitations</h4>
      <ul>{r.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      <h4>Reasoning</h4>
      <table className="grid compact">
        <thead><tr><th>Archetype</th><th>Tier</th><th>Priority</th><th>Feasible</th><th>Candidate</th><th>Met</th><th>Unmet</th></tr></thead>
        <tbody>
          {r.explanation.map((e) => (
            <tr key={e.archetype}>
              <td>{e.archetype}</td><td>{e.tier}</td><td>{e.priority}</td>
              <td>{e.feasible ? 'yes' : 'no'}</td><td>{e.candidate ? 'yes' : 'no'}</td>
              <td className="small">{e.requirements_met.join('; ')}</td>
              <td className="small">{e.requirements_unmet.join('; ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ProfileDetail({ profile, onChanged }: { profile: Profile; onChanged: (key?: string) => void }) {
  const { actor } = useSession()
  const [mode, setMode] = useState<'view' | 'edit' | 'duplicate'>('view')
  const [newKey, setNewKey] = useState('')
  const history = useLoad(() => api.profileHistory(profile.profile_key), [profile.profile_key, profile.version, profile.status])
  const action = useAction()
  const p = profile.payload
  return (
    <div className="detail" data-testid="profile-detail">
      <h3>{profile.profile_key} <StateBadge state={profile.status} /> <span className="muted small">version {profile.version}</span></h3>
      {mode === 'edit' ? (
        <ProfileEditor existing={profile} onCancel={() => setMode('view')}
          onSaved={(key) => { setMode('view'); onChanged(key) }} />
      ) : (
        <>
          <dl className="facts">
            <dt>Team</dt><dd>{p.team_number ?? '—'}</dd>
            <dt>Budget</dt><dd>${p.budget_usd.toLocaleString()}</dd>
            {CAPABILITIES.map((c) => <Fragment key={c}><dt>{c}</dt><dd>{LEVELS[p[c]].label}</dd></Fragment>)}
            <dt>Notes</dt><dd>{p.notes || '—'}</dd>
            <dt>Saved</dt><dd>{profile.created_by}, <When value={profile.created_at} /></dd>
          </dl>
          {profile.status === 'active' && (
            <WriteGate>
              <div className="actions">
                <button type="button" onClick={() => setMode('edit')}>Edit</button>
                <button type="button" className="secondary" onClick={() => setMode(mode === 'duplicate' ? 'view' : 'duplicate')}>Duplicate</button>
                <button type="button" className="secondary danger" disabled={action.busy}
                  onClick={() => void action.run(async () => { await api.archiveProfile(profile.profile_key, { archived_by: actor }); onChanged() }, 'Archived.')}>
                  Archive
                </button>
              </div>
              {mode === 'duplicate' && (
                <form className="form-row" onSubmit={(e) => {
                  e.preventDefault()
                  void action.run(async () => {
                    await api.duplicateProfile(profile.profile_key, { new_key: newKey.trim(), created_by: actor })
                    setMode('view')
                    onChanged(newKey.trim())
                  }, 'Duplicated.')
                }}>
                  <label>New profile key<input value={newKey} onChange={(e) => setNewKey(e.target.value)} aria-label="New profile key" required /></label>
                  <button type="submit" disabled={action.busy}>Create copy</button>
                </form>
              )}
            </WriteGate>
          )}
          {profile.status === 'archived' && <p className="muted small">Archived profiles are read-only and excluded from the active set.</p>}
        </>
      )}
      <ErrorNotice error={action.error} />
      <SuccessNotice message={action.message} />
      <h4>Recommendation (P5-M9)</h4>
      <RecommendationView profileKey={profile.profile_key} />
      <h4>History</h4>
      {history.data && (
        <table className="grid compact">
          <thead><tr><th>Version</th><th>Status</th><th>By</th><th>When</th><th>Budget</th><th>M / P / Mentor</th></tr></thead>
          <tbody>
            {history.data.map((h) => (
              <tr key={h.id}>
                <td>{h.version}</td><td><StateBadge state={h.status} /></td><td>{h.created_by}</td>
                <td><When value={h.created_at} /></td><td>${h.payload.budget_usd.toLocaleString()}</td>
                <td>{h.payload.manufacturing} / {h.payload.programming} / {h.payload.mentoring}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function ProfilesPage() {
  const [includeArchived, setIncludeArchived] = useState(false)
  const profiles = useLoad(() => api.listProfiles(includeArchived), [includeArchived])
  const [selected, setSelected] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const current = profiles.data?.find((p) => p.profile_key === selected) ?? null
  const active = profiles.data?.filter((p) => p.status === 'active').length ?? 0

  return (
    <>
      <Section title="Team capability profiles (P5-M9)"
        actions={<WriteGate><button type="button" onClick={() => setCreating(true)}>New profile</button></WriteGate>}>
        <p className="lede">
          Each profile records a team's budget and its manufacturing, programming and mentoring capability. Edits create
          new versions, so nothing is overwritten. DM1 needs at least 10 active profiles; {active} {active === 1 ? 'is' : 'are'} shown.
        </p>
        <label className="inline">
          <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} /> Show archived
        </label>
        <LoadState loading={profiles.loading && !profiles.data} error={profiles.error} />
        {profiles.data && profiles.data.length === 0 && <p className="muted">No profiles yet.</p>}
        {profiles.data && profiles.data.length > 0 && (
          <table className="grid">
            <thead><tr><th>Profile</th><th>Team</th><th>Budget</th><th>Manufacturing</th><th>Programming</th><th>Mentoring</th><th>Version</th><th>Status</th><th /></tr></thead>
            <tbody>
              {profiles.data.map((p) => (
                <tr key={p.profile_key} className={p.profile_key === selected ? 'selected' : ''}>
                  <td>{p.profile_key}</td><td>{p.payload.team_number ?? '—'}</td>
                  <td>${p.payload.budget_usd.toLocaleString()}</td>
                  <td>{p.payload.manufacturing}</td><td>{p.payload.programming}</td><td>{p.payload.mentoring}</td>
                  <td>{p.version}</td><td><StateBadge state={p.status} /></td>
                  <td><button type="button" className="link" onClick={() => { setSelected(p.profile_key); setCreating(false) }}>view</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      {creating && (
        <Section title="New profile">
          <WriteGate>
            <ProfileEditor existing={null} onCancel={() => setCreating(false)}
              onSaved={(key) => { setCreating(false); setSelected(key); void profiles.reload() }} />
          </WriteGate>
        </Section>
      )}
      {current && !creating && (
        <Section title="Profile">
          <ProfileDetail key={`${current.profile_key}-${current.version}-${current.status}`} profile={current}
            onChanged={(key) => { if (key) setSelected(key); void profiles.reload() }} />
        </Section>
      )}
    </>
  )
}
