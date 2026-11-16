# Team accounts: FRC Team 11 (MORT)

StratAI serves one team, FRC Team 11 (MORT). Everyone signs in with their own account, and the whole site is behind
sign-in. There are two roles, **admin** and **base**.

History:
- **2026-11-02:** team workspaces for many teams, with migration `0012_team_workspaces.sql`. It covered registration
  with a setup password, operator verification, invitations, and three configurable roles.
- **2026-11-11:** replaced by the single-team model here, with migration `0015_single_team_auth.sql`. The decision
  is in RUNNING_NOTES.md (Design Decisions Log, 2026-11-11).

## 1. Architecture

| Part | Responsibility | Where |
|---|---|---|
| Accounts and sessions | Sign-up with the join code, sign-in, password hashing, sessions, password change, reset codes | `workspaces/accounts.py`, `workspaces/sessions.py`, `workspaces/passwords.py` |
| Roles | The two roles and what each may do, fixed in code | `workspaces/permissions.py` |
| Rate limits | Every credential check and every email-sending request | `workspaces/rate_limit.py` |
| PostgreSQL | Users, memberships, sessions, reset codes, activity log, team scouting, live draft | migrations 0012-0015 |
| FastAPI | Session verification and every authorization decision, on the server | `api/session.py`, `api/app.py`, `api/routes/auth.py`, `api/routes/workspace.py` |
| React web app | Sign-in pages, the sign-in gate, role-aware navigation, the Admin Dashboard | `frontend/src/auth/`, `frontend/src/App.tsx`, `frontend/src/workspace/` |
| Command line | Setting a role by hand | `scripts/set_role.py` |

**One workspace, kept internally.** The workspace layer from 0012 stays. Every team-private row carries
`workspace_id`, and a session is bound to a membership. Migration 0015 creates exactly one workspace, team 11's, and
every account is a membership in it. A unique index on a constant (`workspaces_single_team`) allows no second row.
Keeping the layer left the team scouting and live-draft code unchanged. Nobody types a team number anywhere.

The authentication stays built in: stdlib scrypt for passwords, and server-side sessions in the same PostgreSQL, with
no external provider. Row-level security is still not used. The reasons are unchanged from 0012: the API connects as
one role, and locally that role is a superuser.

## 2. Roles

| | admin | base |
|---|---|---|
| Events list (`/`) and an event's page (`/events/:eventKey`), read-only | yes | yes |
| Their own account (`/account`): name, email, role, change password, log out | yes | yes |
| Everything else: team, match and report pages, strategy lab, alliance selection, live draft, drive team and scouting dashboards, historical explorer, system status, game manuals, rulesets, human inputs | yes | no |
| Members page: see members, change a role, suspend, remove | yes | no |

What a base member holds is fixed in code (`ROLE_GRANTS` in `workspaces/permissions.py`): `team_info`,
`event_analysis` and `qualification_forecast`. Those are exactly the routes the two event pages call:
- `GET /events`
- `GET /events/{key}/teams`
- `GET /events/{key}/matches`
- `GET /events/{key}/analysis`
- `GET /events/{key}/qualification-forecast`

An administrator holds every permission. Nothing is configurable per team, so no administrator action can widen what
base sees.

Where base is refused:
- **API.** Every other route answers base with `403 permission_denied`. `tests/test_workspaces_api.py` checks this
  for every GET route in the live OpenAPI schema, so a route added later is covered automatically.
- **Web app.**
  - Base sees only *Events* in the navigation.
  - Any other page shows "Your role does not include this page" and loads none of its data.
  - On an event page, team, match and report entries appear as plain text, not links, and the alliance-selection and
    strategy-lab buttons are hidden.

**Adding a role later:**
1. Add the role to `ROLES` and `ROLE_LABELS`.
2. Give it an entry in `ROLE_GRANTS`.
3. Extend the role CHECK constraint on `team_memberships` in a migration.
4. Add its page allow-list to `pageAllowed` in `frontend/src/auth/roles.ts`.

A team must keep at least one active administrator. A demotion, suspension or removal that would leave none is
refused, by the application and again by a database trigger.

## 3. Signing up, signing in, and roles

- **Sign-up** (`/auth/signup`, `POST /auth/signup`): full name, email, password and a **team join code**. There
  are two codes, both environment settings:
  - `TEAM_JOIN_CODE` signs someone up as a **base** member;
  - `TEAM_ADMIN_JOIN_CODE` signs someone up as an **admin**. It must differ from the member code, or the server
    refuses to start. Anyone who has it can become an admin, so make it long and random, and share it only with
    those who should be admins.

  How the codes are checked:
  - Both codes are compared in constant time, and they are checked before anything else, so only someone who
    already has a code can learn whether an email is taken.
  - A wrong code answers `403 invalid_join_code`. With neither code configured, sign-up is closed
    (`403 signup_closed`).
  - Emails are unique in any case. They are stored lowercased (`409 email_already_registered`).
  - The password needs at least 8 characters. There is no other rule.
  - The role comes from the code. An email in `ADMIN_EMAILS` (optional, comma-separated, any case) is an
    **admin** whichever code it used. The person is signed in at once.
