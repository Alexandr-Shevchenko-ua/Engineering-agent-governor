"""Run evaluation metrics — local extraction, annotation, export (no LLM scoring)."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from governor.project_config import project_config_path
from governor.run_plan import PLAN_JSON, load_plan
from governor.run_store import STATE_FILE, RunStore
from governor.trace import TraceLogger
from governor.utils import (
    governor_root,
    proposals_dir,
    resolve_repo_path,
    runs_dir,
    utc_now_iso,
    validate_run_id,
)
from governor.verdict import parse_validator_verdict

EVAL_JSON = "17_run_evaluation.json"
EVAL_MD = "17_run_evaluation.md"
EVAL_INDEX_NAME = "evaluations.jsonl"
EVAL_CSV_NAME = "evaluations.csv"
EVAL_MD_EXPORT = "evaluations.md"
DASHBOARD_MD = "dashboard.md"

MR_OUTCOMES = frozenset(
    {
        "accepted",
        "needs_minor_changes",
        "needs_major_rewrite",
        "rejected",
        "unknown",
    }
)

_DURATION_RE = re.compile(r"duration=([\d.]+)s", re.IGNORECASE)

_PLAN_START_ACTIONS = frozenset({"plan_execute_start", "plan_resume_start"})
_PLAN_STOP_ACTIONS = frozenset({"plan_execute_stop", "plan_resume_stop"})

# Flags counted from commands_executed and trace reasons (v1.4.1).
_FORCE_LIKE_FLAGS = (
    "--force",
    "--force-unstructured",
)
_REPLACE_FLAGS = ("--replace",)
_SAFETY_OVERRIDE_FLAGS = (
    "--allow-disabled-profile",
    "--allow-write-capable-governor-provider",
    "--accept-failed-output",
)

# Commands that are not human decisions (read-only / housekeeping).
_NON_DECISION_SUBSTRINGS = (
    "governor status",
    "governor list",
    "governor show",
    "governor diagnose",
    "governor cleanup",
    "governor doctor",
    "evaluate show",
    "evaluate export",
    "evaluate summary",
    "evaluate run",
    "safety audit",
    "config show",
    "project show",
    "project validate",
    "project path",
)

_DECISION_SUBSTRINGS = (
    "governor apply",
    "plan resume",
    "plan execute",
    " dispatch ",
    " record ",
    "checkpoint",
    "evaluate annotate",
    "repair prepare",
    " repair ",
    "governor gate",
    "governor report",
    "governor dispatch",
    "governor record",
)


def evaluations_dir(repo_path: Path) -> Path:
    return governor_root(repo_path) / "evaluations"


def evaluation_index_path(repo_path: Path) -> Path:
    return evaluations_dir(repo_path) / EVAL_INDEX_NAME


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _seconds_between(a: str | None, b: str | None) -> float | None:
    da, db = _parse_iso(a), _parse_iso(b)
    if da is None or db is None:
        return None
    return max(0.0, (db - da).total_seconds())


def _infer_task_category(policy: str | None, task: str) -> str:
    pol = (policy or "default").lower()
    if pol in ("docs", "documentation"):
        return "docs"
    if pol in ("bugfix", "fix"):
        return "bugfix"
    low = task.lower()
    if "doc" in low or "readme" in low:
        return "docs"
    if "fix" in low or "bug" in low:
        return "bugfix"
    return pol or "default"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _count_advisor_artifacts(run_dir: Path) -> int:
    return len(list(run_dir.glob("16_advisor_request_*.md")))


def _count_repair_prompts(run_dir: Path) -> int:
    return len(list(run_dir.glob("11_repair_prompt_*.md")))


def _is_comment_command(cmd: str) -> bool:
    s = cmd.strip()
    return not s or s.startswith("#")


def _count_flags_in_text(text: str) -> dict[str, int]:
    low = text.lower()
    force_like = sum(1 for f in _FORCE_LIKE_FLAGS if f in low)
    replace = sum(1 for f in _REPLACE_FLAGS if f in low)
    safety = sum(1 for f in _SAFETY_OVERRIDE_FLAGS if f in low)
    return {
        "force_like": force_like,
        "replace": replace,
        "safety_override": safety,
    }


def _aggregate_flag_counts(*parts: dict[str, int]) -> dict[str, int]:
    out = {"force_like": 0, "replace": 0, "safety_override": 0}
    for p in parts:
        for k in out:
            out[k] += int(p.get(k, 0))
    return out


def _flag_metrics(commands: list[str], events: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"force_like": 0, "replace": 0, "safety_override": 0}
    for cmd in commands:
        if _is_comment_command(cmd):
            continue
        part = _count_flags_in_text(cmd)
        for k in totals:
            totals[k] += part[k]
    for ev in events:
        reason = str(ev.get("reason") or "")
        part = _count_flags_in_text(reason)
        for k in totals:
            totals[k] += part[k]
    return totals


def _human_command_metrics(commands: list[str]) -> dict[str, int]:
    executed = [c for c in commands if not _is_comment_command(c)]
    human_decisions = 0
    manual_steps = 0
    for cmd in executed:
        low = cmd.lower()
        if any(pat in low for pat in _NON_DECISION_SUBSTRINGS):
            continue
        is_decision = any(pat in low for pat in _DECISION_SUBSTRINGS) or " --approve" in low
        if is_decision:
            human_decisions += 1
            manual_steps += 1
    return {
        "commands_executed_count": len(executed),
        "human_decision_count": human_decisions,
        "manual_step_count": manual_steps,
    }


def _plan_execution_timing(
    events: list[dict[str, Any]],
    created_at: str | None,
) -> dict[str, Any]:
    windows: list[tuple[str, str]] = []
    open_start: str | None = None
    first_resume_at: str | None = None
    last_plan_execution_at: str | None = None

    for ev in events:
        action = str(ev.get("action") or "")
        ts = ev.get("ts")
        if not ts:
            continue
        if action in _PLAN_START_ACTIONS:
            if action == "plan_resume_start" and first_resume_at is None:
                first_resume_at = ts
            open_start = ts
        elif action in _PLAN_STOP_ACTIONS and open_start:
            windows.append((open_start, ts))
            last_plan_execution_at = ts
            open_start = None

    active_total = 0.0
    for start_ts, stop_ts in windows:
        sec = _seconds_between(start_ts, stop_ts)
        if sec is not None:
            active_total += sec

    human_gap: float | None = None
    if first_resume_at and created_at:
        human_gap = _seconds_between(created_at, first_resume_at)

    return {
        "first_resume_at": first_resume_at,
        "last_plan_execution_at": last_plan_execution_at,
        "active_execution_seconds": round(active_total, 2) if windows else None,
        "human_gap_before_resume_seconds": round(human_gap, 2) if human_gap is not None else None,
        "plan_execution_window_count": len(windows),
    }


def _trace_metrics(run_dir: Path, run_id: str) -> dict[str, Any]:
    events = TraceLogger(run_dir, run_id).read_all()
    advisor_calls = _count_advisor_artifacts(run_dir)
    checkpoint_count = 0
    repair_loops = _count_repair_prompts(run_dir)
    failed_dispatch = 0
    agent_runtime = 0.0
    first_executor_ts: str | None = None
    first_gate_ts: str | None = None
    first_report_ts: str | None = None

    for ev in events:
        action = str(ev.get("action") or "")
        phase = str(ev.get("phase") or "")
        reason = str(ev.get("reason") or "").lower()
        ts = ev.get("ts")
        status = str(ev.get("status") or "").lower()

        if "checkpoint" in action or "human_checkpoint" in action:
            checkpoint_count += 1
        if phase == "advisor" or action.startswith("advisor"):
            advisor_calls += 1
        if phase == "repair" or "repair" in action:
            repair_loops = max(repair_loops, _count_repair_prompts(run_dir))
        if phase == "dispatch" and status == "fail":
            failed_dispatch += 1
        m = _DURATION_RE.search(str(ev.get("reason") or ""))
        if m and phase == "dispatch":
            agent_runtime += float(m.group(1))
        if action == "dispatch_executor" and ts and not first_executor_ts:
            first_executor_ts = ts
        if phase == "gate" and ts and not first_gate_ts:
            first_gate_ts = ts
        if action == "report" or (phase == "plan" and action == "plan_step_finish" and ev.get("output_ref") == "report"):
            if ts and not first_report_ts:
                first_report_ts = ts

    return {
        "advisor_calls_count": advisor_calls,
        "checkpoint_count": checkpoint_count,
        "repair_loops_count": repair_loops,
        "failed_dispatch_count": failed_dispatch,
        "agent_runtime_total_seconds": round(agent_runtime, 2),
        "first_executor_ts": first_executor_ts,
        "first_gate_ts": first_gate_ts,
        "first_report_ts": first_report_ts,
        "_trace_events": events,
    }


def _gate_metrics(run_dir: Path) -> dict[str, Any]:
    data = _load_json(run_dir / "08_gate_results.json") or {}
    results = data.get("results") or []
    fail_c = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "FAIL")
    warn_c = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "WARN")
    profile_compliance = data.get("profile_compliance")
    profile_status = str(profile_compliance).upper() if profile_compliance is not None else None
    profile_compliance_warn_count = (
        1 if profile_status == "WARN" else 0
    )
    gate_overall = data.get("overall")
    gate_overall_is_warn = str(gate_overall or "").upper() == "WARN"
    profile_reason = data.get("profile_compliance_reason")
    if profile_reason is None and profile_compliance is not None:
        profile_reason = f"profile_compliance={profile_compliance}"
    combined_warn_count = warn_c + profile_compliance_warn_count
    diff_budget_exceeded = False
    tests_passed: bool | None = None
    tests_failed: bool | None = None
    sensitive: list[str] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "")
        st = str(r.get("status") or "")
        if name == "diff_budget" and st == "FAIL":
            diff_budget_exceeded = True
        if name == "pytest":
            summary = str(r.get("summary") or "") + str(r.get("details") or "")
            if "failed" in summary.lower() or st == "FAIL":
                tests_failed = True
            elif "passed" in summary.lower() or st == "PASS":
                tests_passed = True
        if name == "sensitive_paths" and st == "FAIL":
            sensitive.append("sensitive_paths_gate_fail")
    changed = data.get("changed_files_count")
    added = data.get("lines_added")
    deleted = data.get("lines_deleted")
    total_lines = None
    if isinstance(added, int) and isinstance(deleted, int):
        total_lines = added + deleted
    return {
        "gate_overall": gate_overall,
        "gate_overall_is_warn": gate_overall_is_warn,
        "gate_profile_compliance_status": profile_compliance,
        "gate_profile_compliance_reason": profile_reason,
        "profile_compliance_warn_count": profile_compliance_warn_count,
        "gate_fail_count": fail_c,
        "gate_warn_count": combined_warn_count,
        "gate_subcheck_warn_count": warn_c,
        "changed_files_count": changed,
        "diff_lines_added": added,
        "diff_lines_deleted": deleted,
        "diff_total_lines": total_lines,
        "diff_budget_exceeded": diff_budget_exceeded,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "sensitive_paths_touched": sensitive,
    }


def _proposal_metrics(repo: Path, run_dir: Path) -> dict[str, Any]:
    ref = _load_json(run_dir / "00_governor_proposal_ref.json")
    out: dict[str, Any] = {
        "governor_provider": None,
        "provider_confidence": None,
        "cursor_model": None,
        "proposal_rejections_count": 0,
    }
    if not ref:
        return out
    pid = ref.get("proposal_id")
    out["provider_confidence"] = ref.get("confidence")
    if pid:
        pj = proposals_dir(repo) / str(pid) / "proposal.json"
        pdata = _load_json(pj)
        if pdata:
            out["governor_provider"] = pdata.get("provider")
            out["cursor_model"] = pdata.get("provider_model")
            if pdata.get("status") == "REJECTED":
                out["proposal_rejections_count"] = 1
    return out


def _evidence_completeness(run_dir: Path) -> int:
    score = 0
    checks = [
        "09_final_report.md",
        "14_evidence_bundle.md",
        "15_review_package.md",
        "15_pr_body.md",
        "08_gate_results.json",
        "05_executor_output.md",
        "06_validator_output.md",
    ]
    for name in checks:
        if (run_dir / name).is_file():
            score += 1
    return min(5, score)


def compute_scores(ev: dict[str, Any]) -> dict[str, float]:
    human_decisions = int(
        ev.get("human_decision_count")
        if ev.get("human_decision_count") is not None
        else ev.get("human_interventions_count")
        or 0
    )
    friction = (
        human_decisions * 5
        + int(ev.get("repair_loops_count") or 0) * 10
        + int(ev.get("failed_dispatch_count") or 0) * 15
        + int(ev.get("force_like_flags_count") or ev.get("force_flags_count") or 0) * 8
        + int(ev.get("replace_flags_count") or 0) * 5
        + int(ev.get("safety_override_flags_count") or 0) * 15
        + int(ev.get("checkpoint_count") or 0) * 5
        + int(ev.get("manual_rework_minutes") or 0) * 2
    )
    friction = min(100.0, float(friction))

    success = 100.0
    if ev.get("outcome") != "PASS":
        success -= 40
    gate = (ev.get("gate_overall") or "").upper()
    if gate == "FAIL":
        success -= 30
    elif gate == "WARN":
        success -= 10
    verdict = (ev.get("validator_verdict") or "").upper()
    if verdict and verdict not in ("PASS", "PASS_WITH_RISK"):
        success -= 20
    elif verdict == "PASS_WITH_RISK":
        success -= 8
    if ev.get("post_run_defects_found"):
        success -= 20
    rework = int(ev.get("manual_rework_minutes") or 0)
    success -= min(30.0, rework * 2.0)
    if not ev.get("final_report_exists"):
        success -= 20
    if not ev.get("evidence_bundle_exists"):
        success -= 10
    success = max(0.0, min(100.0, success))

    burden_sig = 0.0
    if ev.get("evidence_bundle_exists"):
        burden_sig += 20
    if ev.get("review_package_exists"):
        burden_sig += 20
    if ev.get("pr_body_exists"):
        burden_sig += 15
    if ev.get("final_report_exists"):
        burden_sig += 10
    burden_sig -= int(ev.get("reviewer_comments_count") or 0) * 5
    burden_sig -= int(ev.get("lead_followup_questions_count") or 0) * 8
    rbs = ev.get("reviewer_burden_score")
    if isinstance(rbs, (int, float)) and rbs:
        burden_sig += (6 - float(rbs)) * 5
    eqs = ev.get("evidence_quality_score")
    if isinstance(eqs, (int, float)) and eqs:
        burden_sig += (float(eqs) - 3) * 5
    burden_sig = max(0.0, min(100.0, burden_sig))

    return {
        "governor_friction_score": round(friction, 1),
        "run_success_score": round(success, 1),
        "reviewer_burden_reduction_signal": round(burden_sig, 1),
    }


def _default_evaluation() -> dict[str, Any]:
    return {
        "run_id": None,
        "task": None,
        "task_category": None,
        "policy": None,
        "project_name": None,
        "created_at": None,
        "final_state": None,
        "outcome": None,
        "governor_provider": None,
        "advisor_provider": "chatbang",
        "executor_profile": None,
        "validator_profile": None,
        "cursor_model": None,
        "provider_confidence": None,
        "time_to_first_executor_output_seconds": None,
        "time_to_first_patch_seconds": None,
        "time_to_gate_seconds": None,
        "time_to_final_report_seconds": None,
        "total_runtime_seconds": None,
        "blocked_time_seconds": None,
        "blocked_time_seconds_approximate": True,
        "agent_runtime_total_seconds": None,
        "first_resume_at": None,
        "last_plan_execution_at": None,
        "active_execution_seconds": None,
        "human_gap_before_resume_seconds": None,
        "plan_execution_window_count": 0,
        "commands_executed_count": 0,
        "human_decision_count": 0,
        "manual_step_count": 0,
        "human_interventions_count": 0,
        "manual_commands_count": 0,
        "checkpoint_count": 0,
        "advisor_calls_count": 0,
        "proposal_rejections_count": 0,
        "repair_loops_count": 0,
        "force_like_flags_count": 0,
        "force_flags_count": 0,
        "replace_flags_count": 0,
        "safety_override_flags_count": 0,
        "failed_dispatch_count": 0,
        "changed_files_count": None,
        "diff_lines_added": None,
        "diff_lines_deleted": None,
        "diff_total_lines": None,
        "diff_budget_exceeded": False,
        "sensitive_paths_touched": [],
        "gate_overall": None,
        "gate_overall_is_warn": False,
        "gate_profile_compliance_status": None,
        "gate_profile_compliance_reason": None,
        "profile_compliance_warn_count": 0,
        "gate_fail_count": 0,
        "gate_warn_count": 0,
        "gate_subcheck_warn_count": 0,
        "tests_passed": None,
        "tests_failed": None,
        "validator_verdict": None,
        "post_run_defects_found": False,
        "defect_types": [],
        "manual_rework_minutes": 0,
        "mr_outcome": "unknown",
        "final_report_exists": False,
        "evidence_bundle_exists": False,
        "review_package_exists": False,
        "pr_body_exists": False,
        "evidence_completeness_score": 0,
        "evidence_quality_score": None,
        "reviewer_burden_score": None,
        "reviewer_comments_count": 0,
        "lead_followup_questions_count": 0,
        "tokens_input": None,
        "tokens_output": None,
        "cost_estimate_usd": None,
        "governor_friction_score": 0.0,
        "run_success_score": 0.0,
        "reviewer_burden_reduction_signal": 0.0,
        "evaluated_at": None,
        "annotations": [],
    }


def extract_run_evaluation(repo_path: Path, run_id: str) -> dict[str, Any]:
    repo = resolve_repo_path(str(repo_path))
    rid = validate_run_id(run_id)
    if rid is None:
        raise ValueError("Invalid run_id")
    run_dir = runs_dir(repo) / rid
    if not (run_dir / STATE_FILE).is_file():
        raise FileNotFoundError(f"Run not found: {rid}")

    meta = RunStore(repo).load_metadata(run_dir)
    ev = _default_evaluation()
    ev["run_id"] = rid
    ev["task"] = meta.task
    ev["policy"] = meta.policy
    ev["created_at"] = meta.created_at
    ev["final_state"] = meta.state
    ev["outcome"] = meta.outcome
    cmd_metrics = _human_command_metrics(meta.commands_executed or [])
    ev.update(cmd_metrics)
    ev["manual_commands_count"] = cmd_metrics["commands_executed_count"]
    ev["human_interventions_count"] = cmd_metrics["human_decision_count"]
    ev["repair_loops_count"] = max(
        ev.get("repair_loops_count") or 0,
        int(getattr(meta, "repair_count", 0) or 0),
        int(getattr(meta, "repair_prompt_count", 0) or 0),
    )

    proj_path = project_config_path(repo)
    if proj_path.is_file():
        try:
            pdata = json.loads(proj_path.read_text(encoding="utf-8"))
            ev["project_name"] = pdata.get("project_name") or repo.name
        except (OSError, json.JSONDecodeError):
            ev["project_name"] = repo.name
    else:
        ev["project_name"] = repo.name

    ev["task_category"] = _infer_task_category(meta.policy, meta.task or "")

    if (run_dir / PLAN_JSON).is_file():
        try:
            plan = load_plan(run_dir)
            ev["executor_profile"] = plan.executor_profile
            ev["validator_profile"] = plan.validator_profile
        except (FileNotFoundError, ValueError):
            pass

    trace_m = _trace_metrics(run_dir, rid)
    trace_events = trace_m.pop("_trace_events", [])
    ev.update({k: trace_m[k] for k in trace_m if k in ev})

    flag_totals = _flag_metrics(meta.commands_executed or [], trace_events)
    ev["force_like_flags_count"] = flag_totals["force_like"]
    ev["replace_flags_count"] = flag_totals["replace"]
    ev["safety_override_flags_count"] = flag_totals["safety_override"]
    ev["force_flags_count"] = flag_totals["force_like"]

    plan_timing = _plan_execution_timing(trace_events, meta.created_at)
    ev.update({k: plan_timing[k] for k in plan_timing if k in ev})

    gate_m = _gate_metrics(run_dir)
    ev.update({k: gate_m[k] for k in gate_m if k in ev})

    ev.update(_proposal_metrics(repo, run_dir))

    ev["final_report_exists"] = (run_dir / "09_final_report.md").is_file()
    ev["evidence_bundle_exists"] = (run_dir / "14_evidence_bundle.md").is_file() or (
        run_dir / "14_evidence_bundle.json"
    ).is_file()
    ev["review_package_exists"] = (run_dir / "15_review_package.md").is_file()
    ev["pr_body_exists"] = (run_dir / "15_pr_body.md").is_file()

    val_path = run_dir / "06_validator_output.md"
    if val_path.is_file():
        ev["validator_verdict"] = parse_validator_verdict(val_path.read_text(encoding="utf-8"))

    created = meta.created_at
    if trace_m.get("first_executor_ts"):
        ev["time_to_first_executor_output_seconds"] = _seconds_between(
            created, trace_m["first_executor_ts"]
        )
        ev["time_to_first_patch_seconds"] = ev["time_to_first_executor_output_seconds"]
    if trace_m.get("first_gate_ts"):
        ev["time_to_gate_seconds"] = _seconds_between(created, trace_m["first_gate_ts"])
    if trace_m.get("first_report_ts"):
        ev["time_to_final_report_seconds"] = _seconds_between(
            created, trace_m["first_report_ts"]
        )
    ev["total_runtime_seconds"] = _seconds_between(created, meta.updated_at)
    agent_rt = float(ev.get("agent_runtime_total_seconds") or 0)
    total_rt = float(ev.get("total_runtime_seconds") or 0)
    active_rt = ev.get("active_execution_seconds")
    if active_rt is not None and float(active_rt) > 0:
        ev["blocked_time_seconds"] = round(
            max(0.0, total_rt - float(active_rt)), 2
        ) if total_rt else None
    else:
        ev["blocked_time_seconds"] = round(max(0.0, total_rt - agent_rt), 2) if total_rt else None
    ev["blocked_time_seconds_approximate"] = True

    ev["evidence_completeness_score"] = _evidence_completeness(run_dir)
    ev["evaluated_at"] = utc_now_iso()
    ev.update(compute_scores(ev))
    return ev


def _merge_manual_fields(existing: dict[str, Any], new_auto: dict[str, Any]) -> dict[str, Any]:
    manual_keys = (
        "post_run_defects_found",
        "defect_types",
        "manual_rework_minutes",
        "mr_outcome",
        "evidence_quality_score",
        "reviewer_burden_score",
        "reviewer_comments_count",
        "lead_followup_questions_count",
        "tokens_input",
        "tokens_output",
        "cost_estimate_usd",
        "annotations",
    )
    merged = dict(new_auto)
    for key in manual_keys:
        if key in existing and existing.get(key) is not None:
            if key == "annotations" and existing.get("annotations"):
                merged[key] = existing[key]
            elif key != "annotations":
                merged[key] = existing[key]
    return merged


def render_evaluation_markdown(ev: dict[str, Any]) -> str:
    gate_lines = [
        f"- **Gate overall:** {ev.get('gate_overall')}"
        + (" (WARN)" if ev.get("gate_overall_is_warn") else ""),
        f"- Sub-check WARN count: {ev.get('gate_subcheck_warn_count')}",
        f"- Profile compliance: {ev.get('gate_profile_compliance_status')}",
    ]
    if ev.get("gate_profile_compliance_reason"):
        gate_lines.append(f"- Profile compliance note: {ev.get('gate_profile_compliance_reason')}")
    if ev.get("gate_overall_is_warn") and int(ev.get("gate_subcheck_warn_count") or 0) == 0:
        gate_lines.append(
            "- **Note:** overall WARN may come from profile compliance even when all named sub-checks passed."
        )

    validator_profile = str(ev.get("validator_profile") or "")
    validator_lines = [f"- **Validator verdict:** {ev.get('validator_verdict')}"]
    if "fake-validator" in validator_profile.lower() or validator_profile == "fake-validator":
        validator_lines.append(
            "- **Caveat:** fake-validator PASS is harness success, not production-quality validation."
        )

    lines = [
        f"# Run evaluation `{ev.get('run_id')}`",
        "",
        f"- **Evaluated:** {ev.get('evaluated_at')}",
        f"- **Outcome:** {ev.get('outcome')} · **Task category:** {ev.get('task_category')}",
        "",
        "## Scores",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Governor friction | {ev.get('governor_friction_score')} (lower is better) |",
        f"| Run success | {ev.get('run_success_score')} |",
        f"| Reviewer burden reduction | {ev.get('reviewer_burden_reduction_signal')} |",
        "",
        "## Calendar timing",
        "",
        f"- Total runtime (created → updated): {ev.get('total_runtime_seconds')}s",
        f"- Time to first executor output: {ev.get('time_to_first_executor_output_seconds')}s",
        f"- Human gap before first plan resume: {ev.get('human_gap_before_resume_seconds')}s",
        f"- Blocked/idle time (approximate): {ev.get('blocked_time_seconds')}s",
        "",
        "## Active execution timing",
        "",
        f"- First resume at: {ev.get('first_resume_at')}",
        f"- Last plan execution at: {ev.get('last_plan_execution_at')}",
        f"- Active execution windows: {ev.get('plan_execution_window_count')}",
        f"- Active execution seconds: {ev.get('active_execution_seconds')}s",
        f"- Agent dispatch runtime (sum): {ev.get('agent_runtime_total_seconds')}s",
        "",
        "## Human decision / friction",
        "",
        f"- Human decision count (preferred): {ev.get('human_decision_count')}",
        f"- Manual step count: {ev.get('manual_step_count')}",
        f"- Commands executed (raw, non-comment): {ev.get('commands_executed_count')}",
        f"- human_interventions_count (legacy alias): {ev.get('human_interventions_count')}",
        f"- Repair loops: {ev.get('repair_loops_count')}",
        f"- Checkpoints: {ev.get('checkpoint_count')}",
        f"- Force-like flags: {ev.get('force_like_flags_count')}",
        f"- Replace flags: {ev.get('replace_flags_count')}",
        f"- Safety override flags: {ev.get('safety_override_flags_count')}",
        "",
        "## Gate summary",
        "",
        *gate_lines,
        "",
        "## Validator",
        "",
        *validator_lines,
        "",
        "## Manual (post-MR)",
        "",
        f"- MR outcome: {ev.get('mr_outcome')}",
        f"- Manual rework (min): {ev.get('manual_rework_minutes')}",
        f"- Post-run defects: {ev.get('post_run_defects_found')}",
        "",
    ]
    if ev.get("annotations"):
        lines.append("## Annotations")
        lines.append("")
        for ann in ev["annotations"]:
            lines.append(f"- {ann.get('ts')}: {ann.get('note', '')}")
        lines.append("")
    return "\n".join(lines)


def evaluate_run(
    repo_path: Path,
    run_id: str,
    *,
    preserve_manual: bool = True,
) -> tuple[Path, dict[str, Any]]:
    repo = resolve_repo_path(str(repo_path))
    rid = validate_run_id(run_id)
    assert rid is not None
    run_dir = runs_dir(repo) / rid

    existing: dict[str, Any] = {}
    if preserve_manual:
        existing = load_run_evaluation(repo, rid) or load_index_record(repo, rid) or {}

    ev = extract_run_evaluation(repo, run_id)
    if existing:
        ev = _merge_manual_fields(existing, ev)
        ev.update(compute_scores(ev))

    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / EVAL_JSON
    md_path = run_dir / EVAL_MD
    json_path.write_text(json.dumps(ev, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_evaluation_markdown(ev), encoding="utf-8")

    upsert_evaluation_index(repo, ev)
    return json_path, ev


def load_run_evaluation(repo_path: Path, run_id: str) -> dict[str, Any] | None:
    repo = resolve_repo_path(str(repo_path))
    rid = validate_run_id(run_id)
    if rid is None:
        return None
    path = runs_dir(repo) / rid / EVAL_JSON
    return _load_json(path)


def load_index_record(repo_path: Path, run_id: str) -> dict[str, Any] | None:
    path = evaluation_index_path(resolve_repo_path(str(repo_path)))
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("run_id") == run_id:
                return rec
        except json.JSONDecodeError:
            continue
    return None


def upsert_evaluation_index(repo_path: Path, ev: dict[str, Any]) -> None:
    repo = resolve_repo_path(str(repo_path))
    index_path = evaluation_index_path(repo)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = ev.get("run_id")
    rows: list[dict[str, Any]] = []
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if rec.get("run_id") != run_id:
                    rows.append(rec)
            except json.JSONDecodeError:
                continue
    rows.append(ev)
    with index_path.open("w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_all_evaluations(repo_path: Path) -> list[dict[str, Any]]:
    path = evaluation_index_path(resolve_repo_path(str(repo_path)))
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def validate_annotation_fields(fields: dict[str, Any]) -> None:
    if "mr_outcome" in fields and fields["mr_outcome"] is not None:
        mo = str(fields["mr_outcome"]).lower()
        if mo not in MR_OUTCOMES:
            raise ValueError(f"mr_outcome must be one of: {', '.join(sorted(MR_OUTCOMES))}")
    for score_key in ("evidence_quality_score", "reviewer_burden_score"):
        if score_key in fields and fields[score_key] is not None:
            v = int(fields[score_key])
            if v < 1 or v > 5:
                raise ValueError(f"{score_key} must be 1..5")
    if "defect_types" in fields and fields["defect_types"] is not None:
        dt = fields["defect_types"]
        if not isinstance(dt, list):
            raise ValueError("defect_types must be a list of strings")


def annotate_run(
    repo_path: Path,
    run_id: str,
    *,
    note: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    validate_annotation_fields(fields)
    ev = load_run_evaluation(repo_path, run_id) or extract_run_evaluation(repo_path, run_id)
    for key, val in fields.items():
        if val is not None:
            ev[key] = val
    ann = {"ts": utc_now_iso(), "note": note or "manual annotation"}
    ev.setdefault("annotations", []).append(ann)
    ev["evaluated_at"] = utc_now_iso()
    ev.update(compute_scores(ev))

    repo = resolve_repo_path(str(repo_path))
    rid = validate_run_id(run_id)
    assert rid is not None
    run_dir = runs_dir(repo) / rid
    (run_dir / EVAL_JSON).write_text(
        json.dumps(ev, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / EVAL_MD).write_text(render_evaluation_markdown(ev), encoding="utf-8")
    upsert_evaluation_index(repo, ev)
    return ev


def export_evaluations(
    repo_path: Path,
    *,
    fmt: str = "csv",
) -> Path:
    repo = resolve_repo_path(str(repo_path))
    ev_dir = evaluations_dir(repo)
    ev_dir.mkdir(parents=True, exist_ok=True)
    rows = load_all_evaluations(repo)
    fmt_l = fmt.lower()
    if fmt_l == "jsonl":
        out = ev_dir / EVAL_INDEX_NAME
        with out.open("w", encoding="utf-8") as f:
            for rec in rows:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return out
    if fmt_l == "markdown":
        out = ev_dir / EVAL_MD_EXPORT
        lines = ["# Governor run evaluations", "", f"Runs: {len(rows)}", ""]
        for rec in rows:
            lines.append(f"## {rec.get('run_id')}")
            lines.append("")
            lines.append(f"- Success score: {rec.get('run_success_score')}")
            lines.append(f"- Friction: {rec.get('governor_friction_score')}")
            lines.append(f"- Policy: {rec.get('policy')} · Provider: {rec.get('governor_provider')}")
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        return out
    out = ev_dir / EVAL_CSV_NAME
    if not rows:
        out.write_text("", encoding="utf-8")
        return out
    keys = sorted({k for r in rows for k in r.keys()})
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for rec in rows:
            flat = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in rec.items()}
            w.writerow(flat)
    return out


def _avg(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def build_summary(
    repo_path: Path,
    *,
    group_by: str | None = None,
) -> dict[str, Any]:
    rows = load_all_evaluations(repo_path)
    if not rows:
        return {"runs_count": 0, "groups": {}}

    def _success_rate(rs: list[dict[str, Any]]) -> float | None:
        if not rs:
            return None
        passed = sum(1 for r in rs if r.get("outcome") == "PASS")
        return round(100.0 * passed / len(rs), 1)

    overall = {
        "runs_count": len(rows),
        "success_rate_pct": _success_rate(rows),
        "avg_runtime_seconds": _avg(
            [float(r["total_runtime_seconds"]) for r in rows if r.get("total_runtime_seconds") is not None]
        ),
        "avg_rework_minutes": _avg(
            [float(r["manual_rework_minutes"]) for r in rows if int(r.get("manual_rework_minutes") or 0) > 0]
        ),
        "avg_friction": _avg([float(r["governor_friction_score"]) for r in rows if r.get("governor_friction_score") is not None]),
        "avg_success_score": _avg([float(r["run_success_score"]) for r in rows if r.get("run_success_score") is not None]),
        "avg_reviewer_burden_signal": _avg(
            [
                float(r["reviewer_burden_reduction_signal"])
                for r in rows
                if r.get("reviewer_burden_reduction_signal") is not None
            ]
        ),
    }

    groups: dict[str, Any] = {}
    if group_by:
        key = group_by if group_by in ("policy", "executor_profile", "governor_provider") else group_by
        buckets: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            g = str(r.get(key) or "unknown")
            buckets.setdefault(g, []).append(r)
        for g, rs in sorted(buckets.items()):
            rb_scores = [
                float(r["reviewer_burden_score"])
                for r in rs
                if isinstance(r.get("reviewer_burden_score"), (int, float))
            ]
            groups[g] = {
                "count": len(rs),
                "success_rate_pct": _success_rate(rs),
                "avg_runtime_seconds": _avg(
                    [float(r["total_runtime_seconds"]) for r in rs if r.get("total_runtime_seconds") is not None]
                ),
                "avg_rework_minutes": _avg(
                    [float(r["manual_rework_minutes"]) for r in rs if int(r.get("manual_rework_minutes") or 0) > 0]
                ),
                "avg_reviewer_burden_score": _avg(rb_scores) if rb_scores else None,
                "avg_friction": _avg(
                    [float(r["governor_friction_score"]) for r in rs if r.get("governor_friction_score") is not None]
                ),
            }

    return {"overall": overall, "groups": groups, "group_by": group_by}


def format_summary_text(summary: dict[str, Any]) -> str:
    o = summary.get("overall") or {}
    lines = [
        "# Evaluation summary",
        "",
        f"Runs evaluated: {o.get('runs_count', 0)}",
        f"Success rate: {o.get('success_rate_pct')}%",
        f"Avg runtime (s): {o.get('avg_runtime_seconds')}",
        f"Avg rework (min, nonzero only): {o.get('avg_rework_minutes')}",
        f"Avg friction score: {o.get('avg_friction')} (lower is better)",
        f"Avg success score: {o.get('avg_success_score')}",
        f"Avg reviewer burden signal: {o.get('avg_reviewer_burden_signal')}",
        "",
    ]
    groups = summary.get("groups") or {}
    if groups:
        gb = summary.get("group_by", "group")
        lines.append(f"## By {gb}")
        lines.append("")
        lines.append("| Group | Count | Success % | Avg runtime | Avg rework | Avg friction |")
        lines.append("|-------|-------|-----------|-------------|------------|--------------|")
        for name, g in groups.items():
            lines.append(
                f"| {name} | {g.get('count')} | {g.get('success_rate_pct')} | "
                f"{g.get('avg_runtime_seconds')} | {g.get('avg_rework_minutes')} | {g.get('avg_friction')} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_dashboard(repo_path: Path, summary: dict[str, Any]) -> Path:
    ev_dir = evaluations_dir(resolve_repo_path(str(repo_path)))
    ev_dir.mkdir(parents=True, exist_ok=True)
    path = ev_dir / DASHBOARD_MD
    path.write_text(format_summary_text(summary), encoding="utf-8")
    return path
