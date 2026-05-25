# CLI reference

Entry points:

```bash
python -m governor [COMMAND] [--repo-path PATH]
gov [COMMAND] [--repo-path PATH]   # after pip install -e .
```

`--repo-path` defaults to `.` and may appear before or after the subcommand on most commands.

**Global**

| Flag | Description |
|------|-------------|
| `--version` | Print `governor <version>` and exit |
| `-h`, `--help` | Help |

**Exit codes (typical):** `0` success · `1` usage/validation error · `2` gate overall FAIL (gate command only)

---

## version

Runtime and package identity.

```bash
python -m governor version
python -m governor version --json
```

| Flag | Description |
|------|-------------|
| `--json` | `version`, `package`, `python_version`, `platform` |

**Artifacts:** none  
**Safety:** read-only

---

## check

Meta-check for the **Governor repository** (or any repo with `tests/`). Not autopilot.

```bash
python -m governor check --repo-path .
python -m governor check --repo-path . --smoke
python -m governor check --repo-path . --json
```

| Flag | Description |
|------|-------------|
| `--smoke` | Run all `scripts/smoke_*.py` from the installed package |
| `--json` | Machine-readable summary |
| `--repo-path` | Repo to validate `governor.project.json` and git ignore rules |

**Checks:** version · project config (if present) · `.governor` gitignored · no tracked `.governor` · `pytest tests/` (if `tests/` exists) · optional smokes

**Exit:** `0` if no FAIL checks, else `1`

---

## init

Create a new governed run folder and intake artifacts.

```bash
python -m governor init --task "Add retry policy" --repo-path .
python -m governor init --task "Fix timeout" --policy bugfix --repo-path .
```

| Flag | Description |
|------|-------------|
| `--task` | Required task title |
| `--policy` | Policy pack (default: `governor.project.json` → `default_policy`, else `default`) |

**Artifacts:** `.governor/runs/<run-id>/` — `00`–`04` prompts, `run_state.json`, `trace.jsonl`  
**State after:** `EXECUTOR_PROMPT_READY`  
**Safety:** creates only under `.governor/` (should be gitignored)

---

## status

Show one run’s metadata and artifact list.

```bash
python -m governor status --repo-path .
python -m governor status --run-id 20260524T120000Z_my-task --repo-path .
python -m governor status --json --repo-path .
```

| Flag | Description |
|------|-------------|
| `--run-id` | Default: latest run |
| `--json` | Structured payload |

**Artifacts:** none (read-only)

---

## list

List runs from `.governor/index.json`.

```bash
python -m governor list --repo-path .
python -m governor list --limit 10 --json --repo-path .
```

---

## doctor

Readiness check (Python, git, runs, config, optional tools). Does not create `.governor`.

```bash
python -m governor doctor --repo-path .
```

**Exit:** `1` on FAIL (repo missing, corrupt index/state)

---

## config

Local runner profiles — **gitignored** `.governor/config.json`.

| Subcommand | Purpose |
|------------|---------|
| `init` | Write example config (`--force` to overwrite) |
| `show` | List profiles (argv redacted) |
| `validate` | Schema/secret checks |
| `path` | Print config file path |

```bash
python -m governor config init --repo-path .
python -m governor dispatch --run-id <id> --role executor --profile echo-test --approve --repo-path .
```

See [RUNNER_PROFILES.md](RUNNER_PROFILES.md) and [RUNNER_PROFILE_LOCAL_SETUP.md](RUNNER_PROFILE_LOCAL_SETUP.md).

---

## project

Tracked governance — **`governor.project.json`** (committed, no secrets).

| Subcommand | Purpose |
|------------|---------|
| `init` | Write default project config (`--force`) |
| `show` | Summary |
| `validate` | Schema and policy/gate rules |
| `path` | Print config path |

```bash
python -m governor project init --repo-path .
python -m governor project validate --repo-path .
```

See [PROJECT_GOVERNANCE.md](PROJECT_GOVERNANCE.md).

---

## policy

Built-in policy packs (no `.governor` required).

| Subcommand | Purpose |
|------------|---------|
| `list` | All policy names |
| `show` | Details for one policy |
| `validate` | Internal pack consistency |

```bash
python -m governor policy list
python -m governor policy show --policy agentic-tooling
```

See [POLICY_PACKS.md](POLICY_PACKS.md).

