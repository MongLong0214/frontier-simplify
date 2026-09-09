# Running a review

Frontier-simplify review is built for frontier coding agents including Fable and Astra
(`gpt-6-astra`). Choose an executor/model available on your host; intended use is not a measured
claim of safe merge convergence on either model.

[SKILL.md](SKILL.md) owns the question-led prompts and review recommendations. The runner preserves
execution evidence and exact Git targets. It does **not** turn a Markdown verdict into merge
permission. Bash, Git and Python 3.9+ are required; live runs also need a repository-capable executor.
The optional witness replay and the full selftest also require Node 22+.

## One PR, preserved reviews

Run from a trusted installation outside the implementation checkout. Keep one stable PR ID across
attempts. BASE is the merge-base with the target branch, not its tip.

```sh
scripts/review-round.sh 1 "$REPO" "$HEAD" "$PR_ID" "$BASE" codex
REVIEW_RESPONSE=/host/response.md \
  scripts/review-round.sh 2 "$REPO" "$REMEDIATION_HEAD" "$PR_ID" "$BASE" claude
scripts/review-round.sh report "$REPO" HEAD "$PR_ID"
scripts/review-round.sh status "$REPO" "$HEAD" "$PR_ID" "$BASE" codex
scripts/review-round.sh path "$REPO" HEAD "$PR_ID"
scripts/review-round.sh hunks "$REPO" "$REMEDIATION_HEAD" "$PR_ID"
```

Phase 1 reviews the change. Phase 2 checks the repair, the earlier findings, any later open findings,
and remediation regressions. Actual attempt numbers are assigned under a per-PR lock. A follow-up
requires the same base and a descendant of the original head. For unrelated work or changed scope,
a fresh phase 1 consumes the same PR budget. **At most three attempts per stable PR** may start,
including failures and interruptions. The per-PR lock protects the count; it is checked before
creating another attempt or launching an executor. No head, response or phase change resets it.
Legacy attempts count; a PR already over the limit immediately hands off without rewriting history.
The third attempt is the last automatic review. Later calls report the preserved artifacts and
remaining human work without running a model or appending another refusal. Keep the PR ID and
artifact root stable; this is a cooperative host limit, not protection against an operator deleting
history or assigning an alias. It bounds attempts, not repair count or safe merge arrival.
Each executor has a 1,800-second timeout; `REVIEW_TIMEOUT` accepts any positive finite number of
seconds. Timeout and SIGINT/SIGTERM stop its process group, preserve failure output and release
the lock. A process that could not start is recorded as not executed. SIGKILL or a host crash can
leave an interrupted attempt; status detects active runs from the OS lock, not an old PID file.

The implementer response is optional prose. When absent, the reviewer works from the complete diff
and explains any uncertainty. Git-generated hunk IDs are navigation aids, not required mappings.
The runner supplies the exact original review, the latest available follow-up and the full
original-head..remediation-head diff. Reviewers must carry unresolved findings and coverage gaps.

| Exit | Meaning |
|---|---|
| `10` from a review or cached review | Execution evidence recorded; read the review and make the merge decision through the existing review workflow. |
| `11` from a review or cached review | Automatic review budget exhausted; human handoff. The third intact review and all later calls return this. It can contain BLOCKERs, gaps or an unreviewed requested head. |
| `5` from a review | Execution, target or evidence checks failed. |
| Other nonzero | Invocation or environment error. |
| `0` from `status`, `report`, `path` or `hunks` | The read-only utility completed. This is never a PR approval. |

**Review execution never returns 0, including a PASS recommendation and every stub run.** A shell
caller that previously used exit 0 as a merge gate must stop doing so. Do not reinterpret exit 10 as
approval: a BLOCK, an incomplete review and an uninformative answer all share it. Execution completion
and product safety are different questions. The existing maintainer and required product checks
assess the evidence; there is no new approval record or alternate override path.
An evidence failure on attempt three still returns 5 and prints the terminal handoff; subsequent
calls return 11. Neither status licenses a retry beyond the budget. `report` and evidence replay
remain available after the limit. Replay's 10 means evidence availability even for historical
attempts over the limit; replay does not launch a reviewer or grant a new attempt.

