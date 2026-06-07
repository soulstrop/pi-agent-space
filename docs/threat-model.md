# Threat Model — pi-agent-space (v1)

**Status:** Living document. Scope decisions of record are
[ADR 0020](adrs/0020-v1-security-scope-and-threat-model.md); the isolation
mechanism is [ADR 0009](adrs/0009-trial-isolation-boundary.md).

This document enumerates the assets pi-agent-space handles, the threats against
them, the mitigations in place, and the disposition of each gap (closed in v1,
or deferred with a trigger). It evolves as assets and mitigations change; a
change to a *disposition* is an ADR-level decision (see ADR 0020 D5).

## Scope and trust model

**Deployment scenario (v1):** a single operator running synthetic-suite R&D on
their own machine — scenario 1 of the three-scenario model. The enterprise
A/B and multi-tenant scenarios are explicitly out of v1 scope and are the
reconsider trigger for most deferred items below.

**Trust boundary (inherited from ADR 0009):** the boundary is the *agent's
runtime behavior*, not the harness source. We control the Pi binary, but Pi
drives an LLM that generates and executes arbitrary shell and code against the
workspace. The live adversaries are therefore:

- a **misbehaving / hallucinating LLM** — an unintended `rm -rf $HOME`,
  `curl … | sh`, a backgrounded process; and
- **prompt injection through eval content** — a crafted problem statement or
  fixture file that steers the agent into destruction or exfiltration.

This is **semi-trusted execution**. It is explicitly *not* "untrusted code
actively trying to escape the sandbox via a kernel exploit" — in the
single-operator scenario the operator and the agent are on the same side of the
trust line. That distinction sizes every mitigation: namespace-level I/O
confinement is in scope; hardware-virtualization escape-resistance is not (see
the ADR 0009 isolation ladder).

**Out of scope for this document:** correctness/availability of the optimizer
algorithm itself, model-provider-side security, and physical/host-OS security
below the process boundary.

## Assets

| # | Asset | Where it lives |
| --- | --- | --- |
| A1 | Host credentials — `~/.ssh`, `~/.aws`, `~/.config/gh`, `GITHUB_TOKEN`, dotfiles | Operator's home directory / environment |
| A2 | Model-provider API keys (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) | Operator's environment; forwarded into the agent |
| A3 | Measurement integrity — honest `(package, problem)` capability numbers | Trial workspaces, persisted metrics |
| A4 | Host resources — CPU, memory, file descriptors, process table | The machine running the evaluator |
| A5 | Persisted artifacts — `config.json`, `versions.json`, `events.jsonl`, `final.json` | The run/trial directory tree (ADR 0003) |
| A6 | Supply chain — Python deps, `mise` tool versions, the `pi` binary | Lockfiles, `mise.toml`, the resolved dependency tree |

## Threat catalog

Each row: the threat, its STRIDE-style category, the standing mitigation, and
the v1 disposition. "✅ closed" = mitigated in v1; "🔒 v1" = committed v1 work;
"⏭ deferred" = out of v1 scope with a recorded trigger.

### A1 — Host credentials

| Threat | Category | Mitigation | Disposition |
| --- | --- | --- | --- |
| Agent reads `~/.ssh` / `~/.aws` and exfiltrates | Information disclosure | ADR 0009: real `$HOME` never bind-mounted; tmpfs `$HOME`; the sandbox is hard-fail (`select_sandbox` refuses to run unisolated absent `PI_ALLOW_UNSANDBOXED`) | ✅ closed (when sandboxed) |
| `GITHUB_TOKEN` / `AWS_*` reach the agent via the environment | Information disclosure | ADR 0009 env allowlist forwards only `PATH/LANG/…`, the four model keys, and `PI_*`; everything else is scrubbed | ✅ closed (when sandboxed) |
| Operator runs unsandboxed and exposes all of A1 | Misconfiguration | Hard-fail posture makes unsandboxed runs an explicit, logged `PI_ALLOW_UNSANDBOXED` decision (j8x) | ✅ closed |

### A2 — Model API keys

| Threat | Category | Mitigation | Disposition |
| --- | --- | --- | --- |
| Keys written to logs | Information disclosure | ADR 0015 MD6-A: call sites log identifiers/counts/costs, never raw key material | ✅ closed (by discipline) |
| Keys written to `events.jsonl` via raw stderr / malformed lines | Information disclosure | Redaction layer in the persistence write path (`domain/redaction.py`) scrubs `sk-…`/`AIza…`/`Bearer`/`x-api-key` shapes before every jsonl line is written | ✅ closed (ADR 0020 D1, `28g`) |
| Agent exfiltrates keys over the open network | Information disclosure | None — network is required for the model call (ADR 0009 residual) | ⏭ deferred — egress filtering is enterprise-scenario |
| Long-lived env-var keys, no rotation | Credential management | Accepted for a single operator | ⏭ deferred — rotation/OIDC is enterprise (`622`) |

