# Bug: find_processed_rfe_ids Over-Excludes RFEs With Multiple RHAISTRAT Clones

## Summary

`find_processed_rfe_ids` in `scripts/jira_utils.py` permanently excludes an RFE from the `batch-jql` pipeline if *any* of its RHAISTRAT Cloners-linked issues are in a terminal or active status — even when a newer clone exists that still needs processing. This breaks the pipeline's ability to pick up RFEs that have been re-cloned for a new release cycle.

## Reproduction

The bug is live in production. RHAIRFE-2100 has not been processed by `batch-jql` in 24+ days despite passing all JQL filters.

### Setup (current state in Jira)

1. **RHAIRFE-2100** — "Automated Zero-Manual-Step Migration from RHOAI 2.25 to 3.5 (EUS)"
   - Status: Approved (not in `excluded_statuses`)
   - Labels: includes `rfe-creator-autofix-rubric-pass` (matches `quality_labels`)
   - Target Version (cf[10855]): `3.5 GA RHOAI RELEASE` (matches `target_versions`)
   - Has **two** Cloners links:

2. **RHAISTRAT-1755** — old 3.5 strategy (the blocker)
   - Created: 2026-05-10 by `rhoaieng automationbot` (CI pipeline)
   - Status: **Closed** (Resolution: Duplicate)
   - Labels: `strat-creator-auto-created`, `strat-creator-auto-refined`, `strat-creator-rubric-pass`
   - Closed by Tramaine Darby on 2026-05-29 as "Duplicate of RHAISTRAT-1480"

3. **RHAISTRAT-2210** — new 3.6 strategy (needs processing)
   - Created: 2026-07-10 by Tramaine Darby (locally, not via CI)
   - Status: **New**
   - Labels: `notebooks-teal-scrum`, `strat-creator-3.6` (no pipeline labels)
   - Went through 4 rounds of local review, reached APPROVE 6/8
   - No `strat-creator-rubric-pass`, no `strat-creator-needs-attention`, no `strat-creator-processing`

### Steps

1. `batch-jql` scheduled job fires (every 6 hours)
2. `list-rfe-ids.py --jql-default` builds JQL from `pipeline-settings.yaml`
3. JQL returns 658 RFEs, including RHAIRFE-2100
4. `find_processed_rfe_ids` runs two queries:
   - Skip-labels query: finds RHAISTRAT issues with `strat-creator-rubric-pass` / `strat-creator-needs-attention` / `strat-creator-processing`
   - Excluded-statuses query: finds RHAISTRAT issues in `In Progress` / `Review` / `Release Pending` / `Closed` / `Resolved`
5. **RHAISTRAT-1755** matches the skip-labels query (has `strat-creator-rubric-pass`) AND the excluded-statuses query (status Closed)
6. `_extract_rfe_keys_from_issues` traces RHAISTRAT-1755's Cloners link back to RHAIRFE-2100
7. RHAIRFE-2100 is added to the `processed` exclusion set
8. RHAIRFE-2100 is filtered out — `batch-jql` never sees it
9. RHAISTRAT-2210 is never processed

### Evidence from Observatory

Observatory API confirms zero strat-pipeline runs have ever referenced RHAIRFE-2100 or RHAISTRAT-2210:

```
GET /api/traces/search?q=RHAIRFE-2100&pipeline=strat-pipeline → 0 matches
GET /api/traces/search?q=RHAISTRAT-2210&pipeline=strat-pipeline → 0 matches
```

The short batch-jql runs (83 seconds, no work done) confirm the exclusion:

```
JQL returned 658 RFE(s)
Excluded 658 already-processed RFE(s), 0 remaining
Discovered RFE_IDS:
```

All 658 RFEs excluded. RHAIRFE-2100 is among them.

The longer run (32 minutes, on 2026-08-03T10:07) found exactly 1 RFE (RHAIRFE-2783) — this was a newly created RFE with no prior STRAT clones.

## Expected

RHAIRFE-2100 should be eligible for processing because RHAISTRAT-2210 (status New, no skip labels) still needs pipeline attention. The exclusion logic should recognize that a "done" clone (1755) does not mean all clones are done.

## Actual

RHAIRFE-2100 is permanently excluded because the old closed clone (RHAISTRAT-1755) matches the exclusion criteria. The pipeline has no way to distinguish "all clones are done" from "one clone is done but a newer one needs work."

