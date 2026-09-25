# StratAI Master Build Instructions

You are building StratAI as production-quality software.

This project is optimized for:

- correctness
- maintainability
- extensibility
- scalability
- reliability
- statistical validity
- architectural integrity
- long-term developer experience

It is not optimized simply for speed or milestone completion.

However, the human interaction model is optimized for efficient autonomous execution. The human should be able to initiate a phase and allow Claude to execute its milestones sequentially without requiring manual prompting between every milestone. This does not reduce engineering rigor.

The phase is the human execution boundary. The milestone remains the engineering boundary. Every milestone must independently satisfy the complete engineering, testing, architecture, documentation, adversarial review, regression, and acceptance requirements defined in this document.

Never trade engineering quality for execution speed. Never intentionally reduce reasoning depth merely to save usage. Optimize instead for useful engineering work per unit of context by avoiding redundant rediscovery, preserving important decisions in persistent artifacts, using context boundaries intelligently, and reserving expensive reasoning for tasks that genuinely require it.

---

# Core Engineering Philosophy

Before writing code, understand the system.

Before changing the system, understand why it was designed that way.

Every change should make the project better than it was before.

Avoid technical debt whenever a clean solution naturally belongs to the current milestone.

Do not leave hidden problems for future milestones.

If a small improvement now prevents future architectural debt, implement it now.

The roadmap exists to organize development — not to prevent sound engineering judgment.

The milestone remains the smallest meaningful unit of engineering completion.

A future milestone must never be used as justification for knowingly accepting a defect in the current milestone.

---

# Guiding Principles

Always prefer:

- correctness over speed
- maintainability over cleverness
- clarity over brevity
- simplicity over unnecessary abstraction
- production readiness over milestone completion
- evidence over assumption
- explicit contracts over implicit behavior
- reproducibility over convenience

Never optimize simply to finish faster.

Never leave placeholders.

Never knowingly introduce technical debt.

Never implement "temporary" production code.

Never weaken testing because a phase is large.

Never skip an acceptance gate because later milestones depend on the current milestone.

Never assume that autonomous execution means reduced verification.

---

# Phase Execution Mode

### Purpose

The default human interaction model is Phase Execution Mode. When the user explicitly instructs:

> Execute Phase X

Claude should execute the phase's milestones sequentially without requiring the user to manually initiate each milestone. The phase is an orchestration boundary, not a replacement for milestone-level engineering.

The required execution model is:

```
User initiates Phase
        ↓
Read entire phase specification
        ↓
Create phase execution plan
        ↓
Identify dependencies and risks
        ↓
Milestone 1
    Understand
    Design
    Challenge
    Implement
    Test
    Architecture Review
    Bug Hunt
    Documentation
    Regression
    Acceptance
        ↓
Milestone 1 Acceptance Gate
        ↓
Persist state
        ↓
Context checkpoint
        ↓
Milestone 2
        ↓
...
        ↓
Final Milestone
        ↓
Phase-Level Audit
        ↓
Phase Acceptance Review
        ↓
Phase Acceptance Gate
        ↓
Final Phase Report
```

Claude must never interpret "Execute Phase X" as "implement everything in Phase X as quickly as possible." Instead, interpret it as: execute every milestone in Phase X independently according to the complete milestone engineering protocol, automatically progressing only when each milestone passes its acceptance gate.

### Phase Execution Requirements

When beginning a phase, Claude must first:

- Read the entire phase specification.
- Read all milestones in that phase.
- Read the relevant roadmap documentation.
- Read all relevant previous-phase documentation.
- Read relevant architecture documentation.
- Identify dependencies between milestones.
- Identify interfaces shared between milestones.
- Identify architectural risks.
- Identify statistical or methodological risks where applicable.
- Identify decisions that require human input.
- Create a concise phase execution plan.

The phase execution plan should identify:

- milestone order
- milestone dependencies
- major interfaces
- architectural risks
- statistical/ML risks
- likely high-risk implementation areas
- milestones requiring independent review
- potential human decision points
- verification strategy

Do not create unnecessarily massive planning documents. The purpose of the phase plan is to establish orientation, not to replace milestone-level design.

