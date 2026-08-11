# BUG: lock_issues.py exits non-zero when single blocked RFE remains in batch

**Ticket:** RHAIFIRST-468
**File:** `scripts/lock_issues.py`
**Severity:** Pipeline health shows red when no work is available (false failure)

---

## Problem

When the strat-pipeline `batch-jql` job filters 662 candidates down to 1
remaining RFE, and that RFE is blocked (e.g. has `strat-creator-needs-attention`),
`lock_issues.py lock` exits with code 1. GitLab CI treats this as a job failure,
Observatory marks the pipeline red, and the health signal is useless.

"No work available" should be a clean exit, not a failure.

## Root Cause

`lock()` (line 84) uses `batch_mode = len(keys) > 1` to decide behavior:

- **Multiple keys** (batch_mode=True): blocked keys are skipped, function
  returns exit code 0 with the locked subset (lines 100-102)
- **Single key** (batch_mode=False): a blocked key returns exit code 1
  immediately (lines 103-105)

The single-key exit-1 path was designed for the `lock-strat` command, where
blocking a specific STRAT is a meaningful failure. But `batch-jql` hits this
same path when filtering happens to leave exactly one candidate — and that
candidate being blocked is normal steady-state, not a failure.

```
# The pipeline does this:
RFE_IDS=$(python3 scripts/lock_issues.py lock ${RFE_IDS})
#                                              ^^^^^^^^^
#                  When only 1 RFE remains after filtering,
#                  len(keys)==1, batch_mode=False, exits 1 if blocked
```

The CI yaml already guards against empty output at line 71:
```yaml
if [ -z "${RFE_IDS}" ]; then echo "All RFEs already locked, nothing to process"; exit 0; fi
```
But this guard never fires because `lock_issues.py` exits 1 before printing
anything, and the shell step fails before reaching the guard.

## Evidence

From run 8970 (2026-08-07T10:09:13Z):
```
JQL returned 662 RFE(s)
Excluded 661 already-processed RFE(s), 1 remaining
Discovered RFE_IDS: RHAIRFE-3063
BLOCKED RHAIRFE-3063 — has label(s): strat-creator-needs-attention
ERROR: Job failed: exit code 1
```

Pipeline has been red since 2026-08-04 due to this pattern repeating on runs
8970, 8971, 8972, 8735, 8406.

## Fix

Remove the single-key vs. multi-key distinction in `lock()`. Always skip
blocked keys and return exit code 0 — the caller handles empty output.

```python
def lock(server, user, token, keys):
    locked = []

    for key in keys:
        labels = _get_labels(server, user, token, key)
        blocked_by = labels & BLOCKING_LABELS
        if blocked_by:
            print(f"BLOCKED {key} — has label(s): "
                  f"{', '.join(sorted(blocked_by))}", file=sys.stderr)
            continue

        add_labels(server, user, token, key, [PROCESSING_LABEL])
        locked.append(key)
        print(f"LOCKED {key}", file=sys.stderr)

    print(" ".join(locked))

    if not locked:
        print("No keys locked", file=sys.stderr)

    return 0, locked
```

This removes the `batch_mode` flag entirely. Because `lock()` now treats a
blocked key as an empty selection rather than an error, `lock_strat()` must
explicitly preserve its single-target locking semantics by checking the
returned `locked_keys` list:

```python
    # Lock the RFE. A blocked linked RFE is contention for this specific
    # STRAT request, so lock-strat must still fail.
    _, locked_keys = lock(server, user, token, [rfe_key])
    return 0 if locked_keys else 1
```

Without this accompanying change, `lock-strat` would incorrectly return 0
when the linked RFE already has `strat-creator-processing`. Its existing
STRAT-level blocking check (lines 139-144) only covers labels on the STRAT and
does not replace this linked-RFE contention check.

## Impact of Fix

- `batch-jql`: blocked RFEs produce empty stdout → CI guard catches it → exit 0
- `lock-strat`: STRAT-level blocking still returns 1 (line 144, unchanged)
- `lock-strat`: a blocked linked RFE still returns 1 via the new
  `locked_keys` check
- `lock` with a single unblocked key: still locks and returns 0 (unchanged)
- `lock` with a single blocked key: now returns 0 with empty stdout instead of 1

## Test Cases

1. `lock_issues.py lock BLOCKED_KEY` → exit 0, empty stdout, stderr says BLOCKED
2. `lock_issues.py lock BLOCKED_KEY CLEAN_KEY` → exit 0, stdout has CLEAN_KEY
3. `lock_issues.py lock CLEAN_KEY` → exit 0, stdout has CLEAN_KEY
4. `lock_issues.py lock-strat BLOCKED_STRAT` → exit 1 (STRAT-level gate, unchanged)
5. `lock_issues.py lock-strat CLEAN_STRAT_WITH_ALREADY_LOCKED_RFE` → exit 1
   (linked-RFE contention remains a failure)
