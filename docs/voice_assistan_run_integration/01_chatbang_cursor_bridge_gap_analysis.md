# Chatbang ↔ Cursor bridge: gap analysis для voice assistant run

**Дата:** 2026-05-26  
**Контекст:** ручний міст Chatbang ↔ Cursor (див. `chatbang_cursor_conversation.txt`), ціль — передати це Governor (`python -m governor`, `governor/__main__.py`), репо реалізації — `agents-insiders-test-codex` → `runs/20260502T142452Z_ai_voice_assistant_cli/implementation/voice_assistant/`.  
**Статус Governor:** v1.5.0+ — додано experimental **`governor collab start`** ([CHATBANG_CURSOR_COLLAB_MODE.md](../CHATBANG_CURSOR_COLLAB_MODE.md)); auto-commit лише за policy + `--approve-commit`.

---

## 1. Executive summary (без прикрас)

Ви вже зробили **продуктивний, але ручний** процес: Chatbang виступає суворим рев’юером/архітектором, Cursor — імплементером, ви — **message bus** між двома UI. Engineering Agent Governor **частково покриває окремі шматки** цього пайплайну, але **свідомо не реалізує** те, що ви описуєте як «вони самі почали це робити».

| Що ви хочете | Є в Governor зараз? |
|--------------|---------------------|
| Chatbang дає великий review + промпт агенту | Частково (`governor propose`, `advisor ask`) — **інший формат і контекст** |
| Cursor імплементує в репо | Так (`dispatch` / `run resume` + `cursor-headless-local`) |
| Після змін — **commit**, щоб Chatbang дивився репо (GitHub plugin) | **Ні** — жодного `git commit` у коді Governor |
| Автоматично передати відповідь Cursor → Chatbang | **Ні** |
| Автоматично передати наступний промпт Chatbang → Cursor | **Ні** |
| Багато раундів (reliability patch → report cleanup → shadow-run) | **Ні** — один propose / один advisor ask за виклик |
| Chatbang читає репо через GitHub | **Поза Governor** — залежить від Chatbang + push + вашого акаунта |

**Висновок:** запуск `python -m governor governor propose ...` **не замінить** ваш ручний міст. Це інший продуктовий шар (bounded proposal + human gates), не «два агенти в чаті».

---

## 2. Що показує ваш приклад діалогу (`chatbang_cursor_conversation.txt`)

### 2.1. Фактичний workflow (3 раунди)

```text
[Chatbang]  Аналіз артефакту (zip / repo) → verdict + ризики + великий промпт для агента
     ↓  (ви копіюєте)
[Cursor]  Імплементація → список файлів, команд, статусів
     ↓  (ви копіюєте)
[Chatbang]  Перевірка через GitHub plugin → знаходить розбіжність report vs code
     ↓
[Chatbang]  Другий, вужчий промпт (consistency patch)
```

Це **не** Governor Mode JSON proposal і **не** Advisor envelope `VERDICT / Recommended next action`. Це **довільний інженерний review** з embedded prompt blocks (~300+ рядків), оптимізований під людину-оператора.

### 2.2. Що Chatbang реально перевіряє

- У першому раунді — **розпакований zip** (`voice_assistant_v8.zip`), локальні тести, `manifest_check`.
- У другому — **committed state на GitHub** (`b014dec5...`), `verification_report.md` vs фактичний `security_scan.py`.

Тобто для Chatbang критичні **опубліковані або завантажені артефакти**, а не `.governor/runs/...` і не stdout Cursor з dispatch.

### 2.3. Типові знахідки з діалогу (важливо для автоматизації)

| Проблема | Чому ламає «автопілот» |
|----------|-------------------------|
| Zip ≠ clean `package_release` output | Executor може знову залити «робоче дерево» |
| `verification_report.md` = FAIL після fix коду | Report regeneration не входить у gates за замовчуванням |
| Fake `llm_first_token_ms` | Потрібна доменна експертиза, не generic gate |
| Історичний leaked API key | Chatbang правильно вимагає rotate; Governor gates не замінюють security ops |
| Shadow-run readiness vs live mode | Політичне рішення людини, не PASS gate |

Governor **не знає** про `offer_engine/manifest_check`, `--offer-engine shadow`, post-session audit — поки ви не додасте **project-specific gate profile** у `governor.project.json` цільового репо.

---

## 3. Що є в Engineering-agent-governor (карта можливостей)

