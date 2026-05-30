# Forensic Report: predictor run `9a54dabe-bf52-4946-bdc5-fed22ef1da7f` and missing `analytics_direct_price`

**Дата аналізу:** 2026-05-27  
**Run ID:** `9a54dabe-bf52-4946-bdc5-fed22ef1da7f`  
**Target item ID:** `224a1474-2ad0-48d3-9a33-bcfb890991ed`  
**Lot ID:** `26380138`  
**Repo under analysis:** `/home/shevchenkool/project/tender-ai-price-item-predictor`  
**Artifact owner repo:** `/home/shevchenkool/project/Engineering-agent-governor`  
**Analyst stance:** harsh, evidence-first, no polite smoothing

---

## 1. Executive summary

The run was **technically successful** and the prediction row is `status=done`, but the missing `analytics_direct_price` is **not** a writer bug and **not** a SQL upsert bug.

The direct-price payload was **never produced** on the live path.

The evidence is direct:

1. `price_prediction.analytics_direct_*` is fully `NULL` for this run/item.
2. `price_prediction.evidence_json` does **not** contain `analytics_direct_price`.
3. `price_prediction_analytics_links` has **no row** for this run/item.
4. Live recomputation through the repo's current active components returns:
	 - `direct_map_item_only = {}`
	 - `direct_map_full_lot = {}`

So the loss happens **before persistence**, inside direct-price matching.

The deeper conclusion is worse than “enrichment missing”.

This item has a very strong direct-price candidate:

1. single-item lot;
2. one BQ row for the same lot;
3. unit matches canonically (`шт` -> `штука`, `Штука` -> `штука`);
4. quantity matches exactly (`34000`);
5. BQ `price_no_vat = 9.0`;
6. `9.0 * 34000 = 306000`, which matches `winner_amount = 306000` exactly.

And yet the service rejects the match because the current name gate uses a **symmetric Jaccard threshold** against a very long BQ product description.

That means the system is currently capable of returning a confident predictor price of `139.0`, while silently dropping a structurally stronger direct-price candidate of `9.0`.

That is not a cosmetic miss. That is a real correctness and observability problem.

---

## 2. Critical findings

### Finding 1. The missing direct price is a **lookup-stage false negative**, not a persistence failure

Observed Postgres row for run `9a54...` and item `224a...`:

- `status = done`
- `median_price = 139.0`
- `analytics_direct_price = NULL`
- `analytics_direct_match_type = NULL`
- `analytics_direct_bq_item_id = NULL`
- `evidence_json` has no `analytics_direct_price` block
- `price_prediction_analytics_links` has no rows

Implication:

- `PricePredictionWriter` did not drop a non-empty payload.
- `PredictionWriteRequest.direct_price_info` reached the writer as `None`.

This matters because it narrows the root cause sharply:

- **not** `upsert_prediction.sql`
- **not** `upsert_analytics_links.sql`
- **not** transaction scope in `write_batch()`
- **not** a partially failed insert

The problem sits upstream, in `load_direct_price_map_for_rows(...)` / `DirectPriceMatchService`.

### Finding 2. Structurally, this lot looks like a very strong direct-price candidate

Live repository inspection found:

- classification item:
	- name: `Вставка контактна тролейбусна`
	- unit: `шт`
	- quantity: `34000.0`
	- lot_id: `26380138`
- lot size in classification log: `1`
- BQ rows for the lot: `1`
- BQ row:
	- same lot id
	- name starts with the same product concept, then contains a long technical specification tail
	- unit: `Штука`
	- quantity: `34000`
	- `price_no_vat = 9.0`
	- `bq_item_id = d69b09ce16d64364b650c11d59fcbf3e`
- lot reference amounts:
	- `winner_amount = 306000.0`
	- `budget_amount = 476000.0`

Calculated totals:

- direct-price total: `9.0 * 34000 = 306000.0`
- predictor total: `139.0 * 34000 = 4726000.0`

Ratios:

- predictor unit price vs direct unit price: `15.44x`
- predictor total vs winner amount: `15.44x`
- predictor total vs budget amount: `9.93x`
- direct total vs winner amount: `1.0x` exact

This is the strongest practical signal in the whole case.

The direct-price candidate is not some vague side hint. It is the only value in this analysis that aligns perfectly with the lot's winner amount.

### Finding 3. The rejection is caused by the current name matcher design

The single-item gate in `DirectPriceMatchService._match_single_item_lot(...)` checks:

1. unit compatibility;
2. `ItemNameMatcher.is_compatible(...)`;
3. quantity present and positive;
4. `price_no_vat` present.

For this item, the only failing gate is the name gate.

Live measurements using the same tokenizer and matcher logic:

- left unique tokens: `3`
	- `вставка`, `контактна`, `тролейбусна`
