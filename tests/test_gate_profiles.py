"""Gate profile integration tests."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from governor.gates import run_gates, write_gate_artifacts
from governor.project_config import default_project_config_dict, init_project_config


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


def _minimal_fast_profile_config() -> dict:
    data = default_project_config_dict()
    data["gate_profiles"]["fast"] = {
        "description": "minimal",
        "commands": ["git_status_short", "git_diff_check", "sensitive_paths", "diff_budget"],
        "required": ["git_diff_check", "sensitive_paths"],
        "optional": ["pytest"],
    }
    return data


def test_gate_uses_default_profile_from_project_config():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        cfg = _minimal_fast_profile_config()
        (repo / "governor.project.json").write_text(
            json.dumps(cfg, indent=2) + "\n",
            encoding="utf-8",
        )
        report = run_gates(repo)
        assert report.gate_profile == "fast"
        assert "git_diff_check" in report.required_checks


def test_required_skipped_causes_fail():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        cfg = _minimal_fast_profile_config()
        cfg["gate_profiles"]["fast"]["required"] = ["pytest"]
        cfg["gate_profiles"]["fast"]["commands"] = ["pytest"]
        (repo / "governor.project.json").write_text(
            json.dumps(cfg, indent=2) + "\n",
            encoding="utf-8",
        )
        report = run_gates(repo, gate_profile="fast")
        pytest_results = [r for r in report.results if r.name == "pytest"]
        assert pytest_results
        assert report.overall == "FAIL"


def test_sensitive_path_change_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        cfg = _minimal_fast_profile_config()
        (repo / "governor.project.json").write_text(
            json.dumps(cfg, indent=2) + "\n",
            encoding="utf-8",
        )
        (repo / ".env").write_text("X=1\n", encoding="utf-8")
        subprocess.run(["git", "add", ".env"], cwd=repo, capture_output=True, check=True)
        report = run_gates(repo, gate_profile="fast")
        sens = [r for r in report.results if r.name == "sensitive_paths"]
        assert sens and sens[0].status == "FAIL"
        assert report.overall == "FAIL"


def test_diff_budget_exceeded_warns():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        cfg = _minimal_fast_profile_config()
        cfg["diff_budget"] = {
            "max_changed_files": 1,
            "max_lines_added": 5,
            "max_lines_deleted": 5,
        }
        (repo / "governor.project.json").write_text(
            json.dumps(cfg, indent=2) + "\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "governor.project.json"], cwd=repo, capture_output=True, check=True)
        (repo / "a.txt").write_text("line\n", encoding="utf-8")
        (repo / "b.txt").write_text("line\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt", "b.txt"], cwd=repo, capture_output=True, check=True)
        report = run_gates(repo, gate_profile="fast")
        budget = [r for r in report.results if r.name == "diff_budget"]
        assert budget and budget[0].status == "WARN"


def test_gate_results_json_includes_gate_profile():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        init_project_config(repo)
        report = run_gates(repo)
        run_dir = repo / ".governor" / "runs" / "test"
        run_dir.mkdir(parents=True)
        write_gate_artifacts(run_dir, report)
        data = json.loads((run_dir / "08_gate_results.json").read_text(encoding="utf-8"))
        assert data.get("gate_profile") == "fast"
