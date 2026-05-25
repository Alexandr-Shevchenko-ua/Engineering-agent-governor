#!/usr/bin/env python3
"""Score and compare Governor proposals (post-dogfood / post-compare).

Reads proposal.json paths or proposal IDs under .governor/proposals/.
Prints a human scorecard — no LLM, no network.

Example:
  python scripts/provider_proposal_scorecard.py \\
    --repo-path . \\
    --proposal chatbang-id --proposal cursor-id
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governor.governor_mode import validate_proposal
from governor.utils import proposals_dir, resolve_repo_path

CONFIDENCE_SCORE = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
BLOCKING_FLAGS = frozenset(
    {
        "PROVIDER_FAILED",
        "WRITE_CAPABLE_PROVIDER_BLOCKED",
        "UNSTRUCTURED_RESPONSE",
    }
)


def _load_proposal(repo: Path, ref: str) -> dict:
    path = Path(ref)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    pdir = proposals_dir(repo) / ref
    data_path = pdir / "proposal.json"
    if not data_path.is_file():
        raise FileNotFoundError(f"No proposal at {ref!r} ({data_path})")
    return json.loads(data_path.read_text(encoding="utf-8"))


def _score(data: dict, *, validate_ok: bool | None) -> dict:
    flags = set(data.get("safety_flags") or [])
    exec_len = len((data.get("executor_prompt") or "").strip())
    val_len = len((data.get("validator_prompt") or "").strip())
    plan_steps = len(data.get("recommended_plan") or [])
    conf = data.get("confidence", "LOW")
    structural = 0
    if exec_len >= 200:
        structural += 1
    if val_len >= 120:
        structural += 1
    if plan_steps >= 3:
        structural += 1
    if len(data.get("acceptance_criteria") or []) >= 2:
        structural += 1
    if validate_ok:
        structural += 2
    penalty = sum(2 for f in flags if f in BLOCKING_FLAGS) + len(flags) * 0.25
    total = CONFIDENCE_SCORE.get(str(conf).upper(), 1) + structural - penalty
    return {
        "provider": data.get("provider", "?"),
        "confidence": conf,
        "flags": sorted(flags),
        "exec_chars": exec_len,
        "validator_chars": val_len,
        "plan_steps": plan_steps,
        "validate_ok": validate_ok,
        "composite": round(max(0.0, total), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-path", default=".")
    parser.add_argument(
        "--proposal",
        action="append",
        dest="proposals",
        required=True,
        metavar="ID_OR_PATH",
        help="Proposal id under .governor/proposals/ or path to proposal.json",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()
    repo = resolve_repo_path(args.repo_path)

    rows: list[dict] = []
    for ref in args.proposals:
        data = _load_proposal(repo, ref)
        pid = data.get("proposal_id", ref)
        try:
            v = validate_proposal(repo, pid)
            validate_ok = v.ok
        except (ValueError, FileNotFoundError):
            validate_ok = None
        row = {"proposal_id": pid, **_score(data, validate_ok=validate_ok)}
        rows.append(row)

    rows.sort(key=lambda r: r["composite"], reverse=True)

    if args.json:
        print(json.dumps({"scorecard": rows}, indent=2, ensure_ascii=False))
        return 0

    print("# Governor proposal scorecard\n")
    for i, r in enumerate(rows):
        medal = " (recommended)" if i == 0 and len(rows) > 1 else ""
        print(f"## {r['proposal_id']}{medal}")
        print(f"- provider: **{r['provider']}**")
        print(f"- confidence: {r['confidence']}")
        print(f"- composite: **{r['composite']}**")
        print(f"- validate: {r['validate_ok']}")
        print(f"- flags: {', '.join(r['flags']) or '(none)'}")
        print(
            f"- prompts: executor {r['exec_chars']} chars, "
            f"validator {r['validator_chars']} chars, plan {r['plan_steps']} steps"
        )
        print()
    if len(rows) > 1:
        delta = rows[0]["composite"] - rows[-1]["composite"]
        print(f"Spread (top − bottom composite): {delta:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
