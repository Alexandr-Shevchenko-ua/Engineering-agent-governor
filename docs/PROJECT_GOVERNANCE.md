# Project governance (`governor.project.json`)

**v1.0** (since v0.9) uses **tracked, commit-safe** `governor.project.json` for repository governance, separate from local runner profiles in `.governor/config.json`.

## Two config layers

| File | Committed | Contains |
|------|-----------|----------|
| `governor.project.json` | Yes | Policies, gate profiles, diff budget, sensitive paths |
| `.governor/config.json` | No (gitignored) | Runner profiles, argv, secrets |

Never put API keys, tokens, or local absolute paths in `governor.project.json`.

## CLI

```bash
python -m governor project init --repo-path .
python -m governor project show --repo-path .
python -m governor project validate --repo-path .
python -m governor project path --repo-path .
```

## Gate profiles

Named validation modes under `gate_profiles`. Only **built-in check names** are allowed (no arbitrary shell).

```bash
python -m governor gate --run-id <id> --repo-path . --profile fast
python -m governor plan create --run-id <id> --gate-profile release ...
python -m governor run start --task "..." --gate-profile fast ...
```

If `--profile` is omitted and `governor.project.json` exists, `default_gate_profile` is used.

## Diff budget and sensitive paths

When project config exists, gates can run `diff_budget` (WARN if exceeded) and `sensitive_paths` (FAIL if matched).

## Policy defaults

With project config:

- `governor init` / `run start` without `--policy` use `default_policy`
- `--policy` must be listed in `allowed_policies`

Without project config, behavior matches v0.8 (policy defaults to `default`).

## Preflight

Governed runs with `--approve` validate `governor.project.json` when present (FAIL if invalid). Missing file is WARN only.
