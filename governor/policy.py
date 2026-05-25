"""Built-in policy packs for task intake, plans, and evidence expectations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from governor.redaction import REDACTION_WARNING

POLICY_NAMES = (
    "default",
    "bugfix",
    "refactor",
    "docs",
    "test-only",
    "release",
    "agentic-tooling",
)


@dataclass
class PlanDefaults:
    auto_repair_prepare_on_fail: bool = False
    max_steps: int = 10
    checkpoints: list[tuple[str, str]] = field(default_factory=list)
    recommend_evidence_export: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_repair_prepare_on_fail": self.auto_repair_prepare_on_fail,
            "max_steps": self.max_steps,
            "checkpoints": [{"after": a, "message": m} for a, m in self.checkpoints],
            "recommend_evidence_export": self.recommend_evidence_export,
        }


@dataclass
class PolicyPack:
    name: str
    description: str
    required_artifacts: list[str] = field(default_factory=list)
    recommended_gates: list[str] = field(default_factory=list)
    default_checkpoints: list[tuple[str, str]] = field(default_factory=list)
    risk_prompts: list[str] = field(default_factory=list)
    evidence_expectations: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    max_repair_prompts: int = 2
    plan_defaults: PlanDefaults = field(default_factory=PlanDefaults)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["plan_defaults"] = self.plan_defaults.to_dict()
        return d


def _pack(
    name: str,
    description: str,
    *,
    required_artifacts: list[str] | None = None,
    recommended_gates: list[str] | None = None,
    default_checkpoints: list[tuple[str, str]] | None = None,
    risk_prompts: list[str] | None = None,
    evidence_expectations: list[str] | None = None,
    stop_conditions: list[str] | None = None,
    max_repair_prompts: int = 2,
    plan_defaults: PlanDefaults | None = None,
) -> PolicyPack:
    return PolicyPack(
        name=name,
        description=description,
        required_artifacts=required_artifacts or [],
        recommended_gates=recommended_gates or ["git_status", "git_diff", "security_scan"],
        default_checkpoints=default_checkpoints or [],
        risk_prompts=risk_prompts or [],
        evidence_expectations=evidence_expectations or [],
        stop_conditions=stop_conditions or [],
        max_repair_prompts=max_repair_prompts,
        plan_defaults=plan_defaults or PlanDefaults(),
    )


_BUILTIN: dict[str, PolicyPack] = {}


def _register(p: PolicyPack) -> None:
    _BUILTIN[p.name] = p


_register(
    _pack(
        "default",
        "General engineering task with balanced scope, gates, and validator rigor.",
        required_artifacts=[
            "00_task_intake.md",
            "01_scope_and_assumptions.md",
            "02_risk_register.md",
            "03_executor_prompt.md",
            "04_validator_prompt.md",
        ],
        evidence_expectations=[
            "Executor output recorded",
            "Gate results present",
            "Validator verdict recorded",
        ],
        stop_conditions=[
            "Gate overall FAIL without repair plan",
            "Validator REPAIR_REQUIRED without follow-up",
        ],
    )
)

_register(
    _pack(
        "bugfix",
        "Minimal fix for a defect; prove regression with tests before/after.",
        required_artifacts=[
            "00_task_intake.md",
            "01_scope_and_assumptions.md",
            "02_risk_register.md",
            "03_executor_prompt.md",
            "04_validator_prompt.md",
            "05_executor_output.md",
            "08_gate_results.json",
            "06_validator_output.md",
        ],
        default_checkpoints=[
            ("gate", "Review gate results and failing-test context before validator"),
        ],
        risk_prompts=[
            "Fix may mask symptom instead of root cause",
            "Regression test missing or too narrow",
        ],
        evidence_expectations=[
            "Failing test or reproduction steps documented",
            "Before/after test evidence in executor output",
            "Root cause named in validator output",
            "Minimal diff — no drive-by refactors",
        ],
        stop_conditions=[
            "No reproduction or failing test evidence",
            "Validator cannot confirm root cause",
            "Gate FAIL on security or broad unrelated diff",
        ],
        plan_defaults=PlanDefaults(
            auto_repair_prepare_on_fail=True,
            checkpoints=[("gate", "Review gate and regression context before validator")],
        ),
    )
)

_register(
    _pack(
        "refactor",
        "Structural change with explicit no-behavior-change requirement.",
        required_artifacts=[
            "00_task_intake.md",
            "01_scope_and_assumptions.md",
            "02_risk_register.md",
            "03_executor_prompt.md",
            "04_validator_prompt.md",
        ],
        default_checkpoints=[("gate", "Confirm diff sprawl and public API unchanged")],
        risk_prompts=[
            "Hidden behavior change via renamed symbols",
            "Diff sprawl beyond stated refactor boundary",
        ],
        evidence_expectations=[
            "Explicit no-behavior-change statement",
            "Public API surface unchanged unless approved",
            "Tests still pass with same assertions",
        ],
        stop_conditions=[
            "New features mixed into refactor",
            "Public API break without lead approval",
        ],
        plan_defaults=PlanDefaults(
            checkpoints=[("gate", "Review diff sprawl and API stability before validator")],
        ),
    )
)

_register(
    _pack(
        "docs",
        "Documentation-only changes; accuracy and examples over code gates.",
        required_artifacts=[
            "00_task_intake.md",
            "01_scope_and_assumptions.md",
            "03_executor_prompt.md",
            "04_validator_prompt.md",
        ],
        recommended_gates=["git_status", "git_diff"],
        risk_prompts=[
            "Stale commands or wrong paths in docs",
            "Examples that do not run",
        ],
        evidence_expectations=[
            "No product code changes unless necessary for doc build",
            "Validator confirms accuracy and working examples",
            "Links and version references updated",
        ],
        stop_conditions=[
            "Undocumented code behavior changes",
            "Examples contradict current CLI/API",
        ],
        plan_defaults=PlanDefaults(max_steps=8),
    )
)

_register(
    _pack(
        "test-only",
        "Add or improve tests; avoid product code unless strictly required.",
        required_artifacts=[
            "00_task_intake.md",
            "01_scope_and_assumptions.md",
            "03_executor_prompt.md",
            "04_validator_prompt.md",
        ],
        risk_prompts=[
            "Brittle tests tied to implementation details",
            "Product code changed without justification",
        ],
        evidence_expectations=[
            "Tests map to acceptance criteria",
            "No unnecessary production code edits",
            "Validator checks relevance and stability",
        ],
        stop_conditions=[
            "Production code changed without documented need",
            "Flaky or over-mocked tests",
        ],
        plan_defaults=PlanDefaults(max_steps=8),
    )
)

_register(
    _pack(
        "release",
        "Version bump, changelog, checklist, and smoke validation.",
        required_artifacts=[
            "00_task_intake.md",
            "01_scope_and_assumptions.md",
            "03_executor_prompt.md",
            "04_validator_prompt.md",
        ],
        default_checkpoints=[
            ("validator", "Release checklist and version bump reviewed"),
            ("report", "Confirm version, changelog, and smoke before closure"),
        ],
        risk_prompts=[
            "Version mismatch across pyproject and __init__",
            "Missing smoke or release checklist items",
        ],
        evidence_expectations=[
            "Version bumped consistently",
            "Changelog or release notes updated",
            "Smoke scripts run and recorded",
        ],
        stop_conditions=[
            "Version not bumped where required",
            "Smoke failures not addressed",
        ],
        plan_defaults=PlanDefaults(
            checkpoints=[
                ("validator", "Review release checklist and version files"),
                ("report", "Human sign-off on release artifacts before report"),
            ],
            max_steps=12,
        ),
    )
)

_register(
    _pack(
        "agentic-tooling",
        "Governor/agent harness changes; guard against autopilot and secret leakage.",
        required_artifacts=[
            "00_task_intake.md",
            "01_scope_and_assumptions.md",
            "02_risk_register.md",
            "03_executor_prompt.md",
            "04_validator_prompt.md",
        ],
        default_checkpoints=[("gate", "Review for autopilot creep and secret patterns")],
        risk_prompts=[
            "Background execution or repair loops introduced",
            "Hardcoded vendor CLI syntax",
            "Secrets in config or artifacts",
        ],
        evidence_expectations=[
            "No merge/push/deploy automation added",
            "No external LLM API calls in governor core",
            "`.governor` remains gitignored",
            "Explicit --approve preserved for dispatch",
        ],
        stop_conditions=[
            "Autopilot or background daemon detected in diff",
            "Secret-like strings in committed config examples",
            "Cursor/Claude CLI syntax hardcoded in core",
        ],
        plan_defaults=PlanDefaults(
            checkpoints=[("gate", "Confirm no autopilot/background/secret leakage")],
        ),
    )
)


def list_policies() -> list[str]:
    return list(POLICY_NAMES)


def get_policy(name: str) -> PolicyPack:
    key = name.strip().lower()
    if key not in _BUILTIN:
        known = ", ".join(POLICY_NAMES)
        raise ValueError(f"Unknown policy {name!r}. Known policies: {known}")
    return _BUILTIN[key]


def resolve_policy_name(name: str | None) -> str:
    return "default" if not name else name.strip().lower()


def validate_policy_pack(pack: PolicyPack) -> list[tuple[str, str]]:
    """Return list of (level, message); level OK or FAIL."""
    lines: list[tuple[str, str]] = []
    if not pack.name:
        lines.append(("FAIL", "Policy missing name"))
    if not pack.description:
        lines.append(("WARN", "Policy missing description"))
    if pack.max_repair_prompts < 1:
        lines.append(("FAIL", "max_repair_prompts must be >= 1"))
    for after, msg in pack.default_checkpoints:
        if not after or not msg:
            lines.append(("FAIL", f"Invalid checkpoint: after={after!r}"))
    if not lines:
        lines.append(("OK", f"Policy {pack.name!r} is valid"))
    return lines


# --- Policy-tailored artifact templates ---


def task_intake_for_policy(
    policy: PolicyPack, task: str, repo_path: str, run_id: str
) -> str:
    base = f"""# Task intake

