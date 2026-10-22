# FINAL-1 registration-timestamp hardening: audit (2026-10-10)

## The concern

FINAL-1's frozen-first check read `px1b-v1`'s registry manifest `created_at` (`P6_PX1B_FINAL1_IMPLEMENTATION_AUDIT_2026-10-09.md`, observation 1). That timestamp was not pinned, so it could be edited undetected.

## The fix (`277f938`)

The frozen-first decision now rests on **git-backed, tamper-evident evidence**. The registry's own timestamp alone is never trusted.

**1. A write-once registration record.** `results/p6_px1b_registration_evidence.json` was created by `python -m scripts.phase6_px1b registration-evidence`, with provenance `277f938`, before any 2027 data. Per candidate it records:

| Model | File sha256 | Manifest sha256 | Manifest `created_at` |
|---|---|---|---|
| `playoff_px1b/px1b-v1` | `70d448e2…` | `46af8ace…` | `2026-10-09T01:08:51.645865Z` |
| `playoff_px1b_seed_only/px1b-v1` | `99478f02…` | `34f45973…` | `2026-10-09T01:08:51.645865Z` |

It also names the **evidence commit** `a52641e8cdbb99583919ecd28454fe49c7aa1ad9`, committed 2026-10-08T22:17:47−04:00. That is the commit that first added `p6_px1b_chain_pins.json`, the first record holding both candidates' exact file sha256.

**2. `verify_registration`.** Run by FINAL-1, it re-derives everything from git and the files:
- **the commit:** it exists and is in HEAD's history; its committer time, read from git, equals the record's;
- **the hashes:** the pin file at that commit holds the exact model hashes, and they equal the record and pins v2;
- **the manifests:** each still hashes to the record (so `created_at` cannot be edited undetected), and each `created_at` is no later than the evidence commit;
- **date-independent ordering:** the C0 2027 record (`p6_m1_ruleset_check_2027.json`) must be **committed**, and the evidence commit must be its **strict ancestor**. That proves through the hash chain that the candidate's exact bytes were recorded before any 2027 result was.

**3. `require_candidate_frozen_first`** uses the verified evidence-commit time, against the first 2027 selection moment.

**Refusal rules:**
- A missing record is a listed prerequisite.
- Anything altered or inconsistent is refused at once.

## Tests

**`tests/test_phase6_final1.py`: 51 passed** (14 new). They use synthetic temporary git repositories with controlled commit dates:
- **valid evidence passes**, including the builder's round trip;
- **a missing record** is refused;
- **an altered record** is refused: a model sha, the commit, the commit time, a missing entry, the evidence path, or a manifest sha;
- **bad evidence** is refused: a fake commit; a commit off HEAD's history; evidence without the exact hashes;
- **manifest problems** are refused: an edited manifest, including one backdated to 2020 (the registry timestamp alone is never trusted), or a manifest newer than its evidence;
- **2027-ordering problems** are refused: an uncommitted C0 record, or evidence recorded after it;
- **the builder** refuses a model file that differs from the evidence, and refuses once 2027 data exists.

**Full PX harness batch (12 files): 221 passed, 0 failed, 0 skipped (74 s).**

## Read-only audit of the real state

- **Verifying the real record** passes every check up to the last, which refuses because the C0 2027 record does not exist yet (expected): the commit exists and is in history; the git time equals the record; both hashes equal pins v2 and the commit's pin file; both manifests hash to the record; `created_at` ≤ the commit.
- **`gate2027`** refuses at the missing 2027 ruleset.
- **The prerequisite check** now names six missing items, and the registration evidence is no longer one of them: the D9 v1 confirmation, the FINAL-1 authorization, the 2027 ruleset, the C0 2027 record, 2027 playoff data, and the pinned 2027 EPA source.
- **Unchanged:** no registry entry was added or modified; the four pinned model files are unchanged; every earlier PX record and frozen spec still has exactly one commit; the serving database was never touched; no acceptance record exists.

## Remaining limitation (stated, not hidden)

**Committer times are asserted by whoever commits.** A commit made later with a backdated time cannot be told apart from a genuine one by local git alone.

**Why this is mitigated:**
- **Ordering:** the strict-ancestor check against the committed C0 2027 record proves order without relying on any date.
- **Training data:** the final-fit record proves the candidate's training seasons are 2024–2026 only.

**Full wall-clock independence** would need an external witness, such as a server-side push record or an RFC 3161 timestamp of the evidence commit. Both are outside this session's constraints (no push).
