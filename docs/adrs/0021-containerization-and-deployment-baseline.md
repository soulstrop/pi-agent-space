# Title: 0021 - Containerization and Deployment Baseline

**Status:** Accepted

*Accepted 2026-06-07. Closes spike S006 and issue `pi-agent-space-09c`. Settles
the container posture the torch-framework ADR (0016) deferred.*

## Context

ADR 0016 chose BoTorch/torch for the surrogate and noted the choice "directly
determines the containerization baseline … which is an open question we
deliberately deferred." Spike S006 is that question: **what runtime/build
container posture does v1 ship?**

For *this* codebase the question is unusually loaded, because the security work
already shipped is exactly what fights naive containerization:

- **bwrap needs user namespaces** (ADR 0009). Running the agent sandbox *inside*
  a container requires nested userns — `--privileged` or bespoke
  `--security-opt`, the same friction ADR 0009 documents on bare Ubuntu 24.04.
- **`systemd-run --user` needs a user systemd manager** (ADR 0020 D2). Containers
  don't run one, so the D2 resource caps would silently degrade to unenforced
  unless replaced by container-level `--memory`/`--pids-limit`.

So "containerize the codebase" forks by *purpose*. This ADR draws the line at
the purpose that is in v1 scope per the implementation plan ("runtime container
baseline … distinct from the stronger workspace-isolation containers still
deferred"): a **reproducible environment for the Python canonical source of
truth**, not a per-trial isolation mechanism.

## Decision

### D1 — The image is a Python-only CI/dev base, not a trial runtime

The image carries the pinned toolchain + dependencies and runs **lint +
typecheck + the unit suite**. It deliberately does **not** run real-`pi` trials.
Those stay on the operator's host, where bwrap userns and `systemd-run --user`
caps work. Per-trial container isolation (ADR 0009 Option 5 — `docker run` per
trial) stays the **deferred** item it already is in the v1 "what's deferred"
list; this ADR does not promote it. The bwrap integration tests skip cleanly in
the image (no userns) — expected, not a regression.

This sidesteps the nested-bwrap and no-systemd problems entirely rather than
solving them prematurely for a scenario (multi-tenant / runs-leave-the-host)
that is itself out of v1 scope (ADR 0020).

### D2 — CPU-only torch is realized in `uv.lock`

ADR 0016 accepted "CPU-only torch, no CUDA, for v1," but `uv.lock` still
resolved torch with the full CUDA stack on Linux (37 `nvidia-*` packages +
triton, multi-GB). v1 makes the lock match the decision: torch is pinned to
PyTorch's CPU wheel index (`[[tool.uv.index]]` + `[tool.uv.sources]`), and is
listed as an explicit direct dependency so uv honors the source pin. The result
is `torch==2.12.0+cpu`; the nvidia/triton packages drop; the image is ~1.5 GB
instead of 4–6 GB. dev, CI, and the image now agree, so `uv sync --frozen`
stays honest everywhere. GPU is not foreclosed — a future campaign re-locks
against a CUDA index with no code change (ADR 0016 Reconsider Trigger).

### D3 — Reproducibility is a two-lock split: `mise.lock` + `uv.lock`

The **toolchain** (python, uv, ruff, ty) is pinned in `mise.lock` with
per-platform checksums and GitHub build attestations (`mise lock`, 7 platforms);
the **Python dependencies** are pinned in `uv.lock`. The image provisions tools
via mise (from `mise.lock`) and dependencies via uv (`uv sync --frozen` from
`uv.lock`), with uv resolving against the mise-provided interpreter rather than
fetching its own. This closes the CI-toolchain slice of supply-chain pinning
(`pi-agent-space-1hj`); the root doc-tool toolchain, the `pi` binary
(`evf`), the license gate (`xu4`), and the CI advisory scan / runner (`51d`)
remain their own issues.

### D4 — Podman-first, OCI-standard

The artifacts target **Podman** (rootless, daemonless — aligned with the
project's security ethos and with the nested-userns story should trials ever
move inside). The `Containerfile` is OCI-standard and builds unchanged under
Docker; the `mise` tasks take `ENGINE=docker` to switch.

## Reconsider Triggers

- **Trials must run inside the container** (a hosted runner that executes
  real-`pi`, a multi-tenant deployment). This re-opens the nested-bwrap question
  (userns under `--privileged`/`--security-opt`) and requires replacing the
  `systemd-run` caps with container cgroup limits (`--memory`/`--pids-limit`) —
  i.e. promoting the ADR 0009 container-isolation item out of "deferred."
- **A GPU campaign is justified.** Re-lock torch against a CUDA index; the image
  baseline grows accordingly (ADR 0016 trigger).
- **The torch footprint blocks a target** where ~1.5 GB is disqualifying.
  Revisit the pure-numpy/scipy GP (ADR 0016 trigger), accepting the
  EHVI-correctness burden for a lighter image.
- **Haskell needs CI coverage.** This image is Python-only (the canonical source
  of truth); the Haskell precursor gets a separate image/job rather than
  bloating this one with GHC.

## Consequences

- **New artifacts:** `Containerfile`, `.containerignore`, and the `mise` tasks
  `container-build` / `container-test`. The image mirrors the repo layout
  (`/app/python` + `/app/graduated_problems`) so the eval suite's
  `REPO_ROOT = python/..` data resolution holds inside the container.
- **`uv.lock` changed** (CPU torch) and `pyproject.toml` gained the `pytorch-cpu`
  index, the `torch` source pin, and an explicit `torch` dependency. Anyone who
  `uv sync`s now gets CPU torch — the intended v1 state.
- **`python/mise.toml` is pinned** (no more `latest`) and **`python/mise.lock`**
  is added as the toolchain reproducibility substrate.
- **`51d` (the CI runner) is the natural next consumer** of this image — a
  GitHub Actions job that runs `mise run container-test`, or runs the loop
  directly in the image.
- **Doc-sync:** `docs/threat-model.md` A6 (supply chain) reflects the pinned
  toolchain and CPU-torch lock.

## Related

- [ADR 0016 — Surrogate Modeling Framework](0016-surrogate-modeling-framework.md):
  deferred this decision and set the "CPU-only torch, no CUDA, for v1" baseline
  that D2 finally realizes in the lockfile.
- [ADR 0009 — Trial Isolation Boundary](0009-trial-isolation-boundary.md): why
  trials stay on the host (bwrap userns); container-per-trial isolation (its
  Option 5) stays deferred.
- [ADR 0020 — v1 Security Scope](0020-v1-security-scope-and-threat-model.md): the
  D2 `systemd-run` resource caps that do not function inside a container, part of
  why D1 keeps trials on the host.
- `docs/threat-model.md` A6 — supply chain (toolchain pinning, CPU-torch lock).
- Issues: `09c` (this image), `1hj`/`evf`/`xu4`/`51d` (supply-chain remainder).
- Spike **S006** in `docs/implementation-plan.md` — closed by this ADR.