**Run ID:** `{run_id}`  
**Task:** {task}  
**Target repo:** `{repo_path}`  
**Policy:** `{policy.name}` — {policy.description}

## Objective

{task}

## Policy: {policy.name}

{policy.description}

## Acceptance criteria
"""
    if policy.name == "bugfix":
        base += """
- [ ] Failing test or minimal reproduction documented
- [ ] Root cause identified (not symptom-only fix)
- [ ] Regression test added or updated
- [ ] Before/after test evidence in executor output
"""
    elif policy.name == "refactor":
        base += """
- [ ] **No behavior change** unless explicitly approved
- [ ] Public API unchanged (or lead-approved exceptions listed)
- [ ] Diff limited to refactor scope — no feature additions
"""
    elif policy.name == "docs":
        base += """
- [ ] Documentation accurate vs current code/CLI
- [ ] Examples runnable or clearly marked illustrative
- [ ] No product code changes unless required for doc build
"""
    elif policy.name == "test-only":
        base += """
- [ ] Tests map to stated acceptance criteria
- [ ] Production code untouched unless strictly necessary (document why)
- [ ] Tests are stable (not brittle implementation-detail locks)
"""
    elif policy.name == "release":
        base += """
- [ ] Version bumped in all required locations
- [ ] Changelog or release notes updated
- [ ] Smoke scripts run and results recorded
"""
    elif policy.name == "agentic-tooling":
        base += """
