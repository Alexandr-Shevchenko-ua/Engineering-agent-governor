"""Bounded, human-approved dispatch of local runner commands."""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from governor.models import ROLE_OUTPUT_FILES, RunState, transition_state
from governor.redaction import redact
from governor.run_store import RunStore
from governor.trace import TraceLogger

ROLE_PROMPT_FILES: dict[str, str] = {
    "executor": "03_executor_prompt.md",
    "validator": "04_validator_prompt.md",
}

DISPATCH_ROLES = frozenset(ROLE_PROMPT_FILES.keys())
DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 1800

CURSOR_RUNNER_MESSAGE = """\
Cursor runner profile is not configured in Governor v0.2.

Use an explicit local command instead, for example:
  python -m governor dispatch --run-id <id> --role executor \\
    --runner command --command <your-cursor-cli> --approve --repo-path .

Do not pass secrets on the command line. Review dispatch preview before --approve.
"""

_BLOCKED_ARG_FRAGMENTS = (
    "rm -rf",
    "git push",
    "git reset --hard",
    "git clean -fdx",
    "shutdown",
    "reboot",
    ":(){",
)


@dataclass
class RunnerSpec:
    name: str
    argv: list[str]
    description: str


@dataclass
class DispatchPreview:
    run_id: str
    role: str
    prompt_path: Path
    output_path: Path
    runner: RunnerSpec
    timeout: int
    mode: str  # preview | execute


@dataclass
class DispatchResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    runner_name: str


def validate_timeout(timeout: int) -> int:
    if timeout <= 0 or timeout > MAX_TIMEOUT:
        raise ValueError(f"--timeout must be between 1 and {MAX_TIMEOUT} seconds")
    return timeout


def validate_role(role: str) -> str:
    if role not in DISPATCH_ROLES:
        raise ValueError(f"Unsupported dispatch role: {role}. Use executor or validator.")
    return role


def prompt_path_for_role(run_dir: Path, role: str) -> Path:
    name = ROLE_PROMPT_FILES[role]
    path = run_dir / name
    if not path.is_file():
        raise FileNotFoundError(f"Prompt artifact missing: {path}")
    return path


def output_path_for_role(run_dir: Path, role: str) -> Path:
    return run_dir / ROLE_OUTPUT_FILES[role]


def build_runner_spec(
    runner: str,
    command_args: list[str] | None,
) -> RunnerSpec:
    if runner == "echo":
        return RunnerSpec(
            name="echo",
            argv=["echo", "(builtin)"],
            description="Safe builtin test runner (no external process for echo body)",
        )
    if runner == "command":
        if not command_args:
            raise ValueError(
                "--runner command requires --command followed by executable and args"
            )
        _check_command_safety(command_args)
        return RunnerSpec(
            name="command",
            argv=list(command_args),
            description="Explicit local command (prompt on stdin)",
        )
    if runner == "cursor":
        return RunnerSpec(
            name="cursor",
            argv=["cursor", "(not configured)"],
            description="Placeholder — not executable without external CLI config",
        )
    raise ValueError(f"Unknown runner: {runner}. Use echo, command, or cursor.")


def _check_command_safety(argv: list[str]) -> None:
    joined = " ".join(argv).lower()
    for frag in _BLOCKED_ARG_FRAGMENTS:
        if frag.lower() in joined:
            raise ValueError(
                f"Refusing potentially destructive command (matched '{frag}'): {argv!r}"
            )


