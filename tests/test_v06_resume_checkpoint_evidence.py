"""v0.6.0: plan resume, human checkpoints, evidence export, plan validate."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.evidence import EVIDENCE_JSON, EVIDENCE_MD, export_evidence
from governor.models import RunState
from governor.repair import prepare_repair
from governor.run_plan import (
    RESUME_APPROVE_REQUIRED_MSG,
    RESUME_REPAIR_MANUAL_MSG,
    approve_checkpoint,
    create_plan,
    execute_plan,
    load_plan,
    resume_plan,
    save_plan,
    validate_plan,
)
from governor.run_store import RunStore


def _git_init_repo(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "v06@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "V06 Test"],
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


def _setup_repo_with_config(repo: Path) -> None:
    main(["config", "init", "--repo-path", str(repo)])


def test_resume_skips_pass_steps():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Resume skip")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        execute_plan(
            store,
            meta.run_id,
            approve=True,
            until="gate",
            repo_path=str(repo),
        )
        plan = load_plan(run_dir)
        ex = next(s for s in plan.steps if s.step_id == "dispatch_executor")
        assert ex.status == "PASS"
        result = resume_plan(
            store,
            meta.run_id,
            approve=True,
            repo_path=str(repo),
        )
        plan2 = load_plan(run_dir)
        assert plan2.steps[0].status == "PASS"
        assert result.steps_run >= 1


def test_resume_after_gate_fail_with_repair_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Gate fail resume")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        execute_plan(
            store,
            meta.run_id,
            approve=True,
            until="gate",
            repo_path=str(repo),
        )
        gate_json = run_dir / "08_gate_results.json"
        data = json.loads(gate_json.read_text(encoding="utf-8"))
        data["overall"] = "FAIL"
        gate_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        plan = load_plan(run_dir)
        gate_step = next(s for s in plan.steps if s.step_id == "gate")
        gate_step.status = "FAIL"
        save_plan(run_dir, plan)
        prepare_repair(store, meta.run_id, reason="test", force=True)
        result = resume_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        assert result.exit_code == 1
        assert RESUME_REPAIR_MANUAL_MSG in result.message


def test_checkpoint_execute_and_resume():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Checkpoint flow")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
            checkpoints=[("gate", "Review gate before validator")],
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        result = execute_plan(
            store,
            meta.run_id,
            approve=True,
            repo_path=str(repo),
        )
        assert result.overall_status == "BLOCKED"
        cp = next(
            s for s in load_plan(run_dir).steps if s.action == "human_checkpoint"
        )
        assert cp.status == "BLOCKED"
        approve_checkpoint(
            store,
            meta.run_id,
            cp.step_id,
            note="Reviewed gate results",
        )
        assert (run_dir / "13_human_checkpoints.md").is_file()
        trace = (run_dir / "trace.jsonl").read_text()
        assert "human_checkpoint_approve" in trace
        result2 = resume_plan(
            store,
            meta.run_id,
            approve=True,
            repo_path=str(repo),
        )
        assert result2.overall_status == "PASS"
        _, updated = store.get_run(meta.run_id)
        assert updated.state == RunState.FINAL_REPORT_READY.value


def test_resume_requires_approve():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Resume approve")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        result = resume_plan(store, meta.run_id, approve=False)
        assert result.exit_code == 1
        assert RESUME_APPROVE_REQUIRED_MSG in result.message


def test_resume_dry_run_no_writes():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Resume dry")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        resume_plan(store, meta.run_id, approve=True, dry_run=True)
        assert not (run_dir / "05_executor_output.md").exists()


def test_resume_max_steps():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Resume max")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        result = resume_plan(
            store,
            meta.run_id,
            approve=True,
            max_steps=1,
            repo_path=str(repo),
        )
        assert result.steps_run <= 1


def test_checkpoint_note_required():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Note req")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
            checkpoints=[("gate", "Review")],
        )
        with pytest.raises(ValueError, match="note"):
            approve_checkpoint(store, meta.run_id, "checkpoint_after_gate", note="")


def test_plan_create_with_checkpoint_after_gate():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("CP create")
        plan = create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
            checkpoints=[("gate", "Review gate")],
        )
        actions = [s.action for s in plan.steps]
        assert "human_checkpoint" in actions
        idx_gate = next(i for i, s in enumerate(plan.steps) if s.step_id == "gate")
        assert plan.steps[idx_gate + 1].action == "human_checkpoint"


def test_evidence_export_creates_files():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Evidence")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        execute_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        run_dir = repo / ".governor" / "runs" / meta.run_id
        export_evidence(store, meta.run_id)
        assert (run_dir / EVIDENCE_MD).is_file()
        assert (run_dir / EVIDENCE_JSON).is_file()
        bundle = json.loads((run_dir / EVIDENCE_JSON).read_text())
        assert bundle.get("plan")
        assert bundle.get("gate")
        assert "validator_verdict" in bundle
        assert "prompts" not in bundle
        assert "prompt_artifacts" in bundle


def test_evidence_include_prompts():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Prompts")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        execute_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        from governor.evidence import build_evidence_bundle

        bundle = build_evidence_bundle(store, meta.run_id, include_prompts=True)
        assert "prompts" in bundle


def test_status_json_evidence_flag(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Status json")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        execute_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        export_evidence(store, meta.run_id)
        rc = main(
            ["status", "--run-id", meta.run_id, "--repo-path", str(repo), "--json"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        start = out.find("{")
        assert start >= 0, f"no JSON in stdout: {out!r}"
        data = json.loads(out[start:])
        assert data["run_id"] == meta.run_id
        assert data["evidence_bundle_exists"] is True
        assert data.get("plan")


def test_plan_validate_valid():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Valid")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        lines, has_fail = validate_plan(store, meta.run_id)
        assert not has_fail
        assert any(l.level == "OK" for l in lines)


def test_plan_validate_unknown_action():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Bad action")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        raw = json.loads((run_dir / "12_run_plan.json").read_text())
        raw["steps"][0]["action"] = "fly_to_moon"
        (run_dir / "12_run_plan.json").write_text(json.dumps(raw), encoding="utf-8")
        _, has_fail = validate_plan(store, meta.run_id)
        assert has_fail


def test_plan_validate_duplicate_step_id():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Dup id")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        raw = json.loads((run_dir / "12_run_plan.json").read_text())
        raw["steps"].append(raw["steps"][0])
        (run_dir / "12_run_plan.json").write_text(json.dumps(raw), encoding="utf-8")
        _, has_fail = validate_plan(store, meta.run_id)
        assert has_fail


def test_plan_validate_missing_profile():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Missing prof")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        raw = json.loads((run_dir / "12_run_plan.json").read_text())
        for s in raw["steps"]:
            if s.get("profile") == "echo-test":
                s["profile"] = "no-such-profile"
        (run_dir / "12_run_plan.json").write_text(json.dumps(raw), encoding="utf-8")
        _, has_fail = validate_plan(store, meta.run_id)
        assert has_fail


def test_plan_validate_disabled_profile():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Disabled")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        cfg = json.loads((repo / ".governor" / "config.json").read_text())
        cfg["profiles"]["echo-test"]["enabled"] = False
        (repo / ".governor" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        _, has_fail = validate_plan(store, meta.run_id)
        assert has_fail


def test_plan_validate_secret_argv():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Secret argv")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        raw = json.loads((run_dir / "12_run_plan.json").read_text())
        for s in raw["steps"]:
            if s.get("step_id") == "dispatch_executor":
                s["profile"] = None
                s["runner"] = "command"
                s["command"] = ["echo", "api_key=secret123"]
        (run_dir / "12_run_plan.json").write_text(json.dumps(raw), encoding="utf-8")
        _, has_fail = validate_plan(store, meta.run_id)
        assert has_fail


def test_evidence_excludes_prompt_bodies_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("No prompts")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        execute_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        run_dir = repo / ".governor" / "runs" / meta.run_id
        export_evidence(store, meta.run_id)
        bundle = json.loads((run_dir / EVIDENCE_JSON).read_text())
        assert "prompts" not in bundle
