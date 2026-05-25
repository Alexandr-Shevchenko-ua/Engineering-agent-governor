# Self-dogfooding (Governor on Governor)

Use Governor on **this repository** to validate a release without committing `.governor/` or polluting git history.

## Safety

- `.governor/` must stay **gitignored** (see `.gitignore`).
- `governor.project.json` at repo root is **tracked** — no secrets or local runner argv.
- Runner profiles live only in `.governor/config.json` (ignored).

## Quick automated release check

From the repository root (does not modify this repo’s working tree except reading git metadata):

```bash
python -m governor version
python -m governor project validate --repo-path .
python -m governor check --repo-path .
python scripts/self_dogfood_release_check.py
```

For full smoke coverage (slower):

```bash
python -m governor check --repo-path . --smoke
```

Expected: `Governor check: PASS` and `SELF DOGFOOD OK`.

## Manual dogfood run on this repo

1. **One-time local config** (ignored):

   ```bash
   python -m governor config init --repo-path .
   # Edit .governor/config.json if you use custom validator argv (optional)
   ```

2. **Governed run** (creates `.governor/runs/<run-id>/` only under ignored path):

   ```bash
   python -m governor run start \
     --task "Dogfood v1.0.0 release" \
     --policy agentic-tooling \
     --use-default-profiles \
     --approve \
     --with-evidence \
     --with-review-package \
     --repo-path .
   ```

   Policies with checkpoints (e.g. `agentic-tooling`, `bugfix`) stop after `gate` until:

   ```bash
   python -m governor plan checkpoint \
     --run-id <run-id> \
     --step-id checkpoint_after_gate \
     --approve \
     --note "Reviewed gate results" \
     --repo-path .

   python -m governor run resume --run-id <run-id> --approve --repo-path .
   ```

   For a **single-shot** smoke path without checkpoints, use `--policy default` or `--policy docs`.

   **Gate profile `fast` on this repo:** ensure `pytest` is on `PATH` (e.g. `export PATH="$(pwd)/.venv/bin:$PATH"`). If `08_gate_results.json` shows `overall: WARN` only because optional checks (`ruff`, `mypy`) were skipped, either pass `--continue-on-gate-warn` on `run start` / `run resume`, or accept the WARN and continue manually (do not re-run `gate` from state `GATES_RUN` — resume validator/report instead).

3. **Inspect artifacts** under `.governor/runs/<run-id>/`:

   | Artifact | Purpose |
   |----------|---------|
   | `08_gate_results.json` | Gate profile + compliance |
   | `09_final_report.md` | Closure report |
   | `14_evidence_bundle.md/json` | Lead/MR evidence |
   | `15_review_package.md/json` | Review handoff |
   | `15_pr_body.md` | Suggested PR body |

4. **Status**:

   ```bash
   python -m governor run status --run-id <run-id> --repo-path .
   ```

## Gate profile on this repo

Project default profile is `fast` (see `governor.project.json`). Re-run gates for an existing run:

```bash
python -m governor gate --run-id <run-id> --repo-path . --profile fast
```

## What not to do

- Do not `git add .governor/`.
- Do not put API keys in `governor.project.json`.
- Do not expect Governor to invoke Cursor automatically.

See [docs/DOGFOODING.md](DOGFOODING.md) for run ID conventions and [docs/RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) before tagging.