def format_argv_display(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


def run_echo(role: str, prompt_text: str) -> DispatchResult:
    lines = prompt_text.splitlines()
    preview_lines = "\n".join(f"> {line}" if line else ">" for line in lines[:12])
    if len(lines) > 12:
        preview_lines += f"\n> ... ({len(lines) - 12} more lines)"
    body = (
        f"# Echo dispatch ({role})\n\n"
        f"This is deterministic test output from the **echo** runner.\n\n"
        f"## Prompt preview (first lines)\n\n{preview_lines}\n\n"
        f"## Role\n\n{role}\n"
    )
    return DispatchResult(
        exit_code=0,
        stdout=body,
        stderr="",
        duration_seconds=0.0,
        runner_name="echo",
    )


def run_command(
    argv: list[str],
    prompt_text: str,
    cwd: Path,
    timeout: int,
) -> DispatchResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        duration = time.monotonic() - start
        return DispatchResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_seconds=duration,
            runner_name="command",
        )
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - start
        out = (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode(
            "utf-8", errors="replace"
        )
        err = (e.stderr or "") if isinstance(e.stderr, str) else (e.stderr or b"").decode(
            "utf-8", errors="replace"
        )
        err = (err + f"\n[timeout after {timeout}s]").strip()
        return DispatchResult(
            exit_code=124,
            stdout=out,
            stderr=err,
            duration_seconds=duration,
            runner_name="command",
        )
    except FileNotFoundError as e:
        duration = time.monotonic() - start
        return DispatchResult(
            exit_code=127,
            stdout="",
            stderr=str(e),
            duration_seconds=duration,
            runner_name="command",
        )


def execute_runner(
    spec: RunnerSpec,
    role: str,
    prompt_text: str,
    cwd: Path,
    timeout: int,
) -> DispatchResult:
    if spec.name == "cursor":
        return DispatchResult(
            exit_code=2,
            stdout="",
            stderr=CURSOR_RUNNER_MESSAGE,
            duration_seconds=0.0,
            runner_name="cursor",
        )
    if spec.name == "echo":
        return run_echo(role, prompt_text)
    if spec.name == "command":
        return run_command(spec.argv, prompt_text, cwd, timeout)
    raise ValueError(f"Cannot execute runner: {spec.name}")


def format_dispatch_markdown(
    *,
    spec: RunnerSpec,
    role: str,
    prompt_name: str,
    result: DispatchResult,
) -> str:
    stdout = result.stdout.strip() or "_empty_"
    stderr = result.stderr.strip() or "_empty_"
    return (
        "# Dispatch output\n\n"
        f"**Runner:** {spec.name}\n"
        f"**Role:** {role}\n"
        f"**Exit code:** {result.exit_code}\n"
        f"**Duration seconds:** {result.duration_seconds:.2f}\n"
        f"**Prompt:** {prompt_name}\n\n"
        "## Stdout\n\n"
        f"{stdout}\n\n"
        "## Stderr\n\n"
        f"{stderr}\n\n"
        "## Notes\n\n"
        "- Output was captured by Governor dispatch.\n"
        "- Redaction is heuristic; review before sharing.\n"
    )


def build_preview(
    store: RunStore,
    run_id: str,
    role: str,
    spec: RunnerSpec,
    timeout: int,
    *,
    replace: bool,
) -> DispatchPreview:
    run_dir, meta = store.get_run(run_id)
    validate_role(role)
    prompt_path = prompt_path_for_role(run_dir, role)
    out_path = output_path_for_role(run_dir, role)
    if out_path.exists() and not replace:
        raise FileExistsError(
            f"{out_path.name} already exists for run {meta.run_id}. "
            f"Use --replace to overwrite."
        )
    return DispatchPreview(
        run_id=meta.run_id,
        role=role,
        prompt_path=prompt_path,
        output_path=out_path,
        runner=spec,
        timeout=timeout,
        mode="preview",
    )


def dispatch_command_line(
    run_id: str,
    role: str,
    runner: str,
    *,
    approve: bool,
    command_args: list[str] | None,
    repo_path: str,
) -> str:
    parts = [
        "python -m governor dispatch",
        f"--run-id {run_id}",
        f"--role {role}",
        f"--runner {runner}",
    ]
    if command_args:
        parts.append("--command " + format_argv_display(command_args))
    if approve:
        parts.append("--approve")
    parts.append(f"--repo-path {repo_path}")
    return " ".join(parts)


def preview_dispatch(
    store: RunStore,
    run_id: str,
    role: str,
    spec: RunnerSpec,
    timeout: int,
    *,
    replace: bool,
) -> DispatchPreview:
    preview = build_preview(store, run_id, role, spec, timeout, replace=replace)
    run_dir, meta = store.get_run(run_id)
    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="dispatch",
        actor="governor",
        action="dispatch_preview",
        input_ref=preview.prompt_path.name,
        output_ref=None,
        status="ok",
        reason=f"runner={spec.name} timeout={timeout}s",
    )
    return preview


def execute_dispatch(
    store: RunStore,
    run_id: str,
    role: str,
    spec: RunnerSpec,
    timeout: int,
    *,
    replace: bool,
    repo_path: str,
) -> tuple[Path, DispatchResult]:
    preview = build_preview(store, run_id, role, spec, timeout, replace=replace)
    run_dir, meta = store.get_run(run_id)
    prompt_text = preview.prompt_path.read_text(encoding="utf-8")
    cwd = Path(meta.repo_path)

    result = execute_runner(spec, role, prompt_text, cwd, timeout)
    markdown = format_dispatch_markdown(
        spec=spec,
        role=role,
        prompt_name=preview.prompt_path.name,
        result=result,
    )
    markdown = redact(markdown)

    out_path = store.apply_dispatch_output(
        run_id,
        role,
        markdown,
        replace=replace,
        dispatch_cmd=dispatch_command_line(
            run_id,
            role,
            spec.name,
            approve=True,
            command_args=spec.argv if spec.name == "command" else None,
            repo_path=repo_path,
        ),
    )

    trace = TraceLogger(run_dir, meta.run_id)
    action = f"dispatch_{role}"
    trace.append(
        phase="dispatch",
        actor="governor",
        action=action,
        input_ref=preview.prompt_path.name,
        output_ref=out_path.name,
        status="ok" if result.exit_code == 0 else "fail",
        reason=(
            f"runner={spec.name} exit={result.exit_code} "
            f"duration={result.duration_seconds:.2f}s"
        ),
    )
    return out_path, result
