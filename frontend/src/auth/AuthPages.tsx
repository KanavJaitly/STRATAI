// The sign-in side of FRC Team 11's StratAI: sign-up with the team join code, sign-in, password reset by emailed code,
// and the account page. /auth itself only forwards to the sign-in page.

import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { ErrorNotice, SuccessNotice, useAction } from '../components/common'
import { PageHeader } from '../dashboard/common'
import { auth, type SessionInfo } from './api'
import { useAuth } from './authState'
import { landingFor } from './roles'
import { WakingNotice } from '../components/WakingNotice'

/** Matches the API's rule (workspaces/passwords.py MIN_PASSWORD_LENGTH): at least 8 characters, nothing else. */
export const MIN_PASSWORD = 8

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

/** Says plainly when this server cannot run accounts, instead of letting every form fail with a bare 404/500. */
export function AccountsUnavailableNotice() {
  const { accountsUnavailable } = useAuth()
  if (accountsUnavailable === 'api_outdated') {
    return (
      <div className="notice notice-error" role="alert">
        <strong>This StratAI server does not have accounts yet.</strong> The API answering this page is running an
        older version of StratAI. Stop it and start <code>python -m api</code> again from the current checkout; the
        API does not reload new code on its own.
      </div>
    )
  }
  if (accountsUnavailable === 'schema_missing') {
    return (
      <div className="notice notice-error" role="alert">
        <strong>Accounts are not set up on this server&apos;s database.</strong> The database the API uses has not
        had the account migrations applied (up to <code>0015_single_team_auth.sql</code>;{' '}
        <code>python database/migrate.py</code>, run against that database). For local testing, point the API at a
        disposable <code>stratai_test_&lt;suffix&gt;</code> copy, never the serving database.
      </div>
    )
  }
  return null
}

/** Where to go after signing in: the requested page if this role may open it, otherwise the role's own landing. */
function afterSignIn(session: SessionInfo, next: string | null): string {
  return landingFor(session.role, next, session.permissions ?? [])
}

// --- /auth ---------------------------------------------------------------------------------------------------------

/** /auth has nothing of its own: it forwards to sign-in, keeping ?next=. */
export function AuthLandingPage() {
  const { search } = useLocation()
  return <Navigate to={`/auth/login${search}`} replace />
}

// --- sign-up -------------------------------------------------------------------------------------------------------

