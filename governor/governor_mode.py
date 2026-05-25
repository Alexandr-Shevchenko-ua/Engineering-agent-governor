"""Experimental Chatbang Governor Mode — propose bounded runs; human approves apply."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from governor.chatbang_bridge import run_chatbang_once, run_chatbang_with_session_prime
from governor.config import config_path, load_profiles, redact_argv_for_display
from governor.policy import POLICY_NAMES, get_policy, list_policies
from governor.project_config import (
    PROJECT_CONFIG_FILENAME,
    load_project_config,
    resolve_policy_for_repo,
)
from governor.redaction import redact
from governor.run_plan import PLAN_JSON, create_plan
from governor.run_store import RunStore, init_store
from governor.trace import TraceLogger
from governor.utils import (
    proposals_dir,
    resolve_repo_path,
    slugify,
    utc_now_iso,
    utc_run_timestamp,
    validate_proposal_id,
)

PROPOSAL_JSON = "proposal.json"
PROPOSAL_MD = "proposal.md"
RAW_RESPONSE_MD = "raw_chatbang_response.md"
GOVERNOR_REQUEST_MD = "governor_request.md"
PROPOSAL_TRACE = "trace.jsonl"

# Session prime — one line to chatbang before the full propose prompt (clears advisor habit).
GOVERNOR_SESSION_PRIME = (
    "GOVERNOR_MODE: New proposal task. Ignore prior advisor/VERDICT chat. "
    "Acknowledge with exactly: GOVERNOR_MODE_OK"
)

PROPOSAL_STATUSES = frozenset({"PROPOSED", "APPLIED", "REJECTED", "EXPIRED"})
CONFIDENCE_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH"})
SAFETY_FLAG_UNSTRUCTURED = "UNSTRUCTURED_RESPONSE"
SAFETY_FLAG_ADVISOR_LEAK = "ADVISOR_MODE_LEAK"
SAFETY_FLAG_EXAMPLE_ECHO = "EXAMPLE_ECHO"
SAFETY_FLAG_META_SCHEMA = "CHATBANG_META_SCHEMA"
_PLACEHOLDER_TASK_MARKERS = ("<repeat task", "<repeat task from", "copy verbatim")

MAX_EXECUTOR_PROMPT = 12_000
MAX_VALIDATOR_PROMPT = 12_000
MAX_FIELD_LIST_ITEMS = 40
MAX_FIELD_ITEM_LEN = 500

_GOVERNOR_MODE_MARKER = "GOVERNOR_MODE_V12"

_GOVERNOR_SYSTEM = f"""{_GOVERNOR_MODE_MARKER} — Chatbang Governor (proposal author, NOT advisor).

You are in **Governor propose** mode. This is NOT `advisor ask`. Do NOT use VERDICT/ASK WHY/Done/Next/Need envelopes.
Do NOT ask the human to paste context — repository metadata is already below.

Your job: output ONE bounded run **proposal** for Engineering Agent Governor (human approves; Cursor executes later).

Hard rules:
- Do NOT write product code or edit files.
- Do NOT request git push/merge, deploy, production ops, secrets, or arbitrary shell.
- Do NOT invent test results or evidence.
- Scope minimal; docs-only tasks stay docs-only.
- `executor_prompt` and `validator_prompt` must be copy-paste ready for Governor run folders.

