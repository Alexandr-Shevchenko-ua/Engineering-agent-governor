"""Final report and lead update generation."""

from __future__ import annotations

import json
from pathlib import Path

from governor.models import NEXT_ACTIONS, RunState, require_transition
from governor.run_store import RunStore
from governor.verdict import parse_validator_verdict

REPORT_COMMAND_TEMPLATE = "python -m governor report --run-id {run_id}"


def _read_optional(run_dir: Path, name: str, max_chars: int = 4000) -> str | None:
    path = run_dir / name
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n... (truncated)"
    return text


def _summarize(text: str | None, lines: int = 12) -> str:
    if not text:
        return "_Not recorded._"
    parts = text.splitlines()
    if len(parts) <= lines:
        return text
    return "\n".join(parts[:lines]) + f"\n\n... ({len(parts) - lines} more lines)"


def _gate_summary(run_dir: Path) -> str:
    path = run_dir / "08_gate_results.json"
    if not path.exists():
        return "_Gates not run._"
    data = json.loads(path.read_text(encoding="utf-8"))
    overall = data.get("overall", "unknown")
    results = data.get("results", [])
    failed = [r["name"] for r in results if r.get("status") == "FAIL"]
    warned = [r["name"] for r in results if r.get("status") == "WARN"]
    parts = [f"Overall: **{overall}**"]
    if failed:
        parts.append(f"Failed: {', '.join(failed)}")
    if warned:
        parts.append(f"Warnings: {', '.join(warned)}")
    parts.append(
        f"Diff: {data.get('changed_files_count', 0)} files, "
        f"+{data.get('lines_added', 0)}/-{data.get('lines_deleted', 0)} lines"
    )
    if data.get("suspicious_files"):
        parts.append(f"Suspicious files: {', '.join(data['suspicious_files'])}")
    return "\n".join(parts)


def compute_outcome(
    *,
    verdict: str | None,
    gate_overall: str | None,
    has_gates: bool,
    state: str,
    has_executor: bool,
) -> str:
    """Explicit outcome for final report."""
    if verdict:
        return verdict
    if not has_gates:
        if state in (
            RunState.EXECUTOR_PROMPT_READY.value,
            RunState.INTAKE_CREATED.value,
        ):
            return "INTAKE_ONLY"
        if has_executor:
            return "IN_PROGRESS"
        return "INTAKE_ONLY"
    if gate_overall == "FAIL":
        return "GATES_FAILED"
    if gate_overall == "WARN":
        return "GATES_WARN_NO_VALIDATOR"
    if gate_overall == "PASS":
        return "GATES_PASS_NO_VALIDATOR"
    return "IN_PROGRESS"


def lead_need_from_lead(
    *,
    verdict: str | None,
    gate_overall: str | None,
    has_validator: bool,
    has_gates: bool,
    human_decision: bool,
) -> str:
    if human_decision or verdict == "HUMAN_DECISION_REQUIRED":
        return "Lead decision required on escalated validator/product risk items."
    if verdict == "REPAIR_REQUIRED":
        return "Owner to complete repair loop and re-run gate/validator."
    if verdict == "PASS_WITH_RISK":
        return "Lead acknowledgment of documented risks before merge."
    if not has_validator:
        if has_gates and gate_overall in ("WARN", "FAIL"):
            return "Review gate results; validator output not recorded — do not merge blindly."
        if has_gates and gate_overall == "PASS":
            return "Confirm gate-only PASS is acceptable without validator sign-off."
        return "Awaiting delegated executor/validator outputs."
    if verdict == "PASS":
        return "Optional explicit sign-off if your process requires it."
    return "Review outcome and artifacts before merge."


def _report_command(run_id: str) -> str:
    return REPORT_COMMAND_TEMPLATE.format(run_id=run_id)


