# P9-M4 — Briefing API: acceptance record

status: ACCEPTED on local evidence (2026-10-20)

| Verification state | Result |
|---|---|
| Implemented | `api/routes/briefing.py`, `api/app.py` (optional router: the app builds without `briefing`) |
| Tested (`stratai_test`, synthetic event with stub models) | `tests/test_phase9_briefing_api.py`: 8 passed. Deterministic by default; enabled without approval never calls the LLM; a faithful arrangement is served with usage, every statement once; an unfaithful one falls back; refusals equal the report route's (`match_not_found`, `match_not_scheduled`, `invalid_as_of`); **the report is identical with the LLM layer off, enabled and called, and off again** |
| Contract | `lock` added `GET /matches/{match_key}/briefing` (25 operations, 0 changed leaves); `check` exit 0. Contract, docs-contract and frontend-contract tests: 448 passed with the P9 unit tests. Types regenerated (`--check` exit 0) |
| Accepted | YES |
