# ADR-0002: Multi-Clone RFE Exclusion Override

## Status

Accepted

## Context

`find_processed_rfe_ids` in `scripts/jira_utils.py` decides which RFEs the
`batch-jql` pipeline should skip. It queries RHAISTRAT for clones that have
pipeline skip labels (`strat-creator-rubric-pass`, `strat-creator-needs-attention`,
`strat-creator-processing`) or are in an excluded status (`In Progress`, `Review`,
`Release Pending`, `Closed`, `Resolved`), traces their Cloners links back to
RHAIRFE keys, and adds those keys to an exclusion set. The implicit assumption is
one RHAISTRAT clone per RFE.

That assumption breaks when a STRAT is closed (e.g. as a duplicate or at the end
of a release cycle) and a replacement clone is created for the next cycle. The old
closed clone triggers exclusion, and the pipeline never sees the replacement.
RHAIRFE-2100 was stranded for 24+ days because of this -- its old clone
(RHAISTRAT-1755, Closed with `strat-creator-rubric-pass`) blocked the new clone
(RHAISTRAT-2210, New, no labels) from ever being processed.

Three approaches were considered:

- **Exclude only when all clones are terminal.** Correct semantics for any number
  of clones, but requires fetching all RHAISTRAT issues to build a complete
  RFE-to-clones map. Broader queries and more complex logic than the bug warrants.
- **Consider only the most recent clone.** Simple heuristic that handles the
  release-cycle-rollover case but is fragile if multiple active clones exist
  simultaneously.
- **Override when exactly one open clone needs processing.** Keeps the existing
  exclusion as the default and adds a narrow override for the replacement-clone
  case. Rejects the self-split antipattern (2+ open clones) by design.

## Decision

Keep the existing exclusion logic as the default. After building the exclusion
set, run two additional queries:

1. Count all open clones per RFE -- RHAISTRAT issues not in any excluded status,
   regardless of labels.
2. Identify which RFEs have at least one open clone without skip labels.

Override the exclusion (remove the RFE from the processed set) only when both
conditions hold:

- The RFE has **exactly one** open RHAISTRAT clone (total, including labeled ones).
- That sole open clone has **no skip labels**.

This means:

| Open clones (total) | Unlabeled among them | Override? | Rationale |
|-|-|-|-|
| 0 | 0 | No | All clones are terminal; work is done |
| 1 | 1 | **Yes** | Replacement clone needs processing |
| 1 | 0 | No | Sole open clone already has a skip label |
| 2+ | any | No | Multiple open clones; ambiguous, let humans sort it out |

The "exactly one" constraint is load-bearing: it prevents the pipeline from
repeatedly re-discovering an RFE that has multiple open clones. Without it, an
RFE with two unlabeled open clones would pass the override, enter `batch-jql`,
and be picked up by `strategy-create`, which checks for multiple open STRATs and
skips the RFE as ambiguous. The RFE would then be rediscovered on the next
6-hour cycle, consuming a batch slot without processing either clone -- the same
silent pipeline starvation this fix aims to prevent.

The two-query separation (count all open clones, then check labels) is also
load-bearing: a single query that filters out skip-labeled clones before counting
would make an RFE with one unlabeled clone and one labeled clone look like it has
exactly one open clone, triggering a false override.

## Consequences

Positive:

- Unblocks the replacement-clone case with minimal change to the existing
  exclusion logic. The two original queries are unchanged; the override is
  additive.
- Rejects the self-split antipattern by design -- 2+ open clones stay excluded.
- Two extra Jira queries only fire when the processed set is non-empty, so no
  cost on runs that find nothing to exclude.

Negative:

- Does not handle a legitimate need for multiple open clones from the same RFE.
  If that need arises, this rule must be revisited.
- An RFE with zero open clones and only terminal clones without skip labels (e.g.
  a STRAT closed without ever reaching `rubric-pass`) will not be excluded by the
  original queries and will re-enter the pipeline, potentially triggering a new
  clone. This is acceptable -- if no clone completed successfully, the RFE
  genuinely needs reprocessing.

## Related

- [Bug report](../bugs/open/find-processed-rfe-ids-over-excludes.md)
- `scripts/jira_utils.py`: `find_processed_rfe_ids`, `_count_rfe_clones_from_issues`
