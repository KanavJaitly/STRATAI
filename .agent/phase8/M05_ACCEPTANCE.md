# P8-M5 — Alliance selection view: acceptance record

status: CONDITIONALLY ACCEPTED on local evidence (2026-10-19); refusal-only live (`not_approved`, P6-DM1); NO successful alliance-selection result
date: 2026-10-18 (agent record); updated 2026-10-19: conditional acceptance as directed by Sven Morais (confirmed by Sven Morais on 2026-10-19; PHASE_ACCEPTANCE.md §7); audited 2026-10-19 (final audit)
branch: phase8/build, uncommitted

| Verification state | Result |
|---|---|
| Implemented | yes |
| Tested with fixtures (synthetic) | `AlliancePage.test.tsx` 4 (the success rendering uses a fixture **labelled synthetic**) |
| Verified against the local API (`stratai_test`, `EPA_SOURCE=statbotics`) | page `alliance` OK: candidates 200 (3.74 s), the pick list returns 409 `not_approved` (declared), synergy 200 |
| Verified in the environment of record | BLOCKED (P7-Q5): no pinned models or serving data here |
| Accepted | CONDITIONALLY: directed by Sven Morais and **confirmed by him on 2026-10-19** (PHASE_ACCEPTANCE.md §7) |

## Acceptance criteria
- **The refusal-only state is clear and truthful.** MET. `not_approved` is shown with its explanation, and nothing is presented as a recommendation.
- **The success rendering is tested with a synthetic fixture.** MET: `PickListView` is covered, including the reach-finals labels, alternatives and provenance.
- **`validated_playoff_success` is shown as served,** and never as `validated_playoff` (asserted).
- **Synergy:** the result shows its teams and `as_of`, and resets when the teams or moment change (R3-2).