Output format (strict):
1) First: a single fenced ```json block with the proposal object (valid JSON).
2) Then: at most 8 lines of markdown rationale.

Required JSON keys (all required):
task, recommended_policy, assumptions (array), risk_register (array),
acceptance_criteria (array), executor_prompt (string), validator_prompt (string),
recommended_plan (array of {{step_id, action, description}}),
recommended_profiles (object with executor, validator profile names),
stop_conditions (array), required_human_decisions (array),
confidence (LOW|MEDIUM|HIGH)

Use profile names from context.runner_profile_names when possible (e.g. echo-test, fake-validator, cursor-headless-local).
Pick recommended_policy from context allowed policies.
"""

_GOVERNOR_JSON_EXAMPLE = """```json
{
  "task": "<repeat task from ## Task>",
  "recommended_policy": "docs",
  "assumptions": ["Docs-only", "No production deploy"],
  "risk_register": ["Scope creep beyond README"],
  "acceptance_criteria": ["Link present in README", "governor check passes"],
  "executor_prompt": "# Executor\\n\\nAdd one markdown cross-link...",
  "validator_prompt": "# Validator\\n\\nConfirm link and no code changes.",
  "recommended_plan": [
    {"step_id": "1", "action": "dispatch_executor", "description": "Docs edit"},
    {"step_id": "2", "action": "gate", "description": "fast profile"},
    {"step_id": "3", "action": "dispatch_validator", "description": "Review"}
  ],
  "recommended_profiles": {"executor": "cursor-headless-ask-local", "validator": "fake-validator"},
  "stop_conditions": ["Gate FAIL", "Human rejects"],
  "required_human_decisions": ["Approve apply", "Approve dispatch"],
  "confidence": "MEDIUM"
}
```"""

_DESTRUCTIVE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bgit\s+push\b",
        r"\bgit\s+merge\b",
        r"\bpush\s+to\s+(origin|main|master)\b",
        r"\bmerge\s+(to\s+)?(main|master)\b",
        r"\bdeploy(?:ment)?\s+to\s+production\b",
        r"\bdeploy\s+to\s+prod\b",
        r"\bkubectl\s+apply\b",
        r"\bterraform\s+apply\b",
        r"\bhelm\s+upgrade\b",
        r"\bcurl\b.*\bsecret\b",
        r"\baccess\s+(?:the\s+)?secrets?\b",
        r"\b\.env\b",
    )
]

_SHELL_FORBIDDEN = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bbash\s+-c\b",
        r"\bsh\s+-c\b",
        r"\bsudo\b",
        r"\brm\s+-rf\b",
        r"\bchmod\s+777\b",
        r"\bcurl\s+.*\|\s*bash\b",
    )
]

_GOVERNOR_CMD_OK = re.compile(
    r"(python\s+-m\s+governor\b|^\s*governor\s+\w+)",
    re.IGNORECASE | re.MULTILINE,
)

_SECRET_MARKERS = [
    re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b"),
    re.compile(r"\b(ghp_[a-zA-Z0-9]{36,})\b"),
    re.compile(r"\b(glpat-[a-zA-Z0-9\-_]{20,})\b"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
]


@dataclass
class GovernorProposalStep:
    step_id: str
    action: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v != ""}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GovernorProposalStep:
        return cls(
            step_id=str(data.get("step_id", "")),
            action=str(data.get("action", "")),
            description=str(data.get("description", "")),
        )


@dataclass
class GovernorDecision:
    check: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "status": self.status, "message": self.message}


@dataclass
class GovernorProposal:
    proposal_id: str
    created_at: str
    provider: str
    task: str
    repo_path: str
    recommended_policy: str
    assumptions: list[str] = field(default_factory=list)
    risk_register: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    executor_prompt: str = ""
    validator_prompt: str = ""
    recommended_plan: list[GovernorProposalStep] = field(default_factory=list)
    recommended_profiles: dict[str, str] = field(default_factory=dict)
    stop_conditions: list[str] = field(default_factory=list)
    required_human_decisions: list[str] = field(default_factory=list)
    confidence: str = "LOW"
    raw_advisor_response_ref: str = RAW_RESPONSE_MD
    status: str = "PROPOSED"
    safety_flags: list[str] = field(default_factory=list)
    applied_run_id: str | None = None
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "proposal_id": self.proposal_id,
            "created_at": self.created_at,
            "provider": self.provider,
            "task": self.task,
            "repo_path": self.repo_path,
            "recommended_policy": self.recommended_policy,
            "assumptions": self.assumptions,
            "risk_register": self.risk_register,
            "acceptance_criteria": self.acceptance_criteria,
            "executor_prompt": self.executor_prompt,
            "validator_prompt": self.validator_prompt,
            "recommended_plan": [s.to_dict() for s in self.recommended_plan],
            "recommended_profiles": self.recommended_profiles,
            "stop_conditions": self.stop_conditions,
            "required_human_decisions": self.required_human_decisions,
            "confidence": self.confidence,
            "raw_advisor_response_ref": self.raw_advisor_response_ref,
            "status": self.status,
            "safety_flags": self.safety_flags,
        }
        if self.applied_run_id:
            d["applied_run_id"] = self.applied_run_id
        if self.rejection_reason:
            d["rejection_reason"] = self.rejection_reason
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GovernorProposal:
        steps = [
            GovernorProposalStep.from_dict(s)
            for s in (data.get("recommended_plan") or [])
            if isinstance(s, dict)
        ]
        return cls(
            proposal_id=data["proposal_id"],
            created_at=data["created_at"],
            provider=data.get("provider", "chatbang"),
            task=data["task"],
            repo_path=data["repo_path"],
            recommended_policy=data.get("recommended_policy", "default"),
            assumptions=list(data.get("assumptions") or []),
            risk_register=list(data.get("risk_register") or []),
            acceptance_criteria=list(data.get("acceptance_criteria") or []),
            executor_prompt=str(data.get("executor_prompt") or ""),
            validator_prompt=str(data.get("validator_prompt") or ""),
            recommended_plan=steps,
            recommended_profiles=dict(data.get("recommended_profiles") or {}),
            stop_conditions=list(data.get("stop_conditions") or []),
            required_human_decisions=list(data.get("required_human_decisions") or []),
            confidence=str(data.get("confidence", "LOW")).upper(),
            raw_advisor_response_ref=data.get("raw_advisor_response_ref", RAW_RESPONSE_MD),
            status=data.get("status", "PROPOSED"),
            safety_flags=list(data.get("safety_flags") or []),
            applied_run_id=data.get("applied_run_id"),
            rejection_reason=data.get("rejection_reason"),
        )


@dataclass
class ProposeResult:
    proposal_id: str
    proposal_dir: Path
    dry_run: bool
    ok: bool
    error: str | None = None


@dataclass
class ValidateResult:
    proposal_id: str
    ok: bool
    decisions: list[GovernorDecision]
    warnings_only: bool = False


@dataclass
class ApplyResult:
    proposal_id: str
    run_id: str | None
    dry_run: bool
    approved: bool
    ok: bool
    error: str | None = None


def create_proposal_id(task: str) -> str:
    return f"{utc_run_timestamp()}_{slugify(task)}"


def proposal_dir(repo_path: Path, proposal_id: str) -> Path:
    validate_proposal_id(proposal_id)
    return proposals_dir(repo_path) / proposal_id


def _git_status_summary(repo: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode != 0:
            return "(not a git repo or git unavailable)"
        lines = (r.stdout or "").strip().splitlines()
        return "\n".join(lines[:30]) + ("\n... (truncated)" if len(lines) > 30 else "")
    except (OSError, subprocess.TimeoutExpired):
        return "(git status unavailable)"


def build_repo_context(
    repo_path: Path,
    *,
    include_repo_summary: bool = False,
    experimental_wide: bool = False,
) -> dict[str, Any]:
    repo = resolve_repo_path(str(repo_path))
    ctx: dict[str, Any] = {"repo_path": str(repo)}

    proj_path = repo / PROJECT_CONFIG_FILENAME
    if proj_path.is_file():
        try:
            cfg = load_project_config(repo)
            ctx["project"] = {
                "project_name": cfg.project_name,
                "default_policy": cfg.default_policy,
                "allowed_policies": cfg.allowed_policies,
                "default_gate_profile": cfg.default_gate_profile,
                "gate_profile_names": sorted(cfg.gate_profiles.keys()),
            }
        except Exception as e:
            ctx["project"] = f"(invalid project config: {e})"
    else:
        ctx["project"] = "(no governor.project.json)"

    ctx["builtin_policies"] = list(POLICY_NAMES)
    ctx["policy_catalog"] = [
        {"name": name, "description": get_policy(name).description[:120]}
        for name in list_policies()
    ]

    try:
        profiles = load_profiles(config_path(repo))
        ctx["runner_profile_names"] = sorted(profiles.keys())
        if experimental_wide:
            ctx["runner_profiles_redacted"] = {
                name: {
                    "enabled": spec.enabled,
                    "argv_display": redact_argv_for_display(spec.argv),
                }
                for name, spec in profiles.items()
            }
    except FileNotFoundError:
        ctx["runner_profile_names"] = "(no .governor/config.json)"

    ctx["git_status"] = _git_status_summary(repo)
    if include_repo_summary and experimental_wide:
        ctx["note"] = "wide context enabled — still no file contents"

    return ctx


def build_governor_prompt(
    task: str,
    context: dict[str, Any],
    *,
    policy_hint: str | None = None,
    extra_question: str | None = None,
) -> str:
    parts = [
        _GOVERNOR_SYSTEM,
        "\n## Example shape (fill with this task; do not copy verbatim)\n",
        _GOVERNOR_JSON_EXAMPLE,
        "\n",
        f"## Task\n{task.strip()}\n",
    ]
    if policy_hint:
        parts.append(f"Preferred policy hint: {policy_hint}\n")
    if extra_question:
        parts.append(f"Additional instruction: {extra_question.strip()}\n")
    parts.append("## Repository context (metadata only — already provided)\n")
    parts.append("```json\n")
    parts.append(json.dumps(context, indent=2, ensure_ascii=False)[:8000])
    parts.append(
        "\n```\n\n## Your response now\n"
        "Output the ```json proposal block first. No VERDICT envelope. No requests to paste context.\n"
    )
    return redact("".join(parts))


