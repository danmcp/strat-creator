# ADR-0001: Source of Truth for Refine Loop Count

## Status

Accepted

## Context

The dashboard needs to report how many refine/review iterations each strategy
went through before reaching rubric-pass (see
[plan 001](../plans/001-dashboard-sme-and-loop-metrics.md), RHAIFIRST-390).

This metric is the measurement instrument for RHAIFIRST-325, a `strategy-refine`
convergence bug: answered Open Questions never retire while Technical Approach
drifts, so users cycle five or more non-converging refine passes on a single
strategy and burn quota. A high per-strategy iteration count is the direct
fingerprint of that bug. RHAIFIRST-325's own acceptance criterion is that "a
repeated refine with no new input converges - the second pass is a no-op", so
once 325 is fixed the iteration count must stop climbing. The metric therefore
serves double duty: it quantifies 325's cost today and acts as its regression
signal after the fix.

There is no single existing signal that cleanly counts iterations:

- **Frontmatter counter** - add a mutable `refine_count` field to the strat-task
  schema and increment it in the `strategy-refine` skill. Accurate and explicit,
  but only reflects iterations that ran *through the instrumented skill*, and is
  zero for every strategy created before instrumentation lands.
- **Pipeline-run inference** - count how many distinct CI pipeline runs contain
  the same `strat_id`. Works retroactively from data we already have and needs
  no schema change, but conflates CI re-runs with genuine refine loops and
  misses purely local refinement that never hit CI.
- **Parsing CI logs / review history** - richest signal, but brittle and far
  more work than the metric warrants.

No option is complete on its own: the frontmatter counter is accurate but blind
to history, and run-inference is retroactive but noisy.

## Decision

Use a **two-tier source with frontmatter as the authoritative signal and
pipeline-run count as a fallback**:

1. Add `refine_count` (integer, optional, **no materialized default**) to the
   strat-task frontmatter schema. A default of `0` would erase the absent-vs-zero
   distinction below by making legacy strategies look instrumented, so absence
   must stay absent (see point 2). The `strategy-refine` skill increments it
   **only when a refine pass
   actually changes the strategy body** - a no-op pass (no new input, nothing
   rewritten) does not increment.
2. The dashboard treats `refine_count` as authoritative whenever the field is
   **present, including an explicit `0`** (which means zero productive refine
   passes). Only a **non-boolean integer `>= 0`** is a valid authoritative value.
   Extraction MUST preserve the distinction between absent and zero by emitting
   `refine_count: null` when the field is absent from a strategy's frontmatter and
   the integer value (including `0`) when it is present. A malformed value
   (non-integer, boolean, or negative) is **not** trusted: it normalizes to
   `null` and triggers the fallback, exactly as an absent field does, so a
   corrupt field can never fabricate an authoritative count.
3. The pipeline-run fallback applies **whenever extraction yields `null`** - that
   is, whenever the field is absent *or* malformed (see point 2). Authoritative
   status is reserved for a valid non-boolean integer `>= 0` (including `0`).
   Fallback iterations = `max(0, (distinct pipeline runs containing the
   strat_id) - 1)` - the initial run is the creation baseline, not a refine
   iteration. This value is approximate (CI-run-derived) and MUST be labeled as
   such (see the provenance rule below).

**Precedence rule: frontmatter wins whenever it yields a valid authoritative
value (a non-boolean integer `>= 0`, including `0`).** The two sources can
disagree; the authoritative counter is preferred because it measures the intended
concept (refine iterations) rather than a proxy (CI runs). An explicit `0` is a
real measurement (the strategy reached rubric-pass with no productive refine) and
is not the same as a missing or malformed field; extraction yielding `null`
(absent or malformed) is what triggers the fallback, which exists solely to give
a best-effort number for strategies predating the instrumentation.

**Increment rule: count productive iterations, not attempts.** `refine_count`
increments only when a pass changes the body, not on every invocation of the
skill. This is deliberate and load-bearing for the 325 relationship: if the
counter bumped on every attempt, it would keep climbing even after 325's fix
makes no-input passes no-ops, and the metric could no longer serve as a
regression signal. The cost we care about - wasted, non-converging iterations -
is precisely the set of passes that *do* rewrite content without reaching
rubric-pass. (Trade-off: this measures productive iterations rather than total
quota spent; a pass that runs but changes nothing is invisible to the count.)

**Final-pass inclusion:** a body-changing pass that *reaches* rubric-pass is
counted - it is a productive refine pass. `refine_count` therefore equals the
number of productive refine passes up to and including the one that achieves
rubric-pass. The same inclusive definition applies to the plan (Task 2.2) and to
the tests.

**Provenance:** the dashboard marks fallback-derived counts as approximate (e.g.
a `~` or asterisk) so a CI-run proxy is not read as an instrumented count. This
is a cheap rendering marker, and it matters only while pre-instrumentation
strategies remain - it retires as `refine_count` populates.

## Consequences

Positive:

- Retroactive coverage on day one via the fallback - no waiting for a full cycle
  of instrumented strategies.
- Accuracy improves automatically as instrumented strategies accumulate; the
  fallback quietly retires per-strategy as `refine_count` populates.
- No CI/pipeline changes required to ship the metric.

Negative:

- Two sources of truth that can disagree; the precedence rule and the
  "approximate" marker are load-bearing for interpreting the dashboard.
- `refine_count` is mutable state on the task file and depends on the
  `strategy-refine` skill being the only path that refines a strategy. A refine
  performed outside the skill will undercount.
- Pipeline-run count conflates CI re-runs (infra flakes, retries) with real
  refine loops, so fallback numbers can overstate iterations.
- The "productive passes only" increment rule requires the skill to detect
  whether a pass changed the body. Until RHAIFIRST-325 is fixed, non-convergent
  passes *do* change the body (that is the bug), so they correctly count; the
  rule's payoff lands once 325's no-op behavior exists.

## Related

- [Plan 001: Dashboard Metrics - Empty SME Input & Refine Loop Count](../plans/001-dashboard-sme-and-loop-metrics.md)
- RHAIFIRST-390: Tracking ticket
- RHAIFIRST-325: strategy-refine convergence bug - this metric quantifies its
  cost and is the regression signal for its fix (no-op passes must not increment)
