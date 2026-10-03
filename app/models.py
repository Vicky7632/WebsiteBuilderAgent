from dataclasses import dataclass, field
from enum import Enum


class AgentState(str, Enum):
    PLANNING = "planning"
    ACTING = "acting"
    OBSERVING = "observing"
    INSPECTING = "inspecting"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class VerificationResult:
    passed: bool
    project_path: str | None = None
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def observation(self) -> str:
        if self.passed:
            return (
                "Verification passed. Project files: "
                + ", ".join(self.files)
            )
        return "Verification failed:\n- " + "\n- ".join(self.errors)


@dataclass
class AgentRun:
    state: AgentState = AgentState.PLANNING
    state_history: list[AgentState] = field(default_factory=list)
    project_path: str | None = None
    observations: list[str] = field(default_factory=list)

    def transition(self, state: AgentState) -> None:
        self.state = state
        self.state_history.append(state)
