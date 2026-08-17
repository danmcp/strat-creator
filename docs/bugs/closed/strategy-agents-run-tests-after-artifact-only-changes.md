# Bug: Strategy Agents Run Tests After Artifact-Only Changes

## Summary

The `strategy-create`, `strategy-refine`, and `strategy-review` workflows can
run the strat-creator repository test suite after changing only generated
strategy artifacts, frontmatter, review attachments, or Jira labels. Those
tests exercise the repository implementation and do not validate the generated
strategy content, adding about four minutes of unnecessary work to affected
pipeline jobs.

Tracked as RHAIFIRST-466.

## Reproduction

1. Launch Claude Code with the strat-creator checkout as its working directory,
   as strat-pipeline does through its `CLAUDE_REPO` checkout.
2. Invoke `/strategy-refine RHAISTRAT-NNNN` for a strategy that needs
   refinement.
3. Allow the skill to update the strategy artifact and frontmatter and to
   perform its configured Jira updates. Do not change a script, library, test,
   or other repository implementation file.
4. Observe the agent begin repository verification after the artifact and Jira
   work, commonly invoking `make test-unit` and then `pytest` or `make test`.
5. In some CI environments, observe repeated variants of those commands when
   the first invocation lacks a dependency.

Representative observed output:

```text
Now let me run the tests to verify.
make test-unit
uv run pytest tests/ -v --tb=short
All 618 tests passed (1 skipped)
```

The behavior has been observed repeatedly in pipeline traces, including
artifact-only work immediately before the test commands. It was still present
on 2026-08-17 in Observatory run 11419 while processing RHAISTRAT-2575 and
RHAISTRAT-2577.

## Expected

Repository tests run only when executable implementation, test, configuration,
or build files change (`scripts/`, `tests/`, `Makefile`, `pyproject.toml`).
Agent instruction changes (`CLAUDE.md`, `.claude/skills/*/SKILL.md`) require
only skill-integrity checks. Documentation-only changes and workflow output
(strategy artifacts, frontmatter, review attachments, Jira fields and labels)
do not trigger the strat-creator test suite.

## Actual

The agent treats completion of artifact-only strategy work as requiring the
repository test suite. A job may run both unit and full pytest suites and may
retry three to six command variants before succeeding.

## Confirmation

Confirmed by static inspection at strat-creator commit
`2588e668f89c719946723430ec2dde8bc0047fd6`:

- Root project instructions in `CLAUDE.md` say, "After every code change, run
  the test suite in a background subagent before reporting the change as
  complete," and later require the full suite before a push.
- The root instructions apply when strat-pipeline uses the strat-creator clone
  as Claude Code's working directory; they are not limited to maintenance of
  scripts or library code.
- None of `.claude/skills/strategy-create/SKILL.md`,
  `.claude/skills/strategy-refine/SKILL.md`, or
  `.claude/skills/strategy-review/SKILL.md` contains a `make test`, `pytest`, or
  test-suite instruction.
- `strategy-refine` explicitly writes strategy content and frontmatter and can
  push the Strategy section and labels to Jira. Those output steps contain no
  source-diff gate before completion.

The literal root rule says "code change," not "any change." Therefore the
unnecessary test run is an agent generalization rather than a direct command in
the strategy skills. The defect is nevertheless enabled by ambiguous global
instructions: they prescribe mandatory verification without defining which
paths constitute code or explicitly exempting workflow artifacts and external
Jira writes.

## Root Cause

Strat-pipeline clones strat-creator as the agent's working directory rather than
loading it only as a plugin. Consequently, `CLAUDE.md` is active as root project
guidance for every strategy workflow.

Its Testing section is repository-maintenance guidance, but it is globally
visible during artifact-production workflows. There is no explicit path-based
scope or exemption for:

- `artifacts/` and `local/` strategy/review content
- frontmatter and strategy-history updates
- review attachments
- Jira description, field, and label updates

There is also no post-work diff gate that would prevent tests when no repository
implementation changed. The strategy skills do not independently request the
tests.

## Impact

- About four minutes of unnecessary runtime and compute per affected job.
- Three to six failed or redundant test command attempts can be added when the
  CI environment lacks an expected dependency or invocation path.
- Pipeline duration becomes coupled to the complete strat-creator test suite
  even though only generated content or external issue state changed.
- Passing repository tests can misleadingly appear to validate the generated
  strategy, although those tests validate implementation behavior instead.
- The same post-processing pattern affects create and review as well as refine.

## Proposed Fix

Replace the ambiguous Testing section with tiered verification rules: require
repository tests only for executable implementation, test, configuration, and
build files (`scripts/`, `tests/`, `Makefile`, `pyproject.toml`); require
skill-integrity checks for agent instruction files (`CLAUDE.md`,
`.claude/skills/*/SKILL.md`); exempt documentation-only changes and workflow
output (artifacts, frontmatter, Jira updates) entirely. Keep `make test`
mandatory before an actual remote push of repository code.

## Implementation

Fixed in CLAUDE.md by replacing the ambiguous Testing section with four
explicit subsections, each with its own verification rule:

1. **"Implementation and test changes"** -- scopes mandatory repository test
   runs to executable code: `scripts/`, `tests/`, `Makefile`, `pyproject.toml`.

2. **"Agent instruction changes"** -- `CLAUDE.md` and
   `.claude/skills/*/SKILL.md` get skill-integrity checks
   (`test_skill_integrity.py`), not the full repository test suite.

3. **"Documentation-only changes"** -- files under `docs/` (bug reports,
   ledger entries, plans, ADRs) do not require any repository test command
   unless they accompany implementation changes.

4. **"Workflow output"** -- enumerates every category of workflow output
   (strategy artifacts, frontmatter, review files, Jira updates, architecture
   context fetches, state files) and explicitly states that strategy skills
   produce only workflow output during normal operation.

No changes to the three strategy skill files -- they never contained test
commands. The root cause was solely in the global CLAUDE.md instructions.

No regression tests were added. The defect is agent behavior driven by prose
instructions; the repository's test suite validates implementation code, not
agent instruction compliance. The real regression signal is pipeline trace
observation after deployment.

### Files changed

- `CLAUDE.md` -- Testing section rewritten with four-tier verification rules
  and artifact exemption.

### Verification performed

1. **Artifact-only exemption**: CLAUDE.md workflow-output subsection explicitly
   lists `artifacts/`, `local/`, frontmatter updates, review attachments, Jira
   operations, `.context/`, and `tmp/`.
2. **Code-change testing preserved**: `scripts/`, `tests/`, `Makefile`, and
   `pyproject.toml` are listed as requiring repository tests.
3. **Instruction changes scoped**: `CLAUDE.md` and `.claude/skills/*/SKILL.md`
   are classified as agent instructions requiring integrity checks, not the
   full test suite.
4. **Documentation exempted**: `docs/` files are classified as passive
   documentation not requiring repository tests on their own.
5. **Push requirement preserved**: "Always run `make test` (full suite
   including integration tests) before pushing repository code to remote"
   remains.
6. **Skill-integrity tests pass**: `test_skill_integrity.py` -- all pass.
7. **`git diff --check`**: no whitespace errors.

### Limitations

- The fix is instruction-based. An agent could still choose to run tests, but
  the instructions now leave no reasonable ambiguity. Full confirmation requires
  observing pipeline traces after deployment (Verification item 4 from the
  original plan).

## Related

- RHAIFIRST-466 -- strategy-refine agent runs full test suite after artifact-only
  changes.
