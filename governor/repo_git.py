"""Shared git helpers for check, safety audit, and collab commit snapshots."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
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


def git_worktree_root(repo: Path) -> Path:
    """Repository top-level (follows nested product dirs inside monorepos)."""
    rc, out, _ = _run_git(repo, ["rev-parse", "--show-toplevel"])
    if rc == 0 and out.strip():
        return Path(out.strip())
    return repo.resolve()


def _path_excluded(path: str, exclude_path_prefixes: tuple[str, ...]) -> bool:
    if not exclude_path_prefixes:
        return False
    normalized = path.replace("\\", "/")
    for prefix in exclude_path_prefixes:
        p = prefix.replace("\\", "/").lstrip("./")
        if normalized == p or normalized.startswith(p):
            return True
        if f"/{p}" in normalized or normalized.endswith(f"/{p.rstrip('/')}"):
            return True
    return False


def _run_git(repo: Path, args: list[str], *, timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


@dataclass
class GitSnapshot:
    is_repo: bool
    branch: str | None = None
    head: str | None = None
    short_status: str = ""
    diff_stat: str = ""
    diff_check_ok: bool = True
    diff_check_output: str = ""
    has_dirty: bool = False

    def to_dict(self) -> dict:
        return {
            "is_repo": self.is_repo,
            "branch": self.branch,
            "head": self.head,
            "short_status": self.short_status,
            "diff_stat": self.diff_stat,
            "diff_check_ok": self.diff_check_ok,
            "diff_check_output": self.diff_check_output,
            "has_dirty": self.has_dirty,
        }


@dataclass
class GitCommitResult:
    committed: bool
    commit_hash: str | None = None
    skipped_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "committed": self.committed,
            "commit_hash": self.commit_hash,
            "skipped_reason": self.skipped_reason,
            "error": self.error,
        }


def capture_git_snapshot(repo: Path, *, diff_stat_max_lines: int = 80) -> GitSnapshot:
    git_root = git_worktree_root(repo)
    if not is_git_worktree(git_root):
        return GitSnapshot(is_repo=False, short_status="(not a git repository)")

    rc_branch, branch_out, _ = _run_git(git_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    rc_head, head_out, _ = _run_git(git_root, ["rev-parse", "--short", "HEAD"])
    rc_status, status_out, _ = _run_git(git_root, ["status", "--short", "--branch"])
    rc_stat, stat_out, _ = _run_git(git_root, ["diff", "--stat"])
    rc_cached, cached_out, _ = _run_git(git_root, ["diff", "--cached", "--stat"])
    rc_check, check_out, check_err = _run_git(git_root, ["diff", "--check"])

    stat_parts = []
    if stat_out.strip():
        stat_parts.append(stat_out.strip())
    if cached_out.strip():
        stat_parts.append("staged:\n" + cached_out.strip())
    diff_stat = "\n".join(stat_parts) if stat_parts else "(no diff)"
    stat_lines = diff_stat.splitlines()
    if len(stat_lines) > diff_stat_max_lines:
        diff_stat = "\n".join(stat_lines[:diff_stat_max_lines]) + "\n... (truncated)"

    short_status = (status_out or "").strip() or "(clean)"
    has_dirty = bool(status_out.strip()) or bool(stat_out.strip()) or bool(cached_out.strip())

    return GitSnapshot(
        is_repo=True,
        branch=branch_out.strip() if rc_branch == 0 else None,
        head=head_out.strip() if rc_head == 0 else None,
        short_status=short_status[:4000],
        diff_stat=diff_stat[:8000],
        diff_check_ok=rc_check == 0,
        diff_check_output=(check_out + check_err).strip()[:2000],
        has_dirty=has_dirty,
    )


def _porcelain_paths(repo: Path) -> list[str]:
    rc, out, _ = _run_git(repo, ["status", "--porcelain"])
    if rc != 0:
        return []
    paths: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path_part = line[3:].strip().split(" -> ")[-1].strip()
        if path_part:
            paths.append(path_part)
    return paths


def commit_if_dirty(
    repo: Path,
    message: str,
    *,
    approve: bool,
    require_diff_check_clean: bool = True,
    exclude_path_prefixes: tuple[str, ...] = (),
) -> GitCommitResult:
    """Stage all changes and commit when the worktree is dirty (requires explicit approve)."""
    git_root = git_worktree_root(repo)
    snap = capture_git_snapshot(git_root)
    if not snap.is_repo:
        return GitCommitResult(False, skipped_reason="not a git repository")
    if not snap.has_dirty:
        return GitCommitResult(False, skipped_reason="worktree clean")
    if not approve:
        return GitCommitResult(False, skipped_reason="commit requires --approve-commit or --approve")
    if require_diff_check_clean and not snap.diff_check_ok:
        return GitCommitResult(
            False,
            error=f"git diff --check failed: {snap.diff_check_output[:500]}",
        )

    if exclude_path_prefixes:
        paths = _porcelain_paths(git_root)
        staged_any = False
        for path in paths:
            if _path_excluded(path, exclude_path_prefixes):
                continue
            rc_add, _, err_add = _run_git(git_root, ["add", "--", path])
            if rc_add != 0:
                return GitCommitResult(False, error=f"git add failed for {path}: {err_add}")
            staged_any = True
        if not staged_any:
            return GitCommitResult(False, skipped_reason="only excluded paths dirty")
    else:
        rc_add, _, err_add = _run_git(git_root, ["add", "-A"])
        if rc_add != 0:
            return GitCommitResult(False, error=f"git add failed: {err_add}")

    rc_commit, out_commit, err_commit = _run_git(
        git_root,
        ["commit", "-m", message],
        timeout=120,
    )
    if rc_commit != 0:
        combined = (out_commit + err_commit).strip()
        if "nothing to commit" in combined.lower():
            return GitCommitResult(False, skipped_reason="nothing to commit after git add")
        return GitCommitResult(False, error=combined[:1000])

    _, hash_out, _ = _run_git(repo, ["rev-parse", "--short", "HEAD"])
    return GitCommitResult(
        committed=True,
        commit_hash=hash_out.strip() or None,
    )


def push_current_branch(repo: Path, *, approve: bool, remote: str = "origin") -> GitCommitResult:
    if not approve:
        return GitCommitResult(False, skipped_reason="push requires --approve-push")
    if not is_git_worktree(repo):
        return GitCommitResult(False, skipped_reason="not a git repository")
    rc, out, err = _run_git(repo, ["push", remote, "HEAD"], timeout=300)
    if rc != 0:
        return GitCommitResult(False, error=(out + err).strip()[:1000])
    return GitCommitResult(committed=True, commit_hash="pushed")
