# Hosted deployment (Team 11, members only)

This deployment is for FRC Team 11 (MORT) only. Every page and every analytics route needs a signed-in member
(docs/team_workspaces.md). It is **not** a production launch: Phase 10 M4–M6 are still blocked, and M7 is not done.

| Part | Host | Config |
|---|---|---|
| Web app (React/Vite) | Vercel | `frontend/vercel.json` |
| API (FastAPI) | Render web service | `render.yaml` |
| PostgreSQL | Neon (PostgreSQL 17, AWS us-west-2) | `DATABASE_URL` on the Render API (section 2) |

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
- **Three trained models are deployed** with the code (section 5): event rankings, win probability and the strategy
  model. The playoff model is not (PX-1 failed its gate), so the pick list answers `model_not_loaded`.

## 1. Build the data dump (local)

```bash
python -m scripts.deploy_public_dump
```

What the script does:
1. Reads `stratai_test`.
2. Scrubs a disposable copy and verifies that no scouting row remains.
3. Writes `.deploy/stratai_public.dump`, which is gitignored and never committed.
4. Drops the copy.

## 2. Create the database on Neon and the API on Render

The database moved from Render Postgres to Neon on 2026-11-17 (Render's free databases expire after 30 days).

1. **Neon:** create a project in the same region as the Render API (AWS us-west-2, Oregon), PostgreSQL 17, with a
   database named `stratai`. Copy the **direct** connection string: the host has no `-pooler`, and it ends in
   `sslmode=require`. Use the direct endpoint, not the pooler: the app opens a short connection per request, and
   psycopg's automatic prepared statements are not safe through a transaction pooler.
2. Load the dump into the empty database:

   ```bash
   pg_restore --no-owner --no-privileges --single-transaction --exit-on-error \
     --dbname "<Neon direct connection string>" .deploy/stratai_public.dump
   ```

   Never paste a connection string into a file that is committed, or into a chat.
3. **Render:** push the branch that holds `render.yaml`, then **New → Blueprint** and pick the repository. Render
   creates `stratai-api` (it no longer creates a database).
4. In the `stratai-api` service's **Environment** tab, set `DATABASE_URL` to the Neon direct connection string, and
   the other variables that `render.yaml` marks `sync: false` (section 4).
5. Redeploy `stratai-api`, then open `https://<service>.onrender.com/ready`. It should answer
   `{"status":"ready",...}`.
6. Open the web app, sign up with the admin join code, and check that you land on the Admin Dashboard.

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
| `TEAM_JOIN_CODE` | a random code you choose; signs up base members; share it with the team | set by hand (`sync: false`), never committed |
| `TEAM_ADMIN_JOIN_CODE` | a different, long random code; signs up admins; share it only with admins | set by hand (`sync: false`), never committed |
| `ADMIN_EMAILS` | optional: emails that sign up as admin whichever code they use | set by hand (`sync: false`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | your mail provider's SMTP settings | set by hand; without them "forgot password" cannot send a code |
| `BREVO_API_KEY` | a Brevo API key (SMTP & API → API keys) | set by hand. Render's free plan blocks outgoing SMTP, so set this there: email then goes through Brevo's HTTPS API, from `SMTP_FROM`, which must be a verified sender in Brevo |
| `AUTH_TRUSTED_PROXY_HOPS` | `2` (Vercel, then Render) | set by hand; without it every request shares the proxy's address for rate limiting |
| `PUBLIC_APP_URL` | `https://mortstratai.vercel.app` (optional) | set by hand; named in reset emails |

**Vercel:** none. The web app calls `/api` on its own origin and reads everything else from `GET /auth/session`.

### 4.1 Setting and verifying `AUTH_TRUSTED_PROXY_HOPS` (audit 2026-11-26, workstream 5)

The sign-in, sign-up and password-reset rate limits key on the caller's address (`workspaces/rate_limit.py`). Behind
proxies the connecting peer is the last proxy, so without this setting every member shares one bucket, and one
person's typos can lock the whole team out of signing in.

**The chain.** browser → Vercel (the `/api` rewrite in `frontend/vercel.json`) → Render's load balancer → the app.
Vercel sends the browser's address in `X-Forwarded-For`; Render appends the address that connected to it (Vercel's
outbound address). The app counts `AUTH_TRUSTED_PROXY_HOPS` entries **from the right** (`api/session.py`,
`client_ip`), so with `2` it uses the browser's address, and anything a client writes into its own header (left of
those entries) is ignored. An entry that is not an IP address falls back to the connecting peer.

This topology was reasoned from the two hosts' documented behaviour; it could not be observed from the development
machine. Verify it after setting it:

1. Render dashboard → `stratai-api` → **Environment** → **Add Environment Variable**: key `AUTH_TRUSTED_PROXY_HOPS`,
   value `2`. Change nothing else. Save; Render redeploys the service.
