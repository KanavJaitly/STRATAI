# Team workspaces: accounts, roles and team-private data

Each FRC team gets its own StratAI workspace on the same site. A workspace has its own members, roles, permissions,
settings, activity log and private scouting. Every person signs in with their own account. There is no shared team
password and no choosing a name from a list.

Introduced 2026-11-02 with migration `0012_team_workspaces.sql`.

## 1. Architecture

| Part | Responsibility | Where |
|---|---|---|
| Accounts and sessions | Individual accounts, password hashing, sessions, password changes and resets | `workspaces/accounts.py`, `workspaces/sessions.py`, `workspaces/passwords.py` |
| PostgreSQL | Teams, memberships, roles, permissions, invitations, activity log, team scouting | migration 0012; `docs/data_pipeline.md` section 4.5 |
| FastAPI | Session verification and every authorization decision, on the server | `api/session.py`, `api/routes/auth.py`, `api/routes/workspace.py`, `api/routes/team_scouting.py` |
| React web app | Registration, sign-in, invitations, the Admin Dashboard, role dashboards, navigation | `frontend/src/auth/`, `frontend/src/workspace/` |

### Why the authentication is built in, not Supabase Auth

No part of StratAI used Supabase: the database is a plain PostgreSQL (local, or Render's), and there was no Supabase
project, URL or key. Adding it would mean:
- an external account and project;
- service keys on the API;
- network calls on every sign-in;
- a second user store to keep in step with `team_memberships`.

None of that could be tested in isolation, and Supabase's row-level security keys on Supabase's own JWT claims, which
a non-Supabase PostgreSQL never sees. The built-in provider needs no new dependency and no external service:
- **Passwords:** stdlib scrypt.
- **Sessions:** server-side, in the same PostgreSQL.

`users.auth_provider` and `users.auth_subject` exist so a later move to an external provider can map its users onto
the same memberships without a schema change.

### Why there is no row-level security

Tenant isolation is enforced in the application, by construction, and tested:
- The workspace is taken only from the server-side session, never from a path, query or body.
- Every query on team-private data filters on it.
- An id from another workspace is therefore simply "not found".

The database adds what it can enforce for every connection:
- **Composite foreign keys:** a report's author, and an assignment's scout, must be members of the same workspace.
- **CHECK constraints:** administrative permissions can never be stored for another role.
- **A trigger:** a workspace always keeps an active administrator.
- **Unique indexes:** one active workspace per team number; one pending invitation per email.

PostgreSQL row-level security was considered and not used:
- The API connects as one role.
- Locally that role is a superuser, which bypasses every policy.
- A forced policy on the owning role would break `pg_dump` and `pg_restore` of the public deployment dump.

So RLS would have looked like a protection without being one.

## 2. Roles and permissions

Three roles.
- **Administrators** always hold every permission.
- **The drive team / strategy role and the scouter role** hold what their team's administrators configure, starting
  from these defaults.

| Permission | Administrator | Drive team / strategy | Scouter |
|---|---|---|---|
| `team_info`: events, rosters, schedules, historical seasons | yes | yes | yes |
| `match_predictions`: win probability, rankings, alliance synergy | yes | yes | configurable (off) |
| `team_analytics`: team metrics and strength | yes | yes | configurable (off) |
| `event_analysis` | yes | yes | configurable (off) |
| `qualification_forecast` | yes | yes | configurable (off) |
| `alliance_selection` | yes | yes | configurable (off) |
| `strategy_tools`: strategy lab, pre-match report, briefing | yes | yes | configurable (off) |
| `scouting_forms`: scouting forms, own assignments and submissions | yes | yes | yes |
| `scouting_submit` | yes | configurable (off) | yes |
| `scouting_view`: all of the team's scouting and its summary | yes | yes | configurable (off) |
| `scouting_assign`: assigning scouts to matches | yes | yes | configurable (off) |
| `team_management`: members, invitations, roles, suspension, removal | yes | never | never |
| `manage_permissions` | yes | never | never |
| `team_settings` | yes | never | never |
| `activity_log` | yes | never | never |

"Configurable" means a team's administrator can switch the permission on or off for that role (the default is in
brackets). "Never" is enforced in four places, so no member can grant themselves more:
- `workspaces/permissions.py`;
- `set_role_permissions`;
- the API;
- the database CHECK constraint.

A team may have several administrators. A change that would leave no active administrator (a demotion, suspension or
removal) is refused, by the application and again by the database trigger.

## 3. Team registration and ownership verification

A team number and name are public, so registering them proves nothing.

1. **Register.** On the web app, choose *Login / Register to Your Team's StratAI*, then *Register a New Team*. Enter
   the team number, the team name and a one-time **setup password**. The workspace is created as
   `pending_verification`. Only one pending or verified workspace may exist per team number.
2. **First administrator.** With the setup password, the registrant creates their own account (full name, email,
   password). They become the first administrator and are signed in to the Admin Dashboard. The setup password then
   stops working; it is never a team login.
3. **Pending.** The administrator can configure the workspace (permissions, settings), but cannot invite members or
   hold scouting until the team is verified.
