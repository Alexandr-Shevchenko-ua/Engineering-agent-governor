"""Governed run: start, resume, status, preflight."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FAKE_AGENT = ROOT / "scripts" / "fake_agent.py"

from governor.cli import main
from governor.governed_run import GovernedRunOptions, governed_run_start
from governor.preflight import run_execution_preflight
from governor.run_store import RunStore


def _git_init_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "gov@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Gov Test"],
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


def _config_init(repo: Path) -> None:
    main(["config", "init", "--repo-path", str(repo)])


def _config_with_fake_validator(repo: Path) -> None:
    main(["config", "init", "--repo-path", str(repo)])
    scripts = repo / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy(FAKE_AGENT, scripts / "fake_agent.py")
    cfg_path = repo / ".governor" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["profiles"]["fake-validator"]["argv"] = [
        sys.executable,
        "scripts/fake_agent.py",
    ]
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def test_run_start_dry_run_creates_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_init(repo)
        before = list((repo / ".governor").glob("runs/*")) if (repo / ".governor").exists() else []
        rc = main(
            [
                "run",
                "start",
                "--task",
                "Dry",
                "--use-default-profiles",
                "--dry-run",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        after = list((repo / ".governor").glob("runs/*")) if (repo / ".governor").exists() else []
        assert len(after) == len(before)


def test_run_start_no_approve_creates_run_and_plan_only():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_init(repo)
        rc = main(
            [
                "run",
                "start",
                "--task",
                "No approve",
                "--use-default-profiles",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        store = RunStore(repo)
        _, meta = store.get_run(None)
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert (run_dir / "12_run_plan.json").is_file()
        assert not (run_dir / "05_executor_output.md").exists()


def test_run_start_approve_completes_with_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_with_fake_validator(repo)
        rc = main(
            [
                "run",
                "start",
                "--task",
                "Full run",
                "--policy",
                "default",
                "--use-default-profiles",
                "--approve",
                "--continue-on-gate-warn",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        store = RunStore(repo)
        _, meta = store.get_run(None)
        assert meta.state == "FINAL_REPORT_READY"
        assert (repo / ".governor" / "runs" / meta.run_id / "05_executor_output.md").is_file()


def test_run_start_with_evidence_exports():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_with_fake_validator(repo)
        main(
            [
                "run",
                "start",
                "--task",
                "Evidence",
                "--policy",
                "default",
                "--use-default-profiles",
                "--approve",
                "--with-evidence",
                "--continue-on-gate-warn",
                "--repo-path",
                str(repo),
            ]
        )
        _, meta = RunStore(repo).get_run(None)
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert (run_dir / "14_evidence_bundle.json").is_file()


def test_run_start_missing_profiles_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        rc = main(
            [
                "run",
                "start",
                "--task",
                "No profiles",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_run_start_invalid_policy():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        rc = main(
            [
                "run",
                "start",
                "--task",
                "Bad",
                "--policy",
                "nope",
                "--use-default-profiles",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_run_start_json_output(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_init(repo)
        rc = main(
            [
                "run",
                "start",
                "--task",
                "JSON",
                "--use-default-profiles",
                "--repo-path",
                str(repo),
                "--json",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out[out.find("{") :])
        assert "run_id" in data
        assert "policy" in data


def test_checkpoint_blocks_run_start():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_with_fake_validator(repo)
        rc = main(
            [
                "run",
                "start",
                "--task",
                "CP block",
                "--policy",
                "bugfix",
                "--use-default-profiles",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        store = RunStore(repo)
        _, meta = store.get_run(None)
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert not (run_dir / "09_final_report.md").exists()


def test_preflight_strict_fails_on_warn():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        # no git — governor_gitignored WARN
        checks, ok = run_execution_preflight(str(repo), use_profiles=False, strict=True)
        assert not ok
        assert any(c.status == "WARN" for c in checks)


def test_preflight_non_strict_continues():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_init(repo)
        checks, ok = run_execution_preflight(str(repo), use_profiles=True, strict=False)
        assert ok


def test_preflight_missing_config_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        checks, ok = run_execution_preflight(str(repo), use_profiles=True, strict=False)
        assert not ok
        assert any(c.name == "profiles_config" and c.status == "FAIL" for c in checks)


def test_run_status_json(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_init(repo)
        main(
            [
                "run",
                "start",
                "--task",
                "Status",
                "--use-default-profiles",
                "--repo-path",
                str(repo),
            ]
        )
        _, meta = RunStore(repo).get_run(None)
        rc = main(
            ["run", "status", "--run-id", meta.run_id, "--repo-path", str(repo), "--json"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out[out.find("{") :])
        assert data.get("plan_overall_status") is not None
        assert "artifacts" in data


def test_run_resume_no_plan_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        store = RunStore(repo)
        _, meta = store.create_run("No plan")
        rc = main(
            [
                "run",
                "resume",
                "--run-id",
                meta.run_id,
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_governed_run_stores_policy():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _config_with_fake_validator(repo)
        opts = GovernedRunOptions(
            task="Policy store",
            repo_path=str(repo),
            policy="docs",
            use_default_profiles=True,
            approve=False,
        )
        result = governed_run_start(opts)
        assert result.run_id
        raw = json.loads(
            (result.run_dir / "run_state.json").read_text(encoding="utf-8")
        )
        assert raw.get("policy") == "docs"