- right unique tokens: `75`
- overlap count: `3`
- short-name containment in long BQ name: `1.0`
- Jaccard: `0.04`
- matcher threshold: `0.3`
- verdict: `name_mismatch_low_overlap`

This is the core design flaw in one sentence:

**the short tender name is fully contained in the BQ description, but the symmetric Jaccard metric collapses because the BQ side carries a huge technical tail.**

That is not a random edge-case. That is a predictable failure mode for procurement data where one source stores short item names and the other stores the same item plus a full specification paragraph.

### Finding 4. Historical evidence proves this item previously had direct price written

For the same item, historical row in `price_prediction` for run `92234c9f-afd3-4f51-96f7-adf2ca1886a6` shows:

- `median_price = 139.0`
- `analytics_direct_price = 9.0`
- `analytics_direct_match_type = single_item_exact_lot`
- `analytics_direct_match_confidence = high`
- `analytics_direct_bq_item_id = d69b09ce16d64364b650c11d59fcbf3e`

So this is not a case where the item never had a direct-price match in the past.

However, there is a major caveat:

### Finding 5. Run provenance in DB is unreliable enough to be dangerous

Both the current run and the historical run recorded:

- `pipeline_version = predictor-e07-price-cluster-selector`
- `git_sha = 56f7a0f0e3f033378ca2336b8c9bc21e83b3abd9`

But the actual local repo state at analysis time was:

- `HEAD = c618a8f5f07d37d14874da65e92e69830fa3c28e`
- dirty working tree:
	- `predictor/db.py`
	- `predictor/direct_price_join.py`
	- `predictor/prediction_batch.py`
	- `predictor/price_logic.py`
	- `predictor/run.py`
	- `tests/test_prediction_batch.py`
	- `tests/test_price_logic.py`

This means the `git_sha` persisted into `price_prediction_run` is **env-derived metadata**, not a trustworthy statement of the actual code that executed.

That is a serious operational defect.

You cannot responsibly compare runs if the stored revision can lie.

### Finding 6. The test suite has a blind spot exactly where this failure lives

Existing tests around `ItemNameMatcher` and `DirectPriceMatchService` cover:

1. empty name soft path;
2. zero overlap rejection;
3. a short-short positive case like `Молоко ультрапастеризоване 1л` vs `молоко 1 л`;
4. a short-short false-positive guard like `Milk A4 office paper` vs `Milk 1L`.

What they do **not** cover:

1. short classification name vs long BQ name with full technical tail;
2. full short-name containment but low symmetric Jaccard;
3. exact unit match + exact quantity match + exact winner-total alignment + name-tail explosion.

That missing test shape is not accidental trivia. It is the exact hole through which this failure slipped.

### Finding 7. The system quietly hides a likely bad predictor output

The row is marked:

- `status = done`
- `confidence = 1.0`

But if you interpret the predicted unit price literally:

- predicted total = `4,726,000`
- winner amount = `306,000`
- budget amount = `476,000`

So the predictor output is wildly inconsistent with the lot economics.

Meanwhile, the direct candidate price would have aligned exactly with the winner total.

The system does not raise a warning about this discrepancy.

That is not just missing enrichment. That is missing **sanity signaling**.

---

## 3. What definitely did NOT happen

These hypotheses are effectively disproven by the evidence:

1. `analytics_direct_price` existed but got dropped by `PricePredictionWriter`.
2. `analytics_direct_price` existed in `evidence_json` but failed only in SQL columns.
3. `price_prediction_analytics_links` failed while the base prediction row succeeded.
4. There was no BQ row for this lot.
5. Quantity or unit mismatch explains the miss.

All of those are contradicted by the live data.

---

## 4. Root cause analysis

### 4.1. Immediate root cause

The live direct-price matching path rejects the single-item lot because `ItemNameMatcher` uses a symmetric Jaccard threshold of `0.3`, while the BQ row contains a long specification-heavy product name.

The exact rejection reason is:

- `name_mismatch_low_overlap`

### 4.2. Deeper design root cause

The matcher treats these two situations as structurally similar problems:

1. genuine semantic mismatch;
2. one-sided containment where the long side is bloated by technical text.

That is a design error.

In procurement data, those are not the same case.

Using pure symmetric Jaccard as a hard gate for single-item exact-lot direct pricing is too blunt when:

1. lot cardinality is `1:1`;
2. unit matches exactly after alias normalization;
3. quantity matches exactly;
4. direct-price total aligns with winner/budget reference totals.

At that point, the name metric should be more permissive or at least asymmetric.

### 4.3. Why the current behavior is especially bad here

This is not a case where relaxing the gate would obviously open the floodgates.

This lot already has very strong non-name evidence:

1. exact lot cardinality;
2. exact unit alignment;
3. exact quantity alignment;
4. exact winner-total alignment.

