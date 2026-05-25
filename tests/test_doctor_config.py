"""Doctor and dispatch config polish tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governor.cli import main
from governor.config import CONFIG_NOT_FOUND_MSG
from governor.dispatch import CURSOR_RUNNER_MESSAGE
from governor.doctor import run_doctor


def test_cursor_message_not_v02():
    assert "v0.2" not in CURSOR_RUNNER_MESSAGE
    assert "config.json" in CURSOR_RUNNER_MESSAGE


def test_doctor_warns_missing_config():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        results, code = run_doctor(str(repo))
        cfg = [r for r in results if r.name == "governor_config"][0]
        assert cfg.status == "WARN"
        assert "config init" in cfg.detail
        assert code == 0


def test_doctor_ok_valid_config():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["config", "init", "--repo-path", str(repo)])
        results, code = run_doctor(str(repo))
        cfg = [r for r in results if r.name == "governor_config"][0]
        assert cfg.status == "OK"
        assert "profile" in cfg.detail


def test_doctor_fail_invalid_config():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["config", "init", "--repo-path", str(repo)])
        path = repo / ".governor" / "config.json"
        data = json.loads(path.read_text())
        data["profiles"]["bad"] = {
            "runner": "command",
            "argv": [],
            "enabled": True,
            "timeout": 300,
        }
        path.write_text(json.dumps(data))
        results, code = run_doctor(str(repo))
        cfg = [r for r in results if r.name == "governor_config"][0]
        assert cfg.status == "FAIL"
        assert code == 1


def test_dispatch_profile_missing_config_hint(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store_path = repo / ".governor" / "runs"
        store_path.mkdir(parents=True)
        main(["init", "--task", "Cfg miss", "--repo-path", str(repo)])
        from governor.run_store import RunStore

        _, meta = RunStore(repo).get_run(None)
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "executor",
                "--profile",
                "echo-test",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert CONFIG_NOT_FOUND_MSG in err
