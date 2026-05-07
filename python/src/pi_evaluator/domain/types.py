"""Domain types for pi-agent-space trials.

Value types are frozen dataclasses; ``Trial`` is mutable because events
accrue across phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Package:
    """A user-harness instance plus model selection.

    Per project convention, ``skills`` is an ordered pipeline (not a
    set): rearranging the list represents a semantically different
    package.
    """

    model: str
    system_prompt: str
    skills: list[str]
    template_values: dict[str, str]


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of one ValidationStep run inside a materialized workspace."""

    step_name: str
    exit_code: int
    stdout: str
    stderr: str
    passed: bool


@dataclass(frozen=True)
class RawTelemetry:
    """Raw output from an agent run, before scoring.

    Phase 2 shape: agent event stream + exit code + the per-step
    validation outcomes captured by the harness adapter after the
    agent finishes. ``validation_results`` defaults to an empty list
    so Phase 1 stubs and tests continue to work without explicit
    validation.
    """

    events: list[dict]
    exit_code: int
    validation_results: list[ValidationResult] = field(default_factory=list)


@dataclass(frozen=True)
class Metrics:
    """Objective scoring output (Phase 1 scalar shape).

    Capability-profile / fibered metrics arrive in Phase 4.
    """

    tokens_consumed: int
    validation_pass_rate: float
    quality_score: float


@dataclass(frozen=True)
class SubjectiveScore:
    """Async, partial scoring slot. May be absent on a closed trial."""

    score: float
    notes: str
    scorer: str
    timestamp: str


@dataclass(frozen=True)
class EvalSuiteRef:
    """Lightweight pointer to which eval suite the trial ran against."""

    suite_id: str
    suite_version: str


@dataclass(frozen=True)
class VersionVector:
    """Frozen-at-trial-start version snapshot."""

    pi_version: str
    package_versions: dict[str, str]
    eval_suite_version: str


@dataclass(frozen=True)
class TrialEvent:
    """One event in events.jsonl."""

    phase: str
    timestamp: str
    payload: dict = field(default_factory=dict)


@dataclass
class Trial:
    """In-memory representation of a trial across its lifecycle.

    Mutable: events accrue as phases complete. ``final_metrics`` and
    ``subjective_score`` remain ``None`` until their phases land.
    """

    trial_id: str
    package: Package
    eval_suite_ref: EvalSuiteRef
    version_vector: VersionVector
    events: list[TrialEvent] = field(default_factory=list)
    final_metrics: Metrics | None = None
    subjective_score: SubjectiveScore | None = None
