#!/usr/bin/env python3
"""Post-collab Governor quality scorecard — run after every collab session."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow `python scripts/eval_governor_collab_quality.py` from repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.eval_collab_session import eval_session  # noqa: E402


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _round_metrics(session_root: Path) -> list[dict]:
    rows: list[dict] = []
    for rdir in sorted(session_root.glob("round_*")):
        review = _load_json(rdir / "collab_review.json") or {}
        commit = _load_json(rdir / "git_commit.json") or {}
        gates = _load_json(rdir / "gate_results.json") or {}
        failed = rdir / ".." / "runs"
        run_id = None
        session = _load_json(session_root / "session.json") or {}
        for rec in session.get("rounds") or []:
            if rec.get("round_number") == int(rdir.name.split("_")[1]):
                run_id = rec.get("run_id")
                break
        run_failed = None
        if run_id:
            # product repo .governor/runs — optional
            pass
        rows.append(
            {
                "round": rdir.name,
                "chatbang_verdict": review.get("verdict"),
                "parse_error": review.get("parse_error"),
                "executor_prompt_chars": len(review.get("next_executor_prompt") or ""),
                "gate_overall": gates.get("overall"),
                "commit_committed": commit.get("committed"),
                "commit_error": commit.get("error") or commit.get("skipped_reason"),
            }
        )
    return rows


def build_quality_report(
    *,
    session_root: Path,
    verification_summary: Path | None,
) -> dict:
    session = _load_json(session_root / "session.json") or {}
    combined = eval_session(
        session_root=session_root,
        verification_summary=verification_summary,
    )

    rounds = session.get("rounds") or []
    executor_ok = sum(1 for r in rounds if (r.get("executor_exit_code") or 0) == 0)
    executor_fail = sum(
        1 for r in rounds if r.get("executor_exit_code") not in (None, 0)
    )
    markdown_fallback = 0
    for rdir in session_root.glob("round_*"):
        review = _load_json(rdir / "collab_review.json") or {}
        if review.get("parse_error") and review.get("verdict") == "CONTINUE":
            markdown_fallback += 1

    governor_score = 0
    notes: list[str] = []
    if session.get("chatbang_failures", 0) == 0:
        governor_score += 1
    else:
        notes.append(f"chatbang_failures={session.get('chatbang_failures')}")
    if executor_fail == 0 and rounds:
        governor_score += 1
    elif executor_ok > 0:
        governor_score += 1
        notes.append(f"partial executor success {executor_ok}/{len(rounds)}")
    if markdown_fallback > 0 and executor_ok > 0:
        governor_score += 1
        notes.append(f"markdown JSON fallback used in {markdown_fallback} round(s)")
    if combined["product"].get("ok"):
        governor_score += 1
    if session.get("status") == "COMPLETED" and combined["collab"].get("ok"):
        governor_score += 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "session_id": session.get("session_id"),
        "session_status": session.get("status"),
        "stop_reason": session.get("stop_reason"),
        "governor_quality_score": f"{governor_score}/5",
        "governor_notes": notes,
        "rounds_completed": len(rounds),
        "executor_ok": executor_ok,
        "executor_fail": executor_fail,
        "markdown_json_fallback_rounds": markdown_fallback,
        "round_artifacts": _round_metrics(session_root),
        "honest_eval": combined,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--verification-summary", type=Path, default=None)
    parser.add_argument(
        "--index",
        type=Path,
        default=None,
        help="Append JSONL (default: <session-root>/../collab_quality_index.jsonl)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    session_root = args.session_root.resolve()
    report = build_quality_report(
        session_root=session_root,
        verification_summary=args.verification_summary,
    )

    index_path = args.index or (session_root.parent / "collab_quality_index.jsonl")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False) + "\n")

    out_path = session_root / "governor_quality_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Governor quality: {report['governor_quality_score']}")
        print(f"Session: {report['session_id']} status={report['session_status']}")
        print(f"Product honest eval: {report['honest_eval']['overall']}")
        print(f"Rounds: {report['rounds_completed']} (executor ok={report['executor_ok']} fail={report['executor_fail']})")
        if report["governor_notes"]:
            print("Notes:", "; ".join(report["governor_notes"]))
        print(f"→ {report['honest_eval']['recommendation']}")
        print(f"Wrote {out_path}")
        print(f"Appended {index_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
