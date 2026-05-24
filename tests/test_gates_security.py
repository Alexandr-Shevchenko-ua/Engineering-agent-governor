"""Security gate tests — raw diff scanning vs redacted artifacts."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from governor.gates import (
    _security_scan,
    detect_secrets_in_diff,
    run_gates,
    write_gate_artifacts,
)
from governor.redaction import redact


def test_detect_secrets_in_raw_diff_not_redacted():
    raw = 'api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"'
    assert detect_secrets_in_diff(raw) is True
    assert detect_secrets_in_diff(redact(raw)) is False


def test_security_scan_warns_on_raw_token():
    _, warnings = _security_scan(Path("/tmp"), 'token = "ghp_abc123456789012345678901234567890"', [])
    assert any("secret/token" in w for w in warnings)


def test_gate_artifacts_do_not_leak_raw_secret():
    raw_diff = '+api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"\n'
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        with patch("governor.gates.is_git_worktree", return_value=True):
            with patch("governor.gates._run_cmd") as mock_run:

                def fake_cmd(cmd, cwd, timeout=120):
                    cmd_str = " ".join(cmd)
                    if "rev-parse" in cmd_str:
                        return 0, "true\n", ""
                    if cmd == ["git", "status", "--short"]:
                        return 0, "", ""
                    if cmd == ["git", "diff", "--stat"]:
                        return 0, " 1 file\n", ""
                    if cmd == ["git", "diff", "--check"]:
                        return 0, "", ""
                    if cmd == ["git", "diff", "--numstat"]:
                        return 0, "1\t0\tsecrets.py\n", ""
                    if cmd == ["git", "diff"]:
                        return 0, raw_diff, ""
                    return 0, "", ""

                mock_run.side_effect = fake_cmd
                report = run_gates(repo)

        assert report.security_warnings
        assert any(r.status == "WARN" for r in report.results if "security_heuristic" in r.name)

        with tempfile.TemporaryDirectory() as run_tmp:
            run_dir = Path(run_tmp)
            write_gate_artifacts(run_dir, report)
            blob = (run_dir / "08_gate_results.json").read_text()
            assert "sk-abcdefghijklmnopqrstuvwxyz" not in blob