The tool does not block or authorize a merge. Required product checks and maintainer decisions do.
Review recommendations remain BLOCK for every confirmed, unresolved defect in scope, including
repair regressions and original blockers discovered later. Missing required evidence prevents a
PASS recommendation. Nits, prose formatting, catalog repetition and the exhausted budget cannot
turn into a product blocker or close one. Humans assess requirements, coverage, severity, disputed
reproductions, closure, and integration risk on the actual merge target.

## Evidence and trust

`REVIEW_ARTIFACTS` selects a host directory outside the consumer checkout, defaulting to
`~/.frontier-simplify-review` for new installations. If `~/.sol-simplify-review` exists, its location
continues to be used so existing PR identities, locks and attempt budgets stay intact. An explicit
`REVIEW_ARTIFACTS` still takes precedence; do not change it merely to rename the product.
Each attempt has frozen inputs, the exact final reviewer message in
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

Replay an explicit ledger against an exact requested target, including an old consumer ledger:

```sh
scripts/review-replay.sh "$REPO" "$LEDGER_DIRECTORY" "$BASE" "$HEAD"
```

This performs no discovery, fetch, execution or ledger writes. It recomputes execution and byte
checks, preserves historical rejections and reports each attempt. Exit 5 names a missing target,
missing execution evidence or integrity failure; exit 10 means the latest attempt at that exact
base..head has preserved evidence for human assessment. An earlier intact attempt cannot hide a
later interrupted attempt at the same target. Neither exit authorizes merging. CI status, product
test counts, mutation measurements and contract versions written in a prompt are not attested by
these receipts. Replay does not manufacture those missing measurements from a reviewer's prose.

Host ownership is an execution-environment responsibility. A digest proves byte equality, not
provenance, and same-user access can rewrite the directory or disable a hook. Event checks are not
an OS sandbox or proof of exhaustive reading. Keep raw logs private: they may contain source and
other tool output. Newline-containing filenames remain unsupported by the line-based target seal.

## Host inputs and consumers

`REVIEW_REQUIREMENTS`, `REVIEW_ROUTED`, `REVIEW_CATALOG`, `REVIEW_SUITE_STATUS` and `REVIEW_TOOL_NOTES`
fill prompt inputs. `REVIEW_EXECUTOR` selects codex or claude; `REVIEW_CODEX_MODEL` optionally selects
the model. Without an explicit base, phase 1 needs `REVIEW_TARGET_BRANCH`; phase 2 inherits its base.
`REVIEW_RESPONSE` optionally names the implementer's separate response.

`REVIEW_EXPECTED_IDS` and `REVIEW_ESCAPES` no longer impose obligations or replenish the budget. Automatically harvested
catalog candidates are attributed leads from the current PR, including rejected reviews. Repetition
and a reviewer's assertion of recurrence never promote a mandatory class. Explicit host catalogs
remain usable inputs, and findings must be checked against current code.
Promotion into a standing question needs reviewed source and new-site evidence with a failing
before/passing after witness, or an explicit continuing contract. The selected question is delivered
through the prompts; its source evidence stays with the consumer, outside the portable skill.

```sh
scripts/review-pr.sh "$CONSUMER_REPO" "$PR_NUMBER" auto
scripts/review-pr.sh "$CONSUMER_REPO" "$PR_NUMBER" status
```

