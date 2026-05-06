from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class ValidationStep:
    """A command to run to validate if the agent solved the problem."""
    name: str
    command: str
    expected_exit_code: int = 0

@dataclass
class GraduatedProblem:
    """
    Represents a single problem in the evaluation suite.
    The Pi agent will be spawned in the problem's workspace directory,
    given the prompt, and then evaluated using the validation steps.
    """
    id: str
    title: str
    difficulty: int  # 1 (easiest) to 5 (hardest)
    prompt: str
    workspace_dir: str
    validation_steps: List[ValidationStep]
    tags: List[str]
    
    @classmethod
    def from_dict(cls, data: dict) -> 'GraduatedProblem':
        return cls(
            id=data['id'],
            title=data['title'],
            difficulty=data['difficulty'],
            prompt=data['prompt'],
            workspace_dir=data['workspace_dir'],
            validation_steps=[ValidationStep(**step) for step in data.get('validation_steps', [])],
            tags=data.get('tags', [])
        )
