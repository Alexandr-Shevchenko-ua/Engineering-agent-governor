# Dogfooding Engineering Agent Governor

Use Governor to **manage delegated agent work** on this repository (or any target repo) without treating agent chat as the source of truth.

## Managing a change in this repo

```bash
cd /home/shevchenkool/project/Engineering-agent-governor

python -m governor init --task "Add index.json run discovery" --repo-path .
python -m governor list --repo-path .
# Paste .governor/runs/<run-id>/03_executor_prompt.md into Cursor Agent
python -m governor record --run-id /home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260524T214854Z_add-indexjson-run-discovery --role executor --file /home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260524T214854Z_add-indexjson-run-discovery/output.md --repo-path /home/shevchenkool/project/Engineering-agent-governor
python -m governor gate --run-id /home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260524T214854Z_add-indexjson-run-discovery --repo-path .
# Paste 04_validator_prompt.md
python -m governor record --run-id /home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260524T214854Z_add-indexjson-run-discovery --role validator --file /home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260524T214854Z_add-indexjson-run-discovery/validator.md --repo-path .
python -m governor report --run-id .governor/runs/20260524T214854Z_add-indexjson-run-discovery/validator.md --repo-path .
```

Inspect artifacts under `.governor/runs/<run-id>/` before merging.

## Recommended manual loop

| Step | Command / action |
|------|------------------|
| 1 | `init` — creates intake, prompts, index entry |
| 2 | Human — paste **executor** prompt into Cursor Agent |
| 3 | `record --role executor` |
| 4 | `gate` — git + security + optional tools |
| 5 | Human — paste **validator** prompt |
| 6 | `record --role validator` |
| 7 | `report` — final report + lead update |

Optional: `doctor` before starting; `list` / `status` anytime.

## Bounded dispatch (v0.2)

Dispatch is optional — manual `record` still works.

```bash
# Always preview first
python -m governor dispatch --run-id <id> --role executor --runner echo --repo-path .

# Execute only after reviewing preview
python -m governor dispatch --run-id <id> --role executor --runner echo --approve --repo-path .
```

**Safe usage:**

- Use `echo` for plumbing tests; use `--runner command` only with scripts you trust.
- Never dispatch as root or with credentials in argv.
- Do not use dispatch for merge/push/deploy — Governor will refuse obvious destructive argv patterns.
- `cursor` runner prints configuration guidance; wire your CLI via `--runner command --command …`.
- Inspect `05_*` / `06_*` artifacts — dispatch output is not automatic PASS.
- If runner exits non-zero, check `*.failed.md` — that is **diagnostic only**, not executor/validator evidence.
- Use `--accept-failed-output` only when you intentionally want a failed run to occupy the canonical slot (rare).

### State order (enforced)

1. executor (`record` or `dispatch --approve`)
2. `gate`
3. validator
4. `report`

Skipping steps raises `Invalid transition: …` and does **not** write canonical `05_*` / `06_*` files.

### Preview vs execute

- Preview always exits 0 and may warn: existing artifact needs `--replace`, or wrong state for role.
- Execute enforces transitions and overwrite rules.

## Verdict meanings

| Verdict | Meaning |
|---------|---------|
| **PASS** | Acceptance criteria met; evidence supports claims |
| **PASS_WITH_RISK** | Shippable with documented risks; lead should acknowledge |
| **REPAIR_REQUIRED** | Fix specific issues; re-run gate/validator |
| **HUMAN_DECISION_REQUIRED** | Product/security/architecture call for lead |

Gate-only outcomes (`GATES_PASS_NO_VALIDATOR`, etc.) are **not** validator sign-off — treat them as incomplete unless your process explicitly allows gate-only closure.

## Avoid fake confidence

- Do not record executor output that only says "tests pass" without command output.
- Do not skip `gate` because the agent said it ran checks.
- Do not treat `PASS` in chat as recorded until `06_validator_output.md` contains an explicit verdict line.
- Re-read `08_gate_results.md` for WARN/FAIL and suspicious paths.
- Use `--replace` on record only when intentionally superseding a prior artifact.

## Artifacts to inspect before trust

1. `08_gate_results.json` — overall status, security warnings, diff size
2. `05_executor_output.md` — changed files, commands, limitations
3. `06_validator_output.md` — verdict + findings (adversarial)
4. `09_final_report.md` — outcome, state `FINAL_REPORT_READY`, commands list
5. `trace.jsonl` — audit timeline
6. `.governor/index.json` — run discovery entry matches folder

## Example task (concrete)

**Task:** “Harden report command ordering so final report shows FINAL_REPORT_READY and includes report command once.”

**Success looks like:**

- Executor lists touched files (`report.py`, tests)
- Gate PASS or WARN with explained warnings
- Validator verdict `PASS` or `PASS_WITH_RISK` with evidence cited
- `09_final_report.md` shows correct state and single report command
- Lead update “Need from lead” is honest (not “None” when validator missing)

## Readiness checks

```bash
python -m governor doctor --repo-path .
python scripts/smoke_governor_workflow.py
python scripts/smoke_dispatch_workflow.py
```
