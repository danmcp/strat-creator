# ADR-0003: [DRAFT] Prefix Lifecycle for RHAISTRAT Summaries

## Status

Accepted

## Context

When the pipeline creates a RHAISTRAT by cloning an RHAIRFE, the new issue
appears in Jira with a summary indistinguishable from a human-authored, reviewed
strategy. The label system (`strat-creator-auto-created`, `rubric-pass`,
`needs-attention`, `human-sign-off`) encodes lifecycle state, but labels require
clicking into each issue or constructing JQL. The summary is visible in list
views, boards, and search results -- it's the first thing stakeholders see.

RHAISTRAT-2524 already uses `[DRAFT]` as a manual prefix, with its description
noting "DRAFT -- human-authored, not pipeline-generated." This ADR standardizes
that convention for all pipeline-created strategies.

The key design question is when to remove the prefix. Four options were
evaluated:

- **Option A (remove at rubric-pass):** Earliest quality signal, but rubric-pass
  is a machine judgment. Requires re-adding `[DRAFT]` when `strategy-push`
  removes rubric-pass for re-review -- a second code path.
- **Option B (remove at human-sign-off):** Strongest signal, simplest lifecycle.
  One add at creation, one remove at sign-off. No interaction with push-back
  loops. Trade-off: strats sitting at rubric-pass still show `[DRAFT]`.
- **Option C (remove on Jira status transition):** Aligns with Jira workflow but
  status transitions are inconsistent across teams and the pipeline does not
  monitor them. Requires either a Jira automation rule or a new polling step.
- **Option D (two-stage: [DRAFT] -> [REVIEW] -> none):** Maximum visibility but
  two prefix transitions to maintain, and push-back requires reverting `[REVIEW]`
  to `[DRAFT]`.

## Decision

**Option B: add `[DRAFT]` at creation, remove at human-sign-off.**

1. `clone_issue.py` prepends `[DRAFT]` (followed by a space) to the summary
   when creating the RHAISTRAT.
2. `strategy-signoff` strips the `[DRAFT]` prefix and its trailing space (if
   present) when adding the `human-sign-off` label.
3. Removal is idempotent -- if the summary does not start with `[DRAFT]`, the
   update is skipped. This handles manually-created strats and strats predating
   this feature.

Rationale:

- **Simplest lifecycle** -- one add, one remove, no re-add during push-back.
- **Strongest signal** -- a human has endorsed the content.
- **Conservative** -- errs on keeping `[DRAFT]` longer. A stakeholder seeing
  `[DRAFT]` on a CI-approved strategy will dig into labels; a stakeholder seeing
  no prefix on a strategy that was only CI-approved might assume it's finalized.
- **No interaction with push-back** -- `strategy-push` removes `rubric-pass` or
  `needs-attention` but not `human-sign-off`, and sign-off hasn't happened at
  that point, so `[DRAFT]` is never incorrectly stripped.

**No backfill or rolling enforcement.** Strategies created before this feature
will not have the `[DRAFT]` prefix, and the refine/review/push skills will not
add it retroactively. Those skills currently never touch the Jira summary;
adding a "ensure `[DRAFT]` is present" step would introduce summary writes (with
Jira notifications and history entries) on every pipeline run for a problem that
is limited to a finite, shrinking set of pre-existing strategies. If backfill
becomes important, a one-time JQL-targeted script is the preferred approach over
embedding it in the pipeline's ongoing code paths.

## Consequences

Positive:

- Stakeholders browsing Jira can immediately distinguish pipeline drafts from
  finalized strategies without inspecting labels.
- Consistent with the existing manual precedent (RHAISTRAT-2524).
- No changes needed to `strategy-push`, `strategy-refine`, or `strategy-review`.

Negative:

- Strategies at `rubric-pass` still show `[DRAFT]`, which may feel noisy to
  engineers. If this proves problematic, Option D (two-stage) can be adopted
  incrementally.
- Strategies that never receive human sign-off retain `[DRAFT]` permanently.
- Summary modifications generate Jira notifications and history entries (can be
  mitigated with `notifyUsers=false` on the REST call).

## Related

- RHAISTRAT-2524: Manual `[DRAFT]` precedent
