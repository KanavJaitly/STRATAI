# StratAI — Running Notes

> ⚠️ **UPDATE THIS FIRST** when anything changes: stack decisions, milestone status, blockers, or key design choices. Commit it alongside the work it describes.

---

## 🔄 Project Status Tracker

| Field | Current Value |
|---|---|
| **Active Phase** | Phase 2 — Data Pipeline |
| **Active Milestone** | Milestone 8 — Pipeline orchestration & incremental state (next) |
| **Last Completed** | Milestone 7 — Canonical schema + repository load (merged to `main`, PR #1) |
| **Last Updated** | 2026-07-23 |
| **Current Blocker** | None |
| **Next Session Goal** | Start Milestone 8 |

---

## 🏗️ Tech Stack Decisions (confirmed, not placeholders)

| Layer | Decision | Notes |
|---|---|---|
| **Backend Language** | Python 3.11 | venv-based; `requirements.txt` (no pyproject) |
| **Database** | PostgreSQL 18 | local cluster, port 5432 |
| **DB Driver** | psycopg3 (sync) | context-managed `connection()`/`cursor()`, autocommit-on-exit |
| **Migrations** | Raw SQL in `database/migrations/*.sql` | applied in sorted order by `database/migrate.py`, tracked in `migrations_applied`. **No Alembic.** |
| **Validation** | Pydantic v2 | staging + source schemas |
| **HTTP client** | httpx | TBA / Statbotics clients |
| **Testing** | pytest | 113 passed / 9 skipped as of M7 |

---

## 📦 Phase 2 Milestone Tracker

| Milestone | Status | Notes |
|---|---|---|
| 1. Scaffold & config | ✅ Done | |
| 2. DB connection & initial schema | ✅ Done | `0001_initial.sql` created all canonical tables + `match_teams` |
| 3. Source connector + TBA client | ✅ Done | |
| 4. Landing raw ingestion writer | ✅ Done | |
| 5. Statbotics connector + landing | ✅ Done | `StatboticsTeamEventMetrics` lands EPA / W-L-T |
| 6. Staging normalizer & validation | ✅ Done | `StagingTeam/Event/Match`; strips `frc` prefix → `team_number` int |
| 7. Canonical schema + repository load | ✅ Done | see decisions below (merged PR #1) |
| 8. Pipeline orchestration & incremental state | ⬜ Next | extraction → landing → staging → serving, one runnable flow |
| 9. Data quality checks & audit tracing | ⬜ Not Started | |
| 10. Docs & validation harness | ⬜ Not Started | |

**Status Key:** ⬜ Not Started &nbsp; 🟡 In Progress &nbsp; 🔵 In Review &nbsp; ✅ Done

---

## 📐 Key Design Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-23 | **Re-keyed canonical layer to `team_number`** (`0005_canonical.sql`) | `0001` had keyed teams on `team_key` TEXT (`"frc1114"`), but M6 staging strips the prefix to `team_number` INT. Tables were empty, so drop-and-recreate lost no data. Confirmed with Kanav. `events`/`matches` left untouched (already compatibly keyed). |
| 2026-07-23 | **Kept `match_teams` junction** (not `int[]` arrays) | True FK integrity on roster membership — arrays can't enforce it. Junction already existed in `0001`. |
| 2026-07-23 | **`team_event_stats` sourced from Statbotics (M5)** | Added `StagingTeamEventStats` + `normalize_statbotics_team_event_stats` so the M7 loader is exercised end-to-end, not just against hand-built rows. `epa_endgame` nullable (Statbotics may not provide it). |

---

## 🐛 Known Issues / Tech Debt

- [ ] **Pre-existing config test bug** (not from M7): `tests/test_config.py::test_settings_allows_missing_statbotics_api_key` fails when a `.env` exists at project root (created by `cp .env.example .env`). Cause: `config.py` `load_dotenv(override=False)` + leaked `DATABASE_URL` in `os.environ` shadows the test's temp `.env`. Passes in a fresh clone. Fix touches M1 config/test code — deferred, needs Kanav's call (options: `override=True`, or have the test clear the env var).

---

## 🔑 Critical Constraints (Do Not Forget)

- Defense/feeding scores = **directly measured**, NOT inferred from point output
- Win probabilities = **unbiased** — AI strategy cannot get inflated odds
- Core engine = **no LLM API calls** — ML / stats / optimization only
- LLM allowed only for: natural-language report generation and explanations
- Real-time updates must sync **during an event** as matches are played

---

## 📝 Session Log

| Date | Worked On | What Was Built / Decided | Next Step |
|---|---|---|---|
| 2026-07-23 | Milestone 7 (Sven's first solo milestone) | Local env from scratch (Postgres 18, venv, deps); baseline 102 tests green; M7 built — `0005_canonical.sql` re-key, `CanonicalRepository` upsert loaders, `StagingTeamEventStats`; 113 pass; committed `4086f59`, PR #1 merged to `main` | Milestone 8 |
