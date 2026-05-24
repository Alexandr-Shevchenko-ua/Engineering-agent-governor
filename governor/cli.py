"""CLI entrypoint for Engineering Agent Governor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from governor import __version__
from governor.gates import run_gates, write_gate_artifacts
from governor.models import NEXT_ACTIONS, RunState
from governor.report import generate_reports
from governor.run_store import open_store
from governor.trace import TraceLogger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="governor",
        description="Engineering Agent Governor — local delegation-first control plane.",
    )
    parser.add_argument("--version", action="version", version=f"governor {__version__}")
    parser.add_argument(
        "--repo-path",
        default=".",
        help="Target repository path (default: current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a new governor run")
    p_init.add_argument("--task", required=True, help="Task title / objective")
    p_init.add_argument(
        "--repo-path",
        dest="target_repo",
        default=None,
        help="Repo under work (default: --repo-path or cwd)",
    )

    p_status = sub.add_parser("status", help="Show run status")
    p_status.add_argument("--run-id", default=None, help="Run ID (default: latest)")

    p_record = sub.add_parser("record", help="Record delegated agent output")
    p_record.add_argument("--run-id", required=True)
    p_record.add_argument(
        "--role",
        required=True,
        choices=["executor", "validator", "repair", "human_note"],
    )
    p_record.add_argument("--file", type=Path, default=None, help="Markdown/text file")
    p_record.add_argument("--text", default=None, help="Inline text content")

    p_gate = sub.add_parser("gate", help="Run deterministic local gates")
    p_gate.add_argument("--run-id", required=True)

    p_report = sub.add_parser("report", help="Generate final report and lead update")
    p_report.add_argument("--run-id", required=True)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    target = args.target_repo or args.repo_path
    store = open_store(target)
    run_dir, meta = store.create_run(args.task)
    print(f"Created run: {meta.run_id}")
    print(f"Folder: {run_dir}")
    print(f"State: {meta.state}")
    print(f"Next: {NEXT_ACTIONS.get(RunState(meta.state), '')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = open_store(args.repo_path)
    try:
        run_dir, meta = store.get_run(args.run_id)
    except FileNotFoundError as e:
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
    store = open_store(args.repo_path)
    try:
        out = store.record_output(
            args.run_id,
            args.role,
            file_path=args.file,
            text=args.text,
        )
        _, meta = store.get_run(args.run_id)
        print(f"Recorded {args.role} -> {out.name}")
        print(f"State: {meta.state}")
        print(f"Next: {NEXT_ACTIONS.get(RunState(meta.state), '')}")
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    store = open_store(args.repo_path)
    try:
        run_dir, meta = store.get_run(args.run_id)
    except FileNotFoundError as e:
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


def cmd_report(args: argparse.Namespace) -> int:
    store = open_store(args.repo_path)
    try:
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
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "init": cmd_init,
        "status": cmd_status,
        "record": cmd_record,
        "gate": cmd_gate,
        "report": cmd_report,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
