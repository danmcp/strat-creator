# Plan: Per-Run Trends for SME Input and Refine Iterations

## Goal

Surface the two metrics added by [plan 001](001-dashboard-sme-and-loop-metrics.md)
on the dashboard's Per-Run Trends page, not just the Executive Summary snapshot:

1. Empty SME Input rate over time.
2. Average refine iterations over time.

## Context

Follow-up to plan 001. The SME Input and refine-count metrics landed only on the
Executive Summary page (KPI cards + the unique-strategies table). Both are per-STRAT
signals whose value is watching change over time - in particular, average refine
iterations is the regression signal for RHAIFIRST-325 (refine-loop convergence).
A snapshot cannot show whether convergence is improving or regressing across runs.

## Design decisions

### Refine iterations trend: authoritative-only

The trend plots the mean instrumented `refine_count` per run and EXCLUDES the
pipeline-run fallback estimate. Rationale:

- The fallback `max(0, distinct_runs - 1)` is a proxy for CI churn (re-runs,
  retries), not refine effort. Blending it into a "refine iterations" trend means
  a movement in the line could be CI noise rather than refine behavior - which
  defeats a regression signal whose whole job is detecting real change.
- Division of labor: the Executive Summary keeps the blended (authoritative +
  fallback, marked approximate) snapshot for "where are we now"; the trend is the
  clean instrumented-only regression instrument. The two pages answer different
  questions, so computing them differently is intentional, not an inconsistency.
- Cost: the chart is sparse until STRATs are instrumented (the strategy-refine
  increment from plan 001). Runs with no instrumented STRAT render as gaps
  (`spanGaps: false`), and the chart caption states it is instrumented-only.

### SME rate trend: self-contained per run

Each run's point is the percent of rubric-pass STRATs with a KNOWN SME status
that had empty SME input, using `empty_sme_rubric_pass()` on that run's strategies.
A run with no known rubric-pass STRAT is a gap (None), not a misleading 0 percent.
Unknown SME status (runs predating instrumentation) is excluded from both
numerator and denominator, consistent with the Executive Summary KPI.

## Changes

### `scripts/generate-dashboard.py`

- `compute_metric_trends(runs)`: pure post-processing (called after
  `compute_deltas` in `main()`) that attaches per-run scalar fields to each run
  dict: `sme_empty_count`, `sme_rubric_known`, `sme_empty_rate`, `avg_refine_iter`,
  `refine_instrumented_count`. These serialize into `ALL_RUNS` automatically.
- Two Chart.js line charts on the Per-Run Trends page: "Empty SME Input Rate Over
  Time" and "Avg Refine Iterations Over Time", both reading the per-run fields
  from `RUNS` with `spanGaps: false`.
- Two cards added to the Per-Run Trends hero KPI grid (Empty SME Input, Avg Refine
  Iterations), each with a delta vs the previous run. The empty-SME delta is
  colored (up is worse); the refine delta is neutral. The grid switches to
  `auto-fit` so it reflows from 7 to 9 cards cleanly.

Per-run fields are computed over all loaded runs in Python; the client-side
10-day date filter (`RUNS = filterByDays(ALL_RUNS, 10)`) only selects which points
are plotted, so each point's value is unaffected by the filter window.

### `tests/test_dashboard_metrics.py`

`TestComputeMetricTrends`: SME rate/count per run, None when no known rubric-pass,
authoritative-only refine average, None when uninstrumented, malformed excluded,
per-run independence, empty run.

## Acceptance Criteria

- [ ] Per-Run Trends page shows an Empty SME Input rate line chart (gaps where no
      known rubric-pass STRAT)
- [ ] Per-Run Trends page shows an Avg Refine Iterations line chart
      (authoritative-only; gaps where uninstrumented)
- [ ] Per-Run Trends hero KPI grid has Empty SME Input and Avg Refine Iterations
      cards with vs-previous-run deltas
- [ ] `compute_metric_trends` excludes fallback estimates from the refine trend
      and unknown SME status from the SME trend
- [ ] Unit tests pass for `compute_metric_trends`
- [ ] `make test` passes

## Files to Change

| File | Change |
|------|--------|
| `scripts/generate-dashboard.py` | `compute_metric_trends()` + call site, two trend charts, two overview KPI cards |
| `tests/test_dashboard_metrics.py` | `TestComputeMetricTrends` contract tests |

## Related

- [Plan 001: Dashboard Metrics](001-dashboard-sme-and-loop-metrics.md)
- [ADR-0001: Source of Truth for Refine Loop Count](../decisions/ADR-0001-refine-loop-count-source.md)
- RHAIFIRST-390: Tracking ticket
- RHAIFIRST-325: strategy-refine convergence failure (refine trend quantifies this)
