# Review of .

## Headline (auto-handled)

1. [severity: high | effort: small | slp(s): architecture] ~~Lifecycle classification logic (ADR 0007) is duplicated between `TrialRunner._has_model_error` and `CliSubprocessAdapter._is_retryable_error`.~~ **Resolved by Step 3.5.1 (commit `2611d45`):** predicate extracted to `pi_evaluator.lifecycle.is_model_error`; both call sites import it.
2. [severity: medium | effort: medium | slp(s): architecture] ADR back-references in code use numeric IDs (e.g., "ADR 0005") instead of the exact filename slugs (e.g., "0005-trial-cost-and-budget").
The `architecture` skill mandates using the exact slug to ensure references are mechanically greppable across the repo and resilient to drift.
   - **Suggested fix:** Update ADR back-references in docstrings and comments across the Python and Haskell source files to use the full filename slug of the corresponding ADR.
3. [severity: high | effort: medium | slp(s): continuous-delivery] No automated CI gating path (e.g., GitHub Actions) is configured to enforce test, lint, and type-check invariants on pull requests.
   - **Suggested fix:** Implement a GitHub Actions workflow that executes `mise run setup`, `mise run lint`, `mise run typecheck`, and `mise run test` on every PR and push to main. Configure branch protection to require these checks before merging.
4. [severity: high | effort: medium | slp(s): configuration] Lack of a central typed configuration registry. Operational parameters (cost caps, retry budgets, circuit breakers) are scattered across class constructors and hardcoded defaults rather than being consolidated into a single, typed source of truth.
   - **Suggested fix:** Introduce a central Settings class (e.g., using Pydantic Settings) to define, type, and document all configuration variables in one place.
5. [severity: medium | effort: small | slp(s): configuration] Hardcoded 'magic numbers' in production logic: COST_CAP_WARNING_FRACTION and DEFAULT_RETRY_BACKOFF_SECONDS are defined as module-level constants.
   - **Suggested fix:** Lift these constants into the central configuration registry so they can be tuned per-environment without code changes.
6. [severity: high | effort: small | slp(s): developer-experience] The project requires provider API keys (GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY) for acceptance tests and real trials, but these are not documented in README.md nor provided in a .env.example template.
   - **Suggested fix:** Create a .env.example file at the repository root and document the required environment variables in the README.md "Tooling" or "Getting Started" section.
7. [severity: medium | effort: medium | slp(s): configuration] Absence of startup configuration validation. The system does not verify that required environment variables (like API keys) or configuration values are present and valid before beginning execution.
   - **Suggested fix:** Implement a validation step at application startup that checks the configuration registry and aborts with a clear error if required values are missing or malformed.
8. [severity: medium | effort: medium | slp(s): software-complexity] `OptimizerDriver.run` recomputes the entire Pareto frontier (O(N^2)) for all trials in every iteration of its main loop. As the trial budget (N) grows, this quadratic recomputation will dominate execution time.
   - **Suggested fix:** Implement an incremental Pareto frontier update algorithm or defer frontier recomputation to the end of the run, saving intermediate frontier IDs only if they are needed for real-time reporting.
9. [severity: medium | effort: medium | slp(s): dry] Duplicate Pareto frontier logic (cross-language): 3D dominance rules are implemented identically in Haskell (AgentSpace.hs) and Python (pareto.py).
   - **Suggested fix:** Designate one implementation as canonical or use a single source of truth to generate or verify both implementations.
10. [severity: medium | effort: medium | slp(s): dry] Manual dataclass reconstruction in PerTrialDirectoryAdapter.load_trials duplicates knowledge of field names and types for 5 domain objects.
   - **Suggested fix:** Use a serialization library or implement from_dict class methods on the dataclasses to handle dictionary-to-object mapping.
11. [severity: medium | effort: small | slp(s): dry] Duplicated event stream parsing: logic to filter for assistant 'message_end' events is repeated in synthetic_suite_scorer.py and trial_runner.py.
   - **Suggested fix:** Provide a shared helper in domain/types.py to extract specific event types from a Pi telemetry stream.
