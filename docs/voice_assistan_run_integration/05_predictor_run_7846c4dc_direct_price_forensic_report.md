# Forensic Addendum: predictor run `7846c4dc-9eaf-4f57-892e-d4a8d6f440d7`

**Дата аналізу:** 2026-05-27  
**Run ID:** `7846c4dc-9eaf-4f57-892e-d4a8d6f440d7`  
**Repo under analysis:** `/home/shevchenkool/project/tender-ai-price-item-predictor`  
**Related earlier report:** `04_predictor_run_9a54dabe_direct_price_forensic_report.md`

---

## 1. Executive summary

This run has the same surface symptom as `9a54...`:

1. prediction rows are `done`;
2. `median_price` is populated;
3. `analytics_direct_price` is `NULL`;
4. there are no `price_prediction_analytics_links` rows.

But the root cause is **different**.

For run `7846...`, the direct-price candidate is **not rejected by matching logic on the full lot**.
It is lost because the active canonical path performs matching on the **current batch rows only**, while the direct-price match for this lot requires the **entire lot context**.

In plain language:

- the current active pipeline can match the lot if it sees both lot items together;
- the actual run processed the two target items in separate batches/transactions;
- each partial batch was insufficient for multi-item direct-price matching;
- therefore `direct_price_info` stayed empty and nothing was written.

This is a stronger architectural bug than the `9a54...` case.

The `9a54...` problem was a bad name gate.
The `7846...` problem is that the active pipeline is **batch-shape dependent** for multi-item exact-lot direct pricing.

That means direct-price behavior now depends on how rows happen to be chunked, not only on the data itself.

That is a bad runtime contract.

---

## 2. Live facts from the run

### Run row

- `id = 7846c4dc-9eaf-4f57-892e-d4a8d6f440d7`
- `status = completed`
- `pipeline_version = predictor-e07-price-cluster-selector`
- stored `git_sha = 56f7a0f0e3f033378ca2336b8c9bc21e83b3abd9`

Same provenance warning from the earlier report still applies: stored SHA is env-driven metadata, not trustworthy execution truth.

### Prediction rows in this run

There are exactly 2 prediction rows:

1. `f78d8213-24fe-4707-a45d-20b631b5fbfb`
   - `median_price = 2915.0`
   - all `analytics_direct_* = NULL`
   - `computed_at = 2026-05-27 05:39:29.751729+00:00`
2. `355b3800-c230-413b-9834-a2a6e5eb1245`
   - `median_price = 3645.0`
   - all `analytics_direct_* = NULL`
   - `computed_at = 2026-05-27 05:39:33.604091+00:00`

### Analytics link rows

- `0` rows for this run.

### Lot structure

Both items belong to the same lot:

- `lot_id = 26370104`

Lot contents from classification log:

1. `f78d8213-24fe-4707-a45d-20b631b5fbfb`
   - name: `Опори повітряних ліній електропередачі дерев'яні L=8м`
   - quantity: `480`
   - unit: `шт.`
2. `355b3800-c230-413b-9834-a2a6e5eb1245`
   - name: `Опори повітряних ліній електропередачі дерев'яні L=10м`
   - quantity: `10`
   - unit: `шт.`

BQ rows for the same lot:

1. `L=8м`, quantity `480`, `price_no_vat = 2915.0`
2. `L=10м`, quantity `10`, `price_no_vat = 3645.0`

Lot reference amounts:

- `winner_amount = 1722780.0`
- `budget_amount = 1435650.0`
- `vat_rate = NULL`

---

## 3. The crucial evidence

### 3.1. Current canonical direct lookup fails on partial lot input

