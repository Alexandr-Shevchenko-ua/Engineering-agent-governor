"""Review package export tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from governor.cli import main
from governor.review_package import PR_BODY_MD, REVIEW_JSON, REVIEW_MD, export_review_package
from governor.run_store import RunStore

ROOT = Path(__file__).resolve().parents[1]
FAKE_AGENT = ROOT / "scripts" / "fake_agent.py"


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


def test_review_export_creates_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Review test")
        (run_dir / "05_executor_output.md").write_text("# done\n", encoding="utf-8")
        (run_dir / "09_final_report.md").write_text("# done\n", encoding="utf-8")
        store.update_state(meta.run_id, "record_executor")
        store.update_state(meta.run_id, "report")
        md_p, json_p, pr_p = export_review_package(store, meta.run_id)
        assert md_p and md_p.name == REVIEW_MD
        assert json_p and json_p.name == REVIEW_JSON
        assert pr_p and pr_p.name == PR_BODY_MD
        body = pr_p.read_text(encoding="utf-8")
        assert "## Summary" in body
        assert "## Validation" in body
        assert "## Risk" in body


def test_run_start_with_review_package_after_pass():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        _config_with_fake_validator(repo)
        rc = main(
            [
                "run",
                "start",
                "--task",
                "Review export",
                "--use-default-profiles",
                "--approve",
                "--with-review-package",
                "--continue-on-gate-warn",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        store = RunStore(repo)
        _, meta = store.get_run(None)
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert (run_dir / REVIEW_MD).is_file()
        assert (run_dir / PR_BODY_MD).is_file()
        pkg = json.loads((run_dir / REVIEW_JSON).read_text(encoding="utf-8"))
        assert pkg.get("task") == "Review export"
        assert "gate" in pkg
