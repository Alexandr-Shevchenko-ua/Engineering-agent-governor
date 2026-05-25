"""Semantic Governor Advisor (chatbang) — does not change workflow state or execute code."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from governor.chatbang_bridge import run_chatbang_once
from governor.evidence import EVIDENCE_JSON, EVIDENCE_MD
from governor.models import RunState
from governor.repair_artifacts import list_repair_prompts
from governor.review_package import REVIEW_JSON, REVIEW_MD
from governor.run_plan import PLAN_JSON, load_plan, plan_status_summary
from governor.run_store import RunStore
from governor.trace import TraceLogger
from governor.utils import utc_now_iso
from governor.verdict import parse_validator_verdict

ADVISOR_REQUEST_PREFIX = "16_advisor_request_"
ADVISOR_RESPONSE_PREFIX = "16_advisor_response_"
FINAL_REPORT = "09_final_report.md"

ADVISOR_KINDS = frozenset(
    {
        "next-action",
        "risk-review",
        "plan-review",
        "evidence-review",
        "repair-advice",
    }
)

_KIND_DEFAULT_QUESTIONS: dict[str, str] = {
    "next-action": "What should the human do next in this governed run?",
    "risk-review": "Review risks and stop conditions for this run.",
    "plan-review": "Critique the run plan and step ordering.",
    "evidence-review": "Review whether evidence and closure artifacts are sufficient.",
    "repair-advice": "Advise on repair strategy without dispatching repair automatically.",
}

_ADVISOR_SYSTEM = """You are a semantic Governor Advisor for Engineering Agent Governor.
You are NOT an executor. Do not write product code. Do not ask to run destructive commands.
Do not invent evidence. Use only the run context provided below.

