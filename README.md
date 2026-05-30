# Engineering Agent Governor

**v1.5.0 Dashboard Lite** — local control plane (Cursor Headless executor, Chatbang Governor Advisor, **Governor Mode** with chatbang and **Cursor Governor Provider** `cursor-auto`, **run evaluation metrics**, **static evaluation dashboard**) for agent-delegated engineering: auditable runs, gates, plans, evidence, review packages, and local success/friction scoring. Governor orchestrates **your** tools and **your** agents; it is not an agent itself.

## Not autopilot

| Governor does | Governor does not |
|---------------|-------------------|
| Create run artifacts and prompts | Invoke Cursor/Claude automatically |
| Preview dispatch; run only with `--approve` | Background daemons or repair loops |
| Run git/tooling gates | Merge, push, or deploy |
| Export evidence and PR-ready review packs | Call external LLM APIs |

Keep **`.governor/` gitignored** (local runs and runner argv). Commit **`governor.project.json`** (policies and gate profiles — no secrets).

## Architecture

```text
  propose (chatbang | cursor-auto)     advisor ask (existing run)
           │                                    │
           ▼                                    ▼
     proposal.json                      16_advisor_*.md
           │                                    │
           └──────────────┬─────────────────────┘
                          ▼
              apply --approve → run + plan
                          ▼
              run resume --approve → dispatch executor (may write repo)
                          ▼
                    gates → validator → report
```

| Layer | Command examples | Modifies repo? |
|-------|------------------|----------------|
| Proposal | `governor propose` (`chatbang` / `cursor-auto`) | No |
| Advice | `advisor ask` | No |
| Execute | `dispatch`, `run resume --approve` | Yes (when approved) |

Full role boundaries: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** · Common issues: **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**

```bash
python -m governor safety audit --repo-path .
python -m governor diagnose --run-id <run-id> --repo-path .
python -m governor cleanup status --repo-path .
python -m governor evaluate run --run-id <run-id> --repo-path .
python -m governor evaluate dashboard --repo-path . --format both
```

Success is measured by **lower manual rework and reviewer burden**, not by lines changed — see [docs/EVALUATION_METRICS.md](docs/EVALUATION_METRICS.md) and [docs/EVALUATION_DASHBOARD.md](docs/EVALUATION_DASHBOARD.md).

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
| Ops | `safety audit`, `diagnose`, `cleanup`, `evaluate` |
| Governor Mode | `governor propose`, `validate`, `apply`, `compare` (`chatbang` or `cursor-auto` planner) |
| Collab loop | `collab start` — chatbang review ↔ Cursor executor rounds ([docs/CHATBANG_CURSOR_COLLAB_MODE.md](docs/CHATBANG_CURSOR_COLLAB_MODE.md)) |

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
- [docs/CURSOR_HEADLESS_RUNNER.md](docs/CURSOR_HEADLESS_RUNNER.md)
- [docs/CURSOR_GOVERNOR_PROVIDER.md](docs/CURSOR_GOVERNOR_PROVIDER.md) — Cursor `cursor-auto` proposal provider (read-only)
- [docs/CHATBANG_GOVERNOR_MODE.md](docs/CHATBANG_GOVERNOR_MODE.md) — Chatbang proposal lifecycle
- [docs/CHATBANG_GOVERNOR_ADVISOR.md](docs/CHATBANG_GOVERNOR_ADVISOR.md)
- [docs/EVALUATION_METRICS.md](docs/EVALUATION_METRICS.md) — run metrics, scoring, post-MR annotation
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)
- [docs/DOGFOODING.md](docs/DOGFOODING.md)

Install entry point: `gov` (same as `python -m governor`).
