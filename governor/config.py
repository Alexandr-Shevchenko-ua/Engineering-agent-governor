"""Local runner profiles in .governor/config.json (ignored by git)."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from governor.dispatch import (
    DEFAULT_TIMEOUT,
    MAX_TIMEOUT,
    RunnerSpec,
    build_runner_spec,
    check_command_argv,
)
from governor.redaction import redact
from governor.utils import governor_root, resolve_repo_path

CONFIG_FILENAME = "config.json"
CONFIG_VERSION = 1
PROFILE_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
ALLOWED_RUNNERS = frozenset({"echo", "command", "cursor"})

CONFIG_NOT_FOUND_MSG = (
    "Config not found. Run: python -m governor config init --repo-path ."
)

_SECRET_ARG_RE = re.compile(
    r"(?i)(?:"
    r"bearer\s+|"
    r"api[_-]?key\s*[=:]|"
    r"password\s*[=:]|"
    r"secret\s*[=:]|"
    r"token\s*[=:]|"
    r"\bsk-[a-zA-Z0-9]{20,}\b|"
    r"\bghp_[a-zA-Z0-9]{36,}\b|"
    r"\bglpat-[a-zA-Z0-9\-_]{20,}\b"
    r")"
)


@dataclass
class ProfileSpec:
    name: str
    runner: str
    description: str
    argv: list[str]
    timeout: int
    enabled: bool


@dataclass
class ValidationLine:
    level: str  # OK | WARN | FAIL
    message: str


def config_path(repo_path: Path) -> Path:
    return governor_root(repo_path) / CONFIG_FILENAME


def validate_profile_name(name: str) -> str:
    if not name or not isinstance(name, str):
        raise ValueError("Profile name must be a non-empty string")
    if "/" in name or "\\" in name or ".." in name or " " in name:
        raise ValueError(f"Invalid profile name: {name!r}")
    if not PROFILE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid profile name: {name!r} "
            "(use lowercase letters, digits, hyphen, underscore)"
        )
    return name


def check_secret_argv(argv: list[str]) -> None:
    joined = " ".join(argv)
    if _SECRET_ARG_RE.search(joined):
        raise ValueError(
            "Refusing argv that looks secret-like (tokens, API keys, Bearer, password=, secret=)"
        )


def default_config_dict(repo_path: Path) -> dict[str, Any]:
    fake_script = repo_path / "scripts" / "fake_agent.py"
    profiles: dict[str, Any] = {
        "echo-test": {
            "runner": "echo",
            "description": "Safe builtin echo runner",
            "timeout": DEFAULT_TIMEOUT,
            "enabled": True,
        },
        "fake-validator": {
            "runner": "command",
            "description": "Local fake validator for smoke tests",
            "argv": ["python", "scripts/fake_agent.py"],
            "timeout": DEFAULT_TIMEOUT,
            "enabled": True,
        },
        "cursor-local": {
            "runner": "command",
            "description": (
                "Legacy placeholder — prefer cursor-headless-local for executor runs."
            ),
            "argv": [],
            "timeout": 900,
            "enabled": False,
        },
        "cursor-headless-local": {
            "runner": "command",
            "description": (
                "Cursor Headless CLI executor. Fill argv locally after verifying "
                "Cursor CLI syntax; Governor does not ship personal paths."
            ),
            "argv": [],
            "timeout": 1800,
            "enabled": False,
        },
        "chatbang-local": {
            "runner": "command",
            "description": (
                "Not recommended as executor — use governor advisor ask for chatbang."
            ),
            "argv": [],
            "timeout": 900,
            "enabled": False,
        },
        "claude-local": {
            "runner": "command",
            "description": (
                "User-configured local CLI profile. Fill argv locally; keep secrets out of argv."
            ),
            "argv": [],
            "timeout": 900,
            "enabled": False,
        },
    }
    if not fake_script.is_file():
        profiles["fake-validator"]["description"] = (
            "Local fake validator (scripts/fake_agent.py not found in repo; "
            "fix path or disable before use)"
        )
    return {"version": CONFIG_VERSION, "profiles": profiles}


def write_default_config(path: Path, repo_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = default_config_dict(repo_path)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_config_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(CONFIG_NOT_FOUND_MSG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object")
    return data


def parse_profile(name: str, raw: Any) -> ProfileSpec:
    validate_profile_name(name)
    if not isinstance(raw, dict):
        raise ValueError(f"Profile {name!r} must be an object")
    runner = raw.get("runner")
    if runner not in ALLOWED_RUNNERS:
        raise ValueError(
            f"Profile {name!r}: runner must be one of {sorted(ALLOWED_RUNNERS)}"
        )
    description = raw.get("description") or ""
    if not isinstance(description, str):
        raise ValueError(f"Profile {name!r}: description must be a string")
    argv_raw = raw.get("argv", [])
    if argv_raw is None:
        argv_raw = []
    if not isinstance(argv_raw, list) or not all(isinstance(a, str) for a in argv_raw):
        raise ValueError(f"Profile {name!r}: argv must be a list of strings")
    argv = list(argv_raw)
    timeout = raw.get("timeout", DEFAULT_TIMEOUT)
    if not isinstance(timeout, int) or timeout < 1 or timeout > MAX_TIMEOUT:
        raise ValueError(
            f"Profile {name!r}: timeout must be integer 1..{MAX_TIMEOUT}"
        )
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"Profile {name!r}: enabled must be boolean")
    return ProfileSpec(
        name=name,
        runner=runner,
        description=description,
        argv=argv,
        timeout=timeout,
        enabled=enabled,
    )


def load_profiles(path: Path) -> dict[str, ProfileSpec]:
    data = load_config_file(path)
    version = data.get("version")
    if version != CONFIG_VERSION:
        raise ValueError(f"Config version must be {CONFIG_VERSION}, got {version!r}")
    profiles_raw = data.get("profiles")
    if not isinstance(profiles_raw, dict):
        raise ValueError("Config profiles must be an object")
    return {name: parse_profile(name, raw) for name, raw in profiles_raw.items()}


def _validate_profile_semantics(
    profile: ProfileSpec,
    repo_path: Path,
    *,
    strict: bool,
) -> list[ValidationLine]:
    lines: list[ValidationLine] = []
    if not profile.enabled:
        lines.append(
            ValidationLine("WARN", f"{profile.name}: profile is disabled")
        )
        if profile.runner == "command" and not profile.argv:
            lines.append(
                ValidationLine(
                    "WARN",
                    f"{profile.name}: disabled command profile with empty argv",
                )
            )
            return lines
    if profile.runner == "echo" and profile.argv:
        lines.append(
            ValidationLine("WARN", f"{profile.name}: echo runner ignores argv")
        )
    if profile.runner == "cursor":
        lines.append(
            ValidationLine(
                "WARN",
                f"{profile.name}: cursor runner is a placeholder; prefer command + your argv",
            )
        )
    if profile.runner == "command":
        if profile.enabled and not profile.argv:
            lines.append(
                ValidationLine(
                    "FAIL",
                    f"{profile.name}: enabled command profile requires non-empty argv",
                )
            )
            return lines
        if not profile.enabled and not profile.argv:
            lines.append(
                ValidationLine(
                    "WARN",
                    f"{profile.name}: disabled command profile with empty argv",
                )
            )
            return lines
        try:
            check_secret_argv(profile.argv)
            check_command_argv(profile.argv)
        except ValueError as e:
            lines.append(ValidationLine("FAIL", f"{profile.name}: {e}"))
            return lines
        exe = profile.argv[0]
        if shutil.which(exe) is None and "/" not in exe and "\\" not in exe:
            resolved = repo_path / exe
            if not resolved.is_file():
                lines.append(
                    ValidationLine(
                        "WARN",
                        f"{profile.name}: executable not found on PATH: {exe!r}",
                    )
                )
        if len(profile.argv) >= 2:
            script = profile.argv[1]
            if script.startswith("scripts/") or script.startswith("./"):
                sp = repo_path / script
                if not sp.is_file():
                    lines.append(
                        ValidationLine(
                            "WARN",
                            f"{profile.name}: script path missing: {script}",
                        )
                    )
    if profile.name == "cursor-local" and not profile.enabled:
        lines.append(
            ValidationLine(
                "WARN",
                "cursor-local: disabled / not configured (expected until you fill argv)",
            )
        )
    if strict and profile.enabled:
        lines.append(ValidationLine("OK", f"{profile.name}: valid"))
    elif not strict:
        lines.append(ValidationLine("OK", f"{profile.name}: parsed"))
    return lines


def validate_config_file(
    path: Path,
    repo_path: Path,
) -> tuple[list[ValidationLine], bool]:
    """Return lines and whether config has any FAIL."""
    try:
        profiles = load_profiles(path)
    except (FileNotFoundError, ValueError) as e:
        return [ValidationLine("FAIL", str(e))], True
    if not profiles:
        return [ValidationLine("WARN", "No profiles defined")], False
    lines: list[ValidationLine] = []
    has_fail = False
    for profile in profiles.values():
        plines = _validate_profile_semantics(profile, repo_path, strict=True)
        lines.extend(plines)
        if any(p.level == "FAIL" for p in plines):
            has_fail = True
    if not has_fail:
        lines.insert(0, ValidationLine("OK", f"Config valid ({len(profiles)} profile(s))"))
    return lines, has_fail


def redact_argv_for_display(argv: list[str]) -> list[str]:
    out: list[str] = []
    for arg in argv:
        if _SECRET_ARG_RE.search(arg):
            out.append("[REDACTED]")
        else:
            out.append(redact(arg))
    return out


def resolve_profile_runner(
    profile: ProfileSpec,
    *,
    allow_disabled: bool = False,
) -> RunnerSpec:
    if not profile.enabled and not allow_disabled:
        raise ValueError(
            f"Profile {profile.name!r} is disabled. "
            f"Enable it in .governor/config.json or pass --allow-disabled-profile."
        )
    if profile.runner == "echo":
        return build_runner_spec("echo", None)
    if profile.runner == "cursor":
        return build_runner_spec("cursor", None)
    if profile.runner == "command":
        if not profile.argv:
            raise ValueError(
                f"Profile {profile.name!r} has empty argv; configure argv before dispatch"
            )
        check_secret_argv(profile.argv)
        return build_runner_spec("command", profile.argv)
    raise ValueError(f"Unknown runner for profile {profile.name!r}")


def get_profile(
    repo_path: Path,
    profile_name: str,
    *,
    allow_disabled: bool = False,
) -> tuple[ProfileSpec, RunnerSpec]:
    path = config_path(repo_path)
    profiles = load_profiles(path)
    validate_profile_name(profile_name)
    if profile_name not in profiles:
        names = ", ".join(sorted(profiles))
        raise ValueError(
            f"Unknown profile {profile_name!r}. Available: {names or '(none)'}"
        )
    profile = profiles[profile_name]
    spec = resolve_profile_runner(profile, allow_disabled=allow_disabled)
    return profile, spec


def init_config(repo_path: Path, *, force: bool = False) -> Path:
    path = config_path(repo_path)
    if path.exists() and not force:
        raise FileExistsError(f"Config already exists: {path} (use --force to overwrite)")
    write_default_config(path, repo_path)
    return path