---

## dispatch

Preview or run a **bounded local process** (echo, command, or profile). **Not autopilot.**

```bash
# Preview only
python -m governor dispatch --run-id <id> --role executor --runner echo --repo-path .

# Execute (requires --approve)
python -m governor dispatch --run-id <id> --role executor --profile echo-test --approve --repo-path .
```

| Flag | Description |
|------|-------------|
| `--role` | `executor`, `validator`, `repair` |
| `--runner` / `--profile` | Mutually exclusive |
| `--approve` | Required to execute |
| `--replace` | Overwrite existing role output |
| `--accept-failed-output` | Record output even on non-zero exit |
| `--timeout` | Seconds (command runner) |
| `--command` | Args after flags for `--runner command` |

**Artifacts:** `05_executor_output.md`, `06_validator_output.md`, or `07_repair_output_N.md`  
**Safety:** preview by default; no `shell=True`; stdin gets prompt text

---

## record

Record human/agent output (audit trail protected for executor/validator).

```bash
python -m governor record --run-id <id> --role executor --file ./out.md --repo-path .
python -m governor record --run-id <id> --role validator --text "PASS" --replace --repo-path .
```

| Flag | Description |
|------|-------------|
| `--file` / `--text` | One required |
| `--replace` | Allow overwrite of executor/validator artifact |

---

## repair

Prepare repair prompts; **does not dispatch repair automatically.**

| Subcommand | Purpose |
|------------|---------|
| `prepare` | `11_repair_prompt_N.md` |
| `list` | Existing repair artifacts |

```bash
python -m governor repair prepare --run-id <id> --reason "Gate FAIL" --repo-path .
```

See [REPAIR_WORKFLOW.md](REPAIR_WORKFLOW.md).

---

## plan

Bounded multi-step orchestration (dispatch, gate, validator, report, optional checkpoints).

| Subcommand | Purpose |
|------------|---------|
| `create` | Write `12_run_plan.json` |
| `show` | Plan table |
| `execute` | Run steps (`--approve` for dispatch) |
| `resume` | Continue incomplete plan |
| `validate` | Plan file checks |
| `checkpoint` | Approve `human_checkpoint` step |

```bash
python -m governor plan create --run-id <id> \
  --executor-profile echo-test --validator-profile fake-validator --repo-path .

python -m governor plan execute --run-id <id> --approve --repo-path .
python -m governor plan execute --run-id <id> --approve --continue-on-gate-warn --repo-path .
```

| Flag | Notes |
|------|-------|
| `--gate-profile` | On `create` — stored on plan |
| `--continue-on-gate-warn` | On `execute`/`resume` — WARN does not stop plan |
| `--max-steps` | Step budget (default 10) |

See [RUN_PLANS.md](RUN_PLANS.md).

---

## run

High-level governed workflow (init + plan + optional execution).

| Subcommand | Purpose |
|------------|---------|
| `start` | New run + plan; executes only with `--approve` |
| `status` | Summary + artifact paths |
| `resume` | Continue plan (`--approve` required) |

```bash
python -m governor run start --task "Feature X" --use-default-profiles --approve --repo-path .
python -m governor run start --task "Feature X" --approve \
  --with-evidence --with-review-package --policy default --repo-path .
python -m governor run resume --run-id <id> --approve --repo-path .
```

| Flag | Description |
|------|-------------|
| `--approve` | Run plan steps (otherwise plan-only) |
| `--use-default-profiles` | echo-test + fake-validator (smoke-safe) |
| `--with-evidence` | Export `14_evidence_bundle.*` when final report ready |
| `--with-review-package` | Export `15_review_package.*` + `15_pr_body.md` |
| `--strict-preflight` | FAIL on preflight WARN |
| `--gate-profile` | Gate step profile |
| `--dry-run` | Describe actions only (`start`) |

See [GOVERNED_RUNS.md](GOVERNED_RUNS.md).

---

## gate

Deterministic checks on the **target git repo** for a run.

```bash
python -m governor gate --run-id <id> --repo-path .
python -m governor gate --run-id <id> --profile fast --repo-path .
```

| Flag | Description |
|------|-------------|
| `--profile` | Gate profile from `governor.project.json` (else project default) |

**Artifacts:** `08_gate_results.json`, `08_gate_results.md`  
**Exit:** `2` if overall FAIL, else `0` (WARN still `0`)