4. **Verification by a StratAI operator.** This step is not automated, and is never assumed or simulated.
   - The operator confirms out of band that the registrant speaks for the team. Acceptable checks:
     - an email from an address listed for the team on FIRST's official team information or the team's own website;
     - confirmation from the team's lead mentor through a contact the operator already trusts;
     - a verification phrase posted on the team's official website or social account.
   - Then, on a machine with the deployment's `DATABASE_URL`:

   ```
   python -m scripts.workspace_operator list --status pending_verification
   python -m scripts.workspace_operator verify --team 1676 --operator "Your Name" --note "how ownership was checked"
   python -m scripts.workspace_operator reject --team 1676 --operator "Your Name" --note "why"
   ```

   - The verdict, the operator and the note are recorded on the workspace and in its activity log.
   - Rejecting a workspace ends all its sessions and frees the number for the real team.
   - There is deliberately no HTTP route for this, so no web credential can verify a team.

**What still needs a person:** someone must act as the StratAI operator and decide which checks are enough. Until a
workspace is verified, its team cannot invite members.

## 4. Members, invitations and passwords

- **Inviting:** an administrator adds a member (full name, email, role). StratAI creates an invitation that works
  **once** and **expires** (`INVITATION_TTL_HOURS`, default 7 days).
  - If email is configured, the link is emailed; otherwise the administrator copies it and sends it themselves.
  - The token is in the link's `#fragment`, which browsers never send to any server.
  - Resending replaces the link, and the old one stops working.
- **Accepting:** the invited person opens the link and chooses their password. If they already have a StratAI
  account (from another team), they enter that password instead; their account is never replaced.
- **Signing in:** team number, email and their own password. The role is found automatically, and each role lands on
  its own dashboard:

  | Role | Lands on |
  |---|---|
  | Administrator | `/team` |
  | Drive team | `/drive-team` |
  | Scouter | `/scouting` |

- **Suspending** a member ends their sessions at once and refuses sign-in until they are reactivated.
- **Removing** a member does three things:
  - it ends their sessions and cancels their open assignments;
  - their past scouting stays attributed to them;
  - they can be invited back.
- **Passwords:**
  - **Changing yours** needs your current password and ends your other sessions.
  - **"Forgot password"** emails a single-use, 60-minute link if email is configured. The answer is the same whether
    or not the account exists.
  - **Without email,** an administrator can issue a reset link from Team Management. That is recorded in the activity
    log.
  - **A reset** ends every session of that person.

## 5. The dashboards

All three live in the existing StratAI shell and navigation, and link into the existing event, match and team pages.
What each shows follows the member's permissions.

- **Admin Dashboard** (`/team`), with these tabs:
  - Overview;
  - Team Management: the member table with search, role and status filters, and sorting by role, name or last
    login; plus adding, inviting, changing roles, editing, suspending, reactivating, removing, resending and revoking;
  - Permissions: the matrix above;
  - Analytics: membership, sign-ins, invitations and scouting activity;
  - Team Settings: team name, default event, scouting instructions;
  - Activity Log: actor, action, affected member, details and time, filterable.
- **Drive team dashboard** (`/drive-team`), for the chosen event:
  - event analysis, match predictions, team comparisons, qualification forecast, alliance selection and the strategy
    lab, each shown only with its permission;
  - the team's own scouting summary;
  - scouting assignments.
- **Scouting dashboard** (`/scouting`):
  - the team's instructions;
  - your upcoming assignments;
  - the scouting form (defense and feeding, 0–5, and notes);
  - the event's teams;
  - your submission history.

## 6. Team scouting stays with the team

Team scouting is stored in `workspace_scouting_reports`, never in the shared `scouting_observations`.
- **Why separate:** the shared table feeds the `team_metrics` every visitor and every other team can read, so one
  team's scouting there would reach its rivals.
- **Same rules:** a report passes the same scouting validation (`data.metrics.normalizer`).
- **Same summary method:** the team's summary uses the same `aggregate_defense_feeding`. Defense and feeding come
  only from what scouts recorded. Below two ratings, a value is shown as insufficient, never estimated.

Feeding team scouting into the shared defense/feeding metrics would need a product decision: what may be shared,
and with whom.

## 7. The existing StratAI routes: `ACCESS_POLICY`

Each existing router carries a permission gate:

| Routes | Permission |
|---|---|
| events, rosters, schedules, explorer | `team_info` |
| team metrics and strength | `team_analytics` |
| predictions | `match_predictions` |
| event analysis | `event_analysis` |
| qualification forecast | `qualification_forecast` |
| alliance selection | `alliance_selection` |
| strategy, pre-match report, briefing | `strategy_tools` |

There are two modes:
- **`ACCESS_POLICY=open`** (the default) keeps today's behaviour: the public analytics stay readable by anyone. That
  preserves the hosted public demo and the locked API contract (`docs/api_contract_lock.json`) exactly.
- **`ACCESS_POLICY=members`** requires a signed-in member holding the route's permission (401 `not_authenticated`,
  403 `permission_denied`). The health probes stay open.

