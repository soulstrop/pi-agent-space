# Title: 0020 - v1 Security Scope and Threat Model

**Status:** Accepted

*Accepted 2026-06-07. Closes spike S008. The living enumeration lives in
[`docs/threat-model.md`](../threat-model.md); this ADR is the decision of
record for what v1 hardens versus defers.*

## Context

ADR 0009 closed the agent-isolation question (bwrap behind `SandboxPort`, the
hard-fail `select_sandbox` posture wired onto the real-`pi` path — issue
`pi-agent-space-j8x`). That settled *one* threat. Spike S008 asks the broader
question: **what is the v1 threat model, and what hardening does it imply** —
across credential handling, persisted data, resource bounds, and the supply
chain — so that "the committed v1 surface" (Phase 7) includes an explicit
security posture rather than an implicit one.

This ADR draws the v1 security line. It inherits ADR 0009's **trust boundary**:
the boundary is the agent's *runtime behavior* — an LLM executing arbitrary
generated code, prompt-injectable through eval content — i.e. *semi-trusted
execution*, **not** an adversary wielding a kernel exploit to escape the
sandbox. The v1 deployment scenario is a **single operator on their own
machine** running synthetic-suite R&D (the three-scenario model's scenario 1).
That scenario is what makes the lighter end of each decision correct; the
enterprise / multi-tenant scenario is the documented reconsider trigger for the
deferred items.

The full asset → threat → mitigation catalog is maintained as a living document
in `docs/threat-model.md`. This ADR records only the **scope decisions** — which
gaps v1 commits to closing and which it consciously defers — so downstream work
has one authoritative cut.

## Threat model (summary)

| Asset | Primary threat | Standing mitigation |
| --- | --- | --- |
| Host credentials (`~/.ssh`, `~/.aws`, `GITHUB_TOKEN`, dotfiles) | Agent reads / exfiltrates | ADR 0009: env allowlist, tmpfs `$HOME`, hard-fail sandbox |
| Model API keys | Logged / persisted / exfiltrated | ADR 0015 MD6-A logging discipline; allowlist-forwarded into the sandbox |
| Measurement integrity | Cross-run contamination | ADR 0009: per-trial workspace + filesystem isolation |
| Host resources | Runaway / fork-bomb agent | ADR 0005/0007 cost + wallclock caps (orchestration layer) |
| On-disk artifacts (`events.jsonl`) | Secrets written to disk | — (gap; see D1) |
| Supply chain (deps, tool/`pi` versions) | Compromised / unpinned dependency | — (delegated; see D3) |

`docs/threat-model.md` carries the per-asset detail, the STRIDE-style threat
enumeration, and the disposition of every gap.

## Decision

### D1 — Persisted-secret redaction is **in v1**

`events.jsonl` persists raw agent telemetry including stderr and malformed
lines, which can contain provider API keys or other secrets the agent printed.
A **redaction layer in the persistence write path** scrubs known secret shapes
(provider key prefixes — `sk-…`, `AIza…` — and `authorization: Bearer …` /
`x-api-key: …` headers) before any line is written to disk. Secrets on disk
outlive the run and leak the moment a run directory is shared (a bug report, a
teammate, a backup), so this is closed in v1 even under the single-operator
scenario. Closes `pi-agent-space-28g`. The redaction is **defence-in-depth**, not
a license to log secrets — call-site discipline (MD6-A) remains the first line.

### D2 — OS-level resource caps are **in v1**

The orchestration-layer cost (ADR 0005) and wallclock (ADR 0007) caps bound the
*common* runaway, but they do not bound CPU, memory, file descriptors, or a
fork-bomb — an agent can exhaust the host between cap checks. v1 wraps the bwrap
invocation in `systemd-run --scope` with `MemoryMax`, `CPUQuota`, and `TasksMax`,
realising **rung 1+** of ADR 0009's isolation ladder. This couples the real-`pi`
path to `systemd` — acceptable because bwrap already makes that path Linux-only,
and the wrap degrades gracefully (absent `systemd-run`, the sandbox runs without
the cgroup scope and logs that the caps are unenforced). The cap *values* are
operator-configurable with conservative defaults.

### D3 — Supply-chain hardening is **enumerated, not owned, by S008**

`docs/threat-model.md` names the supply-chain threats (unpinned tool and `pi`
versions, no dependency-advisory scan, no license allowlist — SLP Principles
3/5/8). The **mitigations are tracked under their existing issues** —
`pi-agent-space-1hj` (pin mise tools), `pi-agent-space-evf` (pin the `pi`
binary), `pi-agent-space-xu4` (license posture + gate), `pi-agent-space-51d`
(CI advisory scan) — and owned by the **Containerization & deployment baseline
(S006)** workstream plus the CI workstream. S008 does not implement them; it
ensures they are visible in the threat model and not silently dropped.

### D4 — Deferred to the enterprise scenario (documented, not v1)

The following are out of v1 scope, recorded in `docs/threat-model.md` with their
trigger and tracking issue:

- **Network egress filtering** — Pi requires network for the model call; an open
  socket is an exfiltration path no lightweight sandbox closes (ADR 0009
  residual). Egress allowlisting to the model endpoint is enterprise-scenario
  work.
- **API-key rotation / OIDC scoping** (`pi-agent-space-622`) — long-lived env-var
  keys are accepted for a single operator; short-lived scoped credentials are an
  enterprise concern.
- **Logging field-allowlist** (`pi-agent-space-0ec`, ADR 0015 MD6-B) — the
  redaction-deny posture for *logs* stays deferred; D1 covers the higher-value
  *persisted-artifact* path.
- **Validation-step sandboxing** (`pi-agent-space-o2t`) — validation tooling runs
  agent-authored workspace content outside the sandbox; deferred per ADR 0009.

### D5 — `docs/threat-model.md` is the living artifact

The threat model is a document that evolves as assets and mitigations change;
this ADR is its decision-of-record snapshot. New assets/threats are added to the
document; a change to a *disposition* (promoting a deferred item into scope) is
an ADR-level decision that supersedes the relevant D-item here.

## Reconsider Triggers

- **Enterprise / multi-tenant deployment scenario activates.** Re-open every D4
  item: egress filtering, key rotation/OIDC, log field-allowlist, validation
  sandboxing all become load-bearing when runs leave the single operator's host.
- **Run directories become shareable artifacts** (a results registry, a hosted
  dashboard). D1 redaction coverage must be re-audited against the *actual*
  telemetry shapes seen in the field, and the deferred log field-allowlist (0ec)
  likely promotes.
- **A non-Pi or non-coding harness is added.** The trust-boundary assumption
  ("we control the harness binary") is re-examined; a harness whose source we do
  not control shifts the agent from semi-trusted toward untrusted and may promote
  the isolation rung (ADR 0009 ladder) past bwrap.
- **The supply chain delegated in D3 stalls.** If S006 / CI do not land the
  pinning + advisory-scan + license gate before the v1 cut, S008's "enumerated"
  posture must be revisited — an unpinned dependency tree is a v1 security gap,
  not merely a reproducibility one.

## Consequences

- **Two v1 implementation commitments** follow from this ADR: the persistence
  redaction layer (D1, closes `28g`) and the `systemd-run` resource-cap wrap
  (D2, ADR 0009 rung 1+ — tracked as a new issue). Both are scoped, testable
  slices.
- **`docs/threat-model.md` is added** as the living security catalog and is
  linked from the operators guide and this ADR. The Doc-Sync gate covers it:
  changes to isolation, redaction, or secret flow update the catalog in the same
  or an immediate sibling commit.
- **The deferred items keep their issues open** with an explicit enterprise-gated
  rationale, so "not in v1" is a recorded decision, not an oversight.
- **Supply-chain hardening stays where it is** (S006 + CI) but is now traceable
  from the threat model, closing the "is anyone tracking this?" question.

## Related

- [ADR 0009 — Trial Isolation Boundary](0009-trial-isolation-boundary.md): the
  isolation half of the threat model; this ADR builds the rest on its trust
  boundary and isolation ladder (D2 realises rung 1+).
- [ADR 0015 — Structured Logging Depth](0015-structured-logging-depth.md): MD6-A
  (call-site discipline, kept) and MD6-B (field-allowlist, deferred — D4).
- `docs/threat-model.md`: the living enumeration this ADR decides the scope of.
- Issues: `28g` (D1), `bm9` (D2 — `systemd-run` resource-cap wrap),
  `1hj`/`evf`/`xu4`/`51d` (D3), `622`/`0ec`/`o2t` (D4).
- Spike **S008** in `docs/implementation-plan.md` — closed by this ADR.