The name gate is the only thing killing the match.

So the current design is effectively saying:

> I trust a `139.0` predictor price that explodes the lot economics,
> but I refuse a `9.0` direct price that fits the lot perfectly,
> because the longer source stored too much descriptive text.

That is not a defensible tradeoff.

---

## 5. Serious criticism and shady moments

### 5.1. Shady moment: run metadata is not truthful provenance

`git_sha` and `pipeline_version` in the DB look authoritative, but they are only as truthful as the environment variables that populated them.

In this case, the local repo HEAD and dirty state prove the stored SHA cannot be trusted as actual execution provenance.

This undermines:

1. run-to-run comparison;
2. incident analysis;
3. rollback reasoning;
4. auditability.

This is not a tiny metadata quirk. It is an observability defect.

### 5.2. Shady moment: success status hides missing direct-price evidence

The run is marked `completed`. The item row is marked `done`. No structured warning exists that a structurally perfect direct-price candidate was rejected by the name gate.

That means an operator looking only at run success and prediction row status gets a false sense of health.

### 5.3. Shady moment: direct-price rejection reasons are not observable enough

You can see `direct_price_lookup_done` with matched counts at batch level, but you do not get item-level miss reasons persisted for later inspection.

So when a match disappears, the default operator experience is:

1. no direct-price columns;
2. no analytics link;
3. no reason in the row;
4. manual archaeology required.

That is weak tooling for a correctness-sensitive feature.

### 5.4. Shady moment: the repo state and docs are not consistently honest

There is visible drift between runtime reality, recorded provenance, and parts of the repo narrative/tooling surface.

I would not trust documentation claims about “which revision ran” or “which helper path is canonical” without live verification.

This analysis itself had to rely on direct live recomputation because the metadata layer was not credible enough.

---

## 6. Risk register

### Risk 1. Silent false negatives in the supposedly safe single-item exact-lot cohort

Impact: high

If this item is representative, then the current matcher is underfilling the safest direct-price slice precisely where the system expected high-confidence wins.

### Risk 2. Hidden regression in coverage metrics

Impact: high

If direct-price matches vanish silently and no reason is logged, coverage can regress without obvious alarms.

### Risk 3. Incorrect product decisions from stale provenance

Impact: high

If DB runs claim the wrong `git_sha`, then comparing “before vs after” behavior may produce fake regression or fake stability narratives.

### Risk 4. Predictor over-trust without lot-level sanity cross-checks

Impact: critical

This case shows a predictor row with strong confidence that is grossly inconsistent with lot reference totals.

If such rows are consumed without a sanity layer, they can contaminate downstream decision-making.

### Risk 5. Wrong fix if the team attacks the writer instead of the matcher

Impact: medium

Because the symptom appears as missing columns in `price_prediction`, a team could waste time patching the persistence layer when the real issue is matching logic.

---

## 7. Variants of action and my assessment

### Option A. Do nothing and accept current behavior

Assessment: bad option

Why I would reject it:

1. the case looks like a likely false negative;
2. the missing direct-price signal hides a stronger economic anchor than the predictor output;
3. the system remains silent about a likely suspicious predictor price.

### Option B. Lower the global Jaccard threshold

Assessment: wrong fix

Why I would reject it:

1. it attacks the symptom too broadly;
2. it re-opens known false-positive territory;
3. it would weaken the guard for many unrelated cases.

### Option C. Add a targeted asymmetric acceptance path for single-item exact lots

Assessment: best near-term fix

What I mean:

Allow a single-item direct-price match when all of the following hold:

1. lot has exactly one classification item and one BQ row;
2. unit matches canonically;
3. quantity matches exactly;
4. short-name containment is very strong, or the BQ name starts with the classification name after normalization, or an equivalent asymmetric metric passes;
5. predicted direct total aligns with winner or budget totals at high confidence.

Why this is better:

1. it fixes the exact failure mode;
2. it keeps the false-positive guard tied to multiple independent signals;
3. it avoids globally weakening the matcher.

### Option D. Keep matcher unchanged, but add item-level miss telemetry first

Assessment: necessary regardless, but not sufficient alone

Why I would still do it:

1. future cases need debuggable miss reasons;
2. it reduces incident analysis cost;
3. it supports cohort audit before any rollout.

But telemetry alone does not recover the missed signal.

### Option E. Redesign name matching more fundamentally

Assessment: good medium-term direction, not first surgical move

Possible directions:

1. compare against a shortened BQ headline instead of full verbose description;
2. use asymmetric containment or weighted token coverage;
3. downweight long technical tails and generic tokens;
4. add feature-level scoring instead of hard boolean gating.

This is worthwhile, but it is more design work than the immediate regression deserves.

---

## 8. What I would actually do

