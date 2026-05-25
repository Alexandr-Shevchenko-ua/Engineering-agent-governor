# Engineering Agent Governor

**v1.0.0** — local control plane for agent-delegated engineering: auditable runs, gates, plans, evidence, and review packages. Governor orchestrates **your** tools and **your** agents; it is not an agent itself.

## Not autopilot

| Governor does | Governor does not |
|---------------|-------------------|
| Create run artifacts and prompts | Invoke Cursor/Claude automatically |
| Preview dispatch; run only with `--approve` | Background daemons or repair loops |
| Run git/tooling gates | Merge, push, or deploy |
| Export evidence and PR-ready review packs | Call external LLM APIs |

Keep **`.governor/` gitignored** (local runs and runner argv). Commit **`governor.project.json`** (policies and gate profiles — no secrets).

## Quick workflows

### 1. Governed smoke run (temp or real repo)

```bash
python -m governor config init --repo-path .
python -m governor run start --task "Smoke task" \
  --policy default --use-default-profiles --approve --repo-path .
```

Use `--with-evidence` and `--with-review-package` when you need closure artifacts. See [docs/GOVERNED_RUNS.md](docs/GOVERNED_RUNS.md).

### 2. Real repo setup (project + config)

```bash
python -m governor project init --repo-path .
python -m governor config init --repo-path .
python -m governor project validate --repo-path .
python -m governor init --task "My change" --repo-path .
```

Policy defaults come from `governor.project.json` when present. See [docs/PROJECT_GOVERNANCE.md](docs/PROJECT_GOVERNANCE.md).

### 3. Evidence and review export

After a run reaches final report:

```bash
python -m governor evidence export --run-id <run-id> --repo-path .
python -m governor review export --run-id <run-id> --repo-path .
```

Or in one governed start: `--with-evidence --with-review-package`.

## Architecture (high level)

```text
Human → governor CLI → .governor/runs/<run-id>/artifacts
              ↓
         target git repo (gates, diff)
              ↓
         optional local runner (--approve) → record output
```

- **Tracked:** `governor.project.json` — policies, gate profiles, diff budget
- **Ignored:** `.governor/config.json` — runner profiles
- **Per run:** prompts, outputs, gates, plan, reports, evidence, review

## Commands (index)

| Area | Commands |
|------|----------|
| Runs | `init`, `status`, `list`, `run`, `report` |
| Quality | `gate`, `doctor`, `check`, `project validate` |
| Agents | `dispatch`, `record`, `repair`, `plan` |
| Handoff | `evidence`, `review` |
| Config | `config`, `project`, `policy`, `version` |

Full reference: **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)**

## Development and release

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/ -v
python -m governor check --repo-path .
python scripts/self_dogfood_release_check.py
```

CI: `.github/workflows/ci.yml` (Python 3.11 / 3.12, pytest, smokes).

- [docs/RELEASE_NOTES_v1.0.0.md](docs/RELEASE_NOTES_v1.0.0.md)
- [docs/RELEASE_NOTES_v1.0.0-rc1.md](docs/RELEASE_NOTES_v1.0.0-rc1.md) (release candidate)
- [docs/SELF_DOGFOODING.md](docs/SELF_DOGFOODING.md)
- [docs/RUNNER_PROFILE_LOCAL_SETUP.md](docs/RUNNER_PROFILE_LOCAL_SETUP.md)
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)
- [docs/DOGFOODING.md](docs/DOGFOODING.md)

Install entry point: `gov` (same as `python -m governor`).