12. [severity: medium | effort: small | slp(s): dry] Configuration drift risk for retry_budget: the parameter is declared in OptimizerDriver but not passed to the adapter that actually enforces it.
   - **Suggested fix:** Pass the retry_budget from the OptimizerDriver through the orchestrator to the CliSubprocessAdapter.
13. [severity: medium | effort: small | slp(s): developer-experience] The root 'mise run setup' command is incomplete: it only triggers Python setup. The Haskell project lacks a setup task and is omitted from the root onboarding path, creating friction for contributors needing the full stack.
   - **Suggested fix:** Add a 'setup' task to haskell/mise.toml and update the root mise.toml 'setup' task to depend on both setup-python and setup-haskell.
14. [severity: high | effort: medium | slp(s): documentation] Placeholder text found in 'CLAUDE.md' (e.g., '_Add your build and test commands here_') and 'docs/guides/*/README.md' which are essentially empty templates.
   - **Suggested fix:** Remove placeholder sections from 'CLAUDE.md' or fill them with actual project context. Replace empty guide READMEs with 'Coming soon' notes pointing to the implementation plan, or remove them until they contain content.
15. [severity: medium | effort: small | slp(s): environments] The 'pi' agent binary, central to the project's execution, is not pinned in mise.toml or any declarative manifest.
   - **Suggested fix:** Pin the 'pi' binary version in mise.toml (e.g., using an npm or generic-binary provider) to eliminate tribal knowledge during onboarding and ensure version parity.
16. [severity: medium | effort: medium | slp(s): environments] Lack of full environment containerization (no Dockerfile or devcontainer).
   - **Suggested fix:** Implement a Dockerfile and devcontainer configuration to provide a bit-identical development and execution substrate, as recommended by SLP Principle 4.
17. [severity: medium | effort: medium | slp(s): continuous-delivery] DORA metrics (Lead Time, Deployment Frequency, Change Failure Rate, MTTR) are not measured or visible to the team.
   - **Suggested fix:** Establish a baseline for DORA metrics by tracking deployment events (e.g., successful `mise run build` or tagged releases) and MTTR via issue resolution times. Surface these in a shared dashboard or weekly report.
18. [severity: medium | effort: medium | slp(s): continuous-delivery] The project lacks a 'build once, promote many' artifact pipeline. It is currently run directly from source, which risks environment drift.
   - **Suggested fix:** Define a canonical build artifact (e.g., a Docker image or Python wheel) produced by CI that is used for all downstream evaluation and deployment stages without being rebuilt.
19. [severity: medium | effort: small | slp(s): dependencies] Floating tool versions in 'mise.toml'. Multiple tools (claude, pandoc, weasyprint, beads) and development tools (ruff, ty, uv) are referenced as 'latest' rather than pinned to an immutable version or content digest, breaking build reproducibility (Principle 3).
   - **Suggested fix:** Pin all tools in 'mise.toml' and 'python/mise.toml' to specific versions or content digests to ensure a deterministic environment across different machines and time.
20. [severity: medium | effort: medium | slp(s): continuous-delivery] No automated or documented rollback mechanism exists for the evaluator system.
   - **Suggested fix:** Create a scripted 'one-step' rollback procedure (e.g., a `mise run rollback` command) that reverts the system to the previously known-good version and exercises it in a game-day drill.
21. [severity: medium | effort: medium | slp(s): continuous-delivery] Deployment credentials (API keys) are likely handled as long-lived environment variables without automated rotation or OIDC scoping.
   - **Suggested fix:** Transition to short-lived, scoped credentials using OIDC federation (e.g., GitHub Actions OIDC to cloud providers) or a secret management service with automated rotation.
22. [severity: high | effort: small | slp(s): error-handling] CliSubprocessAdapter implements a retry backoff schedule `(30.0, 60.0)` without jitter. This risks thundering-herd synchronization if multiple evaluators encounter transient upstream errors simultaneously.
   - **Suggested fix:** Add jitter to the backoff duration in the retry loop (e.g., `sleep_time = backoff * random.uniform(0.5, 1.5)`).
