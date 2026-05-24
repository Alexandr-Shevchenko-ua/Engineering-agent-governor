# Engineering Agent Governor

Local **delegation-first control plane** for engineering work executed by external agents (e.g. Cursor Agent). v0.1 is a file-based harness: intake, prompts, recording, deterministic gates, and reporting.

## What this is

- Task intake and assumption/risk artifacts
- Ready-to-paste **executor** and **validator** prompts
- Recording of delegated agent outputs
- Deterministic **git/tooling/security** gates
- Auditable `trace.jsonl` and human-readable reports

## What this is not

- Not a coding agent (does not implement product features)
- Not autopilot (no automatic agent dispatch)
- No external LLM API calls
- No Cursor CLI integration (v0.1)
- No background daemons or production system access

## Quickstart

From this repository (or after install):

```bash
cd /path/to/target-repo
python -m governor init --task "Centralize retry policy" --repo-path .
python -m governor status
# Paste .governor/runs/<run-id>/03_executor_prompt.md into Cursor Agent
python -m governor record --run-id <run-id> --role executor --file /path/to/output.md
python -m governor gate --run-id <run-id>
# Paste 04_validator_prompt.md, then record validator output
python -m governor record --run-id <run-id> --role validator --file /path/to/validator.md
python -m governor report --run-id <run-id>
```

Optional entry point after `pip install -e .`:

```bash
gov init --task "My task" --repo-path .
```

## Commands

| Command | Purpose |
|---------|---------|
| `init` | Create timestamped run under `.governor/runs/` |
| `status` | Show latest or specific run state and artifacts |
| `record` | Store executor/validator/repair/human_note output |
| `gate` | Run local checks → `08_gate_results.json` / `.md` |
| `report` | Generate `09_final_report.md` and `10_lead_update.md` |

## Manual workflow with Cursor Agent

1. **init** — Governor creates intake, scope template, risk register, and prompts.
2. **Human** — Paste `03_executor_prompt.md` into Cursor Agent; agent implements in the target repo.
3. **record --role executor** — Save agent response (file or `--text`).
4. **gate** — Governor runs `git status`, `git diff --stat`, `git diff --check`, optional pytest/ruff/mypy/npm if present, and security heuristics.
5. **Human** — Paste `04_validator_prompt.md`; validator returns one of: `PASS`, `PASS_WITH_RISK`, `REPAIR_REQUIRED`, `HUMAN_DECISION_REQUIRED`.
6. **record --role validator** (and `repair` / `human_note` as needed).
7. **report** — Final audit pack for humans and leads.

## Run artifacts

Each run folder contains:

- `00_task_intake.md` … `04_validator_prompt.md` — planning and prompts
- `05_executor_output.md`, `06_validator_output.md`, `07_repair_output_N.md`, `human_notes.md` — recorded outputs
- `08_gate_results.json` / `.md` — gate evidence
- `09_final_report.md`, `10_lead_update.md` — closure
- `trace.jsonl` — machine-readable audit log
- `run_state.json` — state machine snapshot

## State machine

`INTAKE_CREATED` → `EXECUTOR_OUTPUT_RECORDED` → `GATES_RUN` → `VALIDATOR_OUTPUT_RECORDED` → (`REPAIR_RECORDED`) → `FINAL_REPORT_READY` / `HUMAN_DECISION_REQUIRED`

## Safety

- Gates flag suspicious paths (`.env`, credentials, keys) and coarse diff size.
- Lightweight **redaction** is applied to recorded text; it is **not** perfect.
- **Do not paste secrets** into recorded outputs. Review artifacts before sharing.

## Known limitations (v0.1)

- No automatic agent invocation
- Redaction is heuristic only
- Gates run in the **target repo** from `run_state.json`, not the governor package repo unless that is the target
- Validator verdict parsing is simple (line-based labels)
- Optional tools are skipped when missing (never fail the run solely for missing pytest/ruff)

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/pytest tests/ -v
```

## Planned v0.2

- Cursor CLI / Claude Code dispatcher hooks (still bounded, human-approved)
- Richer verdict parsing and repair loop policies
- `gov` shell completions and run index under `.governor/`
- Optional config file for gate profiles per repo
