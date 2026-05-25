"""CLI entrypoint for Engineering Agent Governor."""

from __future__ import annotations

import argparse
import json
import platform
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
from governor.project_config import (
    PROJECT_CONFIG_FILENAME,
    init_project_config,
    load_project_config,
    project_config_path,
    resolve_gate_profile_for_repo,
    resolve_policy_for_repo,
    validate_project_data,
)
from governor.review_package import (
    PR_BODY_MD,
    REVIEW_JSON,
    REVIEW_MD,
    export_review_package,
    review_json_path,
)
from governor.index import list_entries
from governor.models import NEXT_ACTIONS, RunState
from governor.repair import list_repair_artifacts, prepare_repair
from governor.report import generate_reports
from governor.evidence import EVIDENCE_JSON, EVIDENCE_MD, evidence_json_path, export_evidence
from governor.policy import get_policy, list_policies, validate_policy_pack
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
from governor.governed_run import (
    GovernedRunOptions,
    build_run_summary_payload,
    governed_run_resume,
    governed_run_start,
    print_run_summary,
)
from governor.advisor import ADVISOR_KINDS, ask_advisor
from governor.governor_mode import (
    PROPOSAL_MD,
    apply_proposal,
    list_proposals,
    load_proposal,
    propose_governor_mode,
    reject_proposal,
    render_proposal_markdown,
    validate_proposal,
)
from governor.check import check_exit_code, run_check
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
        description=(
            "Engineering Agent Governor — local delegation-first control plane. "
            "Not autopilot: dispatch and plan execution require explicit --approve."
        ),
        parents=[parent],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"governor {__version__}",
        help="Print version and exit",
    )

    sub = parser.add_subparsers(dest="command", required=False, metavar="COMMAND")

    p_version = sub.add_parser(
        "version",
        help="Show package version and runtime info",
    )
    p_version.add_argument("--json", action="store_true", help="JSON output")

    p_check = sub.add_parser(
        "check",
        help="Meta-check for Governor repo health (validate, gitignore, tests)",
        parents=[parent],
    )
    p_check.add_argument(
        "--smoke",
        action="store_true",
        help="Also run scripts/smoke_*.py from the Governor package",
    )
    p_check.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    p_init = sub.add_parser("init", help="Create a new governor run", parents=[parent])
    p_init.add_argument("--task", required=True, help="Task title / objective")
    p_init.add_argument(
        "--policy",
        default=None,
        metavar="NAME",
        help="Policy pack: default, bugfix, refactor, docs, test-only, release, agentic-tooling",
    )

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

    p_gate = sub.add_parser(
        "gate",
        help="Run deterministic local gates on target repo (requires prior run)",
        parents=[parent],
    )
    p_gate.add_argument("--run-id", required=True, help="Run folder name under .governor/runs/")
    p_gate.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help="Gate profile from governor.project.json (default: project default_gate_profile)",
    )

    p_project = sub.add_parser(
        "project",
        help="Tracked repository governance (governor.project.json)",
        parents=[parent],
    )
    project_sub = p_project.add_subparsers(dest="project_cmd", required=True)
    p_proj_init = project_sub.add_parser(
        "init",
        help="Write governor.project.json if missing",
        parents=[parent],
    )
    p_proj_init.add_argument("--force", action="store_true")
    p_proj_show = project_sub.add_parser("show", help="Show project config summary", parents=[parent])
    p_proj_validate = project_sub.add_parser(
        "validate",
        help="Validate governor.project.json",
        parents=[parent],
    )
    p_proj_path = project_sub.add_parser("path", help="Print expected config path", parents=[parent])

    p_review = sub.add_parser(
        "review",
        help="Review / MR handoff package",
        parents=[parent],
    )
    review_sub = p_review.add_subparsers(dest="review_cmd", required=True)
    p_rev_export = review_sub.add_parser("export", help="Write 15_review_package.*", parents=[parent])
    p_rev_export.add_argument("--run-id", required=True)
    p_rev_export.add_argument(
        "--format",
        choices=["both", "markdown", "json"],
        default="both",
        help="Output format (default: both md and json; PR body always written)",
    )
    p_rev_export.add_argument(
        "--include-trace",
        action="store_true",
        help="Include recent trace events in JSON package",
    )
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
    p_plan_create.add_argument(
        "--policy",
        default=None,
        metavar="NAME",
        help="Policy for plan defaults (default: from run metadata or 'default')",
    )
    p_plan_create.add_argument(
        "--gate-profile",
        default=None,
        metavar="NAME",
        help="Gate profile from governor.project.json",
    )

    p_policy = sub.add_parser(
        "policy",
        help="Built-in policy packs (no .governor required)",
    )
    policy_sub = p_policy.add_subparsers(dest="policy_cmd", required=True)
    p_pol_list = policy_sub.add_parser("list", help="List built-in policies")
    p_pol_list.add_argument("--json", action="store_true", dest="as_json")
    p_pol_show = policy_sub.add_parser("show", help="Show policy details")
    p_pol_show.add_argument("--policy", required=True, metavar="NAME")
    p_pol_show.add_argument("--json", action="store_true", dest="as_json")
    p_pol_validate = policy_sub.add_parser("validate", help="Validate policy pack definition")
    p_pol_validate.add_argument("--policy", required=True, metavar="NAME")

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
        help="Treat gate WARN as non-blocking (default: stop plan on WARN)",
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

    def _add_advisor_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--run-id", required=True)
        p.add_argument(
            "--provider",
            dest="advisor_provider",
            choices=["chatbang"],
            default="chatbang",
            help="Advisor provider (default: chatbang)",
        )
        p.add_argument(
            "--kind",
            choices=sorted(ADVISOR_KINDS),
            default="next-action",
            help="Advisor use case",
        )
        p.add_argument("--question", default=None, help="Override default question for kind")
        p.add_argument(
            "--chatbang-command",
            dest="chatbang_command",
            default="chatbang",
            help="Chatbang executable (local override)",
        )
        p.add_argument("--timeout", type=int, default=180, help="Seconds (30–900)")
        p.add_argument("--max-output-chars", type=int, default=20000)
        p.add_argument("--dry-run", action="store_true", help="Write request only; do not call chatbang")
        p.add_argument(
            "--include-prompts",
            action="store_true",
            help="Include full executor/validator prompts in advisor context",
        )
        p.add_argument(
            "--force",
            action="store_true",
            help="Allow advisor ask when final report already exists",
        )

    p_governor_mode = sub.add_parser(
        "governor",
        help="Experimental Chatbang Governor Mode (propose/validate/apply; not autopilot)",
        parents=[parent],
    )
    gov_sub = p_governor_mode.add_subparsers(dest="governor_cmd", required=True)

    p_gov_propose = gov_sub.add_parser(
        "propose",
        help="Chatbang proposes a bounded Governor run (no run created)",
        parents=[parent],
    )
    p_gov_propose.add_argument("--task", required=True)
    p_gov_propose.add_argument("--policy", default=None, metavar="NAME")
    p_gov_propose.add_argument(
        "--provider",
        default="chatbang",
        choices=["chatbang"],
        help="Proposal provider (chatbang only in v1.2)",
    )
    p_gov_propose.add_argument("--question", default=None, help="Extra instruction for chatbang")
    p_gov_propose.add_argument(
        "--chatbang-command",
        default="chatbang",
        help="Chatbang executable command",
    )
    p_gov_propose.add_argument("--timeout", type=int, default=300, help="Seconds (max 900)")
    p_gov_propose.add_argument("--max-output-chars", type=int, default=30000)
    p_gov_propose.add_argument("--dry-run", action="store_true")
    p_gov_propose.add_argument(
        "--include-repo-summary",
        action="store_true",
        help="Include extra repo metadata in prompt",
    )
    p_gov_propose.add_argument(
        "--experimental-allow-wide-context",
        action="store_true",
        help="Include redacted profile argv in context",
    )
    p_gov_propose.add_argument("--json", action="store_true", dest="as_json")

    p_gov_validate = gov_sub.add_parser(
        "validate",
        help="Validate proposal safety and schema",
        parents=[parent],
    )
    p_gov_validate.add_argument("--proposal", required=True)
    p_gov_validate.add_argument("--force-unstructured", action="store_true")
    p_gov_validate.add_argument("--json", action="store_true", dest="as_json")

    p_gov_list = gov_sub.add_parser(
        "list",
        help="List local Governor proposals",
        parents=[parent],
    )
    p_gov_list.add_argument("--json", action="store_true", dest="as_json")

    p_gov_show = gov_sub.add_parser(
        "show",
        help="Show proposal markdown summary",
        parents=[parent],
    )
    p_gov_show.add_argument("--proposal", required=True)
    p_gov_show.add_argument("--json", action="store_true", dest="as_json")

    p_gov_reject = gov_sub.add_parser(
        "reject",
        help="Mark proposal REJECTED",
        parents=[parent],
    )
    p_gov_reject.add_argument("--proposal", required=True)
    p_gov_reject.add_argument("--reason", required=True)

    p_gov_apply = gov_sub.add_parser(
        "apply",
        help="Apply proposal → run + plan (requires --approve; no execution by default)",
        parents=[parent],
    )
    p_gov_apply.add_argument("--proposal", required=True)
    p_gov_apply.add_argument("--approve", action="store_true")
    p_gov_apply.add_argument("--dry-run", action="store_true")
    p_gov_apply.add_argument("--executor-profile", default=None)
    p_gov_apply.add_argument("--validator-profile", default=None)
    p_gov_apply.add_argument("--policy", default=None, dest="policy_override")
    p_gov_apply.add_argument("--with-evidence", action="store_true")
    p_gov_apply.add_argument("--with-review-package", action="store_true")
    p_gov_apply.add_argument("--continue-on-gate-warn", action="store_true")
    p_gov_apply.add_argument("--no-execute", action="store_true", help="Default in v1.2 (no-op)")
    p_gov_apply.add_argument("--force-unstructured", action="store_true")
    p_gov_apply.add_argument("--json", action="store_true", dest="as_json")

    p_advisor = sub.add_parser(
        "advisor",
        help="Semantic Governor Advisor (chatbang via pexpect; not executor)",
        parents=[parent],
    )
    advisor_sub = p_advisor.add_subparsers(dest="advisor_cmd", required=True)
    p_advisor_ask = advisor_sub.add_parser(
        "ask",
        help="Ask chatbang advisor for bounded run guidance",
        parents=[parent],
    )
    _add_advisor_args(p_advisor_ask)

    p_rev_advise = review_sub.add_parser(
        "advise",
        help="Chatbang advisor: evidence-review (does not export or change state)",
        parents=[parent],
    )
    _add_advisor_args(p_rev_advise)

    p_plan_advise = plan_sub.add_parser(
        "advise",
        help="Chatbang advisor: plan-review (does not execute plan)",
        parents=[parent],
    )
    _add_advisor_args(p_plan_advise)

    p_run = sub.add_parser(
        "run",
        help="Governed run — create run, plan, optional execute (not autopilot)",
        parents=[parent],
    )
    run_sub = p_run.add_subparsers(dest="run_cmd", required=True)

    def _add_governed_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--continue-on-gate-warn",
            action="store_true",
            help="Continue when gate step returns WARN (not FAIL)",
        )
        p.add_argument("--replace", action="store_true")
        p.add_argument("--accept-failed-output", action="store_true")
        p.add_argument("--max-steps", type=int, default=10)
        p.add_argument("--with-evidence", action="store_true")
        p.add_argument("--with-review-package", action="store_true")
        p.add_argument("--strict-preflight", action="store_true")
        p.add_argument("--json", action="store_true", dest="as_json")

    p_run_start = run_sub.add_parser(
        "start",
        help="Create run + plan; execute only with --approve",
        parents=[parent],
    )
    p_run_start.add_argument("--task", required=True)
    p_run_start.add_argument(
        "--policy",
        default=None,
        metavar="NAME",
        help="Policy pack (default: governor.project.json default_policy or 'default')",
    )
    p_run_start.add_argument(
        "--gate-profile",
        default=None,
        metavar="NAME",
        help="Gate profile for plan gate step",
    )
    p_run_start.add_argument("--executor-profile", default=None)
    p_run_start.add_argument("--validator-profile", default=None)
    p_run_start.add_argument(
        "--executor-runner",
        choices=["echo", "command", "cursor"],
        default=None,
    )
    p_run_start.add_argument(
        "--validator-runner",
        choices=["echo", "command", "cursor"],
        default=None,
    )
    p_run_start.add_argument(
        "--executor-command",
        dest="executor_command",
        nargs="*",
        default=None,
        metavar="ARG",
    )
    p_run_start.add_argument(
        "--validator-command",
        dest="validator_command",
        nargs="*",
        default=None,
        metavar="ARG",
    )
    p_run_start.add_argument("--auto-repair-prepare-on-fail", action="store_true")
    p_run_start.add_argument("--approve", action="store_true")
    p_run_start.add_argument("--dry-run", action="store_true")
    p_run_start.add_argument("--use-default-profiles", action="store_true")
    p_run_start.add_argument("--checkpoint", action="append", default=[])
    p_run_start.add_argument("--checkpoint-after", action="append", default=[])
    _add_governed_common(p_run_start)

    p_run_status = run_sub.add_parser("status", help="Run status summary", parents=[parent])
    p_run_status.add_argument("--run-id", default=None)
    p_run_status.add_argument("--json", action="store_true", dest="as_json")

    p_run_resume = run_sub.add_parser(
        "resume",
        help="Resume governed plan; --approve required",
        parents=[parent],
    )
    p_run_resume.add_argument("--run-id", required=True)
    p_run_resume.add_argument("--approve", action="store_true")
    p_run_resume.add_argument("--dry-run", action="store_true")
    _add_governed_common(p_run_resume)

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
        "review_package_exists": review_json_path(run_dir).is_file()
        or (run_dir / REVIEW_MD).is_file(),
        "pr_body_exists": (run_dir / PR_BODY_MD).is_file(),
        "folder": str(run_dir),
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
        "policy": getattr(meta, "policy", None) or "default",
    }


