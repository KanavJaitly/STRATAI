# P6-M1 approval record: <SEASON> (copy to `.agent/phase6/decisions/P6_M1_APPROVAL_<SEASON>.md`)

**Completed by the reviewer** after `scripts.phase6_rulesets review --approve`. Facts only.

| Item | Value |
|---|---|
| Season | |
| Ruleset id / version (`season_rulesets.id`, `.version`) | |
| **Approved `ruleset_sha256` (full 64 hex)** | |
| Schema version | `p6-ruleset-v3` |
| Author (`created_by`) | |
| Reviewer (`reviewed_by`): a different person | |
| Approved at (`reviewed_at`, UTC) | |
| Database | serving `stratai` (migration 0011 applied on: ____) |

**Reading the hash, read-only.** `python -m scripts.phase6_rulesets list --season <SEASON>` shows only a 12-character prefix. For the full value, use a read-only SQL session on serving:

```
SELECT id, season, version, status, created_by, reviewed_by, reviewed_at, ruleset_sha256
FROM season_rulesets WHERE season = <SEASON> AND status = 'approved';
```

## Decisions applied in this ruleset (dated)

| Decision | Choice | Reason / source | Decided by, date |
|---|---|---|---|
| H1 small events | O1 / O2 | | |
| H2 round convention | | | |
| H3 2026 captain rule (2026 only) | (a) / (b) | | |

## Reviewer checklist result (`P6_M1_HUMAN_INPUT_GUIDE.md` §5)

Tick each item and note any exception: R1 … R15.

## Exceptions or notes

-
