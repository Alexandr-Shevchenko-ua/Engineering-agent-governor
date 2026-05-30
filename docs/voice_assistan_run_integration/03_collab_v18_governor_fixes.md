# Collab v1.8 — Governor fixes (2026-05-26)

After post-mortem of `20260526T214847Z_collab_voice-assistant-quality-maximum-aggressive-offer`.

## Problems fixed

| Issue | Fix |
|-------|-----|
| Fake CONTINUE on every round (`parse_error` + freeform fallback) | Human-only: no legacy freeform; **markdown executor brief** → `CONTINUE` |
| Chatbang returns long Patch-or-Fail markdown without JSON | `_extract_markdown_executor_prompt` → Cursor (2026-05-30) |
| Chatbang timeout but Cursor still runs | Stop before executor unless `--continue-on-chatbang-fail` or valid CONTINUE JSON |
| PASS/empty prompt triggered JSON retry | Retry only when `CONTINUE` without `next_executor_prompt` |
| Commits blocked by `.governor/` gate noise | Default `commit_exclude_dot_governor=True` (stage product paths only) |
| Zombie pytest from Cursor | `CURSOR_EXECUTOR_PREAMBLE` forbids background pytest; prefer `scripts/verify_linux.sh` |
| No audit trail of CLI | `session.json` → `cli_options`, `chatbang_failures` |
| Technical wire in human UI | Seed/follow-ups use `build_human_chatbang_message()` + JSON contract (UA) |

## New CLI flags

- `--continue-on-chatbang-fail` — legacy “run Cursor anyway” after Chatbang errors
- `--no-commit-exclude-dot-governor` — include `.governor/` in auto-commits

## Run (after killing stray chatbang/chrome)

```bash
pkill -f chatbang; pkill -f 'chrome.*chatbang' || true
cd /home/shevchenkool/project/Engineering-agent-governor
bash docs/voice_assistan_run_integration/run_voice_assistant_collab.sh
```

Watch stderr: `[governor collab]`. **COMPLETED** only means max rounds; success needs Chatbang **PASS** in `collab_review.json`.

## Product repo fixes (2026-05-26, same session)

- **`finalize_live_max_aggressive_answer`**: drift/short answers keep ownership clause after `max_sentences_live=3` trim (fixes turn 3 judge collapse).
- **`_leadership` judge**: full senior scaffold → 7.4 (aligned with world-model tail).
- **`google_senior_ai` quality target**: `requires_near_offer_if_another_round: true` (stricter gate; `near_offer` now required with `another_round`).
- **`scripts/eval_collab_session.py`**: honest PASS = Chatbang PASS + `verify_linux` quality gate.
- **`starter_collab_pass_criteria.txt`**: appended to collab seed in `run_voice_assistant_collab.sh`.

After fixes: `bash scripts/verify_linux.sh` → `quality_gate: PASS`, `google_senior_ai` `near_offer: true`, `judge_verdict: another_round` (acceptable per gate).

`live_integration_allowed` stays **false** by policy until human approves live mic path.
