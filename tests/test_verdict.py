"""Validator verdict parsing tests."""

from governor.verdict import parse_validator_verdict


def test_pass_standalone_line():
    assert parse_validator_verdict("Some intro\n\nPASS\n") == "PASS"


def test_pass_verdict_colon():
    assert parse_validator_verdict("Verdict: PASS\n") == "PASS"


def test_pass_markdown_bold():
    assert parse_validator_verdict("**Verdict:** PASS_WITH_RISK\n") == "PASS_WITH_RISK"


def test_pass_bullet():
    assert parse_validator_verdict("- Verdict: REPAIR_REQUIRED\n") == "REPAIR_REQUIRED"


def test_pass_fenced_block():
    text = "Summary\n\n```\nHUMAN_DECISION_REQUIRED\n```\n"
    assert parse_validator_verdict(text) == "HUMAN_DECISION_REQUIRED"


def test_no_false_positive_inline_pass():
    assert parse_validator_verdict("Could be PASS after repair.") is None


def test_no_verdict():
    assert parse_validator_verdict("Looks good but no label.") is None