The adapter resolves exact PR commits with `gh`, fetches them into a host clone and invokes the
runner. Auto mode reuses the latest attempt only when head, base, target tip, protocol, executor,
configured model, timeout, supplied prompt inputs, lesson bytes and response bytes (including absence)
match. Changed inputs can use another remaining attempt. Generated leads from the PR's own
reviews do not trigger a repeat. An unchanged failed/interrupted attempt returns 5 without an
automatic retry; explicit `1` or `2` can retry within the same budget. Old receipts without these
input identities remain readable but are not cache hits. Provider-side model revisions and
executor-default configuration are not discoverable here; the revision is recorded as unknown.
When a changed base or rewritten history cannot continue the preserved original review, auto mode
starts a fresh phase 1 within the same remaining PR budget. Explicit phase 2 still rejects that
scope change; it never silently treats unrelated history as a repair.

`status` prints RUNNING, NOT_REVIEWED, RECORDED, FAILED or INTERRUPTED, freshness, attempts and
the artifact path. It launches no reviewer, fetches no Git objects and creates no history. PR status
reads current metadata through `gh`; local status checks the supplied refs and caller inputs.
Use the same input settings as the review when asking whether its result is fresh.

At completion, the runner rechecks mutable local refs; the PR adapter also rereads both PR SHAs.
A moved target or unavailable final metadata returns 5 and labels the preserved artifact STALE.
The artifact still describes its original exact commits. Cached returns recheck PR metadata too.
Freshness is an observation at that check, not a promise that the remote cannot change afterward.
It does not decide whether the PR has merged or whether the review caused a fix.

`SEAL.txt` and the ledger retain the starting protocol SHA-256 (skill instructions and scripts),
including when the installation changes mid-round. `report` displays this identity and the recorded
freshness at finish; older receipts without that observation say UNKNOWN. It reads local evidence
without GitHub access or fetches and announces each attempt before rechecking its evidence. Large
event streams or legacy histories can still take time to check. Use `status` for current PR state,
not `report`'s historical freshness. The reviewer's exact `ARTIFACT.md` is never amended with host metadata.

Consumer configuration lives outside the portable skill. `REVIEW_CONSUMERS_CONFIG` names a JSON
file of consumer repositories and optional portability markers. The maintainer's `dogfood/` command
can discover open PRs through an existing scheduler. Registration alone neither installs a scheduler
nor wires a remote required check.

## Replay a regression and feed it into later reviews

Select the source finding and one top-level Node test that exercises it. The helper copies that
test file from AFTER unchanged into disposable local clones of BEFORE and AFTER. It runs the exact
test name and retains machine events, commands, statuses and hashes outside the consumer checkout:

```sh
python3 scripts/lib/witness.py "$REPO" "$BEFORE" "$AFTER" \
  tests/behavior.test.mjs 'exact test name' "$SOURCE_REVIEW" "$LESSONS/behavior" \
  --lesson 'Does this change repeat the observed cause? Check the relevant sibling paths.'
REVIEW_LESSONS="$LESSONS" scripts/review-pr.sh "$REPO" "$PR_NUMBER" auto
```

Only an assertion failure from that unique named test followed by its passing result publishes
`LEAD.md`. Missing names (even a passing file wrapper), skips, TODOs, load/runtime errors, timeouts,
and a passing test followed by process failure do not count as a repaired regression. The default
timeout is 60 seconds per process; `--timeout` changes it. An existing output directory is refused
so a failed rerun cannot accidentally republish stale success. Exit 0 means this measured contrast
was recorded, never that the consumer can merge. Logs and source reviews may contain private code;
keep the lesson directory host-owned and private.

`REVIEW_LESSONS` supplies all `*/LEAD.md` files to both review phases along with current-PR leads
and an explicit `REVIEW_CATALOG`. The host selects the question and source relation; the helper
does not infer them from prose or call repetition independent recurrence. The result demonstrates
one regression witness and delivery of its lesson, not improved model recall. There is no automatic
code patch, class promotion or merge. Dependencies must already be available to the test in the
clones; this helper installs none. It supports flat `.mjs` Node tests; other runners need an adapter
that reads their own named test results, not an imitation of Node's pass-count behavior.

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

`frontier-simplify: keep the hook while maintaining this runner; remove it when the runner is no longer
maintained here, restoring pre-commit.before-review if present.`