In open mode, hiding a page from a role in the web app is a convenience, not a protection: the data is public.
Team-private routes (`/workspace/...`) always require a session in both modes.

**Turning on `members` is a decision for you.** It adds 401 and 403 responses to operations whose contracts are
locked (P7-DM2), so it needs a relock with a recorded decision, and it ends the public read-only demo.

The platform-wide human-input routes (game manuals, rulesets, capability profiles, coach inputs) keep the platform
write token (`HUMAN_INPUTS_WRITE_TOKEN`). They change data every team shares, so no team role may change them.

## 8. Security measures

- **Passwords:**
  - scrypt (N=2^15, r=8, p=3) with a per-password salt and constant-time comparison;
  - at least 12 characters, not common, not the email;
  - re-hashed on sign-in if the cost is raised.
- **Sessions:**
  - a 256-bit random token in an `HttpOnly`, `SameSite=Lax`, `Secure` cookie (not `Secure` in development); only its
    hash is stored;
  - lifetime `SESSION_TTL_HOURS` (14 days) and idle limit `SESSION_IDLE_HOURS` (72 hours);
  - re-resolved on every request, so suspension, removal, role and permission changes apply at once;
  - sign-out ends the session on the server.
- **CSRF:** every state-changing `/auth` and `/workspace` request needs `X-StratAI-CSRF: 1`. Together with
  `SameSite=Lax` and CORS refusing credentialed cross-origin requests, another site cannot act with a member's cookie.
- **Rate limits** (`workspaces/rate_limit.py`), on:
  - sign-in: 5 failures per account per 15 minutes, plus a looser per-address limit;
  - the setup password;
  - registration;
  - reset requests;
  - token use;
  - password checks.
- **No account enumeration:** failed sign-ins all answer `invalid_credentials` and take the same time, and reset
  requests always answer the same.
- **Secrets stay out of URLs and logs:** invitation and reset tokens travel only in request bodies and URL fragments,
  so they never reach a server log. Request logging records the path only.
- **Server-side authorization:** every rule is checked in the API and again in `workspaces/`; the web app's hiding
  is only a convenience. No secret is ever sent to the web app.

## 9. Configuration

Every setting is optional with a safe default (`data/config.py`). Secrets go in the environment, never in a
committed file.

| Variable | Default | Purpose |
|---|---|---|
| `ACCESS_POLICY` | `open` | `open` or `members` (section 7) |
| `SESSION_COOKIE_SECURE` | unset: secure unless `ENV=development` | send the session cookie only over HTTPS |
| `SESSION_TTL_HOURS` | `336` | session lifetime |
| `SESSION_IDLE_HOURS` | `72` | idle limit |
| `INVITATION_TTL_HOURS` | `168` | how long an invitation link works |
| `PASSWORD_RESET_TTL_MINUTES` | `60` | how long a reset link works |
| `PUBLIC_APP_URL` | unset | the web app's address, for links in emails; email is off without it |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` (secret), `SMTP_FROM`, `SMTP_STARTTLS` | unset, `587`, unset, unset, unset, `true` | outgoing email |
| `DEV_OUTBOX_DIR` | unset | development only: write emails to this folder instead of sending them |
| `AUTH_TRUSTED_PROXY_HOPS` | `0` | proxies in front of the API, for per-address rate limits (for example `2` behind Vercel and Render) |

## 10. Running it locally

```
python database/migrate.py          # applies 0012 to the database DATABASE_URL names
python -m api                       # the API on http://127.0.0.1:8000
cd frontend && npm ci && npm run dev  # the web app on http://localhost:5173 (proxies /api to the API)
```

For local email testing, set `ENV=development`, `PUBLIC_APP_URL=http://localhost:5173` and
`DEV_OUTBOX_DIR=./.outbox`. Verify a local test team with `python -m scripts.workspace_operator verify ...`.

Tests (database-backed tests run only on an isolated `stratai_test_<suffix>` copy, per the test-database guard):

```
python -m pytest tests/test_workspaces_units.py tests/test_workspaces_api.py tests/test_frontend_workspace_contract.py
cd frontend && npx vitest run src/auth
```

## 11. Known limitations

- **Verification needs a person** acting as the StratAI operator (section 3).
- **Email needs an SMTP account.** Without one, invitations are delivered by hand, and self-service password reset is
  unavailable (an administrator issues a reset link instead).
- **No multi-factor authentication** and no single sign-on.
- **Per-address rate limits are coarse behind proxies** unless `AUTH_TRUSTED_PROXY_HOPS` is set.
- **Team scouting does not feed the shared metrics** (section 6). The scouting form records the two measures the
  existing scouting model defines, defense and feeding; game-specific fields would need a season's scouting design.
- **`ACCESS_POLICY=members` is available but not on** (section 7).
- **The hosted public demo:** migration 0012 adds tables only and changes no D18 fingerprint, but the public
  deployment's database must still have it applied before accounts work there. The public dump script empties every
  account and team table (`scripts/deploy_public_dump.py`).
