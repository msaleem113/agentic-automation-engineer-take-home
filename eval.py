"""
eval.py — Is this variant safe to ship?

Runs all 20 fixture orders through baseline and each candidate variant,
collects metrics, applies threshold checks, and writes report.md.

Usage:
    python eval.py
"""

import json
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from variants import baseline, variant_a, variant_b, variant_c

# Pin the seed so every run produces identical numbers.
# The tools all use random internally (pricing jitter, risk failure injection,
# template selection), so without this the verdicts would drift between runs.
random.seed(42)

RUNS_PER_ORDER = 5   # 5 × 20 orders = 100 samples per variant

VARIANTS = [
    ("baseline",  baseline),
    ("variant_a", variant_a),
    ("variant_b", variant_b),
    ("variant_c", variant_c),
]

# Every enriched result must carry these top-level keys
REQUIRED_KEYS = {"order_id", "pricing", "shipping", "risk_assessment", "processing_time_ms"}


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def load_orders():
    path = Path(__file__).parent / "fixtures" / "orders.jsonl"
    with path.open() as f:
        return [json.loads(line) for line in f]


def run_variant(module, orders, n_runs):
    """Run every order n_runs times. Unhandled exceptions are captured as
    crash records so they show up in metrics rather than aborting the run."""
    out = []
    for order in orders:
        for _ in range(n_runs):
            try:
                out.append(module.enrich_order(order))
            except Exception as exc:
                out.append({"_crash": str(exc), "order_id": order.get("order_id")})
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(results):
    n   = len(results)
    crashes = [r for r in results if "_crash" in r]
    ok      = [r for r in results if "_crash" not in r]

    def rate(pred):
        return sum(1 for r in results if pred(r)) / n

    def ra(r):
        # safe accessor — risk_assessment might be absent or None
        return r.get("risk_assessment") or {}

    summaries = [len(r["summary"]) for r in ok if "summary" in r]
    times     = [r["processing_time_ms"] for r in ok if "processing_time_ms" in r]

    return {
        "n":                 n,
        "crash_rate":        len(crashes) / n,
        "schema_ok_rate":    rate(lambda r: REQUIRED_KEYS <= r.keys()),
        "risk_present_rate": rate(lambda r: "risk_assessment" in r),
        "risk_scored_rate":  rate(lambda r: isinstance(ra(r).get("risk_score"), (int, float))),
        "risk_known_rate":   rate(lambda r: ra(r).get("risk_level") not in (None, "unknown")),
        "avg_summary_len":   statistics.mean(summaries) if summaries else 0,
        "median_ms":         statistics.median(times) if times else 0,
        "p95_ms":            sorted(times)[int(len(times) * 0.95)] if times else 0,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def check(m, base):
    """Return a list of human-readable failure reasons.
    Empty list means the variant passed all checks (SAFE)."""
    issues = []

    if m["crash_rate"] > 0.01:
        issues.append(
            f"unhandled exceptions in {m['crash_rate']*100:.0f}% of runs"
        )

    if m["schema_ok_rate"] < 0.99:
        issues.append(
            f"schema incomplete in {(1 - m['schema_ok_rate'])*100:.0f}% of results"
            f" — one or more required fields missing"
        )

    # risk_assessment field silently dropped?
    if m["risk_present_rate"] < 0.95:
        issues.append(
            f"risk_assessment missing from {(1 - m['risk_present_rate'])*100:.0f}% of results"
            f" (baseline: {base['risk_present_rate']*100:.0f}%)"
        )

    # risk service bypassed entirely?
    if m["risk_scored_rate"] < 0.80:
        issues.append(
            f"risk service appears bypassed — risk_score is null in"
            f" {(1 - m['risk_scored_rate'])*100:.0f}% of results"
            f" (baseline: {(1 - base['risk_scored_rate'])*100:.0f}%)"
        )

    # summary text bloated beyond 3x baseline average?
    if base["avg_summary_len"] > 0 and m["avg_summary_len"] > base["avg_summary_len"] * 3:
        ratio = m["avg_summary_len"] / base["avg_summary_len"]
        issues.append(
            f"summary text {ratio:.1f}x longer than baseline"
            f" ({m['avg_summary_len']:.0f} chars avg vs {base['avg_summary_len']:.0f})"
        )

    return issues


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

_VARIANT_DESCRIPTIONS = {
    "variant_a": (
        "Calls the full baseline pipeline, but then randomly drops the entire "
        "`risk_assessment` block from ~30% of results."
    ),
    "variant_b": (
        "Skips the risk service entirely. Every order comes back with "
        "`risk_level: unknown` and `recommendation: manual_review`, "
        "regardless of the actual order data."
    ),
    "variant_c": (
        "Calls the full baseline pipeline, but prepends a ~340-character "
        "marketing paragraph to the `summary` field on every result."
    ),
}

_WHAT_WENT_WRONG = {
    "variant_a": (
        "Any downstream consumer that reads `risk_assessment` — a fraud queue, "
        "an approval workflow, a data warehouse — will crash or silently skip "
        "risk checks on roughly 1 in 3 orders. There is no error, no log entry; "
        "the field is just gone."
    ),
    "variant_b": (
        "The risk service is the whole point of this pipeline for fraud prevention. "
        "Hardcoding every order to `manual_review` means the ops team would be "
        "buried in tickets instantly. It also means real high-risk orders get no "
        "higher priority than a $19 water bottle."
    ),
    "variant_c": (
        "The summary field is 7x longer on average. Any UI rendering it will look "
        "broken; any downstream parser treating summary as a short label will be "
        "surprised. It is not a functional failure, but it is a clear contract "
        "violation — and a sign that something in the synthesis step is off."
    ),
}


def write_report(all_metrics, all_verdicts):
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    base = all_metrics["baseline"]
    lines = []

    lines += [
        "# Order Enrichment Agent — Variant Evaluation Report",
        "",
        f"_Generated {now} &nbsp;·&nbsp; {RUNS_PER_ORDER} runs x 20 orders"
        f" = {RUNS_PER_ORDER * 20} samples per variant_",
        "",
        "---",
        "",
        "## Bottom line",
        "",
        "| Variant | Verdict | One-line reason |",
        "| ------- | :-----: | --------------- |",
    ]

    for name in ("variant_a", "variant_b", "variant_c"):
        issues = all_verdicts[name]
        safe   = not issues
        icon   = "SAFE" if safe else "NOT SAFE"
        reason = "all checks passed" if safe else issues[0]
        lines.append(f"| {name} | {icon} | {reason} |")

    lines += ["", "---", ""]

    # Baseline reference block
    m = all_metrics["baseline"]
    lines += [
        "## Baseline (reference)",
        "",
        "This is the current production agent. All other variants are compared against it.",
        "",
        "| Metric | Value |",
        "| ------ | ----- |",
        f"| Samples | {m['n']} |",
        f"| `risk_assessment` present | {m['risk_present_rate']*100:.0f}% |",
        f"| `risk_score` non-null | {m['risk_scored_rate']*100:.0f}% |",
        f"| `risk_level` known | {m['risk_known_rate']*100:.0f}% |",
        f"| Avg summary length | {m['avg_summary_len']:.0f} chars |",
        f"| Median latency | {m['median_ms']:.0f} ms |",
        f"| p95 latency | {m['p95_ms']:.0f} ms |",
        "",
        "---",
        "",
    ]

    # One section per candidate variant
    for name in ("variant_a", "variant_b", "variant_c"):
        m      = all_metrics[name]
        issues = all_verdicts[name]
        safe   = not issues
        label  = name.replace("_", " ").title()

        lines.append(f"## {label}")
        lines.append("")
        lines.append(f"**What it does:** {_VARIANT_DESCRIPTIONS[name]}")
        lines.append("")

        if safe:
            lines.append("**Verdict: SAFE to ship.** All checks passed.")
        else:
            lines.append("**Verdict: NOT safe to ship.**")
            lines.append("")
            lines.append(f"**Why it matters:** {_WHAT_WENT_WRONG[name]}")
            lines.append("")
            lines.append("**Failing checks:**")
            for issue in issues:
                lines.append(f"- {issue}")

        lines += [
            "",
            "| Metric | Value | Baseline |",
            "| ------ | ----- | -------- |",
            f"| Samples | {m['n']} | {base['n']} |",
            f"| Crash rate | {m['crash_rate']*100:.1f}% | {base['crash_rate']*100:.1f}% |",
            f"| Schema complete | {m['schema_ok_rate']*100:.0f}% | {base['schema_ok_rate']*100:.0f}% |",
            f"| `risk_assessment` present | {m['risk_present_rate']*100:.0f}% | {base['risk_present_rate']*100:.0f}% |",
            f"| `risk_score` non-null | {m['risk_scored_rate']*100:.0f}% | {base['risk_scored_rate']*100:.0f}% |",
            f"| `risk_level` known | {m['risk_known_rate']*100:.0f}% | {base['risk_known_rate']*100:.0f}% |",
            f"| Avg summary length | {m['avg_summary_len']:.0f} chars | {base['avg_summary_len']:.0f} chars |",
            f"| Median latency | {m['median_ms']:.0f} ms | {base['median_ms']:.0f} ms |",
            f"| p95 latency | {m['p95_ms']:.0f} ms | {base['p95_ms']:.0f} ms |",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    orders = load_orders()
    total  = len(orders) * RUNS_PER_ORDER
    print(f"Loaded {len(orders)} orders · {RUNS_PER_ORDER} runs each = {total} samples per variant\n")

    all_metrics  = {}
    all_verdicts = {}

    for name, module in VARIANTS:
        print(f"  running {name}...", end=" ", flush=True)
        t0      = time.time()
        results = run_variant(module, orders, RUNS_PER_ORDER)
        elapsed = time.time() - t0
        all_metrics[name] = compute_metrics(results)
        print(f"done in {elapsed:.1f}s")

    base = all_metrics["baseline"]
    for name in all_metrics:
        all_verdicts[name] = [] if name == "baseline" else check(all_metrics[name], base)

    print("\n--- verdicts ---")
    for name in ("variant_a", "variant_b", "variant_c"):
        issues = all_verdicts[name]
        status = "SAFE" if not issues else "UNSAFE"
        print(f"  {name}: {status}")
        for issue in issues:
            print(f"    - {issue}")

    report   = write_report(all_metrics, all_verdicts)
    out_path = Path(__file__).parent / "report.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nreport written -> {out_path}")


if __name__ == "__main__":
    main()
