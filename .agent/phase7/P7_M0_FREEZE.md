# P7-M0 — Phase 7 specification freeze

**FROZEN / APPROVED by Sven Morais, 2026-10-17.** Sven confirmed in writing that he has the same decision-making
authority as Kanav for this approval. The governance check is in `P7_M0_DECISIONS.md`.

The freeze is defined by content. `git hash-object <file>` must equal the blob below. Committing this record waits
for Sven's authorization and does not change the freeze.

From here on, contracts and acceptance criteria change only by a new, dated decision row in `P7_M0_DECISIONS.md`
made **before the affected result exists**. A change made after seeing a result is never permitted.

**P7-M0 contains zero Phase 7 implementation.** When the freeze was recorded, no P7-M1 … P7-M9 code, endpoint,
test or migration existed; `git status` showed only these documents.

## Frozen documents (git blob hashes at the freeze)

| File | Blob |
|---|---|
| `docs/P7Milestones.md` (revision 2) | `61de504604b8553988810bdb10e10534e7718deb` |
| `.agent/phase7/P7_M0_DECISIONS.md` (P7-A1, A3 … A9 approved; P7-Q1 … Q13 decided; R1 … R19) | `548c28c643aa278e91e70fa40201a29a09204411` |

## Sources at the freeze (unchanged by it)

| File | Blob |
|---|---|
| `docs/ROADMAP.md` (source of P7-DM1 / P7-DM2; also pinned by P6-M0) | `d7517b09f62056ec3155047c0efac31fb1640896` |
| `docs/P6Milestones.md` (frozen P6-M0 revision 2) | `4b34b5346261a60bc3a7488b658089d1a7529e0b` |
| `.agent/phase6/P6_M0_DECISIONS.md` (as frozen at P6-M0) | `47fce8b3f64ec168c5582d2e5240125b7ac36630` |
| `prompts/MASTER_BUILD.md` | `0fc8716314f03b3e93ce17e531d83361aa1a309c` |
| `.agent/phase6/decisions/P6_PHASE_ACCEPTANCE_2026-10-17.md` | `432991d139c9db4573be487ff88ef0877e5eb961` |

Repository base: `main` at `4290a3d`. Branch: `phase7/m0-spec`.

## Review trail

- Revision 1 draft: adversarial review against the code (18 findings, applied).
- Revision 2 (approved decisions): full review (findings → R1–R12) and confirmation review (findings → R13–R19),
  all applied before this freeze.