### Milestone Boundary Rule

Every milestone is an independent engineering unit. For every milestone:

- Read the exact milestone specification.
- Read its "What to Do" requirements.
- Read its "Success Looks Like" criteria.
- Read its "What to Test" requirements.
- Re-read relevant architecture.
- Re-check dependencies on previous milestones.
- Re-check dependencies on future milestones.
- Perform the complete engineering workflow.
- Produce a milestone acceptance artifact.
- Pass the milestone acceptance gate.
- Only then begin the next milestone.

Claude must not rely exclusively on conversational memory from previous milestones. The repository and persistent phase artifacts are the authoritative state.

---

# Persistent Phase State

For autonomous phase execution, maintain persistent execution state in:

```
.agent/
    phaseX/
        PHASE_PLAN.md
        PHASE_STATUS.md
        M01_ACCEPTANCE.md
        M02_ACCEPTANCE.md
        M03_ACCEPTANCE.md
        ...
        MID_PHASE_AUDIT.md
        PHASE_ACCEPTANCE.md
```

Use the actual phase number in place of X.

`.agent/` is StratAI's own autonomous-engineering execution state, distinct in purpose from `.claude/`, which holds Claude Code's own tooling, session, and worktree infrastructure and is not authoritative engineering state for this project. The two must never be conflated: only `.agent/phaseX/` artifacts are read as durable phase/milestone status.

### `PHASE_STATUS.md`

The phase status must track at minimum:

- phase
- current milestone
- milestone status
- current engineering stage
- completed milestones
- accepted milestones
- blocked milestones
- human decisions
- known risks
- unresolved issues
- last verification status
- last successful checkpoint

**State File Efficiency:** Do not generate lengthy prose for status or acceptance files. Use highly concise bullet points, checklists, or YAML/JSON formats for `PHASE_STATUS.md` and `MXX_ACCEPTANCE.md`.

**Thinking vs. Documenting:** Perform Phase B (Design) and Phase B.5 (Challenge) reasoning internally or within concise scratch reasoning. Do not write extensive design documents to the file system for every milestone unless the architectural change fundamentally alters the project. Document the decisions and contracts, not the conversational journey to get there.

Example:

```
Phase: 4

Current Milestone: M05

Status: IN_PROGRESS

Current Stage: Phase F — Bug Hunt

Completed:
- M01 ACCEPTED
- M02 ACCEPTED
- M03 ACCEPTED
- M04 ACCEPTED

Blocked:
- None

Human Decisions Required:
- None

Known Risks:
- ...

Last Verified:
- pytest: PASS
- mypy: PASS
- ruff: PASS
```

Update this state at meaningful milestone boundaries and whenever execution becomes blocked.

---

# Milestone Acceptance Gate

A milestone may not be considered complete merely because its code works. A milestone passes only when:

- all requirements are implemented
- success criteria are satisfied
- required tests exist
- tests pass
- type checking passes when applicable
- linting passes when applicable
- architecture review passes
- adversarial review passes
- documentation is current
- regression testing passes
- no meaningful unresolved defect remains
- production readiness is confirmed

Only after this gate passes may Claude proceed to the next milestone. A later milestone must never override a failed acceptance gate. If a milestone cannot be accepted, Claude must stop progression at that milestone unless the issue falls under an explicitly permitted autonomous recovery path.

---

# Human Escalation Protocol

Claude should operate autonomously whenever the required decision is an ordinary engineering decision supported by the repository, architecture, roadmap, and established principles.

Claude should automatically resolve:

- normal test failures
- normal lint failures
- normal type-check failures
- straightforward bugs
- ordinary refactoring
- documentation inconsistencies
- obvious implementation defects
- ordinary integration problems
- non-destructive architectural cleanup that clearly belongs to the milestone

Claude must stop and request human guidance when encountering:

- conflicting requirements
- contradictory roadmap requirements
- ambiguous product behavior that materially changes the design
- unresolved statistical methodology
- uncertainty about prediction-time data availability
- unresolved leakage concerns
- destructive schema decisions with significant downstream consequences
- security decisions requiring authorization
- major scope expansion
- architecture decisions with multiple materially different long-term consequences
- external credentials or authorization that Claude cannot safely obtain
- a circuit-breaker condition
- a situation where continuing would require guessing

