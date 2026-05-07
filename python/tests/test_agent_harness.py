from pi_evaluator.adapters.stub_agent_harness_adapter import StubAgentHarnessAdapter
from pi_evaluator.domain.test_suite import GraduatedProblem, ValidationStep
from pi_evaluator.domain.types import Package, RawTelemetry
from pi_evaluator.ports.agent_harness_port import AgentHarnessPort


def _pkg() -> Package:
    return Package(
        model="gemini-flash",
        system_prompt="",
        skills=[],
        template_values={},
    )


def _problem() -> GraduatedProblem:
    return GraduatedProblem(
        id="p1",
        title="t",
        difficulty=1,
        prompt="prompt",
        workspace_dir="/tmp/x",
        validation_steps=[ValidationStep(name="v", command="true")],
        tags=[],
    )


def test_stub_adapter_satisfies_port_protocol():
    adapter = StubAgentHarnessAdapter()
    assert isinstance(adapter, AgentHarnessPort)


def test_stub_returns_default_telemetry():
    adapter = StubAgentHarnessAdapter()
    telemetry = adapter.run(_pkg(), _problem(), workspace="/tmp/x")
    assert telemetry == RawTelemetry(events=[], exit_code=0)


def test_stub_returns_configured_telemetry():
    canned = RawTelemetry(events=[{"kind": "tok", "n": 42}], exit_code=0)
    adapter = StubAgentHarnessAdapter(telemetry=canned)
    telemetry = adapter.run(_pkg(), _problem(), workspace="/tmp/x")
    assert telemetry is canned


def test_port_method_returns_raw_telemetry_not_metrics():
    """Regression guard: the port surface drops the legacy Metrics shape."""
    adapter = StubAgentHarnessAdapter()
    result = adapter.run(_pkg(), _problem(), workspace="/tmp/x")
    assert isinstance(result, RawTelemetry)
