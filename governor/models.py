"""Data models and state machine for governor runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RunState(str, Enum):
    INTAKE_CREATED = "INTAKE_CREATED"
    EXECUTOR_PROMPT_READY = "EXECUTOR_PROMPT_READY"
    EXECUTOR_OUTPUT_RECORDED = "EXECUTOR_OUTPUT_RECORDED"
    GATES_RUN = "GATES_RUN"
    VALIDATOR_OUTPUT_RECORDED = "VALIDATOR_OUTPUT_RECORDED"
    REPAIR_RECORDED = "REPAIR_RECORDED"
    FINAL_REPORT_READY = "FINAL_REPORT_READY"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"


# Valid transitions keyed by action; values are target states.
_STATE_TRANSITIONS: dict[str, dict[RunState, RunState]] = {
    "init": {RunState.INTAKE_CREATED: RunState.EXECUTOR_PROMPT_READY},
    "record_executor": {
        RunState.EXECUTOR_PROMPT_READY: RunState.EXECUTOR_OUTPUT_RECORDED,
        RunState.INTAKE_CREATED: RunState.EXECUTOR_OUTPUT_RECORDED,
        RunState.REPAIR_RECORDED: RunState.EXECUTOR_OUTPUT_RECORDED,
    },
    "record_validator": {
        RunState.EXECUTOR_OUTPUT_RECORDED: RunState.VALIDATOR_OUTPUT_RECORDED,
        RunState.GATES_RUN: RunState.VALIDATOR_OUTPUT_RECORDED,
        RunState.REPAIR_RECORDED: RunState.VALIDATOR_OUTPUT_RECORDED,
    },
    "gate": {
        RunState.EXECUTOR_OUTPUT_RECORDED: RunState.GATES_RUN,
        RunState.VALIDATOR_OUTPUT_RECORDED: RunState.GATES_RUN,
        RunState.REPAIR_RECORDED: RunState.GATES_RUN,
    },
    "record_repair": {
        RunState.VALIDATOR_OUTPUT_RECORDED: RunState.REPAIR_RECORDED,
        RunState.GATES_RUN: RunState.REPAIR_RECORDED,
        RunState.EXECUTOR_OUTPUT_RECORDED: RunState.REPAIR_RECORDED,
    },
    "record_human_note": {},  # does not change primary workflow state
    "report": {
        RunState.GATES_RUN: RunState.FINAL_REPORT_READY,
        RunState.VALIDATOR_OUTPUT_RECORDED: RunState.FINAL_REPORT_READY,
        RunState.REPAIR_RECORDED: RunState.FINAL_REPORT_READY,
        RunState.EXECUTOR_OUTPUT_RECORDED: RunState.FINAL_REPORT_READY,
        RunState.HUMAN_DECISION_REQUIRED: RunState.FINAL_REPORT_READY,
        RunState.FINAL_REPORT_READY: RunState.FINAL_REPORT_READY,
    },
    "human_decision": {
        RunState.VALIDATOR_OUTPUT_RECORDED: RunState.HUMAN_DECISION_REQUIRED,
        RunState.GATES_RUN: RunState.HUMAN_DECISION_REQUIRED,
    },
}


def transition_state(current: RunState, action: str) -> RunState:
    """Return next state for action, or unchanged if no transition defined."""
    mapping = _STATE_TRANSITIONS.get(action, {})
    return mapping.get(current, current)


def can_transition(current: RunState, action: str) -> bool:
    """True if action is defined and allowed from current state."""
    mapping = _STATE_TRANSITIONS.get(action, {})
    return current in mapping


def allowed_from_states(action: str) -> list[RunState]:
    return list(_STATE_TRANSITIONS.get(action, {}).keys())


def invalid_transition_message(current: RunState, action: str) -> str:
    mapping = _STATE_TRANSITIONS.get(action, {})
    if mapping:
        allowed = ", ".join(s.value for s in mapping)
        return f"Invalid transition: {current.value} --{action}--> (allowed from: {allowed})"
    return f"Invalid transition: {current.value} --{action}--> (unknown action)"


def require_transition(current: RunState, action: str) -> RunState:
    """Return next state or raise ValueError with a clear message."""
    mapping = _STATE_TRANSITIONS.get(action, {})
    if current not in mapping:
        raise ValueError(invalid_transition_message(current, action))
    return mapping[current]


NEXT_ACTIONS: dict[RunState, str] = {
    RunState.INTAKE_CREATED: "Open 03_executor_prompt.md, paste into Cursor Agent, then record executor output.",
    RunState.EXECUTOR_PROMPT_READY: "Paste 03_executor_prompt.md into Cursor Agent, implement, then: governor record --role executor",
    RunState.EXECUTOR_OUTPUT_RECORDED: "Run: governor gate --run-id <id>, then paste 04_validator_prompt.md and record validator output.",
    RunState.GATES_RUN: "Paste 04_validator_prompt.md into Cursor Agent, then: governor record --role validator",
    RunState.VALIDATOR_OUTPUT_RECORDED: "Review validator verdict; run gate again if needed, or: governor report --run-id <id>",
    RunState.REPAIR_RECORDED: "Re-run executor or validator as needed; gate and report when ready.",
    RunState.FINAL_REPORT_READY: "Review 09_final_report.md and 10_lead_update.md; archive or start a new run.",
    RunState.HUMAN_DECISION_REQUIRED: "Lead must decide before merge/apply; document decision in human_notes.md.",
}


ROLE_OUTPUT_FILES: dict[str, str] = {
    "executor": "05_executor_output.md",
    "validator": "06_validator_output.md",
    "human_note": "human_notes.md",
}

ROLE_FAILED_OUTPUT_FILES: dict[str, str] = {
    "executor": "05_executor_output.failed.md",
    "validator": "06_validator_output.failed.md",
}


def record_action_for_role(role: str) -> str:
    if role == "human_note":
        return "record_human_note"
    if role == "repair":
        return "record_repair"
    return f"record_{role}"


@dataclass
class RunMetadata:
    run_id: str
    task: str
    repo_path: str
    state: str
    created_at: str
    updated_at: str
    repair_count: int = 0
    commands_executed: list[str] = field(default_factory=list)
    outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunMetadata:
        return cls(
            run_id=data["run_id"],
            task=data["task"],
            repo_path=data["repo_path"],
            state=data["state"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            repair_count=data.get("repair_count", 0),
            commands_executed=list(data.get("commands_executed", [])),
            outcome=data.get("outcome"),
        )
