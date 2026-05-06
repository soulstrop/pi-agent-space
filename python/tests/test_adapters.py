def test_cli_stream_adapter_initialization():
    from pi_evaluator.adapters.cli_stream_adapter import CliStreamAdapter
    from pi_evaluator.ports.agent_harness_port import AgentHarnessPort
    
    adapter = CliStreamAdapter()
    assert isinstance(adapter, AgentHarnessPort)
