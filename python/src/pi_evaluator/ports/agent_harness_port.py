from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from typing import Any

@dataclass
class Metrics:
    tokens_consumed: int
    quality_score: float

@dataclass
class Trial:
    # Represents the configuration (AgentGraph in Haskell) being tested
    config: Any 
    metrics: Metrics

@runtime_checkable
class AgentHarnessPort(Protocol):
    """
    Port defining how the optimization domain communicates with the Pi agent harness.
    Adapters will implement this using CLI, RPC, or SDK.
    """
    
    def evaluate_configuration(self, config: Any, problem_prompt: str) -> Metrics:
        """
        Executes the Pi agent with the given configuration and problem, 
        returning the performance metrics.
        """
        ...