### 3.1. Три різні «режими Chatbang» (не плутати)

| Режим | CLI | Що робить | Змінює git? | Multi-turn? |
|-------|-----|-----------|------------|-------------|
| **Governor Mode propose** | `governor governor propose --provider chatbang` | Один JSON-proposal у `.governor/proposals/` | Ні | Ні (1 виклик pexpect) |
| **Governor Mode cursor-auto** | `governor propose --provider cursor-auto` | Те саме, але Cursor **ask/read-only** | Ні | Ні |
| **Advisor** | `governor advisor ask --kind …` | VERDICT-стиль advice у `16_advisor_*.md` | Ні | Ні (кожен ask — новий файл) |
| **Executor** | `dispatch` / `run resume --approve` | Cursor Headless **пише в репо** | Так (якщо не ask mode) | Ні |

Архітектурне правило з документації (і коду):

```text
chatbang/cursor-auto propose → validate → human apply → run + plan ONLY
→ human run resume --approve → executor → gates → validator
```

**Apply v1.2+ не запускає execution.** README прямо: «Governor does not invoke Cursor automatically» на рівні propose.

### 3.2. `chatbang_bridge.py`

- Pexpect: `> ` prompt, timeout, redaction, session prime для propose.
- **Один** round-trip на `run_chatbang_once` / два на `run_chatbang_with_session_prime` (prime + propose).
- Немає збереження **історії сесії Chatbang** між раундами voice-assistant циклу.
- Windows: pexpect **не підтримується** — voice assistant target = Windows → advisor/propose з chatbang лише через **WSL** або окремий Linux host.

### 3.3. Що advisor віддає Chatbang

`build_advisor_context()` включає: run metadata, plan summary, gate JSON **summary**, validator excerpt, trace — **не** включає:

- повний `05_executor_output.md` (лише validator excerpt за замовчуванням);
- `git diff` / `git log` цільового репо;
- вміст `verification_report.md`, zip hashes, live-audit JSONL.

Тобто навіть `advisor ask` **не відтворює** ваш другий раунд «перевірив repo через GitHub plugin».

### 3.4. Gates і git

`governor/gates.py` вміє: `git diff`, secret heuristics, pytest за profile — **не** робить `git commit`, **не** `git push`.

`repo_git.py` — лише `check-ignore` / `ls-files` для audit.

### 3.5. Voice assistant run (agents-insiders-test-codex)

- Шлях: `runs/20260502T142452Z_ai_voice_assistant_cli/implementation/voice_assistant/` — **окремий git worktree** (`main...origin/main`).
- `governor.log` у run folder — **кастомний** workflow log, не `.governor/runs` від пакета `engineering-agent-governor`.
- Ранній dispatch використовував `cursor_cli` (08_dispatch JSON), не обов’язково поточний `python -m governor` CLI з governor repo.

**Розрив:** Governor artifacts живуть у **Engineering-agent-governor** `.governor/`, а код voice assistant — в **іншому репо**. Без явного `--repo-path` на `agents-insiders-test-codex/.../voice_assistant` усі propose/advisor/run будуть дивитися не туди.

---

## 4. Gap matrix: ручний міст vs Governor

| Крок ручного процесу | Governor еквівалент сьогодні | Gap severity |
|---------------------|------------------------------|--------------|
| Chatbang review zip/repo | — / advisor без diff | **Critical** |
| Chatbang → prompt для Cursor | `proposal.executor_prompt` або ручний paste | **High** (формат, довжина, домен) |
| Cursor implement | `dispatch --profile cursor-headless-local` | **Low** (якщо profile налаштований) |
| Cursor → summary назад Chatbang | — | **Critical** |
| `git commit` після змін | — | **Critical** (ваша вимога) |
| Chatbang GitHub review | `git push` + Chatbang plugin | **Critical** (push заборонений політикою Governor) |
| Наступний раунд | новий `advisor ask` вручну | **High** |
| Shadow-run gate / live policy | — | **High** (domain) |

---

## 5. Чи можна «запустити зараз» без нової фічі

### 5.1. Максимально близько до цілі (напівручний скрипт з існуючих команд)

Цільове репо (приклад):

```bash
export VA_REPO=/home/shevchenkool/project/agents-insiders-test-codex/runs/20260502T142452Z_ai_voice_assistant_cli/implementation/voice_assistant
cd "$VA_REPO"
```

