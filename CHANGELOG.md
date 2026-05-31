## [unreleased]

### Features

- *(adapters)* Trial isolation via SandboxPort + bwrap (ADR 0009)
- *(3.5.1)* Add problem_ids filter to GraduatedProblemSetAdapter
- *(3.5.1)* Harden GraduatedProblemSetAdapter.problem_ids filter
- *(adr-0010)* Split acceptance into acceptance_fast and acceptance_full
- *(adr-0011)* Route outcome resolution through event-stream classifier
- *(adapter)* CliSubprocessAdapter subprocess timeout (ADR 0007 A2)
- *(trial_runner)* Emit boundary_violation on subprocess timeout
- *(preservation)* Error-trial scanner (ADR 0007 B1; pi-agent-space-1da)
- *(trial-runner)* Emit per-(problem, metric) events (ADR 0012; Phase 4.2)
- *(domain)* CapabilityProfile aggregator (ADR 0012; Phase 4.3)
- *(pareto)* 4D frontier over CapabilityProfile (ADR 0012; Phase 4.4)
- *(eval-suite)* Add 002 graph_valid_tree and 003 alien_dictionary fixtures (Phase 4.1)
- *(logging)* Add structured JSON logging (pi-agent-space-wtw)
- *(phase-5.1)* Define subjective-score event schema
- *(run-entity)* Implement Run as first-class domain entity (ADR 0013)
- *(phase-5.2)* Add write_subjective_score; load_trials reads subjective.json
- *(phase-5.2)* Add pi-eval score CLI entry point
- *(phase-5.3)* Define subjective_axis policy; 4D frontier unchanged
- *(phase-5.4)* Lift pareto_frontier to 5D with subjective axis

### Bug Fixes

- *(adapter)* Run validation steps with shell=False (pi-agent-space-2wy)

### Refactor

- *(3.5.1)* Extract ADR 0007 model-error predicate to lifecycle module
- *(phase-5.2)* Make final.json objective-only; drop orphaned events.py

### Documentation

