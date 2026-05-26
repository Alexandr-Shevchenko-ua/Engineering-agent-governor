"""Tests for v1.4.1 evaluation metric accuracy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from governor.evaluation import (
    EVAL_MD,
    _flag_metrics,
    _gate_metrics,
    _human_command_metrics,
    _plan_execution_timing,
    evaluate_run,
    extract_run_evaluation,
    load_all_evaluations,
    render_evaluation_markdown,
)
from governor.trace import TraceLogger


def _write_minimal_run(
    run_dir: Path,
    run_id: str,
    *,
    commands: list[str],
    gate_data: dict,
    validator_profile: str = "fake-validator",
    trace_plan: bool = True,
) -> None:
    state = {
        "run_id": run_id,
        "task": "Accuracy test",
        "repo_path": str(run_dir.parent.parent),
        "state": "FINAL_REPORT_READY",
        "created_at": "2026-05-25T10:00:00Z",
        "updated_at": "2026-05-25T10:05:00Z",
        "repair_count": 0,
        "repair_prompt_count": 0,
        "commands_executed": commands,
        "outcome": "PASS",
        "policy": "docs",
    }
    (run_dir / "run_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    (run_dir / "08_gate_results.json").write_text(json.dumps(gate_data, indent=2) + "\n", encoding="utf-8")
    (run_dir / "06_validator_output.md").write_text("## Verdict\n\nPASS\n", encoding="utf-8")
    (run_dir / "12_run_plan.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": run_id,
                "repo_path": str(run_dir.resolve()),
                "created_at": state["created_at"],
                "updated_at": state["updated_at"],
                "executor_profile": "echo-test",
                "validator_profile": validator_profile,
                "overall_status": "PASS",
                "steps": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "09_final_report.md").write_text("# r\n", encoding="utf-8")
    if trace_plan:
        trace = TraceLogger(run_dir, run_id)
        trace.append(
            phase="plan",
            actor="governor",
            action="plan_resume_start",
            status="ok",
        )
        trace.append(
            phase="dispatch",
            actor="governor",
            action="dispatch_executor",
            status="ok",
            reason="duration=2.0s",
        )
        trace.append(
            phase="plan",
            actor="governor",
            action="plan_resume_stop",
            status="pass",
            reason="complete",
        )


def test_profile_compliance_warn_in_gate_warn_count(tmp_path: Path) -> None:
    run_id = "20260525T120000Z_test-run-warn"
    run_dir = tmp_path / ".governor" / "runs" / run_id
    run_dir.mkdir(parents=True)
    gate = {
        "overall": "WARN",
        "profile_compliance": "WARN",
        "profile_compliance_reason": "optional checks skipped",
        "results": [{"name": "pytest", "status": "PASS"}],
    }
    _write_minimal_run(run_dir, run_id, commands=[], gate_data=gate, trace_plan=False)
    gm = _gate_metrics(run_dir)
    assert gm["gate_overall_is_warn"] is True
    assert gm["profile_compliance_warn_count"] == 1
    assert gm["gate_warn_count"] >= 1
    assert gm["gate_subcheck_warn_count"] == 0


def test_human_decision_count_excludes_readonly(tmp_path: Path) -> None:
    cmds = [
        "python -m governor status --run-id x",
        "python -m governor diagnose --run-id x",
        "python -m governor evaluate show --run-id x",
        "python -m governor evaluate export --repo-path .",
        "# comment line",
    ]
    m = _human_command_metrics(cmds)
    assert m["commands_executed_count"] == 4
    assert m["human_decision_count"] == 0


def test_human_decision_count_includes_decisions(tmp_path: Path) -> None:
    cmds = [
        "python -m governor plan resume --run-id x --approve",
        "python -m governor dispatch --run-id x --role executor --approve",
        "python -m governor evaluate annotate --run-id x --mr-outcome accepted",
        "python -m governor repair prepare --run-id x",
    ]
    m = _human_command_metrics(cmds)
    assert m["human_decision_count"] == 4


def test_force_and_safety_flags_from_commands(tmp_path: Path) -> None:
    cmds = [
        "python -m governor dispatch --run-id x --force --approve",
        "python -m governor plan resume --replace --accept-failed-output --approve",
    ]
    flags = _flag_metrics(cmds, [])
    assert flags["force_like"] >= 1
    assert flags["replace"] >= 1
    assert flags["safety_override"] >= 1


def test_safety_override_penalized_more_in_friction(tmp_path: Path) -> None:
    run_id = "20260525T120200Z_test-flags"
    run_dir = tmp_path / ".governor" / "runs" / run_id
    run_dir.mkdir(parents=True)
    gate = {"overall": "PASS", "results": []}
    cmds = ["python -m governor plan resume --accept-failed-output --approve"]
    _write_minimal_run(run_dir, run_id, commands=cmds, gate_data=gate)
    ev = extract_run_evaluation(tmp_path, run_id)
    assert ev["safety_override_flags_count"] >= 1
    assert ev["governor_friction_score"] >= 15


def test_active_execution_seconds_from_plan_trace(tmp_path: Path) -> None:
    run_id = "20260525T120100Z_test-active"
    run_dir = tmp_path / ".governor" / "runs" / run_id
    run_dir.mkdir(parents=True)
    gate = {"overall": "PASS", "results": []}
    _write_minimal_run(run_dir, run_id, commands=[], gate_data=gate, trace_plan=True)
    events = TraceLogger(run_dir, run_id).read_all()
    timing = _plan_execution_timing(events, "2026-05-25T10:00:00Z")
    assert timing["first_resume_at"] is not None
    assert timing["active_execution_seconds"] is not None
    assert timing["active_execution_seconds"] >= 0


def test_markdown_fake_validator_caveat(tmp_path: Path) -> None:
    run_id = "20260525T120300Z_test-fake-val"
    run_dir = tmp_path / ".governor" / "runs" / run_id
    run_dir.mkdir(parents=True)
    gate = {"overall": "PASS", "results": []}
    _write_minimal_run(
        run_dir,
        run_id,
        commands=[],
        gate_data=gate,
        validator_profile="fake-validator",
        trace_plan=False,
    )
    ev = extract_run_evaluation(tmp_path, run_id)
    md = render_evaluation_markdown(ev)
    assert "fake-validator PASS is harness success" in md


def test_full_extract_profile_compliance_and_decisions(tmp_path: Path) -> None:
    repo = tmp_path
    run_id = "20260525T120400Z_acc-run"
    run_dir = repo / ".governor" / "runs" / run_id
    run_dir.mkdir(parents=True)
    gate = {
        "overall": "WARN",
        "profile_compliance": "WARN",
        "results": [{"name": "pytest", "status": "PASS"}],
    }
    cmds = [
        f"python -m governor status --run-id {run_id}",
        f"python -m governor plan execute --run-id {run_id} --approve --replace",
        f"python -m governor dispatch --run-id {run_id} --force --approve",
    ]
    _write_minimal_run(run_dir, run_id, commands=cmds, gate_data=gate)
    ev = extract_run_evaluation(repo, run_id)
    assert ev["gate_warn_count"] >= 1
    assert ev["human_decision_count"] >= 1
    assert ev["replace_flags_count"] >= 1
    assert ev["force_like_flags_count"] >= 1


def test_jsonl_idempotent_after_accuracy_fields(tmp_path: Path) -> None:
    repo = tmp_path
    run_id = "20260525T120500Z_idem-run"
    run_dir = repo / ".governor" / "runs" / run_id
    run_dir.mkdir(parents=True)
    gate = {"overall": "PASS", "results": []}
    _write_minimal_run(run_dir, run_id, commands=[], gate_data=gate, trace_plan=False)
    evaluate_run(repo, run_id)
    evaluate_run(repo, run_id)
    rows = load_all_evaluations(repo)
    assert sum(1 for r in rows if r.get("run_id") == run_id) == 1
    assert "human_decision_count" in rows[0]
