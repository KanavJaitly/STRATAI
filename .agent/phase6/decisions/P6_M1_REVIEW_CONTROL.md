# P6-M1 review control: named, qualified human FRC-domain reviewer

**Decided by Kanav, 2026-10-07. Implemented in `fa70e7c` on `phase6/build`.** No ruleset was approved, and no validation ran.

Earlier records that state the previous control are kept unchanged:
- `P6_M1_ENTRY_STATUS.md`;
- `P6_PX1_PRE_RUN_REPORT.md`;
- `../M01_ACCEPTANCE.md`;
- `../PHASE_ACCEPTANCE.md`;
- the research package README;
- the header comment of the already-applied migration `0011_phase6_season_rulesets.sql`.

This record supersedes their reviewer rule. The **commands** for review are in §3 below. They replace the reviewer steps in `P6_M1_ENTRY_STATUS.md`.

## 1. Previous and new control

| | Previous P6-M1 control | New P6-M1 control |
|---|---|---|
| Who may approve | A named reviewer who is **a different person from the author**. `review_ruleset` refused when `created_by == reviewer` | **P6-M1 requires a named, qualified human FRC-domain reviewer who independently verifies the submitted ruleset against authoritative FIRST sources and completes R1–R15. The reviewer may also be the ruleset author when the reviewer satisfies the qualification requirement** |
| What approval required | A reviewer name | A reviewer name, a stated FRC-domain qualification, R1–R15 **each completed**, the **full stored sha256** verified by the reviewer, and stored content that still validates (v3) and still hashes to that sha256. Any one missing: refused (`invalid_input`, `review_incomplete`, `hash_mismatch`, `invalid_stored_ruleset`) |
| What is recorded | `reviewed_by`, `reviewed_at`, free-text `review_note` | `reviewed_by`, `reviewed_at`, and `review_note` as JSON `{reviewer_qualification, checklist (R1–R15), verified_sha256, note}`. The CLI also writes the write-once approval record `P6_M1_APPROVAL_<season>_v<version>.json` |

**"Independently"** means the review is performed against the authoritative sources, not by accepting the author's transcription, Claude's research draft or the entry sheets.

The four things stay distinct:
- **authoritative sources:** FIRST Game Manuals, Team Updates and FIRST event/division pages, plus TBA only where the frozen ruleset requires the TBA mapping;
- **Claude's research draft** (`rulesets_research/`);
- **the submitted ruleset** (stored in serving);
- **the human review.**

**Unchanged:**
- the draft → submit → review → approve/return lifecycle;
- versioning and supersession;
- the v3 schema;
- `approved_ruleset`'s re-validation and sha256 check;
- the validation runner's gate (`require_rulesets`: approved and hash-matching, for 2024–2026).

## 2. Reason

The different-person rule was a project-control choice, not an FRC requirement. What P6-M1 needs is that the stored ruleset is correctly supported by the authoritative FIRST sources, verified by someone qualified in FRC rules.

Claude is a research and engineering assistant with no authority over the historical FRC rules. The project's qualified FRC-domain reviewer is Kanav. As Kanav stated it: a member of his team's strategy team for four years, who has served as head of strategy, including this season.

**This is a change to the review-control definition, not an exception for any person.**

## 3. Reviewer qualification and how to record it

- **The requirement:** a named human with FRC-domain qualification, stated accurately (no claimed credential the reviewer does not hold), and recorded in the approval record.
- **No authentication:** names and qualifications are recorded, not verified (the Phase 5 convention).
- **Wording for Kanav's review**, from his own statement, to be entered by him at review time:

  > FRC strategy team member for four years; head of strategy; current-season strategy lead

  He may restate it in his own words. Nothing is pre-recorded.

**Review command** (per season):
1. Copy `rulesets_entry/review_checklist_template.json` (all `false`).
2. Set each item `true` only when verified.
3. Run:

