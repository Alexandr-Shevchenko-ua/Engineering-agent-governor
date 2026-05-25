"""Evidence bundle export for lead/MR review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from governor.models import RunState
from governor.policy import assess_policy_compliance, get_policy, resolve_policy_name
from governor.repair_artifacts import list_repair_artifacts
from governor.run_plan import (
    PLAN_JSON,
    load_plan,
    plan_json_path,
    plan_status_summary,
)
from governor.run_store import RunStore
from governor.trace import TraceLogger
from governor.utils import utc_now_iso
from governor.verdict import parse_validator_verdict

EVIDENCE_MD = "14_evidence_bundle.md"
EVIDENCE_JSON = "14_evidence_bundle.json"
CHECKPOINTS_MD = "13_human_checkpoints.md"

PROMPT_ARTIFACTS = (
    "03_executor_prompt.md",
    "04_validator_prompt.md",
)


def evidence_md_path(run_dir: Path) -> Path:
    return run_dir / EVIDENCE_MD


def evidence_json_path(run_dir: Path) -> Path:
    return run_dir / EVIDENCE_JSON


def checkpoints_path(run_dir: Path) -> Path:
    return run_dir / CHECKPOINTS_MD


def _read_optional(path: Path, max_chars: int = 2000) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (truncated)"
    return text


def _gate_summary_dict(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "08_gate_results.json"
    if not p.is_file():
        return {"overall": None, "note": "gates not run"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"overall": "unreadable"}


def _trace_summary(run_dir: Path, limit: int = 30) -> list[dict[str, Any]]:
    p = run_dir / "trace.jsonl"
    if not p.is_file():
        return []
    events = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events[-limit:]


def build_evidence_bundle(
    store: RunStore,
    run_id: str,
    *,
    include_prompts: bool = False,
) -> dict[str, Any]:
    run_dir, meta = store.get_run(run_id)
    gate = _gate_summary_dict(run_dir)
    validator_text = _read_optional(run_dir / "06_validator_output.md")
    verdict = parse_validator_verdict(validator_text)

    plan_summary: dict[str, Any] | None = None
    if plan_json_path(run_dir).is_file():
        try:
            plan = load_plan(run_dir)
            plan_summary = {
                "overall_status": plan.overall_status,
                "step_counts": plan_status_summary(plan),
                "executor_profile": plan.executor_profile,
                "validator_profile": plan.validator_profile,
            }
        except (ValueError, json.JSONDecodeError):
            plan_summary = {"error": "unreadable plan"}

    checkpoints: list[dict[str, str]] = []
    cp_path = checkpoints_path(run_dir)
    if cp_path.is_file():
        for block in cp_path.read_text(encoding="utf-8").split("\n## "):
            block = block.strip()
            if block:
                checkpoints.append({"raw_section": block[:500]})

    pol_name = resolve_policy_name(getattr(meta, "policy", None))
    policy_pack = get_policy(pol_name)
    compliance = assess_policy_compliance(
        run_dir,
        policy_pack,
        gate_overall=gate.get("overall") if isinstance(gate, dict) else None,
        validator_verdict=verdict,
    )

    bundle: dict[str, Any] = {
        "version": 1,
        "exported_at": utc_now_iso(),
        "run_id": meta.run_id,
        "task": meta.task,
        "repo_path": meta.repo_path,
        "state": meta.state,
        "outcome": meta.outcome,
        "repair_count": meta.repair_count,
        "repair_prompt_count": getattr(meta, "repair_prompt_count", 0),
        "repair_history": list_repair_artifacts(run_dir),
        "policy": pol_name,
        "policy_description": policy_pack.description,
        "policy_expectations": list(policy_pack.evidence_expectations),
        "policy_compliance": compliance,
        "plan": plan_summary,
        "commands_executed": list(meta.commands_executed),
        "gate": gate,
        "validator_verdict": verdict,
        "validator_summary": (validator_text or "")[:1500] if validator_text else None,
        "human_checkpoints_file": CHECKPOINTS_MD if cp_path.is_file() else None,
        "artifacts": store.list_artifacts(run_dir),
        "trace_recent": _trace_summary(run_dir),
        "safety_notes": [
            "Governor does not merge, push, or deploy.",
            "Prompt bodies excluded unless --include-prompts.",
            "Repair dispatch is never automatic in plan workflows.",
        ],
        "recommendation": _final_recommendation(meta, verdict, gate),
    }
    if include_prompts:
        bundle["prompts"] = {
            name: _read_optional(run_dir / name, 8000)
            for name in PROMPT_ARTIFACTS
            if (run_dir / name).is_file()
        }
    else:
        bundle["prompt_artifacts"] = [
            n for n in PROMPT_ARTIFACTS if (run_dir / n).is_file()
        ]
    return bundle


def _final_recommendation(meta, verdict: str | None, gate: dict[str, Any]) -> str:
    if meta.state == RunState.FINAL_REPORT_READY.value and meta.outcome == "PASS":
        return "Run completed with PASS; review evidence bundle before merge."
    if verdict == "HUMAN_DECISION_REQUIRED":
        return "Escalate to lead; do not merge without explicit decision."
    if gate.get("overall") == "FAIL":
        return "Fix gate failures; re-run gate after repair; do not merge."
    if meta.state == RunState.REPAIR_RECORDED.value:
        return "Re-run gate after repair before trusting closure."
    return "Review artifacts and complete validator/gate before merge."


def render_evidence_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        "# Evidence bundle",
        "",
        f"**Run ID:** `{bundle['run_id']}`",
        f"**Task:** {bundle['task']}",
        f"**State:** {bundle['state']}",
        f"**Outcome:** {bundle.get('outcome') or '(pending)'}",
        f"**Policy:** `{bundle.get('policy', 'default')}`",
        f"**Exported:** {bundle['exported_at']}",
        "",
        "## Policy compliance",
        "",
    ]
    pc = bundle.get("policy_compliance") or {}
    lines.append(f"- Overall: **{pc.get('overall', 'n/a')}**")
    for f in pc.get("findings") or []:
        lines.append(f"  - {f}")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            bundle["recommendation"],
            "",
            "## Gate summary",
            "",
        ]
    )
    gate = bundle.get("gate") or {}
    lines.append(f"- Overall: **{gate.get('overall', 'n/a')}**")
    if gate.get("results"):
        for r in gate["results"][:12]:
            lines.append(f"  - {r.get('name')}: {r.get('status')}")
    lines.extend(
        [
            "",
            "## Validator",
            "",
            f"**Verdict:** {bundle.get('validator_verdict') or 'not recorded'}",
            "",
        ]
    )
    if bundle.get("validator_summary"):
        lines.append(bundle["validator_summary"][:1200])
        lines.append("")
    if bundle.get("plan"):
        p = bundle["plan"]
        lines.extend(
            [
                "## Run plan",
                "",
                f"- Plan status: {p.get('overall_status')}",
                f"- Step counts: {p.get('step_counts')}",
                "",
            ]
        )
    lines.extend(["## Repair history", ""])
    rh = bundle.get("repair_history") or {}
    lines.append(f"- Prompts: {rh.get('prompts', [])}")
    lines.append(f"- Outputs: {rh.get('outputs', [])}")
    lines.extend(["", "## Commands executed", ""])
    for c in bundle.get("commands_executed", []):
        lines.append(f"- `{c}`")
    lines.extend(["", "## Artifacts", ""])
    for a in bundle.get("artifacts", []):
        lines.append(f"- `{a}`")
    lines.extend(["", "## Safety notes", ""])
    for n in bundle.get("safety_notes", []):
        lines.append(f"- {n}")
    if bundle.get("human_checkpoints_file"):
        lines.extend(
            [
                "",
                "## Human checkpoints",
                "",
                f"See `{bundle['human_checkpoints_file']}` in the run folder.",
            ]
        )
    lines.extend(["", "## Trace (recent)", ""])
    for e in bundle.get("trace_recent", [])[-10:]:
        lines.append(
            f"- {e.get('ts')} {e.get('action')} ({e.get('status')})"
        )
    return "\n".join(lines) + "\n"


def export_evidence(
    store: RunStore,
    run_id: str,
    *,
    include_prompts: bool = False,
    write_markdown: bool = True,
    write_json: bool = True,
) -> tuple[Path | None, Path | None]:
    run_dir, meta = store.get_run(run_id)
    bundle = build_evidence_bundle(store, run_id, include_prompts=include_prompts)
    md_p: Path | None = None
    json_p: Path | None = None
    if write_markdown:
        md_p = evidence_md_path(run_dir)
        md_p.write_text(render_evidence_markdown(bundle), encoding="utf-8")
    if write_json:
        json_p = evidence_json_path(run_dir)
        json_p.write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="evidence",
        actor="governor",
        action="evidence_export",
        output_ref=EVIDENCE_MD,
        status="ok",
        reason=f"prompts={'yes' if include_prompts else 'no'}",
    )
    store.append_command(
        run_id,
        f"python -m governor evidence export --run-id {run_id}",
    )
    return md_p, json_p