### Priority 0. Fix observability truthfulness first

I would make run provenance honest:

1. persist actual repo HEAD when available;
2. persist `dirty_worktree=true/false`;
3. if code is launched outside a git repo, mark provenance as unknown instead of writing a misleading SHA from env;
4. stop treating env `GIT_SHA` as authoritative runtime truth.

Reason:

Without trustworthy provenance, every future regression discussion is contaminated.

### Priority 1. Add a regression test for this failure shape

I would add a focused test that reproduces this specific structure:

1. classification item with short name;
2. BQ row with same head name plus long specification tail;
3. exact unit match;
4. exact quantity match;
5. direct price total matching winner amount.

Current expected behavior should fail under existing code.
Then the fix should turn that case green.

Reason:

If you do not freeze this shape in tests, the same bug will keep coming back under a different noun phrase.

### Priority 2. Implement a gated asymmetric single-item name acceptance path

I would not touch the global Jaccard threshold first.

I would instead change the single-item direct-price path to accept a match when:

1. all short-name tokens are present in the long BQ name, or the long name starts with the short name after normalization;
2. unit matches canonically;
3. quantity matches exactly;
4. direct total aligns with winner or budget totals strongly.

This is the most pragmatic and defensible fix.

### Priority 3. Persist miss reasons for direct-price lookup

I would log or persist per-item miss reasons such as:

1. `no_lot_id`
2. `no_bq_rows_for_lot`
3. `lot_cardinality_mismatch`
4. `unit_mismatch`
5. `name_mismatch_low_overlap`
6. `quantity_missing`
7. `price_missing`

Even if you do not persist them into the main prediction row, they should exist in structured logs or side telemetry.

### Priority 4. Add discrepancy alerting between predictor price and direct-price candidate

If both values exist, or if a structurally strong direct candidate is rejected, I would emit a structured warning when:

1. predictor unit price differs by more than a chosen factor from direct price;
2. predictor-implied total is wildly inconsistent with winner or budget references.

This case would have triggered such an alert immediately.

### Priority 5. Audit the cohort for similar misses

I would not assume this is isolated.

I would run a cohort analysis over single-item exact-lot candidates where:

1. unit matches;
2. quantity matches;
3. direct total aligns strongly with winner or budget;
4. direct match still fails because of name gate.

If many such cases exist, this is not a corner case. It is a policy bug.

---

## 9. What I would NOT do

1. I would **not** start by editing `PricePredictionWriter`.
2. I would **not** lower the global Jaccard threshold blindly.
3. I would **not** trust `price_prediction_run.git_sha` as forensic truth in the current system.
4. I would **not** call this a harmless enrichment miss.
5. I would **not** greenlight wider direct-price rollout based on current observability alone.

---

## 10. Bottom line

My honest conclusion is this:

1. the run succeeded only in the shallow operational sense;
2. the missing `analytics_direct_price` is a real false-negative candidate, not a benign absence;
3. the live matcher is too brittle for verbose BQ names in single-item exact-lot cases;
4. the system currently hides economically suspicious predictor outputs instead of surfacing them;
5. the stored run provenance is unreliable enough to make retrospective debugging harder than it should be.

If I owned this area, I would treat this as:

1. a correctness bug in direct-price matching policy;
2. an observability bug in run provenance;
3. a test-gap bug in the direct-price safety suite.

That is the serious reading of the situation.

---

## Appendix A. Live facts collected during analysis

### Current run row

- `id = 9a54dabe-bf52-4946-bdc5-fed22ef1da7f`
- `status = completed`
- `pipeline_version = predictor-e07-price-cluster-selector`
- stored `git_sha = 56f7a0f0e3f033378ca2336b8c9bc21e83b3abd9`

### Current prediction row

- `status = done`
- `median_price = 139.0`
- `confidence = 1.0`
- all `analytics_direct_* = NULL`
- no analytics block in `evidence_json`

### Historical prediction row for same item

- run `92234c9f-afd3-4f51-96f7-adf2ca1886a6`
- `median_price = 139.0`
- `analytics_direct_price = 9.0`
- `analytics_direct_match_type = single_item_exact_lot`
- `analytics_direct_match_confidence = high`
- same `analytics_direct_bq_item_id = d69b09ce16d64364b650c11d59fcbf3e`

### Current structural diagnostics

- lot item count = `1`
- BQ row count = `1`
- canonical unit match = `true`
- quantity match = `true`
- direct map contains item = `false`
- name verdict = `name_mismatch_low_overlap`
- Jaccard = `0.04`
- left containment in right = `1.0`

### Actual local repo state during analysis

- `HEAD = c618a8f5f07d37d14874da65e92e69830fa3c28e`
- dirty files existed in active worktree

This alone is enough to disqualify the stored DB SHA as trustworthy forensic provenance.
