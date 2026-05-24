"""Doctor command tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from governor.cli import main
from governor.doctor import run_doctor


def test_doctor_does_not_create_dot_governor():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        assert not (repo / ".governor").exists()
        code = main(["doctor", "--repo-path", str(repo)])
        assert code == 0
        assert not (repo / ".governor").exists()


def test_doctor_fails_on_missing_repo():
    results, code = run_doctor("/nonexistent/path/xyz123")
    assert code == 1
    assert any(r.name == "repo_path" and r.status == "FAIL" for r in results)