def build_chatbang_propose_message(
    task: str,
    context: dict[str, Any],
    *,
    policy_hint: str | None = None,
    extra_question: str | None = None,
) -> str:
    """Compact message for pexpect (avoids huge echo / example regurgitation)."""
    project = context.get("project")
    pol_list = context.get("builtin_policies", [])
    profiles = context.get("runner_profile_names", [])
    if isinstance(project, dict):
        proj_line = (
            f"project={project.get('project_name')}; default_policy="
            f"{project.get('default_policy')}; gates={project.get('gate_profile_names')}"
        )
    else:
        proj_line = str(project)[:200]
    lines = [
        f"{_GOVERNOR_MODE_MARKER} — output proposal JSON only (no VERDICT, no paste-context asks).",
        f"Task: {task.strip()}",
        f"Policy hint: {policy_hint or 'docs'}",
        f"Policies available: {', '.join(pol_list) if isinstance(pol_list, list) else pol_list}",
        f"Runner profiles: {', '.join(profiles) if isinstance(profiles, list) else profiles}",
        proj_line,
        "Required keys: task, recommended_policy, assumptions, risk_register, acceptance_criteria,",
        "executor_prompt, validator_prompt, recommended_plan, recommended_profiles,",
        "stop_conditions, required_human_decisions, confidence.",
        "Use executor cursor-headless-ask-local or echo-test for docs-only; validator fake-validator.",
    ]
    if extra_question:
        lines.append(f"Note: {extra_question.strip()}")
    lines.append("Respond with ```json block first, then max 5 lines rationale.")
    return redact("\n".join(lines))


def _clean_chatbang_output(text: str) -> str:
    text = re.sub(r"\[Thinking\.\.\.\]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\[REDACTED[^\]]*\]\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def _normalize_chatbang_alt_schema(
    data: dict[str, Any],
    *,
    task: str,
    policy: str,
) -> dict[str, Any] | None:
    """Map chatbang meta-schema JSON (governor_mode V12) into proposal fields."""
    if data.get("task") and not _is_placeholder_proposal(data):
        return data
    if "governor_mode" not in data and data.get("role") != "chatbang_governor":
        return None
    return {
        "task": task,
        "recommended_policy": policy,
        "assumptions": ["Docs-only unless task states otherwise", "Chatbang meta-schema normalized"],
        "risk_register": ["Scope drift", "Schema mismatch vs Governor proposal v1.2"],
        "acceptance_criteria": ["Human validates proposal.md", "governor check passes"],
        "executor_prompt": (
            f"# Executor\n\nTask: {task}\n\n"
            "Implement minimal scoped change. Record commands and diff summary.\n"
        ),
        "validator_prompt": (
            f"# Validator\n\nConfirm task complete with evidence: {task}\n"
        ),
        "recommended_plan": [
            {"step_id": "1", "action": "dispatch_executor", "description": "Execute"},
            {"step_id": "2", "action": "gate", "description": "Gates"},
            {"step_id": "3", "action": "dispatch_validator", "description": "Validate"},
        ],
        "recommended_profiles": {
            "executor": "cursor-headless-ask-local",
            "validator": "fake-validator",
        },
        "stop_conditions": ["Gate FAIL", "Human rejects"],
        "required_human_decisions": ["Approve apply", "Approve dispatch"],
        "confidence": "MEDIUM",
    }


