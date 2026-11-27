# Alliance optimizer foundation (audit 2026-11-26, workstream 7)

**Status: foundation only. Not active, not validated, not served.** Nothing in the API, the live draft
(`/alliance-selection/live`) or its fallback rules (P11-FB1, P11-FB2) uses it, and a test enforces that
(`tests/test_alliance_optimizer_foundation.py`). No season has an approved scoring configuration. The live draft keeps
recommending exactly as before: the P6-M7 engine where it serves, else P11-FB2 (`not_validated`).

This is the architecture a real optimizer needs, tested on synthetic fixtures. Calling it an optimizer of real
alliances would be premature until a season's configuration is approved and the method is evaluated on that season's
data with a pre-registered protocol.

Code: `ml/alliance/optimizer/`.

| Module | What it does |
|---|---|
| `config.py` | `SeasonScoringConfig`: every season-specific value, with its approval record. Unapproved configurations are refused unless a test or research run passes `allow_unapproved=True`. |
| `evaluator.py` | `evaluate_lineup`: what a lineup is worth, with robot interactions (caps, best-k, bonuses, roles). |
| `backup.py` | `roster_value`, `backup_value`: value over every pattern of robot availability, so what a fourth robot adds. |
| `search.py` | `rank_first_picks` (conditional on the second pick it leads to), `rank_second_picks`, `rank_backup_picks`. |

## 1. How it accounts for robots working together

An alliance's value is not the sum of its robots' values:
- **`capped` component:** the alliance total saturates at `cap` (a shared resource), so two robots that score the
  same thing add less than their sum. With variances, the expectation is `E[min(S, cap)]` under a normal model.
- **`best_k` component:** only the k best robots count (only k can use a location or action at once), so a third
  robot good only at it adds nothing. Robots are ordered by expected contribution; with uncertainty, this is an
  approximation.
- **Bonuses:** a fixed value when a component's alliance total reaches a threshold. Expected bonus =
  value × P(total ≥ threshold) under a normal model. A robot that tips the alliance over is worth more to it.
- **Roles** (for example defense): a robot can play a role instead of scoring normally, contributing its role-mode
  values plus any measured role value. Roles are assigned to maximise the alliance's value, at most
  `max_per_alliance` robots per role.

**The second pick depends on the first.** A first-pick candidate c is valued by the alliance it can expect to
complete. Partners d are sorted by V(captain, c, d), and each is weighted by the probability it is still available
at the alliance's next pick and that every better partner is gone:

    E[c] = Σ_k V(captain, c, d_k) · p_k · Π_{j<k} (1 − p_j)  +  Π_j (1 − p_j) · V(captain, c)

Availabilities are assumed independent. Once the first pick is made, the second pick is ranked exactly by
V(captain, first, d).

**The fourth robot.** Three robots play. Each robot is available for a match with probability `availability`,
independently. For every availability pattern (16 for four robots):
- with lineup choice, the best three available robots play;
- without it, starters play, and a backup substitutes in order;
- with fewer than three available, the short-handed policy applies.

A backup's value is the roster value with it minus the value without it.

## 2. Values a season needs approved before it may run on real data

The game manual gives the rules; the rest are estimates or modelling choices. **Nothing below has a value yet.** Each
needs a source (a game-manual section, or the measurement and its evaluation) and an owner's approval, recorded in
the configuration's `approval.sources`.

**From the game manual (season rules):**
1. The scoring components that robots contribute to, and each one's point values (as used by the per-robot
   estimates).
2. Each component's interaction rule: `additive`, `capped` (and its cap), or `best_k` (and k).
3. Bonuses and ranking points: which component, the threshold, and the value of reaching it in a playoff context.
   (Ranking points do not exist in playoffs; what a playoff bonus is worth must be decided.)
4. Roles that exist as distinct jobs, and any limit on robots per role (for example zone or protection rules).
5. Alliance shape: active robots (3), roster size (is there a fourth pick at this event type?), whether the alliance
   chooses its lineup each match, and what happens when fewer robots can play.

**Estimates (from data, each needing its own evaluation):**
6. Per-robot component contributions and variances. The candidate source is the P11A A3 estimator, whose estimates
   are `not_validated` and whose intervals are `not_calibrated`.
7. Role-mode contributions and role values. For defense, these must be **directly measured** (scouting), never
   inferred from scoring (CLAUDE.md, critical constraints).
8. Each robot's availability probability. There is no estimator yet; Phase 3 reliability is a candidate input, not
   a probability.
9. The probability each team is still available at the alliance's next pick (a model of other captains). Only
   placeholders exist: `EveryoneAvailable` (an optimistic bound) and `GivenProbabilities` (caller-supplied).

**Modelling choices:**
10. The objective: expected alliance points (implemented) or playoff win probability (which needs opponents and a
    validated playoff model; PX-1 failed its gate).
11. The independence assumptions (robot availability; partner availability).
12. Normal approximations for capped components and bonuses, and mean-ordering for `best_k` under uncertainty.

## 3. Configuration format

```json
{
  "season": 2027,
  "version": "2027-draft-1",
  "components": [{"name": "<component>", "kind": "additive"},
                 {"name": "<component>", "kind": "capped", "cap": "<from the manual>"},
                 {"name": "<component>", "kind": "best_k", "k": "<from the manual>"}],
  "bonuses": [{"name": "<bonus>", "component": "<component>", "threshold": "<manual>", "value": "<decided>"}],
  "roles": [{"name": "defense", "max_per_alliance": "<manual or 3>"}],
  "alliance": {"active_robots": 3, "roster_size": 4, "lineup_choice": true, "short_handed": "plays_with_available"},
  "approval": {"status": "draft", "approved_by": null, "approved_on": null,
               "sources": {"components[0]": "<game manual section>"}}
}
```

The `<...>` placeholders are deliberately not numbers. No configuration file is shipped, and a test checks that.

## 4. What would make it a real optimizer (not started)

1. An approved 2027 configuration (section 2, items 1–5).
2. An adapter from the A3 estimates and scouting measurements to `RobotProfile` (items 6–8), point-in-time safe.
3. A partner-availability model (item 9), evaluated on past drafts.
4. A pre-registered evaluation on 2027 events, against P11-FB2 and the captains' actual picks, before any serving
   decision.
