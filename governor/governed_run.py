"""High-level governed run workflow — explicit, bounded, not autopilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from governor.evidence import EVIDENCE_JSON, EVIDENCE_MD, export_evidence
from governor.models import RunState
from governor.policy import get_policy, resolve_policy_name
from governor.preflight import run_execution_preflight
from governor.run_plan import (
    create_plan,
    execute_plan,
    load_plan,
    next_pending_step,
    plan_json_path,
    resume_plan,
)
from governor.run_store import RunStore, init_store


@dataclass
class GovernedRunOptions:
    task: str
    repo_path: str = "."
    policy: str = "default"
    executor_profile: str | None = None
    validator_profile: str | None = None
    executor_runner: str | None = None
    validator_runner: str | None = None
    executor_command: list[str] | None = None
    validator_command: list[str] | None = None
    auto_repair_prepare_on_fail: bool | None = None
    checkpoints: list[tuple[str, str]] | None = None
    with_evidence: bool = False
    approve: bool = False
    dry_run: bool = False
    continue_on_gate_warn: bool = False
    max_steps: int = 10
    replace: bool = False
    accept_failed_output: bool = False
    use_default_profiles: bool = False
    strict_preflight: bool = False


@dataclass
class GovernedRunResult:
    run_id: str | None = None
    policy: str = "default"
    state: str | None = None
    outcome: str | None = None
    plan_overall_status: str | None = None
    stopped_at: str | None = None
    next_action: str = ""
    exit_code: int = 0
    evidence_exported: bool = False
    evidence_skipped_reason: str | None = None
    preflight_messages: list[str] = field(default_factory=list)
    dry_run_actions: list[str] = field(default_factory=list)
    run_dir: Path | None = None
    error: str | None = None


def resolve_runner_profiles(opts: GovernedRunOptions) -> tuple[str | None, str | None]:
    """Return (executor_profile, validator_profile) or raise ValueError."""
    if opts.use_default_profiles:
        return (
            opts.executor_profile or "echo-test",
            opts.validator_profile or "fake-validator",
        )

    has_ex = bool(opts.executor_profile or opts.executor_runner)
    has_val = bool(opts.validator_profile or opts.validator_runner)
    if not has_ex or not has_val:
        raise ValueError(
            "Governed run requires executor and validator. "
            "Pass --executor-profile and --validator-profile (or --executor-runner / "
            "--validator-runner), or use --use-default-profiles for smoke-safe echo-test "
            "/ fake-validator."
        )
    return opts.executor_profile, opts.validator_profile


def uses_config_profiles(opts: GovernedRunOptions) -> bool:
    ex, val = resolve_runner_profiles(opts) if opts.use_default_profiles else (
        opts.executor_profile,
        opts.validator_profile,
    )
    return bool(ex or val)


def _dry_run_plan(opts: GovernedRunOptions) -> list[str]:
    pol = resolve_policy_name(opts.policy)
    pack = get_policy(pol)
    ex_prof = opts.executor_profile or ("echo-test" if opts.use_default_profiles else "?")
    val_prof = opts.validator_profile or ("fake-validator" if opts.use_default_profiles else "?")
    actions = [
        f"Would validate policy: {pol}",
        f"Would create run: task={opts.task!r} policy={pol}",
        f"Would create plan: executor={ex_prof} validator={val_prof}",
    ]
    if pack.plan_defaults.checkpoints:
        for after, msg in pack.plan_defaults.checkpoints:
            actions.append(f"Would add checkpoint after {after}: {msg[:60]}...")
    if opts.approve:
        actions.append("Would run execution preflight")
        actions.append("Would execute plan (--approve)")
        if opts.with_evidence:
            actions.append("Would export evidence if FINAL_REPORT_READY")
    else:
        actions.append("Would NOT execute (missing --approve)")
    return actions


def compute_governed_exit_code(
    *,
    plan_overall_status: str | None,
    state: str | None,
    stopped_at: str | None,
    run_dir: Path | None,
    error: str | None,
) -> int:
    if error:
        return 1
    if plan_overall_status == "BLOCKED" and run_dir and plan_json_path(run_dir).is_file():
        try:
            plan = load_plan(run_dir)
            step = next((s for s in plan.steps if s.step_id == stopped_at), None)
            if step and step.action == "human_checkpoint":
                return 0
        except (ValueError, OSError):
            pass
        return 0
    if plan_overall_status == "PASS":
        return 0
    if state == RunState.FINAL_REPORT_READY.value:
        return 0
    if plan_overall_status in ("FAIL", "STOPPED"):
        return 1
    return 1


def build_next_action(
    store: RunStore,
    run_id: str,
    *,
    repo_path: str,
    plan_overall_status: str | None,
    stopped_at: str | None,
) -> str:
    run_dir, meta = store.get_run(run_id)
    if not plan_json_path(run_dir).is_file():
        return (
            f"python -m governor plan create --run-id {run_id} --repo-path {repo_path}"
        )

    if plan_overall_status == "BLOCKED" and stopped_at:
        try:
            plan = load_plan(run_dir)
            step = next((s for s in plan.steps if s.step_id == stopped_at), None)
            if step and step.action == "human_checkpoint":
                return (
                    f"python -m governor plan checkpoint --run-id {run_id} "
                    f"--step-id {stopped_at} --approve --note \"...\" --repo-path {repo_path}"
                )
        except (ValueError, OSError):
            pass
        return (
            f"python -m governor run resume --run-id {run_id} --approve --repo-path {repo_path}"
        )

    nxt = None
    try:
        plan = load_plan(run_dir)
        nxt = next_pending_step(plan)
    except (ValueError, OSError):
        pass

    if plan_overall_status in ("FAIL", "STOPPED"):
        if (run_dir / "11_repair_prompt_1.md").is_file() or list(
            run_dir.glob("11_repair_prompt_*.md")
        ):
            return (
                f"Repair prompt exists — dispatch repair manually, then: "
                f"python -m governor run resume --run-id {run_id} --approve --repo-path {repo_path}"
            )
        return (
            f"python -m governor repair prepare --run-id {run_id} --repo-path {repo_path}; "
            f"then fix and resume"
        )

    if meta.state == RunState.FINAL_REPORT_READY.value:
        parts = [f"Review 09_final_report.md in {run_dir}"]
        if not evidence_json_path_exists(run_dir):
            parts.append(
                f"python -m governor evidence export --run-id {run_id} --repo-path {repo_path}"
            )
        return "; ".join(parts)

    if nxt:
        return (
            f"python -m governor run resume --run-id {run_id} --approve --repo-path {repo_path}"
        )

    return f"python -m governor status --run-id {run_id} --repo-path {repo_path}"


def evidence_json_path_exists(run_dir: Path) -> bool:
    return (run_dir / EVIDENCE_JSON).is_file() or (run_dir / EVIDENCE_MD).is_file()


def maybe_export_evidence(
    store: RunStore,
    run_id: str,
    *,
    with_evidence: bool,
) -> tuple[bool, str | None]:
    if not with_evidence:
        return False, None
    _, meta = store.get_run(run_id)
    if meta.state != RunState.FINAL_REPORT_READY.value:
        return (
            False,
            "Evidence export skipped because final report is not ready.",
        )
    export_evidence(store, run_id)
    return True, None


def build_run_summary_payload(
    store: RunStore,
    run_id: str,
    *,
    repo_path: str,
    stopped_at: str | None = None,
    plan_overall_status: str | None = None,
    evidence_exported: bool = False,
    evidence_skipped_reason: str | None = None,
) -> dict[str, Any]:
    run_dir, meta = store.get_run(run_id)
    plan_status = plan_overall_status
    if plan_status is None and plan_json_path(run_dir).is_file():
        try:
            plan_status = load_plan(run_dir).overall_status
        except (ValueError, OSError):
            plan_status = None

    next_act = build_next_action(
        store,
        run_id,
        repo_path=repo_path,
        plan_overall_status=plan_status,
        stopped_at=stopped_at,
    )

    artifacts: dict[str, str | None] = {
        "run_folder": str(run_dir),
        "plan_file": str(plan_json_path(run_dir)) if plan_json_path(run_dir).is_file() else None,
        "final_report": str(run_dir / "09_final_report.md")
        if (run_dir / "09_final_report.md").is_file()
        else None,
        "evidence_md": str(run_dir / EVIDENCE_MD)
        if (run_dir / EVIDENCE_MD).is_file()
        else None,
        "evidence_json": str(run_dir / EVIDENCE_JSON)
        if (run_dir / EVIDENCE_JSON).is_file()
        else None,
    }

    return {
        "run_id": meta.run_id,
        "policy": getattr(meta, "policy", None) or "default",
        "state": meta.state,
        "outcome": meta.outcome,
        "plan_overall_status": plan_status,
        "stopped_at": stopped_at,
        "next_action": next_act,
        "artifacts": artifacts,
        "evidence_exported": evidence_exported,
        "evidence_skipped_reason": evidence_skipped_reason,
    }


def print_run_summary(payload: dict[str, Any], *, preflight_warnings: list[str] | None = None) -> None:
    print("=== Governed run summary ===")
    print(f"Run ID:        {payload['run_id']}")
    print(f"Policy:        {payload['policy']}")
    print(f"Plan status:   {payload.get('plan_overall_status') or '(no plan)'}")
    print(f"State:         {payload['state']}")
    print(f"Outcome:       {payload.get('outcome') or '(pending)'}")
    if payload.get("stopped_at"):
        print(f"Stopped at:    {payload['stopped_at']}")
    print("Artifacts:")
    art = payload.get("artifacts") or {}
    print(f"  Run folder:   {art.get('run_folder')}")
    print(f"  Plan:         {art.get('plan_file') or '(none)'}")
    print(f"  Final report: {art.get('final_report') or '(none)'}")
    print(f"  Evidence:     {art.get('evidence_md') or art.get('evidence_json') or '(none)'}")
    if preflight_warnings:
        print("Preflight warnings:")
        for w in preflight_warnings:
            print(f"  - {w}")
    if payload.get("evidence_skipped_reason"):
        print(payload["evidence_skipped_reason"])
    if payload.get("evidence_exported"):
        print("Evidence bundle exported.")
    print(f"Next action:   {payload['next_action']}")


def governed_run_start(opts: GovernedRunOptions) -> GovernedRunResult:
    pol = resolve_policy_name(opts.policy)
    try:
        get_policy(pol)
    except ValueError as e:
        return GovernedRunResult(policy=pol, error=str(e), exit_code=1, next_action=str(e))

    if opts.dry_run:
        return GovernedRunResult(
            policy=pol,
            dry_run_actions=_dry_run_plan(opts),
            next_action="Re-run without --dry-run to create run and plan",
            exit_code=0,
        )

    try:
        ex_prof, val_prof = resolve_runner_profiles(opts)
    except ValueError as e:
        return GovernedRunResult(policy=pol, error=str(e), exit_code=1, next_action=str(e))

    need_profiles = bool(ex_prof or val_prof)
    preflight_msgs: list[str] = []

    if opts.approve:
        checks, ok = run_execution_preflight(
            opts.repo_path,
            use_profiles=need_profiles,
            strict=opts.strict_preflight,
        )
        for c in checks:
            if c.status == "WARN":
                preflight_msgs.append(f"{c.name}: {c.detail}")
            if c.status == "FAIL":
                detail = f"Preflight FAIL — {c.name}: {c.detail}"
                return GovernedRunResult(
                    policy=pol,
                    error=detail,
                    preflight_messages=preflight_msgs + [detail],
                    exit_code=1,
                    next_action=detail,
                )
        if not ok:
            return GovernedRunResult(
                policy=pol,
                error="Preflight failed (strict mode or FAIL checks)",
                preflight_messages=preflight_msgs,
                exit_code=1,
                next_action="Fix preflight issues and retry",
            )

    store = init_store(opts.repo_path)
    run_dir, meta = store.create_run(opts.task, policy_name=pol)
    run_id = meta.run_id

    create_plan(
        store,
        run_id,
        executor_profile=ex_prof,
        executor_runner=opts.executor_runner,
        executor_command=opts.executor_command,
        validator_profile=val_prof,
        validator_runner=opts.validator_runner,
        validator_command=opts.validator_command,
        auto_repair_prepare_on_fail=opts.auto_repair_prepare_on_fail,
        checkpoints=opts.checkpoints,
        policy_name=pol,
    )

    result = GovernedRunResult(
        run_id=run_id,
        policy=pol,
        state=meta.state,
        run_dir=run_dir,
        preflight_messages=preflight_msgs,
    )

    if not opts.approve:
        result.plan_overall_status = load_plan(run_dir).overall_status
        result.next_action = (
            f"python -m governor run resume --run-id {run_id} --approve "
            f"--repo-path {opts.repo_path}"
        )
        if opts.with_evidence:
            result.evidence_skipped_reason = (
                "Evidence export skipped — plan not executed (pass --approve)."
            )
        result.exit_code = 0
        return result

    exec_result = execute_plan(
        store,
        run_id,
        approve=True,
        continue_on_gate_warn=opts.continue_on_gate_warn,
        replace=opts.replace,
        accept_failed_output=opts.accept_failed_output,
        max_steps=opts.max_steps,
        repo_path=opts.repo_path,
    )

    _, meta = store.get_run(run_id)
    plan = load_plan(run_dir)
    result.state = meta.state
    result.outcome = meta.outcome
    result.plan_overall_status = plan.overall_status
    result.stopped_at = exec_result.stopped_at

    ev_ok, ev_skip = maybe_export_evidence(store, run_id, with_evidence=opts.with_evidence)
    result.evidence_exported = ev_ok
    result.evidence_skipped_reason = ev_skip

    result.next_action = build_next_action(
        store,
        run_id,
        repo_path=opts.repo_path,
        plan_overall_status=plan.overall_status,
        stopped_at=exec_result.stopped_at,
    )
    result.exit_code = compute_governed_exit_code(
        plan_overall_status=plan.overall_status,
        state=meta.state,
        stopped_at=exec_result.stopped_at,
        run_dir=run_dir,
        error=None,
    )
    return result


def governed_run_resume(
    store: RunStore,
    run_id: str,
    *,
    opts: GovernedRunOptions,
) -> GovernedRunResult:
    run_dir, meta = store.get_run(run_id)
    pol = getattr(meta, "policy", None) or "default"

    if not plan_json_path(run_dir).is_file():
        return GovernedRunResult(
            run_id=run_id,
            policy=pol,
            error=f"No plan at {plan_json_path(run_dir)}. Run: python -m governor plan create --run-id {run_id}",
            exit_code=1,
            next_action=f"python -m governor plan create --run-id {run_id} --repo-path {opts.repo_path}",
        )

    if not opts.approve:
        return GovernedRunResult(
            run_id=run_id,
            policy=pol,
            error="run resume requires --approve to execute dispatch steps",
            exit_code=1,
            next_action=f"python -m governor run resume --run-id {run_id} --approve --repo-path {opts.repo_path}",
        )

    if opts.dry_run:
        return GovernedRunResult(
            run_id=run_id,
            policy=pol,
            dry_run_actions=[f"Would resume plan for {run_id}"],
            exit_code=0,
        )

    need_profiles = plan_json_path(run_dir).is_file()
    try:
        plan = load_plan(run_dir)
        need_profiles = any(s.profile for s in plan.steps)
    except (ValueError, OSError):
        need_profiles = True

    preflight_msgs: list[str] = []
    checks, ok = run_execution_preflight(
        opts.repo_path,
        use_profiles=need_profiles,
        strict=opts.strict_preflight,
    )
    for c in checks:
        if c.status == "WARN":
            preflight_msgs.append(f"{c.name}: {c.detail}")
        if c.status == "FAIL":
            detail = f"Preflight FAIL — {c.name}: {c.detail}"
            return GovernedRunResult(
                run_id=run_id,
                policy=pol,
                error=detail,
                preflight_messages=preflight_msgs,
                exit_code=1,
            )
    if not ok:
        return GovernedRunResult(
            run_id=run_id,
            policy=pol,
            error="Preflight failed",
            exit_code=1,
        )

    exec_result = resume_plan(
        store,
        run_id,
        approve=True,
        continue_on_gate_warn=opts.continue_on_gate_warn,
        replace=opts.replace,
        accept_failed_output=opts.accept_failed_output,
        max_steps=opts.max_steps,
        repo_path=opts.repo_path,
    )

    _, meta = store.get_run(run_id)
    plan = load_plan(run_dir)
    ev_ok, ev_skip = maybe_export_evidence(store, run_id, with_evidence=opts.with_evidence)

    result = GovernedRunResult(
        run_id=run_id,
        policy=pol,
        state=meta.state,
        outcome=meta.outcome,
        plan_overall_status=plan.overall_status,
        stopped_at=exec_result.stopped_at,
        run_dir=run_dir,
        preflight_messages=preflight_msgs,
        evidence_exported=ev_ok,
        evidence_skipped_reason=ev_skip,
    )
    result.next_action = build_next_action(
        store,
        run_id,
        repo_path=opts.repo_path,
        plan_overall_status=plan.overall_status,
        stopped_at=exec_result.stopped_at,
    )
    result.exit_code = compute_governed_exit_code(
        plan_overall_status=plan.overall_status,
        state=meta.state,
        stopped_at=exec_result.stopped_at,
        run_dir=run_dir,
        error=None,
    )
    return result