def cmd_init(args: argparse.Namespace) -> int:
    try:
        repo = resolve_repo_path(_repo_path_from_args(args))
        pol = resolve_policy_for_repo(repo, args.policy)
        get_policy(pol)
        store = init_store(str(repo))
        run_dir, meta = store.create_run(args.task, policy_name=pol)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Created run: {meta.run_id}")
    print(f"Folder: {run_dir}")
    print(f"Policy: {meta.policy or 'default'}")
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
    print(f"Policy:     {getattr(meta, 'policy', None) or 'default'}")
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
    rev = review_json_path(run_dir).is_file() or (run_dir / REVIEW_MD).is_file()
    print(f"Review pkg: {'yes' if rev else 'no'}")
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
    profile = resolve_gate_profile_for_repo(target_repo, getattr(args, "profile", None))
    report = run_gates(target_repo, gate_profile=profile)
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
    if report.gate_profile:
        print(f"Gate profile: {report.gate_profile} (compliance: {report.profile_compliance})")
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


def cmd_policy_list(args: argparse.Namespace) -> int:
    names = list_policies()
    if args.as_json:
        print(json.dumps([{"name": n} for n in names], indent=2))
        return 0
    print("Built-in policies:")
    for n in names:
        pack = get_policy(n)
        print(f"  - {n}: {pack.description}")
    return 0