- **Sign-in** (`/auth/login`): email and password only. Failures all read `invalid_credentials` and take the same
  time.
- **After sign-in:** an administrator lands on the Admin Dashboard (`/team`) and a base member on the events (`/`). A
  `?next=` target is followed only if that role may open it.
- **Changing a role:**
  - In the web app: Team Management (`/team`, tab *Team Management*).
  - From the command line, on a machine with the deployment's `DATABASE_URL`. On Render, use the API service's Shell:

    ```
    python -m scripts.set_role someone@example.com admin
    python -m scripts.set_role someone@example.com base
    ```

    This also restores a suspended or removed member. A removed member's email stays taken, so they cannot sign up
    again. The change is recorded in the activity log as done from the command line.
- **Removing** a member ends their sessions at once, cancels their open scouting assignments, and keeps their past
  scouting attributed to them.
- `ADMIN_EMAILS` applies only at sign-up. To promote someone who already has an account, use Team Management or
  `scripts.set_role`.

## 4. Passwords and reset codes

- **Changing your password** (`/account`) needs your current password, and ends your other sessions.
- **Forgot password** (`/auth/forgot`, then `/auth/reset`):
  1. Enter your email. If it belongs to an active member and email is configured, StratAI emails a **6-digit code**.
     The answer, and how long it takes, are the same either way: the account lookup and the email run in a background task after the answer is sent. So it never reveals whether an account exists.
  2. Enter your email, the code and a new password. On success, every session you hold ends and you are signed in.
- **The code:**
  - works once, for 15 minutes;
  - is dead after 5 wrong tries;
  - is retired when you ask for a new one.
- **Storage:** only a salted SHA-256 of the code is stored (`password_reset_codes`).
- **Requests are limited** to 3 codes per email per hour, so asking again cannot get around the 5-try limit. At most
  that is 15 guesses an hour against a million possible codes.
- **Delivery** uses the existing mailer: SMTP when `SMTP_HOST` and `SMTP_FROM` are set, or, in development only,
  files written to `DEV_OUTBOX_DIR`. Without either, no code can be sent. The page says so and suggests asking an
  administrator. There is no administrator-issued reset; an administrator can only change the person's role or remove
  them.

## 5. The whole site is behind sign-in

**Web app.** Only these pages open without signing in:
- `/auth/login`
- `/auth/signup`
- `/auth/forgot`
- `/auth/reset`
- `/auth`, which just forwards to `/auth/login`

Anything else sends a visitor to `/auth/login?next=...`. Until the session is known, no page renders, so none starts a
request.

**API: `ACCESS_POLICY`.** Each analytics router carries a permission gate (`api/app.py`):

| Routes | Permission | base? |
|---|---|---|
| events, rosters, schedules | `team_info` | yes |
| event analysis | `event_analysis` | yes |
| qualification forecast | `qualification_forecast` | yes |
| historical season explorer | `season_explorer` | no |
| team metrics and strength | `team_analytics` | no |
| predictions | `match_predictions` | no |
| alliance selection | `alliance_selection` | no |
| strategy, pre-match report, briefing | `strategy_tools` | no |
| game manuals, rulesets, capability profiles, human inputs | `platform_inputs` (or the platform write token) | no |

The two policies:
- **`members`** requires a signed-in member who holds the route's permission. Otherwise the route answers 401
  `not_authenticated` or 403 `permission_denied`. This is the default whenever `ENV` is `production` or `staging`,
  and `render.yaml` also sets it explicitly. The health probes (`/health`, `/ready`) and `GET /auth/session` stay
  open.
- **`open`** lets anyone read the analytics routes. It is the default only in development, where the API test suite
  runs without signing in.

The `/workspace/...` routes always need a session, whatever the policy.

