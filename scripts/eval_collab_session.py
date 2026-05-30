#!/usr/bin/env python3
"""Evaluate collab session + product verification_summary for honest PASS/FAIL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _last_round_review(session_root: Path) -> dict | None:
    rounds = sorted(session_root.glob("round_*"), reverse=True)
    for rdir in rounds:
        review_path = rdir / "collab_review.json"
        if review_path.is_file():
            return json.loads(review_path.read_text(encoding="utf-8"))
    return None


def eval_session(
    *,
    session_root: Path,
    verification_summary: Path | None,
) -> dict:
    session = _load_json(session_root / "session.json") or {}
    review = _last_round_review(session_root)
    verdict = (review or {}).get("verdict")
    stop = session.get("stop_reason")
    status = session.get("status")

    product: dict = {}
    if verification_summary and verification_summary.is_file():
        vs = _load_json(verification_summary) or {}
        qg = vs.get("quality_gate", {})
        product = {
            "verification_gate": vs.get("verification_gate"),
            "all_release_checks_passed": (vs.get("acceptance") or {}).get(
                "all_release_checks_passed"
            ),
            "quality_gate_status": qg.get("status"),
            "roles": qg.get("roles", {}),
            "live_integration_allowed": vs.get("live_integration_allowed"),
        }

    google_judge = (product.get("roles") or {}).get("google_senior_ai", {})
    judge_verdict = google_judge.get("judge_verdict")
    near_offer = bool(google_judge.get("near_offer"))
    judge_ok = judge_verdict == "offer"

    collab_ok = verdict == "PASS" and status == "COMPLETED"
    product_ok = (
        product.get("all_release_checks_passed") is True
        and product.get("quality_gate_status") == "PASS"
        and judge_ok
    )
    overall = "PASS" if collab_ok and product_ok else "FAIL"

    return {
        "overall": overall,
        "collab": {
            "session_id": session.get("session_id"),
            "status": status,
            "stop_reason": stop,
            "last_verdict": verdict,
            "chatbang_failures": session.get("chatbang_failures", 0),
            "cli_options": session.get("cli_options"),
            "ok": collab_ok,
        },
        "product": {
            **product,
            "ok": product_ok,
            "google_judge_ok": judge_ok,
            "google_judge_verdict": judge_verdict,
            "google_near_offer": near_offer,
        },
        "recommendation": _recommendation(
            collab_ok, product_ok, verdict, product, judge_ok, judge_verdict
        ),
    }


def _recommendation(
    collab_ok: bool,
    product_ok: bool,
    verdict: str | None,
    product: dict,
    judge_ok: bool,
    judge_verdict: str | None,
) -> str:
    if collab_ok and product_ok:
        return "Full success: collab PASS + release gate + judge offer. Live mic still separate."
    parts: list[str] = []
    if not collab_ok:
        parts.append(
            f"Collab not done: need Chatbang verdict PASS (got {verdict!r}, status matters)."
        )
    if not product_ok:
        if product.get("quality_gate_status") != "PASS":
            parts.append("Product quality_gate not PASS — run verify_linux.sh.")
        elif not judge_ok:
            parts.append(
                f"Google judge not acceptable: verdict={judge_verdict!r} "
                f"(need offer or another_round+near_offer)."
            )
        roles = product.get("roles") or {}
        for role, info in roles.items():
            if info.get("status") != "PASS":
                parts.append(
                    f"Role {role} quality FAIL: judge={info.get('judge_verdict')} "
                    f"near_offer={info.get('near_offer')}"
                )
    return " ".join(parts) or "Re-run verify_linux.sh and collab with v1.8 governor."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument(
        "--verification-summary",
        type=Path,
        default=None,
        help="Path to offer_engine/reports/latest/verification_summary.json",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = eval_session(
        session_root=args.session_root.resolve(),
        verification_summary=args.verification_summary,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Overall: {result['overall']}")
        print(f"Collab:  {result['collab']}")
        print(f"Product: {result['product']}")
        print(f"→ {result['recommendation']}")
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