def cmd_policy_show(args: argparse.Namespace) -> int:
    try:
        pack = get_policy(args.policy)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(pack.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(f"Policy: {pack.name}")
    print(f"Description: {pack.description}")
    print(f"Required artifacts: {', '.join(pack.required_artifacts) or '(none)'}")
    print(f"Recommended gates: {', '.join(pack.recommended_gates)}")
    print(f"Max repair prompts: {pack.max_repair_prompts}")
    if pack.default_checkpoints:
        print("Default checkpoints:")
        for after, msg in pack.default_checkpoints:
            print(f"  - after {after}: {msg}")
    pd = pack.plan_defaults
    print(f"Plan defaults: auto_repair={pd.auto_repair_prepare_on_fail} max_steps={pd.max_steps}")
    if pack.evidence_expectations:
        print("Evidence expectations:")
        for e in pack.evidence_expectations:
            print(f"  - {e}")
    return 0


def cmd_policy_validate(args: argparse.Namespace) -> int:
    try:
        pack = get_policy(args.policy)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    lines = validate_policy_pack(pack)
    has_fail = any(level == "FAIL" for level, _ in lines)
    for level, msg in lines:
        print(f"{level}: {msg}")
    return 1 if has_fail else 0


def cmd_plan_create(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        checkpoints = _parse_checkpoints(args.checkpoint, args.checkpoint_after)
        auto_repair = True if args.auto_repair_prepare_on_fail else None
        plan = create_plan(
            store,
            args.run_id,
            executor_profile=args.executor_profile,
            executor_runner=args.executor_runner,
            executor_command=args.executor_command,
            validator_profile=args.validator_profile,
            validator_runner=args.validator_runner,
            validator_command=args.validator_command,
            auto_repair_prepare_on_fail=auto_repair,
            force=args.force,
            dry_run=args.dry_run,
            checkpoints=checkpoints or None,
            policy_name=args.policy,
            gate_profile=getattr(args, "gate_profile", None),
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


def cmd_project_init(args: argparse.Namespace) -> int:
    try:
        repo = resolve_repo_path(_repo_path_from_args(args))
        path = init_project_config(repo, force=args.force)
        print(f"Wrote: {path}")
        return 0
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_project_show(args: argparse.Namespace) -> int:
    try:
        repo = resolve_repo_path(_repo_path_from_args(args))
        cfg = load_project_config(repo)
        print(f"File: {project_config_path(repo)}")
        print(f"Project: {cfg.project_name}")
        print(f"Default policy: {cfg.default_policy}")
        print(f"Allowed policies: {', '.join(cfg.allowed_policies)}")
        print(f"Default gate profile: {cfg.default_gate_profile}")
        print(f"Gate profiles: {', '.join(sorted(cfg.gate_profiles))}")
        print(
            f"Diff budget: {cfg.diff_budget.max_changed_files} files, "
            f"+{cfg.diff_budget.max_lines_added}/-{cfg.diff_budget.max_lines_deleted} lines"
        )
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_project_validate(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    path = project_config_path(repo)
    if not path.is_file():
        print(f"WARN: no {PROJECT_CONFIG_FILENAME} at {path}")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = validate_project_data(data)
    has_fail = False
    for ln in lines:
        print(f"{ln.level}: {ln.message}")
        if ln.level == "FAIL":
            has_fail = True
    return 1 if has_fail else 0


def cmd_project_path(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    print(project_config_path(repo))
    return 0


def cmd_review_export(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        fmt = args.format
        md_p, json_p, pr_p = export_review_package(
            store,
            args.run_id,
            include_trace=args.include_trace,
            write_markdown=fmt in ("both", "markdown"),
            write_json=fmt in ("both", "json"),
            write_pr_body=True,
        )
        if md_p:
            print(f"Wrote: {md_p.name}")
        if json_p:
            print(f"Wrote: {json_p.name}")
        if pr_p:
            print(f"Wrote: {pr_p.name}")
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _governed_opts_from_args(args: argparse.Namespace) -> GovernedRunOptions:
    checkpoints = _parse_checkpoints(
        getattr(args, "checkpoint", []) or [],
        getattr(args, "checkpoint_after", []) or [],
    )
    auto_repair = True if getattr(args, "auto_repair_prepare_on_fail", False) else None
    return GovernedRunOptions(
        task=getattr(args, "task", ""),
        repo_path=_repo_path_from_args(args),
        policy=getattr(args, "policy", None),
        gate_profile=getattr(args, "gate_profile", None),
        executor_profile=getattr(args, "executor_profile", None),
        validator_profile=getattr(args, "validator_profile", None),
        executor_runner=getattr(args, "executor_runner", None),
        validator_runner=getattr(args, "validator_runner", None),
        executor_command=getattr(args, "executor_command", None),
        validator_command=getattr(args, "validator_command", None),
        auto_repair_prepare_on_fail=auto_repair,
        checkpoints=checkpoints or None,
        with_evidence=getattr(args, "with_evidence", False),
        with_review_package=getattr(args, "with_review_package", False),
        approve=getattr(args, "approve", False),
        dry_run=getattr(args, "dry_run", False),
        continue_on_gate_warn=getattr(args, "continue_on_gate_warn", False),
        max_steps=getattr(args, "max_steps", 10),
        replace=getattr(args, "replace", False),
        accept_failed_output=getattr(args, "accept_failed_output", False),
        use_default_profiles=getattr(args, "use_default_profiles", False),
        strict_preflight=getattr(args, "strict_preflight", False),
    )


def cmd_run_start(args: argparse.Namespace) -> int:
    opts = _governed_opts_from_args(args)
    result = governed_run_start(opts)
    if result.error and not result.dry_run_actions:
        print(f"Error: {result.error}", file=sys.stderr)
    if result.dry_run_actions:
        print("Dry run — would perform:")
        for line in result.dry_run_actions:
            print(f"  - {line}")
        return 0
    if result.run_id:
        store = open_store(opts.repo_path)
        payload = build_run_summary_payload(
            store,
            result.run_id,
            repo_path=opts.repo_path,
            stopped_at=result.stopped_at,
            plan_overall_status=result.plan_overall_status,
            evidence_exported=result.evidence_exported,
            evidence_skipped_reason=result.evidence_skipped_reason,
            review_package_exported=result.review_package_exported,
            review_skipped_reason=result.review_skipped_reason,
        )
        if args.as_json:
            payload["preflight_warnings"] = result.preflight_messages
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print_run_summary(payload, preflight_warnings=result.preflight_messages)
        return result.exit_code
    return result.exit_code or 1


def cmd_run_status(args: argparse.Namespace) -> int:
    try:
        store = open_store(_repo_path_from_args(args))
        run_dir, meta = store.get_run(args.run_id)
        payload = build_run_summary_payload(store, meta.run_id, repo_path=_repo_path_from_args(args))
        if args.as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print_run_summary(payload)
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_run_resume(args: argparse.Namespace) -> int:
    opts = _governed_opts_from_args(args)
    if not args.run_id:
        print("Error: --run-id required", file=sys.stderr)
        return 1
    try:
        store = open_store(opts.repo_path)
        result = governed_run_resume(store, args.run_id, opts=opts)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if result.error:
        print(f"Error: {result.error}", file=sys.stderr)
    if result.dry_run_actions:
        for line in result.dry_run_actions:
            print(f"  - {line}")
        return 0
    payload = build_run_summary_payload(
        store,
        args.run_id,
        repo_path=opts.repo_path,
        stopped_at=result.stopped_at,
        plan_overall_status=result.plan_overall_status,
        evidence_exported=result.evidence_exported,
        evidence_skipped_reason=result.evidence_skipped_reason,
        review_package_exported=result.review_package_exported,
        review_skipped_reason=result.review_skipped_reason,
    )
    if args.as_json:
        payload["preflight_warnings"] = result.preflight_messages
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_run_summary(payload, preflight_warnings=result.preflight_messages)
    return result.exit_code


def _run_advisor_ask(args: argparse.Namespace, *, kind_override: str | None = None) -> int:
    kind = kind_override or args.kind
    try:
        store = open_store(_repo_path_from_args(args))
        result = ask_advisor(
            store,
            args.run_id,
            provider=args.advisor_provider,
            kind=kind,
            question=args.question,
            command=args.chatbang_command,
            timeout=args.timeout,
            max_output_chars=args.max_output_chars,
            dry_run=args.dry_run,
            include_prompts=args.include_prompts,
            force=args.force,
        )
    except (FileNotFoundError, ValueError, ImportError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Advisor request: {result.request_path}")
    if result.dry_run:
        print("Dry run — chatbang not invoked.")
        return 0
    if result.response_path:
        print(f"Advisor response: {result.response_path}")
    if result.ok:
        print("Advisor: OK")
        return 0
    print(f"Advisor: FAIL — {result.error or 'unknown'}", file=sys.stderr)
    return 1


def cmd_governor_propose(args: argparse.Namespace) -> int:
    timeout = min(max(args.timeout, 30), 900)
    repo = resolve_repo_path(_repo_path_from_args(args))
    try:
        result = propose_governor_mode(
            repo,
            args.task,
            provider=args.provider,
            policy_hint=args.policy,
            extra_question=args.question,
            chatbang_command=args.chatbang_command,
            timeout=timeout,
            max_output_chars=max(1000, min(args.max_output_chars, 50_000)),
            dry_run=args.dry_run,
            include_repo_summary=args.include_repo_summary,
            experimental_wide=args.experimental_allow_wide_context,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if not result.ok:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1
    payload = {
        "proposal_id": result.proposal_id,
        "proposal_dir": str(result.proposal_dir),
        "dry_run": result.dry_run,
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Proposal: {result.proposal_id}")
        print(f"Folder: {result.proposal_dir}")
        if result.dry_run:
            print("Dry-run: prompt preview only (propose_prompt_preview.md)")
    return 0


def cmd_governor_validate(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    try:
        result = validate_proposal(
            repo,
            args.proposal,
            force_unstructured=args.force_unstructured,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.as_json:
        print(
            json.dumps(
                {
                    "proposal_id": result.proposal_id,
                    "ok": result.ok,
                    "warnings_only": result.warnings_only,
                    "decisions": [d.to_dict() for d in result.decisions],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for d in result.decisions:
            print(f"[{d.status}] {d.check}: {d.message}")
        print(f"Validation: {'PASS' if result.ok else 'FAIL'}")
    return 0 if result.ok else 1


def cmd_governor_list(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    entries = list_proposals(repo)
    if args.as_json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
        return 0
    if not entries:
        print("No proposals found under .governor/proposals/")
        return 0
    for e in entries:
        print(
            f"{e['proposal_id']}  {e['status']:8}  {e['confidence']:6}  {e['created_at']}  {e['task']}"
        )
    return 0


def cmd_governor_show(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    try:
        pdir, proposal = load_proposal(repo, args.proposal)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(proposal.to_dict(), indent=2, ensure_ascii=False))
        return 0
    md_path = pdir / PROPOSAL_MD
    if md_path.is_file():
        print(md_path.read_text(encoding="utf-8"))
    else:
        print(render_proposal_markdown(proposal))
    return 0


def cmd_governor_reject(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    try:
        proposal = reject_proposal(repo, args.proposal, args.reason)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Rejected proposal: {proposal.proposal_id}")
    return 0


def cmd_governor_apply(args: argparse.Namespace) -> int:
    repo = resolve_repo_path(_repo_path_from_args(args))
    try:
        result = apply_proposal(
            repo,
            args.proposal,
            approve=args.approve,
            dry_run=args.dry_run,
            force_unstructured=args.force_unstructured,
            executor_profile=args.executor_profile,
            validator_profile=args.validator_profile,
            policy_override=args.policy_override,
            with_evidence=args.with_evidence,
            with_review_package=args.with_review_package,
            continue_on_gate_warn=args.continue_on_gate_warn,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.as_json:
        print(
            json.dumps(
                {
                    "proposal_id": result.proposal_id,
                    "run_id": result.run_id,
                    "ok": result.ok,
                    "approved": result.approved,
                    "dry_run": result.dry_run,
                    "error": result.error,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    if not result.ok and result.error:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1
    return 0


def cmd_advisor_ask(args: argparse.Namespace) -> int:
    return _run_advisor_ask(args)


def cmd_plan_advise(args: argparse.Namespace) -> int:
    return _run_advisor_ask(args, kind_override="plan-review")


def cmd_review_advise(args: argparse.Namespace) -> int:
    return _run_advisor_ask(args, kind_override="evidence-review")


def cmd_version(args: argparse.Namespace) -> int:
    payload = {
        "version": __version__,
        "package": "engineering-agent-governor",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"governor {payload['version']}")
    print(f"Python {payload['python_version']}")
    print(f"Platform {payload['platform']}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    summary = run_check(_repo_path_from_args(args), run_smoke=args.smoke)
    if args.as_json:
        print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Governor check: {summary.overall}")
        for r in summary.results:
            print(f"  [{r.status:4}] {r.name}: {r.detail}")
    return check_exit_code(summary)


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
        "version": cmd_version,
        "check": cmd_check,
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
            "advise": cmd_plan_advise,
        }
        return plan_handlers[args.plan_cmd](args)
    if args.command == "evidence":
        if args.evidence_cmd == "export":
            return cmd_evidence_export(args)
    if args.command == "policy":
        policy_handlers = {
            "list": cmd_policy_list,
            "show": cmd_policy_show,
            "validate": cmd_policy_validate,
        }
        return policy_handlers[args.policy_cmd](args)
    if args.command == "run":
        run_handlers = {
            "start": cmd_run_start,
            "status": cmd_run_status,
            "resume": cmd_run_resume,
        }
        return run_handlers[args.run_cmd](args)
    if args.command == "project":
        project_handlers = {
            "init": cmd_project_init,
            "show": cmd_project_show,
            "validate": cmd_project_validate,
            "path": cmd_project_path,
        }
        return project_handlers[args.project_cmd](args)
    if args.command == "review":
        if args.review_cmd == "export":
            return cmd_review_export(args)
        if args.review_cmd == "advise":
            return cmd_review_advise(args)
    if args.command == "advisor":
        if args.advisor_cmd == "ask":
            return cmd_advisor_ask(args)
    if args.command == "governor":
        gov_handlers = {
            "propose": cmd_governor_propose,
            "validate": cmd_governor_validate,
            "list": cmd_governor_list,
            "show": cmd_governor_show,
            "reject": cmd_governor_reject,
            "apply": cmd_governor_apply,
        }
        return gov_handlers[args.governor_cmd](args)
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
