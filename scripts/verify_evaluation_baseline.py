#!/usr/bin/env python3
"""Verify local evaluation baseline (index + optional annotations)."""

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


def _load_index_rows(index: Path) -> list[dict]:
    if not index.is_file():
        return []
    rows: list[dict] = []
    for line in index.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify evaluation baseline")
    parser.add_argument("--repo-path", default=".", help="Repository root")
    parser.add_argument(
        "--min-runs",
        type=int,
        default=1,
        help="Minimum evaluations in index (default: 1)",
    )
    parser.add_argument(
        "--require-annotations",
        action="store_true",
        help="Require annotations and manual fields on every indexed run",
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="Fail (exit 1) when baseline is missing; default is WARN and exit 0",
    )
    args = parser.parse_args()
    repo = Path(args.repo_path).resolve()
    runs_dir = repo / ".governor" / "runs"
    index = repo / ".governor" / "evaluations" / "evaluations.jsonl"

    if not index.is_file() and not runs_dir.is_dir():
        msg = "BASELINE WARN: no local .governor evaluations (skipped)"
        if args.require:
            print("BASELINE FAIL: no .governor/evaluations/evaluations.jsonl", file=sys.stderr)
            return 1
        print(msg)
        return 0

    rows = _load_index_rows(index)
    warnings: list[str] = []
    errors: list[str] = []

    if not rows:
        errors.append("evaluations.jsonl missing or empty")
    elif len(rows) < args.min_runs:
        warnings.append(f"only {len(rows)} evaluation(s), --min-runs={args.min_runs}")

    if args.require_annotations and rows:
        missing_annotate: list[str] = []
        for ev in rows:
            rid = ev.get("run_id", "?")
            if not ev.get("annotations"):
                missing_annotate.append(str(rid))
                continue
            for key in REQUIRED_MANUAL:
                if ev.get(key) is None:
                    missing_annotate.append(f"{rid} (missing {key})")
        if missing_annotate:
            errors.append(
                "missing annotations: "
                + ", ".join(missing_annotate[:5])
                + (f" (+{len(missing_annotate) - 5} more)" if len(missing_annotate) > 5 else "")
            )

    if runs_dir.is_dir() and index.is_file():
        run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
        ids_index = {r.get("run_id") for r in rows}
        if len(rows) != len(run_dirs):
            warnings.append(f"index lines {len(rows)} != run folders {len(run_dirs)}")
        for rd in run_dirs:
            if rd.name not in ids_index:
                warnings.append(f"run_id missing from index: {rd.name}")
            ev_path = rd / "17_run_evaluation.json"
            if not ev_path.is_file():
                warnings.append(f"missing 17_run_evaluation.json: {rd.name}")

    if errors:
        print("BASELINE FAIL", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if warnings:
        print("BASELINE WARN")
        for w in warnings:
            print(f"  - {w}")
        return 0

    print(f"BASELINE OK: {len(rows)} evaluation(s)")
    print(f"  index: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