def _try_parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("task"):
            return data
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    start = 0
    while start < len(raw):
        brace = raw.find("{", start)
        if brace < 0:
            break
        try:
            data, end = decoder.raw_decode(raw, brace)
            if isinstance(data, dict) and data.get("task"):
                return data
            start = end
        except json.JSONDecodeError:
            start = brace + 1
    return None


def looks_like_advisor_leak(text: str) -> bool:
    """True when chatbang answered like advisor ask instead of proposal JSON."""
    if parse_proposal_json_from_response(text, task="probe"):
        return False
    upper = text.upper()
    markers = (
        "VERDICT:",
        "ASK WHY",
        "PASTE THE TASK",
        "PASTE CONSTRAINTS",
        "PASTE THE LATEST",
        "NEED HANDOFF",
        "DONE/NEXT/NEED",
    )
    return any(m in upper for m in markers)


def extract_response_section(raw: str) -> str:
    """Prefer content after the prompt's 'Your response now' marker (avoids echoed example JSON)."""
    markers = ("## Your response now", "GOVERNOR_MODE_OK\n", "GOVERNOR_MODE_OK\r\n")
    best = raw
    for marker in markers:
        if marker in raw:
            tail = raw.split(marker)[-1].strip()
            if len(tail) > 40:
                best = tail
    return best


def _is_placeholder_proposal(data: dict[str, Any]) -> bool:
    task = str(data.get("task") or "").lower()
    if any(m in task for m in _PLACEHOLDER_TASK_MARKERS):
        return True
    ex = str(data.get("executor_prompt") or "")
    if ex.strip() == "# Executor\n\nAdd one markdown cross-link...":
        return True
    return False


def parse_proposal_json_from_response(
    text: str,
    *,
    task: str = "",
    policy: str = "default",
) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = _clean_chatbang_output(extract_response_section(text))
    blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    for block in reversed(blocks):
        parsed = _try_parse_json_object(block.strip())
        if parsed:
            if _is_placeholder_proposal(parsed):
                continue
            return parsed
            norm = _normalize_chatbang_alt_schema(parsed, task=task, policy=policy)
            if norm:
                return norm
    whole = _try_parse_json_object(cleaned)
    if whole:
        if not _is_placeholder_proposal(whole):
            return whole
        norm = _normalize_chatbang_alt_schema(whole, task=task, policy=policy)
        if norm:
            return norm
    if task and "GOVERNOR_MODE_V12" in cleaned and (
        "governor_mode" in cleaned or "chatbang_governor" in cleaned
    ):
        return _normalize_chatbang_alt_schema(
            {"governor_mode": "GOVERNOR_MODE_V12", "role": "chatbang_governor"},
            task=task,
            policy=policy,
        )
    return None


def _coerce_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [val.strip()] if val.strip() else []
    if isinstance(val, list):
        out = []
        for item in val:
            if item is not None:
                s = str(item).strip()
                if s:
                    out.append(s[:MAX_FIELD_ITEM_LEN])
        return out[:MAX_FIELD_LIST_ITEMS]
    return []


def proposal_from_parsed(
    parsed: dict[str, Any],
    *,
    proposal_id: str,
    task: str,
    repo_path: str,
    provider: str,
    safety_flags: list[str],
    confidence: str,
) -> GovernorProposal:
    steps_raw = parsed.get("recommended_plan") or []
    steps: list[GovernorProposalStep] = []
    if isinstance(steps_raw, list):
        for i, item in enumerate(steps_raw[:20]):
            if isinstance(item, dict):
                steps.append(GovernorProposalStep.from_dict(item))
            elif isinstance(item, str):
                steps.append(
                    GovernorProposalStep(
                        step_id=str(i + 1),
                        action="note",
                        description=item[:MAX_FIELD_ITEM_LEN],
                    )
                )

    profiles = parsed.get("recommended_profiles") or {}
    if not isinstance(profiles, dict):
        profiles = {}

    conf = str(parsed.get("confidence", confidence)).upper()
    if conf not in CONFIDENCE_LEVELS:
        conf = confidence

    pol = str(parsed.get("recommended_policy") or "default").strip() or "default"

    parsed_task = str(parsed.get("task") or task).strip()
    if any(m in parsed_task.lower() for m in _PLACEHOLDER_TASK_MARKERS):
        parsed_task = task

    return GovernorProposal(
        proposal_id=proposal_id,
        created_at=utc_now_iso(),
        provider=provider,
        task=parsed_task,
        repo_path=repo_path,
        recommended_policy=pol,
        assumptions=_coerce_str_list(parsed.get("assumptions")),
        risk_register=_coerce_str_list(parsed.get("risk_register")),
        acceptance_criteria=_coerce_str_list(parsed.get("acceptance_criteria")),
        executor_prompt=str(parsed.get("executor_prompt") or "")[:MAX_EXECUTOR_PROMPT],
        validator_prompt=str(parsed.get("validator_prompt") or "")[:MAX_VALIDATOR_PROMPT],
        recommended_plan=steps,
        recommended_profiles={str(k): str(v) for k, v in profiles.items()},
        stop_conditions=_coerce_str_list(parsed.get("stop_conditions")),
        required_human_decisions=_coerce_str_list(parsed.get("required_human_decisions")),
        confidence=conf,
        safety_flags=list(safety_flags),
    )


