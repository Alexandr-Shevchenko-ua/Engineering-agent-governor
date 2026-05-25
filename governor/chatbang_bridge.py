"""Interactive chatbang bridge via pexpect (Governor Advisor only — not executor)."""

from __future__ import annotations

import shlex
import shutil
import time
from dataclasses import dataclass
from governor.redaction import redact

PEXPECT_INSTALL_HINT = (
    "pexpect is required for chatbang advisor on this platform. "
    "Install with: pip install 'engineering-agent-governor[advisor]' "
    "or pip install 'pexpect>=4.8'"
)


@dataclass(frozen=True)
class ChatbangSessionConfig:
    command: str = "chatbang"
    timeout: int = 180
    prompt_pattern: str = "> "
    max_output_chars: int = 20000


@dataclass
class ChatbangResult:
    ok: bool
    output: str
    duration_seconds: float
    timed_out: bool = False
    exit_status: int | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        if self.timed_out:
            return "timeout"
        if self.error:
            return "error"
        return "ok" if self.ok else "fail"


def _spawn_process(pexpect, command: str, timeout: int):
    parts = shlex.split(command)
    if not parts:
        raise ValueError("empty command")
    if len(parts) == 1:
        return pexpect.spawn(parts[0], encoding="utf-8", timeout=timeout)
    return pexpect.spawn(parts[0], parts[1:], encoding="utf-8", timeout=timeout)


def _import_pexpect():
    try:
        import pexpect  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError(PEXPECT_INSTALL_HINT) from e
    return pexpect


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 40] + "\n... (truncated by Governor)"


def _strip_echoed_prompt(before: str, prompt: str) -> str:
    """Remove terminal echo of the sent prompt from captured output."""
    text = before.strip()
    if not text:
        return ""
    prompt_norm = prompt.strip("\n").strip()
    if not prompt_norm:
        return text
    if text.startswith(prompt_norm):
        return text[len(prompt_norm) :].lstrip("\n").strip()
    prompt_lines = prompt_norm.splitlines()
    out_lines = text.splitlines()
    matched = 0
    for i, pline in enumerate(prompt_lines):
        if i >= len(out_lines) or out_lines[i].strip() != pline.strip():
            break
        matched += 1
    if matched:
        return "\n".join(out_lines[matched:]).strip()
    last_line = prompt_lines[-1]
    if out_lines and out_lines[0].strip() == last_line.strip():
        return "\n".join(out_lines[1:]).strip()
    return text


def _close_child(child, *, send_interrupt: bool = True) -> None:
    if child is None:
        return
    pexpect = _import_pexpect()
    try:
        if send_interrupt and child.isalive():
            child.sendcontrol("c")
            try:
                child.expect(pexpect.EOF, timeout=2)
            except Exception:
                pass
    except Exception:
        pass
    try:
        if child.isalive():
            child.close(force=True)
    except Exception:
        pass


def run_chatbang_with_session_prime(
    prompt: str,
    *,
    session_prime: str,
    command: str = "chatbang",
    timeout: int = 180,
    prompt_pattern: str = "> ",
    max_output_chars: int = 20000,
) -> ChatbangResult:
    """Prime chatbang session (one line), then send the main prompt; return second response."""
    pexpect = _import_pexpect()
    start = time.monotonic()
    child = None
    prime_line = session_prime.strip().splitlines()[-1] if session_prime.strip() else ""
    try:
        child = _spawn_process(pexpect, command, timeout)
        child.expect(prompt_pattern, timeout=timeout)
        child.sendline(prime_line)
        child.expect(prompt_pattern, timeout=timeout)
        if "\n" in prompt.rstrip("\n"):
            child.send(prompt if prompt.endswith("\n") else prompt + "\n")
        else:
            child.sendline(prompt.strip())
        child.expect(prompt_pattern, timeout=timeout)
        raw = child.before or ""
        for chunk in (prompt, prime_line):
            if chunk:
                raw = _strip_echoed_prompt(raw, chunk)
        output = redact(_truncate(raw.strip(), max_output_chars))
        _close_child(child)
        duration = time.monotonic() - start
        return ChatbangResult(
            ok=bool(output.strip()),
            output=output,
            duration_seconds=duration,
            exit_status=None,
        )
    except pexpect.TIMEOUT:
        duration = time.monotonic() - start
        _close_child(child)
        return ChatbangResult(
            ok=False,
            output="",
            duration_seconds=duration,
            timed_out=True,
            error="chatbang timed out (session prime + propose)",
        )
    except Exception as e:
        duration = time.monotonic() - start
        _close_child(child)
        return ChatbangResult(
            ok=False,
            output="",
            duration_seconds=duration,
            error=str(e),
        )


def run_chatbang_once(
    prompt: str,
    *,
    command: str = "chatbang",
    timeout: int = 180,
    prompt_pattern: str = "> ",
    max_output_chars: int = 20000,
) -> ChatbangResult:
    """Send one prompt to interactive chatbang and capture response before next prompt."""
    pexpect = _import_pexpect()
    start = time.monotonic()
    child = None
    try:
        child = _spawn_process(pexpect, command, timeout)
        child.expect(prompt_pattern, timeout=timeout)
        if "\n" in prompt.rstrip("\n"):
            child.send(prompt if prompt.endswith("\n") else prompt + "\n")
        else:
            child.sendline(prompt.strip())
        child.expect(prompt_pattern, timeout=timeout)
        raw = child.before or ""
        output = redact(
            _truncate(_strip_echoed_prompt(raw, prompt), max_output_chars)
        )
        exit_status = child.exitstatus if not child.isalive() else None
        _close_child(child)
        duration = time.monotonic() - start
        ok = bool(output.strip())
        return ChatbangResult(
            ok=ok,
            output=output,
            duration_seconds=duration,
            exit_status=exit_status,
        )
    except pexpect.TIMEOUT:
        duration = time.monotonic() - start
        _close_child(child)
        return ChatbangResult(
            ok=False,
            output="",
            duration_seconds=duration,
            timed_out=True,
            error="chatbang session timed out",
        )
    except Exception as e:
        duration = time.monotonic() - start
        _close_child(child)
        return ChatbangResult(
            ok=False,
            output="",
            duration_seconds=duration,
            error=redact(str(e)),
        )


def is_chatbang_available(command: str = "chatbang") -> bool:
    if not shutil.which(command):
        return False
    try:
        _import_pexpect()
    except ImportError:
        return False
    return True


def probe_chatbang(command: str = "chatbang", timeout: int = 60) -> ChatbangResult:
    """Harmless probe: expect CHATBANG_OK or non-empty coherent output."""
    probe_prompt = "Reply with exactly: CHATBANG_OK"
    result = run_chatbang_once(
        probe_prompt,
        command=command,
        timeout=timeout,
        max_output_chars=5000,
    )
    if result.timed_out or result.error:
        return result
    out = result.output.upper()
    if "CHATBANG_OK" in out:
        return ChatbangResult(
            ok=True,
            output=result.output,
            duration_seconds=result.duration_seconds,
            exit_status=result.exit_status,
        )
    if len(result.output.strip()) >= 3:
        return ChatbangResult(
            ok=True,
            output=result.output,
            duration_seconds=result.duration_seconds,
            exit_status=result.exit_status,
        )
    return ChatbangResult(
        ok=False,
        output=result.output,
        duration_seconds=result.duration_seconds,
        error="probe returned empty or unusable output",
    )
