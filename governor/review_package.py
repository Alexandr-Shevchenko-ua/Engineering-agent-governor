"""Review / MR handoff package export for governed runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from governor.evidence import (
    EVIDENCE_JSON,
    EVIDENCE_MD,
    build_evidence_bundle,
    evidence_json_path,
)
from governor.models import RunState
from governor.policy import assess_policy_compliance, get_policy, resolve_policy_name
from governor.project_config import load_project_config_optional, project_config_path
from governor.repair_artifacts import list_repair_artifacts
from governor.run_plan import load_plan, plan_json_path, plan_status_summary
from governor.run_store import RunStore
from governor.trace import TraceLogger
from governor.utils import utc_now_iso
from governor.verdict import parse_validator_verdict

REVIEW_MD = "15_review_package.md"
REVIEW_JSON = "15_review_package.json"
PR_BODY_MD = "15_pr_body.md"


def review_md_path(run_dir: Path) -> Path:
    return run_dir / REVIEW_MD


def review_json_path(run_dir: Path) -> Path:
    return run_dir / REVIEW_JSON


def pr_body_path(run_dir: Path) -> Path:
    return run_dir / PR_BODY_MD


def _read_gate(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "08_gate_results.json"
    if not p.is_file():
        return {"overall": None, "note": "gates not run"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"overall": "unreadable"}


def _project_summary(repo: Path) -> dict[str, Any] | None:
    cfg = load_project_config_optional(repo)
    if not cfg:
        return None
    return {
        "project_name": cfg.project_name,
        "default_policy": cfg.default_policy,
        "default_gate_profile": cfg.default_gate_profile,
        "diff_budget": {
            "max_changed_files": cfg.diff_budget.max_changed_files,
            "max_lines_added": cfg.diff_budget.max_lines_added,
            "max_lines_deleted": cfg.diff_budget.max_lines_deleted,
        },
        "config_path": str(project_config_path(repo)),
    }


def build_review_package(
    store: RunStore,
    run_id: str,
    *,
    include_trace: bool = False,
) -> dict[str, Any]:
    run_dir, meta = store.get_run(run_id)
    repo = Path(meta.repo_path)
    gate = _read_gate(run_dir)
    pol_name = resolve_policy_name(getattr(meta, "policy", None))
    pack = get_policy(pol_name)

    validator_text = None
    v_path = run_dir / "06_validator_output.md"
    if v_path.is_file():
        validator_text = v_path.read_text(encoding="utf-8").strip()[:2000]
    verdict = parse_validator_verdict(validator_text)

    plan_summary: dict[str, Any] | None = None
    gate_profile: str | None = gate.get("gate_profile")
    if plan_json_path(run_dir).is_file():
        try:
            plan = load_plan(run_dir)
            plan_summary = {
                "overall_status": plan.overall_status,
                "step_counts": plan_status_summary(plan),
                "executor_profile": plan.executor_profile,
                "validator_profile": plan.validator_profile,
                "gate_profile": getattr(plan, "gate_profile", None) or gate_profile,
            }
            if plan_summary.get("gate_profile"):
                gate_profile = plan_summary["gate_profile"]
        except (ValueError, json.JSONDecodeError):
            plan_summary = {"error": "unreadable plan"}

    compliance = assess_policy_compliance(
        run_dir,
        pack,
        gate_overall=gate.get("overall") if isinstance(gate, dict) else None,
        validator_verdict=verdict,
    )

    diff_budget_summary = {
        "changed_files": gate.get("changed_files_count"),
        "lines_added": gate.get("lines_added"),
        "lines_deleted": gate.get("lines_deleted"),
        "diff_budget_gate": _gate_result_status(gate, "diff_budget"),
    }
    sensitive_summary = {
        "suspicious_files": gate.get("suspicious_files", []),
        "sensitive_paths_gate": _gate_result_status(gate, "sensitive_paths"),
    }

    evidence_path = None
    if evidence_json_path(run_dir).is_file():
        evidence_path = str(evidence_json_path(run_dir))
    elif (run_dir / EVIDENCE_MD).is_file():
        evidence_path = str(run_dir / EVIDENCE_MD)

    pkg: dict[str, Any] = {
        "version": 1,
        "exported_at": utc_now_iso(),
        "run_id": meta.run_id,
        "task": meta.task,
        "repo_path": meta.repo_path,
        "policy": pol_name,
        "gate_profile": gate_profile,
        "state": meta.state,
        "outcome": meta.outcome,
        "project_config": _project_summary(repo),
        "plan": plan_summary,
        "gate": gate,
        "validator_verdict": verdict,
        "repair_history": list_repair_artifacts(run_dir),
        "human_checkpoints_file": "13_human_checkpoints.md"
        if (run_dir / "13_human_checkpoints.md").is_file()
        else None,
        "evidence_bundle_path": evidence_path,
        "diff_budget_summary": diff_budget_summary,
        "sensitive_path_summary": sensitive_summary,
        "commands_executed": list(meta.commands_executed),
        "policy_compliance": compliance,
        "reviewer_checklist": _reviewer_checklist(meta, gate, verdict, compliance),
        "risks_and_limitations": [
            "Governor does not merge, push, or deploy.",
            "No automatic repair dispatch loop.",
            "Runner profiles are local-only (.governor/config.json).",
        ],
        "final_report": "09_final_report.md"
        if (run_dir / "09_final_report.md").is_file()
        else None,
    }
    if include_trace:
        pkg["trace_recent"] = _trace_recent(run_dir)
    return pkg


def _gate_result_status(gate: dict[str, Any], name: str) -> str | None:
    for r in gate.get("results") or []:
        if r.get("name") == name:
            return r.get("status")
    return None


def _trace_recent(run_dir: Path, limit: int = 40) -> list[dict[str, Any]]:
    p = run_dir / "trace.jsonl"
    if not p.is_file():
        return []
    events = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events[-limit:]


def _reviewer_checklist(
    meta,
    gate: dict[str, Any],
    verdict: str | None,
    compliance: dict[str, Any],
) -> list[str]:
    items = [
        "Confirm task scope matches diff and final report.",
        "Review gate overall and required profile checks.",
        "Confirm validator verdict before merge.",
    ]
    if gate.get("overall") == "WARN":
        items.append("Gate WARN — acknowledge warnings explicitly.")
    if gate.get("overall") == "FAIL":
        items.append("Gate FAIL — do not merge until fixed and re-gated.")
    if verdict == "HUMAN_DECISION_REQUIRED":
        items.append("Validator requested human decision.")
    if compliance.get("overall") not in ("PASS", "OK", None):
        items.append(f"Policy compliance: {compliance.get('overall')}")
    if meta.state != RunState.FINAL_REPORT_READY.value:
        items.append(f"Run state is {meta.state} — closure may be incomplete.")
    return items


def render_pr_body(pkg: dict[str, Any]) -> str:
    gate = pkg.get("gate") or {}
    lines = [
        "## Summary",
        "",
        f"{pkg.get('task', '')}",
        "",
        f"- **Run ID:** `{pkg.get('run_id')}`",
        f"- **Policy:** `{pkg.get('policy')}`",
        f"- **Gate profile:** `{pkg.get('gate_profile') or 'n/a'}`",
        f"- **Outcome:** {pkg.get('outcome') or '(pending)'}",
        "",
        "## Validation",
        "",
        f"- Gate overall: **{gate.get('overall', 'n/a')}**",
    ]
    if gate.get("profile_compliance"):
        lines.append(f"- Profile compliance: **{gate['profile_compliance']}**")
    lines.append(f"- Validator verdict: **{pkg.get('validator_verdict') or 'n/a'}**")
    pc = pkg.get("policy_compliance") or {}
    lines.append(f"- Policy compliance: **{pc.get('overall', 'n/a')}**")
    if pkg.get("evidence_bundle_path"):
        lines.append(f"- Evidence: `{pkg['evidence_bundle_path']}`")
    lines.extend(
        [
            "",
            "## Risk",
            "",
        ]
    )
    for r in pkg.get("risks_and_limitations") or []:
        lines.append(f"- {r}")
    sens = pkg.get("sensitive_path_summary") or {}
    if sens.get("suspicious_files"):
        lines.append(f"- Sensitive paths flagged: {len(sens['suspicious_files'])}")
    lines.extend(
        [
            "",
            "## Rollback / next action",
            "",
            "- Revert commit if validation fails post-merge.",
            "- Re-run gates after fixes: `python -m governor gate --run-id <id>`.",
            "",
            "## Artifacts",
            "",
            f"- Review package: `{REVIEW_MD}`, `{REVIEW_JSON}`",
        ]
    )
    if pkg.get("final_report"):
        lines.append(f"- Final report: `{pkg['final_report']}`")
    return "\n".join(lines) + "\n"


def render_review_markdown(pkg: dict[str, Any]) -> str:
    lines = [
        "# Review package",
        "",
        f"**Run ID:** `{pkg['run_id']}`",
        f"**Task:** {pkg['task']}",
        f"**Policy:** `{pkg.get('policy')}`",
        f"**Gate profile:** `{pkg.get('gate_profile') or 'n/a'}`",
        f"**State / outcome:** {pkg.get('state')} / {pkg.get('outcome') or '(pending)'}",
        f"**Exported:** {pkg['exported_at']}",
        "",
        "## Project config",
        "",
    ]
    pc = pkg.get("project_config")
    if pc:
        lines.append(f"- Project: {pc.get('project_name')}")
        lines.append(f"- Default policy: `{pc.get('default_policy')}`")
        lines.append(f"- Default gate profile: `{pc.get('default_gate_profile')}`")
    else:
        lines.append("- No `governor.project.json` (legacy repo mode)")
    lines.extend(["", "## Plan summary", ""])
    plan = pkg.get("plan")
    if plan:
        lines.append(f"- Status: {plan.get('overall_status')}")
        lines.append(f"- Steps: {plan.get('step_counts')}")
        if plan.get("gate_profile"):
            lines.append(f"- Gate profile: `{plan['gate_profile']}`")
    lines.extend(["", "## Gate summary", ""])
    gate = pkg.get("gate") or {}
    lines.append(f"- Overall: **{gate.get('overall', 'n/a')}**")
    if gate.get("gate_profile"):
        lines.append(f"- Profile: `{gate['gate_profile']}` ({gate.get('profile_compliance')})")
    lines.extend(["", "## Validator", "", f"**Verdict:** {pkg.get('validator_verdict') or 'n/a'}", ""])
    lines.extend(["", "## Diff budget", ""])
    db = pkg.get("diff_budget_summary") or {}
    lines.append(
        f"- Files: {db.get('changed_files')} (+{db.get('lines_added')}/-{db.get('lines_deleted')})"
    )
    lines.append(f"- diff_budget check: {db.get('diff_budget_gate') or 'n/a'}")
    lines.extend(["", "## Sensitive paths", ""])
    sp = pkg.get("sensitive_path_summary") or {}
    if sp.get("suspicious_files"):
        for f in sp["suspicious_files"][:15]:
            lines.append(f"- `{f}`")
    else:
        lines.append("- None flagged")
    lines.extend(["", "## Reviewer checklist", ""])
    for item in pkg.get("reviewer_checklist") or []:
        lines.append(f"- [ ] {item}")
    lines.extend(["", "## Risks / limitations", ""])
    for r in pkg.get("risks_and_limitations") or []:
        lines.append(f"- {r}")
    if pkg.get("evidence_bundle_path"):
        lines.extend(["", "## Evidence", "", f"See `{pkg['evidence_bundle_path']}`"])
    lines.extend(["", "## Commands executed", ""])
    for c in pkg.get("commands_executed") or []:
        lines.append(f"- `{c}`")
    return "\n".join(lines) + "\n"


def export_review_package(
    store: RunStore,
    run_id: str,
    *,
    include_trace: bool = False,
    write_markdown: bool = True,
    write_json: bool = True,
    write_pr_body: bool = True,
) -> tuple[Path | None, Path | None, Path | None]:
    run_dir, meta = store.get_run(run_id)
    pkg = build_review_package(store, run_id, include_trace=include_trace)
    md_p: Path | None = None
    json_p: Path | None = None
    pr_p: Path | None = None
    if write_markdown:
        md_p = review_md_path(run_dir)
        md_p.write_text(render_review_markdown(pkg), encoding="utf-8")
    if write_json:
        json_p = review_json_path(run_dir)
        json_p.write_text(
            json.dumps(pkg, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if write_pr_body:
        pr_p = pr_body_path(run_dir)
        pr_p.write_text(render_pr_body(pkg), encoding="utf-8")
    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="review",
        actor="governor",
        action="review_export",
        output_ref=REVIEW_MD,
        status="ok",
        reason=f"trace={'yes' if include_trace else 'no'}",
    )
    store.append_command(
        run_id,
        f"python -m governor review export --run-id {run_id}",
    )
    return md_p, json_p, pr_p


def maybe_export_review_package(
    store: RunStore,
    run_id: str,
    *,
    with_review_package: bool,
) -> tuple[bool, str | None]:
    if not with_review_package:
        return False, None
    _, meta = store.get_run(run_id)
    if meta.state != RunState.FINAL_REPORT_READY.value:
        return (
            False,
            "Review package export skipped because final report is not ready.",
        )
    export_review_package(store, run_id)
    return True, None
