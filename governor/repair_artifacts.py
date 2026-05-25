"""Repair artifact naming and discovery (no run_store dependency)."""

from __future__ import annotations

import re
from pathlib import Path

REPAIR_PROMPT_PREFIX = "11_repair_prompt_"
REPAIR_OUTPUT_PREFIX = "07_repair_output_"
REPAIR_FAILED_SUFFIX = ".failed.md"

REPAIR_PREPARE_HINT = (
    "Prepare repair prompt first: python -m governor repair prepare --run-id {run_id}"
)


def repair_prompt_name(index: int) -> str:
    return f"{REPAIR_PROMPT_PREFIX}{index}.md"


def repair_output_name(index: int) -> str:
    return f"{REPAIR_OUTPUT_PREFIX}{index}.md"


def repair_failed_name(index: int) -> str:
    return f"{REPAIR_OUTPUT_PREFIX}{index}{REPAIR_FAILED_SUFFIX}"


def list_repair_prompts(run_dir: Path) -> list[int]:
    indices: list[int] = []
    for p in run_dir.iterdir():
        if not p.is_file():
            continue
        m = re.match(rf"^{re.escape(REPAIR_PROMPT_PREFIX)}(\d+)\.md$", p.name)
        if m:
            indices.append(int(m.group(1)))
    return sorted(indices)


def list_repair_outputs(run_dir: Path) -> list[int]:
    indices: list[int] = []
    for p in run_dir.iterdir():
        if not p.is_file():
            continue
        m = re.match(rf"^{re.escape(REPAIR_OUTPUT_PREFIX)}(\d+)\.md$", p.name)
        if m:
            indices.append(int(m.group(1)))
    return sorted(indices)


def has_repair_prompt(run_dir: Path) -> bool:
    return bool(list_repair_prompts(run_dir))


def resolve_repair_prompt_path(run_dir: Path, repair_prompt: int | None) -> tuple[Path, int]:
    prompts = list_repair_prompts(run_dir)
    if not prompts:
        raise FileNotFoundError("No repair prompts found. Run: governor repair prepare first.")
    if repair_prompt is None:
        index = prompts[-1]
    else:
        index = repair_prompt
        if index not in prompts:
            raise FileNotFoundError(
                f"Repair prompt {repair_prompt_name(index)} not found. "
                f"Available: {', '.join(repair_prompt_name(i) for i in prompts)}"
            )
    return run_dir / repair_prompt_name(index), index


def list_repair_artifacts(run_dir: Path) -> dict[str, list[str]]:
    prompts = [repair_prompt_name(i) for i in list_repair_prompts(run_dir)]
    outputs = [repair_output_name(i) for i in list_repair_outputs(run_dir)]
    failed = sorted(
        p.name
        for p in run_dir.iterdir()
        if p.is_file()
        and p.name.startswith(REPAIR_OUTPUT_PREFIX)
        and p.name.endswith(REPAIR_FAILED_SUFFIX)
    )
    return {"prompts": prompts, "outputs": outputs, "failed": failed}
