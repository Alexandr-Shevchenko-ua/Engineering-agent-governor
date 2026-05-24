"""Final report and lead update generation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from governor.models import NEXT_ACTIONS, RunState
from governor.run_store import RunStore


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


def _extract_verdict(validator_text: str | None) -> str | None:
    if not validator_text:
        return None
    for label in (
        "HUMAN_DECISION_REQUIRED",
        "REPAIR_REQUIRED",
        "PASS_WITH_RISK",
        "PASS",
    ):
        if re.search(rf"^\s*{label}\s*$", validator_text, re.MULTILINE | re.IGNORECASE):
            return label.upper()
    return None


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


def _outcome_from_run(
    state: str,
    verdict: str | None,
    gate_overall: str | None,
) -> str:
    if verdict == "HUMAN_DECISION_REQUIRED":
        return "HUMAN_DECISION_REQUIRED"
    if verdict == "REPAIR_REQUIRED":
        return "REPAIR_REQUIRED"
    if verdict in ("PASS", "PASS_WITH_RISK"):
        return verdict
    if gate_overall == "FAIL":
        return "GATES_FAILED"
    if state == RunState.FINAL_REPORT_READY.value:
        return "REPORT_COMPLETE"
    return "IN_PROGRESS"


def generate_reports(store: RunStore, run_id: str) -> tuple[Path, Path]:
    run_dir, meta = store.get_run(run_id)
    artifacts = store.list_artifacts(run_dir)

    intake = _read_optional(run_dir, "00_task_intake.md")
    scope = _read_optional(run_dir, "01_scope_and_assumptions.md")
    risks = _read_optional(run_dir, "02_risk_register.md")
    executor_out = _read_optional(run_dir, "05_executor_output.md")
    validator_out = _read_optional(run_dir, "06_validator_output.md")

    gate_data = None
    gate_path = run_dir / "08_gate_results.json"
    if gate_path.exists():
        gate_data = json.loads(gate_path.read_text(encoding="utf-8"))

    verdict = _extract_verdict(validator_out)
    gate_overall = gate_data.get("overall") if gate_data else None
    outcome = _outcome_from_run(meta.state, verdict, gate_overall)

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

    git_summary = _gate_summary(run_dir)

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
            "Yes — lead must decide." if human_decision else "No — proceed per validator/gate outcome.",
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
    report_lines.extend(
        [
            "",
            "## Artifact list",
            "",
        ]
    )
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
        ]
    )
    if human_decision:
        lead_lines.append("- Decision on escalated validator/product risk items.")
    else:
        lead_lines.append("- None unless outcome is HUMAN_DECISION_REQUIRED or gates WARN/FAIL.")

    lead_path = run_dir / "10_lead_update.md"
    lead_path.write_text("\n".join(lead_lines) + "\n", encoding="utf-8")

    meta.outcome = outcome
    store.save_metadata(run_dir, meta)
    store.update_state(run_id, "report")
    store.append_command(run_id, f"python -m governor report --run-id {run_id}")

    return report_path, lead_path
