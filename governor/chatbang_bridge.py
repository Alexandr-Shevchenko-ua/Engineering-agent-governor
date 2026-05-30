"""Interactive chatbang bridge via pexpect (Governor Advisor only — not executor)."""

from __future__ import annotations

import shlex
import shutil
import time
from dataclasses import dataclass
from governor.redaction import redact
from governor.utils import flatten_for_chatbang_line

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
    spawn_kw: dict = {
        "encoding": "utf-8",
        "codec_errors": "replace",
        "timeout": timeout,
    }
    if len(parts) == 1:
        return pexpect.spawn(parts[0], **spawn_kw)
    return pexpect.spawn(parts[0], parts[1:], **spawn_kw)


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


def _try_parse_json_dict(raw: str) -> dict | None:
    import json

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


def _spawn_error_from_buffer(buf: str) -> str | None:
    low = buf.lower()
    if "singletonlock" in low or "process_singleton" in low or "profile corruption" in low:
        return (
            "chatbang Chrome profile is locked (another chatbang/Chrome is running). "
            "Close all chatbang terminals and Chrome windows using ~/.config/chatbang/profile_data, "
            "then: pkill -f chatbang; retry collab."
        )
    if "chrome failed to start" in low:
        return "chatbang Chrome failed to start — see stderr above; fix browser path in ~/.config/chatbang/chatbang"
    return None


def _chatbang_response_ready(text: str) -> bool:
    """Enough of Chatbang reply to parse next_executor_prompt or a stop verdict."""
    if not text.strip():
        return False
    parsed = _try_parse_json_dict(text)
    if not parsed:
        return False
    if str(parsed.get("next_executor_prompt") or "").strip():
        return True
    verdict = str(parsed.get("verdict") or "").upper()
    return verdict in ("PASS", "HOLD", "FAIL")


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


