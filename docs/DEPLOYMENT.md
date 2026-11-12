# Hosted deployment (Team 11, members only)

This deployment is for FRC Team 11 (MORT) only. Every page and every analytics route needs a signed-in member
(docs/team_workspaces.md). It is **not** a production launch: Phase 10 M4–M6 are still blocked, and M7 is not done.

| Part | Host | Config |
|---|---|---|
| Web app (React/Vite) | Vercel | `frontend/vercel.json` |
| API (FastAPI) | Render web service | `render.yaml` |
| PostgreSQL | Render Postgres 17 | `render.yaml` |

How the pieces connect:
- The web app calls `/api/...` on its own origin, as it does in development.
- Vercel rewrites `/api/:path*` to the Render API and drops the prefix, as the Vite dev proxy does. The browser never
  makes a cross-origin request, so `CORS_ORIGINS` stays at its default and is not widened.
- **Sign-in is required.** `ACCESS_POLICY=members`, so anonymous requests to the analytics routes answer 401.
  New members sign up at `/auth/signup` with the team join code (`TEAM_JOIN_CODE`).
- **Writes are off.** `HUMAN_INPUTS_WRITE_TOKEN` is not set, so every write route answers 403
  (`/human-inputs/write-access` reports `writes_enabled: false`).
- **Data is public only:** TBA match results and Statbotics EPA. The dump has no scouting observations, no
  human inputs and no accounts (only team 11's empty workspace, which sign-up needs). Every defense and feeding metric is cleared, so those show as unavailable.
- **No trained models are deployed.** Win probability, event analysis and qualification forecast answer
  `model_not_loaded` until the d18 artifacts are installed and pinned.

## 1. Build the data dump (local)

```bash
python -m scripts.deploy_public_dump
```

What the script does:
1. Reads `stratai_test`.
2. Scrubs a disposable copy and verifies that no scouting row remains.
3. Writes `.deploy/stratai_public.dump`, which is gitignored and never committed.
4. Drops the copy.

## 2. Create the API and database on Render

1. Push the branch that holds `render.yaml` to GitHub.
2. In the Render dashboard, go to **New → Blueprint** and pick the repository. Render creates `stratai-db` and
   `stratai-api`.
3. Wait for `stratai-db` to become available. Then copy its **External Database URL** and load the dump:

   ```bash
   pg_restore --no-owner --no-privileges --dbname "<External Database URL>" .deploy/stratai_public.dump
   ```

   Never paste that URL into a file that is committed.
4. In the `stratai-api` service's **Environment** tab, set the variables that `render.yaml` marks `sync: false`
   (section 4).
5. Redeploy `stratai-api`, then open `https://<service>.onrender.com/ready`. It should answer
   `{"status":"ready",...}`.
6. Open the web app, sign up with the join code using an email listed in `ADMIN_EMAILS`, and check that you land on
   the Admin Dashboard.

If Render gives the service a name other than `stratai-api.onrender.com`, change the rewrite destination in
`frontend/vercel.json` to match.

## 3. Deploy the web app on Vercel

1. In Vercel, go to **Add New → Project** and import the repository.
2. Set **Root Directory** to `frontend`. The framework (Vite) and the build settings come from `vercel.json`.
3. Deploy. You need no environment variables, because `VITE_API_BASE` keeps its `/api` default.

## 4. Environment variables

**Render (`stratai-api`):**

| Variable | Value | Where it comes from |
|---|---|---|
| `ACCESS_POLICY` | `members` | `render.yaml` (also the default when `ENV=production`) |
| `TEAM_JOIN_CODE` | a long random code you choose; share it only with the team | set by hand (`sync: false`), never committed |
| `ADMIN_EMAILS` | the administrators' emails, comma-separated | set by hand (`sync: false`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | your mail provider's SMTP settings | set by hand; without them "forgot password" cannot send a code |
| `AUTH_TRUSTED_PROXY_HOPS` | `2` (Vercel, then Render) | set by hand; without it every request shares the proxy's address for rate limiting |
| `PUBLIC_APP_URL` | `https://mortstratai.vercel.app` (optional) | set by hand; named in reset emails |

**Vercel:** none. The web app calls `/api` on its own origin and reads everything else from `GET /auth/session`.

**Promoting someone later:** in the web app's Team Management, or in the Render Shell for `stratai-api`:
`python -m scripts.set_role someone@example.com admin`.

## Caveats

- **Cold starts.** A Render free web service sleeps when idle. The first request after a sleep can take about a
  minute, and Vercel's rewrite may time out on it; retry after the API wakes.
- **Free database expiry.** A Render free database expires after 30 days. Keeping it costs about $7 a month.
- **Refreshing the data.** Rebuild the dump and run `pg_restore --clean --if-exists` again.
- **An existing database needs migration 0015.** A database restored from an older dump lacks the account tables, and
  the sign-in pages say "Accounts are not set up on this server's database". Either restore a new dump (built from a
  `stratai_test` that has 0015), or run `python database/migrate.py` against the Render database. 0015 deletes every
  existing account.
- **Per-address limits can be bypassed** by calling the Render URL directly with a forged `X-Forwarded-For`. The
  per-email limits and the global wrong-join-code limit do not depend on the address.