def _minimal_proposal(
    *,
    proposal_id: str,
    task: str,
    repo_path: str,
    provider: str,
    policy: str,
    safety_flags: list[str],
    raw_note: str,
) -> GovernorProposal:
    return GovernorProposal(
        proposal_id=proposal_id,
        created_at=utc_now_iso(),
        provider=provider,
        task=task,
        repo_path=repo_path,
        recommended_policy=policy,
        assumptions=["Proposal parsed from unstructured chatbang output; review carefully."],
        risk_register=["Unstructured advisor response — human must validate all fields."],
        acceptance_criteria=["Human reviews proposal.md and validates before apply."],
        executor_prompt=raw_note[:MAX_EXECUTOR_PROMPT] or f"Execute bounded task: {task}",
        validator_prompt=f"Validate completion of: {task}",
        recommended_plan=[
            GovernorProposalStep("1", "dispatch_executor", "Human-approved executor dispatch"),
            GovernorProposalStep("2", "gate", "Run deterministic gates"),
            GovernorProposalStep("3", "dispatch_validator", "Validator review"),
        ],
        recommended_profiles={"executor": "PLACEHOLDER", "validator": "PLACEHOLDER"},
        stop_conditions=["Stop if gates FAIL", "Stop if human rejects validator verdict"],
        required_human_decisions=["Approve proposal apply", "Approve executor dispatch"],
        confidence="LOW",
        safety_flags=safety_flags,
    )


def render_proposal_markdown(proposal: GovernorProposal) -> str:
    lines = [
        f"# Governor proposal `{proposal.proposal_id}`",
        "",
        f"- **Status:** {proposal.status}",
        f"- **Confidence:** {proposal.confidence}",
        f"- **Provider:** {proposal.provider}",
        f"- **Policy:** {proposal.recommended_policy}",
        f"- **Created:** {proposal.created_at}",
        "",
    ]
    if proposal.safety_flags:
        lines.append(f"- **Safety flags:** {', '.join(proposal.safety_flags)}")
        lines.append("")
    if proposal.applied_run_id:
        lines.append(f"- **Applied run:** `{proposal.applied_run_id}`")
        lines.append("")
    lines.extend(["## Task", "", proposal.task, ""])
    for title, items in (
        ("Assumptions", proposal.assumptions),
        ("Risk register", proposal.risk_register),
        ("Acceptance criteria", proposal.acceptance_criteria),
        ("Stop conditions", proposal.stop_conditions),
        ("Required human decisions", proposal.required_human_decisions),
    ):
        lines.append(f"## {title}")
        lines.append("")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    lines.extend(["## Executor prompt", "", proposal.executor_prompt, "", "## Validator prompt", "", proposal.validator_prompt, ""])
    if proposal.recommended_profiles:
        lines.append("## Recommended profiles")
        lines.append("")
        for k, v in proposal.recommended_profiles.items():
            lines.append(f"- **{k}:** `{v}`")
        lines.append("")
    if proposal.recommended_plan:
        lines.append("## Recommended plan")
        lines.append("")
        for step in proposal.recommended_plan:
            lines.append(f"- `{step.step_id}` **{step.action}**: {step.description}")
        lines.append("")
    return redact("\n".join(lines))