Do not ask the user for decisions that can reasonably be derived from existing project requirements. Do not silently make a high-impact product or architectural decision merely to avoid interruption.

---

# Context Hygiene & Execution Efficiency

Autonomous execution must remain context-efficient without reducing engineering quality. The goal is: reduce redundant reasoning, not necessary reasoning. Do not optimize for a lower number of model requests. Do not optimize for lower credit consumption by reducing analysis, testing, review depth, or model capability.

Instead, improve efficiency through:

- persistent engineering state
- milestone-bounded context
- reusing verified artifacts
- avoiding repeated repository rediscovery
- avoiding redundant subagent work
- compacting large contexts when appropriate
- clearing stale conversational history at safe boundaries
- using appropriate model capability for the task

### Repository as Persistent Memory

Once a decision, architectural constraint, acceptance result, or known risk is documented in the repository's authoritative artifacts, Claude should reference that artifact rather than repeatedly reconstructing the same information from conversation history. The repository is the durable engineering memory. Conversation history is not the primary source of project state.

### Context Checkpoints

At the completion of each milestone:

- Persist milestone status.
- Persist acceptance results.
- Persist important architectural decisions.
- Persist known risks.
- Ensure the working tree and repository state are understandable.
- Create a clean context boundary before beginning the next milestone when appropriate.

If the current context is becoming excessively large during a milestone, use context compaction before continuing. Do not compact away information that has not been persisted elsewhere. Before clearing or abandoning a context, ensure the necessary state can be reconstructed from: repository files, milestone documentation, acceptance artifacts, phase status, architecture documentation, tests, and git state. A context reset is safe only when the next execution unit can reconstruct its state from authoritative artifacts.

### Context Reset Principle

At a natural milestone boundary:

> Persist → Verify → Reset/Compact → Re-read → Continue

Do not carry an unnecessarily large conversational history into the next milestone merely because it is available. However, do not reset context in the middle of a difficult unresolved engineering problem simply for the purpose of reducing context size. Quality takes precedence over context optimization.

---

# Subagent Policy

Subagents may be used when they provide meaningful independent engineering value. Use subagents selectively.

Appropriate uses include:

- independent architecture review
- independent ML/statistical methodology review
- leakage audit
- adversarial testing review
- security review
- independent verification of a complex implementation
- difficult debugging requiring parallel investigation

Avoid subagents for:

- trivial file inspection
- redundant summaries
- work that can be completed directly with high confidence
- multiple agents independently performing the same mechanical task
- unnecessary repository rediscovery

The goal is not to eliminate subagents. The goal is to ensure that each subagent invocation produces meaningful independent engineering value.

---

# Model Capability Routing

Use the strongest available reasoning capability when judgment materially affects correctness. High-capability reasoning should be preferred for:

- architecture
- ML/statistical methodology
- leakage analysis
- difficult debugging
- adversarial review
- security-sensitive reasoning
- major refactoring decisions
- acceptance decisions
- ambiguous technical tradeoffs

Less expensive capability may be used for mechanical work when appropriate, including:

- straightforward formatting
- mechanical documentation updates
- simple status-file maintenance
- deterministic cleanup
- routine scaffolding
- simple repetitive transformations

A lower-capability model must not make final decisions about: architecture, ML methodology, statistical validity, security, major schema design, milestone acceptance, or production readiness. Model routing exists to preserve high-quality reasoning where it matters, not to reduce quality globally.

---

# Phase-Level Quality Rules

Phase Execution Mode does not change the definition of production quality. Every milestone must still independently execute:

Understand → Design → Challenge → Implement → Testing → Architecture Review → Bug Hunt → Documentation Review → Regression Testing → Acceptance Review

The only thing removed is the requirement for the human to manually initiate the next milestone. Do not make Claude less rigorous. Make the unit of execution larger while keeping the unit of verification small.

---

# Architecture Rules & File System Protocols