Return a concise markdown response with these sections:
## Verdict
## Recommended next action
## Risks
## Required human decision (if any)
## Exact next Governor command (if appropriate)
"""


@dataclass
class AdvisorAskResult:
    run_id: str
    kind: str
    index: int
    request_path: Path
    response_path: Path | None
    dry_run: bool
    ok: bool
    error: str | None = None


def advisor_request_name(index: int) -> str:
    return f"{ADVISOR_REQUEST_PREFIX}{index}.md"


def advisor_response_name(index: int) -> str:
    return f"{ADVISOR_RESPONSE_PREFIX}{index}.md"


def next_advisor_index(run_dir: Path) -> int:
    max_n = 0
    for p in run_dir.iterdir():
        if not p.is_file():
            continue
        m = re.match(rf"^{re.escape(ADVISOR_REQUEST_PREFIX)}(\d+)\.md$", p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _read_json_summary(path: Path, max_chars: int = 1500) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(data, indent=0, ensure_ascii=False)
        if len(text) > max_chars:
            return text[:max_chars] + " ... (truncated)"
        return text
    except (OSError, json.JSONDecodeError):
        return "(unreadable)"


def _list_artifacts(run_dir: Path) -> list[str]:
    return sorted(p.name for p in run_dir.iterdir() if p.is_file())


def _trace_last_events(run_dir: Path, limit: int = 10) -> list[dict[str, Any]]:
    p = run_dir / "trace.jsonl"
    if not p.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events[-limit:]


def build_advisor_context(
    store: RunStore,
    run_id: str,
    *,
    include_prompts: bool = False,
) -> dict[str, Any]:
    run_dir, meta = store.get_run(run_id)
    ctx: dict[str, Any] = {
        "run_id": meta.run_id,
        "task": meta.task,
        "policy": meta.policy,
        "state": meta.state,
        "outcome": meta.outcome,
        "repo_path": meta.repo_path,
        "repair_count": meta.repair_count,
        "artifacts": _list_artifacts(run_dir),
    }

    plan_path = run_dir / PLAN_JSON
    if plan_path.is_file():
        try:
            plan = load_plan(run_dir)
            ctx["plan"] = {
                "overall_status": plan.overall_status,
                "gate_profile": plan.gate_profile,
                "summary": plan_status_summary(plan),
                "steps": [
                    {
                        "step_id": s.step_id,
                        "action": s.action,
                        "status": s.status,
                        "reason": s.reason,
                    }
                    for s in plan.steps
                    if s.action != "stop"
                ],
            }
        except ValueError as e:
            ctx["plan"] = {"error": str(e)}

    gate_path = run_dir / "08_gate_results.json"
    if gate_path.is_file():
        ctx["gates"] = _read_json_summary(gate_path, 1200)

    val_path = run_dir / "06_validator_output.md"
    if val_path.is_file():
        text = val_path.read_text(encoding="utf-8")
        ctx["validator"] = {
            "present": True,
            "verdict": parse_validator_verdict(text),
            "excerpt": text[:800] + ("..." if len(text) > 800 else ""),
        }

    repairs = list_repair_prompts(run_dir)
    if repairs:
        ctx["repair_history"] = {
            "repair_prompt_count": len(repairs),
            "repair_prompt_indices": repairs,
        }

    ctx["evidence"] = {
        "markdown": (run_dir / EVIDENCE_MD).is_file(),
        "json": (run_dir / EVIDENCE_JSON).is_file(),
    }
    ctx["review_package"] = {
        "markdown": (run_dir / REVIEW_MD).is_file(),
        "json": (run_dir / REVIEW_JSON).is_file(),
    }
    ctx["trace_last_events"] = _trace_last_events(run_dir, 10)

    if include_prompts:
        for name in ("03_executor_prompt.md", "04_validator_prompt.md"):
            p = run_dir / name
            if p.is_file():
                ctx.setdefault("full_prompts", {})[name] = p.read_text(encoding="utf-8")[:4000]

    return ctx


def build_advisor_prompt(
    *,
    kind: str,
    question: str,
    context: dict[str, Any],
) -> str:
    ctx_json = json.dumps(context, indent=2, ensure_ascii=False)
    return (
        f"{_ADVISOR_SYSTEM}\n\n"
        f"**Advisor kind:** {kind}\n\n"
        f"**Human question:** {question}\n\n"
        f"## Run context (JSON)\n\n```json\n{ctx_json}\n```\n"
    )


def write_advisor_request(path: Path, *, kind: str, question: str, body: str) -> None:
    header = (
        f"# Advisor request — {kind}\n\n"
        f"**Created:** {utc_now_iso()}\n"
        f"**Question:** {question}\n\n"
        "---\n\n"
    )
    path.write_text(header + body, encoding="utf-8")


def write_advisor_response(
    path: Path,
    *,
    kind: str,
    result_status: str,
    output: str,
    duration_seconds: float,
    error: str | None = None,
) -> None:
    lines = [
        f"# Advisor response — {kind}",
        "",
        f"**Status:** {result_status}",
        f"**Duration:** {duration_seconds:.2f}s",
        "",
    ]
    if error:
        lines.extend(["## Error", "", error, ""])
    lines.extend(["## Response", "", output or "(empty)", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def ask_advisor(
    store: RunStore,
    run_id: str,
    *,
    provider: str,
    kind: str,
    question: str | None = None,
    command: str = "chatbang",
    timeout: int = 180,
    max_output_chars: int = 20000,
    dry_run: bool = False,
    include_prompts: bool = False,
    force: bool = False,
) -> AdvisorAskResult:
    if provider != "chatbang":
        raise ValueError(f"Unknown advisor provider {provider!r}; only 'chatbang' is supported")
    if kind not in ADVISOR_KINDS:
        raise ValueError(f"Unknown kind {kind!r}; expected one of: {sorted(ADVISOR_KINDS)}")

    timeout = min(max(30, timeout), 900)
    max_output_chars = min(max(1000, max_output_chars), 50000)

    run_dir, meta = store.get_run(run_id)
    if meta.state == RunState.FINAL_REPORT_READY.value and not force:
        raise ValueError(
            "Run already has final report; use --force to ask advisor anyway "
            "(advisor does not change workflow state)"
        )

    q = (question or "").strip() or _KIND_DEFAULT_QUESTIONS[kind]
    ctx = build_advisor_context(store, run_id, include_prompts=include_prompts)
    prompt_body = build_advisor_prompt(kind=kind, question=q, context=ctx)

    index = next_advisor_index(run_dir)
    req_name = advisor_request_name(index)
    resp_name = advisor_response_name(index)
    req_path = run_dir / req_name
    write_advisor_request(req_path, kind=kind, question=q, body=prompt_body)

    if dry_run:
        return AdvisorAskResult(
            run_id=run_id,
            kind=kind,
            index=index,
            request_path=req_path,
            response_path=None,
            dry_run=True,
            ok=True,
        )

    bridge_result = run_chatbang_once(
        prompt_body,
        command=command,
        timeout=timeout,
        max_output_chars=max_output_chars,
    )
    resp_path = run_dir / resp_name
    write_advisor_response(
        resp_path,
        kind=kind,
        result_status=bridge_result.status,
        output=bridge_result.output,
        duration_seconds=bridge_result.duration_seconds,
        error=bridge_result.error,
    )

    trace = TraceLogger(run_dir, meta.run_id)
    trace.append(
        phase="advisor",
        actor="governor",
        action=f"advisor_chatbang_{kind.replace('-', '_')}",
        status="ok" if bridge_result.ok else "fail",
        input_ref=req_name,
        output_ref=resp_name,
        reason=bridge_result.error,
    )

    _, meta_after = store.get_run(run_id)
    if meta_after.state != meta.state:
        raise RuntimeError("Advisor must not change workflow state")

    return AdvisorAskResult(
        run_id=run_id,
        kind=kind,
        index=index,
        request_path=req_path,
        response_path=resp_path,
        dry_run=False,
        ok=bridge_result.ok,
        error=bridge_result.error,
    )