def save_proposal_artifacts(
    proposal_dir_path: Path,
    proposal: GovernorProposal,
    *,
    raw_response: str,
) -> None:
    proposal_dir_path.mkdir(parents=True, exist_ok=True)
    (proposal_dir_path / PROPOSAL_JSON).write_text(
        json.dumps(proposal.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (proposal_dir_path / PROPOSAL_MD).write_text(
        render_proposal_markdown(proposal),
        encoding="utf-8",
    )
    (proposal_dir_path / RAW_RESPONSE_MD).write_text(
        redact(raw_response),
        encoding="utf-8",
    )


def load_proposal(repo_path: Path, proposal_id: str) -> tuple[Path, GovernorProposal]:
    pid = validate_proposal_id(proposal_id)
    assert pid is not None
    pdir = proposal_dir(repo_path, pid)
    path = pdir / PROPOSAL_JSON
    if not path.is_file():
        raise FileNotFoundError(f"Proposal not found: {pid}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return pdir, GovernorProposal.from_dict(data)


def _proposal_trace(proposal_dir_path: Path, proposal_id: str) -> TraceLogger:
    return TraceLogger(proposal_dir_path, proposal_id, trace_filename=PROPOSAL_TRACE)


def propose_governor_mode(
    repo_path: Path,
    task: str,
    *,
    provider: str = "chatbang",
    policy_hint: str | None = None,
    extra_question: str | None = None,
    chatbang_command: str = "chatbang",
    timeout: int = 300,
    max_output_chars: int = 30_000,
    dry_run: bool = False,
    include_repo_summary: bool = False,
    experimental_wide: bool = False,
) -> ProposeResult:
    if provider != "chatbang":
        return ProposeResult("", Path(), dry_run, False, error=f"Unsupported provider: {provider}")

    repo = resolve_repo_path(str(repo_path))
    proposal_id = create_proposal_id(task)
    pdir = proposal_dir(repo, proposal_id)
    if pdir.exists():
        return ProposeResult(proposal_id, pdir, dry_run, False, error="Proposal directory already exists")

    policy_default = "default"
    try:
        policy_default = resolve_policy_for_repo(repo, policy_hint)
    except ValueError:
        policy_default = policy_hint or "default"

    context = build_repo_context(
        repo,
        include_repo_summary=include_repo_summary,
        experimental_wide=experimental_wide,
    )
    full_prompt = build_governor_prompt(
        task,
        context,
        policy_hint=policy_hint,
        extra_question=extra_question,
    )
    chatbang_message = build_chatbang_propose_message(
        task,
        context,
        policy_hint=policy_hint,
        extra_question=extra_question,
    )

    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / GOVERNOR_REQUEST_MD).write_text(full_prompt, encoding="utf-8")

    if dry_run:
        trace = _proposal_trace(pdir, proposal_id)
        trace.append(
            phase="governor_mode",
            actor="governor",
            action="propose_dry_run",
            output_ref=GOVERNOR_REQUEST_MD,
            reason="Dry-run: prompt saved; no chatbang call",
        )
        return ProposeResult(proposal_id, pdir, True, True)

    use_prime = "fake_chatbang" in chatbang_command or chatbang_command.strip() == "chatbang"
    if use_prime:
        result = run_chatbang_with_session_prime(
            chatbang_message,
            session_prime=GOVERNOR_SESSION_PRIME,
            command=chatbang_command,
            timeout=timeout,
            max_output_chars=max_output_chars,
        )
    else:
        result = run_chatbang_once(
            chatbang_message,
            command=chatbang_command,
            timeout=timeout,
            max_output_chars=max_output_chars,
        )
    raw = result.output if result.ok else (result.error or "")
    parsed = parse_proposal_json_from_response(
        raw, task=task, policy=policy_default
    )
    flags: list[str] = []
    confidence = "MEDIUM"
    if parsed is None:
        flags.append(SAFETY_FLAG_UNSTRUCTURED)
        if looks_like_advisor_leak(raw):
            flags.append(SAFETY_FLAG_ADVISOR_LEAK)
        confidence = "LOW"
        proposal = _minimal_proposal(
            proposal_id=proposal_id,
            task=task,
            repo_path=str(repo),
            provider=provider,
            policy=policy_default,
            safety_flags=flags,
            raw_note=raw[:2000],
        )
    else:
        if _is_placeholder_proposal(parsed):
            flags.append(SAFETY_FLAG_EXAMPLE_ECHO)
            confidence = "LOW"
        assumptions = parsed.get("assumptions") or []
        if (
            parsed.get("governor_mode")
            or parsed.get("role") == "chatbang_governor"
            or (
                "GOVERNOR_MODE_V12" in raw
                and any("meta-schema normalized" in str(a) for a in assumptions)
            )
        ):
            flags.append(SAFETY_FLAG_META_SCHEMA)
            if confidence == "MEDIUM":
                confidence = "LOW"
        proposal = proposal_from_parsed(
            parsed,
            proposal_id=proposal_id,
            task=task,
            repo_path=str(repo),
            provider=provider,
            safety_flags=flags,
            confidence=confidence,
        )
        if SAFETY_FLAG_EXAMPLE_ECHO in flags and not proposal.executor_prompt.strip().startswith("#"):
            proposal.executor_prompt = (
                f"# Executor\n\nBounded docs-only task: {task}\n\n"
                "Edit README.md only: add one bullet linking to docs/CHATBANG_GOVERNOR_MODE.md.\n"
            )
            proposal.validator_prompt = (
                f"# Validator\n\nConfirm README link exists; no code or config changes.\n"
            )

    save_proposal_artifacts(pdir, proposal, raw_response=raw)
    trace = _proposal_trace(pdir, proposal_id)
    trace.append(
        phase="governor_mode",
        actor="chatbang",
        action="propose",
        output_ref=RAW_RESPONSE_MD,
        reason=f"confidence={proposal.confidence} flags={proposal.safety_flags}",
    )
    return ProposeResult(proposal_id, pdir, False, True)


def _text_blob(proposal: GovernorProposal) -> str:
    parts = [
        proposal.task,
        proposal.executor_prompt,
        proposal.validator_prompt,
        json.dumps(proposal.to_dict(), ensure_ascii=False),
    ]
    return "\n".join(parts)


def validate_proposal(
    repo_path: Path,
    proposal_id: str,
    *,
    force_unstructured: bool = False,
) -> ValidateResult:
    repo = resolve_repo_path(str(repo_path))
    _, proposal = load_proposal(repo, proposal_id)
    decisions: list[GovernorDecision] = []
    failed = False

    def add(check: str, status: str, message: str) -> None:
        nonlocal failed
        decisions.append(GovernorDecision(check, status, message))
        if status == "FAIL":
            failed = True

    if proposal.status not in PROPOSAL_STATUSES:
        add("status", "FAIL", f"Invalid status: {proposal.status}")
    else:
        add("status", "PASS", f"Status is {proposal.status}")

    if SAFETY_FLAG_UNSTRUCTURED in proposal.safety_flags and not force_unstructured:
        add(
            "unstructured",
            "FAIL",
            "UNSTRUCTURED_RESPONSE — use --force-unstructured to apply",
        )
    elif SAFETY_FLAG_UNSTRUCTURED in proposal.safety_flags:
        add("unstructured", "WARN", "Unstructured response allowed via --force-unstructured")

    if SAFETY_FLAG_EXAMPLE_ECHO in proposal.safety_flags:
        add(
            "example_echo",
            "WARN",
            "Chatbang echoed example JSON — proposal fields were repaired from CLI task",
        )
    if SAFETY_FLAG_META_SCHEMA in proposal.safety_flags:
        add(
            "meta_schema",
            "WARN",
            "Chatbang returned meta-schema JSON — mapped to Governor proposal fields",
        )

    try:
        resolve_policy_for_repo(repo, proposal.recommended_policy)
        get_policy(proposal.recommended_policy)
        add("policy", "PASS", f"Policy {proposal.recommended_policy!r} is valid")
    except ValueError as e:
        add("policy", "FAIL", str(e))

    blob = "\n".join(
        [
            proposal.task,
            proposal.executor_prompt[:2000],
            proposal.validator_prompt[:2000],
            json.dumps(
                {
                    "assumptions": proposal.assumptions,
                    "risk_register": proposal.risk_register,
                    "acceptance_criteria": proposal.acceptance_criteria,
                    "stop_conditions": proposal.stop_conditions,
                },
                ensure_ascii=False,
            ),
        ]
    )
    for pat in _DESTRUCTIVE_PATTERNS:
        if pat.search(blob):
            add("destructive", "FAIL", f"Destructive pattern matched: {pat.pattern}")
            break
    else:
        add("destructive", "PASS", "No destructive deployment/merge/push patterns")

    for pat in _SHELL_FORBIDDEN:
        if pat.search(blob):
            add("shell", "FAIL", f"Forbidden shell pattern: {pat.pattern}")
            break
    else:
        add("shell", "PASS", "No forbidden shell patterns")

    for pat in _SECRET_MARKERS:
        if pat.search(blob):
            add("secrets", "FAIL", "Secret-like token detected in proposal text")
            break
    else:
        redacted = redact(blob)
        if redacted != blob:
            add("secrets", "WARN", "Content was redactable; review raw_chatbang_response.md")
        else:
            add("secrets", "PASS", "No obvious secret tokens")

    for field_name, val in (
        ("acceptance_criteria", proposal.acceptance_criteria),
        ("risk_register", proposal.risk_register),
        ("stop_conditions", proposal.stop_conditions),
    ):
        if not val:
            add(field_name, "FAIL", f"{field_name} must be non-empty")
        else:
            add(field_name, "PASS", f"{len(val)} item(s)")

    if not proposal.executor_prompt.strip():
        add("executor_prompt", "FAIL", "executor_prompt is empty")
    elif len(proposal.executor_prompt) > MAX_EXECUTOR_PROMPT:
        add("executor_prompt", "FAIL", "executor_prompt exceeds max length")
    else:
        add("executor_prompt", "PASS", "executor_prompt present")

    if not proposal.validator_prompt.strip():
        add("validator_prompt", "FAIL", "validator_prompt is empty")
    elif len(proposal.validator_prompt) > MAX_VALIDATOR_PROMPT:
        add("validator_prompt", "FAIL", "validator_prompt exceeds max length")
    else:
        add("validator_prompt", "PASS", "validator_prompt present")

    try:
        profiles = load_profiles(config_path(repo))
        for role, name in proposal.recommended_profiles.items():
            if not name or name.upper() in ("PLACEHOLDER", "TBD", "NONE"):
                add(f"profile_{role}", "WARN", f"Profile {role} is placeholder {name!r}")
            elif name not in profiles:
                add(f"profile_{role}", "WARN", f"Profile {name!r} not in local config")
            elif not profiles[name].enabled:
                add(f"profile_{role}", "WARN", f"Profile {name!r} exists but disabled")
            else:
                add(f"profile_{role}", "PASS", f"Profile {name!r} found")
    except FileNotFoundError:
        for role, name in proposal.recommended_profiles.items():
            if name and name.upper() not in ("PLACEHOLDER", "TBD"):
                add(f"profile_{role}", "WARN", "No .governor/config.json — cannot verify profile")

    warnings_only = not failed and any(d.status == "WARN" for d in decisions)
    return ValidateResult(
        proposal_id=proposal.proposal_id,
        ok=not failed,
        decisions=decisions,
        warnings_only=warnings_only,
    )


def list_proposals(repo_path: Path) -> list[dict[str, Any]]:
    base = proposals_dir(resolve_repo_path(str(repo_path)))
    if not base.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        pj = child / PROPOSAL_JSON
        if not pj.is_file():
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
            entries.append(
                {
                    "proposal_id": data.get("proposal_id", child.name),
                    "created_at": data.get("created_at", ""),
                    "status": data.get("status", "?"),
                    "task": (data.get("task") or "")[:80],
                    "confidence": data.get("confidence", "?"),
                }
            )
        except (OSError, json.JSONDecodeError):
            continue
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return entries


def reject_proposal(repo_path: Path, proposal_id: str, reason: str) -> GovernorProposal:
    pdir, proposal = load_proposal(resolve_repo_path(str(repo_path)), proposal_id)
    if proposal.status == "APPLIED":
        raise ValueError("Cannot reject an APPLIED proposal")
    proposal.status = "REJECTED"
    proposal.rejection_reason = reason.strip() or "(no reason given)"
    save_proposal_artifacts(pdir, proposal, raw_response=(pdir / RAW_RESPONSE_MD).read_text(encoding="utf-8"))
    trace = _proposal_trace(pdir, proposal.proposal_id)
    trace.append(
        phase="governor_mode",
        actor="human",
        action="reject",
        reason=proposal.rejection_reason,
    )
    return proposal


def _write_run_proposal_ref(run_dir: Path, proposal: GovernorProposal) -> None:
    ref = {
        "proposal_id": proposal.proposal_id,
        "created_at": proposal.created_at,
        "confidence": proposal.confidence,
        "safety_flags": proposal.safety_flags,
    }
    (run_dir / "00_governor_proposal_ref.json").write_text(
        json.dumps(ref, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    intake = run_dir / "00_task_intake.md"
    if intake.is_file():
        note = (
            f"\n\n---\n\n**Governor proposal ref:** `{proposal.proposal_id}` "
            f"(confidence {proposal.confidence})\n"
        )
        intake.write_text(intake.read_text(encoding="utf-8") + note, encoding="utf-8")


def apply_proposal(
    repo_path: Path,
    proposal_id: str,
    *,
    approve: bool = False,
    dry_run: bool = False,
    force_unstructured: bool = False,
    executor_profile: str | None = None,
    validator_profile: str | None = None,
    policy_override: str | None = None,
    with_evidence: bool = False,
    with_review_package: bool = False,
    continue_on_gate_warn: bool = False,
) -> ApplyResult:
    repo = resolve_repo_path(str(repo_path))
    pdir, proposal = load_proposal(repo, proposal_id)

    if proposal.status == "REJECTED":
        return ApplyResult(proposal_id, None, dry_run, approve, False, error="Proposal is REJECTED")
    if proposal.status == "APPLIED" and proposal.applied_run_id:
        return ApplyResult(
            proposal_id,
            proposal.applied_run_id,
            dry_run,
            approve,
            False,
            error=f"Already applied to run {proposal.applied_run_id}",
        )

    validation = validate_proposal(repo, proposal_id, force_unstructured=force_unstructured)

    pol = policy_override or proposal.recommended_policy
    exec_prof = executor_profile or proposal.recommended_profiles.get("executor")
    val_prof = validator_profile or proposal.recommended_profiles.get("validator")
    if exec_prof and exec_prof.upper() in ("PLACEHOLDER", "TBD"):
        exec_prof = None
    if val_prof and val_prof.upper() in ("PLACEHOLDER", "TBD"):
        val_prof = None

    preview = {
        "proposal_id": proposal_id,
        "task": proposal.task,
        "policy": pol,
        "executor_profile": exec_prof,
        "validator_profile": val_prof,
        "with_evidence": with_evidence,
        "with_review_package": with_review_package,
        "would_execute": False,
    }

    if not approve:
        for d in validation.decisions:
            print(f"[{d.status}] {d.check}: {d.message}")
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        if not validation.ok:
            print("\nValidation FAIL — resolve before apply (see governor validate).")
        else:
            print("\nRe-run with --approve to create run + plan (no execution in v1.2).")
        return ApplyResult(proposal_id, None, dry_run, False, True)

    if not validation.ok:
        return ApplyResult(
            proposal_id,
            None,
            dry_run,
            approve,
            False,
            error="Proposal validation failed",
        )

    if dry_run:
        print(json.dumps({**preview, "dry_run": True}, indent=2, ensure_ascii=False))
        return ApplyResult(proposal_id, None, True, True, True)

    store = init_store(str(repo))
    run_dir, meta = store.create_run(proposal.task, policy_name=pol)

    if proposal.executor_prompt.strip():
        (run_dir / "03_executor_prompt.md").write_text(
            redact(proposal.executor_prompt) + "\n",
            encoding="utf-8",
        )
    if proposal.validator_prompt.strip():
        (run_dir / "04_validator_prompt.md").write_text(
            redact(proposal.validator_prompt) + "\n",
            encoding="utf-8",
        )
    if proposal.risk_register:
        risks = "\n".join(f"- {r}" for r in proposal.risk_register)
        (run_dir / "02_risk_register.md").write_text(f"# Risk register\n\n{risks}\n", encoding="utf-8")

    _write_run_proposal_ref(run_dir, proposal)

    create_plan(
        store,
        meta.run_id,
        executor_profile=exec_prof,
        validator_profile=val_prof,
        policy_name=pol,
        dry_run=False,
    )

    proposal.status = "APPLIED"
    proposal.applied_run_id = meta.run_id
    raw = (pdir / RAW_RESPONSE_MD).read_text(encoding="utf-8") if (pdir / RAW_RESPONSE_MD).is_file() else ""
    save_proposal_artifacts(pdir, proposal, raw_response=raw)

    trace = _proposal_trace(pdir, proposal.proposal_id)
    trace.append(
        phase="governor_mode",
        actor="governor",
        action="apply",
        output_ref=meta.run_id,
        reason="Created run + plan; execution deferred to human",
    )

    run_trace = TraceLogger(run_dir, meta.run_id)
    run_trace.append(
        phase="governor_mode",
        actor="governor",
        action="applied_from_proposal",
        output_ref=proposal_id,
        reason=f"proposal apply (evidence={with_evidence}, review={with_review_package})",
    )

    if not (run_dir / PLAN_JSON).is_file():
        return ApplyResult(proposal_id, meta.run_id, False, True, False, error="Plan was not created")

    print(f"Applied proposal: {proposal_id}")
    print(f"Created run: {meta.run_id}")
    print(f"Run folder: {run_dir}")
    print("Plan created; no execution (v1.2). Next:")
    print(f"  python -m governor run resume --run-id {meta.run_id} --approve --repo-path .")

    return ApplyResult(proposal_id, meta.run_id, False, True, True)
