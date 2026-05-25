"""Policy packs and init/plan/evidence integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.evidence import build_evidence_bundle, export_evidence
from governor.policy import get_policy, list_policies
from governor.report import generate_reports
from governor.run_plan import create_plan, load_plan
from governor.run_store import RunStore


def _git_init_repo(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "pol@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Policy Test"],
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


def _setup_config(repo: Path) -> None:
    main(["config", "init", "--repo-path", str(repo)])


def test_policy_list_show_validate_cli():
    assert main(["policy", "list"]) == 0
    assert main(["policy", "show", "--policy", "bugfix"]) == 0
    assert main(["policy", "validate", "--policy", "bugfix"]) == 0
    assert main(["policy", "show", "--policy", "no-such"]) == 1


def test_invalid_policy_on_init():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        rc = main(
            [
                "init",
                "--task",
                "Bad policy",
                "--policy",
                "unknown-pack",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_init_bugfix_tailored_prompts():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["init", "--task", "Fix validation bug", "--policy", "bugfix", "--repo-path", str(repo)])
        store = RunStore(repo)
        _, meta = store.get_run(None)
        assert meta.policy == "bugfix"
        run_dir = repo / ".governor" / "runs" / meta.run_id
        intake = (run_dir / "00_task_intake.md").read_text(encoding="utf-8")
        assert "bugfix" in intake.lower()
        assert "regression" in intake.lower() or "failing test" in intake.lower()
        executor = (run_dir / "03_executor_prompt.md").read_text(encoding="utf-8")
        assert "Bugfix policy" in executor
        validator = (run_dir / "04_validator_prompt.md").read_text(encoding="utf-8")
        assert "root cause" in validator.lower()


def test_docs_and_refactor_templates_differ():
    bug = get_policy("bugfix")
    doc = get_policy("docs")
    ref = get_policy("refactor")
    assert "failing test" in " ".join(bug.evidence_expectations).lower()
    assert "accuracy" in " ".join(doc.evidence_expectations).lower()
    assert "no-behavior-change" in " ".join(ref.evidence_expectations).lower()


def test_run_state_stores_policy():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["init", "--task", "Docs", "--policy", "docs", "--repo-path", str(repo)])
        run_dir, meta = RunStore(repo).get_run(None)
        raw = json.loads((run_dir / "run_state.json").read_text())
        assert raw.get("policy") == "docs"


def test_plan_create_uses_policy_checkpoints():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Bug plan", policy_name="bugfix")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        plan = load_plan(repo / ".governor" / "runs" / meta.run_id)
        cp_steps = [s for s in plan.steps if s.action == "human_checkpoint"]
        assert len(cp_steps) >= 1
        assert plan.auto_repair_prepare_on_fail is True


def test_status_and_report_include_policy(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_config(repo)
        main(["init", "--task", "Policy status", "--policy", "refactor", "--repo-path", str(repo)])
        store = RunStore(repo)
        _, meta = store.get_run(None)
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        from governor.run_plan import execute_plan

        execute_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        generate_reports(store, meta.run_id)
        report = (
            repo / ".governor" / "runs" / meta.run_id / "09_final_report.md"
        ).read_text()
        assert "**Policy:** `refactor`" in report
        rc = main(["status", "--run-id", meta.run_id, "--repo-path", str(repo), "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out[out.find("{") :])
        assert data["policy"] == "refactor"


def test_evidence_policy_compliance():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Ev pol", policy_name="bugfix")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        from governor.run_plan import execute_plan

        execute_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        bundle = build_evidence_bundle(store, meta.run_id)
        assert bundle["policy"] == "bugfix"
        assert "policy_compliance" in bundle
        assert bundle["policy_compliance"]["overall"] in ("PASS", "WARN", "FAIL")


def test_test_only_executor_avoids_product_code():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["init", "--task", "Add tests", "--policy", "test-only", "--repo-path", str(repo)])
        text = (
            repo / ".governor" / "runs" / list((repo / ".governor" / "runs").iterdir())[0].name
            / "03_executor_prompt.md"
        ).read_text(encoding="utf-8")
        assert "Test-only policy" in text
        assert "production code" in text.lower()


def test_policy_names_complete():
    names = list_policies()
    assert "default" in names
    assert "agentic-tooling" in names
    assert len(names) == 7
