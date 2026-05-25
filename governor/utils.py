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


def require_governor_runs(repo_path: Path) -> Path:
    """Return runs directory or raise if governor was never initialized here."""
    base = runs_dir(repo_path)
    if not base.is_dir():
        root = governor_root(repo_path)
        raise FileNotFoundError(
            f"Governor runs not found at {base}. "
            f"Run 'python -m governor init --task \"...\" --repo-path {repo_path}' first."
        )
    return base