23. [severity: high | effort: medium | slp(s): error-handling] CliSubprocessAdapter.run retries the subprocess execution against the *same materialized workspace*. Since the agent run may have mutated the workspace before failing, the retry will run in a corrupted/dirty state.
   - **Suggested fix:** Move `materialize_workspace(workspace)` inside the retry loop so each attempt runs against a pristine copy.
24. [severity: medium | effort: small | slp(s): error-handling] GraduatedProblemSetAdapter and PerTrialDirectoryAdapter call `json.loads` on files without catching `JSONDecodeError`. A malformed file will crash the entire load process.
   - **Suggested fix:** Wrap `json.loads` in a try/except block to catch `JSONDecodeError`, and either skip the corrupted entry with a warning or propagate a typed domain error.
25. [severity: medium | effort: small | slp(s): purpose-and-scope] The project lacks an explicit "Non-goals" section in the root README or a dedicated purpose document. While "deferred" items are listed in the implementation plan, there is no statement of what the project deliberately refuses to do (e.g., "We do not aim to be a general-purpose agent framework," or "We do not support non-Pi harnesses in v1").
   - **Suggested fix:** Add a "Non-goals" subsection to the root README.md or a new PURPOSE.md. Enumerate at least three explicit non-goals to prevent future scope creep and align contributor expectations (e.g., no live-traffic production orchestration in v1, no support for non-hexagonal adapters, no built-in GUI).
