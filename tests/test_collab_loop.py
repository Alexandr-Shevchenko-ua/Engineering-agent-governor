"""Tests for Chatbang↔Cursor collab loop (fake chatbang + echo executor)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "scripts" / "fake_chatbang.py"


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "collab@test.local"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Collab Test"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "README.md").write_text("# collab test\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".governor/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    return tmp_path


def _init_governor(repo: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "governor", "project", "init", "--repo-path", str(repo)],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "governor", "config", "init", "--repo-path", str(repo)],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    cfg_path = repo / ".governor" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    for name in ("echo-test", "fake-validator"):
        if name in cfg.get("profiles", {}):
            cfg["profiles"][name]["enabled"] = True
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def test_parse_collab_loose_json_next_prompt_only() -> None:
    from governor.collab_loop import parse_collab_response

    text = (
        'From chatbang:\n{"next_executor_prompt": "# Executor\\n\\nDo the thing in repo."}\n'
    )
    review = parse_collab_response(text)
    assert review is not None
    assert review.verdict == "CONTINUE"
    assert "Do the thing" in review.next_executor_prompt


def test_parse_collab_response_json() -> None:
    from governor.collab_loop import parse_collab_response

    text = (
        "Review done.\n\n```json\n"
        '{"verdict": "CONTINUE", "summary": "ok", '
        '"next_executor_prompt": "# Executor\\n\\nDo thing.", "stop_reason": null}\n'
        "```\n"
    )
    review = parse_collab_response(text)
    assert review is not None
    assert review.verdict == "CONTINUE"
    assert "Do thing" in review.next_executor_prompt


def test_collab_start_smoke(git_repo: Path) -> None:
    pytest.importorskip("pexpect")
    _init_governor(git_repo)
    fake_cmd = f"{sys.executable} {FAKE}"

    from governor.collab_loop import CollabStartOptions, load_session, run_collab_loop

    opts = CollabStartOptions(
        task="collab smoke task",
        repo_path=str(git_repo),
        max_rounds=3,
        executor_profile="echo-test",
        commit_policy="never",
        chatbang_command=fake_cmd,
        chatbang_timeout=60,
        approve=True,
        skip_preflight=True,
    )
    result = run_collab_loop(opts)
    assert result.session_dir.is_dir()
    _, session = load_session(git_repo, result.session_id)
    assert session.status == "COMPLETED"
    assert len(session.rounds) >= 1
    round_dir = result.session_dir / "round_01"
    assert (round_dir / "collab_review.json").is_file()
    assert (round_dir / "executor_prompt.md").is_file()


def test_collab_needs_approve(git_repo: Path) -> None:
    _init_governor(git_repo)
    from governor.collab_loop import CollabStartOptions, run_collab_loop

    result = run_collab_loop(
        CollabStartOptions(
            task="no approve",
            repo_path=str(git_repo),
            approve=False,
        )
    )
    assert result.status == "NEEDS_APPROVE"


def test_collab_autopilot_without_approve(git_repo: Path) -> None:
    pytest.importorskip("pexpect")
    _init_governor(git_repo)
    fake_cmd = f"{sys.executable} {FAKE}"
    from governor.collab_loop import CollabStartOptions, run_collab_loop

    result = run_collab_loop(
        CollabStartOptions(
            task="autopilot task",
            repo_path=str(git_repo),
            max_rounds=2,
            executor_profile="echo-test",
            commit_policy="never",
            chatbang_command=fake_cmd,
            chatbang_timeout=60,
            autopilot=True,
            skip_preflight=True,
        )
    )
    assert result.status == "COMPLETED"
    assert result.rounds_completed >= 1


def test_collab_human_only_seed(git_repo: Path) -> None:
    pytest.importorskip("pexpect")
    _init_governor(git_repo)
    seed_file = git_repo / "seed.txt"
    seed_file.write_text(
        "Не можемо з Cursor зробити voice assistant. Дай промпт для агента.\n",
        encoding="utf-8",
    )
    fake_cmd = f"{sys.executable} {FAKE}"
    from governor.collab_loop import CollabStartOptions, run_collab_loop

    result = run_collab_loop(
        CollabStartOptions(
            task="human only collab",
            repo_path=str(git_repo),
            max_rounds=1,
            executor_profile="echo-test",
            commit_policy="never",
            chatbang_command=fake_cmd,
            chatbang_timeout=60,
            chatbang_seed_file=str(seed_file),
            chatbang_human_only=True,
            autopilot=True,
            skip_preflight=True,
        )
    )
    assert result.status == "COMPLETED"
    req = (result.session_dir / "round_00" / "chatbang_request.md").read_text(encoding="utf-8")
    assert "CHATBANG_COLLAB_V1" not in req
    assert "voice assistant" in req
    assert (result.session_dir / "round_00" / "chatbang_request_governor.md").is_file()


def test_collab_seed_bootstrap_round(git_repo: Path) -> None:
    pytest.importorskip("pexpect")
    _init_governor(git_repo)
    seed_file = git_repo / "seed.txt"
    seed_file.write_text("Human starter: improve voice assistant quality.\n", encoding="utf-8")
    fake_cmd = f"{sys.executable} {FAKE}"
    from governor.collab_loop import CollabStartOptions, run_collab_loop

    result = run_collab_loop(
        CollabStartOptions(
            task="seeded collab",
            repo_path=str(git_repo),
            max_rounds=1,
            executor_profile="echo-test",
            commit_policy="never",
            chatbang_command=fake_cmd,
            chatbang_timeout=60,
            chatbang_seed_file=str(seed_file),
            approve=True,
            skip_preflight=True,
        )
    )
    assert result.status == "COMPLETED"
    bootstrap = result.session_dir / "round_00"
    assert bootstrap.is_dir()
    assert (bootstrap / "chatbang_seed.md").is_file()
    assert "voice assistant" in (bootstrap / "chatbang_seed.md").read_text(encoding="utf-8")


def test_git_commit_if_dirty(git_repo: Path) -> None:
    from governor.repo_git import commit_if_dirty

    (git_repo / "README.md").write_text("# changed\n", encoding="utf-8")
    r = commit_if_dirty(git_repo, "test commit", approve=True)
    assert r.committed
    assert r.commit_hash


def test_review_from_chatbang_no_freeform_fallback() -> None:
    from governor.collab_loop import review_from_chatbang_output

    body = "Long Chatbang reply without JSON. " * 12
    review = review_from_chatbang_output(
        body, task="human task", allow_freeform_fallback=False
    )
    assert review.verdict == "HOLD"
    assert review.stop_reason == "MISSING_COLLAB_JSON"
    assert not review.next_executor_prompt.strip()


def test_review_from_chatbang_markdown_executor_fallback() -> None:
    from governor.collab_loop import review_from_chatbang_output

    body = (
        "[Thinking...]\n\n"
        "FINAL EXECUTOR — Patch-or-Fail\n\n"
        "## Non-negotiable instruction\n"
        "You must patch files in the product repo.\n" + ("detail " * 120)
    )
    review = review_from_chatbang_output(
        body, task="voice assistant", allow_freeform_fallback=False
    )
    assert review.verdict == "CONTINUE"
    assert "Non-negotiable" in review.next_executor_prompt
    assert review.stop_reason is None


def test_commit_excludes_path_prefix(git_repo: Path) -> None:
    from governor.repo_git import commit_if_dirty

    art = git_repo / "collab_artifacts"
    art.mkdir()
    (art / "session.json").write_text("{}", encoding="utf-8")
    (git_repo / "README.md").write_text("# product change\n", encoding="utf-8")
    r = commit_if_dirty(
        git_repo,
        "collab snapshot",
        approve=True,
        exclude_path_prefixes=("collab_artifacts/",),
    )
    assert r.committed
    show = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    names = {ln.strip() for ln in show.stdout.splitlines() if ln.strip()}
    assert "README.md" in names
    assert not any(n.startswith("collab_artifacts/") for n in names)


def test_collab_session_records_cli_options(git_repo: Path) -> None:
    pytest.importorskip("pexpect")
    _init_governor(git_repo)
    fake_cmd = f"{sys.executable} {FAKE}"
    from governor.collab_loop import CollabStartOptions, load_session, run_collab_loop

    result = run_collab_loop(
        CollabStartOptions(
            task="opts snapshot",
            repo_path=str(git_repo),
            max_rounds=1,
            executor_profile="echo-test",
            commit_policy="never",
            chatbang_command=fake_cmd,
            chatbang_timeout=60,
            autopilot=True,
            chatbang_human_only=True,
            commit_exclude_dot_governor=True,
            skip_preflight=True,
        )
    )
    _, session = load_session(git_repo, result.session_id)
    assert session.cli_options is not None
    assert session.cli_options.get("commit_exclude_dot_governor") is True
