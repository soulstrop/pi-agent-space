# User Journeys

This document describes the three deployment scenarios pi-agent-space is designed to serve, told from the perspective of the people who use the system. The scenarios share core mechanics — trial = (package, eval suite); Bayesian optimization loop; Pareto frontier over a capability profile; persistent trial history — but differ in operational shape, sample size, signal sources, and budget profile.

**Why this exists.** The agent ecosystem changes continuously: new frontier models ship every few weeks, new prompt-engineering techniques spread overnight, new skills and MCP servers get published, Pi itself evolves. Without principled help, an individual (or an organization) facing this churn either adopts changes essentially at random — chasing whichever was loudest this week — or freezes on a current setup and watches its relative quality decay against the moving frontier. pi-agent-space exists to replace random adoption with directed experimentation: telling someone whether a specific candidate change is actually an improvement for *their* work and accumulating that knowledge across trials. The **individual user** scenario is the project's primary motivating use case; the enterprise and R&D scenarios are how the same machinery scales up.

**v1 scope.** The v1 production target is the **R&D synthetic** journey, because it is the most controllable end-to-end exercise of the optimization loop (no live-user dependency, no fleet telemetry). The **individual** and **enterprise A/B** journeys land as future adapters behind the existing ports (`AgentHarnessPort`, the persistence layer, the eval-suite source); the abstractions are chosen so that the same optimizer code serves all three.

---

## 1. Individual user — guided refinement of a personal setup

### Persona
Maya is a developer who uses Pi for day-to-day coding work. The agent ecosystem around her changes constantly: a new frontier model drops every few weeks, a new prompt-engineering technique goes viral, a new skill or MCP server gets published, Pi itself ships updates. Without help, she either adopts changes essentially at random — chasing whichever option was loudest this week — or freezes on her current setup and watches its relative quality decay against the moving frontier. She wants a principled way to answer "should I adopt this?" against her own work, not against someone else's benchmark.

### Setup (one-time)
1. **Formalize the current package.** Maya translates her existing config into a `package.json` covering system prompt, model identifier, tool selection, skill list, and template values. This becomes her baseline.
2. **Declare a personal eval suite.** She picks 5–20 representative past tasks (small bug fixes, refactors, feature stubs) and writes them as `GraduatedProblem` entries with approximate difficulty tags.
3. **Enable subjective scoring.** Objective metrics flow automatically; Maya will rate outputs after she has actually used them. With small N, her subjective signal is load-bearing.

### Trial cycle (cadence: a few per week)
The trigger is usually external: Maya hears about a new model, prompt template, skill, or MCP server and wants to know if adopting it is actually an improvement for *her* work.

1. Maya registers the candidate change as a variant — swap a model, replace a prompt block, add a skill, change a template value — defined as a delta from her current baseline.
2. The variant runs against her eval suite, or sidecars her next real task. Objective metrics flow back automatically.
3. Maya optionally adds a subjective score after using the result. The trial closes; the next round can proceed before the subjective score arrives, with the subjective signal retroactively updating the surrogate when it does.
4. The optimizer reports whether the variant Pareto-dominates her baseline. If she has no pending external candidate, the optimizer proposes its own next experiment from accumulated history.

### What Maya gets back
- A clear **adopt-or-reject signal** per evaluated change, framed in terms of her own capability profile — e.g., *"`gemini-flash` reduced mean tokens by 18% with no quality regression at difficulty ≤ 3, but the scaling slope worsened: it gets disproportionately expensive on difficulty-4+ tasks. Recommendation: adopt for routine work, keep `claude-sonnet-4-6` available for hard tasks."*
- A persistent record of every change she has evaluated and rejected — so when the same option resurfaces in another blog post, she doesn't re-evaluate it from scratch.
- An accumulating picture of *which kinds of changes* tend to help her work and which don't, useful for triage when the next wave of new options arrives.

### Operational characteristics
- **Sample size:** tens of trials over weeks.
- **Information per trial:** high; subjective signal carries real weight.
- **Budget shape:** Maya's attention, not compute.
- **Persistence scale:** thousands of trials over the lifetime of the project.

---

## 2. Enterprise A/B — optimization as a side effect of normal operations

### Persona
Acme Corp deploys Pi-based agents across 10,000 developer desks worldwide. They already pay for the model usage; they want optimization signal as a side effect of production use rather than as a separate compute line item.

### Setup (one-time per package)
1. **Lock the production baseline.** The current package becomes the control variant.
2. **Declare candidate variants and segmentation.** A platform team specifies which package variants are eligible for fleet rollout and which segments of the fleet receive each variant (random subsets, regional slices, role-based cohorts).
3. **Wire passive telemetry.** Each desk's Pi session emits trial events into a shared event stream. Privacy filters scrub task content according to policy. Subjective scoring is opt-in via a thumbs-up/down surface; most trials carry only objective scores.
4. **Define the "eval suite" as the observed task distribution.** Unlike R&D's synthetic suite, here the eval suite *is the work people are doing*. Per-trial capability profiles aggregate per-task metrics across whatever tasks fall into each desk's variant assignment.

### Trial cycle (cadence: continuous)
1. Variants ship to their fleet subsets; users do their normal work.
2. Telemetry accumulates asynchronously. Subjective ratings trickle in for a small fraction of trials.
3. The optimizer runs Pareto analysis on a periodic cadence (daily, weekly), comparing variants by aggregated capability profiles segmented by task type, role, and region.
4. Variants that lose decisively are retired from rotation; promising variants have their fleet share expanded; new variants enter rotation based on the optimizer's recommendation.