**Раунд 0 — ініціалізація Governor на цільовому репо:**

```bash
cd /home/shevchenkool/project/Engineering-agent-governor
.venv/bin/python -m governor project init --repo-path "$VA_REPO"
.venv/bin/python -m governor config init --repo-path "$VA_REPO"
# Увімкнути cursor-headless-local у $VA_REPO/.governor/config.json (локально, gitignored)
```

**Раунд 1 — Chatbang як planner (один shot):**

```bash
.venv/bin/python -m governor governor propose \
  --task "Live Contract Reliability Patch for voice_assistant per chatbang review" \
  --provider chatbang \
  --policy agentic-tooling \
  --repo-path "$VA_REPO"

.venv/bin/python -m governor governor validate --proposal <id> --repo-path "$VA_REPO"
.venv/bin/python -m governor governor apply --proposal <id> --approve --repo-path "$VA_REPO"
```

**Раунд 2 — Cursor execute (людина все ще approve):**

```bash
.venv/bin/python -m governor run resume --run-id <run-id> \
  --approve \
  --executor-profile cursor-headless-local \
  --validator-profile fake-validator \
  --continue-on-gate-warn \
  --repo-path "$VA_REPO"
```

**Раунд 3 — commit (вручну, Governor не зробить):**

```bash
cd "$VA_REPO"
git add -A
git commit -m "feat(live-contract): …"
git push   # якщо Chatbang має дивитись GitHub — інакше він знову не побачить commit
```

**Раунд 4 — Chatbang feedback (вручну):**

```bash
.venv/bin/python -m governor advisor ask --run-id <run-id> \
  --kind evidence-review \
  --question "Review executor output and git state; is verification_report consistent?" \
  --include-prompts \
  --repo-path "$VA_REPO"
```

Потім знову **ви** копіюєте `16_advisor_response_N.md` у Chatbang або навпаки — це **не** автоматичний міст.

### 5.2. Чого цей шлях не дає

- Chatbang **не** отримає автоматично повний diff після Cursor.
- **Немає** циклу «поки Chatbang не скаже HOLD cleared».
- `governor propose` на task «зроби reliability patch» майже напевно дасть **коротший** executor_prompt, ніж ваш 130-рядковий блок з acceptance criteria — або `UNSTRUCTURED` / `EXAMPLE_ECHO` flags.
- Push для GitHub plugin **суперечить** safety validation (`git push` pattern = FAIL у proposal validate).

---

## 6. Що треба **додати** для справжнього bridge (рекомендований дизайн)

### 6.1. Нова підкоманда (пропозиція імені)

`python -m governor collab loop` або `governor bridge run` — **experimental**, opt-in, з жорсткими лімітами.

**Мінімальний MVP loop (1 repo, N rounds):**

```text
FOR round IN 1..max_rounds:
  1. chatbang_review  → prompt_path, verdict (PASS/HOLD/FAIL), stop_reason
  2. IF HOLD or FAIL and human_policy=stop: BREAK
  3. cursor_execute   → dispatch executor (existing) з prompt з кроку 1
  4. git_snapshot     → optional: commit if dirty (policy-gated)
  5. artifact_bundle  → diff stat, test log, executor stdout → наступний chatbang_review
```

### 6.2. Обов’язкові компоненти