class ChatbangPersistentSession:
    """Keep one pexpect child open across collab rounds (caller must close())."""

    def __init__(
        self,
        *,
        command: str = "chatbang",
        timeout: int = 180,
        prompt_pattern: str = "> ",
        max_output_chars: int = 20000,
    ) -> None:
        self.command = command
        self.timeout = timeout
        self.prompt_pattern = prompt_pattern
        self.max_output_chars = max_output_chars
        self._child = None
        self._primed = False

    def _chatbang_eof_hint(self, before: str = "") -> str:
        blob = (before or "").lower()
        if "profile corruption" in blob or "existing process" in blob:
            return (
                "chatbang exited: another chatbang session may be running. "
                "Close all chatbang terminals, then retry collab."
            )
        return (
            "chatbang exited before prompt (EOF). Close other chatbang instances "
            "or run: pkill -f chatbang"
        )

    def _ensure_child(self) -> ChatbangResult | None:
        """Spawn child if needed. Returns error result on failure, None on success."""
        if self._child is not None and self._child.isalive():
            return None
        pexpect = _import_pexpect()
        try:
            self._child = _spawn_process(pexpect, self.command, self.timeout)
            self._child.expect(self.prompt_pattern, timeout=self.timeout)
            boot = (self._child.before or "") + (getattr(self._child, "after", "") or "")
            spawn_err = _spawn_error_from_buffer(boot)
            if spawn_err:
                _close_child(self._child)
                self._child = None
                return ChatbangResult(
                    ok=False,
                    output=redact(boot.strip()),
                    duration_seconds=0.0,
                    error=spawn_err,
                )
            self._primed = False
            return None
        except pexpect.EOF:
            before = (self._child.before or "") if self._child is not None else ""
            _close_child(self._child)
            self._child = None
            return ChatbangResult(
                ok=False,
                output=redact(before.strip()),
                duration_seconds=0.0,
                error=self._chatbang_eof_hint(before),
            )
        except pexpect.TIMEOUT:
            _close_child(self._child)
            self._child = None
            return ChatbangResult(
                ok=False,
                output="",
                duration_seconds=0.0,
                timed_out=True,
                error="chatbang timed out waiting for first prompt (> )",
            )

    def prime(self, session_prime: str) -> ChatbangResult:
        spawn_err = self._ensure_child()
        if spawn_err is not None:
            return spawn_err
        if self._primed:
            return ChatbangResult(ok=True, output="", duration_seconds=0.0)
        prime_line = session_prime.strip().splitlines()[-1] if session_prime.strip() else ""
        start = time.monotonic()
        pexpect = _import_pexpect()
        try:
            self._child.sendline(prime_line)
            self._child.expect(self.prompt_pattern, timeout=self.timeout)
            raw = self._child.before or ""
            raw = _strip_echoed_prompt(raw, prime_line)
            self._primed = True
            return ChatbangResult(
                ok=True,
                output=redact(_truncate(raw.strip(), self.max_output_chars)),
                duration_seconds=time.monotonic() - start,
            )
        except pexpect.EOF:
            before = self._child.before or ""
            _close_child(self._child)
            self._child = None
            return ChatbangResult(
                ok=False,
                output=redact(before.strip()),
                duration_seconds=time.monotonic() - start,
                error=self._chatbang_eof_hint(before),
            )
        except pexpect.TIMEOUT:
            _close_child(self._child)
            self._child = None
            return ChatbangResult(
                ok=False,
                output="",
                duration_seconds=time.monotonic() - start,
                timed_out=True,
                error="chatbang session prime timed out",
            )

    def send(
        self,
        prompt: str,
        *,
        single_line: bool = False,
        wait_for_json: bool = False,
    ) -> ChatbangResult:
        spawn_err = self._ensure_child()
        if spawn_err is not None:
            return spawn_err
        start = time.monotonic()
        pexpect = _import_pexpect()
        payload = flatten_for_chatbang_line(prompt) if single_line else prompt
        try:
            if single_line or "\n" not in payload.rstrip("\n"):
                self._child.sendline(payload.strip())
            else:
                blob = payload if payload.endswith("\n") else payload + "\n"
                self._child.send(blob)

            chunks: list[str] = []
            deadline = start + self.timeout
            saw_substantial = False
            while time.monotonic() < deadline:
                slice_timeout = min(90.0, max(5.0, deadline - time.monotonic()))
                try:
                    self._child.expect(self.prompt_pattern, timeout=slice_timeout)
                except pexpect.TIMEOUT:
                    if saw_substantial or chunks:
                        break
                    return ChatbangResult(
                        ok=False,
                        output=redact("".join(chunks).strip()),
                        duration_seconds=time.monotonic() - start,
                        timed_out=True,
                        error=(
                            "chatbang timed out waiting for model reply "
                            f"(>{int(self.timeout)}s). Is Chrome/chatbang running?"
                        ),
                    )
                piece = self._child.before or ""
                if piece.strip():
                    chunks.append(piece)
                    if len(piece.strip()) > 60:
                        saw_substantial = True
                combined = _strip_echoed_prompt("".join(chunks), payload)
                spawn_err = _spawn_error_from_buffer(combined)
                if spawn_err:
                    return ChatbangResult(
                        ok=False,
                        output=redact(combined.strip()),
                        duration_seconds=time.monotonic() - start,
                        error=spawn_err,
                    )
                if wait_for_json:
                    if _chatbang_response_ready(combined):
                        break
                    continue
                if saw_substantial:
                    break

            raw = _strip_echoed_prompt("".join(chunks), payload)
            output = redact(_truncate(raw.strip(), self.max_output_chars))
            err: str | None = None
            if not output.strip():
                err = (
                    "empty chatbang reply (check Chrome profile lock or increase --chatbang-timeout)"
                )
            return ChatbangResult(
                ok=bool(output.strip()),
                output=output,
                duration_seconds=time.monotonic() - start,
                error=err,
            )
        except pexpect.EOF:
            before = self._child.before or ""
            _close_child(self._child)
            self._child = None
            return ChatbangResult(
                ok=False,
                output=redact(before.strip()),
                duration_seconds=time.monotonic() - start,
                error=self._chatbang_eof_hint(before),
            )
        except pexpect.TIMEOUT:
            return ChatbangResult(
                ok=False,
                output="",
                duration_seconds=time.monotonic() - start,
                timed_out=True,
                error="chatbang collab round timed out",
            )

    def close(self) -> None:
        _close_child(self._child)
        self._child = None
        self._primed = False


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
