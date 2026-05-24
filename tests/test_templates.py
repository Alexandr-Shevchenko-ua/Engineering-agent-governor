"""Tests for prompt template content."""

from governor.templates import executor_prompt, validator_prompt


def test_executor_prompt_includes_critical_constraints():
    prompt = executor_prompt("My task", "/repo", "run-1")
    assert "Inspect first" in prompt or "Inspect" in prompt
    assert "minimal" in prompt.lower()
    assert "refactor" in prompt.lower()
    assert "secrets" in prompt.lower() or ".env" in prompt
    assert "changed files" in prompt.lower()
    assert "Commands run" in prompt or "commands" in prompt.lower()


def test_validator_prompt_requires_exact_verdict_labels():
    prompt = validator_prompt("My task", "/repo", "run-1")
    assert "PASS" in prompt
    assert "PASS_WITH_RISK" in prompt
    assert "REPAIR_REQUIRED" in prompt
    assert "HUMAN_DECISION_REQUIRED" in prompt
    assert "adversarial" in prompt.lower()
