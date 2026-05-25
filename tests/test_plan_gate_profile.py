"""Plan and governed run gate_profile integration."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from governor.cli import main
from governor.run_plan import load_plan, plan_json_path
from governor.run_store import RunStore


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def test_plan_create_stores_gate_profile():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        main(["project", "init", "--repo-path", str(repo)])
        main(["config", "init", "--repo-path", str(repo)])
        main(["init", "--task", "Plan gate", "--repo-path", str(repo)])
        store = RunStore(repo)
        _, meta = store.get_run(None)
        rc = main(
            [
                "plan",
                "create",
                "--run-id",
                meta.run_id,
                "--gate-profile",
                "release",
                "--executor-runner",
                "echo",
                "--validator-runner",
                "echo",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        run_dir = repo / ".governor" / "runs" / meta.run_id
        plan = load_plan(run_dir)
        assert plan.gate_profile == "release"
