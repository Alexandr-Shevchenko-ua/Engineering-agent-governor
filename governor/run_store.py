"""Run folder lifecycle: create, load, update, record outputs."""

from __future__ import annotations

import json
from pathlib import Path

from governor.models import (
    ROLE_FAILED_OUTPUT_FILES,
    ROLE_OUTPUT_FILES,
    RunMetadata,
    RunState,
    record_action_for_role,
    repair_failed_output_name,
    require_transition,
    transition_state,
)
from governor.repair_artifacts import (
    REPAIR_PREPARE_HINT,
    has_repair_prompt,
    repair_output_name,
)
from governor.redaction import redact
from governor.policy import build_init_artifacts, get_policy
from governor.project_config import resolve_policy_for_repo
from governor.templates import (
    executor_prompt,
    risk_register,
    scope_and_assumptions,
    task_intake,
    validator_prompt,
)
from governor.index import find_run_dir, upsert_entry
from governor.trace import TraceLogger
from governor.utils import (
    require_governor_runs,
    resolve_repo_path,
    runs_dir,
    slugify,
    utc_now_iso,
    utc_run_timestamp,
)


STATE_FILE = "run_state.json"


class RunStore:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path

    def _state_path(self, run_dir: Path) -> Path:
        return run_dir / STATE_FILE

    def load_metadata(self, run_dir: Path) -> RunMetadata:
        path = self._state_path(run_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunMetadata.from_dict(data)

    def save_metadata(self, run_dir: Path, meta: RunMetadata) -> None:
        meta.updated_at = utc_now_iso()
        self._state_path(run_dir).write_text(
            json.dumps(meta.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        upsert_entry(self.repo_path, meta, run_dir)

    def create_run(
        self,
        task: str,
        *,
        policy_name: str | None = None,
    ) -> tuple[Path, RunMetadata]:
        runs_dir(self.repo_path).mkdir(parents=True, exist_ok=True)
        slug = slugify(task)
        run_id = f"{utc_run_timestamp()}_{slug}"
        run_dir = runs_dir(self.repo_path) / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        resolved_policy = resolve_policy_for_repo(self.repo_path, policy_name)
        policy = get_policy(resolved_policy)

        now = utc_now_iso()
        meta = RunMetadata(
            run_id=run_id,
            task=task,
            repo_path=str(self.repo_path),
            state=RunState.INTAKE_CREATED.value,
            created_at=now,
            updated_at=now,
            policy=resolved_policy,
        )

        repo_str = str(self.repo_path)
        if resolved_policy == "default":
            artifacts = {
                "00_task_intake.md": task_intake(task, repo_str, run_id),
                "01_scope_and_assumptions.md": scope_and_assumptions(task),
                "02_risk_register.md": risk_register(),
                "03_executor_prompt.md": executor_prompt(task, repo_str, run_id),
                "04_validator_prompt.md": validator_prompt(task, repo_str, run_id),
            }
        else:
            artifacts = build_init_artifacts(policy, task, repo_str, run_id)
        for name, content in artifacts.items():
            (run_dir / name).write_text(content, encoding="utf-8")

        self.save_metadata(run_dir, meta)
        trace = TraceLogger(run_dir, run_id)
        trace.append(
            phase="intake",
            actor="governor",
            action="init",
            output_ref=str(run_dir),
            reason=f"Created run for task: {task} (policy={resolved_policy})",
        )

        meta.state = require_transition(RunState.INTAKE_CREATED, "init").value
        cmd = f"python -m governor init --task {task!r} --policy {resolved_policy} --repo-path {self.repo_path}"
        meta.commands_executed.append(cmd)
        self.save_metadata(run_dir, meta)
        return run_dir, meta

    def get_run(self, run_id: str | None) -> tuple[Path, RunMetadata]:
        run_dir = find_run_dir(self.repo_path, run_id)
        return run_dir, self.load_metadata(run_dir)

    def list_artifacts(self, run_dir: Path) -> list[str]:
        return sorted(p.name for p in run_dir.iterdir() if p.is_file())

    def record_output(
        self,
        run_id: str,
        role: str,
        *,
        file_path: Path | None = None,
        text: str | None = None,
        replace: bool = False,
    ) -> Path:
        run_dir, meta = self.get_run(run_id)
        trace = TraceLogger(run_dir, meta.run_id)

        if role == "repair":
            if not has_repair_prompt(run_dir):
                raise ValueError(REPAIR_PREPARE_HINT.format(run_id=run_id))
            meta.repair_count += 1
            out_name = repair_output_name(meta.repair_count)
        elif role in ROLE_OUTPUT_FILES:
            out_name = ROLE_OUTPUT_FILES[role]
        else:
            raise ValueError(f"Unknown role: {role}")

        action = record_action_for_role(role)
        state = RunState(meta.state)

        if file_path:
            content = file_path.read_text(encoding="utf-8")
            input_ref = str(file_path)
        elif text is not None:
            content = text
            input_ref = "stdin:text"
        else:
            raise ValueError("Either --file or --text is required")

        content = redact(content)
        out_path = run_dir / out_name
        had_existing = out_path.exists()

        protected_roles = {"executor", "validator"}
        if role in protected_roles and had_existing and not replace:
            raise FileExistsError(
                f"{out_name} already exists for run {run_id}. "
                f"Use --replace to overwrite (audit trail protection)."
            )

        if role == "human_note":
            next_state = state
        elif replace and had_existing:
            next_state = state
        else:
            next_state = require_transition(state, action)

        if role == "human_note" and had_existing:
            existing = out_path.read_text(encoding="utf-8")
            content = existing + "\n\n---\n\n" + content
        out_path.write_text(content, encoding="utf-8")
        meta.state = next_state.value
        cmd = f"python -m governor record --run-id {run_id} --role {role}"
        meta.commands_executed.append(cmd)
        self.save_metadata(run_dir, meta)

        trace.append(
            phase="record",
            actor="human",
            action=action,
            input_ref=input_ref,
            output_ref=out_name,
            status="ok",
        )
        return out_path

    def update_state(self, run_id: str, action: str, *, outcome: str | None = None) -> RunMetadata:
        run_dir, meta = self.get_run(run_id)
        state = RunState(meta.state)
        meta.state = require_transition(state, action).value
        if outcome:
            meta.outcome = outcome
        self.save_metadata(run_dir, meta)
        return meta

    def append_command(self, run_id: str, command: str) -> None:
        run_dir, meta = self.get_run(run_id)
        meta.commands_executed.append(command)
        self.save_metadata(run_dir, meta)

    def write_failed_dispatch_artifact(
        self,
        run_dir: Path,
        role: str,
        content: str,
    ) -> Path:
        """Diagnostic artifact only; does not change workflow state or commands."""
        if role not in ROLE_FAILED_OUTPUT_FILES:
            raise ValueError(f"No failed artifact mapping for role: {role}")
        out_path = run_dir / ROLE_FAILED_OUTPUT_FILES[role]
        out_path.write_text(content, encoding="utf-8")
        return out_path

    def write_failed_repair_dispatch(
        self,
        run_dir: Path,
        repair_index: int,
        content: str,
    ) -> Path:
        out_path = run_dir / repair_failed_output_name(repair_index)
        out_path.write_text(content, encoding="utf-8")
        return out_path

    def apply_repair_dispatch_output(
        self,
        run_id: str,
        repair_index: int,
        content: str,
        *,
        replace: bool = False,
        dispatch_cmd: str | None = None,
    ) -> Path:
        run_dir, meta = self.get_run(run_id)
        out_name = repair_output_name(repair_index)
        out_path = run_dir / out_name
        action = "record_repair"
        state = RunState(meta.state)

        had_existing = out_path.exists()
        if had_existing and not replace:
            raise FileExistsError(
                f"{out_name} already exists for run {run_id}. "
                f"Use --replace to overwrite (audit trail protection)."
            )

        if replace and had_existing:
            next_state = state
        else:
            next_state = require_transition(state, action)

        out_path.write_text(content, encoding="utf-8")
        meta.repair_count = max(meta.repair_count, repair_index)
        meta.state = next_state.value
        cmd = dispatch_cmd or (
            f"python -m governor dispatch --run-id {run_id} --role repair "
            f"--repair-prompt {repair_index} --approve"
        )
        meta.commands_executed.append(cmd)
        self.save_metadata(run_dir, meta)
        return out_path

    def apply_dispatch_output(
        self,
        run_id: str,
        role: str,
        content: str,
        *,
        replace: bool = False,
        dispatch_cmd: str | None = None,
    ) -> Path:
        """Write successful dispatch output and transition state like record."""
        if role not in ("executor", "validator"):
            raise ValueError(f"Dispatch does not support role: {role}")

        run_dir, meta = self.get_run(run_id)
        out_name = ROLE_OUTPUT_FILES[role]
        out_path = run_dir / out_name
        action = record_action_for_role(role)
        state = RunState(meta.state)

        had_existing = out_path.exists()
        if had_existing and not replace:
            raise FileExistsError(
                f"{out_name} already exists for run {run_id}. "
                f"Use --replace to overwrite (audit trail protection)."
            )

        if replace and had_existing:
            next_state = state
        else:
            next_state = require_transition(state, action)

        out_path.write_text(content, encoding="utf-8")
        meta.state = next_state.value
        cmd = dispatch_cmd or f"python -m governor dispatch --run-id {run_id} --role {role}"
        meta.commands_executed.append(cmd)
        self.save_metadata(run_dir, meta)
        return out_path


def open_store(repo_path: str | None = None, *, require_runs: bool = True) -> RunStore:
    """Open a store for an existing repo. Does not create `.governor` by default."""
    path = resolve_repo_path(repo_path)
    if require_runs:
        require_governor_runs(path)
    return RunStore(path)


def init_store(repo_path: str | None = None) -> RunStore:
    """Open store for init; creates `.governor/runs` parent when the run is created."""
    return RunStore(resolve_repo_path(repo_path))
