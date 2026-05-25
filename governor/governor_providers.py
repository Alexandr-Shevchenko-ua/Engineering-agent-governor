"""Governor Mode proposal providers (chatbang, cursor-auto)."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from governor.chatbang_bridge import run_chatbang_once, run_chatbang_with_session_prime
from governor.config import ProfileSpec, check_secret_argv, config_path, get_profile, load_profiles
from governor.dispatch import run_command
from governor.redaction import redact

PROVIDER_CHATBANG = "chatbang"
PROVIDER_CURSOR_AUTO = "cursor-auto"

GOVERNOR_SESSION_PRIME = (
    "GOVERNOR_MODE: New proposal task. Ignore prior advisor/VERDICT chat. "
    "Acknowledge with exactly: GOVERNOR_MODE_OK"
)
GOVERNOR_PROVIDERS = frozenset({PROVIDER_CHATBANG, PROVIDER_CURSOR_AUTO})

DEFAULT_CURSOR_GOVERNOR_PROFILE = "cursor-governor-auto"
CURSOR_GOVERNOR_MAX_TIMEOUT = 1800

SAFETY_FLAG_PROVIDER_FAILED = "PROVIDER_FAILED"
SAFETY_FLAG_CURSOR_GOVERNOR = "CURSOR_GOVERNOR_PROVIDER"
SAFETY_FLAG_READ_ONLY_PROVIDER = "READ_ONLY_PROVIDER"
SAFETY_FLAG_WRITE_CAPABLE_BLOCKED = "WRITE_CAPABLE_PROVIDER_BLOCKED"
SAFETY_FLAG_DISABLED_PROFILE_ALLOWED = "DISABLED_PROFILE_ALLOWED"

_APPLY_BLOCKING_FLAGS = frozenset(
    {
        SAFETY_FLAG_PROVIDER_FAILED,
        SAFETY_FLAG_WRITE_CAPABLE_BLOCKED,
    }
)


@dataclass
class ProviderInvokeResult:
    ok: bool
    output: str
    exit_code: int | None = None
    error: str | None = None
    timed_out: bool = False
    provider_profile: str | None = None
    provider_model: str | None = None
    provider_mode: str | None = None


class GovernorProvider(Protocol):
    name: str

    def invoke(
        self,
        prompt_text: str,
        *,
        repo_path: Path,
        options: dict[str, Any],
    ) -> ProviderInvokeResult: ...


def validate_provider_name(name: str) -> str:
    if name not in GOVERNOR_PROVIDERS:
        known = ", ".join(sorted(GOVERNOR_PROVIDERS))
        raise ValueError(f"Unknown provider {name!r}. Known: {known}")
    return name


def argv_has_ask_mode(argv: list[str]) -> bool:
    parts = [a.lower() for a in argv]
    if "ask" in parts:
        idx = parts.index("ask")
        if idx > 0 and parts[idx - 1] in ("--mode", "-m"):
            return True
    joined = " ".join(argv).lower()
    return "--mode ask" in joined or " --mode=ask" in joined


def argv_looks_write_capable(argv: list[str]) -> bool:
    if argv_has_ask_mode(argv):
        return False
    joined = " ".join(argv).lower()
    write_markers = (
        "--mode write",
        "--mode=write",
        "--mode edit",
        "--mode=edit",
        " --mode write",
    )
    return any(m in joined for m in write_markers)


def extract_model_from_argv(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--model" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--model="):
            return arg.split("=", 1)[1]
    return None


def validate_cursor_governor_profile(
    profile: ProfileSpec,
    *,
    allow_disabled: bool = False,
    allow_write_capable: bool = False,
) -> list[str]:
    """Return safety flags / issues; raises ValueError on hard failures."""
    flags: list[str] = []
    if profile.runner != "command":
        raise ValueError(
            f"Profile {profile.name!r} must use runner 'command' for cursor-auto Governor provider"
        )
    if not profile.argv:
        raise ValueError(
            f"Profile {profile.name!r} has empty argv — fill locally (see docs/CURSOR_GOVERNOR_PROVIDER.md)"
        )
    check_secret_argv(profile.argv)
    joined = " ".join(profile.argv).lower()
    for frag in ("git push", "git merge", "deploy", "kubectl apply"):
        if frag in joined:
            raise ValueError(f"Profile argv must not contain destructive fragment: {frag}")
    if argv_looks_write_capable(profile.argv) and not allow_write_capable:
        flags.append(SAFETY_FLAG_WRITE_CAPABLE_BLOCKED)
        raise ValueError(
            f"Profile {profile.name!r} argv lacks read-only ask mode (--mode ask). "
            "Governor provider must not write the repo."
        )
    if not argv_has_ask_mode(profile.argv):
        if allow_write_capable:
            flags.append(SAFETY_FLAG_WRITE_CAPABLE_BLOCKED)
        else:
            raise ValueError(
                f"Profile {profile.name!r} must include --mode ask for cursor-auto Governor provider"
            )
    flags.append(SAFETY_FLAG_CURSOR_GOVERNOR)
    flags.append(SAFETY_FLAG_READ_ONLY_PROVIDER)
    return flags


def resolve_cursor_governor_profile(
    repo_path: Path,
    profile_name: str,
    *,
    allow_disabled: bool = False,
    allow_write_capable: bool = False,
) -> ProfileSpec:
    profiles = load_profiles(config_path(repo_path))
    if profile_name not in profiles:
        raise ValueError(
            f"Profile {profile_name!r} not found in {config_path(repo_path)}. "
            "Run: python -m governor config init --repo-path ."
        )
    spec = profiles[profile_name]
    if not spec.enabled and not allow_disabled:
        raise ValueError(
            f"Profile {profile_name!r} is disabled. Enable in .governor/config.json or use "
            "--allow-disabled-profile (discouraged)."
        )
    validate_cursor_governor_profile(
        spec,
        allow_disabled=allow_disabled,
        allow_write_capable=allow_write_capable,
    )
    return spec


@dataclass
class ChatbangProviderOptions:
    command: str = "chatbang"
    timeout: int = 300
    max_output_chars: int = 30_000
    session_prime: str = ""


class ChatbangGovernorProvider:
    name = PROVIDER_CHATBANG

    def invoke(
        self,
        prompt_text: str,
        *,
        repo_path: Path,
        options: dict[str, Any],
    ) -> ProviderInvokeResult:
        opts = options
        command = str(opts.get("command", "chatbang"))
        timeout = int(opts.get("timeout", 300))
        max_chars = int(opts.get("max_output_chars", 30_000))
        session_prime = str(opts.get("session_prime", ""))
        use_prime = "fake_chatbang" in command or command.strip() == "chatbang"
        if use_prime and session_prime:
            result = run_chatbang_with_session_prime(
                prompt_text,
                session_prime=session_prime,
                command=command,
                timeout=timeout,
                max_output_chars=max_chars,
            )
        else:
            result = run_chatbang_once(
                prompt_text,
                command=command,
                timeout=timeout,
                max_output_chars=max_chars,
            )
        if result.timed_out:
            return ProviderInvokeResult(
                ok=False,
                output="",
                error=result.error or "chatbang timed out",
                timed_out=True,
            )
        if not result.ok:
            return ProviderInvokeResult(
                ok=False,
                output=result.output or "",
                error=result.error,
                exit_code=result.exit_status,
            )
        return ProviderInvokeResult(ok=True, output=result.output, exit_code=result.exit_status)


@dataclass
class CursorAutoProviderOptions:
    profile_name: str = DEFAULT_CURSOR_GOVERNOR_PROFILE
    timeout: int = 900
    allow_disabled_profile: bool = False
    allow_write_capable: bool = False


class CursorAutoGovernorProvider:
    name = PROVIDER_CURSOR_AUTO

    def invoke(
        self,
        prompt_text: str,
        *,
        repo_path: Path,
        options: dict[str, Any],
    ) -> ProviderInvokeResult:
        profile_name = str(options.get("profile_name", DEFAULT_CURSOR_GOVERNOR_PROFILE))
        timeout = min(max(int(options.get("timeout", 900)), 30), CURSOR_GOVERNOR_MAX_TIMEOUT)
        allow_disabled = bool(options.get("allow_disabled_profile", False))
        allow_write = bool(options.get("allow_write_capable", False))
        try:
            spec = resolve_cursor_governor_profile(
                repo_path,
                profile_name,
                allow_disabled=allow_disabled,
                allow_write_capable=allow_write,
            )
        except ValueError as e:
            return ProviderInvokeResult(
                ok=False,
                output="",
                error=str(e),
                exit_code=2,
            )
        dispatch = run_command(spec.argv, prompt_text, repo_path, spec.timeout or timeout)
        out = redact((dispatch.stdout or "") + ("\n" + dispatch.stderr if dispatch.stderr else ""))
        model = extract_model_from_argv(spec.argv)
        mode = "ask/read-only" if argv_has_ask_mode(spec.argv) else "unknown"
        if dispatch.exit_code != 0:
            body = out or dispatch.stderr or f"exit {dispatch.exit_code}"
            return ProviderInvokeResult(
                ok=False,
                output=body,
                exit_code=dispatch.exit_code,
                error=f"cursor-auto provider exit {dispatch.exit_code}",
                provider_profile=profile_name,
                provider_model=model,
                provider_mode=mode,
            )
        return ProviderInvokeResult(
            ok=True,
            output=out.strip(),
            exit_code=0,
            provider_profile=profile_name,
            provider_model=model,
            provider_mode=mode,
        )


def get_governor_provider(name: str) -> GovernorProvider:
    validate_provider_name(name)
    if name == PROVIDER_CHATBANG:
        return ChatbangGovernorProvider()
    return CursorAutoGovernorProvider()


def format_provider_command_display(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)
