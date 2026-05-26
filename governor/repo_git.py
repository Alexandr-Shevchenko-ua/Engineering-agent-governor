"""Shared git ignore / tracked-path helpers for check and safety audit."""

from __future__ import annotations

import subprocess
from pathlib import Path

from governor.gates import is_git_worktree


def git_check_ignore(repo: Path, path: str) -> bool:
    if not is_git_worktree(repo):
        return False
    proc = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=repo,
        capture_output=True,
    )
    return proc.returncode == 0


def git_ls_files(repo: Path, path: str) -> list[str]:
    if not is_git_worktree(repo):
        return []
    proc = subprocess.run(
        ["git", "ls-files", path],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def git_tracked_under_governor(repo: Path) -> list[str]:
    return git_ls_files(repo, ".governor")