- [ ] No autopilot, background jobs, or auto repair dispatch loops
- [ ] No merge/push/deploy automation in governor
- [ ] No hardcoded vendor agent CLI syntax in core
- [ ] `.governor` remains gitignored
"""
    else:
        base += """
- [ ] Criteria 1
- [ ] Criteria 2
"""
    base += f"""
## Constraints

- Minimal scope aligned with policy `{policy.name}`
- {REDACTION_WARNING}
- Human delegates implementation; Governor records and gates only

## Evidence expectations

"""
    for e in policy.evidence_expectations:
        base += f"- {e}\n"
    base += """
## Out of scope

- (list explicitly)

## References

- (links, tickets, docs)
"""
    return base


def scope_and_assumptions_for_policy(policy: PolicyPack, task: str) -> str:
    extra = ""
    if policy.name == "bugfix":
        extra = "\n- Assume a failing test or reproduction exists or will be created first.\n"
    elif policy.name == "refactor":
        extra = "\n- Assume **zero intentional behavior change**.\n"
    elif policy.name == "docs":
        extra = "\n- Assume code behavior is frozen; only docs change.\n"
    elif policy.name == "test-only":
        extra = "\n- Assume tests-only diff unless blocker documented.\n"
    return f"""# Scope and assumptions

**Task:** {task}  
**Policy:** `{policy.name}`

## In scope

- (what will change — aligned with {policy.name} policy)
{extra}
## Out of scope

- (what will not change)

## Facts

- (verified truths)

## Assumptions

- (accepted defaults — label clearly)