```
python -m scripts.phase6_rulesets review --id <id> --reviewer "<Full Name>" --approve \
    --qualification "<qualification>" --checklist <checklist.json> --sha256 <full stored sha256>
```

4. Commit the generated `.agent/phase6/decisions/P6_M1_APPROVAL_<season>_v1.json`.

The stored ids and hashes are in `P6_M1_ENTRY_STATUS.md`:

| Season | id | Stored sha256 |
|---|---|---|
| 2024 | 1 | `cdba3add…` |
| 2025 | 2 | `befbbb87…` |
| 2026 | 3 | `24bd006c…` |

## 4. What this does NOT change

**No ruleset or rule content:**
- the historical FRC rules;
- any FIRST source;
- any citation;
- any ruleset value;
- any event exclusion;
- any unresolved/null decision.

The three stored rulesets (ids 1–3) are untouched and still `awaiting_review`, with the same hashes. That was checked read-only on serving after the change.

**No modelling methodology:**
- PX-1 composition, features, objectives, thresholds, train/test populations and model definitions;
- PX-2/PX-4 methodology;
- the M8 criterion;
- the P6-Q decisions;
- D-PX1-1 to 5, C1/C2;
- P6-M10;
- the Phase 4 models;
- **any acceptance criterion**.

**The authoritative-source requirement is unchanged.** The frozen spec (`docs/P6Milestones.md` P6-M1: "named-reviewer approval", "a named reviewer") is satisfied as written and was not edited.

## 5. Files changed (`fa70e7c`)

- `data/rulesets.py`:
  - `review_ruleset` loses the self-approval refusal;
  - it gains `reviewer_qualification`, `checklist` and `verified_sha256`, enforced by `_approval_record`;
  - `REVIEW_CHECKLIST` = R1–R15;
  - the docstring now states the control.
- `scripts/phase6_rulesets.py`: `review` takes `--qualification`, `--checklist`, `--sha256` and `--record-dir`, and writes the write-once approval record.
- `tests/test_phase6_rulesets.py`: tests updated and added (below).
- `.agent/phase6/P6_M1_HUMAN_INPUT_GUIDE.md`: header, U3, §5 header and statement, R1, R15, §6 step 5.
- `.agent/phase6/rulesets_entry/README.md`, `APPROVAL_RECORD_TEMPLATE.md`, and the new `review_checklist_template.json`.
- `docs/phase6.md`, `CLAUDE.md`, `.agent/phase6/PHASE_STATUS.md`: wording of the control.

## 6. Tests

**New or changed in `tests/test_phase6_rulesets.py`** (isolated `stratai_test` only; the permanent DB guard is unchanged):

| Area | Tests |
|---|---|
| Lifecycle | lifecycle with a qualified reviewer, including the refusal of an unsubmitted draft; return to draft; supersession (updated) |
| Who may approve | a qualified reviewer different from the author: allowed; the same as the author: allowed |
| What is recorded | the approval records qualification, checklist and hash |
| Refusals | a missing reviewer identity (2 cases); a missing qualification (3); an incomplete R1–R15 (5: missing item, `false`, none, unknown item, non-boolean); a wrong or short sha256 (4); stored content tampered after submission; stored content with an unresolved `HUMAN_DECISION` marker (and such content can never be drafted) |
| Runner gate | refuses an unapproved ruleset; accepts an approved, hash-matching one; refuses one tampered after approval (`storage_integrity`) |
| CLI | refuses approval without qualification or checklist, and writes the approval record on success |
| Existing | the runner still refuses without approved 2024–2026 rulesets |

**Results:**
- **Targeted** (`test_phase6_rulesets`, `_ruleset_variants`, `_px1_composition`, `_selection`, `_contract`): **103 passed**.
- **Full isolated suite: 2015 passed, 3 skipped** (12.5 min).

## 7. Status

**P6-M1: awaiting human review.** ids 1–3 are `awaiting_review` on serving. Kanav performs R1–R15 and the approvals. M1, PX-1, PX-2, PX-4, M6 (b) and M8 have not run.
