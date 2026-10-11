# FINAL-1 (PX-1b 2027 acceptance): readiness checklist

**A living document, not a frozen spec and not a decision record.** It tracks the frozen prerequisites of PX-1b spec §6 and D9 v1 Part B. Each box is ticked only when the named artifact exists and the named check passes.

**Last updated 2026-10-11.** Item 1 is done; items 2–6 and 8–9 are open, and FINAL-1 refuses today.

**Rule:** FINAL-1 runs **once**, through `python -m scripts.phase6_px1b gate2027`. Its record `p6_px1b_gate_2027.json` is write-once, and a second run is refused. **A pass is not acceptance:** item 9 is still required (D9 v1 Part B condition 4).

| # | Prerequisite | Artifact (who produces it) | How the code verifies it (`scripts/phase6_px1b_final1.py`) | Status |
|---|---|---|---|---|
| 1 | **D9 v1 confirmed** | `decisions/p6_d9_v1_confirmation.json` (**Kanav**): `confirmed: true`, `confirmed_by`, `date`, `record: ".agent/phase6/decisions/P6_D9_PX1B_REPLACEMENT_V1.md"`, `record_blob: "147463ecf103e3995d3cb5ccdaf6a289c2495738"` | `check_d9_confirmation`: every field, and the blob must equal the record's current blob | ☑ done: confirmed by Kanav Jaitly, 2026-10-11 (`check_d9_confirmation` accepts it) |
| 2 | **Approved 2027 ruleset** | `season_rulesets` row for 2027, entered from the 2027 manual and approved by a named, qualified reviewer (`scripts/phase6_rulesets.py`; **a person**) | `require_rulesets(database, (2027,))` in `main`; `approved_ruleset(2027)` | ☐ open (needs the 2027 manual) |
| 3 | **Complete, synced 2027 playoff data** | the 2027 season synced into the isolated copy (TBA) | `_playoff_matches(2027) > 0`; completeness is attested in item 6 | ☐ open (2027 season) |
| 4 | **2027 reproduction check, committed** | `results/p6_m1_ruleset_check_2027.json` (`python -m scripts.phase6_playoff_track m1-2027`), then **committed** | present; not escalated; made with item 2's ruleset sha256. Registration ordering: the evidence commit `a52641e` must be a strict ancestor of the commit that added this record | ☐ open |
| 5 | **Pinned 2027 EPA snapshot** | `decisions/p6_px1b_epa_source_2027_config.json` (**Kanav**: `snapshot`, `chain`), then `python -m scripts.phase6_px1b epa-pin-2027`, which writes `results/p6_px1b_epa_source_2027.json` after D18's integrity checks | `verified_epa_source`: the manifest and chain sha256 match; the manifest's seasons include 2027 | ☐ open (needs a 2027 Statbotics snapshot) |
| 6 | **Explicit run authorization** | `decisions/p6_px1b_final1_authorization.json` (**Kanav**): `authorized: true`, `authorized_by`, `date`, `scope: "FINAL-1"`, `season: 2027`, `season_complete_and_synced: true` | `check_authorization` | ☐ open |
| 7 | Frozen candidate and integrity (already in place) | `p6_px1b_final_fit.json`, `p6_px1b_dev.json`, `p6_px1b_chain_pins_v2.json`, `p6_px1b_registration_evidence.json`, M6/M7 `d18` | pins (sha256); training seasons ⊆ 2024–2026; fingerprints agree; registration evidence re-derived from git | ☑ present and verified (2026-10-10); re-verified at run time |
| 8 | Run FINAL-1 | `python -m scripts.phase6_px1b gate2027`, which writes `results/p6_px1b_gate_2027.json` | the prerequisites above; the candidate recorded before the first 2027 selection; the frozen gate | ☐ not run (never before items 1–6) |
| 9 | **Kanav's sha-matched confirmation (after a pass)** | `decisions/p6_px1b_final1_confirmation.json` (**Kanav**): `confirmed: true`, `confirmed_by`, `date`, `record: "p6_px1b_gate_2027.json"`, `record_sha256` | `_require_model(PX1B_TRACK)`, checked by PX-2b, PX-4b and M8b | ☐ open |

**Never acceptable substitutes:**
- 2026 data, HV-1 results, synthetic fixtures;
- a fallback to an unpinned artifact;
- a hand-written FINAL-1 record.

**Downstream, after item 9:** PX-2b, then PX-4b, then M8b. Each refuses until its own prerequisite passes. They also need:
- the 2027 EPA source wired into their track (a separate authorization);
- for M8b, a pre-run record with a mentor whose agreement is confirmed.

See `decisions/P6_PX_CHAIN_STATUS_2026-10-10.md`.
