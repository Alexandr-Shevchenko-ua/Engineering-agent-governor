# Collab ready checklist (2026-05-30)

## Product gates (must be green before `governor collab start`)

```bash
cd <voice_assistant>
bash scripts/pre_collab_gate.sh

# Milestone / major collab round (highest bar):
bash scripts/raise_the_bar_gate.sh
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
- B07 claim memory in product B01 + live path
- B05 LLM interviewer: OFFER_ENGINE_LLM_INTERVIEWER=1 + OPENAI_API_KEY
