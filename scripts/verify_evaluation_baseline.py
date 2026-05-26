#!/usr/bin/env python3
"""Verify local evaluation baseline is ready for Dashboard Lite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_MANUAL = (
    "mr_outcome",
    "manual_rework_minutes",
    "evidence_quality_score",
    "reviewer_burden_score",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify evaluation baseline")
    parser.add_argument("--repo-path", default=".", help="Repository root")
    args = parser.parse_args()
    repo = Path(args.repo_path).resolve()
    runs_dir = repo / ".governor" / "runs"
    index = repo / ".governor" / "evaluations" / "evaluations.jsonl"

    errors: list[str] = []
    if not runs_dir.is_dir():
        errors.append(f"Missing {runs_dir}")
        return 1

    run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    missing_eval: list[str] = []
    missing_annotate: list[str] = []

    for run_dir in run_dirs:
        rid = run_dir.name
        ev_path = run_dir / "17_run_evaluation.json"
        if not ev_path.is_file():
            missing_eval.append(rid)
            continue
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        if not ev.get("annotations"):
            missing_annotate.append(rid)
        for key in REQUIRED_MANUAL:
            if ev.get(key) is None:
                missing_annotate.append(f"{rid} (missing {key})")

    if not index.is_file():
        errors.append(f"Missing index {index}")
    else:
        lines = [ln for ln in index.read_text(encoding="utf-8").splitlines() if ln.strip()]
        ids_index = {json.loads(ln)["run_id"] for ln in lines}
        if len(lines) != len(run_dirs):
            errors.append(f"Index lines {len(lines)} != run folders {len(run_dirs)}")
        for rd in run_dirs:
            if rd.name not in ids_index:
                errors.append(f"run_id missing from index: {rd.name}")

    if missing_eval:
        errors.append(f"Missing 17_run_evaluation.json: {', '.join(missing_eval)}")
    if missing_annotate:
        errors.append(f"Missing annotations: {', '.join(missing_annotate[:5])}"
                       + (f" (+{len(missing_annotate)-5} more)" if len(missing_annotate) > 5 else ""))

    if errors:
        print("BASELINE NOT READY", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"BASELINE OK: {len(run_dirs)} runs, all evaluated and annotated")
    print(f"  index: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