**Contract lock.** The gates add nothing to any operation's OpenAPI contract: `python -m scripts.phase7_contract_lock
check` reports no change under either policy. Under `members`, locked operations do answer 401 and 403 at runtime.
That was the documented cost of turning `members` on, and it was decided on 2026-11-11 (RUNNING_NOTES.md). The public
read-only demo ends with it.

## 6. Team scouting stays with the team

Team scouting is stored in `workspace_scouting_reports`, never in the shared `scouting_observations`. It passes the
same validation (`data.metrics.normalizer`) and uses the same summary method (`aggregate_defense_feeding`). Defense and
feeding come only from what scouts recorded. Since 2026-11-11, scouting is an administrator tool.

## 7. Security measures

- **Passwords:**
  - scrypt (N=2^15, r=8, p=3) with a per-password salt and constant-time comparison;
  - at least 8 characters, at most 256 (the upper bound keeps hashing time bounded);
  - re-hashed at sign-in if the cost is raised.
- **Join code:**
  - an environment secret (`SecretStr`, never printed);
  - compared with `hmac.compare_digest`;
  - never in the repository, which is public.
- **Sessions:**
  - a 256-bit random token in an `HttpOnly`, `SameSite=Lax` cookie, `Secure` outside development; only its hash is
    stored;
  - a lifetime of `SESSION_TTL_HOURS` and an idle limit of `SESSION_IDLE_HOURS`;
  - re-resolved on every request, so suspension, removal and role changes apply at once.
- **CSRF:** every state-changing `/auth` and `/workspace` request needs `X-StratAI-CSRF: 1`.
- **Rate limits** (`workspaces/rate_limit.py`):

  | Scope | Limit | What counts |
  |---|---|---|
  | `login_account` | 5 per email per 15 min | failures |
  | `login_ip` | 100 per address per 15 min | failures |
  | `signup_code_ip` | 10 per address per 15 min | wrong join codes only |
  | `signup_code_global` | 50 across all addresses per hour | wrong join codes only |
  | `reset_request_account` | 3 per email per hour | every request |
  | `reset_request_ip` | 30 per address per hour | every request |
  | `reset_code_ip` | 30 per address per 15 min | wrong or dead codes |
  | `password_check_user` | 5 per account per 15 min | wrong current passwords |

  Only wrong join codes count, so a team signing up together at a meeting is never slowed. The global limit means
  someone guessing the code from many addresses locks sign-up for everyone for up to an hour. That is the intended
  trade-off: change the code if it happens.
- **Secrets stay out of URLs and logs.** The join code, passwords and reset codes travel only in request bodies.
  Request logging records the path only.

## 8. Configuration

Secrets go in the environment, never in a committed file (`data/config.py`, `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `ACCESS_POLICY` | `members` outside development, `open` in development | section 5 |
| `TEAM_JOIN_CODE` (secret) | unset | the code that signs up a base member |
| `TEAM_ADMIN_JOIN_CODE` (secret) | unset | the code that signs up an admin; must differ from `TEAM_JOIN_CODE` |
| `ADMIN_EMAILS` | empty | optional: emails that sign up as admin whichever code they use |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` (secret), `SMTP_FROM`, `SMTP_STARTTLS` | unset, `587`, unset, unset, unset, `true` | outgoing email for reset codes |
| `DEV_OUTBOX_DIR` | unset | development only: write emails to this folder instead of sending them |
| `PUBLIC_APP_URL` | unset | the web app's address, mentioned in reset emails |
| `AUTH_TRUSTED_PROXY_HOPS` | `0` | proxies in front of the API, so rate limits see the client address (hosted: Vercel then Render) |
| `SESSION_COOKIE_SECURE` | secure unless `ENV=development` | send the session cookie only over HTTPS |
| `SESSION_TTL_HOURS`, `SESSION_IDLE_HOURS` | `336`, `72` | session lifetime and idle limit |

## 9. Running it locally

```
python database/migrate.py            # applies every pending migration, through 0015, to DATABASE_URL's database
python -m api                         # the API on http://127.0.0.1:8000
cd frontend && npm ci && npm run dev  # the web app on http://localhost:5173 (proxies /api to the API)
```

Before testing locally, set these:
- **A disposable database.** Point `DATABASE_URL` at a `stratai_test_<suffix>` copy, never the serving `stratai`.
  0015 deletes every account.
- **The environment:**
  - `ENV=development`, so the session cookie works over plain http;
  - `TEAM_JOIN_CODE=<anything>`, so sign-up is open;
  - `ADMIN_EMAILS=<your email>`, so your sign-up makes you an admin;
  - `DEV_OUTBOX_DIR=./.outbox`, to read reset codes from files.
- **Members-only locally (optional):** development defaults to `ACCESS_POLICY=open`. Set `ACCESS_POLICY=members` to
  test members-only behaviour exactly as hosted.
- **Restart `python -m api` after updating the code.** It never reloads. An older API has no `/auth/signup`, and the
  sign-in pages say "This StratAI server does not have accounts yet".

Tests (database-backed tests run only on an isolated `stratai_test` copy, per the test-database guard):

```
python -m pytest tests/test_workspaces_units.py tests/test_workspaces_api.py tests/test_phase11_live_draft_api.py
cd frontend && npx vitest run src/auth src/workspace
```

## 10. Known limitations

- **Email needs an SMTP account.** Without one, a forgotten password cannot be reset by email.
- **No multi-factor authentication** and no single sign-on.
- **The global wrong-code limit can be used to block sign-up for an hour.** Change the code if that happens.
- **Per-address rate limits are coarse behind proxies** unless `AUTH_TRUSTED_PROXY_HOPS` is set.
- **Changing either join code does not affect existing accounts.** It only gates new sign-ups. If the admin code
  leaks, change it and check the members page for unexpected administrators.