export function SignupPage() {
  const { session, setSession } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const action = useAction()
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '', code: '' })
  const [problem, setProblem] = useState<string | null>(null)
  const closed = session.signup_open === false

  async function submit(event: FormEvent) {
    event.preventDefault()
    const issue = !form.name.trim() ? 'Enter your full name.' : !form.email.includes('@') ? 'Enter your email.'
      : passwordProblem(form.password, form.confirm) ?? (!form.code.trim() ? 'Enter the team join code.' : null)
    setProblem(issue)
    if (issue) return
    await action.run(async () => {
      const signedIn = await auth.signup({ full_name: form.name.trim(), email: form.email.trim(),
        password: form.password, join_code: form.code.trim() })
      setSession(signedIn)
      navigate(afterSignIn(signedIn, params.get('next')), { replace: true })
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Create your account" subtitle="StratAI for FRC Team 11 (MORT)." />
      <AccountsUnavailableNotice />
      {closed && (
        <div className="notice notice-warn" role="alert">Sign-up is not open on this server: no team join code is
          configured. Ask one of the team&apos;s administrators.</div>
      )}
      <AuthCard title="Your account" wide>
        <form onSubmit={submit} noValidate>
          <Field label="Full name">
            <input value={form.name} required autoComplete="name" maxLength={120}
              onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Email address">
            <input type="email" value={form.email} required autoComplete="username"
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label="Password" hint={`At least ${MIN_PASSWORD} characters.`}>
            <input type="password" value={form.password} required autoComplete="new-password"
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Field label="Confirm password">
            <input type="password" value={form.confirm} required autoComplete="new-password"
              onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
          </Field>
          <Field label="Team join code" hint="The member code, or the admin code if you are an administrator. Ask one of the team's administrators.">
            <input value={form.code} required autoComplete="off" spellCheck={false}
              onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </Field>
          {problem && <div className="notice notice-error" role="alert">{problem}</div>}
          <ErrorNotice error={action.error} />
          <div className="actions">
            <button type="submit" disabled={action.busy || closed}>
              {action.busy ? 'Creating…' : 'Create account'}
            </button>
            {action.busy && <WakingNotice />}
          </div>
        </form>
      </AuthCard>
      <p className="muted">Already have an account? <Link to="/auth/login">Log in</Link></p>
    </div>
  )
}

// --- sign-in and recovery ------------------------------------------------------------------------------------------

export function LoginPage() {
  const { setSession } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const action = useAction()
  const [form, setForm] = useState({ email: '', password: '' })

  async function submit(event: FormEvent) {
    event.preventDefault()
    await action.run(async () => {
      const session = await auth.login({ email: form.email.trim(), password: form.password })
      setSession(session)
      navigate(afterSignIn(session, params.get('next')), { replace: true })
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Log in" subtitle="StratAI for FRC Team 11 (MORT)." />
      <AccountsUnavailableNotice />
      <AuthCard title="Your account">
        <form onSubmit={submit} noValidate>
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
            {action.busy && <WakingNotice />}
            <Link to="/auth/forgot">Forgot your password?</Link>
          </div>
        </form>
      </AuthCard>
      <p className="muted">New to the team&apos;s StratAI? <Link to="/auth/signup">Create an account</Link> with the
        team join code.</p>
    </div>
  )
}

export function ForgotPasswordPage() {
  const navigate = useNavigate()
  const action = useAction()
  const [email, setEmail] = useState('')
  const [answer, setAnswer] = useState<{ email_delivery_configured: boolean } | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    await action.run(async () => {
      setAnswer(await auth.forgotPassword({ email: email.trim() }))
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Reset your password" crumbs={[{ to: '/auth/login', label: 'Log in' }]} />
      <AuthCard title="Get a reset code">
        {answer ? (
          answer.email_delivery_configured ? (
            <>
              <div className="notice notice-ok" role="status">If that email has an account, a 6-digit code is on its
                way. It works once, for 15 minutes.</div>
              <div className="actions">
                <button type="button" onClick={() => navigate('/auth/reset', { state: { email: email.trim() } })}>
                  Enter the code
                </button>
              </div>
            </>
          ) : (
            <div className="notice notice-warn" role="status">This StratAI server does not send email, so it cannot
              send you a code. Ask one of the team&apos;s administrators.</div>
          )
        ) : (
          <form onSubmit={submit} noValidate>
            <Field label="Email address">
              <input type="email" value={email} required autoComplete="username"
                onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <ErrorNotice error={action.error} />
            <div className="actions">
              <button type="submit" disabled={action.busy}>Send code</button>
              {action.busy && <WakingNotice />}
              <Link to="/auth/reset">I already have a code</Link>
            </div>
          </form>
        )}
      </AuthCard>
    </div>
  )
}

export function ResetPasswordPage() {
  const { state } = useLocation()
  const { setSession } = useAuth()
  const navigate = useNavigate()
  const action = useAction()
  const initialEmail = typeof (state as { email?: unknown } | null)?.email === 'string'
    ? (state as { email: string }).email : ''
  const [form, setForm] = useState({ email: initialEmail, code: '', password: '', confirm: '' })
  const [problem, setProblem] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const issue = !form.email.includes('@') ? 'Enter your email.'
      : !/^\d{6}$/.test(form.code.trim()) ? 'Enter the 6-digit code from the email.'
        : passwordProblem(form.password, form.confirm)
    setProblem(issue)
    if (issue) return
    await action.run(async () => {
      const session = await auth.resetPassword({ email: form.email.trim(), code: form.code.trim(),
        new_password: form.password })
      setSession(session)
      navigate(afterSignIn(session, null), { replace: true })
    })
  }

  return (
    <div className="auth-page">
      <PageHeader title="Choose a new password" crumbs={[{ to: '/auth/forgot', label: 'Reset your password' }]} />
      <AuthCard title="New password">
        <form onSubmit={submit} noValidate>
          <Field label="Email address">
            <input type="email" value={form.email} required autoComplete="username"
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label="6-digit code" hint="From the email. It works once, for 15 minutes.">
            <input value={form.code} required inputMode="numeric" autoComplete="one-time-code" maxLength={6}
              onChange={(e) => setForm({ ...form, code: e.target.value.replace(/\D/g, '') })} />
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
          <div className="actions">
            <button type="submit" disabled={action.busy}>{action.busy ? 'Saving…' : 'Set new password'}</button>
            {action.busy && <WakingNotice />}
            <Link to="/auth/forgot">Send a new code</Link>
          </div>
        </form>
      </AuthCard>
    </div>
  )
}

// --- the account page ----------------------------------------------------------------------------------------------

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
          <dt>Role</dt><dd>{session.role_label}</dd>
        </dl>
        <div className="actions">
          <button type="button" onClick={async () => { await signOut(); navigate('/auth/login', { replace: true }) }}>
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
