# P7-D5 — Alliance selection corrections before P7-M6 acceptance (2026-10-18)

**Status:** implementation decision recorded by Claude Code during P7-M6. It was made after the P7-M6 independent
review and before acceptance, before any example was captured and before any client used these routes. Items 1 and
5 change locked entries: item 1 makes the status a constant, and item 5 adds fields and drops a code. The others
change only behaviour behind already-declared refusal codes, plus one Phase 6 engine fix (item 7).

**1. The playoff label states its scope. Its name follows the frozen P7 spec, and the naming conflict is OPEN for a
human decision.**
- The frozen P7-M6 spec says `probability_status` is `"validated_playoff"`, "exactly as
  `scripts/phase6_playoff_track.py` sets it". The script does set that (line 542), and R17 follows it.
- The frozen P6 spec uses `validated_playoff` for PX-2 playoff *match* probabilities (P6Milestones line 189). For
  event-level values it uses `validated_playoff_success` instead: "Pass: `validated_playoff_success`, scope stated"
  (line 228), and "`validated_playoff_success` only if P6-M5 passed" (line 269).
- The two frozen specs disagree on the name. Changing a frozen P7 spec item is not a routine implementation detail,
  so the served label stays `validated_playoff` (`Literal["validated_playoff"]`). The open question is recorded for
  Sven/Kanav: should the pick list serve `validated_playoff_success`, with a relock?
- No harm today: the label is reachable only after an approved ruleset and passed PX gates, so it is never served
  now. The question must be settled before frontend work locks it (P7-DM2).
- What both specs agree on is applied: the scope is stated. Every displayed P(win event) / P(reach finals)
  carries `validation.reasons`:
  - `px4_scope`: validated on actual alliances (P6-M5);
  - `predicted_field_not_validated`: the other alliances come from the P6-Q6 draft model, and P6-DM1 is not met.

  Its `validation.evidence` is the PX-4 record.
- (An earlier draft of this decision switched the label to `validated_playoff_success`. That was reverted before
  acceptance, because it overrode the frozen P7 spec.)

**2. The served PX artifacts must be the evaluated ones.** The loader refuses a PX-1 file whose `model_type` is not
`playoff_px1`, which keeps the seed-only baseline out. Malformed files are logged and served as `model_not_loaded`,
never as a 500. The pick list also requires each pinned sha256 to appear in its gate record (PX-1 or PX-2) or in the
PX-4 record; otherwise it refuses with `playoff_models_not_accepted`.
- **Known consequence:** the current P6 track script (`scripts/phase6_playoff_track.py`) writes no artifact hash into
  those records, and it keeps the PX-2 calibrator only in its rows cache.
- So even if the PX gates were later passed by that script unchanged, the pick list would keep refusing until a
  record (or a later decision) binds the hashes.
- This is deliberate: a passed gate must never vouch for a different file.

**3. "Qualification finished" and "final ranks" are checked, not assumed.**
- Selection needs every scheduled qualification match (with a roster) to be scored, as well as the moment to have
  passed.
- The ranks must come from a ranking payload fetched no earlier than the last scheduled qualification match, and
  must cover every qualification-roster team. Anything else is `rankings_unavailable`.
- Every ranked team must have features at the selection moment, or the result is `playoff_inputs_insufficient`.

**4. The selection pool is the qualification roster.** Candidates and the configuration check use teams in a
scheduled qualification match: the rule of `ml.playoffs.data.QUALIFICATION_SQL`. A team that appears only in a
playoff row is `team_not_found`. P6-M8's `run_m8` used every team with features. For historical events with full
rosters the two coincide, and serving takes the stricter pool.

**5. Responses gain these fields:**
- `vs_next_reach_finals_label`;
- `models.ranking_model_sha256`, null when the ordering is raw EPA;
- `provenance`: the ruleset sha256, its variant and the ordering policy.

`event_rules_required` is removed from the declared 409 codes, because the service always passes one event's
rules.

**6. Draft state and ruleset storage refuse instead of crashing.**
- An inconsistent draft state is `invalid_state`. That covers:
  - an unknown team, or a team both declined and on an alliance where the event's rules forbid it. A declined
    captain is allowed only when `declined_team_may_become_captain` is true; a null rule is `not_established`. A
    declined pick is allowed only when `declined_team_may_be_picked_later` is true;
  - `turns_taken` beyond the draft;
  - an alliance size that does not match its turns;
  - a captain listed before its seed's turn. Only the acting seed may already hold its captain, and only the one
    the captain rule gives. Listing every captain up front would wrongly remove them from the pick pool.
- A team listed twice across the alliances is rejected earlier by the request body (422 `validation_error`).
- A stored, approved ruleset that fails its schema is `storage_integrity`.
- A missing `season_rulesets` table is `not_approved`.
- The gate reader passes only a JSON object whose `passed` is the JSON `true`.

**7. One Phase 6 engine change (`ml/playoffs/selection.py`).** `SelectionEngine._finish` asserted that the
optimizing seed always has an option. One declined team can leave none on that seed's last turn, which was an
AssertionError (a 500). It now raises `RulesetError("infeasible")`, the refusal `run_draft` already uses for the
other seeds. `recommend` also refuses `infeasible` instead of returning an empty ranking. No feasible draft is
affected, so no P6 record or result changes.

**8. Rank freshness is measured against results as well as the schedule.** The ranking payload must also be fetched
no earlier than the latest current TBA match payload of the event's qualification matches. An event running late
can otherwise pass the scheduled-time check with ranks missing its last results. When no match payload exists
(synthetic tests), only the scheduled-time check applies.

**Supersedes:** the `event_rules_required` code in P7-Q1 and R17 of `P7_M0_DECISIONS.md` (the label is unchanged;
item 1). That file is blob-pinned by the freeze, so it is not edited.

**Considered, not changed:** binding the hashes to named record fields instead of record text. The P6 records
define no such field yet, so a field name would be invented. The text match is lowercase hex as written, and the
loader already refuses a non-`playoff_px1` file. Revisit when a P6 record gains artifact-hash fields.
