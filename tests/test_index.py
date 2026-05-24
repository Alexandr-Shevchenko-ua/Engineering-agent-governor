"""Tests for .governor/index.json maintenance."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governor.index import index_path, list_entries, load_index, rebuild_index
from governor.run_store import RunStore


def test_init_creates_index_entry():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Index task")
        assert index_path(repo).exists()
        data = load_index(repo)
        ids = [e["run_id"] for e in data["runs"]]
        assert meta.run_id in ids


def test_rebuild_index_from_run_states():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Rebuild me")
        index_path(repo).unlink()
        data = rebuild_index(repo)
        assert len(data["runs"]) == 1
        assert data["runs"][0]["run_id"] == meta.run_id


def test_list_entries_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        store.create_run("Older")
        store.create_run("Newer")
        entries = list_entries(repo)
        assert len(entries) >= 2
        assert entries[0]["run_id"] >= entries[1]["run_id"]
