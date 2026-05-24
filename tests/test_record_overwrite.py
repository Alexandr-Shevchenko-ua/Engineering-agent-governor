"""Audit-trail protection for executor/validator record."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from governor.run_store import RunStore


def test_record_executor_twice_without_replace_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Overwrite test")
        store.record_output(meta.run_id, "executor", text="first")
        with pytest.raises(FileExistsError, match="05_executor_output"):
            store.record_output(meta.run_id, "executor", text="second")


def test_record_executor_with_replace_succeeds():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Replace test")
        store.record_output(meta.run_id, "executor", text="first")
        store.record_output(meta.run_id, "executor", text="second", replace=True)
        assert (run_dir / "05_executor_output.md").read_text() == "second"
