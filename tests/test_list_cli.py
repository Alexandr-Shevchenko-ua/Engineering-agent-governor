"""List command CLI tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governor.cli import main


def test_list_json_output():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        assert main(["init", "--task", "List test", "--repo-path", str(repo)]) == 0
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["list", "--repo-path", str(repo), "--json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert len(data) >= 1
        assert "run_id" in data[0]