| Компонент | Опис |
|-----------|------|
| **`CollabSession` store** | `.governor/collab/<session-id>/round_N/{chatbang_request,chatbang_response,executor_prompt,executor_output,gate_results,git_commit}.json` |
| **Chatbang prompt template `CHATBANG_COLLAB_V1`** | Окремий від `GOVERNOR_MODE_V12` і `_ADVISOR_SYSTEM` — включає diff summary, last commit, test commands output |
| **`run_chatbang_multi`** | Reuse pexpect child **без** закриття між раундами (зараз кожен виклик spawn/close) |
| **`post_executor_commit` policy** | `never` / `if_dirty` / `always`; message template; **ніколи** push за замовчуванням |
| **Feed-forward** | Парсер «наступний промпт» — fenced ` ```text ` block або JSON field `next_executor_prompt` |
| **Domain gate profile** | У `voice_assistant` repo: `governor.project.json` з кроками `manifest_check`, `test_live_offer_integration`, `package_release` |
| **Human checkpoint** | Після кожного round або перед commit — `--approve-round` |

### 6.3. Auto-commit: окрема політика, не «завжди сліпо»

Ваша вимога «Cursor завжди commit після змін» **конфліктує** з:

- user rule «only commit when user asks» (у Cursor agent);
- Governor anti-autopilot (README);
- ризиком commit **generated reports FAIL**, secrets, `__pycache__` (ваш власний діалог).

**Рекомендація:** commit лише якщо:

1. `git diff --stat` non-empty tracked files;
2. gates `fast` PASS (або `--continue-on-gate-warn` явно);
3. `git diff --check` clean;
4. **не** commit paths з `.gitignore` / `reports/` якщо policy `exclude_generated_reports`;
5. human `--approve-commit` або config `collab.auto_commit: if_gates_pass`.

Для Chatbang GitHub review — окремий крок `collab publish` з **`--approve-push`** (explicit), не default.

### 6.4. Альтернатива без push

Якщо Chatbang вміє читати **локальний folder** (zip upload), автоматизація може:

- `package_release` → upload path у prompt;
- або `git bundle` / patch artifact у `collab/round_N/repo_snapshot.zip`.

Це ближче до вашого **першого** раунду діалогу, ніж до GitHub plugin.

---

## 7. Справжня критика (процес, інструменти, очікування)

### 7.1. Governor не був спроєктований як «два ChatGPT в циклі»

Документація багаторазово фіксує **anti-patterns**:

- no auto-apply / auto-resume after propose (`GOVERNOR_PROVIDER_INNOVATION.md`);
- do not merge provider and advisor code paths;
- chatbang is **not** executor.

Ваш ручний міст — **операційний патерн двох сильних моделей + людина**, що суперечить філософії Governor «human approves every execution step». Це не баг — **product mismatch**.

### 7.2. Ручний міст ховав системні проблеми — автоматизація їх викриє

| Shady moment | Деталь |
|--------------|--------|
| **Два джерела правди** | Cursor каже PASS; committed `verification_report.md` = FAIL — ви помітили лише через Chatbang GitHub pass |
| **Zip hygiene theater** | `voice_assistant_v8.zip` з `__pycache__` при заяві «self-verifiable» — automation без `package_release` gate повторить |
| **Security** | Hardcoded key прибрали з коду, але rotate/revoke лишається — commit loop **не** закриває history |
| **Metric gaming** | `first_token_at = offer_started_at` — executor «виправив» метрики в тексті, report лишився stale |
| **Shadow state honesty** | Архітектурно правильно, але легко зламати benchmark якщо automation ганяє shadow без isolated policy |
| **Chatbang GitHub plugin** | Непрозорий контекст (що саме бачить модель), versioning lag vs local HEAD |
| **Governor proposals gitignored** | `.governor/proposals/` не в git — audit trail лише локально |
| **Cross-repo confusion** | Governor runs в одному місці, код в іншому — легко propose не на той `repo-path` |
| **pexpect fragility** | Echo prompt, timeout 300s, `[Thinking...]` stripping — flaky у CI і під навантаженням |

### 7.3. Voice assistant scope vs Governor generic gates

Проєкт — **high-risk live audio + offer engine + verification theater** (judge, red-team, proof packs). Generic `pytest` + `git diff` gate **не замінить** Chatbang-рівень review без **10+ custom checks**.

### 7.4. Вимога «завжди commit»

Небезпечна як default:

- комітить FAIL reports, великі JSONL audits, replay artifacts;
- створює шум для Chatbang review;
- ускладнює `git revert` при помилковому executor run.

Краще: **commit only verification-clean snapshot** або **commit + tag `chatbang-round-N`**.

---

## 8. Ризики при впровадженні bridge

| Риск | Імовірність | Вплив | Мітигація |
|------|-------------|-------|-----------|
| Нескінченний ping-pong Chatbang↔Cursor | Висока | Гроші, час, drift | `max_rounds`, budget, stop on repeated HOLD |
| Chatbang session context drift | Висока | Повтори, суперечності | Persistent pexpect + session summary file |
| Executor ігнорує частину промпту | Середня | False PASS | Domain gates + validator profile (не fake-validator) |
| Auto-commit секретів | Середня | Critical | secret scan gate, path allowlist |
| Push без review | Низка/середня | Critical | окремий `--approve-push`, never default |
| Windows dev / Linux governor | Висока | Flaky audio tests | split: implement on Windows runner profile |
| Два формати prompt (V12 vs collab vs advisor) | Висока | Parser breaks | один canonical JSON schema для collab round-trip |
| False confidence від Governor PASS gates | Середня | Production incident | Chatbang round з explicit «shadow-only» policy |

---

## 9. Варіанти дій (від швидкого до правильного)

### Варіант A — «Сьогодні», без коду Governor (2–4 год)

1. Фіксований `VA_REPO` + shell script з 4 кроками (propose → apply → resume → **manual commit** → advisor ask).
2. У `VA_REPO` додати `governor.project.json` з gate profile `voice_assistant_release` (manifest + tests + security_scan).
3. Chatbang лишається з GitHub plugin; ви pushите лише після green gates.

**Плюс:** швидко. **Мінус:** ви все ще bridge.

### Варіант B — «Тонкий collab MVP» у Governor (3–5 днів dev)

1. `governor/collab_loop.py` + CLI `governor collab start --repo-path … --task-file …`.
2. Reuse `dispatch` + `run_chatbang_with_session_prime` + optional `repo_git.commit_if_dirty()`.
3. Prompt contract: Chatbang returns JSON `{verdict, next_executor_prompt, required_commands[]}`.
4. Tests з `fake_chatbang.py` + fake cursor.

**Плюс:** закриває 80% болю. **Мінус:** experimental, потрібна дисципліна prompt schema.

### Варіант C — «Повний product» (2+ тижні)

- Collab loop + domain gates у voice repo + publish step + evaluation metrics per round + dashboard.
- Окремий Windows executor profile для STT smoke (не в WSL).

---

## 10. Рекомендований наступний крок (конкретно)

1. **Прийняти рішення по `repo-path`:** усі Governor команди на  
   `agents-insiders-test-codex/.../implementation/voice_assistant`, не на `Engineering-agent-governor`.

2. **Не очікувати, що `governor propose` замінить Chatbang review** — для voice assistant потрібен **окремий collab prompt** з diff + verification artifacts.

3. **Замість «завжди commit»** — policy:
   - `commit` після PASS custom gate profile;
   - `push` лише з `--approve` для Chatbang GitHub;
   - regenerate `verification_report.md` у gate, не вручну в промпті.

4. **Якщо писати фічу в Governor** — почати з **Варіант B**, файли:
   - `governor/collab_loop.py`
   - `governor/repo_git.py` — extend: `commit_snapshot(message, paths_allowlist)`
   - `docs/CHATBANG_CURSOR_COLLAB_MODE.md`
   - `tests/test_collab_loop.py` + `scripts/smoke_collab_fake_workflow.py`

5. **Перший end-to-end тест collab** — вузький task з діалогу:  
   «Regenerate verification reports + fix misleading llm_first_token_ms» (другий промпт у conversation.txt) — measurable, мало scope.

---

## 11. Довідка: релевантні файли в Governor repo

| Файл | Роль |
|------|------|
| `governor/__main__.py` | Entry → `governor.cli:main` |
| `governor/governor_mode.py` | propose/validate/apply |
| `governor/chatbang_bridge.py` | pexpect Chatbang |
| `governor/advisor.py` | advisor ask (інший envelope) |
| `governor/dispatch.py` | Cursor executor |
| `governor/run_plan.py` | plan execute steps |
| `governor/gates.py` | git diff, tests — no commit |
| `docs/CHATBANG_GOVERNOR_MODE.md` | propose lifecycle |
| `docs/CHATBANG_GOVERNOR_ADVISOR.md` | advisor vs propose |
| `docs/CURSOR_HEADLESS_RUNNER.md` | executor setup |
| `docs/ARCHITECTURE.md` | role boundaries |

---

## 12. Verdict по запиту користувача

| Питання | Відповідь |
|---------|-----------|
| Чи можна зараз запустити `governor/__main__.py` і отримати повний автоматичний Chatbang↔Cursor bridge? | **Ні** |
| Чи є зачатки? | **Так:** propose + dispatch + advisor + gates — але **не з’єднані** в loop і **без commit/push** |
| Чи варто додавати фічу? | **Так**, як окремий **Collab Mode** з explicit policies — не розширювати silently `governor propose` |
| Чи безпечна вимога auto-commit always? | **Ні** як default — лише після gates + allowlist |
| Чи готовий voice assistant до shadow-run після automation? | **Лише після** report consistency + domain gates — як у вашому діалозі, automation не скасовує це |

**Статус документа:** planning / gap analysis complete — **не** implementation complete.
