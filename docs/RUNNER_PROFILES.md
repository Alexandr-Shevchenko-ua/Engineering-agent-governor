# Runner profiles (v0.3)

Governor v0.3 adds **local runner profiles**: named dispatch settings stored in
`.governor/config.json`. This is **not autopilot** and **not** a built-in Cursor
integration — you define trusted local commands on your machine.

## Local-only config

| Path | Tracked in git? |
|------|-----------------|
| `.governor/config.json` | **No** (entire `.governor/` is gitignored) |
| `examples/governor.config.example.json` | Yes (template only) |

`config init` creates `.governor/config.json` only. It does **not** create runs.

## Quick start

```bash
python -m governor config path --repo-path .
python -m governor config init --repo-path .
python -m governor config validate --repo-path .
python -m governor config show --repo-path .
```

Repair dispatch uses the same profiles:

```bash
python -m governor repair prepare --run-id "$RUN_ID" --repo-path .
python -m governor dispatch --run-id "$RUN_ID" --role repair --profile echo-test --approve --repo-path .
```

See [REPAIR_WORKFLOW.md](REPAIR_WORKFLOW.md).

## Dispatch with a profile

Preview first (no output artifact):

```bash
RUN_ID=<run-id-from-list>
python -m governor dispatch --run-id "$RUN_ID" --role executor --profile echo-test --repo-path .
```

Execute after review:

```bash
python -m governor dispatch --run-id "$RUN_ID" --role executor --profile echo-test --approve --repo-path .
```

`--profile` and `--runner` are **mutually exclusive**. Direct `--runner echo|command|cursor`
behavior from v0.2.x is unchanged.

## Configure a trusted local CLI

1. Copy ideas from `examples/governor.config.example.json`.
2. Edit `.governor/config.json` locally.
3. For a custom CLI, use `"runner": "command"` and fill `"argv"` with executable + args.
4. Set `"enabled": true` only when argv is complete.
5. Run `config validate` before dispatch.

**Do not put secrets in argv** (tokens, API keys, `Bearer …`, `password=`, `secret=`).
Governor rejects secret-looking argv at validate/dispatch time. Config `show` redacts
suspicious argv values.

## Why `cursor-local` is disabled by default

- Governor does **not** ship or hardcode Cursor CLI syntax.
- The default `cursor-local` profile has empty `argv` and `"enabled": false`.
- Enable it only after you fill argv with **your** trusted local command.

Same for `claude-local`: placeholder for user configuration, not product integration.

## Timeout

- Profile `timeout` is used when dispatch omits `--timeout`.
- CLI `--timeout` overrides the profile when provided.

## Safety

Profiles are validated for:

- schema version `1`
- safe profile names (no paths)
- runner type `echo` | `command` | `cursor`
- enabled `command` profiles must have non-empty `argv`
- destructive argv patterns (same rules as `--runner command`)
- secret-like argv patterns

Disabled profiles fail dispatch unless you pass `--allow-disabled-profile`.

## Example profiles

| Name | Purpose |
|------|---------|
| `echo-test` | Safe builtin echo runner (smoke / dogfood) |
| `fake-validator` | Runs `scripts/fake_agent.py` via `python` |
| `cursor-local` | Disabled until you add your local CLI argv |
| `claude-local` | Disabled placeholder for another local CLI |

## Preview-first workflow

1. `dispatch --profile X` → inspect Profile, Runner, Command, Timeout, Config path.
2. `dispatch --profile X --approve` → execute bounded runner.
3. `gate` / `report` as usual.

## Run ID reminder

`--run-id` is the **folder name** only (e.g. `20260524T214854Z_my-task`), not a path.
