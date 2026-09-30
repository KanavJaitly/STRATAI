# STRATAI EPA specification

Status: **specification only (rating-engine milestone 1)**. Nothing described
here is implemented yet. This document is the normative definition the pure
engine will be built and tested against. Where it and any implementation
disagree, this document wins until it is deliberately revised.

## 0. Reference, scope and reproduction levels

**Reproducibility target.** The Statbotics implementation at
`github.com/avgupta456/statbotics`, commit
**`a2cea5553e35693d423400f419bd770cb2143408`** (2026-06-13). All `path:line`
citations below are to that commit. The repository is MIT-licensed
("Copyright (c) 2020 Abhijit Gupta"); this document describes its method and
transcribes its constants and formulas, and any code later derived from it
keeps that notice.

**Published methodology** (the Statbotics EPA blog, dated 2023-01-09, source in
the same repository at `frontend/src/pages/blog/epa/index.tsx`) is recorded as
separate documentation. It disagrees with the code in places (§10). Those
disagreements are preserved, not resolved: **numerical behaviour follows the
code**, and every difference is listed.

**Scope of this milestone.** Seasons **2024, 2025 and 2026** (the seasons in
STRATAI's canonical data). Rules that exist in the reference only for other
seasons (2002-2023) are listed where they touch shared code, so nothing is
silently assumed away, but no adapter for them is specified; the engine must
reject those seasons explicitly.

**Three reproduction levels** — every validation claim must say which one it
makes:

| Level | Claim | Requires |
|---|---|---|
| **A. Algorithmic** | Given the same season inputs *and the same initial ratings*, STRATAI computes what the reference code computes. | This spec + 2024-2026 adapters. Achievable in isolation. |
| **B. Full historical** | STRATAI's 2024-2026 ratings equal the reference's, *including initialization*. | Level A + the prior-season chain (§4.5), which depends on seasons STRATAI does not hold. **Not claimed.** |
| **C. Published agreement** | STRATAI matches values Statbotics actually served. | Level B + identical source data snapshot and event universe as the live service, compared against published outputs. **Not claimed.** |

Until the initialization dependency is resolved, **no 2024-2026 final rating
may be described as an exact Statbotics reproduction.**

Source tags used below: **[CODE]** reference implementation; **[BLOG]**
published methodology; **[TBA]** The Blue Alliance data; **[STRATAI]** a
STRATAI design decision (never silently changes a reference number — see §11).

## 1. Rating vector

For 2016+ a team's rating is a length-18 float vector **[CODE]**
(`backend/src/breakdown.py:210-227`, padded with `"empty"` to 18 at
`backend/src/tba/breakdown.py:7-11`):

| Index | Key | Meaning |
|---|---|---|
| 0 | `no_foul_points` | total EPA (named `total_points` in the API; excludes fouls) |
| 1 | `auto_points` | auto EPA |
| 2 | `teleop_points` | teleop EPA (updated independently — not derived) |
| 3 | `endgame_points` | endgame EPA |
| 4-6 | `rp_1`, `rp_2`, `rp_3` | ranking-point components, stored in logit-like space (§5.1) |
| 7 | `tiebreaker_points` | tiebreaker component |
| 8-17 | `comp_0`..`comp_9` | season-specific components (§6); unused slots are `"empty"` |

Every dimension evolves by the same scalar update with no covariance between
dimensions **[CODE]** (`backend/src/models/epa/math.py:11-24`).

## 2. Season universe and ordering

### 2.1 Events **[CODE]** `backend/src/tba/read_tba.py:86-135`
- Excluded: keys containing `tempclone`; `EVENT_BLACKLIST`
  (`tba/constants.py:122-130`: 2004va, 2005va, 2007ga, 2022zhha, 2024nywz,
  2025mnsp, 2025miwrc); TBA `event_type` 99 or 100 (offseason, preseason)
  unless in `EVENT_TYPE_OVERRIDES` (`constants.py:137-139`: `2026isrtp` →
  district); events whose week is null after the adjustments below.
- Type mapping: 0 regional, 1 district, 2 and 5 district championship, 3
  championship division, 4 **and 6** Einstein. Any other type maps to INVALID
  but is **not dropped**.
- Week: championship events (division, Einstein) are set to **8**
  (`:121-123`); regional/district/DCMP weeks are TBA `week` **+1** except in
  2016 (`:129-135`). So "week 1" in the reference is TBA week 0.

### 2.2 Matches **[CODE]** `read_tba.py:183-293`
- Dropped at ingest (after 2004): an alliance with fewer than 3 distinct
  teams, or any team on both alliances (`:201-205`); `MATCH_BLACKLIST` (empty,
  `constants.py:132`).
- Completed iff both alliance scores are ≥ 0 (`:207-211`); otherwise upcoming
  (predicted, never used to update).
- `elim` = comp level is not `qm`.
- Time: TBA match `time` (**scheduled**, epoch seconds). If null, a synthetic
  time = event start-date epoch (via `time.mktime`, i.e. server-local
  midnight, `read_tba.py:19-20`) plus qm: `+match_number`; ef:
  `+200+10·set+match`; qf: `+300+10·set+match`; sf: `+400+10·set+match`; f:
  `+500+match` (`tba/clean_data.py:32-48`).

### 2.3 Ordering **[CODE]** `backend/src/data/epa/calc.py:34`
All completed and upcoming matches of the season, **across all events**, are
processed in ascending `time` with Python's stable sort. No qual-before-elim
rule. Ties keep insertion order, which the reference does not define
(TBA/DB read order). STRATAI's treatment of ties is §11.

## 3. Year statistics **[CODE]** `backend/src/data/avg.py:9-75`

Computed from the season's **week-1** (TBA week-0) **completed** matches,
pooling red and blue alliance values:

- `score_mean`, `score_sd` of alliance **total score including fouls**
  (`statistics.mean`, sample `statistics.stdev`), each rounded with `r(·,2)`
  (§8); both 0 if fewer than 2 values.
- 2016+: `no_foul_mean` (via the mean/sd helper), and via the mean helper
  (0 if no values): `foul_mean`, `auto_mean`, `teleop_mean`, `endgame_mean`,
  `rp_1..3_mean` (booleans averaged), `tiebreaker_mean`, `comp_0..9_mean`.
- **2025 only** (`:66-73`): `no_foul_mean`, `teleop_mean` and `comp_7_mean`
  each have `3·comp_6_mean` subtracted (processor algae counted at 3, not 6).
- Derived: `foul_rate = foul_mean / (no_foul_mean or 1)`
  (`db/models/year.py:176-177`).

Year statistics are **in-sample for week 1**: week-1 matches are predicted
using means computed from week-1 matches.

## 4. Initialization

### 4.1 Constants **[CODE]** `backend/src/models/epa/constants.py:1-8`
`NORM_MEAN = 1500`, `NORM_SD = 250`, `INIT_PENALTY = 0.2`,
`YEAR_ONE_WEIGHT = 0.7`, `MEAN_REVERSION = 0.4`, `ELIM_WEIGHT = 1/3`;
`EPS = 1e-6` (`backend/src/constants.py:42`).

### 4.2 Starting rating **[CODE]** `backend/src/models/epa/init.py:24-59`
```
INIT_EPA  = NORM_MEAN − INIT_PENALTY·NORM_SD                 (= 1450)
n1, n2    = norm_epa of the two most recent prior TeamYears, else INIT_EPA
prev      = YEAR_ONE_WEIGHT·n1 + (1 − YEAR_ONE_WEIGHT)·n2
curr      = (1 − mr)·prev + mr·INIT_EPA                     (mr = MEAN_REVERSION)
z         = (curr − NORM_MEAN) / NORM_SD
z         = max(−year_mean / num_teams / year_sd, z)        (start EPA ≥ 0)
mean      = year component-mean vector (§3, year.py:179-203)
sd        = mean · (year_sd / year_mean)
2016+:  mean[4..6] = max(−1, inv_unit_sigmoid(clip(mean[4..6], EPS, 1−EPS)))
start     = mean / num_teams + sd · z
```
with `year_mean = no_foul_mean or score_mean or 0`, `year_sd = score_sd or 0`
(`init.py:15-21`; `year_sd/year_mean` uses `year_mean or 1`), `num_teams = 3`
for 2024-2026 (`models/template.py:25`). Note: `sd` is computed **before** the
rp entries are transformed, so the rp `sd` uses the raw rates; and the
`sd·z` term is **not** divided by `num_teams`.

### 4.3 Prior TeamYears **[CODE]** `backend/src/models/epa/main.py:55-65`
Search seasons Y−1 down to Y−4 and take the **first two found** (gaps
skipped; 2021 never exists because that season is never processed,
`backend/src/data/main.py:126-127`). A team with none found (rookie, or
absent four seasons) gets `n1 = n2 = INIT_EPA`, i.e. `z = −0.2`.

### 4.4 Season exceptions and quirks **[CODE]**
- 2026, district `isr`: `mean_reversion = 0` (`main.py:67-70`).
- `epa_start` is recorded as `r(start[0], 2)` (`main.py:77`).
- A team not in the season's TeamYears receives a single **shared** default
  `EPARating` object (`main.py:51-52`); updates to one such team would move all
  of them. Not expected to occur; STRATAI must reject rather than share (§11).

### 4.5 The initialization dependency (why Level B is not claimed)
`n1`, `n2` are prior seasons' **`norm_epa`**, an integer-rounded year-end
statistic (§7.2) of that season's full replay, whose own start depended on the
seasons before it — a chain back to 2002. STRATAI holds 2024-2026 only. The
engine therefore takes prior `norm_epa` values as an **explicit input** (data
contract §4); where they are absent it must say so and apply the reference's
own rookie rule only to genuine rookies, never as a silent stand-in for
missing history. Resolving the chain is a later, separately approved milestone.

**How much the start matters (measured, 2025 real data).** attrib = epa + err/3
and err contains the team's own rating, so a team's rating updates as
epa ← (1 − p/3)·epa + …, not (1 − p)·epa + …. An error in one team's
starting value therefore persists far longer than the step size suggests:
shifting a single team's start by +10 leaves about +4.9 after 6 qualifying
matches, +2.3 after 12, +1.3 after 20 and +0.6 after 30 (teams 118, 1678,
254). A shift applied to every team at once washes out within about 12
matches, since only relative starts affect the error. Without prior history,
teams are therefore mis-ranked relative to one another through roughly their
first one or two events; this is the largest known source of difference from
Statbotics' published 2024-2026 values.

## 5. Per-match procedure **[CODE]** `backend/src/models/template.py:54-99`

For each match in order (§2.3):

### 5.1 Predict **[CODE]** `models/epa/main.py:81-138`
1. Alliance vector = sum of its first 3 teams' rating vectors
   (`:94-99`).
2. `post_process_breakdown` (`models/epa/breakdown.py:8-91`):
   2016+: `rp_i ← unit_sigmoid(rp_i)`, `unit_sigmoid(x) = 1/(1+e^{−4(x−0.5)})`
   (`math.py:37-38`). **2025**: with `pa` = own `processor_algae` and `opa` =
   opponent's: `processor_algae_points += 3·pa`, `net_algae_points += 3·opa`,
   `teleop_points += 3·(pa+opa)`, and index 0 `+= 3·(pa+opa)`. (2018 and 2023
   rules exist; out of scope.)
3. Predicted no-foul score = index 0 of the post-processed vector for 2024,
   2025, 2026 (`breakdown.py:147-150`).
4. Win probability: `P(red) = 1 / (1 + 10^(k·(R − B)/score_sd))`,
   `k = −5/8` for years ≥ 2008 (`main.py:25-27, 125-126`); R, B the no-foul
   predictions (not foul-inflated).
5. Recorded predicted scores = `R·(1+foul_rate)`, `B·(1+foul_rate)`
   (`main.py:128-136`).
6. Pre-match team ratings are recorded (§7.1) **before** any update.

### 5.2 Actual vector **[CODE]** `db/models/match.py:195-211`
float32 array `[no_foul, auto, teleop, endgame, rp1, rp2, rp3, tiebreaker,
comp_0..9]` per alliance, each `value or 0`, booleans as int (§6).

### 5.3 Attribution **[CODE]** `models/epa/main.py:140-165`,
`models/epa/breakdown.py:155-202`
```
my_err  = actual_vec − pred_vec      (pred_vec = post-processed prediction)
opp_err = opp_actual − opp_pred
M       = margin_func(year) = 1 for 2002-2003, else 0     (main.py:29-33)
err     = (my_err − M·opp_err) / (1 + M)
attrib  = epa + err / num_teams                              (per team)
```
- **2025**: `u = 3·err_t[processor_algae]` (with `err_t = err/num_teams`);
  subtract `u` from the per-team error's `processor_algae_points`,
  `teleop_points` and `no_foul_points`; recompute `attrib = epa + err_t`.
- **Elims (2016+)**: `attrib[rp_i] = epa[rp_i]` (ranking-point components
  unchanged in playoff matches).
- Note: rp predictions are probabilities (after the sigmoid) while ratings
  hold logit-like values; the error is added in probability units.

### 5.4 Skip rules **[CODE]** `models/template.py:77-90`
No team is updated when: any team is a placeholder (9970-9999,
`tba/constants.py:115`); or an elim match has an alliance with ≥ 3 DQ'd teams;
or both alliances have `no_foul == 0` and `foul > 0`. Predictions and
pre-match records still happen.

### 5.5 Update **[CODE]** `models/epa/main.py:35-40, 167-172`, `math.py:17-24`
```
N      = the team's count of completed qual matches processed so far this season
base   = min(0.5, max(0.3, 0.5 − (0.2/6)·(N − 6)))
p      = (2/3)·base          (2016+; ½·base for ≤ 2015)
w      = ELIM_WEIGHT if elim else 1
new    = (1 − p)·epa + p·attrib
epa    = w·new + (1 − w)·epa                  ⇒  epa += w·p·err/num_teams
N     += 1 if not elim
```
`p` is 1/3 for N ≤ 6, falling linearly to 0.2 at N ≥ 12. Playoff matches
never advance N. Surrogates are ignored by the model; qual DQs are not
special-cased (only the elim all-DQ skip, §5.4).

## 6. Season component adapters (2024-2026)

Shared **[CODE]** `tba/breakdown.py:823-883`:
- If the alliance breakdown is null, the score is null, or **score == 0**, the
  alliance gets the empty breakdown (every component null → 0 in §5.2).
- `foul_points = foulPoints + adjustPoints`; `no_foul_points = score −
  foul_points` (TBA `adjustPoints` may be negative).
- **Identity enforcement**: residual `no_foul − (auto + teleop + endgame)` is
  added to `teleop_points` (and printed as "ERROR").

Absent TBA fields default to 0 in the reference (`.get(field, 0)`); see §11
for STRATAI's handling.

### 2024 **[CODE]** `tba/breakdown.py:619-693`, names `breakdown.py:127-143`
| Slot | Name | Formula (TBA fields) |
|---|---|---|
| auto | auto_points | `autoLeavePoints + 2·autoAmpNoteCount + 5·autoSpeakerNoteCount` |
| teleop | teleop_points | `teleopAmpNoteCount + 2·(teleopSpeakerNoteCount + teleopSpeakerNoteAmplifiedCount) + 3·teleopSpeakerNoteAmplifiedCount` (endgame **excluded**, unlike TBA `teleopPoints`) |
| endgame | endgame_points | `endGameParkPoints + endGameOnStagePoints + endGameHarmonyPoints + endGameNoteInTrapPoints + endGameSpotLightBonusPoints` |
| rp_1 / rp_2 / rp_3 | melody / ensemble / — | `melodyBonusAchieved`, `ensembleBonusAchieved`, none |
| tiebreaker | tiebreaker_points | `int(coopertitionBonusAchieved)` |
| comp_0..9 | auto_leave_points, auto_note_points, teleop_note_points, speaker_points (auto+teleop speaker points), amplified_notes (**count**), endgame_park/on_stage/harmony/trap/spotlight_points | as named |

### 2025 **[CODE]** `tba/breakdown.py:696-766, 929-936`, names `breakdown.py:145-163`
| Slot | Name | Formula |
|---|---|---|
| auto | auto_points | `autoMobilityPoints + autoCoralPoints` |
| teleop | teleop_points | `teleopCoralPoints + 6·wallAlgaeCount + 4·netAlgaeCount` (all algae in teleop) |
| endgame | endgame_points | `endGameBargePoints` |
| rp_1..3 | auto / coral / barge | `autoBonusAchieved`, `coralBonusAchieved`, `bargeBonusAchieved` |
| tiebreaker | tiebreaker_points | **recomputed**: 1 iff both alliances have `wallAlgaeCount ≥ 2` (TBA `coopertitionCriteriaMet` overwritten) |
| comp_0..9 | auto_coral_points, teleop_coral_points, coral_l1..l4, processor_algae (**count**), processor_algae_points, net_algae_points, barge_points | L2-L4 = auto row count + (teleopReef row count − auto row count); **L1 = autoReef.trough + teleopReef.trough with no auto subtraction** |

### 2026 **[CODE]** `tba/breakdown.py:769-820`, names `breakdown.py:164-179`
| Slot | Name | Formula |
|---|---|---|
| auto | auto_points | `hubScore.autoPoints + autoTowerPoints` |
| teleop | teleop_points | `hubScore.transitionPoints + shift1..4Points` |
| endgame | endgame_points | `hubScore.endgamePoints + endGameTowerPoints` |
| rp_1..3 | energized / supercharged / traversal | `energizedAchieved`, `superchargedAchieved`, `traversalAchieved` |
| tiebreaker | tiebreaker_points | `no_foul_points` (points, not 0/1) |
| comp_0..6 | auto_fuel, auto_tower, transition_fuel, first_shift_fuel (shifts 1+2), second_shift_fuel (shifts 3+4), endgame_fuel, endgame_tower | as named; comp_7..9 unused |

The API's derived `teleop_fuel` (`breakdown.py:192-198`) includes endgame fuel;
the `teleop_points` component does not.

## 7. Outputs and snapshots

### 7.1 Match **[CODE]** `models/epa/main.py:174-257`, `db/models/match.py:243-248`
- `pre_epas[team]`: rating before the match (§5.1 step 6).
- `epas[team]`: rating after the update (first 3 teams per alliance).
- Predictions: `win_prob = r(p,4)`, `pred score = r(·,2)`, rp predictions
  `r(·,4)`; `epa_winner` red iff `p ≥ 0.5`. All pre-match.
- Team values rounded with `np.round(·,2)` (round-half-to-even) for points;
  rp values `round(·,4)` (`ty.rp_3_epa` uses 5 decimals, `main.py:223`).

### 7.2 Season aggregates **[CODE]** `backend/src/data/epa/agg.py`
- **TeamYear** (`:11-22, 65-126`): `epa` = last recorded post-match EPA
  (rounded values); `epa_start`; `epa_pre_champs` = last post-EPA with week
  < 8; `epa_max` = max post-EPA **excluding the first 8 matches**.
- **TeamEvent** (`:157-186`, `calc.py:45-48`): `epa` = post-EPA after the
  team's last processed match at the event, **elims included**; if the team
  has no qual match there, its latest EPA at run time. `stats.start` =
  pre-EPA of its first match there (else the previous event's `epa` or
  `epa_start`); `stats.pre_elim` = **pre**-EPA of its last qual match (excludes
  that match's own update); `stats.mean`/`stats.max` over pre-match EPAs there.
- **Unitless** (`models/epa/unitless.py:11-12`, `agg.py:94,158`):
  `1500 + 250·(epa − score_mean/3)/score_sd` (with-foul `score_mean` against
  a no-foul EPA; always `/3`), rounded `r(·)` to an integer.
- **Norm** (`unitless.py:16-61`, `agg.py:92-98,161`): fit `exponnorm` (scipy
  MLE) to all TeamYear end-of-season EPAs; fit `expon` to the top
  `int(N/10)`; percentile = exponnorm CDF, blended toward the exponential tail
  for the top 10% with weight `min(1, 2·(cutoff−i)/cutoff)` (tail alone in the
  top 5%); map through the **fixed** `exponnorm(1.6, −0.3, 0.2).ppf`, giving
  `1500 + 250·ppf`; evaluated at 101 quantiles and linearly interpolated;
  rounded `r(·)` to an integer. Norm is **year-end and look-ahead**: it is a
  season artifact, never a point-in-time value.

## 8. Numerical conventions **[CODE]**
- In-memory ratings: float64 (NumPy); actuals: float32 (§5.2).
- `r(x, n) = int(x·10ⁿ + 0.5) / 10ⁿ` (`backend/src/utils/utils.py:33-34`):
  rounds half up for positives, but `int()` truncates toward zero, so
  **negatives come out one unit too high about half the time**
  (`r(−1.234, 2) = −1.22`, where correct rounding gives −1.23;
  `r(−1.236, 2) = −1.23`, correct −1.24). Used for year statistics,
  predictions, unitless, norm and `epa_start`.
- `np.round` (half-to-even) for recorded team EPAs; Python `round` for rp.
- No randomness. Norm depends on scipy's MLE (`exponnorm.fit`); the
  reference pins scipy ^1.11.1 and numpy 1.26.4 (`backend/pyproject.toml`), so
  results may differ slightly under other versions.

## 9. Win probability and prediction summary
See §5.1 steps 3-5. Predicted margin is `R − B` (no-foul). `P(red)` is
symmetric: `P(red | R,B) = 1 − P(red | B,R)`.

## 10. Published methodology vs. reference code (preserved, not resolved)

| # | Topic | Published [BLOG] (`frontend/src/pages/blog/epa/index.tsx`) | Reference [CODE] | STRATAI numerical behaviour |
|---|---|---|---|---|
| 1 | Margin | M rises 0→1 over N = 12..36; M = 0 in 2015, 1 in 2018 (`:153-168`) | M = 1 only 2002-2003, else 0 (`main.py:29-33`) | code |
| 2 | Update rate K | 0.5 → 0.3 (`:133-135`) | (2/3)·(0.5→0.3) = 0.333→0.2 for 2016+ (`main.py:35-40`) | code |
| 3 | Teleop | derived as total − auto − endgame (`:187-191`) | its own independently updated component | code |
| 4 | Ranking points | ILS model (`:193-208`) | sigmoid-EPA (`breakdown.py:17-20`) | code |
| 5 | Playoff weight | The EPA sections state **no** playoff weight. The only published ratio is for the predecessor Elo model: "K is set to 12 for qualification matches and 3 for playoff matches" (`:73-74`), i.e. 1/4 | `ELIM_WEIGHT = 1/3` (`constants.py:8`) | code (the published text is silent for EPA, not contradictory) |
| 6 | Norm | target "defined by another exponential normal distribution fit to EPA ratings from all years"; "a separate exponential distribution ... for the top 5%" (`:243-248`) | fixed target `exponnorm(1.6, −0.3, 0.2)`; exponential fit to the top 10%, blended 10%→5% (`unitless.py:16-61`) | code |

Also recorded: the intro blog (`pagesContent/blog/intro/main.tsx:148-150`)
says week-0 statistics seed week 1; no such override exists in `data/avg.py`
at this commit.

## 11. Reference quirks and STRATAI decisions

Each item is either reproduced (so Level A holds) or **deliberately not
reproduced** — the latter is a documented, counted divergence, never a
silent one. The items marked *proposed* at milestone 1 were decided in the
engine-core milestone (`ml/ratings/epa/`); each decision names the test that
pins it. Real-data counts are from a read-only profile of STRATAI's stored
2024-2026 TBA payloads (2026-09-30).

| Reference behaviour | Source | STRATAI treatment |
|---|---|---|
| Completed match with score ≠ 0 but no breakdown → all components 0, ratings pulled toward 0 | `match.py:195-211`, `tba/breakdown.py:830-832` | **Not reproduced** [STRATAI]: excluded and reported (`missing_breakdown`); a divergence from Level A for that match. Real data: 0 cases in 2024-2026. |
| Alliance score == 0 → empty breakdown: components None in season means, 0 in the update; rp False (counted as 0 in rp means) | `tba/breakdown.py:831`, `tba/types.py:52`, `data/avg.py:21` | Reproduced exactly, including the None/False distinction. Real data: 20 / 17 / 49 alliances. |
| The empty breakdown is one module-level dict, returned by reference and written by `post_clean_breakdown` | `tba/types.py:52`, `tba/breakdown.py:830-832, 886-938` | **Decided.** Investigated: within 2025 the only write is `tiebreaker = int(min(red comp_6 or 0, blue comp_6 or 0) >= 2)`, and an empty alliance's comp_6 is unknown (0), so that write is always 0 — deterministic per match, independent of read order. That per-match rule is **reproduced** (decision *a*). The shared state itself persists across seasons in one process: 2018's post-clean writes comp_6..comp_9 and 2025's writes tiebreaker, and `reset_all_years` (`data/main.py:111-134`) processes 2002 → current in one process, so a 2024-2026 empty alliance can carry values left by an earlier season. That depends on the reference process's history, not on the match's data; it is **not reproduced** (decision *b*, a reference-process artifact) — each empty alliance is a fresh immutable value. Every empty alliance is counted as a possible divergence (`shared_empty_breakdown`). It can reach total EPA only in 2025, through the processor-algae revalue in attribution and year statistics. Tests: `test_ratings_epa_adapters.py` (2025 tiebreaker, no shared state, 2026 statistics). Not option *c*: STRATAI's raw payloads are read correctly; the issue is entirely in the reference's in-memory handling. |
| Absent TBA fields default to 0 (`.get(f, 0)`) | `tba/breakdown.py` adapters | **Decided**: a present breakdown missing a required field, or holding a wrongly typed one, is rejected (`malformed_breakdown`), never zero-filled. A field whose value the reference always overwrites (2025 `coopertitionCriteriaMet`) is not required. Real data: every one of 106,304 scored 2024-2026 alliance breakdowns has every required field with the expected type. |
| Equal `time` ordering undefined (stable sort over dict insertion order) | `calc.py:34` | [STRATAI] deterministic tie-break by `match_key`, counted as a possible divergence (`tie_order`) only when a team plays in two matches of the tie group. Real data: ~3,400-3,700 tie groups per season (simultaneous events), of which 1 (2024), 1 (2025), 0 (2026) are order-sensitive. |
| `r()` negative-rounding bug | `utils.py:33-34` | Reproduced where the reference applies `r()` (needed for Level A). |
| float32 actuals, `np.round` half-to-even | `match.py:198-211`, `main.py:175,197` | Reproduced. |
| 2025 trough coral not auto-subtracted | `tba/breakdown.py:721,730` | Reproduced (it is the reference's definition of `coral_l1`). |
| Shared default rating for unknown teams | `main.py:51-52` | Not reproduced: an unknown team is an input error. |
| Norm depends on scipy version | `unitless.py:24-26` | Reproduced with STRATAI's scipy; version recorded in provenance; version sensitivity reported, not hidden. Exact norm parity needs the pinned scipy (^1.11.1, numpy 1.26.4): a validation-environment requirement, not a core-correctness one. |
| Week-1 statistics use every week-1 result, so a week-1 match's own result feeds the scale used to predict it and every other week-1 match | `data/avg.py:10-12` | Reproduced; this is the only way a pre-match rating can depend on a later result. Pinned by `test_ratings_epa_leakage.py`, which also shows the loop itself is causal once the statistics are fixed. |
| A team-event with no counted qual match (all DQ/surrogate, or none played) takes the team's season-end rating | `data/epa/calc.py:45-48`, `data/wins.py:67-81` | Reproduced and flagged: `epa_is_season_end` / provider `lookahead=True`. A consumer needing point-in-time values must not use it. |
| Playoff RP freeze sets attrib = epa, then applies the normal update, so the value can move by one ulp | `breakdown.py:190-200`, `math.py:17-24` | Reproduced as arithmetic, not special-cased (`test_2024_elimination_update_by_hand`). |
| numpy 1.26.4 in the reference; STRATAI runs numpy 2.x | `pyproject` of the reference | `np.exp` / `np.log` implementations can differ in the last ulp across numpy versions. Level A comparisons against a reference run must use the pinned numpy or a stated tolerance. |

STRATAI additionally guarantees: no network access in the engine;
deterministic output for identical inputs; every excluded or skipped match is
reported with a reason (data contract §5).
