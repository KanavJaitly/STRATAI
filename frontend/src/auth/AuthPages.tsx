// The sign-in side of team workspaces: the choice between registering a team and signing in, team registration and
// its first administrator, sign-in, password recovery, invitation acceptance and the account page.

import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { ErrorNotice, SuccessNotice, useAction } from '../components/common'
import { PageHeader } from '../dashboard/common'
import { auth, tokenFromHash, type InvitationPreview, type RegisteredTeam } from './api'
import { useAuth } from './authState'
import { homeFor, ROLE_LABEL, safeNext } from './roles'

export const MIN_PASSWORD = 12

function passwordProblem(password: string, confirm: string): string | null {
  if (password.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`
  if (password !== confirm) return 'The two passwords do not match.'
  return null
}

function AuthCard({ title, children, wide }: { title: string; children: ReactNode; wide?: boolean }) {
  const headingId = useId() // unique per card: two cards on one page must not share an id or a region name
  return (
    <section className={`card auth-card${wide ? ' auth-card-wide' : ''}`} aria-labelledby={headingId}>
      <h2 id={headingId}>{title}</h2>
      {children}
    </section>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="auth-field">
      <span>{label}</span>
      {children}
      {hint && <span className="muted small">{hint}</span>}
    </label>
  )
}

function teamNumberValue(text: string): number | null {
  const value = Number(text)
  return Number.isInteger(value) && value >= 1 && value <= 99999 ? value : null
}

// --- the choice -------------------------------------------------------------------------------------------------

export function AuthLandingPage() {
  const { signedIn, role, session } = useAuth()
  return (
    <div className="auth-page">
      <PageHeader title="Your team's StratAI" subtitle="Each FRC team gets its own private workspace: its own members,
        roles, scouting and strategy tools. Every person signs in with their own account." />
      {signedIn && (
        <div className="notice notice-info" role="status">
          You are signed in to team {session.workspace?.team_number} as {session.user?.name}.{' '}
          <Link to={homeFor(role)}>Go to your dashboard</Link>
        </div>
      )}
      <div className="auth-choices">
        <AuthCard title="Register a New Team">
          <p>Set up your team&apos;s workspace and become its first administrator. You will invite the rest of your
            team after StratAI verifies that the workspace belongs to your team.</p>
          <Link className="button" to="/auth/register">Register a new team</Link>
        </AuthCard>
        <AuthCard title="Log In to an Existing Team">
          <p>Sign in with your team number, your email and your own password. Your role is found automatically.</p>
          <Link className="button" to="/auth/login">Log in</Link>
          <p className="small muted">Invited by your team? Open the link in your invitation to create your account.</p>
        </AuthCard>
      </div>
    </div>
  )
}

// --- registration -----------------------------------------------------------------------------------------------

export function RegisterTeamPage() {
  const { setSession } = useAuth()
  const navigate = useNavigate()
  const action = useAction()
  const [step, setStep] = useState<'team' | 'admin'>('team')
  const [registered, setRegistered] = useState<RegisteredTeam | null>(null)
  const [team, setTeam] = useState({ number: '', name: '', setup: '', setupConfirm: '' })
  const [admin, setAdmin] = useState({ name: '', email: '', password: '', confirm: '' })
  const [problem, setProblem] = useState<string | null>(null)

  async function submitTeam(event: FormEvent) {
    event.preventDefault()
    const number = teamNumberValue(team.number)
    const issue = number === null ? 'Enter your FRC team number (1 to 99999).'
      : !team.name.trim() ? 'Enter your team name.' : passwordProblem(team.setup, team.setupConfirm)
    setProblem(issue)
    if (issue || number === null) return
    await action.run(async () => {
      setRegistered(await auth.registerTeam({ team_number: number, team_name: team.name.trim(),
        setup_password: team.setup }))
      setStep('admin')
    })
  }

  async function submitAdmin(event: FormEvent) {
    event.preventDefault()
    const number = teamNumberValue(team.number)
    const issue = !admin.name.trim() ? 'Enter your full name.' : !admin.email.includes('@') ? 'Enter your email.'
      : passwordProblem(admin.password, admin.confirm)
    setProblem(issue)
    if (issue || number === null) return
    await action.run(async () => {
      setSession(await auth.initialAdmin({ team_number: number, setup_password: team.setup,
        full_name: admin.name.trim(), email: admin.email.trim(), password: admin.password }))
      navigate('/team', { replace: true })
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title={step === 'team' ? 'Register a new team' : 'Create the administrator account'}
        crumbs={[{ to: '/auth', label: 'Sign in or register' }]} />
      <ol className="auth-steps" aria-label="Registration steps">
        <li aria-current={step === 'team' ? 'step' : undefined}>1. Your team</li>
        <li aria-current={step === 'admin' ? 'step' : undefined}>2. Your administrator account</li>
        <li>3. Verification by StratAI</li>
      </ol>
      {step === 'team' && (
        <AuthCard title="Your team" wide>
          <p className="muted">A team number is public, so registering one does not by itself prove it is yours.
            Your workspace starts as <strong>pending verification</strong> until StratAI confirms that you speak for
            the team. You can set it up meanwhile; inviting members and scouting open once it is verified.</p>
          <form onSubmit={submitTeam} noValidate>
            <Field label="FRC team number">
              <input inputMode="numeric" value={team.number} required autoComplete="off"
                onChange={(e) => setTeam({ ...team, number: e.target.value.trim() })} />
            </Field>
            <Field label="Team name">
              <input value={team.name} required maxLength={100}
                onChange={(e) => setTeam({ ...team, name: e.target.value })} />
            </Field>
            <Field label="Team setup password" hint={`A one-time onboarding password (at least ${MIN_PASSWORD}
              characters). You need it once more, on the next step; it stops working after the administrator account
              exists. It is never a team login.`}>
              <input type="password" value={team.setup} required autoComplete="new-password"
                onChange={(e) => setTeam({ ...team, setup: e.target.value })} />
            </Field>
            <Field label="Confirm the setup password">
              <input type="password" value={team.setupConfirm} required autoComplete="new-password"
                onChange={(e) => setTeam({ ...team, setupConfirm: e.target.value })} />
            </Field>
            {problem && <div className="notice notice-error" role="alert">{problem}</div>}
            <ErrorNotice error={action.error} />
            <div className="actions">
              <button type="submit" disabled={action.busy}>{action.busy ? 'Registering…' : 'Register team'}</button>
              <button type="button" className="link" onClick={() => { setProblem(null); setStep('admin') }}>
                Already registered? Create the administrator account
              </button>
            </div>
          </form>
        </AuthCard>
      )}
      {step === 'admin' && (
        <AuthCard title="Your administrator account" wide>
          {registered ? (
            <div className="notice notice-info" role="status">
              Team {registered.team_number} ({registered.team_name}) is registered and{' '}
              <strong>pending verification</strong>.
              {registered.frc_team_name && registered.frc_team_name !== registered.team_name &&
                ` The Blue Alliance lists team ${registered.team_number} as “${registered.frc_team_name}”.`}
            </div>
          ) : (
            <>
              <Field label="FRC team number">
                <input inputMode="numeric" value={team.number} required
                  onChange={(e) => setTeam({ ...team, number: e.target.value.trim() })} />
              </Field>
              <Field label="Team setup password">
                <input type="password" value={team.setup} required autoComplete="off"
                  onChange={(e) => setTeam({ ...team, setup: e.target.value })} />
              </Field>
            </>
          )}
          <p className="muted">This is your own account. You will be the workspace&apos;s first administrator; you can
            add more administrators later.</p>
          <form onSubmit={submitAdmin} noValidate>
            <Field label="Full name">
              <input value={admin.name} required autoComplete="name" maxLength={120}
                onChange={(e) => setAdmin({ ...admin, name: e.target.value })} />
            </Field>
            <Field label="Email address">
              <input type="email" value={admin.email} required autoComplete="username"
                onChange={(e) => setAdmin({ ...admin, email: e.target.value })} />
            </Field>
            <Field label="Password" hint={`At least ${MIN_PASSWORD} characters. A short passphrase works well.`}>
              <input type="password" value={admin.password} required autoComplete="new-password"
                onChange={(e) => setAdmin({ ...admin, password: e.target.value })} />
            </Field>
            <Field label="Confirm password">
              <input type="password" value={admin.confirm} required autoComplete="new-password"
                onChange={(e) => setAdmin({ ...admin, confirm: e.target.value })} />
            </Field>
            {problem && <div className="notice notice-error" role="alert">{problem}</div>}
            <ErrorNotice error={action.error} />
            <div className="actions">
              <button type="submit" disabled={action.busy}>
                {action.busy ? 'Creating…' : 'Create account and open the Admin Dashboard'}
              </button>
            </div>
          </form>
        </AuthCard>
      )}
    </div>
  )
}

// --- sign-in and recovery ----------------------------------------------------------------------------------------

export function LoginPage() {
  const { setSession } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const action = useAction()
  const [form, setForm] = useState({ team: params.get('team') ?? '', email: '', password: '' })

  async function submit(event: FormEvent) {
    event.preventDefault()
    const number = teamNumberValue(form.team)
    await action.run(async () => {
      const session = await auth.login({ team_number: number ?? 0, email: form.email.trim(), password: form.password })
      setSession(session)
      navigate(safeNext(params.get('next')) ?? homeFor(session.role), { replace: true })
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Log in to your team" crumbs={[{ to: '/auth', label: 'Sign in or register' }]} />
      <AuthCard title="Your account">
        <form onSubmit={submit} noValidate>
          <Field label="FRC team number">
            <input inputMode="numeric" value={form.team} required autoComplete="organization"
              onChange={(e) => setForm({ ...form, team: e.target.value.trim() })} />
          </Field>
          <Field label="Email address">
            <input type="email" value={form.email} required autoComplete="username"
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label="Password">
            <input type="password" value={form.password} required autoComplete="current-password"
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <ErrorNotice error={action.error} />
          <div className="actions">
            <button type="submit" disabled={action.busy}>{action.busy ? 'Signing in…' : 'Log in'}</button>
            <Link to="/auth/forgot">Forgot your password?</Link>
          </div>
        </form>
      </AuthCard>
      <p className="muted">New to StratAI? <Link to="/auth/register">Register your team</Link>, or open the invitation
        link your team&apos;s administrator sent you.</p>
    </div>
  )
}

export function ForgotPasswordPage() {
  const action = useAction()
  const [form, setForm] = useState({ team: '', email: '' })
  const [answer, setAnswer] = useState<{ email_delivery_configured: boolean } | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    await action.run(async () => {
      setAnswer(await auth.forgotPassword({ team_number: teamNumberValue(form.team) ?? 0, email: form.email.trim() }))
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Reset your password" crumbs={[{ to: '/auth/login', label: 'Log in' }]} />
      <AuthCard title="Request a reset link">
        {answer ? (
          answer.email_delivery_configured ? (
            <div className="notice notice-ok" role="status">If that account exists, a reset link is on its way to
              that email. It works once, for a limited time.</div>
          ) : (
            <div className="notice notice-warn" role="status">This StratAI server does not send email, so it cannot
              send you a link. Ask one of your team&apos;s administrators to issue you a password reset link from
              Team Management.</div>
          )
        ) : (
          <form onSubmit={submit} noValidate>
            <Field label="FRC team number">
              <input inputMode="numeric" value={form.team} required
                onChange={(e) => setForm({ ...form, team: e.target.value.trim() })} />
            </Field>
            <Field label="Email address">
              <input type="email" value={form.email} required autoComplete="username"
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </Field>
            <ErrorNotice error={action.error} />
            <div className="actions"><button type="submit" disabled={action.busy}>Send reset link</button></div>
          </form>
        )}
      </AuthCard>
    </div>
  )
}

export function ResetPasswordPage() {
  const { hash } = useLocation()
  const token = tokenFromHash(hash)
  const action = useAction()
  const [form, setForm] = useState({ password: '', confirm: '' })
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const issue = passwordProblem(form.password, form.confirm)
    setProblem(issue)
    if (issue) return
    await action.run(async () => {
      await auth.resetPassword({ token, new_password: form.password })
      setDone(true)
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Choose a new password" />
      <AuthCard title="New password">
        {!token && <div className="notice notice-error" role="alert">This page needs the link from your reset email
          or from your administrator.</div>}
        {done ? (
          <div className="notice notice-ok" role="status">Your password is changed and every earlier session has
            ended. <Link to="/auth/login">Log in</Link></div>
        ) : token && (
          <form onSubmit={submit} noValidate>
            <Field label="New password" hint={`At least ${MIN_PASSWORD} characters.`}>
              <input type="password" value={form.password} required autoComplete="new-password"
                onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </Field>
            <Field label="Confirm new password">
              <input type="password" value={form.confirm} required autoComplete="new-password"
                onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
            </Field>
            {problem && <div className="notice notice-error" role="alert">{problem}</div>}
            <ErrorNotice error={action.error} />
            <div className="actions"><button type="submit" disabled={action.busy}>Set new password</button></div>
          </form>
        )}
      </AuthCard>
    </div>
  )
}

// --- invitations -------------------------------------------------------------------------------------------------

export function AcceptInvitationPage() {
  const { hash } = useLocation()
  const token = tokenFromHash(hash)
  const { setSession } = useAuth()
  const navigate = useNavigate()
  const load = useAction()
  const action = useAction()
  const [preview, setPreview] = useState<InvitationPreview | null>(null)
  const [form, setForm] = useState({ name: '', password: '', confirm: '' })
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    void load.run(async () => {
      const found = await auth.previewInvitation(token)
      setPreview(found)
      setForm((current) => ({ ...current, name: found.full_name }))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!preview) return
    const issue = !form.name.trim() ? 'Enter your full name.'
      : preview.existing_account ? (form.password ? null : 'Enter your existing StratAI password.')
        : passwordProblem(form.password, form.confirm)
    setProblem(issue)
    if (issue) return
    await action.run(async () => {
      const session = await auth.acceptInvitation({ token, full_name: form.name.trim(), password: form.password })
      setSession(session)
      navigate(homeFor(session.role), { replace: true })
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Join your team on StratAI" />
      <AuthCard title="Your invitation" wide>
        {!token && <div className="notice notice-error" role="alert">This page needs the link from your
          invitation.</div>}
        <ErrorNotice error={load.error} />
        {load.busy && <p className="muted" role="status">Checking your invitation…</p>}
        {preview && (
          <>
            <p>You are invited to team <strong>{preview.team_number} ({preview.team_name})</strong> as{' '}
              <strong>{ROLE_LABEL[preview.role]}</strong>, with the email <strong>{preview.email}</strong>.</p>
            {preview.existing_account && (
              <div className="notice notice-info" role="status">You already have a StratAI account with this email
                (in another team). Enter that account&apos;s password to join with it.</div>
            )}
            <form onSubmit={submit} noValidate>
              <Field label="Full name">
                <input value={form.name} required autoComplete="name" maxLength={120}
                  onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field label={preview.existing_account ? 'Your existing password' : 'Choose a password'}
                hint={preview.existing_account ? undefined : `At least ${MIN_PASSWORD} characters.`}>
                <input type="password" value={form.password} required
                  autoComplete={preview.existing_account ? 'current-password' : 'new-password'}
                  onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </Field>
              {!preview.existing_account && (
                <Field label="Confirm password">
                  <input type="password" value={form.confirm} required autoComplete="new-password"
                    onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
                </Field>
              )}
              {problem && <div className="notice notice-error" role="alert">{problem}</div>}
              <ErrorNotice error={action.error} />
              <div className="actions">
                <button type="submit" disabled={action.busy}>
                  {action.busy ? 'Joining…' : preview.existing_account ? 'Join the team' : 'Create my account'}
                </button>
              </div>
            </form>
          </>
        )}
      </AuthCard>
    </div>
  )
}

// --- the account page --------------------------------------------------------------------------------------------

export function AccountPage() {
  const { session, signOut } = useAuth()
  const navigate = useNavigate()
  const action = useAction()
  const [form, setForm] = useState({ current: '', password: '', confirm: '' })
  const [problem, setProblem] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const issue = !form.current ? 'Enter your current password.' : passwordProblem(form.password, form.confirm)
    setProblem(issue)
    if (issue) return
    const ok = await action.run(() => auth.changePassword({ current_password: form.current,
      new_password: form.password }), 'Your password is changed. Your other sessions have been signed out.')
    if (ok) setForm({ current: '', password: '', confirm: '' })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Your account" />
      <AuthCard title="Signed in" wide>
        <dl className="facts">
          <dt>Name</dt><dd>{session.user?.name}</dd>
          <dt>Email</dt><dd>{session.user?.email}</dd>
          <dt>Team</dt><dd>{session.workspace?.team_number} ({session.workspace?.team_name})</dd>
          <dt>Role</dt><dd>{session.role_label}</dd>
        </dl>
        <div className="actions">
          <button type="button" onClick={async () => { await signOut(); navigate('/auth', { replace: true }) }}>
            Log out
          </button>
        </div>
      </AuthCard>
      <AuthCard title="Change your password" wide>
        <form onSubmit={submit} noValidate>
          <Field label="Current password">
            <input type="password" value={form.current} required autoComplete="current-password"
              onChange={(e) => setForm({ ...form, current: e.target.value })} />
          </Field>
          <Field label="New password" hint={`At least ${MIN_PASSWORD} characters.`}>
            <input type="password" value={form.password} required autoComplete="new-password"
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Field label="Confirm new password">
            <input type="password" value={form.confirm} required autoComplete="new-password"
              onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
          </Field>
          {problem && <div className="notice notice-error" role="alert">{problem}</div>}
          <ErrorNotice error={action.error} />
          <SuccessNotice message={action.message} />
          <div className="actions"><button type="submit" disabled={action.busy}>Change password</button></div>
        </form>
      </AuthCard>
    </div>
  )
}
