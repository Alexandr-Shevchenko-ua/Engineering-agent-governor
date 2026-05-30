# Confidence Addendum: predictor run `0dd31633-63c0-4ebe-8b27-7c0363d9c487`

**Дата аналізу:** 2026-05-27  
**Run ID:** `0dd31633-63c0-4ebe-8b27-7c0363d9c487`  
**Related runs:** `7846c4dc-9eaf-4f57-892e-d4a8d6f440d7`, `92234c9f-afd3-4f51-96f7-adf2ca1886a6`  
**Repo under analysis:** `/home/shevchenkool/project/tender-ai-price-item-predictor`

---

## 1. Короткий висновок

У run `0dd31633...` проблема з `BATCH_SIZE` вже зникла:

1. `analytics_direct_price` записався для обох items;
2. `price_prediction_analytics_links` теж записались;
3. `match_type = multi_item_exact_lot_quantity` для обох rows.

Тобто full-lot direct-price matching тут уже відпрацював.

Але `analytics_direct_match_confidence` лишився `low` не через batching і не через відсутність direct-price candidate.

Причина інша:

1. canonical confidence path спершу намагається нормалізувати `winner_amount` і `budget_amount` через VAT normalizer;
2. у цього lot `vat_rate = NULL`;
3. через це normalized winner total і normalized budget total стають `None`;
4. далі contract confidence branch і budget confidence branch не мають reference total для порівняння;
5. система падає у fallback `low`.

Отже поточний `low` означає не “match слабкий”, а “current canonical confidence logic не змогла порахувати reference-side comparison”.

---

## 2. Факти з БД

### Run row

- `id = 0dd31633-63c0-4ebe-8b27-7c0363d9c487`
- `status = completed`
- `pipeline_version = predictor-e07-price-cluster-selector`
- stored `git_sha = 56f7a0f0e3f033378ca2336b8c9bc21e83b3abd9`

### Prediction rows

Для обох items записано:

1. `analytics_direct_price`
2. `analytics_direct_match_type = multi_item_exact_lot_quantity`
3. `analytics_direct_match_confidence = low`
4. `analytics_direct_bq_item_id`

Items:

1. `f78d8213-24fe-4707-a45d-20b631b5fbfb`
   - `median_price = 2915.0`
   - `analytics_direct_price = 2915.0`
2. `355b3800-c230-413b-9834-a2a6e5eb1245`
   - `median_price = 3645.0`
   - `analytics_direct_price = 3645.0`

### Analytics links

Для обох items є `price_prediction_analytics_links` rows, теж із `match_confidence = low`.

Це остаточно підтверджує, що direct price вже не губиться, а саме отримує low confidence.

---

## 3. Дані lot, які визначають confidence

Lot: `26370104`

Direct-price totals:

1. `2915 * 480 = 1,399,200`
2. `3645 * 10 = 36,450`
3. total = `1,435,650`

Reference amounts:

1. `winner_amount = 1,722,780`
2. `budget_amount = 1,435,650`
3. `vat_rate = NULL`

Найважливіший факт:

- direct-price total **ідеально збігається** з raw `budget_amount`;
- direct-price total **не збігається** з `winner_amount`.

---

## 4. Чому current canonical code дає `low`

### Крок 1. Service рахує predicted total правильно

Для цього lot canonical path отримує:

- `predicted_total = 1435650.00`

Тут проблеми немає.

### Крок 2. Service пробує взяти normalized winner total

Winner branch йде через `DirectPriceMatchService._normalized_reference_total(...)`.

Вона викликає VAT normalizer для `winner_amount`.

Але оскільки `vat_rate = NULL`, VAT normalizer повертає `None`.

Result:

- `winner_total_normalized = None`

### Крок 3. Service пробує взяти normalized budget total

Те саме відбувається для `budget_amount`.

Попри те, що raw `budget_amount` точно дорівнює predicted total, code не порівнює raw budget amount напряму. Він теж жене його через VAT normalization.

Знову через `vat_rate = NULL` виходить:

- `budget_total_normalized = None`

### Крок 4. Contract confidence branch automatically fails