---

## evidence

Lead/MR evidence bundle.

```bash
python -m governor evidence export --run-id <id> --repo-path .
python -m governor evidence export --run-id <id> --format json --include-prompts --repo-path .
```

**Artifacts:** `14_evidence_bundle.md`, `14_evidence_bundle.json`

See [EVIDENCE_BUNDLES.md](EVIDENCE_BUNDLES.md).

---

## advisor

Semantic Governor Advisor (chatbang via pexpect). **Does not** change run state or execute code.

```bash
python -m governor advisor ask --run-id <id> --provider chatbang --kind next-action --repo-path .
python -m governor advisor ask --run-id <id> --kind risk-review --dry-run --repo-path .
python -m governor plan advise --run-id <id> --repo-path .
python -m governor review advise --run-id <id> --repo-path .
```

**Artifacts:** `16_advisor_request_N.md`, `16_advisor_response_N.md`

See [CHATBANG_GOVERNOR_ADVISOR.md](CHATBANG_GOVERNOR_ADVISOR.md).

---

## governor (experimental — Governor Mode)

Providers propose a bounded run; Governor validates; human `--approve` apply. **Does not** execute repo changes on propose/apply.

```bash
python -m governor governor propose --task "..." --provider chatbang --repo-path .
python -m governor governor propose --task "..." --provider cursor-auto --cursor-profile cursor-governor-auto --repo-path .
python -m governor governor compare --task "..." --providers chatbang,cursor-auto --repo-path .
python -m governor governor validate --proposal <id> --repo-path .
python -m governor governor show --proposal <id> --repo-path .
python -m governor governor reject --proposal <id> --reason "..." --repo-path .
python -m governor governor apply --proposal <id> --approve --repo-path .
```

| propose flag | Default | Notes |
|--------------|---------|--------|
| `--provider` | `chatbang` | `chatbang` or `cursor-auto` (read-only) |
| `--cursor-profile` | `cursor-governor-auto` | Local config profile |
| `--cursor-timeout` | `900` | Max `1800` |

**Artifacts:** `.governor/proposals/<id>/` (`proposal.json`, `proposal.md`, `raw_chatbang_response.md`)

Apply creates **run + plan only** — use `governor run resume --approve` to execute with an **executor** profile.

See [CHATBANG_GOVERNOR_MODE.md](CHATBANG_GOVERNOR_MODE.md), [CURSOR_GOVERNOR_PROVIDER.md](CURSOR_GOVERNOR_PROVIDER.md).

---

## review

Review / PR handoff package.

```bash
python -m governor review export --run-id <id> --repo-path .
python -m governor review export --run-id <id> --include-trace --repo-path .
```

**Artifacts:** `15_review_package.md`, `15_review_package.json`, `15_pr_body.md`

See [REVIEW_PACKAGES.md](REVIEW_PACKAGES.md).

---

## report

Final report and lead update (explicit outcome).

```bash
python -m governor report --run-id <id> --repo-path .
```

**Artifacts:** `09_final_report.md`, `10_lead_update.md`  
**State:** `FINAL_REPORT_READY`

---

## Artifact map (per run)

| File | Command(s) |
|------|----------------|
| `00`–`04` | `init` |
| `05_executor_output.md` | `record` / `dispatch` |
| `06_validator_output.md` | `record` / `dispatch` |
| `07_repair_output_*.md` | `record` / `dispatch` repair |
| `08_gate_results.*` | `gate`, plan gate step |
| `09_final_report.md` | `report` |
| `10_lead_update.md` | `report` |
| `11_repair_prompt_*.md` | `repair prepare` |
| `12_run_plan.json` | `plan create` |
| `13_human_checkpoints.md` | plan checkpoints |
| `14_evidence_bundle.*` | `evidence export` |
| `15_review_package.*`, `15_pr_body.md` | `review export` |
| `run_state.json`, `trace.jsonl` | all transitions |

---

## Related docs

- [PROJECT_GOVERNANCE.md](PROJECT_GOVERNANCE.md)
- [GOVERNED_RUNS.md](GOVERNED_RUNS.md)
- [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md)
- [RELEASE_NOTES_v1.0.0-rc1.md](RELEASE_NOTES_v1.0.0-rc1.md)
- [SELF_DOGFOODING.md](SELF_DOGFOODING.md)
