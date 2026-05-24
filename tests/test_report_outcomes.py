"""Report outcome logic tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governor.report import compute_outcome, generate_reports, lead_need_from_lead
from governor.run_store import RunStore


def test_compute_outcome_gate_only_pass():
    assert (
        compute_outcome(
            verdict=None,
            gate_overall="PASS",
            has_gates=True,
            state="GATES_RUN",
            has_executor=True,
        )
        == "GATES_PASS_NO_VALIDATOR"
    )


def test_compute_outcome_gate_only_warn():
    assert (
        compute_outcome(
            verdict=None,
            gate_overall="WARN",
            has_gates=True,
            state="GATES_RUN",
            has_executor=True,
        )
        == "GATES_WARN_NO_VALIDATOR"
    )


def test_compute_outcome_gate_fail():
    assert (
        compute_outcome(
            verdict=None,
            gate_overall="FAIL",
            has_gates=True,
            state="GATES_RUN",
            has_executor=True,
        )
        == "GATES_FAILED"
    )


def test_compute_outcome_intake_only():
    assert (
        compute_outcome(
            verdict=None,
            gate_overall=None,
            has_gates=False,
            state="EXECUTOR_PROMPT_READY",
            has_executor=False,
        )
        == "INTAKE_ONLY"
    )


def test_lead_need_not_none_on_gate_warn_without_validator():
    msg = lead_need_from_lead(
        verdict=None,
        gate_overall="WARN",
        has_validator=False,
        has_gates=True,
        human_decision=False,
    )
    assert "None" not in msg
    assert "validator" in msg.lower()


def test_report_gate_only_pass_outcome_in_file():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Gate only")
        store.record_output(meta.run_id, "executor", text="done")
        (run_dir / "08_gate_results.json").write_text(
            json.dumps({"overall": "PASS", "results": []}),
            encoding="utf-8",
        )
        report_p, lead_p = generate_reports(store, meta.run_id)
        body = report_p.read_text(encoding="utf-8")
        lead = lead_p.read_text(encoding="utf-8")
        assert "GATES_PASS_NO_VALIDATOR" in body
        assert "validator" in lead.lower()
