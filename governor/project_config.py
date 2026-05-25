"""Tracked repository governance config (governor.project.json)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from governor.policy import POLICY_NAMES

PROJECT_CONFIG_FILENAME = "governor.project.json"
PROJECT_CONFIG_VERSION = 1

PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|password|token|bearer|authorization\s*:)"
)
_ABSOLUTE_PATH_RE = re.compile(r"^(/|[A-Za-z]:\\|\.\./)")

BUILTIN_GATE_COMMANDS = frozenset(
    {
        "git_status_short",
        "git_diff_stat",
        "git_diff_check",
        "security_suspicious_files",
        "pytest",
        "ruff",
        "mypy",
        "npm_test",
        "smoke_governor",
        "smoke_dispatch",
        "smoke_profile",
        "smoke_repair",
        "smoke_plan",
        "smoke_resume_checkpoint_evidence",
        "smoke_policy",
        "smoke_governed_run",
        "smoke_all",
        "diff_budget",
        "sensitive_paths",
    }
)


@dataclass
class GateProfileSpec:
    description: str
    commands: list[str]
    required: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateProfileSpec:
        return cls(
            description=data.get("description", ""),
            commands=list(data.get("commands", [])),
            required=list(data.get("required", [])),
            optional=list(data.get("optional", [])),
        )


@dataclass
class DiffBudget:
    max_changed_files: int = 20
    max_lines_added: int = 1200
    max_lines_deleted: int = 800

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffBudget:
        return cls(
            max_changed_files=int(data.get("max_changed_files", 20)),
            max_lines_added=int(data.get("max_lines_added", 1200)),
            max_lines_deleted=int(data.get("max_lines_deleted", 800)),
        )


@dataclass
class ReviewPackageSettings:
    include_evidence: bool = True
    include_trace_summary: bool = True
    include_commands: bool = True
    include_policy_compliance: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewPackageSettings:
        return cls(
            include_evidence=data.get("include_evidence", True),
            include_trace_summary=data.get("include_trace_summary", True),
            include_commands=data.get("include_commands", True),
            include_policy_compliance=data.get("include_policy_compliance", True),
        )


@dataclass
class ProjectConfig:
    version: int
    project_name: str
    default_policy: str
    allowed_policies: list[str]
    default_gate_profile: str
    gate_profiles: dict[str, GateProfileSpec]
    diff_budget: DiffBudget
    sensitive_paths: list[str]
    review_package: ReviewPackageSettings

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project_name": self.project_name,
            "default_policy": self.default_policy,
            "allowed_policies": list(self.allowed_policies),
            "default_gate_profile": self.default_gate_profile,
            "gate_profiles": {
                name: {
                    "description": spec.description,
                    "commands": spec.commands,
                    "required": spec.required,
                    "optional": spec.optional,
                }
                for name, spec in self.gate_profiles.items()
            },
            "diff_budget": {
                "max_changed_files": self.diff_budget.max_changed_files,
                "max_lines_added": self.diff_budget.max_lines_added,
                "max_lines_deleted": self.diff_budget.max_lines_deleted,
            },
            "sensitive_paths": list(self.sensitive_paths),
            "review_package": {
                "include_evidence": self.review_package.include_evidence,
                "include_trace_summary": self.review_package.include_trace_summary,
                "include_commands": self.review_package.include_commands,
                "include_policy_compliance": self.review_package.include_policy_compliance,
            },
        }


@dataclass
class ProjectValidationLine:
    level: str
    message: str


def project_config_path(repo: Path) -> Path:
    return repo / PROJECT_CONFIG_FILENAME


def default_project_config_dict() -> dict[str, Any]:
    return {
        "version": PROJECT_CONFIG_VERSION,
        "project_name": "Engineering Agent Governor",
        "default_policy": "agentic-tooling",
        "allowed_policies": list(POLICY_NAMES),
        "default_gate_profile": "fast",
        "gate_profiles": {
            "fast": {
                "description": "Fast local validation",
                "commands": [
                    "git_status_short",
                    "git_diff_check",
                    "pytest",
                    "diff_budget",
                    "sensitive_paths",
                ],
                "required": ["git_diff_check", "pytest", "sensitive_paths"],
                "optional": ["ruff", "mypy", "git_status_short"],
            },
            "release": {
                "description": "Release validation",
                "commands": [
                    "git_status_short",
                    "git_diff_check",
                    "pytest",
                    "smoke_all",
                    "diff_budget",
                    "sensitive_paths",
                ],
                "required": ["git_diff_check", "pytest", "smoke_all", "sensitive_paths"],
                "optional": ["ruff", "mypy"],
            },
        },
        "diff_budget": {
            "max_changed_files": 20,
            "max_lines_added": 1200,
            "max_lines_deleted": 800,
        },
        "sensitive_paths": [
            ".env",
            ".governor/",
            "**/*secret*",
            "**/*token*",
            "**/*.pem",
        ],
        "review_package": {
            "include_evidence": True,
            "include_trace_summary": True,
            "include_commands": True,
            "include_policy_compliance": True,
        },
    }


def _is_glob_path_pattern(value: str) -> bool:
    """True for fnmatch-style path patterns (not credential values)."""
    return "*" in value or "?" in value or value.endswith("/")


def _check_no_secrets_in_value(path: str, value: Any) -> list[str]:
    errs: list[str] = []
    if isinstance(value, str):
        if not _is_glob_path_pattern(value) and _SECRET_RE.search(value):
            errs.append(f"{path}: secret-like string")
        if _ABSOLUTE_PATH_RE.match(value.strip()):
            errs.append(f"{path}: absolute path not allowed")
    elif isinstance(value, dict):
        for k, v in value.items():
            errs.extend(_check_no_secrets_in_value(f"{path}.{k}", v))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            errs.extend(_check_no_secrets_in_value(f"{path}[{i}]", item))
    return errs


def _validate_gate_profile_name(name: str) -> str | None:
    if not PROFILE_NAME_RE.match(name):
        return f"invalid gate profile name {name!r}"
    return None


def validate_project_data(data: dict[str, Any]) -> list[ProjectValidationLine]:
    lines: list[ProjectValidationLine] = []
    has_fail = False

    def fail(msg: str) -> None:
        nonlocal has_fail
        lines.append(ProjectValidationLine("FAIL", msg))
        has_fail = True

    def warn(msg: str) -> None:
        lines.append(ProjectValidationLine("WARN", msg))

    def ok(msg: str) -> None:
        lines.append(ProjectValidationLine("OK", msg))

    version = data.get("version")
    if version != PROJECT_CONFIG_VERSION:
        fail(f"version must be {PROJECT_CONFIG_VERSION}, got {version!r}")

    for err in _check_no_secrets_in_value("root", data):
        fail(err)

    default_policy = data.get("default_policy")
    allowed = data.get("allowed_policies", [])
    if not isinstance(allowed, list) or not allowed:
        fail("allowed_policies must be a non-empty list")
    else:
        for p in allowed:
            if p not in POLICY_NAMES:
                fail(f"allowed_policies contains unknown policy {p!r}")
        if default_policy and default_policy not in allowed:
            fail(f"default_policy {default_policy!r} not in allowed_policies")

    default_gp = data.get("default_gate_profile")
    gate_profiles = data.get("gate_profiles")
    if not isinstance(gate_profiles, dict) or not gate_profiles:
        fail("gate_profiles must be a non-empty object")
    else:
        for name, spec in gate_profiles.items():
            err = _validate_gate_profile_name(name)
            if err:
                fail(err)
            if not isinstance(spec, dict):
                fail(f"gate_profiles.{name} must be an object")
                continue
            for cmd in spec.get("commands", []):
                if cmd not in BUILTIN_GATE_COMMANDS:
                    fail(
                        f"gate_profiles.{name}: unknown command {cmd!r} "
                        f"(only built-in names allowed)"
                    )
            for cmd in spec.get("required", []):
                if cmd not in BUILTIN_GATE_COMMANDS:
                    fail(f"gate_profiles.{name}.required: unknown command {cmd!r}")
            for cmd in spec.get("optional", []):
                if cmd not in BUILTIN_GATE_COMMANDS:
                    fail(f"gate_profiles.{name}.optional: unknown command {cmd!r}")
        if default_gp and default_gp not in gate_profiles:
            fail(f"default_gate_profile {default_gp!r} not in gate_profiles")

    budget = data.get("diff_budget", {})
    if isinstance(budget, dict):
        for key in ("max_changed_files", "max_lines_added", "max_lines_deleted"):
            val = budget.get(key)
            if val is not None and (not isinstance(val, int) or val <= 0):
                fail(f"diff_budget.{key} must be a positive integer")

    for i, pat in enumerate(data.get("sensitive_paths", [])):
        if isinstance(pat, str) and _ABSOLUTE_PATH_RE.match(pat.strip()):
            fail(f"sensitive_paths[{i}]: absolute path pattern not allowed")

    if not has_fail:
        ok("Project config valid")
    return lines


def load_project_config(repo: Path) -> ProjectConfig:
    path = project_config_path(repo)
    if not path.is_file():
        raise FileNotFoundError(
            f"No project config at {path}. Run: python -m governor project init --repo-path ."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = validate_project_data(data)
    if any(l.level == "FAIL" for l in lines):
        msgs = "; ".join(l.message for l in lines if l.level == "FAIL")
        raise ValueError(f"Invalid {PROJECT_CONFIG_FILENAME}: {msgs}")
    return ProjectConfig(
        version=data["version"],
        project_name=data.get("project_name", ""),
        default_policy=data["default_policy"],
        allowed_policies=list(data["allowed_policies"]),
        default_gate_profile=data["default_gate_profile"],
        gate_profiles={
            k: GateProfileSpec.from_dict(v) for k, v in data["gate_profiles"].items()
        },
        diff_budget=DiffBudget.from_dict(data.get("diff_budget", {})),
        sensitive_paths=list(data.get("sensitive_paths", [])),
        review_package=ReviewPackageSettings.from_dict(data.get("review_package", {})),
    )


def load_project_config_optional(repo: Path) -> ProjectConfig | None:
    path = project_config_path(repo)
    if not path.is_file():
        return None
    return load_project_config(repo)


def init_project_config(repo: Path, *, force: bool = False) -> Path:
    path = project_config_path(repo)
    if path.exists() and not force:
        raise FileExistsError(
            f"{PROJECT_CONFIG_FILENAME} already exists at {path}. Use --force to overwrite."
        )
    data = default_project_config_dict()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def resolve_policy_for_repo(
    repo: Path,
    policy_arg: str | None,
) -> str:
    """Resolve policy from CLI arg and optional project config."""
    from governor.policy import resolve_policy_name

    cfg = load_project_config_optional(repo)
    if policy_arg:
        name = resolve_policy_name(policy_arg)
        if cfg and name not in cfg.allowed_policies:
            raise ValueError(
                f"Policy {name!r} not in allowed_policies: {cfg.allowed_policies}"
            )
        return name
    if cfg:
        return cfg.default_policy
    return resolve_policy_name(None)


def resolve_gate_profile_for_repo(
    repo: Path,
    profile_arg: str | None,
) -> str | None:
    cfg = load_project_config_optional(repo)
    if profile_arg:
        if not cfg:
            return profile_arg
        if profile_arg not in cfg.gate_profiles:
            raise ValueError(
                f"Gate profile {profile_arg!r} not in project config. "
                f"Available: {sorted(cfg.gate_profiles)}"
            )
        return profile_arg
    if cfg:
        return cfg.default_gate_profile
    return None
