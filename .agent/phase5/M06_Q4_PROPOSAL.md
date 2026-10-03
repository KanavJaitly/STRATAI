# P5-M6 — Q4 proposal: a seeded, stratified verification population within the 45-minute rule

**Status: PROPOSAL for Kanav's review (2026-10-03). Not adopted, not implemented, not run.**

If approved, it is recorded as a dated decision (P5-D14) in `P5_M0_DECISIONS.md` **before** the sample is drawn or
any recorded check runs.

## 1. The frozen population

P5-M6 (docs/P5Milestones.md, frozen at P5-M0) fixes:
- **The evaluation population:** a replay of six held-out 2026 events — the first five 2026 events by event_key that
  have qualification matches (2026alhu, 2026arc, 2026arli, 2026ausc, 2026azfg), plus 2026iscmp. That is 559
  matches, re-landed chronologically through the production ingestion path into an isolated database.
- **Criteria (a) and (d):** checked "after every completed match".

## 2. Why it conflicts with the permanent 45-minute rule

- **Measured cost:** a clean 2026arli debug run (33-team roster) took 30.1 min for 65 matches.
- **The floor, before any check:**
  - `sync_event` costs about 0.9 s per match;
  - the production watch follow-on (the `team_metrics` recompute) costs about 7 s per match for 33 teams, and
    grows with roster size. It is production behaviour and must not be shortcut.
  - That puts ingestion alone at about 75 min for 559 matches.
- **With checks:** about 4–5 h. 2026arc alone (141 matches, a championship-division roster) exceeds 45 min.
- **Conclusion:** no sampling of the *checks* brings the frozen population under the rule. Only the *population*
  can change, and that is a spec amendment.

## 3. What changes and what does not