Коли `reference_total is None`, totals-match branch не може сказати “matched”.

Result:

- contract decision = `low`

### Крок 5. Budget confidence branch теж automatically fails

З тієї ж причини:

- budget decision = `low`

Тобто не тому, що budget mismatch, а тому що budget reference total до branch-а не дожив як число.

### Крок 6. Fallback теж `low`

Коли contract і budget branches не спрацьовують, service падає у fallback:

- fallback decision = `low`

Саме це і записується в БД.

---

## 5. Найважливіша інтерпретація

`low` тут не означає, що direct match сумнівний по item-level structure.

Навпаки, lot виглядає доволі сильним:

1. balanced multi-item lot;
2. кількість classification rows і BQ rows збігається;
3. quantities match;
4. units match;
5. direct-price total точно збігається з raw budget amount.

Поточний `low` означає лише одне:

> canonical confidence logic не вміє коректно оцінити budget-side confidence, коли `vat_rate` відсутній.

Це дуже важлива різниця.

---

## 6. Чому historical run міг мати `high`

Historical run `92234c9f...` для тих самих items зберіг:

- `analytics_direct_match_confidence = high`

Це означає, що current canonical semantics розійшлися з earlier behavior.

Найімовірніше пояснення:

1. older path порівнював raw lot totals без жорсткої залежності від `vat_rate`;
2. current canonical path пропускає reference totals через `VatNormalizer.to_net(...)`;
3. якщо VAT не заданий, raw budget/winner signal effectively втрачається.

---

## 7. Серйозна критика

### Criticism 1. Current confidence semantics over-penalize missing VAT

У цьому lot direct-price total точно збігається з raw budget amount.

Сказати `low` у такій ситуації означає, що code більше карає за відсутній metadata field, ніж нагороджує за точний monetary alignment.

Це слабка operational semantics.

### Criticism 2. Budget-side exact match is being silently undervalued

Навіть якщо виправити `vat_rate=NULL` handling, поточний budget branch за design-ом у кращому разі дає `medium`, не `high`.

Тобто current policy already treats exact budget alignment as weaker evidence than winner alignment.

Це може бути допустимий policy choice, але зараз він ще й маскується тим, що при missing VAT branch узагалі не працює.

### Criticism 3. Confidence label currently mixes data quality and evidence quality

`low` тут використовується і для:

1. реально слабких direct matches;
2. випадків, де немає reference total;
3. випадків, де reference total theoretically є, але code не зміг його нормалізувати через missing VAT.

Це semantic overload. Такий `low` погано читається операційно.

---

## 8. Що я б робив

### Priority 1. Add explicit fallback for missing VAT

Якщо `vat_rate` відсутній, але `predicted_total` точно збігається з raw `budget_amount` або raw `winner_amount`, current code не повинен просто звалюватися в `low`.

Я б додав окрему branch-логіку:

1. спочатку спроба normalized comparison;
2. якщо normalization неможлива через missing VAT, fallback to raw comparison;
3. записати в evidence, що confidence based on raw reference without VAT normalization.

### Priority 2. Separate “no reference evidence” from “low confidence match”

Було б чесніше мати окремий label або reason для ситуацій типу:

- `reference_missing`
- `reference_unusable_due_to_missing_vat`

замість того, щоб усе стискати в один `low`.

### Priority 3. Decide policy explicitly for exact budget matches

Тут треба прийняти явне рішення:

1. exact winner match = `high`
2. exact budget match = `medium`
3. або exact budget match теж може бути `high` у певних cohorts

Але це має бути policy choice, а не побічний ефект missing VAT.

---

## 9. Bottom line

Для run `0dd31633...` direct-price path уже працює правильно по batching.

Поточний `low` виникає тому, що:

1. direct total = `1435650.00`;
2. raw `budget_amount = 1435650.0`;
3. `vat_rate = NULL`;
4. canonical code не може перетворити budget/winner reference у normalized total;
5. обидва confidence branches залишаються без reference total;
6. фінальний verdict = `low`.

Тобто це вже не lookup bug, а confidence-policy / missing-VAT handling bug.