# P6-M13 parity rerun for P6-M10b: plan (prepared 2026-10-10, before any run)

**Status: prepared, not run.**
- This plan governs the rerun only through Kanav's authorization file `decisions/p6_m13_m10b_rerun_authorization.json`, which must name **this file's blob**.
- Any change to this file is a new blob and needs a new authorization.
- The rerun may run only after a **passed** P6-M10b 2027 run. P6-M10 stays `not_validated` and v1 stays served until the §7 guard passes.

**Basis:** frozen spec `P6_M10B_SPEC.md` (blob `d699afaf`) §7, condition 3: a passing P6-M13 parity rerun on v2, "the P6-DM2 procedure unchanged".

**Runner:** `scripts/phase6_m13_parity_audit_m10b.py`. **Record:** write-once `results/p6_m13_parity_audit_m10b.json`. The v1 records (`p6_m13_parity_audit.json`, `p6_m13_parity_audit_rerun1.json`) are not touched.

## 1. Unchanged from the v1 plan

The v1 plan is `P6_M13_AUDIT_PLAN.md`, blob `301a7434`. The runner refuses if that file differs from the blob the v1 rerun recorded.

- **Frame:** `frame_ab1adbf38b43c2f3`. The runner refuses any other content hash.
- **Contexts:** selected by the same code as v1 (`scripts.phase6_m13_parity_audit.select_contexts`):
  - **Ordinary:** 10 EPA-complete 2026 qualification matches with every model input present, drawn with `random.Random(20261007).sample` from the rows sorted by `match_key`.
  - **Full-search (M2):** the first 2 ordinary contexts.
  - **Missing input (M6):** the first match, by `match_key`, that lacks a model input.
  - **Low odds (M7):** the first complete match, by `match_key`, whose baseline odds for a side are below 0.05.
- **Checks:** S1–S3 and M1–M7, unchanged, as `ml/strategy/parity_audit.py` defines them. All 10 must pass on the real engine.
- **Planted defects:** the same 7 names and target checks, each run on the first 3 ordinary contexts plus the missing-input and low-odds contexts (`run_planted`, shared with v1). Each must fail its target check.
- **Budget:** a hard 45 minutes. On overrun, the defects not yet run are recorded as not caught, and the audit does not pass.
- **Pass:** P6-DM2 is met only if every check passes on the real engine and every planted defect is caught by its target check.

A read-only replay on 2026-10-10 confirmed that `select_contexts`, given v1, reproduces the v1 rerun's recorded contexts exactly.

## 2. Adaptations needed for v2, and why

| # | Adaptation | Why |
|---|---|---|
| A1 | **The audited model is v2**, loaded by `ml.strategy.serving.load_v2_model` with the base and calibrator sha256 from the passed outcome record. That identity must equal `p6_m10b_pins.json` and the registry files. The model carries the status it would be served with (`validated`, baseline case). | §7 requires the audited identity to equal the accepted identity. The served path uses the same loader. |
| A2 | **`prediction_season` = the row's season (2026)** on every context. | v2 refuses without it (§2). v1 ignored it. |
| A3 | **The low-odds context is chosen by v2's odds.** The rule is unchanged; the model applying it is the one under audit. | M7 needs a context where the *audited* model's odds are below 0.05. |
| A4 | **v2 analogues of the planted defects** (`PLANTED_DEFECTS_V2`); see §3. | The v1 factories read v1's β and Σ, or impute a source key v2 refuses. |
| A5 | **Preflight, before any check runs:** the runner refuses unless all of these hold. Otherwise the audit would test the wrong thing. | |
| | - v2 scores every ordinary context; | |
| | - v2 refuses the missing-input context; | |
| | - the low-odds side is below 0.05 under v2; | |
| | - the missing-data defect's imputed source key resolves to a season. | |

## 3. Planted defects for v2

| Defect | v1 form | v2 form | Target check |
|---|---|---|---|
| source_dependent_weighting | AI path: β × 1.05 | AI path: base β × 1.05, then the same calibrator | M1 |
| hidden_ai_only_feature | AI path: mean + 0.05 | AI path: base mean + 0.05, then the same calibrator | M1 |
| ai_only_adjustment | p + 0.02 after recommending | unchanged (engine-level) | M1 |
| different_rounding | ceil display | unchanged (engine-level) | M5 |
| different_calibration | AI path: σ × 0.8 | AI path: every calibration factor × 1.25 (v2's calibration is the factor) | M1 |
| different_missing_data_handling | AI imputes absent inputs; source key `"imputed"` | AI imputes absent inputs; source key borrowed from a team in the same context, so v2 can resolve it | M6 |
| ai_probability_inflation | AI floors p at 0.10 | unchanged (engine-level) | M7 |

**Why the missing-data defect changes:** v2 refuses an unresolvable source key (§2). When the team with the absent input has no source key at all, the v1 form imputes `"imputed"`, so the AI path also returns nothing. M6 then passes, and the defect goes uncaught for the wrong reason. A synthetic test demonstrates this, and that the v2 form is caught.

**Scope of that difference:** `TeamFeatures` requires a source key whenever any EPA field is present, and the plan's population requires all six teams to have `epa_total`. So in the plan's real contexts every team has a source key, and the v1 and v2 forms behave identically. The v2 form makes the defect robust for contexts outside that population; it does not change what the planned rerun measures.

## 4. A point for Kanav's attention

The contexts are 2026 rows, and 2026 is v2's calibration season.
- Parity compares the AI and coach paths on identical inputs. It is a property of the code paths, not of predictive accuracy, so in-sample contexts do not bias it.
- Keeping them keeps the P6-DM2 procedure unchanged, as §7 requires.
- Using 2027 contexts instead would change the procedure and would need a new plan.

## 5. The record and serving

**The record holds:**
- the model identity;
- the spec blob, the v1 plan blob and this plan's blob;
- the git blob of every file on the audited code path;
- the frame hash, the contexts and the preflight;
- each check's result and each planted defect's failed checks;
- the authorization's sha256 and the commit.

**Serving:** a passing record alone switches nothing. The §7 guard (`ml.strategy.serving.m10b_serving_decision`) also requires:
- the passed outcome record;
- Kanav's sha-matched confirmation;
- this record's milestone and spec blob;
- its identity equal to the outcome record's.