### What the platform team gets back
- Continuous Pareto-frontier reports across in-production variants, with segmentation breakdowns (*"Variant 3 dominates for backend tasks but loses for data-science notebooks"*).
- Predicted-improvement and required-fleet-share-for-confidence estimates for the next proposed variant.

### Operational characteristics
- **Sample size:** millions of trials per quarter.
- **Information per trial:** low; real-world task variation contributes large noise.
- **Subjective signal:** sparse; objective metrics dominate.
- **Budget shape:** zero marginal — optimization piggybacks on production usage.
- **Persistence scale:** millions of trials; warrants a SQL-backed adapter (ADR 0003's reconsider trigger).
- **Constraints:** privacy filtering, reliability SLOs, zero extra latency on the user-visible path.

---

## 3. R&D synthetic — systematic exploration of the configuration space

### Persona
A research-engineering team at a software vendor wants to map the configuration space for a specific problem domain (initially software engineering; later domains such as insurance contract drafting) and identify Pareto-optimal packages within a fixed compute budget.

### Setup (one-time per domain)
1. **Build a synthetic eval suite.** A graduated problem set with explicit difficulty levels, deterministic validation methods, and tags for any required template variables (e.g., `language: python`).
2. **Declare the slot/value space.** Which models populate the model slot, which system-prompt variants are in scope, which tool subsets, which skill bundles, which template values, and so on.
3. **Allocate the compute budget.** A trial budget (e.g., 5,000 trials over two weeks) is fixed up front; the optimizer's job is to spend it informatively.

### Trial cycle (cadence: many per hour, parallelizable)
1. The optimizer proposes the next configuration from accumulated history — initially via a space-filling design (random or Latin hypercube), later via the surrogate model.
2. The configuration materializes into a Pi runtime and runs against every problem in the eval suite. A capability profile (per-difficulty metric vector) is recorded as event-stream entries.
3. Objective scoring runs automatically — tokens, runtime, static-analysis quality, validation pass rate. Subjective scoring is optional and applied selectively, typically only to Pareto-frontier finalists.
4. The optimizer updates its surrogate and proposes the next configuration.

### What the research team gets back
- A Pareto frontier in `(mean_cost, scaling_slope, mean_quality)` over the explored slot/value space, with the scaling slope making "cheap-then-explodes" packages distinguishable from "uniformly moderate" ones.
- A prioritized list of unexplored regions worth probing next.
- A record of how the frontier evolved over the budget — useful for understanding which slots drove the trade-offs and where further exploration would pay off.

### Operational characteristics
- **Sample size:** thousands to tens of thousands; controlled.
- **Information per trial:** moderate — synthetic problems have lower signal than real-world tasks but are repeatable.
- **Subjective signal:** occasional and selective.
- **Budget shape:** explicit compute budget; high parallelism feasible.
- **Persistence scale:** tens of thousands of trials; comfortable within v1's per-trial-directory layout (ADR 0003).
- **Constraints:** synthetic only — no live user signal, no production deployment dependencies.

---

## Cross-cutting structure

All three journeys instantiate the same conceptual machinery:

- A **package** plugs into Pi's extension surface — skills, prompts, workflows, foundation models, configuration values, and template values.
- An **eval suite** defines the validation context: synthetic graduated problems for R&D; a curated task set for the individual; the observed task distribution for the enterprise.
- A **trial** is an event stream — `configuration → evaluation → objective scoring → subjective scoring → final` — whose phases may complete asynchronously and whose downstream consumers tolerate partial scoring.
- A **Bayesian optimization loop** ingests trial history, fits a surrogate model over the configuration space, and proposes the next experiment subject to the deployment scenario's budget shape.
- A **Pareto frontier** over a capability-profile-derived metric vector (`mean_cost`, `scaling_slope`, `mean_quality` at minimum) is the primary output surface for decision-making.

The three journeys differ along three axes, each expressed as a port-and-adapter boundary in the implementation:

| Axis | Individual | Enterprise A/B | R&D synthetic |
| --- | --- | --- | --- |
| Agent harness adapter | live-session sidecar | fleet telemetry consumer | spawned subprocess |
| Persistence adapter | jsonl per trial | SQL / columnar | jsonl per trial |
| Eval-suite source | curated past tasks | observed task stream | synthetic problem set |
| Subjective scoring weight | dominant | sparse opt-in | occasional / selective |
| Sample size | tens | millions | thousands–tens of thousands |
| Budget shape | user attention | zero marginal compute | explicit compute budget |

Keeping these distinctions on the *adapter* side — not in the core optimizer, persistence schema, or trial model — is what lets the same v1 codebase grow into all three deployments over time without rework of the core.

**A note on subjective signal.** Across all three scenarios, the human-in-the-loop subjective signal is produced by individuals evaluating outputs against their own real work. The enterprise case is structurally many-individuals-embedded-in-a-fleet — the same signal source at sparser per-person density. R&D synthetic mode is the outlier: it largely lacks a natural subjective-signal source, since there is no end-user generating organic feedback. Its subjective scoring requires researchers tasting outputs and is therefore occasional and selective. This is another reason the individual scenario is load-bearing: it is where the richest form of the signal that fuels the optimization loop actually lives. The individual user is simultaneously the consumer of recommendations and the producer of the signal those recommendations depend on.
