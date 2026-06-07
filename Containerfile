# Containerfile — Python-only CI/dev base image (ADR 0021, spike S006).
#
# A reproducible environment for the Python canonical source of truth: the
# toolchain (python/uv/ruff/ty) comes from python/mise.lock with per-platform
# checksums; the dependencies (CPU-only torch per ADR 0016) come from
# python/uv.lock. It runs lint + typecheck + the unit suite.
#
# It deliberately does NOT run real-pi trials. Those stay on the operator's
# host, where bwrap user namespaces (ADR 0009) and `systemd-run --user`
# resource caps (ADR 0020 D2) work; both fight naive containerization, and
# per-trial container isolation is the ADR 0009 item still deferred from v1.
# The bwrap integration tests skip cleanly here (no userns) — expected.
#
# Build (Podman):  podman build -t pi-agent-space:ci -f Containerfile .
# Run the CI loop: podman run --rm pi-agent-space:ci
#
# Engine: Podman-first (rootless, daemonless), but the file is OCI-standard
# and builds unchanged under Docker.

# Pinned Debian base. Digest-pinning is the reproducibility follow-up (1hj);
# the toolchain and deps above are already checksum-pinned via the lockfiles.
FROM docker.io/library/debian:bookworm-slim AS base

# System libraries: ca-certificates + curl for mise's tool downloads, git for
# uv's VCS metadata, libgomp1 for the torch CPU runtime (OpenMP). xz-utils
# decompresses the python-build-standalone tarballs mise fetches.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libgomp1 \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Pinned mise. Tool versions/checksums live in mise.lock, not here; this pins
# only the resolver itself.
ARG MISE_VERSION=v2026.6.0
ENV MISE_DATA_DIR=/opt/mise/data \
    MISE_CONFIG_DIR=/opt/mise/config \
    MISE_CACHE_DIR=/opt/mise/cache \
    MISE_YES=1
RUN curl -fsSL https://mise.run | MISE_VERSION=${MISE_VERSION} sh \
    && mv /root/.local/bin/mise /usr/local/bin/mise
ENV PATH=/opt/mise/data/shims:$PATH

# Mirror the repo layout: the project lives at /app/python and the eval-suite
# fixtures at /app/graduated_problems, because the suite resolves its data dir
# as python/../graduated_problems (REPO_ROOT = two parents up from a test).
WORKDIR /app/python

# 1) Toolchain from mise.lock (python, uv, ruff, ty) — checksum-verified.
#    Copied first so the toolchain layer caches independently of the deps.
COPY python/mise.toml python/mise.lock ./
RUN mise trust --yes /app/python/mise.toml \
    && mise install \
    && mise reshim

# uv resolves against the mise-provided python rather than fetching its own,
# keeping one source of truth for the interpreter.
ENV UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON=python

# 2) Dependencies from uv.lock (CPU-only torch). Copied before the source so a
#    source change does not bust the dependency layer.
COPY python/pyproject.toml python/uv.lock ./
COPY python/README.md ./README.md
RUN uv sync --frozen --no-install-project

# 3) Project source + tests, plus the eval-suite fixtures the synthetic
#    acceptance tests load from the sibling graduated_problems/ directory.
COPY python/src ./src
COPY python/tests ./tests
COPY python/main.py ./main.py
COPY graduated_problems /app/graduated_problems
RUN uv sync --frozen

# Default: the CI loop via the project's own mise tasks (single source of
# truth — they delegate to `uv run ruff/ty/pytest`). Acceptance tests are
# excluded by pyproject's default -m filter and need real pi anyway.
CMD ["sh", "-c", "mise run lint && mise run typecheck && mise run test"]
