# STRATAI web app

Two areas share this app:
- **Strategy dashboard (Phase 8):** events, team profiles, match strategy, alliance selection and the shareable
  pre-match report, built on the Phase 7 API. See `docs/phase8.md` for the views, the rules they follow and how to
  verify them.
- **Human inputs (P5-M8 / P5-M9 / DM1):** described below. These pages now live under `/inputs`; the old paths
  redirect.

## Human inputs

This app lets people enter, review and approve the human inputs that STRATAI's game analysis and DM1 need, without editing the database, code or seed files. It is built only on the `/human-inputs` API (`api/routes/human_inputs.py`). Storage and every rule live in `data/human_inputs.py`.

| Page | What a person does there |
|---|---|
| **Inputs overview** (`/inputs`) | Sees each DM1 input's state, and DM1's done-means as the write-once records report it. The page never decides DM1. |
| **Game manual & spec** (`/inputs/game`) | Uploads the official manual PDF (kept write-once under its sha256, with the checksum compared in the browser). Enters a structured game specification as immutable versions, submits a complete version for review, and approves it or returns it with a note. |
| **Team profiles** (`/inputs/profiles`) | Creates, edits (each save is a new version), duplicates and archives capability profiles. Views the history and the deterministic P5-M9 recommendation with its reasoning and `heuristic_not_validated_against_outcomes` label. |
| **Human review** (`/inputs/review`) | Works through the codebook, two independent codings over the curated reference rows, codebook agreement (κ), the consensus coding (offered only after κ), the action→function map, the rubric and the mentor review. Each version is listed, and named sign-off establishes the kinds that need it. |

Nothing in the app reads the manual, fills a field automatically or calls an LLM. Every blank field is sent as missing, so the server's model names what is incomplete; the page never supplies a default.

## Running it

```sh
# API (the human-input routes need migration 0010 applied to the database it serves)
HUMAN_INPUTS_WRITE_TOKEN=<token> python -m api        # http://127.0.0.1:8000

# web app
cd frontend
npm install
npm run dev                                            # http://localhost:5173
```

The dev server proxies `/api` to the API (`STRATAI_API_URL`, default `http://127.0.0.1:8000`), so the browser talks to one origin. This is deliberate. The API's CORS allow-list admits only GET and POST with `Content-Type`, and it is not widened for PUT or the write-token header. In production, serve `npm run build`'s `dist/` behind the same origin as the API, with `/api` routed to it (or set `VITE_API_BASE`).

**Writes** need the `X-StratAI-Write-Token` header:
- Enter the token in the page header. It is kept in memory only.
- With no token configured on the server, every write is refused (fail closed).
- Your name, also entered in the header, is recorded on every change.

## Tests

```sh
npm test            # vitest + Testing Library; fetch is mocked, with synthetic fixtures only
npm run build       # type-check and production build
```

`tests/test_frontend_api_contract.py` checks every route listed in `src/api/client.ts`'s `ENDPOINTS` against the API's OpenAPI schema, in both directions.
