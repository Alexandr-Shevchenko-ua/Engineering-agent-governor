"""Experimental Chatbang ↔ Cursor collab loop (seed bootstrap, optional autopilot, post-audit)."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from governor.chatbang_bridge import (
    ChatbangPersistentSession,
    ChatbangResult,
    is_chatbang_available,
    probe_chatbang,
)
from governor.config import config_path, get_profile, load_profiles
from governor.dispatch import execute_dispatch
from governor.gates import run_gates, write_gate_artifacts
from governor.models import RunState
from governor.project_config import resolve_gate_profile_for_repo, resolve_policy_for_repo
from governor.redaction import redact
from governor.repo_git import GitCommitResult, capture_git_snapshot, commit_if_dirty, push_current_branch
from governor.run_store import RunStore, init_store
from governor.trace import TraceLogger
from governor.utils import (
    collab_dir,
    read_text_robust,
    resolve_repo_path,
    slugify,
    utc_now_iso,
    utc_run_timestamp,
)

COLLAB_MARKER = "CHATBANG_COLLAB_V1"
COLLAB_SESSION_PRIME = (
    "Collab session starting. Acknowledge with exactly: CHATBANG_COLLAB_OK"
)
SESSION_JSON = "session.json"
COLLAB_TRACE = "trace.jsonl"
VERDICTS = frozenset({"CONTINUE", "PASS", "HOLD", "FAIL"})
CommitPolicy = Literal["never", "if_dirty", "if_gates_pass"]
MAX_EXECUTOR_PROMPT = 48_000
BOOTSTRAP_ROUND = 0
AUDIT_DIR = "audit"
MAX_CHATBANG_TO_CURSOR_PROMPT = 64_000
CURSOR_EXECUTOR_PREAMBLE = """# Collab executor rules (Governor)

- Work in the **product repo** only; do not edit `.governor/` run artifacts unless explicitly required.
- Do **not** run `pytest` in background or spawn long-lived subprocesses; use `bash scripts/verify_linux.sh` when verifying.
- Avoid mass-regenerating `offer_engine/reports/latest/**` unless the task requires fresh judge outputs.
- Prefer small, reviewable diffs over report churn.

"""

_HUMAN_JSON_CONTRACT = """
---
**Обов'язковий формат відповіді (Engineering Agent Governor):**
Спочатку один fenced блок ```json з полями:
- `verdict`: `CONTINUE` | `PASS` | `HOLD` | `FAIL`
- `summary`: короткий підсумок (1 абзац)
- `next_executor_prompt`: повний markdown для Cursor Agent (copy-paste)
- `stop_reason`: `null` або рядок причини

`PASS` — лише якщо ціль сесії повністю досягнута. `HOLD`/`FAIL` — зупинити цикл.
Після JSON — до 10 рядків пояснення. Без JSON Governor зупинить раунд.
"""


def _collab_log(message: str) -> None:
    print(f"[governor collab] {message}", file=sys.stderr, flush=True)


def _executor_prompt_with_preamble(prompt: str) -> str:
    p = prompt.strip()
    if not p:
        return p
    if p.startswith(CURSOR_EXECUTOR_PREAMBLE):
        return p
    return CURSOR_EXECUTOR_PREAMBLE + p


def _record_chatbang_failure(session: CollabSession, cb_result: ChatbangResult) -> None:
    if not cb_result.ok:
        session.chatbang_failures += 1


def _stop_before_executor(
    cb_result: ChatbangResult,
    review: CollabReview,
    opts: CollabStartOptions,
) -> tuple[bool, str | None]:
    """Return (should_stop, stop_reason) before dispatching Cursor."""
    if review.verdict in ("PASS", "HOLD", "FAIL"):
        return True, review.stop_reason or review.verdict
    if not cb_result.ok and not opts.continue_on_chatbang_fail:
        has_cursor_work = (
            review.verdict == "CONTINUE" and review.next_executor_prompt.strip()
        )
        if not has_cursor_work:
            return True, review.stop_reason or cb_result.error or "CHATBANG_FAILED"
    if review.verdict == "CONTINUE" and not review.next_executor_prompt.strip():
        return True, "CONTINUE without next_executor_prompt"
    return False, None

_COLLAB_SYSTEM = f"""{COLLAB_MARKER} — Chatbang collab reviewer (NOT Governor propose, NOT advisor VERDICT).

You collaborate with a Cursor executor via Engineering Agent Governor. The human is NOT the message bus.

Your job each round:
1) Review repository snapshot (git status, diff stat, prior executor output).
2) Decide verdict: CONTINUE | PASS | HOLD | FAIL.
3) If CONTINUE, provide a complete copy-paste executor prompt for Cursor.

Rules:
- Do NOT run shell yourself. Do NOT request git push unless human will use collab publish.
- Do NOT invent test results — use only evidence in context.
- PASS = task done, no more executor work. HOLD/FAIL = stop the loop (human must intervene).
- CONTINUE = executor should implement the next bounded slice.

Output format (strict):
1) First: one fenced ```json block with:
   verdict, summary, next_executor_prompt (string, empty if not CONTINUE), stop_reason (string or null)