## Open questions

- (blockers for lead)
"""


def risk_register_for_policy(policy: PolicyPack) -> str:
    rows = []
    for i, r in enumerate(policy.risk_prompts[:6], start=1):
        rows.append(f"| R{i} | {r} | medium | medium | Mitigate per policy | owner |")
    if not rows:
        rows = [
            "| R1 | Scope creep | medium | high | Minimal diff policy | executor |",
            "| R2 | Secret leakage | low | critical | Redaction + no secrets | human |",
        ]
    table = "\n".join(rows)
    stops = "\n".join(f"- {s}" for s in policy.stop_conditions) or "- (none listed)"
    return f"""# Risk register

**Policy:** `{policy.name}`

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|----|------|------------|--------|------------|-------|
{table}

## Stop conditions (policy)

{stops}

## Notes

- Update after gate and validator review.
"""


def executor_prompt_for_policy(
    policy: PolicyPack, task: str, repo_path: str, run_id: str
) -> str:
    mission_extra = ""
    deliverables_extra = ""
    if policy.name == "bugfix":
        mission_extra = (
            "\n**Bugfix policy:** Find root cause, add/update regression test, "
            "minimal fix only. Document failing test before and passing test after.\n"
        )
        deliverables_extra = (
            "- **Regression evidence:** failing test output (before) and passing (after)\n"
            "- Root cause summary (1–3 sentences)\n"
        )
    elif policy.name == "refactor":
        mission_extra = (
            "\n**Refactor policy:** No behavior change. Preserve public API. "
            "Keep diff focused — flag any incidental behavior risk.\n"
        )
        deliverables_extra = "- Statement: **no behavior change** (or list approved exceptions)\n"
    elif policy.name == "docs":
        mission_extra = (
            "\n**Docs policy:** Do not change product code unless required for doc build. "
            "Verify commands and examples against the repo.\n"
        )
        deliverables_extra = "- List of doc files updated with accuracy notes\n"
    elif policy.name == "test-only":
        mission_extra = (
            "\n**Test-only policy:** Avoid production code. If you must touch prod code, "
            "justify in one paragraph.\n"
        )
        deliverables_extra = "- Test-to-criteria mapping table\n"
    elif policy.name == "release":
        mission_extra = (
            "\n**Release policy:** Bump version, update changelog/checklist, run smoke scripts.\n"
        )
        deliverables_extra = "- Version locations changed\n- Smoke script results\n"
    elif policy.name == "agentic-tooling":
        mission_extra = (
            "\n**Agentic-tooling policy:** No autopilot, no background execution, "
            "no hardcoded Cursor/Claude CLI in core, no secrets in repo.\n"
        )
        deliverables_extra = "- Explicit list of safety checks performed\n"

    return f"""# Executor agent prompt

**Policy:** `{policy.name}` — {policy.description}

Paste this entire document into your delegated agent. You are the **implementation executor**, not the Governor.

**Run ID:** `{run_id}`  
**Task:** {task}  
**Repo:** `{repo_path}`

---

## Mission

Implement the task with **minimal, focused changes** per policy `{policy.name}`.
{mission_extra}
## Required workflow

1. **Inspect first** — Read relevant files, tests, and conventions.
2. **Plan briefly** — Short implementation plan before editing.
3. **Implement minimally** — Smallest correct diff for this policy.
4. **Avoid** — Scope creep, secrets, vendor-specific CLI wiring in governor core.
5. **Run checks** — Tests/lint/smoke as applicable to policy.
6. **Report honestly** — Limitations and unverified areas.

## Deliverables (include all in your final message)

- Implementation plan (short)
- Changed files with one-line rationale each
- Commands run with exit codes
- Test/lint/smoke results
{deliverables_extra}- Risks and known gaps

## Security

- {REDACTION_WARNING}

## When done

`python -m governor record --run-id {run_id} --role executor --file <your_output.md>`
"""


def validator_prompt_for_policy(
    policy: PolicyPack, task: str, repo_path: str, run_id: str
) -> str:
    checks_extra = ""
    if policy.name == "bugfix":
        checks_extra = """
3. Confirm **root cause** vs symptom-only fix.
4. Require **before/after test evidence** in executor output.
5. Reject drive-by refactors unrelated to the bug.
"""
    elif policy.name == "refactor":
        checks_extra = """
