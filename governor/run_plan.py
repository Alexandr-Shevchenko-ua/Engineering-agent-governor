"""Bounded run plan orchestrator — explicit steps, approvals, hard stops."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from governor.config import check_secret_argv, get_profile, redact_argv_for_display
from governor.dispatch import (
    DEFAULT_TIMEOUT,
    build_runner_spec,
    execute_dispatch,
    format_argv_display,
)
from governor.gates import run_gates, write_gate_artifacts
from governor.models import (
    ROLE_OUTPUT_FILES,
    RunState,
    can_transition,
    record_action_for_role,
)
from governor.policy import get_policy, resolve_policy_name
from governor.repair import prepare_repair
from governor.run_store import RunStore
from governor.trace import TraceLogger
from governor.utils import utc_now_iso
from governor.verdict import parse_validator_verdict

PLAN_VERSION = 1
PLAN_JSON = "12_run_plan.json"
PLAN_MD = "12_run_plan.md"

STEP_STATUSES = frozenset(
    {"PENDING", "RUNNING", "PASS", "FAIL", "SKIPPED", "BLOCKED"}
)
PLAN_ACTIONS = frozenset(
    {
        "dispatch_executor",
        "gate",
        "dispatch_validator",
        "report",
        "repair_prepare",
        "human_checkpoint",
        "stop",
    }
)

APPROVE_REQUIRED_MSG = (
    "Plan includes dispatch steps that require --approve to execute. "
    "Re-run with: python -m governor plan execute --run-id <id> --approve --repo-path ."
)

RESUME_APPROVE_REQUIRED_MSG = (
    "Plan resume includes dispatch steps that require --approve. "
    "Re-run with: python -m governor plan resume --run-id <id> --approve --repo-path ."
)

RESUME_REPAIR_MANUAL_MSG = (
    "Gate failed and repair prompt exists. Dispatch repair manually or start a new plan "
    "after repair — plan resume does not auto-dispatch repair."
)


@dataclass
class PlanStep:
    step_id: str
    action: str
    status: str = "PENDING"
    role: str | None = None
    profile: str | None = None
    runner: str | None = None
    command: list[str] | None = None
    command_display: str | None = None
    approve_required: bool = False
    state_precondition: str | None = None
    output_ref: str | None = None
    reason: str | None = None
    run_on_fail_only: bool = False
    checkpoint_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanStep:
        return cls(
            step_id=data["step_id"],
            action=data["action"],
            status=data.get("status", "PENDING"),
            role=data.get("role"),
            profile=data.get("profile"),
            runner=data.get("runner"),
            command=list(data["command"]) if data.get("command") else None,
            command_display=data.get("command_display"),
            approve_required=data.get("approve_required", False),
            state_precondition=data.get("state_precondition"),
            output_ref=data.get("output_ref"),
            reason=data.get("reason"),
            run_on_fail_only=data.get("run_on_fail_only", False),
            checkpoint_message=data.get("checkpoint_message"),
        )


@dataclass
class RunPlan:
    version: int
    run_id: str
    repo_path: str
    created_at: str
    updated_at: str
    steps: list[PlanStep] = field(default_factory=list)
    auto_repair_prepare_on_fail: bool = False
    stop_on_warn: bool = True
    overall_status: str = "PENDING"
    executor_profile: str | None = None
    validator_profile: str | None = None
    gate_profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["steps"] = [s.to_dict() for s in self.steps]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunPlan:
        steps = [PlanStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            version=data.get("version", PLAN_VERSION),
            run_id=data["run_id"],
            repo_path=data["repo_path"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            steps=steps,
            auto_repair_prepare_on_fail=data.get("auto_repair_prepare_on_fail", False),
            stop_on_warn=data.get("stop_on_warn", True),
            overall_status=data.get("overall_status", "PENDING"),
            executor_profile=data.get("executor_profile"),
            validator_profile=data.get("validator_profile"),
            gate_profile=data.get("gate_profile"),
        )


@dataclass
class PlanExecutionResult:
    overall_status: str
    steps_run: int
    stopped_at: str | None
    message: str
    exit_code: int


def plan_json_path(run_dir: Path) -> Path:
    return run_dir / PLAN_JSON


def plan_md_path(run_dir: Path) -> Path:
    return run_dir / PLAN_MD


def load_plan(run_dir: Path) -> RunPlan:
    path = plan_json_path(run_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"No run plan at {path}. Create with: python -m governor plan create --run-id <id>"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunPlan.from_dict(data)


def save_plan(run_dir: Path, plan: RunPlan) -> None:
    plan.updated_at = utc_now_iso()
    plan_json_path(run_dir).write_text(
        json.dumps(plan.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    plan_md_path(run_dir).write_text(render_plan_markdown(plan), encoding="utf-8")


def plan_status_summary(plan: RunPlan) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in plan.steps:
        counts[s.status] = counts.get(s.status, 0) + 1
    return counts


def next_pending_step(plan: RunPlan) -> PlanStep | None:
    for step in plan.steps:
        if step.status in ("PENDING", "BLOCKED"):
            return step
    return None


@dataclass
class PlanValidationLine:
    level: str  # OK, WARN, FAIL
    message: str


def _gate_fail_with_repair_prepared(run_dir: Path, plan: RunPlan) -> bool:
    from governor.repair_artifacts import list_repair_prompts

    gate = next((s for s in plan.steps if s.step_id == "gate"), None)
    if gate and gate.status == "FAIL" and list_repair_prompts(run_dir):
        return True
    return False


def _prepare_steps_for_resume(
    plan: RunPlan,
    run_dir: Path,
    *,
    replace: bool,
) -> None:
    for step in plan.steps:
        if step.status in ("PASS", "SKIPPED"):
            continue
        if step.action == "human_checkpoint" and step.status == "BLOCKED":
            continue
        if step.status == "FAIL" and step.step_id != "gate":
            step.status = "PENDING"
            step.reason = None
        elif step.status == "BLOCKED" and step.action != "human_checkpoint":
            step.status = "PENDING"
            step.reason = None
        if step.status != "PENDING":
            continue
        if step.action == "dispatch_executor":
            out = run_dir / ROLE_OUTPUT_FILES["executor"]
            if out.is_file() and not replace:
                step.status = "SKIPPED"
                step.reason = "artifact already exists"
        elif step.action == "dispatch_validator":
            out = run_dir / ROLE_OUTPUT_FILES["validator"]
            if out.is_file() and not replace:
                step.status = "SKIPPED"
                step.reason = "artifact already exists"


def validate_plan(store: RunStore, run_id: str) -> tuple[list[PlanValidationLine], bool]:
    """Validate 12_run_plan.json; return (lines, has_fail)."""
    run_dir, meta = store.get_run(run_id)
    lines: list[PlanValidationLine] = []
    has_fail = False

    def add(level: str, message: str) -> None:
        nonlocal has_fail
        lines.append(PlanValidationLine(level=level, message=message))
        if level == "FAIL":
            has_fail = True

    try:
        plan = load_plan(run_dir)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        add("FAIL", f"Cannot load plan: {e}")
        return lines, True

    if plan.version != PLAN_VERSION:
        add("WARN", f"Plan version {plan.version} (expected {PLAN_VERSION})")
    if plan.run_id != meta.run_id:
        add("FAIL", f"Plan run_id {plan.run_id!r} != metadata {meta.run_id!r}")

    seen_ids: set[str] = set()
    repo = Path(meta.repo_path)
    for step in plan.steps:
        if step.step_id in seen_ids:
            add("FAIL", f"Duplicate step_id: {step.step_id}")
        seen_ids.add(step.step_id)
        if step.action not in PLAN_ACTIONS:
            add("FAIL", f"Unknown action {step.action!r} on step {step.step_id}")
        if step.status not in STEP_STATUSES:
            add("FAIL", f"Unknown status {step.status!r} on step {step.step_id}")
        if step.action in ("dispatch_executor", "dispatch_validator"):
            if not step.role:
                add("FAIL", f"Step {step.step_id}: dispatch missing role")
            if not step.profile and not step.runner:
                add("FAIL", f"Step {step.step_id}: dispatch needs profile or runner")
            if step.profile:
                try:
                    prof, _ = get_profile(repo, step.profile)
                    if not prof.enabled:
                        add("FAIL", f"Step {step.step_id}: profile {step.profile!r} disabled")
                except ValueError as e:
                    add("FAIL", f"Step {step.step_id}: {e}")
            if step.command:
                try:
                    check_secret_argv(step.command)
                except ValueError as e:
                    add("FAIL", f"Step {step.step_id}: {e}")
        if step.state_precondition:
            try:
                RunState(step.state_precondition)
            except ValueError:
                add("FAIL", f"Step {step.step_id}: unknown state_precondition")

    if not has_fail:
        add("OK", f"Plan valid ({len(plan.steps)} steps)")
    return lines, has_fail


def approve_checkpoint(
    store: RunStore,
    run_id: str,
    step_id: str,
    *,
    note: str,
) -> PlanStep:
    from governor.evidence import CHECKPOINTS_MD, checkpoints_path

    if not note or not note.strip():
        raise ValueError("Checkpoint approval requires --note")

    run_dir, meta = store.get_run(run_id)
    plan = load_plan(run_dir)
    step = next((s for s in plan.steps if s.step_id == step_id), None)
    if step is None:
        raise ValueError(f"Unknown step_id {step_id!r}")
    if step.action != "human_checkpoint":
        raise ValueError(f"Step {step_id!r} is not a human_checkpoint (action={step.action})")
    if step.status == "PASS":
        raise ValueError(f"Checkpoint {step_id!r} already approved")

    step.status = "PASS"
    step.reason = note.strip()
    plan.updated_at = utc_now_iso()
    save_plan(run_dir, plan)

    cp_path = checkpoints_path(run_dir)
    header = f"## {step_id} — {utc_now_iso()}\n\n"
    block = (
        f"{header}"
        f"**Message:** {step.checkpoint_message or '(none)'}\n\n"
        f"**Note:** {note.strip()}\n\n"
    )
    if cp_path.is_file():
        cp_path.write_text(cp_path.read_text(encoding="utf-8") + "\n" + block, encoding="utf-8")
    else:
        cp_path.write_text(f"# Human checkpoints\n\n{block}", encoding="utf-8")

    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="plan",
        actor="human",
        action="human_checkpoint_approve",
        output_ref=CHECKPOINTS_MD,
        status="ok",
        reason=f"{step_id}: {note.strip()[:120]}",
    )
    store.append_command(
        run_id,
        f"python -m governor plan checkpoint --run-id {run_id} "
        f"--step-id {step_id} --approve --note \"...\"",
    )
    return step


def render_plan_markdown(plan: RunPlan) -> str:
    lines = [
        "# Run plan",
        "",
        f"**Run ID:** `{plan.run_id}`",
        f"**Overall status:** {plan.overall_status}",
        f"**Auto repair prepare on fail:** {plan.auto_repair_prepare_on_fail}",
        f"**Stop on gate WARN:** {plan.stop_on_warn}",
    ]
    if plan.gate_profile:
        lines.append(f"**Gate profile:** `{plan.gate_profile}`")
    lines.extend(
        [
            "",
            "| Step | Action | Status | Profile/Runner | Reason |",
            "|------|--------|--------|----------------|--------|",
        ]
    )
    for s in plan.steps:
        if s.action == "stop":
            continue
        runner_col = s.profile or s.runner or "-"
        if s.command_display:
            runner_col += f" ({s.command_display})"
        lines.append(
            f"| {s.step_id} | {s.action} | {s.status} | {runner_col} | {s.reason or ''} |"
        )
    lines.extend(
        [
            "",
            "> Bounded orchestration — not autopilot. Dispatch steps require `--approve`.",
            "> No automatic repair dispatch; repair prepare only on failure when enabled.",
        ]
    )
    return "\n".join(lines) + "\n"


def _validate_runner_spec(
    repo: Path,
    *,
    profile: str | None,
    runner: str | None,
    command: list[str] | None,
    label: str,
) -> tuple[str | None, str | None, list[str] | None, str | None]:
    """Return (profile, runner, command argv, command_display)."""
    if profile and runner:
        raise ValueError(f"{label}: specify profile or runner, not both")
    if not profile and not runner:
        raise ValueError(f"{label}: provide --{label}-profile or --{label}-runner")

    if profile:
        prof, _ = get_profile(repo, profile)
        if not prof.enabled:
            raise ValueError(f"Profile {profile!r} is disabled")
        return profile, None, None, None

    assert runner is not None
    if runner == "command":
        if not command:
            raise ValueError(
                f"{label}: --runner command requires --{label}-command with executable and args"
            )
        check_secret_argv(command)
        display = format_argv_display(redact_argv_for_display(command))
        return None, runner, list(command), display
    if runner in ("echo", "cursor"):
        return None, runner, None, None
    raise ValueError(f"{label}: invalid runner {runner!r}")


def _make_dispatch_step(
    step_id: str,
    action: str,
    role: str,
    *,
    profile: str | None,
    runner: str | None,
    command: list[str] | None,
    command_display: str | None,
    output_ref: str,
    state_precondition: str | None,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        action=action,
        role=role,
        profile=profile,
        runner=runner,
        command=command,
        command_display=command_display,
        approve_required=True,
        state_precondition=state_precondition,
        output_ref=output_ref,
        status="PENDING",
    )


def _insert_checkpoints(
    steps: list[PlanStep],
    checkpoints: list[tuple[str, str]],
) -> list[PlanStep]:
    if not checkpoints:
        return steps
    after_map = dict(checkpoints)
    out: list[PlanStep] = []
    for step in steps:
        out.append(step)
        if step.step_id in after_map:
            msg = after_map[step.step_id]
            out.append(
                PlanStep(
                    step_id=f"checkpoint_after_{step.step_id}",
                    action="human_checkpoint",
                    status="PENDING",
                    checkpoint_message=msg,
                    reason=msg,
                    output_ref="13_human_checkpoints.md",
                )
            )
    return out


def build_default_plan(
    store: RunStore,
    run_id: str,
    *,
    executor_profile: str | None,
    executor_runner: str | None,
    executor_command: list[str] | None,
    validator_profile: str | None,
    validator_runner: str | None,
    validator_command: list[str] | None,
    auto_repair_prepare_on_fail: bool,
    stop_on_warn: bool = True,
    checkpoints: list[tuple[str, str]] | None = None,
    gate_profile: str | None = None,
) -> RunPlan:
    run_dir, meta = store.get_run(run_id)
    repo = Path(meta.repo_path)

    ex_prof, ex_run, ex_cmd, ex_disp = _validate_runner_spec(
        repo,
        profile=executor_profile,
        runner=executor_runner,
        command=executor_command,
        label="executor",
    )
    val_prof, val_run, val_cmd, val_disp = _validate_runner_spec(
        repo,
        profile=validator_profile,
        runner=validator_runner,
        command=validator_command,
        label="validator",
    )

    steps = [
        _make_dispatch_step(
            "dispatch_executor",
            "dispatch_executor",
            "executor",
            profile=ex_prof,
            runner=ex_run,
            command=ex_cmd,
            command_display=ex_disp,
            output_ref=ROLE_OUTPUT_FILES["executor"],
            state_precondition=RunState.EXECUTOR_PROMPT_READY.value,
        ),
        PlanStep(
            step_id="gate",
            action="gate",
            output_ref="08_gate_results.json",
            state_precondition=RunState.EXECUTOR_OUTPUT_RECORDED.value,
        ),
        _make_dispatch_step(
            "dispatch_validator",
            "dispatch_validator",
            "validator",
            profile=val_prof,
            runner=val_run,
            command=val_cmd,
            command_display=val_disp,
            output_ref=ROLE_OUTPUT_FILES["validator"],
            state_precondition=RunState.GATES_RUN.value,
        ),
        PlanStep(
            step_id="report",
            action="report",
            output_ref="09_final_report.md",
        ),
    ]
    if auto_repair_prepare_on_fail:
        steps.append(
            PlanStep(
                step_id="repair_prepare_on_fail",
                action="repair_prepare",
                run_on_fail_only=True,
                status="PENDING",
                reason="Runs only after gate/validator failure; then plan stops",
            )
        )

    steps = _insert_checkpoints(steps, checkpoints or [])

    now = utc_now_iso()
    return RunPlan(
        version=PLAN_VERSION,
        run_id=meta.run_id,
        repo_path=str(repo),
        created_at=now,
        updated_at=now,
        steps=steps,
        auto_repair_prepare_on_fail=auto_repair_prepare_on_fail,
        stop_on_warn=stop_on_warn,
        executor_profile=ex_prof,
        validator_profile=val_prof,
        gate_profile=gate_profile,
    )


def _merge_policy_checkpoints(
    policy_checkpoints: list[tuple[str, str]],
    cli_checkpoints: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    merged = list(policy_checkpoints)
    seen = {a for a, _ in merged}
    for after, msg in cli_checkpoints:
        if after not in seen:
            merged.append((after, msg))
            seen.add(after)
    return merged


def resolve_plan_policy_options(
    meta,
    *,
    policy_name: str | None = None,
    auto_repair_prepare_on_fail: bool | None = None,
    checkpoints: list[tuple[str, str]] | None = None,
) -> tuple[str, bool, list[tuple[str, str]], object]:
    """Return (policy_name, auto_repair, checkpoints, PolicyPack)."""
    pol = resolve_policy_name(policy_name or getattr(meta, "policy", None))
    pack = get_policy(pol)
    auto = (
        auto_repair_prepare_on_fail
        if auto_repair_prepare_on_fail is not None
        else pack.plan_defaults.auto_repair_prepare_on_fail
    )
    policy_cps = list(pack.plan_defaults.checkpoints) or list(pack.default_checkpoints)
    cli_cps = checkpoints or []
    if cli_cps:
        cps = _merge_policy_checkpoints(policy_cps, cli_cps)
    else:
        cps = policy_cps
    return pol, auto, cps, pack


def create_plan(
    store: RunStore,
    run_id: str,
    *,
    executor_profile: str | None = None,
    executor_runner: str | None = None,
    executor_command: list[str] | None = None,
    validator_profile: str | None = None,
    validator_runner: str | None = None,
    validator_command: list[str] | None = None,
    auto_repair_prepare_on_fail: bool | None = None,
    force: bool = False,
    dry_run: bool = False,
    checkpoints: list[tuple[str, str]] | None = None,
    policy_name: str | None = None,
    gate_profile: str | None = None,
) -> RunPlan:
    run_dir, meta = store.get_run(run_id)
    if plan_json_path(run_dir).exists() and not force:
        raise FileExistsError(
            f"Plan already exists at {plan_json_path(run_dir)}. Use --force to overwrite."
        )

    pol, effective_auto, effective_cps, pack = resolve_plan_policy_options(
        meta,
        policy_name=policy_name,
        auto_repair_prepare_on_fail=auto_repair_prepare_on_fail,
        checkpoints=checkpoints,
    )

    from governor.project_config import resolve_gate_profile_for_repo

    repo = Path(meta.repo_path)
    resolved_gate_profile = resolve_gate_profile_for_repo(repo, gate_profile)

    plan = build_default_plan(
        store,
        run_id,
        executor_profile=executor_profile,
        executor_runner=executor_runner,
        executor_command=executor_command,
        validator_profile=validator_profile,
        validator_runner=validator_runner,
        validator_command=validator_command,
        auto_repair_prepare_on_fail=effective_auto,
        checkpoints=effective_cps or None,
        gate_profile=resolved_gate_profile,
    )

    if dry_run:
        return plan

    save_plan(run_dir, plan)
    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="plan",
        actor="governor",
        action="plan_create",
        output_ref=PLAN_JSON,
        status="ok",
        reason=(
            f"steps={len(plan.steps)} policy={pol} auto_repair={effective_auto} "
            f"checkpoints={len(effective_cps)}"
        ),
    )
    cmd = f"python -m governor plan create --run-id {run_id}"
    if policy_name or meta.policy:
        cmd += f" --policy {pol}"
    if resolved_gate_profile:
        cmd += f" --gate-profile {resolved_gate_profile}"
    store.append_command(run_id, cmd)
    if pack.plan_defaults.recommend_evidence_export:
        store.append_command(
            run_id,
            f"# Recommended after closure: python -m governor evidence export --run-id {run_id}",
        )
    return plan


def _resolve_step_spec(
    repo: Path,
    step: PlanStep,
) -> tuple[object, int, str | None]:
    """Return RunnerSpec, timeout, profile_name."""
    if step.profile:
        prof, spec = get_profile(repo, step.profile)
        return spec, prof.timeout, step.profile
    timeout = DEFAULT_TIMEOUT
    spec = build_runner_spec(step.runner or "echo", step.command)
    return spec, timeout, None


def _maybe_auto_repair(
    store: RunStore,
    run_dir: Path,
    plan: RunPlan,
    run_id: str,
    reason: str,
) -> bool:
    """Run repair prepare if enabled; return True if plan should stop."""
    if not plan.auto_repair_prepare_on_fail:
        return False
    try:
        prepare_repair(store, run_id, reason=reason)
        for s in plan.steps:
            if s.action == "repair_prepare" and s.run_on_fail_only:
                s.status = "PASS"
                s.reason = reason[:200]
        return True
    except (ValueError, FileExistsError) as e:
        for s in plan.steps:
            if s.action == "repair_prepare" and s.run_on_fail_only:
                s.status = "FAIL"
                s.reason = str(e)
        return True


def _execute_dispatch_step(
    store: RunStore,
    run_dir: Path,
    meta,
    plan: RunPlan,
    step: PlanStep,
    *,
    replace: bool,
    accept_failed_output: bool,
    repo_path: str,
) -> tuple[str, int]:
    """Return step status and process exit code hint."""
    role = step.role or ("executor" if "executor" in step.action else "validator")
    out_path = run_dir / (step.output_ref or ROLE_OUTPUT_FILES[role])
    if out_path.exists() and not replace:
        step.reason = "already satisfied"
        return "SKIPPED", 0

    repo = Path(meta.repo_path)
    spec, timeout, profile_name = _resolve_step_spec(repo, step)
    _, result = execute_dispatch(
        store,
        meta.run_id,
        role,
        spec,
        timeout,
        replace=replace,
        repo_path=repo_path,
        accept_failed_output=accept_failed_output,
        profile_name=profile_name,
    )
    if result.exit_code != 0 and not accept_failed_output:
        step.reason = f"exit_code={result.exit_code}"
        if plan.auto_repair_prepare_on_fail:
            _maybe_auto_repair(
                store,
                run_dir,
                plan,
                meta.run_id,
                f"Dispatch {role} failed (exit {result.exit_code})",
            )
        return "FAIL", result.exit_code
    step.output_ref = out_path.name
    return "PASS", result.exit_code


def _execute_gate_step(
    store: RunStore,
    run_dir: Path,
    meta,
    plan: RunPlan,
    step: PlanStep,
    *,
    continue_on_gate_warn: bool,
) -> tuple[str, int]:
    if not (run_dir / ROLE_OUTPUT_FILES["executor"]).is_file():
        return "BLOCKED", 1

    target_repo = Path(meta.repo_path)
    report = run_gates(target_repo, gate_profile=plan.gate_profile)
    write_gate_artifacts(run_dir, report)
    store.update_state(meta.run_id, "gate")
    store.append_command(meta.run_id, f"python -m governor gate --run-id {meta.run_id}")

    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="gate",
        actor="governor",
        action="gate",
        output_ref="08_gate_results.json",
        status=report.overall.lower(),
        reason=f"overall={report.overall}",
    )

    step.output_ref = "08_gate_results.json"
    if report.overall == "FAIL":
        step.reason = "gate overall FAIL"
        if _maybe_auto_repair(
            store,
            run_dir,
            plan,
            meta.run_id,
            "Gate overall FAIL",
        ):
            return "FAIL", 2
        return "FAIL", 2

    if report.overall == "WARN" and plan.stop_on_warn and not continue_on_gate_warn:
        step.reason = "gate overall WARN (stop_on_warn)"
        return "FAIL", 2

    return "PASS", 0 if report.overall == "PASS" else 2


def execute_plan(
    store: RunStore,
    run_id: str,
    *,
    approve: bool = False,
    until: str | None = None,
    dry_run: bool = False,
    stop_on_warn: bool | None = None,
    continue_on_gate_warn: bool = False,
    replace: bool = False,
    accept_failed_output: bool = False,
    max_steps: int = 10,
    repo_path: str = ".",
    resume: bool = False,
) -> PlanExecutionResult:
    run_dir, meta = store.get_run(run_id)
    plan = load_plan(run_dir)

    if stop_on_warn is not None:
        plan.stop_on_warn = stop_on_warn

    approve_msg = RESUME_APPROVE_REQUIRED_MSG if resume else APPROVE_REQUIRED_MSG

    if resume and not dry_run:
        blocked = _gate_fail_with_repair_prepared(run_dir, plan)
        if blocked:
            return PlanExecutionResult(
                overall_status="BLOCKED",
                steps_run=0,
                stopped_at="gate",
                message=RESUME_REPAIR_MANUAL_MSG,
                exit_code=1,
            )
        _prepare_steps_for_resume(plan, run_dir, replace=replace)
        save_plan(run_dir, plan)

    dispatch_steps = [
        s
        for s in plan.steps
        if s.action in ("dispatch_executor", "dispatch_validator")
        and s.status == "PENDING"
    ]
    if dispatch_steps and not approve and not dry_run:
        return PlanExecutionResult(
            overall_status="BLOCKED",
            steps_run=0,
            stopped_at=None,
            message=approve_msg,
            exit_code=1,
        )

    if dry_run:
        prefix = "Resume dry run" if resume else "Dry run"
        lines = [f"{prefix} — would execute:"]
        for s in plan.steps:
            if s.action == "stop":
                continue
            if resume and s.status in ("PASS", "SKIPPED"):
                continue
            if not resume and s.status != "PENDING":
                continue
            if resume and s.status not in ("PENDING", "BLOCKED"):
                continue
            lines.append(f"  - {s.step_id}: {s.action} ({s.status})")
        return PlanExecutionResult(
            overall_status=plan.overall_status,
            steps_run=0,
            stopped_at=None,
            message="\n".join(lines),
            exit_code=0,
        )

    trace = TraceLogger(run_dir, meta.run_id)
    start_action = "plan_resume_start" if resume else "plan_execute_start"
    stop_action = "plan_resume_stop" if resume else "plan_execute_stop"
    trace.append(
        phase="plan",
        actor="governor",
        action=start_action,
        output_ref=PLAN_JSON,
        status="ok",
    )
    plan.overall_status = "RUNNING"
    save_plan(run_dir, plan)

    steps_run = 0
    stopped_at: str | None = None
    exit_code = 0

    for step in plan.steps:
        if step.action == "stop":
            continue
        if step.run_on_fail_only:
            continue
        if resume and step.status in ("PASS", "SKIPPED"):
            continue
        if not resume and step.status not in ("PENDING", "RUNNING"):
            continue
        if resume and step.status not in ("PENDING", "RUNNING", "BLOCKED"):
            continue
        if steps_run >= max_steps:
            plan.overall_status = "BLOCKED"
            stopped_at = step.step_id
            step.status = "BLOCKED"
            step.reason = f"max_steps ({max_steps}) reached"
            save_plan(run_dir, plan)
            break

        _, meta = store.get_run(run_id)
        state = RunState(meta.state)

        if step.action == "dispatch_validator":
            if not (run_dir / ROLE_OUTPUT_FILES["executor"]).is_file():
                step.status = "BLOCKED"
                step.reason = "executor output missing"
                plan.overall_status = "BLOCKED"
                stopped_at = step.step_id
                save_plan(run_dir, plan)
                break

        if step.state_precondition and step.action.startswith("dispatch"):
            action = record_action_for_role(step.role or "executor")
            if not can_transition(state, action) and not (
                step.action == "dispatch_executor"
                and (run_dir / ROLE_OUTPUT_FILES["executor"]).exists()
            ):
                if step.action == "dispatch_validator" and (
                    run_dir / ROLE_OUTPUT_FILES["validator"]
                ).exists() and not replace:
                    pass
                elif not can_transition(state, action):
                    step.status = "BLOCKED"
                    step.reason = f"state {state.value} invalid for {action}"
                    plan.overall_status = "BLOCKED"
                    stopped_at = step.step_id
                    save_plan(run_dir, plan)
                    break

        step.status = "RUNNING"
        save_plan(run_dir, plan)
        trace.append(
            phase="plan",
            actor="governor",
            action="plan_step_start",
            output_ref=step.step_id,
            status="ok",
            reason=step.action,
        )

        steps_run += 1
        step_status = "FAIL"
        step_exit = 1

        try:
            if step.action == "dispatch_executor":
                step_status, step_exit = _execute_dispatch_step(
                    store,
                    run_dir,
                    meta,
                    plan,
                    step,
                    replace=replace,
                    accept_failed_output=accept_failed_output,
                    repo_path=repo_path,
                )
            elif step.action == "gate":
                step_status, step_exit = _execute_gate_step(
                    store,
                    run_dir,
                    meta,
                    plan,
                    step,
                    continue_on_gate_warn=continue_on_gate_warn,
                )
            elif step.action == "dispatch_validator":
                step_status, step_exit = _execute_dispatch_step(
                    store,
                    run_dir,
                    meta,
                    plan,
                    step,
                    replace=replace,
                    accept_failed_output=accept_failed_output,
                    repo_path=repo_path,
                )
                if step_status == "PASS":
                    val_text = (run_dir / ROLE_OUTPUT_FILES["validator"]).read_text(
                        encoding="utf-8"
                    )
                    verdict = parse_validator_verdict(val_text)
                    if verdict == "REPAIR_REQUIRED" and plan.auto_repair_prepare_on_fail:
                        _maybe_auto_repair(
                            store,
                            run_dir,
                            plan,
                            meta.run_id,
                            "Validator verdict REPAIR_REQUIRED",
                        )
                        step_status = "FAIL"
                        step.reason = "validator REPAIR_REQUIRED"
                        step_exit = 1
            elif step.action == "report":
                from governor.report import generate_reports

                generate_reports(store, run_id)
                store.append_command(
                    run_id,
                    f"python -m governor plan execute --run-id {run_id} --approve",
                )
                step_status = "PASS"
                step_exit = 0
            elif step.action == "repair_prepare":
                prepare_repair(store, run_id, reason="Plan step repair_prepare")
                step_status = "PASS"
                step_exit = 0
                plan.overall_status = "STOPPED"
                stopped_at = step.step_id
            elif step.action == "human_checkpoint":
                if step.status == "PASS":
                    step_status, step_exit = "PASS", 0
                else:
                    msg = step.checkpoint_message or "Human review required"
                    step.reason = (
                        f"{msg}. Approve: python -m governor plan checkpoint "
                        f"--run-id {meta.run_id} --step-id {step.step_id} "
                        f"--approve --note \"...\""
                    )
                    step_status = "BLOCKED"
                    step_exit = 1
            else:
                step.status = "BLOCKED"
                step.reason = f"unknown action {step.action}"
                break
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            step_status = "FAIL"
            step.reason = str(e)
            step_exit = 1

        step.status = step_status
        trace.append(
            phase="plan",
            actor="governor",
            action="plan_step_finish",
            output_ref=step.step_id,
            status="ok" if step_status == "PASS" else "fail",
            reason=step.reason or step.action,
        )
        save_plan(run_dir, plan)

        if step_status in ("FAIL", "BLOCKED"):
            plan.overall_status = step_status
            stopped_at = step.step_id
            exit_code = step_exit if step_exit else 1
            if step.action == "repair_prepare" or (
                plan.auto_repair_prepare_on_fail and step_status == "FAIL"
            ):
                plan.overall_status = "STOPPED"
            save_plan(run_dir, plan)
            break

        if until and step.step_id == until:
            stopped_at = step.step_id
            plan.overall_status = "STOPPED"
            save_plan(run_dir, plan)
            break

        exit_code = max(exit_code, step_exit)

    else:
        if plan.overall_status == "RUNNING":
            plan.overall_status = "PASS"

    save_plan(run_dir, plan)
    trace.append(
        phase="plan",
        actor="governor",
        action=stop_action,
        output_ref=PLAN_JSON,
        status=plan.overall_status.lower(),
        reason=stopped_at or "complete",
    )

    _, meta = store.get_run(run_id)
    label = "Resume" if resume else "Plan"
    msg = f"{label} {plan.overall_status}"
    if stopped_at:
        msg += f" at step {stopped_at}"
    msg += f"; run state={meta.state}"
    return PlanExecutionResult(
        overall_status=plan.overall_status,
        steps_run=steps_run,
        stopped_at=stopped_at,
        message=msg,
        exit_code=0 if plan.overall_status == "PASS" else exit_code or 1,
    )


def resume_plan(
    store: RunStore,
    run_id: str,
    **kwargs: Any,
) -> PlanExecutionResult:
    """Resume an existing plan from the first incomplete step."""
    return execute_plan(store, run_id, resume=True, **kwargs)