2) Then: at most 10 lines markdown rationale.
"""

_COLLAB_JSON_EXAMPLE = """Required keys only (do not copy this example verbatim):
verdict, summary, next_executor_prompt, stop_reason"""


@dataclass
class CollabReview:
    verdict: str
    summary: str
    next_executor_prompt: str
    stop_reason: str | None = None
    raw_response: str = ""
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "next_executor_prompt": self.next_executor_prompt,
            "stop_reason": self.stop_reason,
            "parse_error": self.parse_error,
        }


@dataclass
class CollabRoundRecord:
    round_number: int
    run_id: str | None = None
    chatbang_verdict: str | None = None
    executor_exit_code: int | None = None
    gate_overall: str | None = None
    commit_hash: str | None = None
    stopped: bool = False
    stop_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CollabSession:
    session_id: str
    created_at: str
    updated_at: str
    task: str
    repo_path: str
    status: str
    max_rounds: int
    current_round: int
    commit_policy: str
    executor_profile: str
    gate_profile: str | None
    policy: str
    rounds: list[CollabRoundRecord] = field(default_factory=list)
    stop_reason: str | None = None
    chatbang_seed_file: str | None = None
    autopilot: bool = False
    chatbang_human_only: bool = False
    audit_run_id: str | None = None
    cli_options: dict[str, Any] | None = None
    chatbang_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "task": self.task,
            "repo_path": self.repo_path,
            "status": self.status,
            "max_rounds": self.max_rounds,
            "current_round": self.current_round,
            "commit_policy": self.commit_policy,
            "executor_profile": self.executor_profile,
            "gate_profile": self.gate_profile,
            "policy": self.policy,
            "rounds": [r.to_dict() for r in self.rounds],
            "stop_reason": self.stop_reason,
            "chatbang_seed_file": self.chatbang_seed_file,
            "autopilot": self.autopilot,
            "chatbang_human_only": self.chatbang_human_only,
            "audit_run_id": self.audit_run_id,
            "cli_options": self.cli_options,
            "chatbang_failures": self.chatbang_failures,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollabSession:
        rounds = [
            CollabRoundRecord(**{k: v for k, v in r.items() if k in CollabRoundRecord.__dataclass_fields__})
            for r in (data.get("rounds") or [])
            if isinstance(r, dict)
        ]
        return cls(
            session_id=data["session_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            task=data["task"],
            repo_path=data["repo_path"],
            status=data.get("status", "RUNNING"),
            max_rounds=int(data.get("max_rounds", 1)),
            current_round=int(data.get("current_round", 0)),
            commit_policy=data.get("commit_policy", "if_gates_pass"),
            executor_profile=data.get("executor_profile", "echo-test"),
            gate_profile=data.get("gate_profile"),
            policy=data.get("policy", "default"),
            rounds=rounds,
            stop_reason=data.get("stop_reason"),
            chatbang_seed_file=data.get("chatbang_seed_file"),
            autopilot=bool(data.get("autopilot")),
            chatbang_human_only=bool(data.get("chatbang_human_only")),
            audit_run_id=data.get("audit_run_id"),
            cli_options=data.get("cli_options"),
            chatbang_failures=int(data.get("chatbang_failures") or 0),
        )


@dataclass
class CollabStartOptions:
    task: str
    repo_path: str = "."
    max_rounds: int = 3
    policy: str | None = None
    gate_profile: str | None = None
    executor_profile: str = "echo-test"
    commit_policy: CommitPolicy = "if_gates_pass"
    chatbang_command: str = "chatbang"
    chatbang_timeout: int = 300
    executor_timeout: int | None = None
    approve: bool = False
    approve_commit: bool = False
    approve_push: bool = False
    dry_run: bool = False
    continue_on_gate_warn: bool = False
    skip_gates: bool = False
    accept_failed_executor: bool = False
    force_continue_on_hold: bool = False
    max_output_chars: int = 30000
    skip_preflight: bool = False
    chatbang_seed_file: str | None = None
    chatbang_seed_text: str | None = None
    autopilot: bool = False
    run_audit_after: bool = False
    auditor_profile: str | None = None
    governor_repo_path: str | None = None
    audit_timeout: int | None = None
    chatbang_human_only: bool = False
    chatbang_prompt_pattern: str = "> "
    continue_on_chatbang_fail: bool = False
    commit_exclude_dot_governor: bool = True


def collab_opts_snapshot(opts: CollabStartOptions) -> dict[str, Any]:
    data = asdict(opts)
    return {k: v for k, v in data.items() if v is not None}


@dataclass
class CollabLoopResult:
    session_id: str
    session_dir: Path
    status: str
    rounds_completed: int
    exit_code: int
    error: str | None = None
    last_run_id: str | None = None
    audit_run_id: str | None = None


def default_governor_repo_path() -> Path:
    return Path(__file__).resolve().parents[1]


def execution_approved(opts: CollabStartOptions) -> bool:
    return opts.approve or opts.autopilot


def commit_approved(opts: CollabStartOptions) -> bool:
    return opts.approve_commit or opts.approve or opts.autopilot


def load_chatbang_seed(*, seed_file: str | None, seed_text: str | None) -> str:
    if seed_file:
        path = Path(seed_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Chatbang seed file not found: {path}")
        return read_text_robust(path)
    if seed_text:
        return seed_text.strip()
    return ""


def build_chatbang_seed_prompt(*, seed_body: str, task: str) -> str:
    return redact(
        f"""{COLLAB_MARKER} — BOOTSTRAP round (human seed message).

You start a Chatbang ↔ Cursor collab session via Engineering Agent Governor.
The human is NOT the message bus — you must produce the first Cursor executor prompt.

Instructions:
1) Read the human seed completely (repo links, goals, constraints).
2) Use your GitHub plugin / repo knowledge as you normally would.
3) End with a fenced ```json block (required):
   verdict: CONTINUE | PASS | HOLD | FAIL
   summary: one paragraph
   next_executor_prompt: full copy-paste prompt for Cursor Agent (markdown)
   stop_reason: null or string
4) Then at most 15 lines of rationale.

Session task label: {task.strip()}

## Human seed message
{seed_body.strip()}
"""
    )


def build_human_chatbang_message(body: str, *, task: str, is_seed: bool = False) -> str:
    """Human-visible Chatbang text + mandatory JSON contract."""
    intro = ""
    if is_seed:
        intro = (
            f"Collab сесія (Governor). Завдання: {task.strip()}.\n"
            "Використай GitHub plugin для repo з seed. Потім дай JSON для Cursor.\n\n"
        )
    return redact(intro + body.strip() + _HUMAN_JSON_CONTRACT)


def _format_retry_json_prompt(*, task: str) -> str:
    return redact(
        f"Формат відхилено. Повтори відповідь для завдання «{task.strip()[:120]}»: "
        "лише ```json з verdict, summary, next_executor_prompt, stop_reason. "
        "verdict=CONTINUE якщо потрібен ще один раунд Cursor."
        + _HUMAN_JSON_CONTRACT
    )


def _summarize_executor_excerpt(raw: str, *, max_chars: int = 2500) -> str:
    """Send Chatbang a short Cursor summary, not full Governor dispatch markdown."""
    if not raw.strip():
        return ""
    text = raw
    if "## Stdout" in text:
        text = text.split("## Stdout", 1)[1]
        for stop in ("## Stderr", "## Notes", "## Role"):
            if stop in text:
                text = text.split(stop, 1)[0]
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("**Dispatch") or line.startswith("# Dispatch"):
            continue
        if line.startswith("**Runner:**") or line.startswith("**Exit code:**"):
            continue
        if line.startswith("**Duration") or line.startswith("**Prompt:**"):
            continue
        lines.append(line)
    summary = "\n".join(lines).strip()
    return summary[:max_chars]


def review_from_chatbang_output(
    cb_output: str,
    *,
    task: str,
    parse_error_label: str = "missing collab JSON",
    allow_freeform_fallback: bool = True,
) -> CollabReview:
    """Parse collab JSON; optional legacy fallback to freeform text as executor prompt."""
    parsed = parse_collab_response(cb_output)
    if parsed is not None and parsed.next_executor_prompt.strip():
        return parsed
    body = _collab_response_tail(cb_output).strip()
    if len(body) < 80:
        return CollabReview(
            verdict="HOLD",
            summary="Chatbang returned empty or too-short response",
            next_executor_prompt="",
            stop_reason="EMPTY_CHATBANG_RESPONSE",
            raw_response=cb_output,
            parse_error=parse_error_label,
        )
    if not allow_freeform_fallback:
        return CollabReview(
            verdict="HOLD",
            summary="Chatbang did not return required ```json collab block",
            next_executor_prompt="",
            stop_reason="MISSING_COLLAB_JSON",
            raw_response=cb_output,
            parse_error=parse_error_label,
        )
    return CollabReview(
        verdict="CONTINUE",
        summary="No collab JSON block; Governor forwarded Chatbang text to Cursor (legacy)",
        next_executor_prompt=(
            f"{CURSOR_EXECUTOR_PREAMBLE}\n"
            f"# Executor (Chatbang)\n\n**Session task:** {task.strip()}\n\n"
            f"{body[:MAX_EXECUTOR_PROMPT]}"
        ),
        stop_reason=None,
        raw_response=cb_output,
        parse_error=parse_error_label,
    )


