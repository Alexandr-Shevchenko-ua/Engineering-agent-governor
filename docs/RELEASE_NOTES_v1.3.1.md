# Release notes — v1.3.1 (stabilization)

**Theme:** Daily-use hardening — clearer roles, safety audit, cleanup, diagnostics. No new providers or autopilot features.

## Added

- **`governor safety audit`** — read-only checks for gitignore, tracked `.governor`/`.claude`, profile ask-mode for Governor provider, secret-like argv, project config.
- **`governor cleanup`** — `status`, `runs`, `proposals` with retention (`--keep-last`, dry-run default, `--approve` to delete).
- **`governor diagnose --run-id`** — state, gate/plan summary, next recommended command.
- **Docs:** [ARCHITECTURE.md](ARCHITECTURE.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
- **Smoke:** `scripts/smoke_stabilization_workflow.py`.

## Improved

- **`governor check`** includes safety-audit checks (deduped with existing gitignore checks).
- **Proposal validation** — negation-aware destructive pattern matching (“do not git push” no longer FAIL).
- **README** — architecture diagram and ops commands.

## Unchanged

- v1.3.0 Governor Mode (`chatbang`, `cursor-auto`), advisor, Cursor executor profiles.
- Proposal-first lifecycle; no background daemon; no merge/push/deploy from Governor.

## Upgrade

```bash
pip install -e ".[dev]"
python -m governor --version   # 1.3.1
python -m governor safety audit --repo-path .
python -m governor check --repo-path .
```