### A3 — Measurement integrity

| Threat | Category | Mitigation | Disposition |
| --- | --- | --- | --- |
| Agent reads prior trials' workspaces or the eval suite's expected outputs | Tampering / disclosure | ADR 0009: per-trial workspace bind only; other trials' trees not visible | ✅ closed (filesystem side) |
| Cross-run contamination via shared `/tmp` or `$HOME` | Tampering | tmpfs `/tmp` and tmpfs `$HOME` per invocation | ✅ closed |
| Provider-side response caching correlates trials | Tampering | Out of our boundary | ⏭ out of scope (documented in ADR 0009) |

### A4 — Host resources

| Threat | Category | Mitigation | Disposition |
| --- | --- | --- | --- |
| Runaway CPU / memory consumption | Denial of service | ADR 0005 cost cap + ADR 0007 wallclock cap bound the common case | partial |
| Fork-bomb / fd exhaustion between cap checks | Denial of service | `systemd-run --scope` wrap with `MemoryMax`/`CPUQuota`/`TasksMax` | 🔒 v1 (ADR 0020 D2, ADR 0009 rung 1+) |
| Detached process outlives the trial | Denial of service | ADR 0009 `--die-with-parent` terminates sandboxed processes with the adapter | ✅ closed |

### A5 — Persisted artifacts

| Threat | Category | Mitigation | Disposition |
| --- | --- | --- | --- |
| Secrets land in `events.jsonl` and leak when the run dir is shared | Information disclosure | Persistence redaction layer (same as A2) | ✅ closed (ADR 0020 D1, `28g`) |
| Malformed / forward-version files crash the reader | Availability | ADR 0019 tolerant reader + schema-version stamp | ✅ closed |

### A6 — Supply chain

| Threat | Category | Mitigation | Disposition |
| --- | --- | --- | --- |
| Unpinned `mise` tool versions (`latest`) drift or are swapped | Tampering | Pin tools to immutable versions/digests | ⏭ delegated — `1hj` (S006) |
| The `pi` binary is unpinned | Tampering | Pin `pi` in a declarative manifest | ⏭ delegated — `evf` (S006) |
| A dependency ships a known advisory | Elevation / tampering | `pip-audit` advisory scan in CI | ⏭ delegated — `51d` / Principle 5 (CI) |
| A newly added dependency violates the license posture | Compliance | `LICENSES.md` + CI allowlist gate | ⏭ delegated — `xu4` / Principle 8 (S006/CI) |

Supply-chain mitigations are **enumerated here but owned elsewhere** (ADR 0020
D3): the Containerization & deployment baseline (S006) and CI workstreams. They
are listed so the threat model is complete and nothing is silently dropped.

## v1 commitments (this threat model's "must-close" set)

1. ✅ **Persistence-layer secret redaction** — scrub provider-key shapes from
   telemetry before it is written to `events.jsonl`. ADR 0020 D1 · issue `28g`.
   *Done:* `domain/redaction.py` is applied in `PerTrialDirectoryAdapter._append_jsonl`.
2. **OS-level resource caps** — `systemd-run --scope` cgroup wrap around the
   bwrap invocation, degrading gracefully where `systemd-run` is absent. ADR 0020
   D2 · ADR 0009 rung 1+.

Already shipped and counted as standing mitigations: ADR 0009 (isolation,
env allowlist, hard-fail `select_sandbox`), ADR 0015 MD6-A (logging discipline),
ADR 0019 (tolerant reader / schema stamp).

## Deferred (enterprise-scenario gated)

| Item | Trigger to revisit | Issue |
| --- | --- | --- |
| Network egress filtering | Runs leave the single-operator host | — (ADR 0009 residual) |
| API-key rotation / OIDC scoping | Multi-tenant / shared infra | `622` |
| Logging field-allowlist (MD6-B) | Run dirs become shareable artifacts | `0ec` |
| Validation-step sandboxing | Validation taint proves real | `o2t` |

## Maintenance

- Update this catalog in the same or an immediate sibling commit as any change
  to isolation, redaction, secret flow, or the asset set (Doc-Sync gate).
- Promoting a deferred item into scope is an ADR decision that supersedes the
  relevant ADR 0020 D-item — record it there, then reflect the new disposition
  here.