26. [severity: medium | effort: small | slp(s): purpose-and-scope] The project demonstrates high discipline in capturing scope changes and architectural shifts via ADRs (e.g., ADR 0005 for cost axes, ADR 0007 for lifecycle). This ensures that every expansion of the project's scope is documented with rationale and consequences, preventing "smuggled" scope creep.
   - **Suggested fix:** Continue this practice and ensure that future phase-driven scope expansions (like Phase 6's surrogate modeling) continue to be preceded by an ADR or a design-notes update.
27. [severity: medium | effort: small | slp(s): dependencies] Missing declared license posture and audit gate. The project lacks a 'LICENSES.md' or equivalent document, and there is no CI gate ensuring that newly added dependencies comply with an allowlist (Principle 8).
   - **Suggested fix:** Document the project's license policy in 'LICENSES.md' and add a license audit step (e.g., 'pip-licenses' or 'cargo-deny' equivalent) to the CI pipeline.
28. [severity: medium | effort: medium | slp(s): documentation] Lack of automated documentation generation and drift checks. The project has rich docstrings and ADRs but no pipeline to render them into a searchable documentation site or verify in CI that the documentation remains in sync with the code.
   - **Suggested fix:** Set up a documentation generator (e.g., MkDocs with mkdocstrings) and add a CI job to verify that documentation builds without errors and stays current with the source.
29. [severity: high | effort: small | slp(s): versioning] The project does not declare a versioning scheme in README.md or docs/. Consumers cannot distinguish whether MAJOR.MINOR.PATCH increments follow Semantic Versioning, Calendar Versioning, or a custom stability contract.
   - **Suggested fix:** Add a 'Versioning' section to the root README.md declaring the project's adherence to Semantic Versioning 2.0.0 (or ZeroVer if stability is not yet promised).
30. [severity: high | effort: medium | slp(s): versioning] There is no CHANGELOG.md or equivalent to track user-visible changes across releases. While Phase 3 closeout is mentioned in README.md, there is no structured history for consumers to audit features, fixes, or breaking changes.
   - **Suggested fix:** Create a root CHANGELOG.md following the 'Keep a Changelog' format and back-populate it from recent git tags and the implementation plan phases.
31. [severity: medium | effort: medium | slp(s): versioning] Manifest versions have drifted in formatting: python/pyproject.toml uses '0.1.0' while haskell/pi-agent-space.cabal uses '0.1.0.0'. There is no automated mechanism to keep these in sync during a version bump.
   - **Suggested fix:** Standardize version formats across all manifest files and implement a 'mise' task (e.g., 'mise run bump') that updates all versions in lockstep using a single source of truth.
32. [severity: medium | effort: medium | slp(s): versioning] The release process is undocumented and lacks a defined gate. There is no guidance on how a commit on main becomes a released version, or what CI/manual checks must pass before tagging.
   - **Suggested fix:** Document the release flow in CLAUDE.md or a new RELEASE.md, defining the branch strategy (e.g., trunk-based with tags), the version-bump location, and the mandatory quality gates (tests, lints) that must pass before a release is cut.
33. [severity: high | effort: small | slp(s): testing] Missing test coverage measurement and gating in the Python project.
   - **Suggested fix:** Add 'pytest-cov' to dev dependencies in 'python/pyproject.toml' and update the 'test-python' task in 'mise.toml' to include coverage reporting and a failure threshold (e.g., --cov-fail-under=90).
34. [severity: medium | effort: medium | slp(s): testing] Haskell modeling DSL has relatively low test coverage (19 examples) compared to the core Python implementation.
   - **Suggested fix:** Expand the Haskell test suite in 'haskell/test/AgentSpaceSpec.hs' to cover more edge cases in the Pareto and Bayesian optimization stubs.
35. [severity: high | effort: medium | slp(s): types] Untyped event boundaries in Python (RawTelemetry.events and TrialEvent.payload).
   - **Suggested fix:** Refine the raw `list[dict]` and `dict` types into sealed unions of Dataclasses or TypedDicts. Parse and validate the Pi JSON stream into these typed shapes at the boundary (CliSubprocessAdapter) using a library like Pydantic or a manual parser that returns a Union of types. This prevents downstream logic from relying on unsafe `.get()` calls on raw dictionaries.
36. [severity: high | effort: small | slp(s): types] Python codebase lacks a project-wide strict type-checking configuration.
   - **Suggested fix:** Adopt Pyright in strict mode (or Mypy in strict mode) by adding a `[tool.pyright]` or `[tool.mypy]` section to `pyproject.toml`. Enforce this check in CI to prevent type regressions. Currently, the project only uses Ruff for linting, which does not provide static type analysis.
37. [severity: medium | effort: medium | slp(s): types] Primitive obsession for domain identifiers and quantities (trial_id, model, tokens, dollars).
   - **Suggested fix:** Wrap domain primitives in refined types using `NewType` in Python (e.g., `TrialId = NewType('TrialId', str)`) and `newtype` in Haskell (e.g., `newtype Prompt = Prompt String`). This prevents silent argument-swapping and documents intent in function signatures like `finalize_trial(trial_id, metrics, outcome)`.
38. [severity: medium | effort: medium | slp(s): types] Representation of Trial lifecycle allows illegal states (Optional Metrics/Outcome).
   - **Suggested fix:** Refactor the `Trial` class to use a sum type (Union of dataclasses) representing its lifecycle states (e.g., `ConfiguredTrial`, `EvaluatedTrial`, `FinalizedTrial`). This mirrors the Haskell `Outcome` model and ensures that `final_metrics` and `outcome` are only accessible when the trial is in the appropriate state, eliminating `None` checks.
39. [severity: high | effort: medium | slp(s): types] Parallel type definition drift for template values between Package and SlotSpace.
   - **Suggested fix:** Align the types for `template_values` to use a single source of truth. `Package` uses `dict[str, str]` while `SlotSpace` uses `Mapping[str, str]`. Use `Mapping` for read-only usage to allow wider compatibility.
40. [severity: medium | effort: medium | slp(s): logging] The cost cap warning in `optimizer_driver.py` uses unstructured string interpolation (`logger.warning("Per-run cost cap warning: cumulative=$%.4f...")`) rather than structured event fields, making it difficult to query or aggregate.
   - **Suggested fix:** Convert the warning to a structured log line (e.g., `logger.warning("per_run_cost_cap_warning", cumulative_cost=cumulative, cap_usd=self._per_run_cost_cap_usd)`).
41. [severity: high | effort: medium | slp(s): security] CliSubprocessAdapter._run_validation_step in python/src/pi_evaluator/adapters/cli_subprocess_adapter.py uses shell=True with user-provided commands, creating a shell injection vulnerability.
   - **Suggested fix:** Refactor validation steps to use argument lists and shell=False, or strictly validate command strings against an allowlist.
42. [severity: medium | effort: small | slp(s): security] Trial event logs (events.jsonl) persist raw telemetry including stderr and malformed lines which may contain sensitive data or API keys without redaction.
   - **Suggested fix:** Introduce a redaction layer in the persistence adapter to sanitize logs before they are written to disk.
43. [severity: high | effort: medium | slp(s): dependencies] Missing automated dependency audit gate in CI. No evidence of a CI pipeline (e.g., GitHub Actions) performing advisory-database scans (e.g., pip-audit) against the resolved dependency tree (Principle 5).
   - **Suggested fix:** Implement a CI workflow that runs dependency audit tools on every PR to surface known vulnerabilities before they land.

## Promoted for human review

1. [severity: critical | effort: large | slp(s): types] Haskell placeholder data types in Ports.hs provide no structural verification.
   - **Promotion rationale:** large effort, scope decision needed
   - **Suggested fix:** Define the record structures for `Package`, `RawTelemetry`, etc., in Haskell to provide actual type safety for the `runTrial` signature. Currently, these are empty declarations that only allow the code to compile without enforcing any invariants.
2. [severity: critical | effort: large | slp(s): security] Agents are not isolated; they run as the same user and on the same host as the evaluator, with full access to the filesystem beyond the temporary workspace copy (Principle 10).
   - **Promotion rationale:** large effort, scope decision needed
   - **Suggested fix:** Implement containerized or sandboxed execution for agents (e.g., using Docker or gVisor) to enforce strong boundaries.

## Low-priority and info-only items

1. `SlotSpace.iter_packages` uses a quadruple nested loop to generate the Cartesian product of slots, leading to high cognitive complexity a... [low | software-complexity]
2. `RandomFromSlotSpace.propose` exhaustively enumerates the `SlotSpace` into a list to pick one random unseen package. This is inefficient... [low | software-complexity]
3. The `OptimizerDriver` constructor includes a `replicates` parameter that explicitly raises `NotImplementedError` for values other than 1,... [info | software-complexity]
4. ~~`_has_model_error` and `_is_retryable_error` have high cognitive complexity (nesting depth of 4-5) due to multiple conditional checks wit...~~ **Resolved by Step 3.5.1 (commit `2611d45`)** — the two predicates were unified into `pi_evaluator.lifecycle.is_model_error`. [low | software-complexity]
5. Duplicate timeout logic in .beads/hooks/ files: '_bd_timeout=${BEADS_HOOK_TIMEOUT:-300}' is repeated across 5 shell scripts. [low | dry]
6. Duplicate test data construction: baseline objects for EvalSuiteRef and VersionVector are manually constructed in three different test fi... [low | dry]
7. Duplicated package identity calculation in test_acceptance_phase3.py manually reconstructs package signatures instead of using candidate_... [low | dry]
8. The 'docs:build' task in the root mise.toml contains multi-line shell logic for PDF generation. This logic is untestable and duplicated i... [low | developer-experience]
9. `OptimizerResult.halted_reason` is typed as `str` with a comment listing valid values, whereas `Outcome` correctly uses `Literal`. This f... [low | error-handling]
10. The primary purpose statement in README.md and ARCHITECTURE.md is heavily technical (focusing on "Bayesian combinatorial-optimization") a... [low | purpose-and-scope]
11. Missing Haskell lockfile. The 'haskell/' directory lacks a 'cabal.project.freeze' file, meaning dependency resolution for the modeling to... [low | dependencies]
12. Missing dependency quarantine/cooldown mechanism. There is no configuration for a dependency update bot (e.g., Renovate) with a 'minimumR... [low | dependencies]
13. Missing or empty component READMEs. 'python/README.md' is empty and there is no 'haskell/README.md', which makes it harder for contributo... [low | documentation]
14. The project does not explicitly classify its public vs. internal surface. While hexagonal architecture (ports/adapters) provides structur... [low | versioning]
15. Conventional commits are used in practice but not enforced via automation. This prevents the adoption of automated changelog generation a... [low | versioning]
