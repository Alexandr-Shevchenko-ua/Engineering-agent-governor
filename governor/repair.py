"""Bounded repair-pack workflow: prepare prompts (no autopilot)."""

from __future__ import annotations

import json
from pathlib import Path

from governor.models import RunMetadata, RunState
from governor.repair_artifacts import (
    REPAIR_PREPARE_HINT,
    has_repair_prompt,
    list_repair_artifacts,
    list_repair_outputs,
    list_repair_prompts,
    repair_prompt_name,
    resolve_repair_prompt_path,
)
from governor.run_store import RunStore
from governor.trace import TraceLogger

# Re-export for callers
__all__ = [
    "REPAIR_PREPARE_HINT",
    "has_repair_prompt",
    "list_repair_artifacts",
    "list_repair_prompts",
    "list_repair_outputs",
    "prepare_repair",
    "repair_output_name",
    "repair_prompt_name",
    "require_repair_prompt",
    "resolve_repair_prompt_path",
]

from governor.repair_artifacts import repair_output_name  # noqa: E402

DEFAULT_MAX_REPAIRS = 2

PREPARE_ALLOWED_STATES = frozenset(
    {
        RunState.GATES_RUN,
        RunState.VALIDATOR_OUTPUT_RECORDED,
        RunState.REPAIR_RECORDED,
    }
)

PREPARE_BLOCKED_WITHOUT_FORCE = frozenset(
    {
        RunState.EXECUTOR_PROMPT_READY,
        RunState.INTAKE_CREATED,
        RunState.FINAL_REPORT_READY,
        RunState.EXECUTOR_OUTPUT_RECORDED,
        RunState.HUMAN_DECISION_REQUIRED,
    }
)


def require_repair_prompt(run_dir: Path, run_id: str) -> None:
    if not has_repair_prompt(run_dir):
        raise ValueError(REPAIR_PREPARE_HINT.format(run_id=run_id))


def _read_snippet(run_dir: Path, name: str, max_chars: int = 2500) -> str:
    path = run_dir / name
    if not path.is_file():
        return "_Not present._"
    text = path.read_text(encoding="utf-8").strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n... (truncated)"
    return text


def _gate_failure_summary(run_dir: Path) -> str:
    json_p = run_dir / "08_gate_results.json"
    md_p = run_dir / "08_gate_results.md"
    if json_p.is_file():
        try:
            data = json.loads(json_p.read_text(encoding="utf-8"))
            overall = data.get("overall", "unknown")
            failed = [
                r.get("name", "?")
                for r in data.get("results", [])
                if r.get("status") == "FAIL"
            ]
            warned = [
                r.get("name", "?")
                for r in data.get("results", [])
                if r.get("status") == "WARN"
            ]
            parts = [f"Overall: {overall}"]
            if failed:
                parts.append(f"Failed checks: {', '.join(failed)}")
            if warned:
                parts.append(f"Warnings: {', '.join(warned)}")
            return "\n".join(parts)
        except (OSError, json.JSONDecodeError):
            pass
    if md_p.is_file():
        return _read_snippet(run_dir, "08_gate_results.md", 1500)
    return "_Gates not run._"


def build_repair_prompt_body(
    meta: RunMetadata,
    *,
    reason: str,
    prompt_index: int,
    run_dir: Path,
) -> str:
    existing_outputs = list_repair_outputs(run_dir)
    outputs_summary = (
        ", ".join(repair_output_name(i) for i in existing_outputs)
        if existing_outputs
        else "_None yet._"
    )
    return f"""# Repair prompt #{prompt_index}

> **Bounded repair** — fix only the issues listed below. Do not broaden scope, refactor unrelated code, or touch secrets.

## Run context

| Field | Value |
|-------|-------|
| Run ID | `{meta.run_id}` |
| Task | {meta.task} |
| Current state | `{meta.state}` |
| Reason | {reason} |

## Gate summary

{_gate_failure_summary(run_dir)}

## Validator summary

{_read_snippet(run_dir, "06_validator_output.md")}

## Executor summary

{_read_snippet(run_dir, "05_executor_output.md")}

## Existing repair outputs

{outputs_summary}

## Instructions (strict)

1. Fix **only** the issues implied by gate/validator findings and the reason above.
2. **No** broad refactors, drive-by changes, or new features outside the repair scope.
3. **Do not** commit secrets, tokens, or credentials in code or logs.
4. Run relevant local checks (tests, lint) and report commands executed.
5. In your repair output, list: **changed files**, **commands run**, **remaining risks**.
6. If the issue cannot be fixed safely without lead input, state **HUMAN_DECISION_REQUIRED** and stop.

## After repair (human workflow)

Governor does **not** auto-run gate or validator. After recording or dispatching repair output:

1. `python -m governor gate --run-id {meta.run_id} --repo-path .`
2. Re-run validator or `report` when appropriate.

Record output to `07_repair_output_{prompt_index}.md` or use `governor dispatch --role repair --approve`.
"""


def prepare_repair(
    store: RunStore,
    run_id: str,
    *,
    reason: str = "Address gate/validator findings",
    force: bool = False,
    max_repairs: int = DEFAULT_MAX_REPAIRS,
) -> Path:
    run_dir, meta = store.get_run(run_id)
    state = RunState(meta.state)

    if state in PREPARE_BLOCKED_WITHOUT_FORCE and not force:
        raise ValueError(
            f"Cannot prepare repair from state {state.value}. "
            f"Allowed: {', '.join(s.value for s in PREPARE_ALLOWED_STATES)}. Use --force to override."
        )
    if state not in PREPARE_ALLOWED_STATES and not force:
        raise ValueError(
            f"Cannot prepare repair from state {state.value}. "
            f"Allowed: {', '.join(s.value for s in PREPARE_ALLOWED_STATES)}."
        )

    prompt_count = getattr(meta, "repair_prompt_count", 0) or len(list_repair_prompts(run_dir))
    if prompt_count >= max_repairs and not force:
        raise ValueError(
            f"Max repair prompts ({max_repairs}) reached. Use --force to add another."
        )

    next_index = (max(list_repair_prompts(run_dir), default=0)) + 1
    out_name = repair_prompt_name(next_index)
    out_path = run_dir / out_name
    if out_path.exists() and not force:
        raise FileExistsError(f"{out_name} already exists. Use --force to overwrite.")

    body = build_repair_prompt_body(
        meta,
        reason=reason,
        prompt_index=next_index,
        run_dir=run_dir,
    )
    out_path.write_text(body, encoding="utf-8")

    meta.repair_prompt_count = next_index
    cmd = (
        f"python -m governor repair prepare --run-id {run_id} "
        f"--reason {reason!r}"
    )
    if force:
        cmd += " --force"
    meta.commands_executed.append(cmd)
    store.save_metadata(run_dir, meta)

    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="repair",
        actor="governor",
        action="repair_prepare",
        output_ref=out_name,
        status="ok",
        reason=f"index={next_index}; bounded repair; {reason[:120]}",
    )
    return out_path
