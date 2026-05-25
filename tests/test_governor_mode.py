"""Tests for experimental Chatbang Governor Mode (v1.2)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from governor.cli import main
from governor.governor_mode import (
    PROPOSAL_JSON,
    RAW_RESPONSE_MD,
    SAFETY_FLAG_ADVISOR_LEAK,
    SAFETY_FLAG_UNSTRUCTURED,
    GovernorProposal,
    _destructive_pattern_violation,
    apply_proposal,
    create_proposal_id,
    looks_like_advisor_leak,
    parse_proposal_json_from_response,
    proposal_from_parsed,
    propose_governor_mode,
    reject_proposal,
    save_proposal_artifacts,
    validate_proposal,
    validate_proposal_id,
)
from governor.run_plan import PLAN_JSON
from governor.utils import proposals_dir

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "scripts" / "fake_chatbang.py"
DOCS = ROOT / "docs"


def _git_init(repo: Path) -> None:
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
    (repo / ".gitignore").write_text(".governor/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def _init_project_and_config(repo: Path) -> None:
    rp = str(repo)
    assert main(["project", "init", "--repo-path", rp]) == 0
    assert main(["config", "init", "--repo-path", rp]) == 0
    cfg_path = repo / ".governor" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    for name in ("echo-test", "fake-validator"):
        if name in cfg.get("profiles", {}):
            cfg["profiles"][name]["enabled"] = True
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def test_proposal_id_format() -> None:
    pid = create_proposal_id("Add governor mode")
    assert re.match(r"^[0-9]{8}T[0-9]{6}Z_[a-z0-9_-]+$", pid)
    assert validate_proposal_id(pid) == pid
    with pytest.raises(ValueError):
        validate_proposal_id("../evil")


def test_parse_bare_json_object() -> None:
    raw = '{"task": "t", "recommended_policy": "default", "assumptions": ["a"]}'
    data = parse_proposal_json_from_response(raw)
    assert data is not None
    assert data["task"] == "t"


def test_advisor_leak_detection() -> None:
    raw = "VERDICT: ASK WHY\n\nPaste the task objective."
    assert looks_like_advisor_leak(raw)
    assert not parse_proposal_json_from_response(raw)


def test_parse_structured_json_fence() -> None:
    raw = 'Rationale here\n```json\n{"task": "t", "recommended_policy": "default"}\n```\n'
    data = parse_proposal_json_from_response(raw)
    assert data is not None
    assert data["task"] == "t"


def test_unstructured_response_flag(tmp_path: Path) -> None:
    _git_init(tmp_path)
    proposal_id = create_proposal_id("unstructured test")
    pdir = proposals_dir(tmp_path) / proposal_id
    proposal = proposal_from_parsed(
        {"task": "x", "recommended_policy": "default"},
        proposal_id=proposal_id,
        task="x",
        repo_path=str(tmp_path),
        provider="chatbang",
        safety_flags=[SAFETY_FLAG_UNSTRUCTURED],
        confidence="LOW",
    )
    save_proposal_artifacts(pdir, proposal, raw_response="no json here")
    result = validate_proposal(tmp_path, proposal_id)
    assert not result.ok
    assert any(d.check == "unstructured" and d.status == "FAIL" for d in result.decisions)


def test_validation_rejects_destructive_commands(tmp_path: Path) -> None:
    _git_init(tmp_path)
    proposal_id = create_proposal_id("destructive")
    pdir = proposals_dir(tmp_path) / proposal_id
    proposal = GovernorProposal(
        proposal_id=proposal_id,
        created_at="2026-05-25T12:00:00Z",
        provider="chatbang",
        task="bad task",
        repo_path=str(tmp_path),
        recommended_policy="default",
        assumptions=["a"],
        risk_register=["r"],
        acceptance_criteria=["c"],
        executor_prompt="Run git push origin main after deploy to production",
        validator_prompt="Check it",
        stop_conditions=["stop"],
        required_human_decisions=["human"],
        confidence="HIGH",
    )
    save_proposal_artifacts(pdir, proposal, raw_response="raw")
    result = validate_proposal(tmp_path, proposal_id)
    assert not result.ok
    assert any(d.check == "destructive" for d in result.decisions)


def test_validation_rejects_secrets(tmp_path: Path) -> None:
    _git_init(tmp_path)
    proposal_id = create_proposal_id("secrets")
    pdir = proposals_dir(tmp_path) / proposal_id
    proposal = GovernorProposal(
        proposal_id=proposal_id,
        created_at="2026-05-25T12:00:00Z",
        provider="chatbang",
        task="leak",
        repo_path=str(tmp_path),
        recommended_policy="default",
        assumptions=["a"],
        risk_register=["r"],
        acceptance_criteria=["c"],
        executor_prompt="use ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
        validator_prompt="v",
        stop_conditions=["s"],
        required_human_decisions=["h"],
        confidence="MEDIUM",
    )
    save_proposal_artifacts(pdir, proposal, raw_response="raw")
    result = validate_proposal(tmp_path, proposal_id)
    assert not result.ok
    assert any(d.check == "secrets" for d in result.decisions)


def test_list_show_reject(tmp_path: Path) -> None:
    _git_init(tmp_path)
    proposal_id = create_proposal_id("reject me")
    pdir = proposals_dir(tmp_path) / proposal_id
    proposal = GovernorProposal(
        proposal_id=proposal_id,
        created_at="2026-05-25T12:00:00Z",
        provider="chatbang",
        task="reject me",
        repo_path=str(tmp_path),
        recommended_policy="default",
        assumptions=["a"],
        risk_register=["r"],
        acceptance_criteria=["c"],
        executor_prompt="do work",
        validator_prompt="check",
        stop_conditions=["s"],
        required_human_decisions=["h"],
    )
    save_proposal_artifacts(pdir, proposal, raw_response="raw")
    assert main(["governor", "list", "--repo-path", str(tmp_path)]) == 0
    assert main(["governor", "show", "--proposal", proposal_id, "--repo-path", str(tmp_path)]) == 0
    reject_proposal(tmp_path, proposal_id, "not needed")
    data = json.loads((pdir / PROPOSAL_JSON).read_text(encoding="utf-8"))
    assert data["status"] == "REJECTED"


def test_apply_dry_run_no_run(tmp_path: Path) -> None:
    pytest.importorskip("pexpect")
    _git_init(tmp_path)
    _init_project_and_config(tmp_path)
    fake_cmd = f"{sys.executable} {FAKE}"
    assert (
        main(
            [
                "governor",
                "propose",
                "--task",
                "Apply dry run",
                "--chatbang-command",
                fake_cmd,
                "--timeout",
                "60",
                "--repo-path",
                str(tmp_path),
            ]
        )
        == 0
    )
    entries = list((proposals_dir(tmp_path)).iterdir())
    pid = next(p.name for p in entries if p.is_dir())
    runs_before = list((tmp_path / ".governor" / "runs").glob("*")) if (tmp_path / ".governor" / "runs").is_dir() else []
    assert main(["governor", "apply", "--proposal", pid, "--repo-path", str(tmp_path)]) == 0
    runs_after = list((tmp_path / ".governor" / "runs").glob("*")) if (tmp_path / ".governor" / "runs").is_dir() else []
    assert len(runs_after) == len(runs_before)


def test_apply_approve_creates_run_and_plan_no_execution(tmp_path: Path) -> None:
    pytest.importorskip("pexpect")
    _git_init(tmp_path)
    _init_project_and_config(tmp_path)
    fake_cmd = f"{sys.executable} {FAKE}"
    assert (
        main(
            [
                "governor",
                "propose",
                "--task",
                "Apply approve",
                "--chatbang-command",
                fake_cmd,
                "--timeout",
                "60",
                "--repo-path",
                str(tmp_path),
            ]
        )
        == 0
    )
    pid = next(p.name for p in proposals_dir(tmp_path).iterdir() if p.is_dir())
    assert main(["governor", "validate", "--proposal", pid, "--repo-path", str(tmp_path)]) == 0
    assert (
        main(
            [
                "governor",
                "apply",
                "--proposal",
                pid,
                "--approve",
                "--repo-path",
                str(tmp_path),
            ]
        )
        == 0
    )
    pdata = json.loads((proposals_dir(tmp_path) / pid / PROPOSAL_JSON).read_text(encoding="utf-8"))
    assert pdata["status"] == "APPLIED"
    run_id = pdata["applied_run_id"]
    run_dir = tmp_path / ".governor" / "runs" / run_id
    assert (run_dir / PLAN_JSON).is_file()
    assert not (run_dir / "05_executor_output.md").is_file()
    assert (run_dir / "00_governor_proposal_ref.json").is_file()
    ref = json.loads((run_dir / "00_governor_proposal_ref.json").read_text(encoding="utf-8"))
    assert ref["proposal_id"] == pid


def test_proposal_artifacts_redacted(tmp_path: Path) -> None:
    _git_init(tmp_path)
    proposal_id = create_proposal_id("redact")
    pdir = proposals_dir(tmp_path) / proposal_id
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"
    proposal = GovernorProposal(
        proposal_id=proposal_id,
        created_at="2026-05-25T12:00:00Z",
        provider="chatbang",
        task="redact",
        repo_path=str(tmp_path),
        recommended_policy="default",
        assumptions=["a"],
        risk_register=["r"],
        acceptance_criteria=["c"],
        executor_prompt=secret,
        validator_prompt="ok",
        stop_conditions=["s"],
        required_human_decisions=["h"],
    )
    save_proposal_artifacts(pdir, proposal, raw_response=secret)
    md = (pdir / "proposal.md").read_text(encoding="utf-8")
    assert "ghp_" not in md or "[REDACTED" in md


def test_docs_mention_experimental() -> None:
    text = (DOCS / "CHATBANG_GOVERNOR_MODE.md").read_text(encoding="utf-8")
    assert "experimental" in text.lower()
    assert "not" in text.lower() and "autopilot" in text.lower()


def test_destructive_negation_allows_do_not_git_push() -> None:
    blob = "Scope:\n- Do **not** run git push, merge, or deploy.\n"
    assert _destructive_pattern_violation(blob) is None


def test_destructive_still_flags_bare_git_push() -> None:
    blob = "Then run git push to origin main."
    viol = _destructive_pattern_violation(blob)
    assert viol is not None


def test_validate_passes_when_executor_forbids_push(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _init_project_and_config(tmp_path)
    pid = create_proposal_id("negation validate")
    pdir = proposals_dir(tmp_path) / pid
    pdir.mkdir(parents=True)
    proposal = GovernorProposal(
        proposal_id=pid,
        created_at="2026-05-25T12:00:00Z",
        provider="cursor-auto",
        task="docs link",
        repo_path=str(tmp_path),
        recommended_policy="docs",
        assumptions=["docs only"],
        risk_register=["scope creep"],
        acceptance_criteria=["README updated"],
        executor_prompt="# Executor\n\nDo **not** run git push or deploy.\n",
        validator_prompt="# Validator\n\nCheck README only.\n",
        recommended_profiles={"executor": "echo-test", "validator": "fake-validator"},
        stop_conditions=["gate fail"],
        required_human_decisions=["approve"],
        confidence="HIGH",
        safety_flags=["CURSOR_GOVERNOR_PROVIDER", "READ_ONLY_PROVIDER"],
        provider_mode="ask/read-only",
    )
    save_proposal_artifacts(pdir, proposal, raw_response="{}")
    result = validate_proposal(tmp_path, pid)
    assert result.ok
    destructive = next(d for d in result.decisions if d.check == "destructive")
    assert destructive.status == "PASS"
