# P6-M1 entry status: 2026-10-06

**Authorized by Kanav (2026-10-06):**
- apply migration 0011 to serving if the guide's checks pass;
- resolve H1 (O1), H2 (the manual's rounds) and H3 (2026 `captain_rule = highest_ranked_available`);
- run the draft and submit workflow.

**Approval is NOT done.** It needs a different named human reviewer. **No validation has run.**

## Migration 0011 on serving (`stratai`): APPLIED

The guide §7 pre-checks all passed:
- serving ended at `0010_phase5_human_inputs.sql`;
- `to_regclass('season_rulesets')` was null;
- `0011_phase6_season_rulesets.sql` was the only pending migration;
- the checkout was `phase6/build`;
- 0 other sessions were connected.

| Item | Value |
|---|---|
| Backup, before applying | `C:/Dev/StratAI-artifacts/backups/stratai_before_0011_20261006T232659Z.dump` (pg_dump `-Fc`, 26,674,804 bytes, sha256 `7fe99105bc96b381dc6f069bdf07f0a198d1732f319a9eeda58ae132736c412d`; `pg_restore --list` reads 18 table-data entries) |
| Applied | `python database/migrate.py`, recorded `0011_phase6_season_rulesets.sql` at 2026-10-06 19:27:10.206 America/New_York |
| Verified | `season_rulesets` exists; `database/verify_db.py` passed. Row counts of all 18 pre-existing tables are unchanged, except `migrations_applied` (10 → 11). Snapshot: `C:/Dev/StratAI-artifacts/backups/stratai_rowcounts_before_0011.json` |

## Rulesets on serving: AWAITING REVIEW (not approved)

| id | Season | Version | Status | Author (`created_by`) | Submitted (America/New_York) | `ruleset_sha256` |
|---|---|---|---|---|---|---|
| 1 | 2024 | v1 | `awaiting_review` | Claude (AI author; entered on Kanav's instruction, 2026-10-06) | 2026-10-06 19:28:56 | `cdba3adde21db30e571a6e7b0e9d4f7ecfce48d48fc927b944a3c6d95092cee2` |
| 2 | 2025 | v1 | `awaiting_review` | same | 2026-10-06 19:28:56 | `befbbb87ca62b766dfc89173d955ed3e52d0b4e810ca352c6d4b294e153e40d5` |
| 3 | 2026 | v1 | `awaiting_review` | same | 2026-10-06 19:28:57 | `24bd006cae59cf5498538ab5ac78c0cf902a789310ce0b4988d93ab3f3a77b6c` |

**Content:**
- Each stored JSON is byte-for-byte the content of `.agent/phase6/rulesets_entry/resolved/ruleset_<season>.json` (`f87af60`): same sha256.
- **Decisions applied:**
  - **H1 = O1:** explicit small-event exclusions, each with its own reason.
  - **H2:** rounds 1–5, finals 6, in every season.
  - **H3:** 2026 `captain_rule = highest_ranked_available`, default and variant. The citation quotes the 2026 §10.6.1 T606 box verbatim; the box itself speaks of teams that "will become captain if not picked", not of "highest-ranked available".
- Nothing else was changed from the entry forms.

**Author-side verification:**
- `resolved/author_verification.json`: 32 checks per season, all pass.
- It compares every field with the research package; re-fetches the 24 FRC Events division pages; checks TBA names, the exclusions, and the official PDFs' sha256.
- **It is the author's check. It is not the review.**

**Authorship is recorded truthfully:**
- Claude entered the values, on Kanav's instruction.
- No person has yet verified them against the manuals. The reviewer's R1–R15 is that human verification.
- Kanav's 2026-10-05 workflow said a person enters the values. His 2026-10-06 instruction to run draft and submit supersedes that for this entry.
- The reviewer must not be the author string above. **Claude does not approve.**

## Reviewer steps (a different named person)

1. For each id, read the **stored** JSON, read-only on serving. Check its sha256 against the table above.

   ```
   SELECT id, season, status, ruleset_sha256, ruleset_json FROM season_rulesets WHERE id IN (1, 2, 3);
   ```
2. Run `P6_M1_HUMAN_INPUT_GUIDE.md` §5 **R1–R15** against the official PDFs. Use `rulesets_entry/entry_<season>.md` for the citations, and `rulesets_research/sources.json` for the PDF hashes.
3. Then either approve or return:

   ```
   python -m scripts.phase6_rulesets review --id <id> --reviewer "<Reviewer Full Name>" --approve
   python -m scripts.phase6_rulesets review --id <id> --reviewer "<Reviewer Full Name>" --return --note "<what to fix>"
   ```

   A returned ruleset goes back to `draft`. A corrected version is a new draft and is submitted again.
4. Complete `rulesets_entry/APPROVAL_RECORD_TEMPLATE.md` as `.agent/phase6/decisions/P6_M1_APPROVAL_<season>.md`, with the full approved sha256. Commit it.

## After all three are approved (not done)

```
python -m scripts.phase5_isolated_db --name stratai_test --replace
export DATABASE_URL=$(python -m scripts.phase5_isolated_db --name stratai_test --print-url-env)
python -c "from scripts.phase6_common import isolated_database; from scripts.phase6_playoff_track import require_rulesets; print({s: r.sha256() for s, r in require_rulesets(isolated_database()).items()})"
```

The last command verifies the gate without running any milestone. It must print the three approved hashes.