## Root Cause

`find_processed_rfe_ids` (`scripts/jira_utils.py`, lines 264-289) uses a union-based exclusion strategy:

```python
def find_processed_rfe_ids(server, user, token, skip_labels,
                           excluded_strat_statuses=None,
                           strat_project="RHAISTRAT"):
    processed = set()

    if skip_labels:
        label_clause = " OR ".join(f'labels = "{l}"' for l in skip_labels)
        jql = f"project = {strat_project} AND ({label_clause})"
        issues = search_issues(server, user, token, jql, fields=["issuelinks"])
        processed |= _extract_rfe_keys_from_issues(issues)

    if excluded_strat_statuses:
        status_clause = ", ".join(f'"{s}"' for s in excluded_strat_statuses)
        jql = f"project = {strat_project} AND status IN ({status_clause})"
        issues = search_issues(server, user, token, jql, fields=["issuelinks"])
        processed |= _extract_rfe_keys_from_issues(issues)

    return processed
```

The function collects RFE keys from ANY matching STRAT clone and adds them to the exclusion set. It never checks whether the RFE has OTHER clones that are NOT in a terminal/excluded state. The implicit assumption is one STRAT per RFE — which breaks when:

- A STRAT is closed as a duplicate and a new one is created
- A STRAT is created for release N, closed, and a new one is created for release N+1
- A STRAT is manually created locally alongside a CI-created one

## Impact

- **RHAISTRAT-2210 has been stranded for 24+ days.** It reached APPROVE 6/8 through local review but has no pipeline labels, meaning it is invisible to downstream consumers that rely on `strat-creator-rubric-pass` as a quality signal.
- **Any RFE with a closed/resolved STRAT clone is permanently blocked.** This is not limited to RHAIRFE-2100. Any RFE that had a STRAT created in a previous release cycle and then closed/duplicated will hit the same exclusion.
- **The batch-jql job runs every 6 hours and silently skips these RFEs.** There is no log line indicating which specific RFEs were excluded or why — only the aggregate count ("Excluded 658 already-processed RFE(s)").

## Fix

### Approach: Override when exactly one open clone needs processing

The existing exclusion logic stays as the default. A third query finds
"needs-processing" clones -- RHAISTRAT issues that are NOT in an excluded
status AND have no skip labels. If an excluded RFE has exactly one such
clone, the exclusion is overridden so the replacement can be processed.

This handles the narrow "rejected-and-replaced" case without enabling
self-splitting (2+ open clones keeps the RFE excluded).

| Open clones w/o skip labels | Result |
|-|-|
| 0 (all closed/labeled) | Excluded (work is done) |
| 1 (replacement clone) | Not excluded (override) |
| 2+ (self-split) | Excluded (let humans sort it out) |

### Observability

`list-rfe-ids.py` now accepts `--verbose` to log each excluded RFE
individually, instead of only showing the aggregate count.

## Related Tasks

- [001-dashboard-sme-and-loop-metrics.md](../plans/001-dashboard-sme-and-loop-metrics.md) -- dashboard work that will surface pipeline processing gaps
- RHAIFIRST-399 -- argument parsing bug in strategy-refine (separate issue, same pipeline)

## Scope of Fix

| File | Change |
|------|--------|
| `scripts/jira_utils.py` | Add override query to `find_processed_rfe_ids`; add `_count_rfe_clones_from_issues` helper |
| `scripts/list-rfe-ids.py` | Add `--verbose` flag with per-RFE exclusion logging |
| `tests/test_search_and_filter.py` | Five multi-clone test cases |

## Timeline

- **2026-05-10**: RHAISTRAT-1755 created by CI pipeline for RHAIRFE-2100
- **2026-05-29**: Tramaine closes RHAISTRAT-1755 as duplicate of RHAISTRAT-1480
- **2026-07-10**: Tramaine creates RHAISTRAT-2210 locally for 3.6 release cycle, cloned from RHAIRFE-2100
- **2026-07-10**: RHAISTRAT-2210 goes through 4 rounds of local review, reaches APPROVE 6/8
- **2026-07-10 – 2026-08-03**: `batch-jql` runs every 6 hours (~96 runs), never picks up RHAIRFE-2100
- **2026-08-03**: Bug identified via Observatory API investigation
