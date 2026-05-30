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


def flatten_for_chatbang_line(text: str, *, max_chars: int = 12_000) -> str:
    """One physical line for chatbang UIs that submit on Enter (avoid multi-message seed)."""
    line = text.replace("\r\n", "\n").replace("\n", " ⏎ ").strip()
    if len(line) > max_chars:
        line = line[: max_chars - 24] + " …(truncated for chatbang UI)"
    return line


def read_text_robust(path: Path) -> str:
    """Read text file with UTF-8 (BOM) and common fallbacks for Ukrainian/Windows saves."""
    raw = path.read_bytes()
    if not raw:
        return ""
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def governor_root(repo_path: Path) -> Path:
    return repo_path / ".governor"


def runs_dir(repo_path: Path) -> Path:
    return governor_root(repo_path) / "runs"


def proposals_dir(repo_path: Path) -> Path:
    return governor_root(repo_path) / "proposals"


def collab_dir(repo_path: Path) -> Path:
    return governor_root(repo_path) / "collab"


def validate_collab_session_id(session_id: str | None) -> str | None:
    """Collab sessions use the same id shape as run/proposal folders."""
    return validate_run_id(session_id)


def validate_proposal_id(proposal_id: str | None) -> str | None:
    """Same rules as run_id — proposals live under .governor/proposals/."""
    return validate_run_id(proposal_id)


def require_governor_runs(repo_path: Path) -> Path:
    """Return runs directory or raise if governor was never initialized here."""
    base = runs_dir(repo_path)
    if not base.is_dir():
        raise FileNotFoundError(
            f"Governor runs not found at {base}. "
            f"Run 'python -m governor init --task \"...\" --repo-path {repo_path}' first."
        )
    return base


RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z_[a-z0-9_-]+$")

_INVALID_RUN_ID_MSG = "Invalid run id: expected run folder name, not a path"


def validate_run_id(run_id: str | None) -> str | None:
    """
    Validate a user-supplied run id (folder name under .governor/runs/).
    None is allowed for latest-run resolution.
    """
    if run_id is None:
        return None
    if not isinstance(run_id, str):
        raise ValueError(_INVALID_RUN_ID_MSG)
    s = run_id.strip()
    if not s or s != run_id:
        raise ValueError(_INVALID_RUN_ID_MSG)
    if "/" in s or "\\" in s or ".." in s:
        raise ValueError(_INVALID_RUN_ID_MSG)
    if Path(s).is_absolute():
        raise ValueError(_INVALID_RUN_ID_MSG)
    if s.startswith(".governor") or s.startswith("runs"):
        raise ValueError(_INVALID_RUN_ID_MSG)
    if not RUN_ID_PATTERN.match(s):
        raise ValueError(
            f"Invalid run id: {s!r} (expected format YYYYMMDDTHHMMSSZ_slug)"
        )
    return s