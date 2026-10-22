# Hosted deployment (public data, read-only)

This is a demo deployment. It is **not** a production launch: Phase 10 M4–M6 are still blocked, and M7 is not done.

| Part | Host | Config |
|---|---|---|
| Web app (React/Vite) | Vercel | `frontend/vercel.json` |
| API (FastAPI) | Render web service | `render.yaml` |
| PostgreSQL | Render Postgres 17 | `render.yaml` |

How the pieces connect:
- The web app calls `/api/...` on its own origin, as it does in development.
- Vercel rewrites `/api/:path*` to the Render API and drops the prefix, as the Vite dev proxy does. The browser never
  makes a cross-origin request, so `CORS_ORIGINS` stays at its default and is not widened.
- **Writes are off.** `HUMAN_INPUTS_WRITE_TOKEN` is not set, so every write route answers 403
  (`/human-inputs/write-access` reports `writes_enabled: false`).
- **Data is public only:** TBA match results and Statbotics EPA. The dump has no scouting observations and no
  human inputs. Every defense and feeding metric is cleared, so those show as unavailable.
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
4. Redeploy `stratai-api`, then open `https://<service>.onrender.com/ready`. It should answer
   `{"status":"ready",...}`.

If Render gives the service a name other than `stratai-api.onrender.com`, change the rewrite destination in
`frontend/vercel.json` to match.

## 3. Deploy the web app on Vercel

1. In Vercel, go to **Add New → Project** and import the repository.
2. Set **Root Directory** to `frontend`. The framework (Vite) and the build settings come from `vercel.json`.
3. Deploy. You need no environment variables, because `VITE_API_BASE` keeps its `/api` default.

## Caveats

- **Cold starts.** A Render free web service sleeps when idle. The first request after a sleep can take about a
  minute, and Vercel's rewrite may time out on it; retry after the API wakes.
- **Free database expiry.** A Render free database expires after 30 days. Keeping it costs about $7 a month.
- **Refreshing the data.** Rebuild the dump and run `pg_restore --clean --if-exists` again.