Live recomputation using the current active helper [predictor/services/direct_price_lookup.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/services/direct_price_lookup.py#L17) on a single item from this lot returns:

- `canonical_partial_batch = {}`

That is expected from the current canonical design, because the service passes only the provided rows into `DirectPriceMatchService.match_payloads(...)` at [predictor/services/direct_price_lookup.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/services/direct_price_lookup.py#L46).

For multi-item lots, the matcher explicitly rejects incomplete lot context at [predictor/services/direct_price.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/services/direct_price.py#L225):

- if `len(items) <= 1` or `len(items) != len(bq_rows)`, return `{}`.

So a batch that sees only one item from a two-item lot cannot produce a multi-item direct-price result.

### 3.2. Current canonical direct lookup succeeds if given the full lot

Using the same current canonical service on the full lot item set returns:

- both items matched;
- `analytics_direct_match_type = multi_item_exact_lot_quantity`;
- `analytics_direct_price = 2915.0` / `3645.0`;
- current canonical confidence = `low`.

That means the current active logic is **capable** of matching this lot, but only when the lot is presented whole.

### 3.3. Compatibility-era full-lot hydration also succeeds from a single selected item

Using the older full-lot hydration approach from [predictor/direct_price_join.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/direct_price_join.py#L43) plus [predictor/direct_price_join.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/direct_price_join.py#L323) on the same lot returns:

- both items matched;
- same direct prices;
- historical-style confidence = `high`.

This is the sharpest regression proof in the whole case.

The old approach said, effectively:

> if I see a row from lot `26370104`, I load the full lot and then match.

The current active approach says:

> I match only whatever rows happened to arrive in this batch.

That is the behavioral break.

### 3.4. Historical DB state confirms this lot previously had direct prices stored

For both items, historical run `92234c9f-afd3-4f51-96f7-adf2ca1886a6` already contains:

- `analytics_direct_price` populated;
- `analytics_direct_match_type = multi_item_exact_lot_quantity`;
- `analytics_direct_match_confidence = high`.

So this is not a case where the lot never supported direct pricing.

---

## 4. Why I am confident the actual run split the lot into separate batches

There are two strong indicators.

### Indicator 1. The two row timestamps differ materially

The two prediction rows have:

- `05:39:29.751729`
- `05:39:33.604091`

That matters because the active writer uses `write_batch(...)` at [predictor/repositories/price_prediction_writer.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/repositories/price_prediction_writer.py#L530), and the SQL upsert sets `computed_at = NOW()` at [predictor/sql/price_prediction/upsert_prediction.sql](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/sql/price_prediction/upsert_prediction.sql#L41).

Within a single DB transaction, `NOW()` is transaction-scoped. If both rows had been written in one `write_batch(...)` transaction, their `computed_at` values should have been the same transaction timestamp.

They are not.

So these rows were written in separate transactions, which strongly indicates separate batches.

### Indicator 2. The active target-id runner chunks by `BATCH_SIZE`

The target-id path in [predictor/pipeline/job_runner.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/pipeline/job_runner.py#L217) does:

1. iterate over `target_ids` in chunks of `container.settings.BATCH_SIZE`;
2. fetch only the rows for that chunk;
3. pass those rows to the batch processor.

So if two target IDs from the same lot are processed with `BATCH_SIZE=1`, the direct-price lookup sees them one-by-one and loses multi-item lot context.

That fits the observed data exactly.

---

## 5. Root cause

### Immediate root cause

The active canonical direct-price lookup is batch-local.

It does not hydrate full classification lot contents before multi-item direct-price matching.

So partial batches from a multi-item lot produce no direct-price payload even when the full lot is perfectly matchable.

### Architectural root cause

The pipeline has mixed assumptions:

1. direct-price matching for multi-item exact lots is a **lot-level** operation;
2. the active runtime hands the matcher **batch-level slices** that may contain only a subset of lot items.

Those assumptions are incompatible.

You cannot have a lot-level matcher and then feed it arbitrary row slices while expecting stable results.

### Why this is worse than a simple target-id edge case

This does not only threaten manually targeted runs.

Any path that batches rows without lot completeness guarantees is suspect:

1. `TARGET_ITEM_IDS` runs when `BATCH_SIZE` is smaller than lot size;
2. full-scan runs if keyset pagination splits lot items across batch boundaries;
3. missing-median runs if batch boundaries do not respect lot completeness.

In other words, this is a runtime contract problem, not a one-off operator mistake.

---

## 6. Secondary drift: confidence semantics also diverged

Even when I recomputed the full lot through the current canonical service, it returned `analytics_direct_match_confidence = low`.

Historical rows for the same lot have `high`.

This is a second, separate discrepancy.

The most likely reason is this:

1. the current canonical confidence path goes through [predictor/strategies/confidence/budget_total.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/strategies/confidence/budget_total.py#L14), where budget match can at most become `medium`;
2. before that, it tries to normalize budget/winner totals through [predictor/services/vat.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/services/vat.py#L41);
3. with `vat_rate = NULL`, `VatNormalizer.to_net(...)` returns `None` at [predictor/services/vat.py](/home/shevchenkool/project/tender-ai-price-item-predictor/predictor/services/vat.py#L44), which can collapse the fallback to `low`.

Meanwhile the older compatibility helper in `direct_price_join.py` effectively used a simpler raw-total comparison and returned `high`.

This does **not** explain why run `7846...` lost direct price entirely.
But it does show another new/old semantic drift that should be audited.

---

## 7. Serious criticism

### Criticism 1. The active canonical path regressed a valid historical behavior

The old behavior could recover multi-item direct pricing from partial selected rows because it rehydrated the full lot.

The active canonical path cannot.

That is a regression in practical correctness, even if it was introduced during architectural cleanup.

### Criticism 2. The runtime contract is underspecified and unsafe

A direct-price feature that depends on full-lot context should either:

1. enforce lot-complete batching; or
2. fetch the full lot internally.

The current design does neither.

That is not a small edge bug. That is a broken abstraction boundary.

### Criticism 3. The observability is too weak for this class of failure

Nothing in the persisted prediction rows says:

- `direct_price skipped because partial lot context`
- `lot has 2 classification items but batch had 1`
- `multi-item exact-lot match impossible with current batch slice`

So again, the operator sees `done` rows and no direct price, with no stored reason.

### Criticism 4. Historical comparison is still polluted by weak provenance

As in the earlier report, the stored `git_sha` cannot be trusted as forensic execution truth.
So even when we say “historical run behaved differently”, the DB metadata is not sufficient proof of which code actually ran.

That is still a serious governance problem.

---

## 8. What I would do

### Priority 1. Fix the runtime contract for multi-item direct-price lookup

I would change the active direct-price lookup path so that matching operates on **full lot classification rows**, not only the current batch slice.

Concretely, for the active path I would do one of these:

1. when a batch contains any rows for lot `L`, load all classification items for lot `L` before calling the matcher;
2. compute direct-price map on full lot rows, then filter the results back to only the batch items being written;
3. or guarantee lot-complete batching everywhere direct-price matching is expected.

My preference is option 2.

Reason:

- it preserves current write scope;
- it decouples match correctness from batch shape;
- it avoids forcing batch orchestration to become lot-aware in every runner mode.

### Priority 2. Add regression tests for partial-lot batches

I would add tests that explicitly prove:

1. batch contains one item from a two-item lot;
2. canonical direct-price lookup still produces direct matches for the batch item by hydrating the full lot;
3. target-id path with `BATCH_SIZE=1` does not lose multi-item direct price.

Without this, the same regression will come back.

### Priority 3. Add item-level miss reason telemetry

At minimum, log structured reasons like:

1. `partial_lot_context`
2. `multi_item_lot_requires_full_context`
3. `lot_batch_incomplete`

This should exist in structured logs, and ideally in persisted evidence when a direct-price candidate is skipped.

### Priority 4. Audit the confidence drift separately

This is a separate task from restoring direct-price presence.

I would compare:

1. old compatibility confidence semantics;
2. current canonical confidence semantics;
3. the effect of `vat_rate = NULL` on budget-based fallback.

This deserves its own focused fix after the lot-hydration bug is corrected.

### Priority 5. Fix provenance truthfulness

Same recommendation as before:

1. record actual repo HEAD when available;
2. record dirty-worktree status;
3. do not use env `GIT_SHA` as if it were precise execution truth.

---

## 9. Bottom line

For run `7846...`, the problem is not “we had no direct-price candidate”.

We did have one.
In fact, we had both multi-item direct-price matches for the lot.

The active runtime lost them because it matched on partial batch context instead of full lot context.

That means:

1. the current direct-price outcome is batch-shape dependent;
2. the active canonical path regressed useful old behavior;
3. multi-item direct-price can silently disappear in valid runs when lot items are split across batches.

That is a real architectural defect.
