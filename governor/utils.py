"""Small shared utilities."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_run_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def slugify(text: str, max_len: int = 48) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s_]+", "-", s).strip("-")
    if not s:
        s = "task"
    return s[:max_len].rstrip("-")


def resolve_repo_path(path: str | None) -> Path:
    return Path(path or ".").resolve()


def governor_root(repo_path: Path) -> Path:
    return repo_path / ".governor"


def runs_dir(repo_path: Path) -> Path:
    return governor_root(repo_path) / "runs"


def find_run_dir(repo_path: Path, run_id: str | None) -> Path:
    base = runs_dir(repo_path)
    if not base.exists():
        raise FileNotFoundError(f"No runs found under {base}")
    if run_id:
        run_dir = base / run_id
        if not run_dir.is_dir():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return run_dir
    dirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    if not dirs:
        raise FileNotFoundError(f"No runs found under {base}")
    return dirs[0]
