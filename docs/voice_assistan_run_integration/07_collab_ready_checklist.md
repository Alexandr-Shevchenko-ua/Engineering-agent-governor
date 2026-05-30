# Collab ready checklist (2026-05-30)

## Product gates (must be green before `governor collab start`)

```bash
cd <voice_assistant>
bash scripts/iter_gate.sh          # light + B01 + B08 + B05 (skip w/o API) + B10
bash scripts/pre_collab_gate.sh     # before collab (stability + shadow)
# optional offline: OPENAI_API_KEY=... bash scripts/run_b05_ab_compare.sh
bash scripts/raise_the_bar_gate.sh  # milestone: + full verify_linux (logs milestone_gate_index.jsonl)

Product doc: `<voice_assistant>/docs/COLLAB_READY.md`
```

Expected:

| Check | Signal |
|-------|--------|
| verify_linux | `verification_gate: PASS` |
| check_offer_gate | `independent_judge.offer: offer` |
| B01 sim | `"hiring_recommendation": "offer"` |
| B01 stability | `"all_offer": true` (3/3) |
| shadow live | ownership phrases present |

## RAM safety

- **Never** background `verify_linux` without watchdog.
- If `pgrep -c voice_assistant/.venv/bin/python` > 24 → `pkill -9 -f voice_assistant/.venv/bin/python` then re-run gates.
- Incident: `voice_assistant/docs/incidents/20260530_fork_bomb_run_full_verification.md`

## Chatbang PASS contract

See `starter_collab_pass_criteria.txt` — judge **offer** required, not only `another_round`.

## Eval session

```bash
python scripts/eval_collab_session.py <session_dir>
```

`product_ok` requires `judge_verdict == offer`.

## Optional experiments (raise the bar further)

- **B07** claim memory — on by default in B01 + live adapter (`claim_memory` in session summary).
- **B05** LLM interviewer — `export OFFER_ENGINE_LLM_INTERVIEWER=1` + `OPENAI_API_KEY`; `bash scripts/run_b05_llm_interview.sh`.
- **B10** counterfactual — `bash scripts/run_b01_counterfactual.sh`.
