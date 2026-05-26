"""Local .governor retention cleanup (runs/proposals only)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from governor.utils import governor_root, proposals_dir, resolve_repo_path, runs_dir


def _dir_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


_human_size = human_size  # backward compat for internal use


def _sorted_child_dirs(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    dirs = [p for p in base.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.name, reverse=True)
    return dirs


@dataclass
class CleanupStatus:
    runs_count: int
    runs_bytes: int
    proposals_count: int
    proposals_bytes: int
    governor_bytes: int

    def to_dict(self) -> dict:
        return {
            "runs_count": self.runs_count,
            "runs_bytes": self.runs_bytes,
            "proposals_count": self.proposals_count,
            "proposals_bytes": self.proposals_bytes,
            "governor_bytes": self.governor_bytes,
        }


def cleanup_status(repo_path: str | Path) -> CleanupStatus:
    repo = resolve_repo_path(str(repo_path))
    rdir = runs_dir(repo)
    pdir = proposals_dir(repo)
    run_dirs = _sorted_child_dirs(rdir)
    prop_dirs = _sorted_child_dirs(pdir)
    runs_bytes = sum(_dir_size(d) for d in run_dirs)
    prop_bytes = sum(_dir_size(d) for d in prop_dirs)
    gov_bytes = _dir_size(governor_root(repo))
    return CleanupStatus(
        runs_count=len(run_dirs),
        runs_bytes=runs_bytes,
        proposals_count=len(prop_dirs),
        proposals_bytes=prop_bytes,
        governor_bytes=gov_bytes,
    )


@dataclass
class CleanupActionResult:
    kind: str  # runs | proposals
    kept: list[str]
    removed: list[str]
    dry_run: bool
    bytes_freed: int

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "kept": self.kept,
            "removed": self.removed,
            "dry_run": self.dry_run,
            "bytes_freed": self.bytes_freed,
        }


def _prune_dirs(
    base: Path,
    *,
    keep_last: int,
    approve: bool,
) -> CleanupActionResult:
    kind = base.name
    dirs = _sorted_child_dirs(base)
    keep = dirs[:keep_last]
    drop = dirs[keep_last:]
    kept_ids = [d.name for d in keep]
    drop_ids = [d.name for d in drop]
    freed = sum(_dir_size(d) for d in drop)
    if approve:
        for d in drop:
            shutil.rmtree(d, ignore_errors=True)
    return CleanupActionResult(
        kind=kind,
        kept=kept_ids,
        removed=drop_ids,
        dry_run=not approve,
        bytes_freed=0 if not approve else freed,
    )


def cleanup_runs(
    repo_path: str | Path,
    *,
    keep_last: int = 20,
    approve: bool = False,
) -> CleanupActionResult:
    repo = resolve_repo_path(str(repo_path))
    keep_last = max(1, keep_last)
    return _prune_dirs(runs_dir(repo), keep_last=keep_last, approve=approve)


def cleanup_proposals(
    repo_path: str | Path,
    *,
    keep_last: int = 20,
    approve: bool = False,
) -> CleanupActionResult:
    repo = resolve_repo_path(str(repo_path))
    keep_last = max(1, keep_last)
    return _prune_dirs(proposals_dir(repo), keep_last=keep_last, approve=approve)
