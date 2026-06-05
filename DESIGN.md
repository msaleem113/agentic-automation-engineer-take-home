# DESIGN.md

## What I chose to measure, and why

The question for each variant is simple: does it behave the same as baseline on the things that actually matter in production?

For an order enrichment agent, those things are:

**1. Are all the expected fields always present?**
Every enriched order must come back with `order_id`, `pricing`, `shipping`, `risk_assessment`, and `processing_time_ms`. If any of these disappear, something downstream — a fraud queue, a checkout flow, a data warehouse — will break. This is the most basic contract check.

**2. Is the risk service actually being called?**
Risk scoring is the whole point of this pipeline. I track whether `risk_score` comes back as a real number or null. The baseline hits the service with retry logic, so it returns a real score on almost every run. A variant that consistently returns null is almost certainly skipping the service altogether.

**3. Is the `risk_assessment` block always included?**
Related but separate from the score itself — the entire field could be silently dropped. Baseline always includes it, even when the service fails (it falls back to a stub). Anything below 95% presence is a regression.

**4. Is the summary text a reasonable length?**
The `summary` field is the short human-readable description of the order. If it suddenly grows to 3x the baseline average, something in the output step is clearly wrong.

---

**Why I used code-based checks instead of an AI judge**

The problems in A, B, and C are structural — a missing field, a bypassed service, bloated text. You don't need AI judgment to spot these; a simple comparison against baseline numbers is faster, cheaper, and gives the same result every time you run it. An AI judge would add cost and inconsistency without telling you anything more.

That said, if the question were about *quality* — e.g., "is the risk reasoning still sound, or has it started approving fraudulent orders?" — then an AI judge would be the right tool. That's not what's being tested here.

---

**Why run each order 5 times (100 samples per variant)?**

The agent has randomness built in: prices fluctuate slightly, the risk service fails ~10% of calls, and the output template is chosen at random. Running each order once gives you a noisy picture. At 5 runs across 20 orders (100 samples), the numbers are stable enough to trust. The random seed is fixed at 42, so re-running the script produces identical results every time.

---

## What this eval would NOT catch

- **Wrong numbers.** If `pricing.total` started calculating incorrectly, all checks would still pass — the field is present, just wrong. Catching this would need known-good expected values to compare against.
- **Biased risk scoring.** If the risk model started giving everyone a "low" score regardless of order value, the non-null check would pass. You'd need to check the *distribution* of scores to catch this.
- **Latency regressions.** Processing time is reported but there's no enforced threshold against baseline. A variant that got 30% slower would not fail any check.
- **New required fields.** If the application adds a new expected output field tomorrow, the harness won't know to check for it until `REQUIRED_KEYS` is updated.

---

## Cost and runtime

| | |
|---|---|
| Runtime | ~30 seconds on a laptop (100 samples x 4 variants) |
| Cost | $0 — no external APIs, no AI calls, runs entirely locally |
| Reproducibility | Results are identical every run — random seed is fixed |

To re-run: `python eval.py`