2. Sign in to the web app as an administrator, then open `https://mortstratai.vercel.app/api/auth/network-check`
   in the same browser (the session cookie authorizes it; base members get 403).
3. Expected: `"forwarded_entries": 2`, `"consistent": true`, `"address_source": "x_forwarded_for"`, and
   `rate_limit_address` equal to your network's public address (compare with any "what is my IP" page).
4. Repeat from a second network (for example a phone on mobile data). `rate_limit_address` must change to that
   network's address. If both networks show the same address, the setting is wrong.

If the check disagrees:
- `forwarded_entries` is **3 or more** on every request: another proxy appends an entry. Set the value to
  `forwarded_entries` and check again (step 4 is what proves it).
- `forwarded_entries` is **1**: only one proxy appends. Set `1`, and check step 4 again.
- `forwarded_entries` is **0**: no proxy sends the header. Remove the variable (the peer is then used).

Known limit: a request sent straight to `https://stratai-api.onrender.com` (bypassing Vercel) passes through one
proxy, not two, so the entry the app uses there is the one the client wrote itself. Such a client can pick its own
rate-limit bucket on the per-address limits. The per-account limits (`login_account`, `reset_request_account`) and
the global join-code limit (`signup_code_global`) do not depend on the address and still apply. Closing this fully
needs Render to accept traffic only from Vercel, which the free plan does not offer.

**Promoting someone later:** in the web app's Team Management, or in the Render Shell for `stratai-api`:
`python -m scripts.set_role someone@example.com admin`.

## 5. Trained models

Render's free plan has no persistent disk, so the models ship with the code, in `deploy/ml_registry/` (about 800 KB):

| Model | Folder | Serves |
|---|---|---|
| `ranking_xgb_v2` `d18` | `deploy/ml_registry/ranking_xgb_v2/d18/` | event rankings and contenders |
| `win_prob_xgb_calibrated` `d18` | `deploy/ml_registry/win_prob_xgb_calibrated/d18/` | match win probability |
| `strategy_outcome_component` `p6m10-v1` | `deploy/ml_registry/strategy_outcome_component/p6m10-v1/` | the strategy lab |

- **Pinned.** `render.yaml` sets `ML_REGISTRY_DIR=deploy/ml_registry` and each model's version tag and sha256. The
  API loads a model only when its `model.json` matches the pin; otherwise that feature answers `model_not_loaded`.
  `tests/test_hosted_models.py` checks the pins against the committed files and loads all three.
- **Their source.** These are copies of the registered artifacts: the D18 registration
  (`.agent/production/d18_model_registration.json`) for the two D18 models, and P6-M10
  (`.agent/phase6/M10_ACCEPTANCE.md`) for the strategy model. The sha256 values are the recorded ones.
- **EPA on the hosted API stays live Statbotics** (`EPA_SOURCE=statbotics`). The models were checked against it
  locally on 2026-11-16 (event analysis served for `2026mrcmp` and `2026njfla`). The evaluated configuration,
  `d18_statbotics_primary`, needs a 185 MB EPA chain that is not deployed.
- **The models are public.** The repository is public, so anyone can download these files. They are trained only on
  public TBA and Statbotics data.
- **Replacing a model:** commit the new folder and change its version tag and sha256 in `render.yaml` in the same
  commit. The test fails if they disagree.

## Caveats

- **Cold starts.** A Render free web service sleeps when idle. The first request after a sleep can take about a
  minute, and Vercel's rewrite may time out on it; retry after the API wakes.
- **Neon free plan.** 0.5 GB of storage (the hosted data was 229 MB on 2026-11-17, most of it raw source payloads that
  grow during a season); the compute sleeps after about 5 minutes idle, so the first query after a pause is a little
  slower; compute hours are limited per month (check Neon's current allowance).
- **Refreshing the data** keeps the accounts: stage the public tables and swap them in a short transaction (the
  2026-11-16 reload; RUNNING_NOTES). Never TRUNCATE the live tables inside one long transaction over the network.
- **Backups.** Before any data change, `pg_dump --format=custom --no-owner --no-privileges` the live database into
  `.deploy/` (gitignored). Neon also keeps a short point-in-time history (its restore window) for the free plan.
- **Moving between hosts** (as from Render to Neon): dump, restore into the empty new database, compare every table's
  row count, take a fresh dump at the moment of the switch, change `DATABASE_URL`, redeploy, and keep the old database
  as the rollback until the new one is confirmed.
- **An existing database needs migration 0015.** A database restored from an older dump lacks the account tables, and
  the sign-in pages say "Accounts are not set up on this server's database". Either restore a new dump (built from a
  `stratai_test` that has 0015), or run `python database/migrate.py` against the hosted database. 0015 deletes every
  existing account.
- **Per-address limits can be bypassed** by calling the Render URL directly with a forged `X-Forwarded-For`. The
  per-email limits and the global wrong-join-code limit do not depend on the address.
