# Bug: clone_issue.py Copies Target Version by Version ID, Invalid in Target Project

## Summary

`clone_issue.py` copies the Target Version field (`customfield_10855`) from the
source RHAIRFE issue using the version **id** in preference to the name. Jira
version ids are project-scoped, so an id that exists in RHAIRFE does not exist in
RHAISTRAT. The `create_issue` call is rejected with an HTTP 400, and every
RFE -> STRAT clone of an RFE that has a Target Version set fails on first
attempt.

Error returned by the Jira API:

```
HTTP 400: {"errorMessages":[],"errors":{"customfield_10855":"Version id 'Target Version' is not valid"}}
```

(Concrete instances observed: `Version id '107605' is not valid`,
`Version id '107607' is not valid`.)

## Reproduction

1. Pick a RHAIRFE issue with a Target Version set (e.g. RHAIRFE-2776, Target
   Version "3.6 EA1 RHOAI RELEASE", id `107605`).
2. Run the clone into RHAISTRAT (`scripts/clone_issue.py`), as the
   `strategy-create` skill / `batch-jql` pipeline does.
3. `clone_issue.py` reads `customfield_10855` as full version objects and builds
   `target_versions = [{"id": v["id"]}, ...]`.
4. `create_issue()` posts `customfield_10855: [{"id": "107605"}]` to RHAISTRAT.
5. Jira rejects the create with `HTTP 400 ... "customfield_10855":"Version id
   '107605' is not valid"` because id `107605` belongs to RHAIRFE, not
   RHAISTRAT.

## Expected

The clone succeeds and the RHAISTRAT issue is created with the equivalent Target
Version resolved by **name** in the target project. The clone should send the
matching RHAISTRAT version id when one is found. If no equivalently named target
version exists, it should omit that Target Version rather than fail the entire
issue creation.

## Actual

The create call returns HTTP 400 and the clone fails. In the batch pipeline the
agent self-heals at runtime -- it patches `clone_issue.py` in
`/tmp/claude-workdir` to copy by name and retries -- but that patch lives only in
the runner workspace and is discarded when the container exits. Every run
re-clones `strat-creator` main, hits the same failure, and depends on the agent
improvising the same fix (~40s of wasted wall-clock plus tokens per batch, with
no guarantee of the same outcome).

## Root Cause

`scripts/clone_issue.py` (lines 105-112, commit `fcb2fff` "Prefer version id
over name when copying Target Version"):

```python
# Target Version (customfield_10855) is a multi-version picker. Prefer the
# stable version id over the name so it resolves unambiguously in the
# target project; fall back to name when no id is present.
target_versions = [
    {"id": v["id"]} if v.get("id") else {"name": v["name"]}
    for v in (fields.get("customfield_10855") or [])
    if isinstance(v, dict) and (v.get("id") or v.get("name"))
]
```

The premise in that comment is inverted. Version ids are per-project in Jira; the
**name** is what resolves across projects. Every other version field in the same
function (`versions`/affects-versions, `components`) already copies by name.
Commit `fcb2fff` switched Target Version to prefer id, on the assumption that id
resolves "unambiguously in the target project" -- the opposite is true for a
cross-project clone.

## Impact

- **Every RFE -> STRAT clone of an RFE with a Target Version fails on first
  attempt.** Observed in strat-pipeline run 2704164315 (2026-07-24, Observatory
  trace 3972): 6 of 8 initial clones failed; and job 15561141445 (pipeline
  2709949648, 2026-07-27): all 9 clones failed silently before runtime repair.
- **CI never goes red.** The `strategy-create` skill invokes `clone_issue.py`
  with `2>/dev/null`, so the failure is silent; the batch job survives only
  because the agent re-runs one clone with stderr visible, diagnoses the
  project-scoped id, edits the script in `/tmp`, and retries. The fix is
  ephemeral and recurs on every run.
- **Wasted wall-clock and tokens per batch**, with no guarantee the self-heal
  reproduces.

## Secondary Issue (exception handling)

The exception handler inspects only the `HTTPError` string representation, which
is `"HTTP Error 400: Bad Request"` -- the actual `customfield_10855` detail lives
in the response **body**, not the string. A handler that keys on the substring
`"customfield_10855"` will never match. Diagnosing this class of failure requires
reading the response body.

## Fix

1. Fetch the versions belonging to the target project and index them by name.
2. For each source Target Version, look up its name in that target-project index.
   When a match exists, copy it using the **target project's version id**. Never
   fall back to the source version id, because that id belongs to RHAIRFE.
3. If the source value has no name, or its name has no match in the target
   project, omit that Target Version value. If none resolve, do not set
   `customfield_10855` on the new issue.
4. Update tests: `test_target_version_is_copied_to_clone` (line 101) now seeds
   versions into RHAISTRAT and asserts target-project id resolution;
   `test_target_version_resolves_by_name_in_target_project` (line 128) verifies
   that unmatched source versions are omitted without preventing the clone.
   (Replaces the former `test_target_version_prefers_id_over_name` which
   asserted the broken behaviour.)
5. Consider surfacing the Jira response body in the `create_issue` error path so
   `customfield_10855` failures are diagnosable without a re-run.

## Test Gap

The former `test_target_version_prefers_id_over_name` asserted the broken
behaviour and passed because the jira-emulator does not model project-scoped
version ids. It has been replaced by
`test_target_version_is_copied_to_clone` (line 101) and
`test_target_version_resolves_by_name_in_target_project` (line 128), which
seed versions into RHAISTRAT and assert target-project id resolution and
omission of unmatched versions respectively.

## Scope of Fix

| File | Change |
|------|--------|
| `scripts/clone_issue.py` | Resolve Target Versions by name against target-project versions; use the matching target id and omit unresolved values |
| `tests/test_clone_issue.py` | Rework `test_target_version_prefers_id_over_name` to assert target-project resolution and omission behavior |
| jira-emulator | (optional) Reject version ids not belonging to the target project |
| `scripts/jira_utils.py` | (optional) Surface Jira response body on `create_issue` HTTP 400 |

## Related

- RHAIFIRST-323 -- clone_issue.py copies Target Version by version id, which is
  invalid in the target project (canonical Jira write-up).
- RHAIFIRST-309 -- strat-creator: clone operations fail on customfield_10855
  (duplicate of RHAIFIRST-323; blocked in triage on missing repo URL).
- RHAIFIRST-303 -- Copy Target Version from RFE to STRAT on clone (the earlier
  "field never copied" bug; commit `a5eb6c9` added the copy, `fcb2fff` then
  introduced the id-preference that this bug reports).

## Timeline

- **2026-07-23** (`a5eb6c9`): Target Version copy added to clone (RHAIFIRST-303).
- **2026-07-23** (`fcb2fff`): switched to prefer version id over name -- introduces this bug.
- **2026-07-24**: strat-pipeline run 2704164315, 6 of 8 clones fail; RHAIFIRST-309 filed.
- **2026-07-27**: job 15561141445, all 9 clones fail silently, agent self-heals at runtime.
- **2026-07-28**: RHAIFIRST-323 filed with full root-cause analysis.
