"""Tests for Governor Advisor (chatbang) artifacts and CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from governor.advisor import (
    ADVISOR_REQUEST_PREFIX,
    advisor_request_name,
    advisor_response_name,
    ask_advisor,
    build_advisor_context,
    build_advisor_prompt,
    next_advisor_index,
)
from governor.cli import main
from governor.run_store import init_store

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "scripts" / "fake_chatbang.py"


def _git_init(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
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


def test_advisor_artifact_names_increment(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / advisor_request_name(1)).write_text("a", encoding="utf-8")
    assert next_advisor_index(run_dir) == 2
    assert advisor_response_name(3) == "16_advisor_response_3.md"


def test_context_excludes_full_prompts_by_default(tmp_path: Path) -> None:
    pytest.importorskip("pexpect")
    _git_init(tmp_path)
    store = init_store(str(tmp_path))
    _, meta = store.create_run("ctx test", policy_name="default")
    run_dir, _ = store.get_run(meta.run_id)
    secret = "UNIQUE_EXECUTOR_SECRET_LINE_XYZ"
    (run_dir / "03_executor_prompt.md").write_text(secret, encoding="utf-8")

    ctx = build_advisor_context(store, meta.run_id, include_prompts=False)
    blob = json.dumps(ctx)
    assert secret not in blob
    assert "03_executor_prompt.md" in ctx["artifacts"]

    ctx2 = build_advisor_context(store, meta.run_id, include_prompts=True)
    assert secret in json.dumps(ctx2)


def test_dry_run_no_response(tmp_path: Path) -> None:
    _git_init(tmp_path)
    store = init_store(str(tmp_path))
    _, meta = store.create_run("dry", policy_name="default")
    result = ask_advisor(
        store,
        meta.run_id,
        provider="chatbang",
        kind="next-action",
        dry_run=True,
    )
    assert result.dry_run
    assert result.request_path.is_file()
    assert result.response_path is None
    assert not (result.request_path.parent / advisor_response_name(1)).exists()


def test_advisor_ask_fake_chatbang(tmp_path: Path) -> None:
    pytest.importorskip("pexpect")
    _git_init(tmp_path)
    store = init_store(str(tmp_path))
    _, meta = store.create_run("ask", policy_name="default")
    run_dir, meta_before = store.get_run(meta.run_id)
    state_before = meta_before.state

    cmd = f"{sys.executable} {FAKE}"
    result = ask_advisor(
        store,
        meta.run_id,
        provider="chatbang",
        kind="risk-review",
        command=cmd,
        timeout=30,
    )
    assert result.response_path and result.response_path.is_file()
    trace_lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "advisor_chatbang_risk_review" in trace_lines or "advisor_chatbang" in trace_lines

    _, meta_after = store.get_run(meta.run_id)
    assert meta_after.state == state_before


def test_cli_advisor_dry_run(tmp_path: Path, capsys) -> None:
    _git_init(tmp_path)
    rp = str(tmp_path)
    assert main(["init", "--task", "cli", "--repo-path", rp]) == 0
    out = capsys.readouterr().out
    run_id = [ln.split(":", 1)[1].strip() for ln in out.splitlines() if ln.startswith("Created run:")][0]
    assert (
        main(
            [
                "advisor",
                "ask",
                "--run-id",
                run_id,
                "--dry-run",
                "--repo-path",
                rp,
            ]
        )
        == 0
    )
    assert "Dry run" in capsys.readouterr().out


def test_prompt_builder_sections() -> None:
    body = build_advisor_prompt(
        kind="next-action",
        question="What next?",
        context={"run_id": "x", "state": "EXECUTOR_PROMPT_READY"},
    )
    assert "Governor Advisor" in body
    assert "Verdict" in body
    assert "What next?" in body


def test_docs_mention_advisor_not_executor() -> None:
    doc = (ROOT / "docs" / "CHATBANG_GOVERNOR_ADVISOR.md").read_text(encoding="utf-8")
    assert "not executor" in doc.lower() or "not an executor" in doc.lower()
    assert "advisor ask" in doc.lower() or "governor advisor ask" in doc.lower()


def test_example_config_cursor_headless_disabled() -> None:
    data = json.loads((ROOT / "examples" / "governor.config.example.json").read_text(encoding="utf-8"))
    prof = data["profiles"]["cursor-headless-local"]
    assert prof["enabled"] is False
    assert prof["argv"] == []