**Amended (P5-M6's evaluation population only):** "six events, every match" becomes the seeded, stratified
windows in §4. Matches outside a window are still landed through the same production path, as bulk catch-up syncs;
they are just not individually checked.

**Unchanged:**
- **Criteria (a)–(e)** and their pass conditions.
- **The leakage rule**, the no-retraining rule, and the replay-log contents.
- **The frozen D18 models**, the D18 root snapshot, and the STRATAI chain.
- **The isolated-database rule**: the serving database is read only.

**DM2 (immutable) is unaffected:**
- Its wording ("real mid-season 2026 events are replayed match by match … through the production ingestion path …
  the production serving path shows … P5-M6 criteria a–e") is satisfied by the 2026 windows, which replay real 2026
  matches one at a time.
- DM2 still also needs P5-M6's declared dependency, "P5-M2 adopted".
- The 2025 window (§4, E5) is additional coverage, not part of the DM2 demonstration.

## 4. The sampling procedure, fixed before any selection

- **Seed:** `20261006`, with `random.Random(20261006)`.
- **Draw order:** the strata are drawn in the order E2, E3, E4, E5. Each draw is `rng.choice` over its candidate
  list, sorted by event_key.
- **Inputs:** the serving database's canonical tables and current raw TBA event and match payloads (read-only).
  Their fingerprint (row counts plus the sha256 of the sorted candidate lists) is recorded with the selection.
- **Eligible events:**
  - at least 12 qualification and 2 playoff matches;
  - not one of the five events replayed before Q4 (2026arli is excluded, having served as the debug event);
  - week = TBA's 0-based event `week`.

| Stratum | Purpose | Candidates | Window (consecutive steps) |
|---|---|---|---|
| **E1 (fixed): `2026iscmp`** | EPA fallback path (criterion (e)); a district championship | fixed | 8 qualification steps from a seeded start in [1, n_q − 8], then the first 2 playoff steps |
| **E2: early week** | season start: no prior EPA (`withheld_no_prior_event`); first match of an event | 2026, Regional or District, TBA week 0 | qualification matches 1–8 (from the event's first match), then the first 2 playoff steps |
| **E3: championship division** | the largest rosters; a championship division | 2026, event_type 3 | 5 qualification steps from a seeded start, then the first playoff step |
| **E4: mid-season, P5-M4 switch** | the ordering policy switching mid-window (raw EPA → M5 v2) | 2026, Regional or District, TBA weeks 2–4 | 8 qualification steps centred on the event switch point (4 before, 4 at or after), then the first 2 playoff steps |
| **E5: second season, edge data** | a second season's breakdown adapters and EPA chain; DQ and surrogate rows | 2025, Regional or District, weeks 1–5, with at least 1 qualification match carrying a DQ or surrogate team | 6 qualification steps starting 2 before the first such match (clamped to ≥ 1), then the first 2 playoff steps |

**Within each event:**
- Matches before the window land in **one bulk catch-up sync**, through the same production path, followed by
  the watch follow-on. This is the "watch reconnects after downtime" path.
- The window then steps one match at a time. Matches sharing a scheduled time form one step, as before.
- Before the playoff steps, the remaining qualification matches land in a second bulk sync.
- Qualification matches not yet played are TBA's unplayed placeholders; playoff matches appear only once played.

**Steps:** 10 + 10 + 6 + 10 + 8 = **44 checked steps**. Events are processed in E1–E5 order; each event's windows
are chronological. Events in different seasons or weeks do not interact, because every check is at the step's
as_of.

## 5. Checks per checked step (as in the clean 2026arli run, no criterion changed)

**Per step:**
- (a) Served strength view = assembler `TeamFeatures`, for the step's affected teams plus 2 seeded controls.
- (a) Each affected team's match count rises by exactly 1, traced to the new row's raw payload id.
- (b) The no-op re-poll lands nothing, and its re-request is identical.
- (b) Control teams show no in-event change since their latest served state. EPA changes are counted and must
  coincide with a simulated retrieval or fallback-clock crossing.
- (d) `team_metrics` = a fresh recompute (excluding `computed_at`), for the step's served teams. Every rostered
  team is checked at each window's last step.
- **Candidate EPA rules:** both are still computed and compared at the EPA lookup. Production uses `d18_skip`
  (P5-D11); the comparison is diagnostic.

**Per event:**
- **(e)** E1's EPA-present teams must be served `fallback_stratai`, with source event 2026isde1 or 2026isde2 and
  provenance.
- **Leakage sentinels**, at each window's middle step, on an affected team. Each is inserted, served, compared
  with the baseline, then removed. Any served change fails.
  - a scored match row 1 h after as_of;
  - a scouting observation submitted 1 h after as_of.
- **Endpoints:** event analysis and qualification forecast at the end of E1's and E2's windows. Also at E4's
  window, once before and once after its switch point, which checks the served ordering model changes from
  raw EPA to M5 v2.

**End of run:**
- **(c)** Re-request a seeded sample of 150 logged strength responses, plus every sentinel step's, at their as_of
  on the final database. All must be identical.
- **Optional targeted edge case (recommended), a TBA score correction.** No recorded payload history exists, so
  this one case is synthetic and labelled so.
  - At E2's last qualification step, re-land that match with a corrected score, through the same path.
  - Check that the affected features and `team_metrics` change, traced to the new raw payload.
  - Re-land the original and check they return to their prior values.

## 6. Runtime estimate (from the measured 2026arli costs)

- **Per checked step:** about 13 s + 0.45 s × roster size. That gives about 28 s at 33 teams and about 47 s at 75.

| Part | Estimate |
|---|---|
| Clone, sources (recorded payloads, STRATAI values), model load, initial schedule syncs | ~3 min |
| E1 10 steps (~30 teams) | ~4.5 min |
| E2 10 steps (~35) | ~4.8 min |
| E3 6 steps (~75) | ~4.7 min |
| E4 10 steps (~40) | ~5.2 min |
| E5 8 steps (~40) | ~4.1 min |
| 10 bulk catch-up syncs plus follow-ons | ~1.7 min |
| Endpoints: E1 and E2 at window end; E4 before and after switch | ~6 min |
| (c) re-requests (~160) and the correction case | ~2.5 min |
| **Total** | **~36 min** |

- **Hard budget:** 45 min, enforced by the harness.
- **If the budget is hit**, the run stops and is recorded as **incomplete (a failure)**, never as a partial pass.

## 7. Why the sample still exercises every required behaviour

| Required behaviour | Where |
|---|---|
| Full live-sync path, repeatedly | 44 single-match syncs plus 10 bulk catch-up syncs, each followed by the watch follow-on; 44 no-op re-polls |
| Qualification and playoff matches | every stratum has both |
| Multiple seasons | 2026 (E1–E4) and 2025 (E5) |
| Early-week event / season start | E2 (TBA week 0; teams without prior EPA) |
| Championship / division | E1 (district championship), E3 (championship division) |
| EPA fallback path (e) | E1, 2026iscmp |
| Missing or repeated data | E5's DQ / surrogate rows; E2's withheld EPA; every step's repeat poll; bulk catch-up; the correction case |
| Future-row leakage | 10 targeted sentinels (2 types × 5 events) |
| Per-match equality, increment, stability, metrics recompute, final re-request | every checked step, and (c) at the end |
| Analysis and forecast endpoints, including the policy switch | E1, E2 and E4 |
| Point-in-time across interleaved history | each check at its own as_of; (c) re-requests on the final database |

## 7a. Recording

`p5_m6_replay.json`, write-once, with:
- the population definition (this document's sha256), seed and selection;
- the inclusion and stratification rules;
- the commit;
- the serving-database fingerprint, the D18 root snapshot id and the STRATAI fingerprints;
- the model sha256s;
- per-check counts and every problem.

## 8. What happens after approval

1. Record P5-D14.
2. Implement the selection and windows in `scripts/phase5_m6_replay.py`, with unit tests and no data run.
3. Draw and record the selection, which is committed before any check runs.
4. Run the recorded verification once, within 45 min.
5. Report.