- *(readme)* Update status section through Phase 3
- Add Rosetta Stone guide with dual deductive/inductive paths
- Deepen Python context in Rosetta Stone guides with I/O and asyncio examples
- *(3.5.1)* Mark OptimizerDriver.retry_budget as declarative-only in v1
- *(3.5.1)* Sync references to deleted predicates and scope lifecycle.py
- *(plan)* Bake Phase 3.5.1 lessons into Phase 4 entry conditions
- *(contributors)* Add phase 1–3 demo snapshots from showboat
- *(adr-0011)* Close spike 0008 — outcome classifier as single SoT
- *(design-notes)* Preservation queue is a derived view, not a stored artifact
- Update AGENTS.md with progressive disclosure instructions for AI assistants
- Add TDD methodology to AGENTS.md
- Compress implementation plan to focus on strategy and future phases
- *(adr)* Accept ADR 0012 — capability profile + per-(problem, metric) events
- Separate spike-ID namespace (S###) from ADR numbers
- Reconcile pre-Phase-4 Pareto / Metrics drift (pi-agent-space-98m)
- *(plan)* Note dimensional lifts in Phase 5/6 steps (pi-agent-space-98m)
- ADR 0013 (Accepted), 0014 (Accepted), 0015 (Proposed); close S001/S002

### Testing

- *(phase2)* Pin acceptance test to problem_ids=["001_binary_search"]
- *(phase4)* Acceptance test for capability profile scaling-slope discrimination

### Chores

- *(haskell)* Reconcile DSL drift with Python implementation
- *(haskell)* Import Outcome/Metrics from AgentSpace in Ports.hs

### Other

- Lift Pareto to 4D with scalingSlope (ADR 0012; pi-agent-space-98m)
## [phase-3-complete] - 2026-05-13

### Features

- *(dsl)* Implement ArrowChoice, ArrowLoop, and Parameterized Morphisms (Para)
- *(examples)* Implement abstract Claude Code workflow
- *(evaluator)* Init python subproject with Hexagonal Architecture skeleton
- *(haskell)* Add domain-flavored Ports module
- *(domain)* Add Phase 1.1 types and 1.2 candidate-identity hash
- *(evaluator)* Add Phase 1.3–1.6 ports and stub adapters
- *(evaluator)* Add TrialRunner orchestrator (Phase 1.7)
- *(adapters)* Add workspace materialization helper (Phase 2.1)
- *(adapters)* Add CliSubprocessAdapter for real Pi (Phase 2.2)
- *(adapters)* Validation execution + RawTelemetry extension (Phase 2.3)
- *(adapters)* Add SyntheticSuiteScorer (Phase 2.4)
- *(adapter)* Preserve stderr and malformed lines in RawTelemetry
- *(runner)* Classify trial outcome per ADR 0007
- *(haskell)* Bubble ADR 0006 + 0007 into AgentSpace types
- *(metrics)* Track cost_dollars alongside tokens per ADR 0005
- *(domain)* Add slot/value space schema (Phase 3.1)
- *(domain)* 3D Pareto frontier over tokens, dollars, quality (Phase 3.3)
- *(adapters)* RandomFromSlotSpace proposer (Phase 3.2)
- *(optimizer)* Driver loop + frontier persistence (Phase 3.4 base)
- *(optimizer)* Per-trial + per-run cost cap enforcement (Phase 3.4)
- *(optimizer)* Circuit breaker for consecutive errors + time (Phase 3.4)
- *(adapters)* Retry budget on CliSubprocessAdapter (Phase 3.4)

### Bug Fixes

- *(adapter)* Resolve workspace_dir to absolute path on load
- *(identity)* Canonicalize skills as a sorted set in candidate hash

### Refactor

- *(dsl)* Implement mathematically accurate ArrowLoop trace for dreaming

### Documentation

- *(adr)* Update ADR 0001 to accept Python and black-box interaction
- *(math)* Add sections on ArrowChoice, ArrowLoop, and Para
- *(architecture)* Add Claude Code modeling example
- *(architecture)* Add OpenClaw modeling example
- *(math)* Add case studies for Claude Code and OpenClaw
- *(adr)* Adopt Hexagonal Architecture to defer IPC decision
- *(math)* Add Appendix A — User-Harness Feedback as a Lens
- *(plan)* Fold Phase 1 lessons into Phases 2, 4, and 5
- *(plan)* Defer __init__.py / public-surface decision to deploy phase
- Add design-notes.md as a lightweight sub-ADR design log
- *(plan)* Fold Phase 2 lessons into Phases 3, 4, and 6
- *(notes)* Append four Phase 2 design choices to design-notes
- *(adr)* Draft ADR 0004 — workspace isolation strategy (Proposed)
- *(adr)* Accept ADR 0004 — workspace isolation strategy
- Establish spike-tracking convention via draft ADRs
- *(adr)* Seed ADRs 0005, 0006, 0007 as draft spike notebooks
- *(adr)* Accept ADR 0005 — trial cost and budget model
- *(adr)* Accept ADR 0006 — reproducibility under stochastic agents
- *(adr)* Reshape ADR 0007 with three-axis framing
- *(adr)* Accept ADR 0007 — Pi invocation lifecycle
- *(plan)* Fold ADR 0004-0007 commitments into the plan
- *(plan,notes)* Record Phase 2 closeout findings
- *(math)* Bubble ADR 0006 + 0007 commitments into the paper
- *(architecture)* Add ARCHITECTURE.md as the orientation document
- *(architecture)* Split Haskell content into haskell.md
- *(architecture)* Rename README, dedupe case studies, render all three
- *(architecture)* Replace empty module map with Claude Code workflow
- *(plan)* Phase 3 retrospective — add 3.5.1 cleanup + open spikes

### Testing

- *(problems)* Define GraduatedProblem schema and add 001_binary_search
- *(evaluator)* Phase 1 end-to-end acceptance test (Phase 1.8)
- *(evaluator)* Add Phase 2 real-Pi acceptance test (Phase 2.5)
- *(acceptance)* Phase 3.5 multi-trial driver-mechanics test

### Chores

- Persist scaffolding, documentation, and Haskell OpenClaw case study
- *(domain)* Modernize List[X] to list[X] in test_suite

### Other

- *(mise)* Add setup/lint/format/typecheck tasks for python
- *(ruff)* Enable UP+I rules and auto-fix in format task
- *(mise)* Add docs:build task for pandoc + mermaid-filter
- *(mise,docs)* Wire weasyprint + puppeteer config so docs:build runs
