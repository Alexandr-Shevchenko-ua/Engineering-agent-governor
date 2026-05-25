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
from governor.report import generate_reports
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
    p_dispatch.add_argument("--role", required=True, choices=["executor", "validator"])
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

    return parser


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

    artifacts = store.list_artifacts(run_dir)
    print(f"Run ID:     {meta.run_id}")
    print(f"Task:       {meta.task}")
    print(f"State:      {meta.state}")
    print(f"Created:    {meta.created_at}")
    print(f"Updated:    {meta.updated_at}")
    print(f"Folder:     {run_dir}")
    print(f"Outcome:    {meta.outcome or '(pending)'}")
    print(f"Artifacts:  {', '.join(artifacts)}")
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
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
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
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
