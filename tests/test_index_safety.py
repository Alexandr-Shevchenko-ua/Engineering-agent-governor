"""Index-backed find_run_dir safety."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governor.index import find_run_dir, index_path, save_index
from governor.run_store import RunStore


def test_status_resolves_latest_run():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Latest status")
        run_dir, loaded = store.get_run(None)
        assert loaded.run_id == meta.run_id
        assert run_dir.name == meta.run_id


def test_stale_index_escape_run_dir_falls_back_to_filesystem():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Safe fallback")
        data = {
            "version": 1,
            "runs": [
                {
                    "run_id": meta.run_id,
                    "task": meta.task,
                    "repo_path": str(repo),
                    "run_dir": "/etc/passwd",
                    "created_at": meta.created_at,
                    "updated_at": meta.updated_at,
                    "state": meta.state,
                    "outcome": None,
                }
            ],
        }
        save_index(repo, data)
        resolved = find_run_dir(repo, None)
        assert resolved == run_dir


def test_explicit_run_id_ignores_malicious_index_run_dir():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Explicit id")
        malicious = {
            "version": 1,
            "runs": [
                {
                    "run_id": "99999999T999999Z_evil",
                    "run_dir": str(repo / ".governor" / "runs" / meta.run_id),
                }
            ],
        }
        index_path(repo).write_text(json.dumps(malicious), encoding="utf-8")
        run_dir, _ = RunStore(repo).get_run(meta.run_id)
        assert run_dir.name == meta.run_id
