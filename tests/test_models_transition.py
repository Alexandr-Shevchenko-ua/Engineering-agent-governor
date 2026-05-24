"""Transition helper tests."""

from governor.models import RunState, can_transition, require_transition


def test_can_transition_executor_from_prompt_ready():
    assert can_transition(RunState.EXECUTOR_PROMPT_READY, "record_executor")


def test_cannot_transition_validator_from_prompt_ready():
    assert not can_transition(RunState.EXECUTOR_PROMPT_READY, "record_validator")


def test_require_transition_raises_clear_message():
    try:
        require_transition(RunState.EXECUTOR_PROMPT_READY, "record_validator")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "Invalid transition" in str(e)
        assert "EXECUTOR_PROMPT_READY" in str(e)
        assert "record_validator" in str(e)