3. Confirm **no behavior change** (or approved exceptions documented).
4. Review **public API** and diff sprawl.
"""
    elif policy.name == "docs":
        checks_extra = """
3. Skip deep code review unless docs required code changes.
4. Verify **accuracy**, examples, and stale commands/paths.
"""
    elif policy.name == "test-only":
        checks_extra = """
3. Confirm tests map to criteria and are not brittle.
4. Flag unnecessary **production code** changes.
"""
    elif policy.name == "release":
        checks_extra = """
3. Verify **version** consistency and changelog/release checklist.
4. Confirm **smoke scripts** were run (evidence in executor output).
"""
    elif policy.name == "agentic-tooling":
        checks_extra = """
3. Reject **autopilot**, background jobs, or auto repair dispatch loops.
4. Reject **hardcoded vendor CLI** syntax in governor core.
5. Confirm no **secret leakage** in config/examples.
"""

    return f"""# Validator agent prompt

**Policy:** `{policy.name}` — {policy.description}

Paste into your delegated validator agent. You are an **adversarial auditor**.

**Run ID:** `{run_id}`  
**Task:** {task}  
**Repo:** `{repo_path}`

---

## Mission

Verify executor work against **{policy.name}** policy expectations and intake.

## Required checks

1. Read intake and scope artifacts.
2. Inspect git diff and changed files.
{checks_extra}
## Verdict (exactly one label on its own line)

```
PASS
PASS_WITH_RISK
REPAIR_REQUIRED
HUMAN_DECISION_REQUIRED
```

## Output structure

- **Verdict:** (one of four)
- **Policy compliance:** met / partial / not met for `{policy.name}`
- **Findings:** severity-tagged bullets
- **Evidence reviewed**
- **Repair instructions** if REPAIR_REQUIRED

## When done

`python -m governor record --run-id {run_id} --role validator --file <your_output.md>`
"""


def build_init_artifacts(
    policy: PolicyPack,
    task: str,
    repo_path: str,
    run_id: str,
) -> dict[str, str]:
    return {
        "00_task_intake.md": task_intake_for_policy(policy, task, repo_path, run_id),
        "01_scope_and_assumptions.md": scope_and_assumptions_for_policy(policy, task),
        "02_risk_register.md": risk_register_for_policy(policy),
        "03_executor_prompt.md": executor_prompt_for_policy(policy, task, repo_path, run_id),
        "04_validator_prompt.md": validator_prompt_for_policy(policy, task, repo_path, run_id),
    }


def assess_policy_compliance(
    run_dir: Path,
    policy: PolicyPack,
    *,
    gate_overall: str | None = None,
    validator_verdict: str | None = None,
) -> dict[str, Any]:
    """Simple PASS/WARN/FAIL heuristic for evidence bundle."""
    findings: list[str] = []
    missing = [
        a for a in policy.required_artifacts if not (run_dir / a).is_file()
    ]
    if missing:
        findings.append(f"Missing required artifacts: {', '.join(missing)}")

    if gate_overall == "FAIL":
        findings.append("Gate overall FAIL")
    elif gate_overall is None and any(
        g in policy.recommended_gates for g in ("git_diff", "security_scan")
    ):
        if not (run_dir / "08_gate_results.json").is_file():
            findings.append("Gate results not recorded (recommended)")

    if validator_verdict in ("REPAIR_REQUIRED", "HUMAN_DECISION_REQUIRED"):
        findings.append(f"Validator verdict: {validator_verdict}")

    if policy.name == "bugfix":
        ex = (run_dir / "05_executor_output.md").read_text(encoding="utf-8").lower()
        if (run_dir / "05_executor_output.md").is_file():
            if "test" not in ex and "regression" not in ex:
                findings.append("Bugfix: executor output lacks test/regression evidence")
        else:
            findings.append("Bugfix: executor output missing")

    if policy.name == "release":
        ex = ""
        if (run_dir / "05_executor_output.md").is_file():
            ex = (run_dir / "05_executor_output.md").read_text(encoding="utf-8").lower()
        if "version" not in ex and "smoke" not in ex:
            findings.append("Release: executor output should mention version/smoke")

    hard = [f for f in findings if f.startswith("Missing") or "FAIL" in f]
    if hard:
        overall = "FAIL"
    elif findings:
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "overall": overall,
        "policy": policy.name,
        "findings": findings,
        "missing_artifacts": missing,
        "expectations": list(policy.evidence_expectations),
    }
