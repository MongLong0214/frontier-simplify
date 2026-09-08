# Running a review

[SKILL.md](SKILL.md) owns the question-led prompts and review recommendations. The runner preserves
execution evidence and exact Git targets. It does **not** turn a Markdown verdict into merge
permission. Bash, Git and Python 3.9+ are required; live runs also need a repository-capable executor.

## One PR, preserved reviews

Run from a trusted installation outside the implementation checkout. Keep one stable PR ID across
attempts. BASE is the merge-base with the target branch, not its tip.

```sh
scripts/review-round.sh 1 "$REPO" "$HEAD" "$PR_ID" "$BASE" codex
REVIEW_RESPONSE=/host/response.md \
  scripts/review-round.sh 2 "$REPO" "$REMEDIATION_HEAD" "$PR_ID" "$BASE" claude
scripts/review-round.sh report "$REPO" HEAD "$PR_ID"
scripts/review-round.sh path "$REPO" HEAD "$PR_ID"
scripts/review-round.sh hunks "$REPO" "$REMEDIATION_HEAD" "$PR_ID"
```

Phase 1 reviews the change. Phase 2 checks the repair, the earlier findings, any later open findings,
and remediation regressions. Actual attempt numbers are assigned under a per-PR lock. A follow-up
requires the same base and a descendant of the original head. For unrelated work or changed scope,
run a new phase 1; it retains the attempt history. More than two attempts needs no escape form.

The implementer response is optional prose. When absent, the reviewer works from the complete diff
and explains any uncertainty. Git-generated hunk IDs are navigation aids, not required mappings.
The runner supplies the exact original review, the latest available follow-up and the full
original-head..remediation-head diff. Reviewers must carry unresolved findings and coverage gaps.

| Exit | Meaning |
|---|---|
| `10` from a review or cached review | Execution evidence recorded; read the review and make the merge decision through the existing review workflow. |
| `5` from a review | Execution, target or evidence checks failed. |
| Other nonzero | Invocation or environment error. |
| `0` from `report`, `path` or `hunks` | The read-only utility completed. This is never a PR approval. |

**Review execution never returns 0, including a PASS recommendation and every stub run.** A shell
caller that previously used exit 0 as a merge gate must stop doing so. Do not reinterpret exit 10 as
approval: a BLOCK, an incomplete review and an uninformative answer all share it. Execution completion
and product safety are different questions. The existing maintainer and required product checks
assess the evidence; there is no new approval record or alternate override path.

## Evidence and trust

`REVIEW_ARTIFACTS` selects a host directory outside the consumer checkout, defaulting to
`~/.sol-simplify-review`. Each attempt has frozen inputs, the exact final reviewer message in
`ARTIFACT.md`, the event stream, process status, checks and hashes. A local disposable clone keeps the
consumer checkout untouched. No script pushes, posts reviews or merges.

The checks verify the target, execution completion, evidence of tool use, final-message identity
and preserved bytes. They do not certify reading coverage, correct severity, sibling completeness
or product truth. No prose parser counts findings or authorizes work. An uninformative final answer
is still preserved evidence of an uninformative run, never a pass. Read the event stream if a final
message is only a correction to earlier text; it does not restore an earlier draft as a final verdict.

Legacy receipts retain their original acceptance and counts, labelled historical. Their hashes are
checked without rewriting the ledger or reclassifying a rejection as approval. An old artifact whose
execution/target evidence checks out can now be read by a follow-up even if its Markdown was refused.
The original limitations remain visible. Generic legacy `inventory` errors cannot be retrospectively
split when their leaf diagnostic was never recorded. Available leaf reasons are reported separately.

Host ownership is an execution-environment responsibility. A digest proves byte equality, not
provenance, and same-user access can rewrite the directory or disable a hook. Event checks are not
an OS sandbox or proof of exhaustive reading. Keep raw logs private: they may contain source and
other tool output. Newline-containing filenames remain unsupported by the line-based target seal.

## Host inputs and consumers

`REVIEW_REQUIREMENTS`, `REVIEW_ROUTED`, `REVIEW_CATALOG`, `REVIEW_SUITE_STATUS` and `REVIEW_TOOL_NOTES`
fill prompt inputs. `REVIEW_EXECUTOR` selects codex or claude; `REVIEW_CODEX_MODEL` optionally selects
the model. Without an explicit base, phase 1 needs `REVIEW_TARGET_BRANCH`; phase 2 inherits its base.
`REVIEW_RESPONSE` optionally names the implementer's separate response.

`REVIEW_EXPECTED_IDS` and `REVIEW_ESCAPES` no longer impose obligations. Automatically harvested
catalog candidates are attributed leads from the current PR, including rejected reviews. Repetition
and a reviewer's assertion of recurrence never promote a mandatory class. Explicit host catalogs
remain usable inputs, and findings must be checked against current code.

```sh
scripts/review-pr.sh "$CONSUMER_REPO" "$PR_NUMBER" auto
```

The adapter resolves exact PR commits with `gh`, fetches them into a host clone and invokes the
runner. Auto mode reviews each head once and routes changed heads to follow-up when an original
review is available. Explicit `1` or `2` can retry. Cached results have the same nonapproval status.
It does not decide whether the PR has merged or whether the review caused a fix.

Consumer configuration lives outside the portable skill. `REVIEW_CONSUMERS_CONFIG` names a JSON
file of consumer repositories and optional portability markers. The maintainer's `dogfood/` command
can discover open PRs through an existing scheduler. Registration alone neither installs a scheduler
nor wires a remote required check.

## Offline verification and hook

```sh
scripts/selftest.sh
scripts/install-hook.sh "$SKILL_REPOSITORY"
```

The hook tests one staged tree with the installed tests and the staged tests. It preserves an
existing hook and ignores unrelated changes. Installed failure witnesses prevent a candidate from
passing merely by deleting its tests. They cannot prove that the installed protocol itself is right.
When deliberately replacing protocol semantics, select and test the new version, then reinstall the
hook from that version so retired contract tests do not pin the old design forever. This is a local
installation change, not a release or a push.

Tests cover failed execution, altered artifacts, commit/ancestry mismatches, prose handoff, later
open findings, cached status and the absence of an automatic approval path. They do not measure
reviewer recall or safe merge completion. The [reassessment](../../dogfood/REASSESSMENT.md) explains
why the Markdown gates and their tests were retired.

`sol-simplify: keep the hook while maintaining this runner; remove it when the runner is no longer
maintained here, restoring pre-commit.before-review if present.`
