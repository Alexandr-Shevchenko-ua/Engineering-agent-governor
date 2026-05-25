"""CLI entrypoint for Engineering Agent Governor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from governor import __version__
from governor.config import (
    CONFIG_NOT_FOUND_MSG,
    config_path,
    get_profile,
    init_config,
    load_profiles,
    redact_argv_for_display,
    validate_config_file,
)
from governor.dispatch import (
    DEFAULT_TIMEOUT,
    build_runner_spec,
    execute_dispatch,
    format_argv_display,
    preview_dispatch,
    validate_timeout,
)
from governor.doctor import run_doctor
from governor.gates import run_gates, write_gate_artifacts
from governor.index import list_entries
from governor.models import NEXT_ACTIONS, RunState
from governor.repair import list_repair_artifacts, prepare_repair
from governor.report import generate_reports
from governor.evidence import EVIDENCE_JSON, EVIDENCE_MD, evidence_json_path, export_evidence
from governor.run_plan import (
    APPROVE_REQUIRED_MSG,
    PLAN_JSON,
    RESUME_APPROVE_REQUIRED_MSG,
    approve_checkpoint,
    create_plan,
    execute_plan,
    load_plan,
    next_pending_step,
    plan_json_path,
    plan_status_summary,
    render_plan_markdown,
    resume_plan,
    validate_plan,
)
from governor.run_store import init_store, open_store
from governor.trace import TraceLogger
from governor.utils import resolve_repo_path


def _repo_path_from_args(args: argparse.Namespace) -> str:
    return getattr(args, "repo_path", ".")


def _add_repo_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo-path",
        default=".",
        help="Target repository path (default: current directory)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    _add_repo_path(parent)

    parser = argparse.ArgumentParser(
        prog="governor",
        description="Engineering Agent Governor — local delegation-first control plane.",
        parents=[parent],
    )
    parser.add_argument("--version", action="version", version=f"governor {__version__}")

    sub = parser.add_subparsers(dest="command", required=False)

    p_init = sub.add_parser("init", help="Create a new governor run", parents=[parent])
    p_init.add_argument("--task", required=True, help="Task title / objective")

    p_status = sub.add_parser("status", help="Show run status", parents=[parent])
    p_status.add_argument("--run-id", default=None, help="Run ID (default: latest)")
    p_status.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    p_record = sub.add_parser("record", help="Record delegated agent output", parents=[parent])
    p_record.add_argument("--run-id", required=True)
    p_record.add_argument(
        "--role",
        required=True,
        choices=["executor", "validator", "repair", "human_note"],
    )
    p_record.add_argument("--file", type=Path, default=None, help="Markdown/text file")
    p_record.add_argument("--text", default=None, help="Inline text content")
    p_record.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite existing executor/validator output (default: protect audit trail)",
    )

    p_gate = sub.add_parser("gate", help="Run deterministic local gates", parents=[parent])
    p_gate.add_argument("--run-id", required=True)

    p_report = sub.add_parser("report", help="Generate final report and lead update", parents=[parent])
    p_report.add_argument("--run-id", required=True)

    p_list = sub.add_parser("list", help="List governor runs (newest first)", parents=[parent])
    p_list.add_argument("--limit", type=int, default=None, help="Max runs to show")
    p_list.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    p_doctor = sub.add_parser("doctor", help="Readiness check for repo and governor state", parents=[parent])

    p_dispatch = sub.add_parser(
        "dispatch",
        help="Preview or execute bounded local runner (requires --approve to run)",
        parents=[parent],
    )
    p_dispatch.add_argument("--run-id", required=True)
    p_dispatch.add_argument(
        "--role",
        required=True,
        choices=["executor", "validator", "repair"],
    )
    p_dispatch.add_argument(
        "--repair-prompt",
        type=int,
        default=None,
        metavar="N",
        help="Repair prompt index (11_repair_prompt_N.md); default: latest",
    )
    runner_group = p_dispatch.add_mutually_exclusive_group(required=True)
    runner_group.add_argument(
        "--runner",
        choices=["echo", "command", "cursor"],
        help="Builtin runner: echo (safe test), command (explicit argv), cursor (placeholder)",
    )
    runner_group.add_argument(
        "--profile",
        metavar="NAME",
        help="Named runner profile from .governor/config.json (see: governor config init)",
    )
    p_dispatch.add_argument(
        "--allow-disabled-profile",
        action="store_true",
        help="Allow dispatch with a disabled config profile (default: fail)",
    )
    p_dispatch.add_argument(
        "--approve",
        action="store_true",
        help="Execute runner; without this flag only preview is shown",
    )
    p_dispatch.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite existing executor/validator output",
    )
    p_dispatch.add_argument(
        "--accept-failed-output",
        action="store_true",
        help="On non-zero exit, write canonical output and transition (default: .failed.md only)",
    )
    p_dispatch.add_argument(
        "--timeout",
        type=int,
        default=None,
        help=(
            f"Max seconds for command runner (default {DEFAULT_TIMEOUT} or profile timeout; max 1800)"
        ),
    )
    p_dispatch.add_argument(
        "--command",
        dest="runner_argv",
        nargs="*",
        default=None,
        metavar="ARG",
        help="Executable and args for --runner command; place after other flags (prompt on stdin)",
    )

    p_config = sub.add_parser(
        "config",
        help="Manage local runner profiles (.governor/config.json)",
        parents=[parent],
    )
    config_sub = p_config.add_subparsers(dest="config_cmd", required=True)

    p_cfg_init = config_sub.add_parser("init", help="Create default config.json", parents=[parent])
    p_cfg_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config",
    )

    config_sub.add_parser("show", help="Show profiles (argv redacted)", parents=[parent])
    config_sub.add_parser("validate", help="Validate config.json", parents=[parent])
    config_sub.add_parser("path", help="Print expected config path", parents=[parent])

    p_repair = sub.add_parser(
        "repair",
        help="Prepare bounded repair prompts (not autopilot)",
        parents=[parent],
    )
    repair_sub = p_repair.add_subparsers(dest="repair_cmd", required=True)

    p_rep_prepare = repair_sub.add_parser(
        "prepare",
        help="Generate 11_repair_prompt_N.md from gate/validator context",
        parents=[parent],
    )
    p_rep_prepare.add_argument("--run-id", required=True)
    p_rep_prepare.add_argument(
        "--reason",
        default="Address gate/validator findings",
        help="Short reason shown in repair prompt",
    )
    p_rep_prepare.add_argument(
        "--force",
        action="store_true",
        help="Allow prepare from unusual states or exceed max prompts",
    )
    p_rep_prepare.add_argument(
        "--max-repairs",
        type=int,
        default=2,
        help="Max repair prompts per run (default 2)",
    )

    p_rep_list = repair_sub.add_parser(
        "list",
        help="List repair prompts and outputs for a run",
        parents=[parent],
    )
    p_rep_list.add_argument("--run-id", required=True)

    p_plan = sub.add_parser(
        "plan",
        help="Bounded run plan orchestrator (explicit steps, --approve for dispatch)",
        parents=[parent],
    )
    plan_sub = p_plan.add_subparsers(dest="plan_cmd", required=True)

    p_plan_create = plan_sub.add_parser("create", help="Write 12_run_plan.json", parents=[parent])
    p_plan_create.add_argument("--run-id", required=True)
    p_plan_create.add_argument("--executor-profile", default=None)
    p_plan_create.add_argument("--validator-profile", default=None)
    p_plan_create.add_argument(
        "--executor-runner",
        choices=["echo", "command", "cursor"],
        default=None,
    )
    p_plan_create.add_argument(
        "--validator-runner",
        choices=["echo", "command", "cursor"],
        default=None,
    )
    p_plan_create.add_argument(
        "--executor-command",
        dest="executor_command",
        nargs="*",
        default=None,
        metavar="ARG",
    )
    p_plan_create.add_argument(
        "--validator-command",
        dest="validator_command",
        nargs="*",
        default=None,
        metavar="ARG",
    )
    p_plan_create.add_argument(
        "--auto-repair-prepare-on-fail",
        action="store_true",
        help="On gate/validator fail, run repair prepare then stop (no repair dispatch)",
    )
    p_plan_create.add_argument("--force", action="store_true")
    p_plan_create.add_argument("--dry-run", action="store_true")
    p_plan_create.add_argument(
        "--checkpoint",
        action="append",
        default=[],
        help="Checkpoint message (pair with --checkpoint-after)",
    )
    p_plan_create.add_argument(
        "--checkpoint-after",
        action="append",
        default=[],
        metavar="STEP_ID",
        help="Insert human_checkpoint after this step (e.g. gate, validator)",
    )

    p_plan_show = plan_sub.add_parser("show", help="Show plan steps", parents=[parent])
    p_plan_show.add_argument("--run-id", required=True)
    p_plan_show.add_argument("--json", action="store_true", dest="as_json")

    p_plan_exec = plan_sub.add_parser(
        "execute",
        help="Execute plan steps sequentially (bounded)",
        parents=[parent],
    )
    p_plan_exec.add_argument("--run-id", required=True)
    p_plan_exec.add_argument(
        "--approve",
        action="store_true",
        help="Required to run dispatch steps in the plan",
    )
    p_plan_exec.add_argument("--until", default=None, metavar="STEP_ID")
    p_plan_exec.add_argument("--dry-run", action="store_true")
    p_plan_exec.add_argument(
        "--continue-on-gate-warn",
        action="store_true",
        help="Continue plan when gate returns WARN (default: stop on WARN)",
    )
    p_plan_exec.add_argument("--replace", action="store_true")
    p_plan_exec.add_argument("--accept-failed-output", action="store_true")
    p_plan_exec.add_argument("--max-steps", type=int, default=10)

    p_plan_resume = plan_sub.add_parser(
        "resume",
        help="Resume plan from first incomplete step (not autopilot)",
        parents=[parent],
    )
    p_plan_resume.add_argument("--run-id", required=True)
    p_plan_resume.add_argument("--approve", action="store_true")
    p_plan_resume.add_argument("--until", default=None, metavar="STEP_ID")
    p_plan_resume.add_argument("--dry-run", action="store_true")
    p_plan_resume.add_argument("--continue-on-gate-warn", action="store_true")
    p_plan_resume.add_argument("--replace", action="store_true")
    p_plan_resume.add_argument("--accept-failed-output", action="store_true")
    p_plan_resume.add_argument("--max-steps", type=int, default=10)

    p_plan_validate = plan_sub.add_parser(
        "validate",
        help="Validate 12_run_plan.json",
        parents=[parent],
    )
    p_plan_validate.add_argument("--run-id", required=True)

    p_plan_checkpoint = plan_sub.add_parser(
        "checkpoint",
        help="Approve a human_checkpoint step",
        parents=[parent],
    )
    p_plan_checkpoint.add_argument("--run-id", required=True)
    p_plan_checkpoint.add_argument("--step-id", required=True)
    p_plan_checkpoint.add_argument("--approve", action="store_true", required=True)
    p_plan_checkpoint.add_argument("--note", required=True, help="Required approval note")

    p_evidence = sub.add_parser(
        "evidence",
        help="Export lead/MR review evidence bundle",
        parents=[parent],
    )
    evidence_sub = p_evidence.add_subparsers(dest="evidence_cmd", required=True)
    p_ev_export = evidence_sub.add_parser("export", help="Write 14_evidence_bundle.*", parents=[parent])
    p_ev_export.add_argument("--run-id", required=True)
    p_ev_export.add_argument(
        "--format",
        choices=["both", "markdown", "json"],
        default="both",
        help="Output format (default: both md and json)",
    )
    p_ev_export.add_argument(
        "--include-prompts",
        action="store_true",
        help="Include full prompt bodies in JSON bundle",
    )

    return parser


def _parse_checkpoints(
    messages: list[str],
    after_steps: list[str],
) -> list[tuple[str, str]]:
    if not after_steps:
        return []
    out: list[tuple[str, str]] = []
    for i, after in enumerate(after_steps):
        msg = messages[i] if i < len(messages) else "Human review required"
        out.append((after, msg))
    return out


def _status_payload(store: RunStore, run_dir: Path, meta) -> dict:
    plan_summary: dict | None = None
    next_plan: str | None = None
    if plan_json_path(run_dir).is_file():
        try:
            plan = load_plan(run_dir)
            plan_summary = {
                "overall_status": plan.overall_status,
                "step_counts": plan_status_summary(plan),
            }
            nxt = next_pending_step(plan)
            if nxt:
                next_plan = f"{nxt.step_id} ({nxt.action})"
        except (ValueError, json.JSONDecodeError):
            plan_summary = {"error": "unreadable"}

    return {
        "run_id": meta.run_id,
        "task": meta.task,
        "state": meta.state,
        "outcome": meta.outcome,
        "repair_count": meta.repair_count,
        "repair_prompt_count": getattr(meta, "repair_prompt_count", 0),
        "plan": plan_summary,
        "next_plan_step": next_plan,
        "next_action": NEXT_ACTIONS.get(RunState(meta.state), ""),
        "evidence_bundle_exists": evidence_json_path(run_dir).is_file()
        or (run_dir / EVIDENCE_MD).is_file(),
        "folder": str(run_dir),
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
    }


def cmd_init(args: argparse.Namespace) -> int:
    store = init_store(_repo_path_from_args(args))
    run_dir, meta = store.create_run(args.task)
    print(f"Created run: {meta.run_id}")
    print(f"Folder: {run_dir}")
    print(f"State: {meta.state}")
    print(f"Next: {NEXT_ACTIONS.get(RunState(meta.state), '')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        run_dir, meta = store.get_run(args.run_id)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(_status_payload(store, run_dir, meta), indent=2, ensure_ascii=False))
        return 0

    artifacts = store.list_artifacts(run_dir)
    print(f"Run ID:     {meta.run_id}")
    print(f"Task:       {meta.task}")
    print(f"State:      {meta.state}")
    print(f"Created:    {meta.created_at}")
    print(f"Updated:    {meta.updated_at}")
    print(f"Folder:     {run_dir}")
    print(f"Outcome:    {meta.outcome or '(pending)'}")
    print(f"Repair:     count={meta.repair_count} prompts={getattr(meta, 'repair_prompt_count', 0)}")
    print(f"Artifacts:  {', '.join(artifacts)}")
    if plan_json_path(run_dir).is_file():
        try:
            plan = load_plan(run_dir)
            counts = plan_status_summary(plan)
            parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print(f"Plan:       exists ({plan.overall_status}; {parts})")
            nxt = next_pending_step(plan)
            if nxt:
                print(f"Next plan:  {nxt.step_id} ({nxt.action})")
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            print("Plan:       present but unreadable")
    ev = evidence_json_path(run_dir).is_file() or (run_dir / EVIDENCE_MD).is_file()
    print(f"Evidence:   {'yes' if ev else 'no'}")
    print(f"Next:       {NEXT_ACTIONS.get(RunState(meta.state), 'See run_state.json')}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    if not args.file and not args.text:
        print("Error: provide --file or --text", file=sys.stderr)
        return 1
    try:
        store = open_store(_repo_path_from_args(args))
        out = store.record_output(
            args.run_id,
            args.role,
            file_path=args.file,
            text=args.text,
            replace=args.replace,
        )
        _, meta = store.get_run(args.run_id)
        print(f"Recorded {args.role} -> {out.name}")
        print(f"State: {meta.state}")
        print(f"Next: {NEXT_ACTIONS.get(RunState(meta.state), '')}")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        run_dir, meta = store.get_run(args.run_id)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    target_repo = Path(meta.repo_path)
    report = run_gates(target_repo)
    json_p, md_p = write_gate_artifacts(run_dir, report)

    meta = store.update_state(args.run_id, "gate")
    store.append_command(args.run_id, f"python -m governor gate --run-id {args.run_id}")

    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="gate",
        actor="governor",
        action="gate",
        output_ref="08_gate_results.json",
        status=report.overall.lower(),
        reason=f"overall={report.overall}",
    )

    print(f"Gates overall: {report.overall}")
    print(f"Wrote: {json_p.name}, {md_p.name}")
    print(f"State: {meta.state}")
    print(f"Next: {NEXT_ACTIONS.get(RunState(meta.state), '')}")
    return 0 if report.overall != "FAIL" else 2


def cmd_list(args: argparse.Namespace) -> int:
    try:
        repo = resolve_repo_path(_repo_path_from_args(args))
        open_store(str(repo))  # ensure runs exist
        entries = list_entries(repo, limit=args.limit)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
        return 0

    if not entries:
        print("No runs found.")
        return 0

    print(f"{'RUN_ID':<40} {'STATE':<28} {'OUTCOME':<24} TASK")
    print("-" * 120)
    for e in entries:
        outcome = e.get("outcome") or "-"
        task = (e.get("task") or "")[:40]
        print(
            f"{e.get('run_id', ''):<40} {e.get('state', ''):<28} {str(outcome):<24} {task}"
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    results, code = run_doctor(_repo_path_from_args(args))
    for r in results:
        print(f"[{r.status:4}] {r.name}: {r.detail}")
    return code


def _print_dispatch_preview(preview) -> None:
    print(f"Run ID:        {preview.run_id}")
    print(f"Role:          {preview.role}")
    if preview.role == "repair" and preview.repair_prompt_index is not None:
        print(f"Repair prompt: {preview.repair_prompt_index}")
    if preview.profile_name:
        print(f"Profile:       {preview.profile_name}")
    print(f"Prompt file:   {preview.prompt_path}")
    print(f"Output target: {preview.output_path}")
    print(f"Runner:        {preview.runner.name}")
    print(f"Command:       {format_argv_display(preview.runner.argv)}")
    print(f"Timeout:       {preview.timeout}s")
    if preview.config_path:
        print(f"Config:        {preview.config_path}")
    print("Mode:          preview (pass --approve to execute)")
    for w in preview.warnings:
        print(f"Warning:       {w}")


def _resolve_dispatch_runner(
    args: argparse.Namespace, repo: Path
) -> tuple[object, int, str | None, Path | None]:
    """Return (RunnerSpec, timeout, profile_name, config_path)."""
    profile_name: str | None = None
    cfg_p: Path | None = None
    if args.profile:
        profile_name = args.profile
        cfg_p = config_path(repo)
        if not cfg_p.is_file():
            raise FileNotFoundError(CONFIG_NOT_FOUND_MSG)
        prof, spec = get_profile(
            repo,
            profile_name,
            allow_disabled=args.allow_disabled_profile,
        )
        timeout_val = (
            args.timeout if args.timeout is not None else prof.timeout
        )
        return spec, validate_timeout(timeout_val), profile_name, cfg_p
    timeout_val = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT
    spec = build_runner_spec(args.runner, args.runner_argv)
    return spec, validate_timeout(timeout_val), profile_name, cfg_p


def cmd_dispatch(args: argparse.Namespace) -> int:
    repo_path = _repo_path_from_args(args)
    try:
        repo = resolve_repo_path(repo_path)
        spec, timeout, profile_name, cfg_p = _resolve_dispatch_runner(args, repo)
        store = open_store(repo_path)
        if not args.approve:
            preview = preview_dispatch(
                store,
                args.run_id,
                args.role,
                spec,
                timeout,
                replace=args.replace,
                profile_name=profile_name,
                config_path=cfg_p,
                repair_prompt_index=args.repair_prompt,
            )
            _print_dispatch_preview(preview)
            return 0
        out_path, result = execute_dispatch(
            store,
            args.run_id,
            args.role,
            spec,
            timeout,
            replace=args.replace,
            repo_path=repo_path,
            accept_failed_output=args.accept_failed_output,
            profile_name=profile_name,
            repair_prompt_index=args.repair_prompt,
        )
        _, meta = store.get_run(args.run_id)
        print(f"Dispatched {args.role} -> {out_path.name}")
        print(f"Exit code: {result.exit_code}")
        print(f"Duration:  {result.duration_seconds:.2f}s")
        print(f"State:     {meta.state}")
        if result.exit_code != 0 and not args.accept_failed_output:
            print("Note:      Non-zero exit — diagnostic .failed.md only; state unchanged.")
        print(f"Next:      {NEXT_ACTIONS.get(RunState(meta.state), '')}")
        return 0 if result.exit_code == 0 else 1
    except FileNotFoundError as e:
        msg = str(e)
        if msg == CONFIG_NOT_FOUND_MSG:
            print(msg, file=sys.stderr)
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_repair_prepare(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        path = prepare_repair(
            store,
            args.run_id,
            reason=args.reason,
            force=args.force,
            max_repairs=args.max_repairs,
        )
        print(f"Wrote: {path.name}")
        print("Warning: repair is bounded — fix only listed issues; do not broaden scope.")
        print("Next: paste prompt into agent, then dispatch/record repair, then gate again.")
        return 0
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_repair_list(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        run_dir, meta = store.get_run(args.run_id)
        art = list_repair_artifacts(run_dir)
        print(f"Run ID: {meta.run_id}")
        print(f"State:  {meta.state}")
        print(f"repair_count={meta.repair_count} repair_prompt_count={getattr(meta, 'repair_prompt_count', 0)}")
        print("Prompts:")
        for p in art["prompts"] or ["(none)"]:
            print(f"  - {p}")
        print("Outputs:")
        for o in art["outputs"] or ["(none)"]:
            print(f"  - {o}")
        if art["failed"]:
            print("Failed diagnostics:")
            for f in art["failed"]:
                print(f"  - {f}")
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_report(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        report_p, lead_p = generate_reports(store, args.run_id)
        _, meta = store.get_run(args.run_id)
        run_dir = report_p.parent
        trace = TraceLogger(run_dir, meta.run_id)
        trace.append(
            phase="report",
            actor="governor",
            action="report",
            output_ref="09_final_report.md",
            status="ok",
        )
        print(f"Wrote: {report_p.name}, {lead_p.name}")
        print(f"State: {meta.state}")
        print(f"Outcome: {meta.outcome}")
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_config_init(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    try:
        path = init_config(repo, force=args.force)
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote: {path}")
    print("Next: python -m governor config validate --repo-path .")
    print("      python -m governor dispatch --profile echo-test --run-id <id> --role executor --repo-path .")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    path = config_path(repo)
    if not path.is_file():
        print(f"Error: {CONFIG_NOT_FOUND_MSG}", file=sys.stderr)
        return 1
    try:
        profiles = load_profiles(path)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Config: {path}")
    for name in sorted(profiles):
        p = profiles[name]
        enabled = "enabled" if p.enabled else "disabled"
        print(f"\n[{name}] ({enabled}) runner={p.runner} timeout={p.timeout}s")
        print(f"  {p.description}")
        if p.argv:
            display = format_argv_display(redact_argv_for_display(p.argv))
            print(f"  argv: {display}")
    return 0


def cmd_config_validate(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    path = config_path(repo)
    if not path.is_file():
        print(f"FAIL: {CONFIG_NOT_FOUND_MSG}", file=sys.stderr)
        return 1
    lines, has_fail = validate_config_file(path, repo)
    for line in lines:
        print(f"{line.level}: {line.message}")
    return 1 if has_fail else 0


def cmd_plan_create(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        checkpoints = _parse_checkpoints(args.checkpoint, args.checkpoint_after)
        plan = create_plan(
            store,
            args.run_id,
            executor_profile=args.executor_profile,
            executor_runner=args.executor_runner,
            executor_command=args.executor_command,
            validator_profile=args.validator_profile,
            validator_runner=args.validator_runner,
            validator_command=args.validator_command,
            auto_repair_prepare_on_fail=args.auto_repair_prepare_on_fail,
            force=args.force,
            dry_run=args.dry_run,
            checkpoints=checkpoints or None,
        )
        if args.dry_run:
            print(render_plan_markdown(plan))
            print("(dry-run: plan not written)")
            return 0
        print(f"Wrote: {PLAN_JSON}, 12_run_plan.md")
        print(f"Steps: {len(plan.steps)}")
        for s in plan.steps:
            if s.action == "stop":
                continue
            print(f"  - {s.step_id}: {s.action}")
        return 0
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_plan_show(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        run_dir, _ = store.get_run(args.run_id)
        plan = load_plan(run_dir)
        if args.as_json:
            print(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
            return 0
        print(render_plan_markdown(plan))
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_plan_execute(args: argparse.Namespace) -> int:
    repo_path = _repo_path_from_args(args)
    try:
        store = open_store(repo_path)
        result = execute_plan(
            store,
            args.run_id,
            approve=args.approve,
            until=args.until,
            dry_run=args.dry_run,
            stop_on_warn=False if args.continue_on_gate_warn else None,
            continue_on_gate_warn=args.continue_on_gate_warn,
            replace=args.replace,
            accept_failed_output=args.accept_failed_output,
            max_steps=args.max_steps,
            repo_path=repo_path,
        )
        if result.message == APPROVE_REQUIRED_MSG:
            print(APPROVE_REQUIRED_MSG, file=sys.stderr)
            return result.exit_code
        print(result.message)
        return result.exit_code
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_plan_resume(args: argparse.Namespace) -> int:
    repo_path = _repo_path_from_args(args)
    try:
        store = open_store(repo_path)
        result = resume_plan(
            store,
            args.run_id,
            approve=args.approve,
            until=args.until,
            dry_run=args.dry_run,
            stop_on_warn=False if args.continue_on_gate_warn else None,
            continue_on_gate_warn=args.continue_on_gate_warn,
            replace=args.replace,
            accept_failed_output=args.accept_failed_output,
            max_steps=args.max_steps,
            repo_path=repo_path,
        )
        if result.message == RESUME_APPROVE_REQUIRED_MSG:
            print(RESUME_APPROVE_REQUIRED_MSG, file=sys.stderr)
            return result.exit_code
        print(result.message)
        return result.exit_code
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_plan_validate(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        lines, has_fail = validate_plan(store, args.run_id)
        for line in lines:
            print(f"{line.level}: {line.message}")
        return 1 if has_fail else 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_plan_checkpoint(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        step = approve_checkpoint(
            store,
            args.run_id,
            args.step_id,
            note=args.note,
        )
        print(f"Checkpoint {step.step_id}: PASS")
        print(f"Note: {step.reason}")
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_evidence_export(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        fmt = args.format
        md_p, json_p = export_evidence(
            store,
            args.run_id,
            include_prompts=args.include_prompts,
            write_markdown=fmt in ("both", "markdown"),
            write_json=fmt in ("both", "json"),
        )
        if md_p:
            print(f"Wrote: {md_p.name}")
        if json_p:
            print(f"Wrote: {json_p.name}")
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_config_path(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    print(config_path(repo))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(sys.stderr)
        return 1
    handlers = {
        "init": cmd_init,
        "status": cmd_status,
        "list": cmd_list,
        "doctor": cmd_doctor,
        "dispatch": cmd_dispatch,
        "record": cmd_record,
        "gate": cmd_gate,
        "report": cmd_report,
    }
    if args.command == "config":
        config_handlers = {
            "init": cmd_config_init,
            "show": cmd_config_show,
            "validate": cmd_config_validate,
            "path": cmd_config_path,
        }
        return config_handlers[args.config_cmd](args)
    if args.command == "repair":
        repair_handlers = {
            "prepare": cmd_repair_prepare,
            "list": cmd_repair_list,
        }
        return repair_handlers[args.repair_cmd](args)
    if args.command == "plan":
        plan_handlers = {
            "create": cmd_plan_create,
            "show": cmd_plan_show,
            "execute": cmd_plan_execute,
            "resume": cmd_plan_resume,
            "validate": cmd_plan_validate,
            "checkpoint": cmd_plan_checkpoint,
        }
        return plan_handlers[args.plan_cmd](args)
    if args.command == "evidence":
        if args.evidence_cmd == "export":
            return cmd_evidence_export(args)
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