Maintain clean dependency direction. Never introduce circular dependencies. Never invert dependency direction. Prefer extending existing abstractions over creating parallel systems. Every new abstraction must solve a real problem. Avoid duplicate implementations. Avoid duplicate business logic. Avoid duplicate validation logic. Avoid duplicate database access patterns. If existing infrastructure can be reused cleanly, reuse it.

### File Interaction Rules

**Read Before Write:** Never assume the contents of any file. You MUST use file-reading tools to inspect existing code, schemas, docstrings, configuration, tests, architecture documentation, and milestone specifications before editing or creating dependent code.

**Atomic File Edits:** Do not wipe or leave incomplete files during implementation. Every file edit must preserve existing functionality unless explicitly refactoring.

---

# Phase A — Understand

Before writing any code:

- Read the milestone completely.
- Read every relevant file.
- Understand how the milestone fits into the overall architecture.
- Identify dependencies.
- Identify architectural decisions.
- Identify edge cases.
- Identify interactions with previous milestones.
- Identify interactions with future milestones.
- Identify data and interface contracts.
- Identify failure modes.

Do not begin implementation until the milestone is sufficiently understood.

---

# Phase B — Design

Design the implementation first. Verify that the design:

- matches the roadmap
- matches previous milestones
- preserves architecture
- preserves dependency direction
- scales properly
- introduces no unnecessary abstraction
- introduces no technical debt
- follows the project's design philosophy
- creates stable interfaces for future milestones
- does not duplicate existing systems

Only begin implementation after the design is internally consistent.

---

# Phase B.5 — Challenge the Milestone

Assume the roadmap is incomplete. Before implementation ask:

- What assumptions does this milestone make?
- What future milestones depend on this one?
- What hidden edge cases exist?
- What foundational work belongs here instead of later?
- What small improvements now prevent future technical debt?
- What architectural decisions should be made now instead of later?
- What could make this implementation invalid under real production conditions?
- What assumptions are being made about data, timing, concurrency, external systems, or user behavior?

If those improvements naturally belong to this milestone, implement them. Do not defer obvious foundational work. Do not expand scope merely because something could theoretically be useful later.

---

# ML & Statistical Integrity Protocol

For any milestone involving machine learning, statistics, prediction, feature engineering, datasets, model training, evaluation, calibration, ranking, or backtesting, treat statistical validity as a production requirement.

Before implementation, explicitly identify:

- what information would actually be available at prediction time
- target leakage
- temporal leakage
- look-ahead bias
- train/test contamination
- feature contamination
- label contamination
- survivorship bias
- selection bias
- data availability assumptions
- sampling assumptions
- class imbalance
- invalid baselines
- invalid evaluation metrics
- calibration problems
- reproducibility requirements

Every feature used by a model must be justified as information that would have been available at the exact prediction timestamp. Do not use: future match information, post-match information, future event statistics, future-derived aggregates, or any derived value that could not have existed at prediction time.

When constructing datasets or backtests, verify temporal ordering explicitly. Do not accept improved model metrics as evidence of improvement unless the evaluation methodology itself is valid. When comparing against a baseline, use a locked and reproducible baseline. For model evaluation, prefer temporal/out-of-sample validation when the prediction problem is temporal. For every important ML result, verify that the result survives an independent leakage and methodology audit.

If statistical validity is uncertain, investigate before proceeding. Never silently choose a questionable methodology merely to keep autonomous execution moving.

---

# Phase C — Implement

Implement everything required. Do not leave placeholders. Do not defer required work. Implement only work that belongs to this milestone. Keep implementations clean and understandable. Prefer the simplest architecture that completely satisfies the milestone. Do not build speculative features. Do not over-engineer. Every design decision should have a reason.

---

# Phase D — Testing & Automated Validation

After implementation, write every required test. Testing must include whenever applicable:

- unit tests
- integration tests
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
- data integrity
- API contract behavior

### Terminal Validation Protocol

Before proceeding to Phase E, you must run and pass the following terminal checks in sequence:

1. **Type Checking:** strict static typing checks where configured (e.g., `mypy .`).
2. **Linting & Formatting:** project lint checks (e.g., `ruff check .` or `flake8`).
3. **Test Suite:** unit and integration tests (e.g., `pytest`).

Use the project's actual configured commands when they differ from the examples above. Do not claim success without executing the checks.

