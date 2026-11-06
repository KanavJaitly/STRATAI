# P11A post-implementation hardening (2026-11-06)

**Instruction.** The project owner's request of 2026-11-06, "P11A — Post-Implementation Hardening and Verification".
- Stage 4 is not begun.
- The spec is unchanged, and no threshold, GameSpec or scoring configuration is approved.
- Nothing unvalidated is enabled.

## H1. The collapse check (investigated; demoted to a non-authoritative screen)

**What it measured.**
- The check was σ̂²/var(y) < 0.05.
- For a random schedule, var(y) ≈ 3τ² + σ², so the ratio is about r²/(3 + r²), where r = σ/τ. It is the residual's
  share of the variance, i.e. a signal-to-noise measure, not a degeneracy measure.
- It fires on every event with r below about 0.4, however well the fit is determined.

**Evidence.**
- Script: `research/p11a_hardening/collapse_check.py`, with its grid and definitions declared in the file before it
  ran, seeded.
- Output: `results/collapse_check.json`. Each of the 20 cells has 60 fits; the run took 49 s.
- **False positives:** at r = 0.2 with 6–10 matches per robot, there were no collapsed fits, the screen flagged 100%,
  and 80% coverage in the flagged fits was 0.77–0.80 (nominal). At r = 0.35 it flagged 60–73% with no collapse.
- **Sensitivity:** at r = 1.0 with 3 matches it was 0.67.
- **The objective alternatives were tested too:** σ̂² on the optimizer bound, and a profile likelihood ratio for
  σ² = 0. Each detected 0–8% of collapsed fits, because collapse shrinks σ̂² without reaching the bound.

**Conclusion.**
- The ratio cannot tell a reliable high-signal fit from a collapsed one.
- No data-only indicator tested detects short-schedule collapse reliably.

**Change (methodology unchanged; the threshold 0.05 is unchanged):**
- The ratio is reported as `collapse_screen` with `status: non_authoritative`, plus the robot label
  `collapse_screen_flagged`. It no longer withholds a plan.
- A plan is withheld (`estimator_fit_unreliable`, robot label `fit_unreliable`) only for a degenerate optimum: σ̂² on
  the optimizer's lower bound. That is the E2 report's §21 safeguard 2.
- Per-component `fit_diagnostics` (σ̂², τ̂², the likelihood ratio for σ² = 0 capped at 100, residual df, and the
  screen) are served with every plan and profile.

**Open, for a properly designed evaluation** (before any threshold is ratified):
- short-schedule collapse remains undetected by data alone;
- E2 safeguard 3 (σ² from earlier same-season events) is the candidate remedy;
- the mitigations in force are the per-robot labels and `not_calibrated` intervals.

## H2. One definition of "pickable now"

- `draft_recommendations.selectable_teams(view, seed, team)` replaces the private `_excluded` import.
- P11-FB1, the P6-M7 engine branch and P11A all use it. Behaviour is identical: the Phase 11 tests are unchanged and
  pass.
- `tests/test_p11a_availability.py` walks seeded random legal drafts under five rule variants and checks the three
  agree at every state.

## H3. Runtime enforcement and the trust root

- **The contract.** The P11A response types moved to `ml/alliance/contract.py`, shared by the API and the offline CLI.
  - `thresholds_status`, comparison `reason`, `prior_kind`, the destination `status` and the collapse-screen `status`
    are now `Literal`.
  - The plan's `scouting` and the whole profile are fully typed: no free-form dictionaries, except `versions`.
- **Found and fixed: approval was self-attested.**
  - A configuration's review is plain JSON whose hash covers only its own content. A hand-edited snapshot could
    therefore embed a fabricated "approved" configuration and produce a usable plan.
  - Now the version-controlled registry (`data/season_scoring/<season>.json`) is the trust root. The snapshot's
    embedded configuration must equal the registered approved one exactly (content and review), and scoring uses
    the registry copy (`scoring_config_not_registered` otherwise).
- **Found and fixed: identical-lineup comparisons.**
  - When two adjacent first picks share the same best lineup, the comparison had reported floating-point noise as
    `p_delta_positive`, and it was nondeterministic.
  - It is now `reason: same_lineup`, with `p_delta_positive: null`.
- **Found and fixed: scouting leakage in the snapshot.** `team_metrics` is a current-state table, so a scouting
  summary computed after `as_of` is now left out and recorded in the snapshot's exclusions, as rankings already were.

## Contract relock

- **What changes:** the two P11A operations, added the same day and never released. Their schemas change as above,
  and the schema names `CodeMessage` and `ExcludedOut` become `P11ACodeMessage` and `P11ATeamReason` inside them.
- **What does not:** no other locked operation changes.
