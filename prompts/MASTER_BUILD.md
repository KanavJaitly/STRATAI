# StratAI Master Build Instructions

You are building StratAI as production-quality software.

This project is not optimized for speed.

It is optimized for correctness, maintainability, extensibility, scalability, and long-term architecture.

Every milestone should be treated as production software that future milestones will depend on.

Never rush to complete milestones.

Always optimize for engineering quality.


---

# Core Engineering Philosophy

Before writing code, understand the system.

Before changing the system, understand why it was designed that way.

Every change should make the project better than it was before.

Avoid technical debt whenever a clean solution naturally belongs to the current milestone.

Do not leave hidden problems for future milestones.

If a small improvement now prevents future architectural debt, implement it now.

The roadmap exists to organize development—not to limit engineering judgment.


---

# Guiding Principles

Always prefer:

- correctness over speed
- maintainability over cleverness
- clarity over brevity
- simplicity over unnecessary abstraction
- production readiness over milestone completion

Never optimize simply to finish faster.

Never leave placeholders.

Never knowingly introduce technical debt.

Never implement "temporary" production code.


---

# Architecture Rules

Maintain clean dependency direction.

Never introduce circular dependencies.

Never invert dependency direction.

Prefer extending existing abstractions over creating parallel systems.

Every new abstraction must solve a real problem.

Avoid duplicate implementations.

Avoid duplicate business logic.

Avoid duplicate validation logic.

Avoid duplicate database access patterns.

If existing infrastructure can be reused cleanly, reuse it.


---

# Phase A — Understand

Before writing any code:

Read the milestone completely.

Read every relevant file.

Understand how the milestone fits into the overall architecture.

Identify dependencies.

Identify architectural decisions.

Identify edge cases.

Identify interactions with previous milestones.

Do not begin implementation until the milestone is fully understood.


---

# Phase B — Design

Design the implementation first.

Verify that the design:

- matches the roadmap
- matches previous milestones
- preserves architecture
- preserves dependency direction
- scales properly
- introduces no unnecessary abstraction
- introduces no technical debt
- follows the project's design philosophy

Only begin implementation after the design is internally consistent.


---

# Phase B.5 — Challenge the Milestone

Assume the roadmap is incomplete.

Before implementation ask:

- What assumptions does this milestone make?
- What future milestones depend on this one?
- What hidden edge cases exist?
- What foundational work belongs here instead of later?
- What small improvements now prevent future technical debt?
- What architectural decisions should be made now instead of later?

If those improvements naturally belong to this milestone, implement them.

Do not defer obvious foundational work.


---

# Phase C — Implement

Implement everything required.

Do not leave placeholders.

Do not defer required work.

Implement only work that belongs to this milestone.

Keep implementations clean and understandable.

Prefer the simplest architecture that completely satisfies the milestone.

Do not build speculative features.

Do not over-engineer.

Every design decision should have a reason.


---

# Phase D — Testing

After implementation:

Write every required test.

Testing must include whenever applicable:

- unit tests
- regression tests
- boundary tests
- edge cases
- invalid inputs
- malformed inputs
- repeated execution
- idempotency
- concurrency
- rollback behavior
- failure recovery

Run the entire test suite.

Fix every failing test.

Repeat until every test passes.


---

# Phase E — Architecture Review

Do not assume your implementation is correct.

Review it like a senior engineer reviewing another person's code.

Compare against:

- roadmap
- milestone
- previous milestones
- project philosophy
- architecture

Look for:

- architectural drift
- duplicated logic
- inconsistent naming
- poor abstractions
- unnecessary complexity
- dependency violations
- circular dependencies
- maintainability concerns
- scalability concerns
- performance concerns
- extension problems

Improve anything that naturally belongs in this milestone.


---

# Phase F — Bug Hunt

Attempt to break the implementation.

Construct adversarial scenarios.

Assume someone is intentionally trying to expose weaknesses.

Look for:

- hidden bugs
- race conditions
- deadlocks
- ordering bugs
- stale state
- duplicated state
- silent failures
- rollback failures
- partial writes
- inconsistent outputs
- invalid assumptions
- sentinel-value bugs
- API assumption bugs
- database inconsistencies
- concurrency issues
- performance bottlenecks

Fix every issue discovered.


---

# Phase G — Documentation Review

Documentation must explain WHY, not only WHAT.

Verify:

- documentation matches implementation
- implementation matches documentation
- architecture decisions are explained
- future contributors can understand the reasoning
- no stale documentation exists

Update documentation if needed.


---

# Phase H — Regression Testing

Run the complete test suite again.

Ensure:

- no regressions
- previous milestones still work
- architecture remains clean
- documentation remains accurate
- all tests pass

Repeat until no further issues remain.


---

# Phase I — Acceptance Review

Treat the milestone as production software.

Verify:

- roadmap completed
- milestone completed
- every "What to do" item implemented
- every "Success looks like" item demonstrably true
- every "What to test" item implemented and executed
- architecture preserved
- project philosophy preserved
- tests complete
- documentation updated

Assume another senior engineering team will inherit this code tomorrow.

Ask:

Would they understand it?

Would they trust it?

Would they extend it correctly?

If not, improve it.


---

# Milestone Completion Criteria

A milestone is complete only when:

✓ Every roadmap requirement exists.

✓ Every success criterion is satisfied.

✓ Every required test exists.

✓ Entire test suite passes.

✓ Documentation is current.

✓ Architecture remains clean.

✓ No meaningful issues remain.

Do not continue if the milestone is not production ready.


---

# Mid-Phase Audit

Halfway through every phase:

Stop.

Perform a complete production-readiness review.

Attempt to find:

- regressions
- architectural drift
- coupling
- duplicated logic
- stale docs
- hidden assumptions
- missing tests
- race conditions
- data-quality issues
- performance regressions
- extension problems

Fix every issue before continuing.


---

# Phase Acceptance Review

After the final milestone:

Treat the phase as production software.

Attempt to break every subsystem.

Review:

- architecture
- maintainability
- scalability
- extensibility
- performance
- reliability
- developer experience
- security
- production readiness

Look for:

- hidden bugs
- race conditions
- stale documentation
- duplicated code
- unnecessary abstractions
- incorrect assumptions
- missing edge cases
- API inconsistencies
- database inconsistencies
- missing tests
- insufficient tests
- backwards compatibility
- future extension issues

Fix everything possible.

Repeat until no additional meaningful improvements remain.


---

# Continuous Improvement

Claude may:

- rename variables
- improve architecture
- improve abstractions
- improve documentation
- add comments
- reorganize files
- improve naming
- improve developer experience
- improve testing
- improve maintainability

provided these improvements naturally belong to the current milestone.

Do not postpone obvious quality improvements.


---

# Engineering Workflow

Understand

↓

Design

↓

Challenge the Milestone

↓

Implement

↓

Testing

↓

Architecture Review

↓

Bug Hunt

↓

Documentation Review

↓

Regression Testing

↓

Acceptance Review

↓

Only then continue.


---

# Milestone Report

At the end of every milestone report:

Completed

Files Changed

Architectural Decisions

Architectural Improvements

Tests Added

Tests Passing

Issues Found

Issues Fixed

Remaining Known Risks

Why the milestone satisfies the roadmap

Production Readiness

Readiness for the next milestone


---

# Ultimate Objective

Never optimize for finishing the project.

Optimize for building software that another experienced engineering team could confidently extend for years without needing to redesign earlier phases.

Every milestone should leave the project stronger than before.