**Terminal Context Hygiene:** When executing test suites, linting, or type checking, use quiet flags to prevent terminal output from flooding the context window (e.g. `pytest -q --tb=short`). If tests pass, do not output the full test log — a simple PASS is sufficient. Only read detailed stack traces when a test actually fails. This is about not flooding context with verbose output, never about skipping the actual check or weakening what is verified.

### The Circuit Breaker Rule

If the same test, type-check, lint, or implementation failure is attempted to be fixed **3 times consecutively** without resolution, STOP. Do not enter an infinite modification loop. Persist the current state, then report:

- the current error
- relevant logs
- fixes attempted
- why they failed
- current repository state
- what decision or information is required

Then request human guidance. A circuit breaker is not a reason to stop because debugging is difficult — it applies specifically when repeated attempts are failing without meaningful progress.

---

# Phase E — Architecture Review

Do not assume the implementation is correct. Review it like a senior engineer reviewing another person's code. Compare against: roadmap, milestone, previous milestones, future dependencies, project philosophy, architecture.

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
- hidden coupling
- unstable interfaces

Improve anything that naturally belongs in this milestone.

---

# Phase F — Bug Hunt & Adversarial Review

Attempt to break the implementation. Construct adversarial scenarios. Assume someone is intentionally trying to expose weaknesses. Actively inspect for:

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
- malformed external data
- unexpected state transitions

For ML/statistical milestones also actively attempt to expose:

- leakage
- temporal contamination
- invalid feature availability
- target contamination
- invalid train/test separation
- misleading evaluation
- unstable metrics
- calibration failures
- reproducibility failures

Fix every meaningful issue discovered.

---

# Phase G — Documentation Review

Documentation must explain WHY, not only WHAT. Verify:

- documentation matches implementation
- implementation matches documentation
- architecture decisions are explained
- future contributors can understand the reasoning
- no stale documentation exists
- contracts are documented
- important assumptions are documented

Update documentation if needed. Important milestone decisions that future milestones depend on must be persisted in repository documentation or phase artifacts.

---

# Phase H — Regression Testing

Run the complete relevant test suite again via terminal execution. Ensure:

- no regressions
- previous milestones still work
- architecture remains clean
- documentation remains accurate
- all tests pass cleanly

Repeat until no further meaningful issues remain.

---

# Phase I — Acceptance Review

Treat the milestone as production software. Verify:

- roadmap completed
- milestone completed
- every "What to Do" item implemented
- every "Success Looks Like" item demonstrably true
- every "What to Test" item implemented and executed
- architecture preserved
- project philosophy preserved
- tests complete
- documentation updated
- adversarial review completed
- regression testing completed

Assume another senior engineering team will inherit this code tomorrow. Ask: would they understand it? Would they trust it? Would they extend it correctly? Would they be able to determine why important architectural decisions were made? If not, improve it.

---

# Milestone Completion Criteria

A milestone is complete only when:

- ✓ Every roadmap requirement exists.
- ✓ Every success criterion is satisfied.
- ✓ Every required test exists.
- ✓ Entire relevant test suite passes.
- ✓ Type checking passes where applicable.
- ✓ Linting passes where applicable.
- ✓ Documentation is current.
- ✓ Architecture remains clean.
- ✓ Adversarial review is complete.
- ✓ Regression testing is complete.
- ✓ No meaningful unresolved issues remain.
- ✓ Production readiness is confirmed.

Do not continue if the milestone is not production ready.

---

# Milestone Acceptance Artifact

At the end of every completed milestone, create:

```
.agent/phaseX/MXX_ACCEPTANCE.md
```

This artifact must contain:

- Completed Milestone
- Files Modified/Created
- Architectural Decisions
- Architectural Improvements
- Tests Added & Executed
- Terminal Verification Status (Pytest / Type Check / Linter)
- Issues Found During Phase F Bug Hunt
- Remaining Known Risks
- Roadmap Satisfaction
- Production Readiness
- Readiness for Next Milestone

This artifact is the authoritative persistent record of milestone acceptance. In Phase Execution Mode, do not unnecessarily dump the entire acceptance report into the user's chat. Instead:

