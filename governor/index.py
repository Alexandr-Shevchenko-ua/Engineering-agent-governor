"""`.governor/index.json` run index — local discovery without scanning all artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from governor.models import RunMetadata
from governor.utils import governor_root, runs_dir, validate_run_id

INDEX_VERSION = 1
INDEX_FILENAME = "index.json"


def index_path(repo_path: Path) -> Path:
    return governor_root(repo_path) / INDEX_FILENAME


def _empty_index() -> dict[str, Any]:
    return {"version": INDEX_VERSION, "runs": []}


def load_index(repo_path: Path) -> dict[str, Any]:
    path = index_path(repo_path)
    if not path.exists():
        return rebuild_index(repo_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Corrupted governor index at {path}: {e}") from e
    if "runs" not in data:
        data["runs"] = []
    data.setdefault("version", INDEX_VERSION)
    return data


def save_index(repo_path: Path, data: dict[str, Any]) -> None:
    path = index_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = INDEX_VERSION
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def entry_from_metadata(meta: RunMetadata, run_dir: Path) -> dict[str, Any]:
    return {
        "run_id": meta.run_id,
        "task": meta.task,
        "repo_path": meta.repo_path,
        "run_dir": str(run_dir.resolve()),
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
        "state": meta.state,
        "outcome": meta.outcome,
    }


def upsert_entry(repo_path: Path, meta: RunMetadata, run_dir: Path) -> None:
    data = load_index(repo_path) if index_path(repo_path).exists() else _empty_index()
    entry = entry_from_metadata(meta, run_dir)
    runs: list[dict[str, Any]] = data["runs"]
    for i, existing in enumerate(runs):
        if existing.get("run_id") == meta.run_id:
            runs[i] = entry
            break
    else:
        runs.append(entry)
    save_index(repo_path, data)


def rebuild_index(repo_path: Path) -> dict[str, Any]:
    """Rebuild index from run_state.json files (does not create .governor)."""
    data = _empty_index()
    base = runs_dir(repo_path)
    if not base.is_dir():
        return data
    entries: list[dict[str, Any]] = []
    for run_dir in sorted(base.iterdir()):
        if not run_dir.is_dir():
            continue
        state_file = run_dir / "run_state.json"
        if not state_file.exists():
            continue
        try:
            meta = RunMetadata.from_dict(json.loads(state_file.read_text(encoding="utf-8")))
            entries.append(entry_from_metadata(meta, run_dir))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    entries.sort(key=lambda e: e.get("run_id", ""), reverse=True)
    data["runs"] = entries
    if entries:
        save_index(repo_path, data)
    return data


def list_entries(
    repo_path: Path,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    data = load_index(repo_path)
    runs = sorted(data.get("runs", []), key=lambda e: e.get("run_id", ""), reverse=True)
    if limit is not None:
        runs = runs[:limit]
    return runs


def _run_dir_within_base(base: Path, candidate: Path) -> Path | None:
    """Return resolved path if candidate is a directory under base, else None."""
    try:
        resolved = candidate.resolve()
        base_resolved = base.resolve()
        resolved.relative_to(base_resolved)
    except (ValueError, OSError):
        return None
    if not resolved.is_dir():
        return None
    return resolved


def find_run_dir(repo_path: Path, run_id: str | None) -> Path:
    """Resolve a run folder by id, or the newest indexed run when run_id is omitted."""
    base = runs_dir(repo_path)
    if not base.is_dir():
        raise FileNotFoundError(
            f"Governor runs not found at {base}. "
            f"Run 'python -m governor init --task \"...\" --repo-path {repo_path}' first."
        )

    if run_id is not None:
        validated = validate_run_id(run_id)
        assert validated is not None
        run_dir = base / validated
        if not run_dir.is_dir():
            raise FileNotFoundError(f"Run not found: {validated}")
        return run_dir

    for entry in list_entries(repo_path, limit=1):
        indexed_id = entry.get("run_id")
        if indexed_id:
            try:
                validated = validate_run_id(indexed_id)
            except ValueError:
                continue
            run_dir = base / validated
            if run_dir.is_dir():
                return run_dir
        raw_dir = entry.get("run_dir")
        if raw_dir:
            safe = _run_dir_within_base(base, Path(raw_dir))
            if safe is not None:
                return safe

    dirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    if not dirs:
        raise FileNotFoundError(f"No runs found under {base}")
    return dirs[0]
