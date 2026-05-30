# Breakthrough ideas track (voice assistant + collab)

Product repo maintains the canonical registry:

`voice_assistant/docs/breakthrough_ideas/00_INDEX.md`

## Active: B01 bidirectional interview simulator

Aligns with human seed goal: train the **whole interview game**, not only candidate monologue.

```bash
cd <voice_assistant_root>
bash scripts/run_bidirectional_sim_mvp.sh
```

**Gates (2026-05-30):**

```bash
bash scripts/verify_light.sh      # daily
bash scripts/verify_linux.sh      # full L1 — use verification_watchdog.sh run -- …
bash scripts/run_b01_stability.sh # 3× B01 offer check
```

Fork-bomb fix + mock isolation: `docs/incidents/20260530_fork_bomb_run_full_verification.md`

Governor collab can target B01 improvements when Chatbang PASS requires judge `offer` on **adaptive** sessions, not only fixed transcript replay.

## Operating model

1. **Ship** — verify_linux + check_offer_gate (L1–L2)
2. **Experiment** — one breakthrough ID per week, artifacts in `reports/experiments/`
3. **Promote** — merge only if gate non-regressing + experiment verdict positive

## Link to collab

`starter_collab_pass_criteria.txt` + `eval_collab_session.py` — collab PASS = release + judge `offer`.

Optional stretch for collab round: improve B01 until `hiring_recommendation` stable across 3 sim seeds.