def generate_reports(store: RunStore, run_id: str) -> tuple[Path, Path]:
    run_dir, meta = store.get_run(run_id)

    intake = _read_optional(run_dir, "00_task_intake.md")
    scope = _read_optional(run_dir, "01_scope_and_assumptions.md")
    risks = _read_optional(run_dir, "02_risk_register.md")
    executor_out = _read_optional(run_dir, "05_executor_output.md")
    validator_out = _read_optional(run_dir, "06_validator_output.md")

    gate_data = None
    gate_path = run_dir / "08_gate_results.json"
    has_gates = gate_path.exists()
    if has_gates:
        gate_data = json.loads(gate_path.read_text(encoding="utf-8"))

    verdict = parse_validator_verdict(validator_out)
    gate_overall = gate_data.get("overall") if gate_data else None
    outcome = compute_outcome(
        verdict=verdict,
        gate_overall=gate_overall,
        has_gates=has_gates,
        state=meta.state,
        has_executor=executor_out is not None,
    )

    human_decision = (
        verdict == "HUMAN_DECISION_REQUIRED"
        or meta.state == RunState.HUMAN_DECISION_REQUIRED.value
    )

    next_action = NEXT_ACTIONS.get(
        RunState(meta.state),
        "Review artifacts and decide next step.",
    )
    if outcome == "REPAIR_REQUIRED":
        next_action = "Address validator repair items, record repair output, re-run gate."
    elif human_decision:
        next_action = "Lead decision required before merge or deployment."
    elif outcome in ("GATES_PASS_NO_VALIDATOR", "GATES_WARN_NO_VALIDATOR"):
        next_action = "Record validator output or obtain lead sign-off for gate-only result."

    report_cmd = _report_command(run_id)
    if report_cmd not in meta.commands_executed:
        meta.commands_executed.append(report_cmd)
    meta.outcome = outcome
    meta.state = require_transition(RunState(meta.state), "report").value
    store.save_metadata(run_dir, meta)

    artifacts = store.list_artifacts(run_dir)
    git_summary = _gate_summary(run_dir)
    need_lead = lead_need_from_lead(
        verdict=verdict,
        gate_overall=gate_overall,
        has_validator=validator_out is not None,
        has_gates=has_gates,
        human_decision=human_decision,
    )

    report_lines = [
        "# Final report",
        "",
        f"**Outcome:** {outcome}",
        f"**Run ID:** `{meta.run_id}`",
        f"**Task:** {meta.task}",
        f"**State:** {meta.state}",
        f"**Repo:** `{meta.repo_path}`",
        "",
        "## Scope",
        "",
        _summarize(scope or intake, 20),
        "",
        "## Git / diff summary",
        "",
        git_summary,
        "",
        "## Executor output summary",
        "",
        _summarize(executor_out),
        "",
        "## Validator output summary",
        "",
        _summarize(validator_out) if validator_out else "_Not recorded._",
    ]
    if verdict:
        report_lines.extend(["", f"**Validator verdict:** {verdict}", ""])

    report_lines.extend(
        [
            "## Gate results",
            "",
            git_summary,
            "",
            "## Open risks",
            "",
            _summarize(risks, 25) if risks else "_See 02_risk_register.md._",
            "",
            "## Human decision needed",
            "",
            "Yes — lead must decide." if human_decision else "No — unless gate-only or risks require review.",
            "",
            "## Recommended next action",
            "",
            next_action,
            "",
            "## Commands executed (governor)",
            "",
        ]
    )
    for cmd in meta.commands_executed:
        report_lines.append(f"- `{cmd}`")
    report_lines.extend(["", "## Artifact list", ""])
    for a in artifacts:
        report_lines.append(f"- `{a}`")

    report_path = run_dir / "09_final_report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    evidence_bits = []
    if gate_data:
        evidence_bits.append(f"gates={gate_data.get('overall')}")
    if verdict:
        evidence_bits.append(f"verdict={verdict}")
    if executor_out:
        evidence_bits.append("executor output recorded")

    lead_lines = [
        "# Lead update",
        "",
        "## Done",
        "",
        f"- Governor run `{meta.run_id}` for: {meta.task}",
        f"- Outcome: **{outcome}**",
        "",
        "## Evidence",
        "",
    ]
    if evidence_bits:
        lead_lines.append("- " + "; ".join(evidence_bits))
    else:
        lead_lines.append("- Intake and prompts created; awaiting delegated execution.")
    lead_lines.extend(
        [
            f"- Artifacts: `{run_dir}`",
            "",
            "## Next",
            "",
            next_action,
            "",
            "## Need from lead",
            "",
            f"- {need_lead}",
        ]
    )

    lead_path = run_dir / "10_lead_update.md"
    lead_path.write_text("\n".join(lead_lines) + "\n", encoding="utf-8")

    return report_path, lead_path