def create_session_id(task: str) -> str:
    return f"{utc_run_timestamp()}_collab_{slugify(task)}"


def session_path(repo: Path, session_id: str) -> Path:
    return collab_dir(repo) / session_id


def round_dir(session_root: Path, round_number: int) -> Path:
    return session_root / f"round_{round_number:02d}"


def save_session(session_root: Path, session: CollabSession) -> None:
    session_root.mkdir(parents=True, exist_ok=True)
    session.updated_at = utc_now_iso()
    (session_root / SESSION_JSON).write_text(
        json.dumps(session.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_session(repo: Path, session_id: str) -> tuple[Path, CollabSession]:
    root = session_path(repo, session_id)
    path = root / SESSION_JSON
    if not path.is_file():
        raise FileNotFoundError(f"Collab session not found: {session_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return root, CollabSession.from_dict(data)


def list_sessions(repo: Path) -> list[dict[str, Any]]:
    base = collab_dir(repo)
    if not base.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        sj = child / SESSION_JSON
        if not sj.is_file():
            continue
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
            entries.append(
                {
                    "session_id": data.get("session_id", child.name),
                    "status": data.get("status", "?"),
                    "task": (data.get("task") or "")[:80],
                    "current_round": data.get("current_round", 0),
                    "max_rounds": data.get("max_rounds", 0),
                    "updated_at": data.get("updated_at", ""),
                }
            )
        except (OSError, json.JSONDecodeError):
            continue
    entries.sort(key=lambda e: e.get("updated_at", ""), reverse=True)
    return entries


def _try_parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
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
            if isinstance(data, dict):
                return data
            start = end
        except json.JSONDecodeError:
            start = brace + 1
    return None


def _collab_response_tail(raw: str) -> str:
    """Prefer model reply after prompt echo markers."""
    markers = (
        "Respond with the ```json collab block first.",
        "CHATBANG_COLLAB_OK",
        "## Your response now",
    )
    best = raw
    for marker in markers:
        if marker in raw:
            tail = raw.split(marker)[-1].strip()
            if len(tail) > 40:
                best = tail
    return best


def _is_placeholder_collab(parsed: dict[str, Any]) -> bool:
    summary = str(parsed.get("summary") or "")
    prompt = str(parsed.get("next_executor_prompt") or "")
    if "..." in prompt and len(prompt) < 120:
        return True
    if "Add OfferEngineClient.close()" in prompt and "..." in prompt:
        return True
    return False


def _review_from_loose_chatbang_json(
    parsed: dict[str, Any], *, raw_response: str
) -> CollabReview | None:
    """Chatbang often returns only {next_executor_prompt} without verdict."""
    prompt = str(parsed.get("next_executor_prompt") or "").strip()
    if not prompt or _is_placeholder_collab(parsed):
        return None
    verdict = str(parsed.get("verdict") or "CONTINUE").upper().strip()
    if verdict not in VERDICTS:
        verdict = "CONTINUE"
    return CollabReview(
        verdict=verdict,
        summary=str(parsed.get("summary") or "Chatbang next_executor_prompt").strip(),
        next_executor_prompt=prompt,
        stop_reason=(
            str(parsed["stop_reason"]).strip()
            if parsed.get("stop_reason") not in (None, "")
            else None
        ),
        raw_response=raw_response,
    )


def parse_collab_response(text: str) -> CollabReview | None:
    if not text.strip():
        return None
    if text.strip().upper() in ("CHATBANG_COLLAB_OK", "GOVERNOR_MODE_OK"):
        return None
    cleaned = re.sub(r"\[Thinking\.\.\.\]\s*", "", text, flags=re.IGNORECASE)
    cleaned = _collab_response_tail(cleaned)
    blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    for block in reversed(blocks):
        parsed = _try_parse_json_object(block.strip())
        if not parsed:
            continue
        if parsed.get("verdict") and not _is_placeholder_collab(parsed):
            return _review_from_parsed(parsed, raw_response=text)
        loose = _review_from_loose_chatbang_json(parsed, raw_response=text)
        if loose:
            return loose
    whole = _try_parse_json_object(cleaned)
    if whole:
        if whole.get("verdict") and not _is_placeholder_collab(whole):
            return _review_from_parsed(whole, raw_response=text)
        loose = _review_from_loose_chatbang_json(whole, raw_response=text)
        if loose:
            return loose
    return None


def _review_from_parsed(parsed: dict[str, Any], *, raw_response: str) -> CollabReview:
    verdict = str(parsed.get("verdict", "HOLD")).upper().strip()
    if verdict not in VERDICTS:
        verdict = "HOLD"
    return CollabReview(
        verdict=verdict,
        summary=str(parsed.get("summary") or "").strip(),
        next_executor_prompt=str(parsed.get("next_executor_prompt") or "").strip(),
        stop_reason=(
            str(parsed["stop_reason"]).strip()
            if parsed.get("stop_reason") not in (None, "")
            else None
        ),
        raw_response=raw_response,
    )


def build_collab_prompt(
    *,
    task: str,
    round_number: int,
    max_rounds: int,
    git_snapshot: dict[str, Any],
    prior_summary: str | None,
    last_executor_excerpt: str | None,
) -> str:
    parts = [
        _COLLAB_SYSTEM,
        "\n## JSON keys (fill for this task; do not echo this template)\n",
        _COLLAB_JSON_EXAMPLE,
        f"\n## Task\n{task.strip()}\n",
        f"## Round\n{round_number} of {max_rounds}\n",
    ]
    if prior_summary:
        parts.append(f"## Prior round summary\n{prior_summary}\n")
    if last_executor_excerpt:
        parts.append("## Last executor output (excerpt)\n```\n")
        parts.append(last_executor_excerpt[:6000])
        parts.append("\n```\n")
    parts.append("## Repository snapshot\n```json\n")
    parts.append(json.dumps(git_snapshot, indent=2, ensure_ascii=False)[:8000])
    parts.append("\n```\n\nRespond with the ```json collab block first.\n")
    return redact("".join(parts))


def _sanitize_excerpt_for_chatbang(text: str) -> str:
    """Avoid false pexpect prompt matches on lines like `> # Echo` in executor output."""
    return re.sub(r"^> ", "| ", text, flags=re.MULTILINE)


def build_human_round_message(
    *,
    task: str,
    round_number: int,
    max_rounds: int,
    git_snapshot: dict[str, Any],
    prior_summary: str | None,
    last_executor_excerpt: str | None,
) -> str:
    """Natural-language follow-up for Chatbang (no CHATBANG_COLLAB_V1 / wire protocol)."""
    head = git_snapshot.get("head", "?")
    status = (git_snapshot.get("short_status") or "").strip()
    diff_stat = (git_snapshot.get("diff_stat") or "").strip()
    parts = [
        f"Раунд {round_number} з {max_rounds}.\n\n",
        f"Завдання сесії: {task.strip()}\n",
    ]
    if prior_summary:
        parts.append(f"\nПідсумок попереднього кроку:\n{prior_summary.strip()}\n")
    if last_executor_excerpt:
        summary = _summarize_executor_excerpt(last_executor_excerpt)
        if summary:
            parts.append("\nКороткий підсумок останнього Cursor (stdout):\n```\n")
            parts.append(_sanitize_excerpt_for_chatbang(summary))
            parts.append("\n```\n")
    parts.append(f"\nGit HEAD: {head}\n")
    if status:
        parts.append(f"Статус:\n{status}\n")
    if diff_stat:
        parts.append(f"\ndiff --stat:\n{diff_stat[:4000]}\n")
    parts.append(
        "\nПереглянь зміни (GitHub plugin) і виріши: CONTINUE, PASS, HOLD чи FAIL. "
        "PASS — лише якщо ціль сесії досягнута повністю.\n"
    )
    return build_human_chatbang_message("".join(parts), task=task, is_seed=False)


def build_collab_wire_message(
    *,
    task: str,
    round_number: int,
    max_rounds: int,
    git_snapshot: dict[str, Any],
) -> str:
    """Compact wire prompt for pexpect (full audit prompt saved separately)."""
    status = git_snapshot.get("short_status", "")[:200]
    head = git_snapshot.get("head", "?")
    return redact(
        f"{COLLAB_MARKER} round {round_number}/{max_rounds}. "
        f"Task: {task.strip()[:200]}. HEAD={head}. Status: {status}. "
        "Output ```json with verdict, summary, next_executor_prompt, stop_reason."
    )


def _session_trace(session_root: Path, session_id: str) -> TraceLogger:
    return TraceLogger(session_root, session_id, trace_filename=COLLAB_TRACE)


def _write_round_artifacts(
    rdir: Path,
    *,
    request_md: str,
    response_md: str,
    review: CollabReview | None,
    executor_prompt: str | None,
    gate_report: dict[str, Any] | None,
    commit: GitCommitResult | None,
    governor_request_md: str | None = None,
) -> None:
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "chatbang_request.md").write_text(request_md, encoding="utf-8")
    if governor_request_md and governor_request_md.strip() != request_md.strip():
        (rdir / "chatbang_request_governor.md").write_text(
            governor_request_md, encoding="utf-8"
        )
    (rdir / "chatbang_response.md").write_text(response_md, encoding="utf-8")
    if review:
        (rdir / "collab_review.json").write_text(
            json.dumps(review.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if executor_prompt:
        (rdir / "executor_prompt.md").write_text(executor_prompt + "\n", encoding="utf-8")
    if gate_report is not None:
        (rdir / "gate_results.json").write_text(
            json.dumps(gate_report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if commit is not None:
        (rdir / "git_commit.json").write_text(
            json.dumps(commit.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _dispatch_executor_for_collab(
    store: RunStore,
    run_id: str,
    *,
    executor_profile: str,
    repo: Path,
    repo_path_str: str,
    executor_prompt: str,
    timeout: int,
    approve: bool,
    accept_failed: bool,
) -> tuple[int, str]:
    run_dir, meta = store.get_run(run_id)
    prompt_path = run_dir / "03_executor_prompt.md"
    body = redact(executor_prompt)
    if len(body) > MAX_CHATBANG_TO_CURSOR_PROMPT:
        body = (
            body[:MAX_CHATBANG_TO_CURSOR_PROMPT]
            + "\n\n...(prompt truncated by Governor; see chatbang_response.md in collab round)\n"
        )
    prompt_path.write_text(body + "\n", encoding="utf-8")

    if meta.state == RunState.INTAKE_CREATED.value:
        meta = store.update_state(run_id, "init")
    if meta.state != RunState.EXECUTOR_PROMPT_READY.value:
        if meta.state == RunState.INTAKE_CREATED.value:
            meta = store.update_state(run_id, "init")

    if not approve:
        return 0, ""

    _prof, spec = get_profile(repo, executor_profile, allow_disabled=True)
    _collab_log(
        f"Cursor → dispatch profile={executor_profile!r} timeout={timeout}s "
        f"(prompt {prompt_path.stat().st_size} bytes) — may take several minutes"
    )

    _, result = execute_dispatch(
        store,
        run_id,
        "executor",
        spec,
        timeout,
        replace=True,
        repo_path=repo_path_str,
        accept_failed_output=accept_failed,
        profile_name=executor_profile,
    )
    out_path = run_dir / "05_executor_output.md"
    excerpt = ""
    if out_path.is_file():
        excerpt = read_text_robust(out_path)[:8000]
    _collab_log(f"Cursor ← finished exit={result.exit_code}")
    return result.exit_code, excerpt


def preflight_collab(repo: Path, opts: CollabStartOptions) -> list[str]:
    """Return list of fatal error messages (empty if ready)."""
    errors: list[str] = []
    if opts.skip_preflight:
        return errors

    cfg_p = config_path(repo)
    if not cfg_p.is_file():
        errors.append(f"Missing {cfg_p}; run: python -m governor config init --repo-path {repo}")
        return errors

    try:
        profiles = load_profiles(cfg_p)
        prof = profiles.get(opts.executor_profile)
        if prof is None:
            errors.append(
                f"Unknown executor profile {opts.executor_profile!r}. "
                f"Available: {', '.join(sorted(profiles))}"
            )
        elif not prof.argv:
            errors.append(
                f"Profile {opts.executor_profile!r} has empty argv. "
                "Set argv in .governor/config.json, e.g. "
                '["agent", "-p", "--force", "--output-format", "text"] '
                "(see docs/CURSOR_HEADLESS_RUNNER.md)"
            )
        elif not prof.enabled:
            errors.append(
                f"Profile {opts.executor_profile!r} is disabled. "
                "Set enabled: true in .governor/config.json"
            )
    except ValueError as e:
        errors.append(str(e))

    if not is_chatbang_available(opts.chatbang_command):
        errors.append(
            f"chatbang/pexpect unavailable for command {opts.chatbang_command!r}. "
            "Install: pip install 'engineering-agent-governor[advisor]'"
        )
    elif opts.chatbang_human_only:
        probe_session = ChatbangPersistentSession(
            command=opts.chatbang_command,
            timeout=min(90, opts.chatbang_timeout),
            prompt_pattern=opts.chatbang_prompt_pattern,
        )
        spawn_err = probe_session._ensure_child()
        probe_session.close()
        if spawn_err is not None:
            errors.append(
                spawn_err.error
                or "chatbang failed to start (Chrome profile lock or browser path)"
            )
    else:
        probe = probe_chatbang(
            command=opts.chatbang_command,
            timeout=min(120, opts.chatbang_timeout),
        )
        if not probe.ok:
            hint = probe.error or "chatbang probe failed"
            errors.append(
                f"{hint}. Close any other chatbang terminal windows and retry."
            )

    return errors


def _maybe_commit(
    repo: Path,
    *,
    policy: CommitPolicy,
    gate_overall: str | None,
    round_number: int,
    session_id: str,
    approve_commit: bool,
    continue_on_gate_warn: bool,
    exclude_dot_governor: bool = False,
) -> GitCommitResult:
    if policy == "never":
        return GitCommitResult(False, skipped_reason="commit_policy=never")
    if policy == "if_gates_pass":
        if gate_overall == "FAIL":
            return GitCommitResult(False, skipped_reason="gates FAIL")
        if gate_overall == "WARN" and not continue_on_gate_warn:
            return GitCommitResult(False, skipped_reason="gates WARN (use --continue-on-gate-warn)")
    msg = f"collab({session_id}): round {round_number} snapshot"
    exclude = (".governor/",) if exclude_dot_governor else ()
    return commit_if_dirty(
        repo, msg, approve=approve_commit, exclude_path_prefixes=exclude
    )


def _chatbang_exchange(
    chatbang: ChatbangPersistentSession,
    *,
    wire: str,
    full_prompt: str,
    task: str,
    human_only: bool = False,
    continue_on_chatbang_fail: bool = False,
) -> tuple[Any, CollabReview]:
    if human_only:
        message = full_prompt.strip()
        if not message:
            return (
                ChatbangResult(ok=False, output="", duration_seconds=0.0, error="empty prompt"),
                CollabReview(
                    verdict="HOLD",
                    summary="Empty message for chatbang",
                    next_executor_prompt="",
                    stop_reason="EMPTY_PROMPT",
                ),
            )
        _collab_log(
            f"Chatbang ← sending human message ({len(message)} chars, one line for UI)"
        )
        cb_result = chatbang.send(
            message, single_line=True, wait_for_json=True
        )
        combined_output = cb_result.output or ""
        review = parse_collab_response(combined_output)
        needs_json_retry = review is None or (
            review.verdict == "CONTINUE" and not review.next_executor_prompt.strip()
        )
        if needs_json_retry:
            _collab_log("Chatbang JSON missing — sending format retry")
            retry = chatbang.send(
                _format_retry_json_prompt(task=task),
                single_line=True,
                wait_for_json=True,
            )
            if retry.output:
                combined_output = combined_output + "\n\n--- retry ---\n\n" + retry.output
            if not retry.ok:
                cb_result = retry
            review = parse_collab_response(combined_output)
        _collab_log(
            f"Chatbang → response ({len(combined_output)} chars, "
            f"ok={cb_result.ok}, {cb_result.duration_seconds:.1f}s)"
        )
        if cb_result.error:
            _collab_log(f"Chatbang error: {cb_result.error}")
        if not cb_result.ok and not continue_on_chatbang_fail:
            if not (review and review.next_executor_prompt.strip()):
                return cb_result, CollabReview(
                    verdict="HOLD",
                    summary=cb_result.error or "Chatbang request failed",
                    next_executor_prompt="",
                    stop_reason="CHATBANG_FAILED",
                    raw_response=combined_output,
                )
        if review is None or (
            review.verdict == "CONTINUE" and not review.next_executor_prompt.strip()
        ):
            review = review_from_chatbang_output(
                combined_output,
                task=task,
                allow_freeform_fallback=False,
            )
        elif review.parse_error and review.next_executor_prompt.strip():
            review.parse_error = None
        if review.verdict == "CONTINUE" and review.next_executor_prompt.strip():
            review.next_executor_prompt = _executor_prompt_with_preamble(
                review.next_executor_prompt
            )
        cb_result = ChatbangResult(
            ok=cb_result.ok or bool(combined_output.strip()),
            output=combined_output,
            duration_seconds=cb_result.duration_seconds,
            error=cb_result.error,
        )
        return cb_result, review

    cb_result = chatbang.send(wire)
    review = parse_collab_response(cb_result.output)
    if review is None and full_prompt:
        cb_result = chatbang.send(full_prompt)
        review = review_from_chatbang_output(cb_result.output or "", task=task)
    elif review is None:
        review = review_from_chatbang_output(cb_result.output or "", task=task)
    elif not review.next_executor_prompt.strip():
        review = review_from_chatbang_output(cb_result.output or "", task=task)
    return cb_result, review


def _execute_executor_round(
    *,
    opts: CollabStartOptions,
    session: CollabSession,
    session_id: str,
    repo: Path,
    store: RunStore,
    policy: str,
    gate_prof: str | None,
    round_number: int,
    review: CollabReview,
    rdir: Path,
    chatbang_sent_md: str,
    cb_output: str,
    governor_request_md: str | None = None,
) -> tuple[int, str, str | None, GitCommitResult, str | None, bool, str | None]:
    """Returns exec_code, excerpt, gate_overall, commit, run_id, should_stop, stop_reason."""
    record = CollabRoundRecord(round_number=round_number, chatbang_verdict=review.verdict)
    _write_round_artifacts(
        rdir,
        request_md=chatbang_sent_md,
        response_md=cb_output or "(empty)",
        review=review,
        executor_prompt=None,
        gate_report=None,
        commit=None,
        governor_request_md=governor_request_md,
    )

    effective_verdict = review.verdict
    if (
        review.verdict == "HOLD"
        and opts.force_continue_on_hold
        and review.next_executor_prompt.strip()
    ):
        effective_verdict = "CONTINUE"

    if effective_verdict in ("PASS", "HOLD", "FAIL"):
        record.stopped = True
        record.stop_reason = review.stop_reason or review.verdict
        session.rounds.append(record)
        return 0, "", None, GitCommitResult(False), None, True, record.stop_reason

    if effective_verdict == "CONTINUE" and not review.next_executor_prompt.strip():
        record.stopped = True
        record.stop_reason = "CONTINUE without next_executor_prompt"
        session.rounds.append(record)
        return 0, "", None, GitCommitResult(False), None, True, record.stop_reason

    run_dir, meta = store.create_run(
        f"{opts.task} (collab round {round_number})",
        policy_name=policy,
    )
    run_id = meta.run_id
    record.run_id = run_id

    prof, _spec = get_profile(repo, opts.executor_profile, allow_disabled=True)
    exec_timeout = opts.executor_timeout or prof.timeout
    exec_code, excerpt = _dispatch_executor_for_collab(
        store,
        run_id,
        executor_profile=opts.executor_profile,
        repo=repo,
        repo_path_str=str(repo),
        executor_prompt=_executor_prompt_with_preamble(review.next_executor_prompt),
        timeout=exec_timeout,
        approve=execution_approved(opts),
        accept_failed=opts.accept_failed_executor,
    )
    record.executor_exit_code = exec_code

    gate_report_dict: dict[str, Any] | None = None
    gate_overall: str | None = None
    if not opts.skip_gates:
        report = run_gates(repo, gate_profile=gate_prof)
        gate_overall = report.overall
        record.gate_overall = gate_overall
        write_gate_artifacts(run_dir, report)
        gate_report_dict = report.to_dict()
        store.update_state(run_id, "gate")

    commit_result = _maybe_commit(
        repo,
        policy=opts.commit_policy,
        gate_overall=gate_overall,
        round_number=round_number,
        session_id=session_id,
        approve_commit=commit_approved(opts),
        continue_on_gate_warn=opts.continue_on_gate_warn,
        exclude_dot_governor=opts.commit_exclude_dot_governor,
    )
    if commit_result.committed:
        record.commit_hash = commit_result.commit_hash
    if opts.approve_push and commit_result.committed:
        push_current_branch(repo, approve=commit_approved(opts))

    _write_round_artifacts(
        rdir,
        request_md=chatbang_sent_md,
        response_md=cb_output or "(empty)",
        review=review,
        executor_prompt=review.next_executor_prompt,
        gate_report=gate_report_dict,
        commit=commit_result,
        governor_request_md=governor_request_md,
    )
    session.rounds.append(record)

    if exec_code != 0 and not opts.accept_failed_executor:
        return (
            exec_code,
            excerpt,
            gate_overall,
            commit_result,
            run_id,
            True,
            f"executor exit {exec_code}",
        )
    return exec_code, excerpt, gate_overall, commit_result, run_id, False, None


def run_bootstrap_round(
    *,
    opts: CollabStartOptions,
    session: CollabSession,
    session_root: Path,
    session_id: str,
    repo: Path,
    store: RunStore,
    policy: str,
    gate_prof: str | None,
    chatbang: ChatbangPersistentSession,
    seed_body: str,
    trace: TraceLogger,
) -> tuple[int, str, str | None, str | None, bool, str | None]:
    """Seed → chatbang → cursor. Returns excerpt, summary, run_id, should_stop, stop_reason."""
    rdir = round_dir(session_root, BOOTSTRAP_ROUND)
    rdir.mkdir(parents=True, exist_ok=True)
    git_snap = capture_git_snapshot(repo).to_dict()
    governor_seed_prompt = build_chatbang_seed_prompt(seed_body=seed_body, task=opts.task)
    (rdir / "chatbang_seed.md").write_text(seed_body + "\n", encoding="utf-8")

    if opts.chatbang_human_only:
        chatbang_sent = build_human_chatbang_message(
            seed_body, task=opts.task, is_seed=True
        )
        _collab_log("Round 00: seed → Chatbang (human-only, single line)")
        cb_result, review = _chatbang_exchange(
            chatbang,
            wire="",
            full_prompt=chatbang_sent,
            task=opts.task,
            human_only=True,
            continue_on_chatbang_fail=opts.continue_on_chatbang_fail,
        )
    else:
        chatbang_sent = governor_seed_prompt
        cb_result, review = _chatbang_exchange(
            chatbang,
            wire=(
                f"{COLLAB_MARKER} BOOTSTRAP. Task: {opts.task[:120]}. "
                "Output ```json with next_executor_prompt."
            ),
            full_prompt=governor_seed_prompt,
            task=opts.task,
        )

    trace.append(
        phase="collab",
        actor="chatbang",
        action="bootstrap",
        status="ok" if cb_result.ok else "fail",
        output_ref="round_00/collab_review.json",
        reason=f"verdict={review.verdict}",
    )
    _record_chatbang_failure(session, cb_result)
    stop, stop_reason = _stop_before_executor(cb_result, review, opts)
    if stop:
        _write_round_artifacts(
            rdir,
            request_md=chatbang_sent,
            response_md=cb_result.output or "(empty)",
            review=review,
            executor_prompt=None,
            gate_report=None,
            commit=None,
            governor_request_md=(
                governor_seed_prompt if opts.chatbang_human_only else None
            ),
        )
        session.rounds.append(
            CollabRoundRecord(
                round_number=BOOTSTRAP_ROUND,
                chatbang_verdict=review.verdict,
                stopped=True,
                stop_reason=stop_reason,
            )
        )
        return 0, review.summary, "", None, True, stop_reason

    exec_code, excerpt, _gate, _commit, run_id, should_stop, stop_reason = _execute_executor_round(
        opts=opts,
        session=session,
        session_id=session_id,
        repo=repo,
        store=store,
        policy=policy,
        gate_prof=gate_prof,
        round_number=BOOTSTRAP_ROUND,
        review=review,
        rdir=rdir,
        chatbang_sent_md=chatbang_sent,
        cb_output=cb_result.output or "",
        governor_request_md=(
            governor_seed_prompt if opts.chatbang_human_only else None
        ),
    )
    return exec_code, review.summary, excerpt, run_id, should_stop, stop_reason


def build_collab_audit_prompt(
    *,
    session: CollabSession,
    session_root: Path,
    target_repo: Path,
    governor_repo: Path,
) -> str:
    round_summaries: list[str] = []
    for r in session.rounds:
        round_summaries.append(
            f"- round {r.round_number}: verdict={r.chatbang_verdict} run={r.run_id} "
            f"gates={r.gate_overall} commit={r.commit_hash}"
        )
    seed_note = ""
    seed_path = session_root / "round_00" / "chatbang_seed.md"
    if seed_path.is_file():
        seed_note = f"\nSeed file snapshot: {seed_path}\n"
    return redact(
        f"""# Governor collab post-run audit (Cursor executor)

You are an independent auditor — NOT the collab executor that worked on the product repo.

## Context
- **Product repo (audited implementation):** `{target_repo}`
- **Governor package repo (audit target for improvements):** `{governor_repo}`
- **Collab session folder:** `{session_root}`
- **Session task:** {session.task}
- **Rounds completed:** {session.current_round}/{session.max_rounds}
- **Autopilot:** {session.autopilot}
{seed_note}

## Your mission
1. Read collab artifacts under `{session_root}` (round_00 bootstrap if present, round_01..N, trace.jsonl).
2. Inspect the **real product repo** at `{target_repo}` (git state, key files, tests if feasible).
3. Inspect **Engineering Agent Governor** code/docs at `{governor_repo}` — especially `governor/collab_loop.py`, CLI, docs.
4. Produce a detailed audit of how well the collab loop worked and **concrete improvements** to `python -m governor` collab mode.

## Required output files (write in your response as sections; Governor saves verbatim)
### 01_executive_summary.md
### 02_collab_session_verdict.md
### 03_product_repo_findings.md
### 04_governor_improvement_backlog.md
(prioritized: P0/P1/P2, file paths, acceptance criteria)
### 05_shady_moments_and_risks.md
### 06_recommended_next_commands.md

Be blunt. No false PASS. Cite paths and evidence from session artifacts.

## Round index
{chr(10).join(round_summaries) or "(no rounds recorded)"}
"""
    )


def run_collab_audit(
    *,
    opts: CollabStartOptions,
    session: CollabSession,
    session_root: Path,
    target_repo: Path,
    store: RunStore,
    policy: str,
) -> str | None:
    gov_repo = resolve_repo_path(opts.governor_repo_path or str(default_governor_repo_path()))
    audit_dir = session_root / AUDIT_DIR
    audit_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_collab_audit_prompt(
        session=session,
        session_root=session_root,
        target_repo=target_repo,
        governor_repo=gov_repo,
    )
    (audit_dir / "auditor_request.md").write_text(prompt, encoding="utf-8")

    auditor_profile = opts.auditor_profile or opts.executor_profile
    prof, _spec = get_profile(gov_repo, auditor_profile, allow_disabled=True)
    timeout = opts.audit_timeout or prof.timeout

    run_dir, meta = store.create_run(
        f"Collab audit: {session.session_id}",
        policy_name=policy,
    )
    prompt_path = run_dir / "03_executor_prompt.md"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    if store.load_metadata(run_dir).state == RunState.INTAKE_CREATED.value:
        store.update_state(meta.run_id, "init")

    _, result = execute_dispatch(
        store,
        meta.run_id,
        "executor",
        _spec,
        timeout,
        replace=True,
        repo_path=str(gov_repo),
        accept_failed_output=True,
        profile_name=auditor_profile,
    )
    out_path = run_dir / "05_executor_output.md"
    audit_output = read_text_robust(out_path) if out_path.is_file() else ""
    (audit_dir / "auditor_response.md").write_text(audit_output, encoding="utf-8")
    (audit_dir / "governor_repo_path.txt").write_text(str(gov_repo) + "\n", encoding="utf-8")
    (audit_dir / "product_repo_path.txt").write_text(str(target_repo) + "\n", encoding="utf-8")
    (audit_dir / "audit_run_id.txt").write_text(meta.run_id + "\n", encoding="utf-8")

    sections = {
        "01_executive_summary.md": "## Executive summary",
        "02_collab_session_verdict.md": "## Collab session verdict",
        "03_product_repo_findings.md": "## Product repo findings",
        "04_governor_improvement_backlog.md": "## Governor improvement backlog",
        "05_shady_moments_and_risks.md": "## Shady moments and risks",
        "06_recommended_next_commands.md": "## Recommended next commands",
    }
    for filename, heading in sections.items():
        part = _extract_markdown_section(audit_output, heading)
        if part:
            (audit_dir / filename).write_text(part + "\n", encoding="utf-8")

    if not (audit_dir / "01_executive_summary.md").is_file():
        (audit_dir / "01_full_auditor_output.md").write_text(audit_output + "\n", encoding="utf-8")

    return meta.run_id


def _extract_markdown_section(text: str, heading: str) -> str:
    if heading not in text:
        return ""
    start = text.index(heading)
    rest = text[start + len(heading) :]
    next_h = re.search(r"\n###? ", rest)
    if next_h:
        rest = rest[: next_h.start()]
    return heading + rest.strip()


def run_collab_loop(opts: CollabStartOptions) -> CollabLoopResult:
    repo = resolve_repo_path(opts.repo_path)
    session_id = create_session_id(opts.task)
    session_root = session_path(repo, session_id)
    if session_root.exists():
        return CollabLoopResult(
            session_id,
            session_root,
            "FAILED",
            0,
            1,
            error="Session directory already exists",
        )

    policy = resolve_policy_for_repo(repo, opts.policy)
    gate_prof = opts.gate_profile or resolve_gate_profile_for_repo(repo, None)

    seed_body = load_chatbang_seed(
        seed_file=opts.chatbang_seed_file,
        seed_text=opts.chatbang_seed_text,
    )

    session = CollabSession(
        session_id=session_id,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
        task=opts.task,
        repo_path=str(repo),
        status="RUNNING",
        max_rounds=max(1, min(opts.max_rounds, 20)),
        current_round=0,
        commit_policy=opts.commit_policy,
        executor_profile=opts.executor_profile,
        gate_profile=gate_prof,
        policy=policy,
        chatbang_seed_file=opts.chatbang_seed_file,
        autopilot=opts.autopilot,
        chatbang_human_only=opts.chatbang_human_only,
        cli_options=collab_opts_snapshot(opts),
    )
    save_session(session_root, session)
    trace = _session_trace(session_root, session_id)

    if opts.dry_run:
        trace.append(
            phase="collab",
            actor="governor",
            action="dry_run",
            reason=(
                f"Would run bootstrap={bool(seed_body)} rounds={session.max_rounds} "
                f"autopilot={opts.autopilot} human_only={opts.chatbang_human_only} "
                f"audit={opts.run_audit_after}"
            ),
        )
        session.status = "DRY_RUN"
        save_session(session_root, session)
        return CollabLoopResult(session_id, session_root, "DRY_RUN", 0, 0)

    if not execution_approved(opts):
        session.status = "NEEDS_APPROVE"
        session.stop_reason = "Re-run with --approve or --autopilot to execute collab rounds"
        save_session(session_root, session)
        return CollabLoopResult(
            session_id,
            session_root,
            "NEEDS_APPROVE",
            0,
            0,
            error=session.stop_reason,
        )

    preflight_errors = preflight_collab(repo, opts)
    if preflight_errors:
        session.status = "FAILED"
        session.stop_reason = preflight_errors[0]
        save_session(session_root, session)
        return CollabLoopResult(
            session_id,
            session_root,
            "FAILED",
            0,
            1,
            error="; ".join(preflight_errors),
        )

    chatbang = ChatbangPersistentSession(
        command=opts.chatbang_command,
        timeout=min(max(60, opts.chatbang_timeout), 900),
        prompt_pattern=opts.chatbang_prompt_pattern,
        max_output_chars=opts.max_output_chars,
    )
    store = init_store(str(repo))
    last_executor_excerpt = ""
    prior_summary: str | None = None
    last_run_id: str | None = None
    exit_code = 0

    try:
        if not opts.chatbang_human_only:
            prime_result = chatbang.prime(COLLAB_SESSION_PRIME)
            if not prime_result.ok:
                session.status = "FAILED"
                session.stop_reason = prime_result.error or "chatbang prime failed"
                save_session(session_root, session)
                return CollabLoopResult(
                    session_id,
                    session_root,
                    "FAILED",
                    0,
                    1,
                    error=session.stop_reason,
                )

        rounds_completed = 0

        if seed_body:
            session.current_round = BOOTSTRAP_ROUND
            _collab_log("=== Bootstrap: Chatbang seed → Cursor → commit ===")
            b_exec, prior_summary, last_executor_excerpt, last_run_id, stop, stop_reason = (
                run_bootstrap_round(
                    opts=opts,
                    session=session,
                    session_root=session_root,
                    session_id=session_id,
                    repo=repo,
                    store=store,
                    policy=policy,
                    gate_prof=gate_prof,
                    chatbang=chatbang,
                    seed_body=seed_body,
                    trace=trace,
                )
            )
            save_session(session_root, session)
            rounds_completed = 1
            if stop:
                if stop_reason and str(stop_reason).upper() == "PASS":
                    session.status = "COMPLETED"
                else:
                    session.status = "STOPPED"
                session.stop_reason = stop_reason
                save_session(session_root, session)
                return CollabLoopResult(
                    session_id,
                    session_root,
                    session.status,
                    rounds_completed,
                    0 if session.status == "COMPLETED" else (b_exec or 1),
                    last_run_id=last_run_id,
                )
            if b_exec != 0 and not opts.accept_failed_executor:
                exit_code = b_exec

        for round_number in range(1, session.max_rounds + 1):
            session.current_round = round_number
            _collab_log(
                f"=== Round {round_number}/{session.max_rounds}: "
                "Chatbang review → Cursor → commit ==="
            )
            rdir = round_dir(session_root, round_number)
            git_snap = capture_git_snapshot(repo).to_dict()

            governor_prompt = build_collab_prompt(
                task=opts.task,
                round_number=round_number,
                max_rounds=session.max_rounds,
                git_snapshot=git_snap,
                prior_summary=prior_summary,
                last_executor_excerpt=last_executor_excerpt or None,
            )
            if opts.chatbang_human_only:
                _collab_log(
                    f"Round {round_number}: git snapshot + prior Cursor output → Chatbang"
                )
                chatbang_sent = build_human_round_message(
                    task=opts.task,
                    round_number=round_number,
                    max_rounds=session.max_rounds,
                    git_snapshot=git_snap,
                    prior_summary=prior_summary,
                    last_executor_excerpt=last_executor_excerpt or None,
                )
                cb_result, review = _chatbang_exchange(
                    chatbang,
                    wire="",
                    full_prompt=chatbang_sent,
                    task=opts.task,
                    human_only=True,
                    continue_on_chatbang_fail=opts.continue_on_chatbang_fail,
                )
            else:
                chatbang_sent = governor_prompt
                wire = build_collab_wire_message(
                    task=opts.task,
                    round_number=round_number,
                    max_rounds=session.max_rounds,
                    git_snapshot=git_snap,
                )
                cb_result, review = _chatbang_exchange(
                    chatbang,
                    wire=wire,
                    full_prompt=governor_prompt,
                    task=opts.task,
                )

            trace.append(
                phase="collab",
                actor="chatbang",
                action="review",
                status="ok" if cb_result.ok else "fail",
                output_ref=f"round_{round_number:02d}/collab_review.json",
                reason=f"verdict={review.verdict}",
            )
            _record_chatbang_failure(session, cb_result)

            if review.verdict == "PASS":
                _write_round_artifacts(
                    rdir,
                    request_md=chatbang_sent,
                    response_md=cb_result.output or "(empty)",
                    review=review,
                    executor_prompt=None,
                    gate_report=None,
                    commit=None,
                    governor_request_md=(
                        governor_prompt if opts.chatbang_human_only else None
                    ),
                )
                session.rounds.append(
                    CollabRoundRecord(
                        round_number=round_number,
                        chatbang_verdict="PASS",
                        stopped=True,
                        stop_reason=review.stop_reason or "PASS",
                    )
                )
                session.status = "COMPLETED"
                session.stop_reason = review.stop_reason or "PASS"
                save_session(session_root, session)
                return CollabLoopResult(
                    session_id,
                    session_root,
                    "COMPLETED",
                    round_number,
                    0,
                    last_run_id=last_run_id,
                )

            stop, stop_reason = _stop_before_executor(cb_result, review, opts)
            if stop:
                _write_round_artifacts(
                    rdir,
                    request_md=chatbang_sent,
                    response_md=cb_result.output or "(empty)",
                    review=review,
                    executor_prompt=None,
                    gate_report=None,
                    commit=None,
                    governor_request_md=(
                        governor_prompt if opts.chatbang_human_only else None
                    ),
                )
                session.rounds.append(
                    CollabRoundRecord(
                        round_number=round_number,
                        chatbang_verdict=review.verdict,
                        stopped=True,
                        stop_reason=stop_reason,
                    )
                )
                session.status = "STOPPED"
                session.stop_reason = stop_reason
                save_session(session_root, session)
                _collab_log(f"Stopped before Cursor: {stop_reason}")
                return CollabLoopResult(
                    session_id,
                    session_root,
                    "STOPPED",
                    round_number,
                    1,
                    last_run_id=last_run_id,
                )

            exec_code, excerpt, gate_overall, _commit, run_id, stop, stop_reason = (
                _execute_executor_round(
                    opts=opts,
                    session=session,
                    session_id=session_id,
                    repo=repo,
                    store=store,
                    policy=policy,
                    gate_prof=gate_prof,
                    round_number=round_number,
                    review=review,
                    rdir=rdir,
                    chatbang_sent_md=chatbang_sent,
                    cb_output=cb_result.output or "",
                    governor_request_md=(
                        governor_prompt if opts.chatbang_human_only else None
                    ),
                )
            )
            last_run_id = run_id or last_run_id
            last_executor_excerpt = excerpt
            prior_summary = review.summary
            rounds_completed = round_number
            save_session(session_root, session)

            trace.append(
                phase="collab",
                actor="governor",
                action="round_complete",
                output_ref=last_run_id or "",
                reason=f"executor_exit={exec_code} gates={gate_overall}",
            )

            if gate_overall == "FAIL" and not opts.accept_failed_executor:
                exit_code = 2

            if stop:
                session.status = "STOPPED"
                session.stop_reason = stop_reason
                save_session(session_root, session)
                return CollabLoopResult(
                    session_id,
                    session_root,
                    "STOPPED",
                    rounds_completed,
                    exec_code or 1,
                    last_run_id=last_run_id,
                )

        session.status = "COMPLETED"
        session.stop_reason = "max_rounds reached without PASS"
        save_session(session_root, session)

        audit_run_id: str | None = None
        if opts.run_audit_after:
            audit_run_id = run_collab_audit(
                opts=opts,
                session=session,
                session_root=session_root,
                target_repo=repo,
                store=store,
                policy=policy,
            )
            session.audit_run_id = audit_run_id
            save_session(session_root, session)
            trace.append(
                phase="collab",
                actor="governor",
                action="audit",
                output_ref=AUDIT_DIR,
                reason=f"audit_run_id={audit_run_id}",
            )

        return CollabLoopResult(
            session_id,
            session_root,
            session.status,
            rounds_completed,
            exit_code,
            last_run_id=last_run_id,
            audit_run_id=audit_run_id,
        )
    finally:
        chatbang.close()
