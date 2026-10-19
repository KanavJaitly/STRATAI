# P8-Q6 — Pre-match report completeness: decision brief (2026-10-19)

> **Decided 2026-10-19: Option C now, then D.** See `P8_Q6_DECISION_2026-10-19.md`. This brief is kept unchanged
> below as the options record.

**Status: OPEN, a human decision for Sven Morais or Kanav. P8-DM2 stays NOT MET until it is resolved and the
completeness criterion is actually satisfied.** This brief does not decide anything, and it does not treat a
labelled absence as a completed field.

## 1. The binding wording

**`docs/ROADMAP.md`, Phase 8 (immutable):**
> Build the shareable pre-match report view containing exactly: our alliance (role, expected scoring contribution,
> strengths/weaknesses per robot), opposing alliance (roles, contributions, defensive threats, key risks), and match
> forecast (predicted flow, critical matchups, key success factors, win probability).
>
> Done means: every view runs off the real API endpoints, and the pre-match report is complete and shareable with an
> alliance partner as-is.

**`docs/P8Milestones.md`, P8-M6 acceptance (frozen):** "Every field traces to the report response, and every absent
part shows its `absent_code`. Nothing is derived client-side. P8-DM2's 'complete' is evaluated honestly (P8-Q6)."

**P7-Q12 (frozen, Phase 7):** "Report items no engine produces … are present as `null` with `reason:
not_produced_by_any_engine` and documented semantics … Derivation rules may be added later only by a dated
decision."

## 2. The six unsupported fields

These are served by `GET /matches/{m}/pre-match-report` → `not_produced.*`. They are always `null` today, and their
semantics are defined in `ml/views/pre_match_report.py:42-49`.

| # | Report section (roadmap) | API field | Served semantics | Shown in the dashboard as |
|---|---|---|---|---|
| 1 | Our alliance: "strengths/weaknesses per robot" | `not_produced.strengths_and_weaknesses` | "Per-team labels of what a team does well or poorly relative to the field." | "not produced by any engine" + semantics |
| 2 | Opposing alliance: "defensive threats" | `not_produced.defensive_threats` | "Opposing robots likely to play effective defense against this alliance." | same |
| 3 | Opposing alliance: "key risks" | `not_produced.key_risks` | "Events that would most reduce this alliance's chance of winning (e.g. a mechanism failure)." | same |
| 4 | Match forecast: "predicted flow" | `not_produced.predicted_flow` | "The expected sequence of the match by phase (auto, teleop, endgame)." | same |
| 5 | Match forecast: "critical matchups" | `not_produced.critical_matchups` | "Robot-versus-robot interactions that most influence the outcome." | same |
| 6 | Match forecast: "key success factors" | `not_produced.key_success_factors` | "The conditions under which this alliance wins." | same |

**The other report items are served:**
- role: from the engine's recommended strategy, or its labelled baseline;
- expected scoring contribution: EPA by phase, with n;
- the opponents' roles and contributions;
- win probability: M6/M7, with its validation status.

In this environment the model-backed items (roles, win probability) appear only as `model_not_loaded`.

## 3. Constraints that bound any resolution

- **Engine, not LLM** (CLAUDE.md critical constraints). The core engine makes no LLM calls. Phase 9's LLM layer may
  only format the engines' structured outputs, so it cannot supply these six items.
- **No fabrication** (the Phase 8 mandate). The client may not derive values, and labelled absences do not make the
  report "complete".
- **Contract.** A new served field is a Phase 7 contract change: additive fields, a relock, contract tests, and docs
  under the lock procedure.
- **Validation honesty.** Anything built on the strategy engine inherits `not_validated` (P6-M10 failed its gate).
  Defense ratings come from scouting only, the defense metric's definition is still an open product decision
  (Phase 3 M14), and no inter-scout agreement exists yet.

## 4. Options

| Option | What it means | DM2 outcome | Cost and risk |
|---|---|---|---|
| **A. Accept the explicit absences** as satisfying "complete" | A human waiver or reinterpretation of the roadmap's "complete" | Waived, not met. It must be recorded as a waiver, not as completion | No work. But the report sent to an alliance partner lacks half the roadmap's forecast content |
| **B. Commission derivation rules for all six** | A dated decision per field, then backend engine work with tests and validation labels, a contract relock, then dashboard rendering | Could become met, once all six are served and verified | Highest. Two fields have no defensible basis today (see D) |
| **C. Defer DM2** to a later phase (or Phase 10) and accept Phase 8 conditionally without it | Keep the absences; DM2 stays unmet and is tracked, as with P6-DM1 and P7-DM1 | Not met (deferred) | Low now. The gap stays visible |
| **D. Staged derivation** (C now, then B for the fields with a defensible deterministic basis) | Derive what existing engines support; keep the rest absent until a model exists | Not met until the last field is served, or until a human decides to waive the remainder | Medium, and incremental |

**For option D, the candidate bases** (each still needs its own dated decision; none is implemented):

| Field | A deterministic basis already in the engines | What it would still need |
|---|---|---|
| 4 predicted flow | EPA by phase for each alliance (already served per robot), summed into expected points by phase | Low: a rule and its label ("descriptive", from EPA) |
| 1 strengths and weaknesses | Field-relative percentiles of the served EPA components and of defense and feeding, with n | Thresholds and minimum n; defense depends on the open definition |
| 3 key risks / 6 key success factors | Strategy-engine sensitivity: the change in odds when a robot or component is unavailable (the coach-observation mechanism exists) | Served `not_validated` (P6-M10). Compute cost per report |
| 2 defensive threats | Opponents' scouting defense ratings | The Phase 3 M14 defense-definition decision; scout agreement is unmeasured |
| 5 critical matchups | None: no model of robot-versus-robot interaction exists | A new model and its validation |

## 5. Recommendation

**Choose C now, then D as a separately approved backend workstream. Do not choose A.**
- Accept Phase 8 conditionally with **P8-DM2 recorded as NOT MET (deferred)**, as Phase 6 and Phase 7 deferred
  their unmet done-means.
- Open one dated decision for **predicted flow** first (the lowest risk, built from served EPA), then strengths and
  weaknesses, then key risks and key success factors (labelled `not_validated`).
- Leave **defensive threats** blocked on the defense-definition decision, and **critical matchups** blocked on a
  model.
- DM2 becomes "met" only when all six fields are served by an engine and verified, or when you explicitly waive the
  remainder in a dated record.

**Why not A:** calling labelled absences "complete" would misstate what an alliance partner receives, and the
mandate forbids presenting the six items as complete.

**Decision requested from Sven Morais or Kanav:**
1. choose A, B, C or D;
2. under B or D, authorize the first derivation decision(s) and the contract change process.