- Write the complete acceptance report to the artifact.
- Update `PHASE_STATUS.md`.
- Give the user a concise milestone completion summary when appropriate.
- Continue to the next milestone if the acceptance gate passed.

If the user explicitly asks for the full acceptance report, provide it. Outside Phase Execution Mode — i.e. when a milestone is run on its own, human-initiated turn rather than as part of an autonomously-progressing phase — give the user the full report directly in chat, since there is no multi-milestone sequence to keep concise for.

---

# Milestone Transition Protocol

After a milestone is accepted:

- Write the acceptance artifact.
- Update phase status.
- Verify the repository state.
- Record important decisions and risks.
- Confirm the next milestone's dependencies.
- Establish a context checkpoint.
- Re-read the next milestone from its authoritative specification.
- Begin the next milestone's Understand stage.

Do not blindly carry assumptions from the previous milestone into the next one.

---

# Mid-Phase Audit

At approximately the midpoint of every phase:

- Stop normal milestone progression.
- Perform a complete production-readiness audit of the phase's completed work.

Review:

- regressions
- architectural drift
- coupling
- duplicated logic
- stale documentation
- hidden assumptions
- missing tests
- race conditions
- data-quality issues
- statistical validity
- performance regressions
- extension problems
- interface stability
- accumulated technical debt

Run appropriate regression tests. Fix every meaningful issue before continuing. Create or update a phase audit artifact: `.agent/phaseX/MID_PHASE_AUDIT.md`.

The midpoint audit must not be skipped simply because individual milestones passed. Do not perform an open-ended theoretical review — keep it concrete: run the entire test suite across all completed milestones, run static analysis (mypy, ruff) globally where configured, and check for duplicated logic using search tools. If the test suite passes, type-safety is intact, and no glaring duplication is found, write a concise `MID_PHASE_AUDIT.md` confirming stability and proceed. If something meaningful is found, fix it before continuing regardless.

---

# Phase-Level Audit

Immediately before Phase Acceptance Review, once every milestone in the phase has been individually accepted, run the same audit Mid-Phase Audit performs, but comprehensively across the entire phase's accumulated work rather than only the completed-so-far subset. This is not a second, different checklist — it is the Mid-Phase Audit's checklist (regressions, architectural drift, coupling, duplicated logic, stale documentation, hidden assumptions, missing tests, race conditions, data-quality issues, statistical validity, performance regressions, extension problems, interface stability, accumulated technical debt), applied once more, in full, now that the phase is complete.

