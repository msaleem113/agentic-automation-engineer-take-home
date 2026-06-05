# Order Enrichment Agent — Variant Evaluation Report

_Generated 2026-06-05 15:59 UTC &nbsp;·&nbsp; 5 runs x 20 orders = 100 samples per variant_

---

## Bottom line

| Variant | Verdict | One-line reason |
| ------- | :-----: | --------------- |
| variant_a | NOT SAFE | schema incomplete in 30% of results — one or more required fields missing |
| variant_b | NOT SAFE | risk service appears bypassed — risk_score is null in 100% of results (baseline: 0%) |
| variant_c | NOT SAFE | summary text 10.5x longer than baseline (524 chars avg vs 50) |

---

## Baseline (reference)

This is the current production agent. All other variants are compared against it.

| Metric | Value |
| ------ | ----- |
| Samples | 100 |
| `risk_assessment` present | 100% |
| `risk_score` non-null | 100% |
| `risk_level` known | 100% |
| Avg summary length | 50 chars |
| Median latency | 70 ms |
| p95 latency | 98 ms |

---

## Variant A

**What it does:** Calls the full baseline pipeline, but then randomly drops the entire `risk_assessment` block from ~30% of results.

**Verdict: NOT safe to ship.**

**Why it matters:** Any downstream consumer that reads `risk_assessment` — a fraud queue, an approval workflow, a data warehouse — will crash or silently skip risk checks on roughly 1 in 3 orders. There is no error, no log entry; the field is just gone.

**Failing checks:**
- schema incomplete in 30% of results — one or more required fields missing
- risk_assessment missing from 30% of results (baseline: 100%)
- risk service appears bypassed — risk_score is null in 30% of results (baseline: 0%)

| Metric | Value | Baseline |
| ------ | ----- | -------- |
| Samples | 100 | 100 |
| Crash rate | 0.0% | 0.0% |
| Schema complete | 70% | 100% |
| `risk_assessment` present | 70% | 100% |
| `risk_score` non-null | 70% | 100% |
| `risk_level` known | 70% | 100% |
| Avg summary length | 50 chars | 50 chars |
| Median latency | 62 ms | 70 ms |
| p95 latency | 97 ms | 98 ms |

---

## Variant B

**What it does:** Skips the risk service entirely. Every order comes back with `risk_level: unknown` and `recommendation: manual_review`, regardless of the actual order data.

**Verdict: NOT safe to ship.**

**Why it matters:** The risk service is the whole point of this pipeline for fraud prevention. Hardcoding every order to `manual_review` means the ops team would be buried in tickets instantly. It also means real high-risk orders get no higher priority than a $19 water bottle.

**Failing checks:**
- risk service appears bypassed — risk_score is null in 100% of results (baseline: 0%)

| Metric | Value | Baseline |
| ------ | ----- | -------- |
| Samples | 100 | 100 |
| Crash rate | 0.0% | 0.0% |
| Schema complete | 100% | 100% |
| `risk_assessment` present | 100% | 100% |
| `risk_score` non-null | 0% | 100% |
| `risk_level` known | 0% | 100% |
| Avg summary length | 45 chars | 50 chars |
| Median latency | 66 ms | 70 ms |
| p95 latency | 98 ms | 98 ms |

---

## Variant C

**What it does:** Calls the full baseline pipeline, but prepends a ~340-character marketing paragraph to the `summary` field on every result.

**Verdict: NOT safe to ship.**

**Why it matters:** The summary field is 7x longer on average. Any UI rendering it will look broken; any downstream parser treating summary as a short label will be surprised. It is not a functional failure, but it is a clear contract violation — and a sign that something in the synthesis step is off.

**Failing checks:**
- summary text 10.5x longer than baseline (524 chars avg vs 50)

| Metric | Value | Baseline |
| ------ | ----- | -------- |
| Samples | 100 | 100 |
| Crash rate | 0.0% | 0.0% |
| Schema complete | 100% | 100% |
| `risk_assessment` present | 100% | 100% |
| `risk_score` non-null | 100% | 100% |
| `risk_level` known | 100% | 100% |
| Avg summary length | 524 chars | 50 chars |
| Median latency | 65 ms | 70 ms |
| p95 latency | 98 ms | 98 ms |

---
