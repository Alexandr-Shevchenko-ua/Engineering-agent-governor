"""Read-only run diagnostics and next-step hints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from governor.models import RunState
from governor.run_plan import PLAN_JSON, load_plan
from governor.run_store import RunStore, STATE_FILE
from governor.utils import resolve_repo_path, runs_dir, validate_run_id


@dataclass
class DiagnoseResult:
    run_id: str
    state: str
    outcome: str | None
    stuck_reason: str
    next_command: str
    gate_overall: str | None
    plan_overall: str | None
    has_executor_output: bool
    has_validator_output: bool
    has_final_report: bool
    has_evidence: bool
    has_review_package: bool
    proposal_id: str | None
    extra_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "outcome": self.outcome,
            "stuck_reason": self.stuck_reason,
            "next_command": self.next_command,
            "gate_overall": self.gate_overall,
            "plan_overall": self.plan_overall,
            "has_executor_output": self.has_executor_output,
            "has_validator_output": self.has_validator_output,
            "has_final_report": self.has_final_report,
            "has_evidence": self.has_evidence,
            "has_review_package": self.has_review_package,
            "proposal_id": self.proposal_id,
            "extra_notes": self.extra_notes,
        }


def _gate_overall(run_dir: Path) -> str | None:
    path = run_dir / "08_gate_results.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("overall", "")) or None
    except (OSError, json.JSONDecodeError):
        return None


def diagnose_run(repo_path: str | Path, run_id: str) -> DiagnoseResult:
    repo = resolve_repo_path(str(repo_path))
    rid = validate_run_id(run_id)
    if rid is None:
        raise ValueError("run-id is required")
    run_dir = runs_dir(repo) / rid
    if not (run_dir / STATE_FILE).is_file():
        raise FileNotFoundError(f"Run not found: {rid}")

    store = RunStore(repo)
    meta = store.load_metadata(run_dir)
    state = meta.state
    notes: list[str] = []

    has_exec = (run_dir / "05_executor_output.md").is_file()
    has_val = (run_dir / "06_validator_output.md").is_file()
    has_report = (run_dir / "09_final_report.md").is_file()
    has_evidence = (run_dir / "14_evidence_bundle.md").is_file()
    has_review = (run_dir / "15_review_package.md").is_file() or (
        run_dir / "15_pr_body.md"
    ).is_file()
    gate = _gate_overall(run_dir)

    proposal_id: str | None = None
    ref_path = run_dir / "00_governor_proposal_ref.json"
    if ref_path.is_file():
        try:
            ref = json.loads(ref_path.read_text(encoding="utf-8"))
            proposal_id = ref.get("proposal_id")
        except (OSError, json.JSONDecodeError):
            pass

    plan_overall: str | None = None
    plan_path = run_dir / PLAN_JSON
    if plan_path.is_file():
        try:
            plan = load_plan(run_dir)
            plan_overall = plan.overall_status
            pending = [s.step_id for s in plan.steps if s.status == "PENDING"]
            if pending:
                notes.append(f"Plan pending steps: {', '.join(pending[:5])}")
        except (ValueError, OSError) as e:
            notes.append(f"Plan load issue: {e}")

    if has_exec and (run_dir / "05_executor_output.failed.md").is_file():
        notes.append("Executor failed artifact exists — use dispatch --replace or --accept-failed-output")
    if has_exec and not (run_dir / "05_executor_output.failed.md").is_file():
        if (run_dir / "05_executor_output.md").stat().st_size == 0:
            notes.append("Executor output file is empty")

    stuck = "Run in progress or awaiting human approval."
    next_cmd = f"python -m governor run resume --run-id {rid} --approve --repo-path ."

    if state == RunState.EXECUTOR_PROMPT_READY.value:
        stuck = "Executor not dispatched yet; plan may be waiting for dispatch_executor."
        next_cmd = (
            f"python -m governor dispatch --run-id {rid} --role executor --approve "
            f"--repo-path ."
        )
        if plan_path.is_file():
            next_cmd = (
                f"python -m governor run resume --run-id {rid} --approve "
                f"--continue-on-gate-warn --repo-path ."
            )
    elif state == RunState.EXECUTOR_OUTPUT_RECORDED.value:
        stuck = "Executor output recorded; gates or validator may be next."
        next_cmd = (
            f"python -m governor run resume --run-id {rid} --approve --repo-path ."
        )
    elif state == RunState.GATES_RUN.value:
        if gate == "WARN":
            stuck = "Gates completed with WARN (e.g. wide diff, optional tools missing)."
            next_cmd = (
                f"python -m governor run resume --run-id {rid} --approve "
                f"--continue-on-gate-warn --repo-path ."
            )
            notes.append("Review 08_gate_results.json / 08_gate_results.md")
        elif gate == "FAIL":
            stuck = "Gates FAILED — fix repo or narrow diff before continuing."
            next_cmd = f"python -m governor gate --run-id {rid} --repo-path ."
        else:
            stuck = "Gates ran; continue plan or validator."
            next_cmd = (
                f"python -m governor run resume --run-id {rid} --approve --repo-path ."
            )
    elif state == RunState.FINAL_REPORT_READY.value:
        stuck = "Run complete — review final report and optional exports."
        next_cmd = f"python -m governor status --run-id {rid} --repo-path ."
        if not has_evidence:
            notes.append(
                f"Export evidence: python -m governor evidence export --run-id {rid} --repo-path ."
            )
        if not has_review:
            notes.append(
                f"Export review: python -m governor review export --run-id {rid} --repo-path ."
            )
    elif state == RunState.HUMAN_DECISION_REQUIRED.value:
        stuck = "Human decision required before continuing."
        next_cmd = f"python -m governor status --run-id {rid} --repo-path ."

    if has_exec and state == RunState.EXECUTOR_PROMPT_READY.value:
        notes.append("05_executor_output.md exists but state is EXECUTOR_PROMPT_READY — record or resume with --replace")

    return DiagnoseResult(
        run_id=rid,
        state=state,
        outcome=meta.outcome,
        stuck_reason=stuck,
        next_command=next_cmd,
        gate_overall=gate,
        plan_overall=plan_overall,
        has_executor_output=has_exec,
        has_validator_output=has_val,
        has_final_report=has_report,
        has_evidence=has_evidence,
        has_review_package=has_review,
        proposal_id=proposal_id,
        extra_notes=notes,
    )