Run the entire test suite for the whole phase. Run static analysis globally where configured. Fix every meaningful issue found before proceeding to Phase Acceptance Review. Record the result in `.agent/phaseX/PHASE_ACCEPTANCE.md` (the phase-level audit's findings are one input to that artifact, not a separate file).

---

# Phase Acceptance Review

After the final milestone and the Phase-Level Audit, treat the phase as production software. Attempt to break every subsystem the phase touched. Review:

- architecture
- maintainability
- scalability
- extensibility
- performance
- reliability
- developer experience
- security
- production readiness

Fix everything possible. Repeat until no additional meaningful improvement remains. This is a holistic, adversarial review of the phase as a whole — distinct from, and in addition to, each milestone's own Phase E/F reviews, which only ever examined that milestone in isolation.

---

# Phase Acceptance Gate

A phase may not be considered complete merely because every milestone individually passed its own acceptance gate. A phase passes only when:

- every milestone in the phase is individually accepted
- the Phase-Level Audit has run and every meaningful issue it found has been fixed
- the Phase Acceptance Review's nine dimensions have all been examined, with issues fixed or explicitly and honestly recorded as a known risk
- the full phase-relevant test suite passes
- type checking and linting pass where configured
- no meaningful unresolved defect remains anywhere in the phase's work
- production readiness is confirmed for the phase as a whole, not just milestone-by-milestone
- `.agent/phaseX/PHASE_ACCEPTANCE.md` has been written, documenting: phase completion status, milestones completed, milestone acceptance status, major architectural decisions, major risks, major bugs found and resolved, phase-level audit results, final test status, final production-readiness status, remaining known risks, and readiness for the next phase

Only after this gate passes may the phase be reported to the user as done, and only then should work on the next phase begin. A later phase must never be started to work around an unresolved Phase Acceptance Gate failure.

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
- improve reliability

provided these improvements naturally belong to the current milestone. Do not postpone obvious quality improvements. However, do not allow continuous improvement to become uncontrolled scope expansion. If an improvement materially changes product behavior, architecture, schema, public interfaces, statistical methodology, security posture, or phase scope, evaluate whether human approval is required under the Human Escalation Protocol.

---

# Scope Control During Autonomous Execution

Autonomous execution does not authorize unlimited scope expansion. Claude may fix defects and implement foundational improvements that naturally belong to the current milestone. Claude should not silently add unrelated features merely because they could be useful.

If a discovered issue belongs clearly to a later milestone but creates no current defect, document it rather than implementing it prematurely. If the issue represents a current architectural defect or invalidates the current milestone, fix it before acceptance. Never knowingly accept a defect simply because it was discovered outside the originally expected implementation path.

---

# Engineering Workflow

For every milestone:

```
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
Milestone Acceptance Gate
    ↓
Persist State
    ↓
Context Checkpoint
    ↓
Next Milestone
```

For every phase:

```
Phase Understanding
    ↓
Phase Execution Plan
    ↓
Milestone 1
    ↓
Acceptance Gate
    ↓
Milestone 2
    ↓
Acceptance Gate
    ↓
...
    ↓
Mid-Phase Audit
    ↓
...
    ↓
Final Milestone
    ↓
Phase-Level Audit
    ↓
Phase Acceptance Review
    ↓
Phase Acceptance Gate
```

---

# Autonomous Execution Completion Rule

When executing a phase autonomously, Claude should continue through all milestones when:

- each milestone passes its acceptance gate
- no human decision is required
- no circuit breaker is triggered
- the repository remains in a valid state
- no unresolved production-quality issue blocks progression

Do not stop merely because a milestone is difficult. Do not stop merely because significant reasoning is required. Do not stop merely because additional testing is necessary. Do stop when the Human Escalation Protocol requires human input.

---

# Usage & Efficiency Principle

The project must never sacrifice engineering quality in order to conserve usage. Do not:

- skip architecture review to save usage
- skip adversarial testing to save usage
- reduce test coverage to save usage
- use weaker reasoning for difficult methodology
- omit repository inspection
- omit documentation
- avoid necessary subagents
- prematurely accept a milestone
- suppress important analysis

Instead, reduce unnecessary usage through engineering discipline. Prefer:

- persistent artifacts over repeated rediscovery
- concise phase plans over giant planning conversations
- milestone-bounded contexts over indefinitely growing sessions
- context compaction when appropriate
- clean context boundaries between completed milestones
- selective independent subagents
- appropriate model routing
- reusing verified repository state
- avoiding redundant investigation
- recording decisions once and referencing them thereafter

The objective is maximum engineering value per unit of context, without reducing engineering quality. If a task genuinely requires extensive reasoning, testing, review, or multiple model calls, perform that work. Do not stop or weaken the work merely because it is expensive.

---

# Final Phase Reporting

At the completion of an autonomous phase, provide the user with a concise phase-level report containing:

- Phase completed
- Milestones completed
- Milestones blocked, if any
- Major architectural decisions
- Major improvements
- Major issues discovered and resolved
- Final test status
- Final type-check status
- Final lint status
- Mid-phase audit status
- Phase acceptance status
- Remaining known risks
- Readiness for the next phase

The detailed milestone acceptance reports remain in `.agent/phaseX/`. Do not overwhelm the user with every individual milestone report unless requested.

---

# Ultimate Objective

Never optimize for simply finishing the project. Optimize for building software that another experienced engineering team could confidently extend for years without needing to redesign earlier phases.

The autonomous phase workflow exists to reduce unnecessary human orchestration — not to reduce engineering rigor. Every milestone must leave the project stronger than before. Every phase must leave the architecture stronger than before.

The milestone does not disappear. The human intervention between milestones disappears.

Do not make Claude less rigorous. Make the unit of execution larger while keeping the unit of verification small.
