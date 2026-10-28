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
scripts/review-round.sh witnesses "$REPO" "$REMEDIATION_HEAD" "$PR_ID"
scripts/review-round.sh 2 "$REPO" "$REMEDIATION_HEAD" "$PR_ID" "$BASE" codex \
  --supplementary --granted-by "$WHO" --budget 2
```

Phase 1 reviews the change. Phase 2 checks the repair, the earlier findings, any later open findings,
and remediation regressions. Actual attempt numbers are assigned under a per-PR lock. A follow-up
requires the same base and a descendant of the original head. For unrelated work or changed scope,
a fresh phase 1 consumes the same PR budget. **At most three attempts per stable PR** may start,
including failures and interruptions; only a recorded supplementary grant (below) adds more. The per-PR lock protects the count; it is checked before
creating another attempt or launching an executor. No head, response or phase change resets it.
Legacy attempts count; a PR already over the limit immediately hands off without rewriting history.
The third attempt is the last automatic review. Later calls report the preserved artifacts and the
calling agent's next action without running a model or appending another refusal. Keep the PR ID and
artifact root stable; this is a cooperative host limit, not protection against an operator deleting
history or assigning an alias. It bounds attempts, not repair count or safe merge arrival.
Each executor has a 1,800-second timeout; `REVIEW_TIMEOUT` accepts any positive finite number of
seconds. The two validators share one such deadline, so an attempt that runs them can take up to
twice `REVIEW_TIMEOUT`. Timeout and SIGINT/SIGTERM stop every executor's process group, preserve
failure output and release the lock. A process that could not start is recorded as not executed. SIGKILL or a host crash can
leave an interrupted attempt; status detects active runs from the OS lock, not an old PID file.

The implementer response is optional prose. When absent, the reviewer works from the complete diff
and explains any uncertainty. Git-generated hunk IDs are navigation aids, not required mappings.
The runner supplies the exact original review, the latest available follow-up and the full
original-head..remediation-head diff. Reviewers must carry unresolved findings and coverage gaps.

| Exit | Meaning |
|---|---|
| `10` from a review or cached review | Review recorded. The calling agent reads the finder's review, each validator answer that ran (or why they were skipped) and the required checks. When nothing blocking remains on the exact reviewed head and the required checks pass, it continues its existing completion path; otherwise it repairs, refutes or marks findings nonblocking and runs the follow-up. Rerunning with unchanged inputs returns the same cached result. The status alone never completes the task. |
| `11` from a review or cached review | Automatic review budget exhausted. The third intact review and all later calls return this. When `status` shows the latest review `RECORDED FRESH` for the exact requested head, its validators completed or were skipped, no blocking finding remains and the required checks pass, the calling agent continues its existing completion path; otherwise it ends the task as failed, naming what remains. |
| `5` from a review | Valid invocation, but repository/ref, preparation, execution or evidence failed, including a validator that failed, timed out or answered nothing. The raw child exit/signal remains in its receipt. The calling agent repairs what its task already permits within the budget or ends as failed. |
| `12` | Historical: earlier runners returned it, without reserving an attempt, when a contract invariant stayed open in two consecutive reviews. Current runners note the recurrence and review; repair the cause structurally. |
| `13` from a later review or `witnesses` | A preserved reviewer witness fails on the requested head. No attempt is reserved and no model runs; fix the failure or name a witness shown to be wrong in `REVIEW_WITNESS_DISPUTED`. The same state returns the same result. |
| `2` | Command syntax or argument count is invalid; no attempt is reserved. |
| `0` from help, `status`, `report`, `path`, `hunks` or a passing `witnesses` | The utility completed. This is never a PR approval. |

**Review execution never returns 0, including a PASS recommendation and every stub run.** A shell
caller that previously used exit 0 as a merge gate must stop doing so. Do not reinterpret exit 10 as
approval: a BLOCK, an incomplete review and an uninformative answer all share it. Execution completion
and product safety are different questions. The calling agent assesses the evidence against the
required product checks; there is no new approval record or alternate override path.
An evidence failure on attempt three still returns 5 and prints the terminal handoff; subsequent
calls return 11. Neither status licenses a retry beyond the budget. `report` and evidence replay
remain available after the limit. Replay's 10 means evidence availability even for historical
attempts over the limit; replay does not launch a reviewer or grant a new attempt.

The tool does not block or authorize a merge. Required product checks and existing merge permissions do.
Review recommendations remain BLOCK for every confirmed, unresolved defect in scope, including
repair regressions and original blockers discovered later. Missing required evidence prevents a
PASS recommendation. Nits, prose formatting, catalog repetition and the exhausted budget cannot
turn into a product blocker or close one. The calling agent assesses requirements, coverage, severity,
disputed reproductions, closure and integration risk on the actual merge target, and ends the task as
failed when a judgment or evidence it needs stays open; nobody is asked to answer.

## Finder and validators

One attempt is one finder review and, when needed, two validators over its whole answer: a refuter
and a reproducer. They run in parallel in separate fresh checkouts of the reviewed head, each with the
finder's inputs, its answer as `CANDIDATE_REVIEW.md` and the witnesses preserved so far. Neither sees
the other's answer and no further model combines them; the calling agent reads all three. Their files
sit in the same round with a `refuter-` or `reproducer-` prefix (prompt, events, stderr, exit and
`ARTIFACT.md`); the top-level `ARTIFACT.md` and `events.jsonl` stay the finder's own.

The validators are skipped only for a first review that inherits no earlier review and whose final
answer's last nonblank line is exactly `Validation candidates: NONE`. The runner reads that one line
and nothing else in the prose; the skip is not a PASS. Otherwise both run, follow-ups included. They
start only after a finder review that would itself be recorded, so an empty or failed finder launches
neither. An attempt that needed them is recorded only when both exit 0 with a nonempty final answer.
A failure, empty answer, timeout or failed setup returns `5` and keeps every output the validators
wrote; the finder's review still feeds the next follow-up, which receives `PRIOR_VALIDATION.md` and
copies of the earlier validators' answers. A cancellation also keeps what they wrote and ends the
attempt as cancelled. Witnesses a validator writes merge into the round's `WITNESSES.json`; a path
another reviewer of the attempt already preserved keeps its first copy and lists the later one as
skipped. The validators' checkouts are disposable and not observed for mutations as the finder's is.
`status` and `report` name each validator's answer or why it was skipped, failed or not run.

## Contracts, witnesses and supplementary reviews

A contract defect is reported as one invariant, the sites that share its cause and an optional
stable key in a final `- invariant: KEY | family N | STATUS | sentence` line; a producer/sink table
is optional. The host carries every key's latest status and the attempts that reported it open into
the next prompt so the reviewer reuses the key. If the same key is OPEN, ROUND1-ESCAPE or REGRESSION
in the two latest recorded reviews, the next prompt, stderr, `status` and the handoff note that its
cause needs a structural repair; the review still runs. `REVIEW_REDESIGN` (or `pr-N-redesign.md`
beside the PR adapter's response file) optionally supplies a redesign, frozen for a later review as
`IMPLEMENTER_REDESIGN.md`. The lines are read only to carry keys and notes. A reviewer that omits
them changes nothing, and that absence is not convergence.
A family-5 key that stays open while most new non-test code lines since the last review are
conditionals or early exits adds an advisory repair-shape note; it blocks nothing.

`review_evidence/` is created in each checkout. Files the reviewer writes there are copied to
`round-NNNN/witnesses/` with a hashed `WITNESSES.json` (regular files only; links, dependency and
cache directories, files over 1 MiB, and anything past 16 MiB or 200 files are listed as skipped).
A witness is a top-level `review_evidence/<ID>.sh`, run as `bash` from the repository root: nonzero
while the defect is present, 0 once it is fixed. Before any later review reserves an attempt, every
active witness from the PR's recorded reviews runs in a clean exact-head clone, `REVIEW_WITNESS_TIMEOUT`
seconds each (default 300). Witnesses stay with the PR in every phase, across restarts and changed
bases, until retired with a reason.
The whole preserved bundle is restored over the tree there and checked byte for byte before anything
runs, so the tree under review cannot supply a witness or a helper it reads; a bundle that cannot be
restored intact is an ERROR. Restoration never writes through a link. Any FAIL, TIMEOUT or ERROR returns `13`. `REVIEW_WITNESS_DISPUTED`
lets named failing witnesses through, marked disputed for the reviewer. Results are frozen as
`WITNESS_RESULTS.md` and the files are restored into the reviewer's checkout without replacing its
tracked files. A reviewer retires a
witness with `- witness_obsolete: ID -- reason`; `report`, the results and the handoff keep the reason.
Run logs stay under `witness-runs/` in the PR root. A pass shows that the script exited 0 on this
head, not that the defect is closed or that the witness could have failed.

A witness is reviewer-written code run against the PR's code by the host, outside the executor's
sandbox, and the reviewer read untrusted repository text while writing it. It gets a minimal
environment (PATH, HOME, TMPDIR, locale, user and shell), never the runner's tokens or settings.
`REVIEW_WITNESS_WRAPPER` is a command prefix for every witness, such as the sandbox the executor runs
in; without one a witness has the runner's file access. Set it wherever that access matters.

The three automatic attempts are unchanged. After them, a calling task that already holds a grant uses
`--supplementary --granted-by WHO --budget N` to run more reviews of the same kind; the granter, budget and number are written into each such
attempt's `started` record, so older readers still see an over-limit history and hand off. A grant
while automatic attempts remain is refused. Every review prints `PR cumulative reviews k (automatic
a/3, supplementary m/N granted by WHO), cumulative time T` before anything else, `review-pr.sh`
included, measured from the ledger's reservation and finish times. The last automatic attempt and the last granted review write
`HANDOFF.md`: the latest and original review paths with the latest review's validators, tracked
invariants, any recurrence note, the witness ledger and the calling agent's next action: continue the
existing completion path when the latest review covers the requested head and nothing blocking
remains, otherwise end the task as failed with the cause. It asks no one to answer.
The grant is a recorded cooperative limit, not access control. A review run outside the runner
cannot be counted; when an implementer response cites finding IDs that no recorded review for the PR
contains, the next prompt and stderr say so.

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
base..head has preserved evidence for the calling agent to assess. An earlier intact attempt cannot hide a
later interrupted attempt at the same target. Neither exit authorizes merging. CI status, product
test counts, mutation measurements and contract versions written in a prompt are not attested by
these receipts. Replay does not manufacture those missing measurements from a reviewer's prose.

Host ownership is an execution-environment responsibility. A digest proves byte equality, not
provenance, and same-user access can rewrite the directory or disable a hook. Event checks are not
an OS sandbox or proof of exhaustive reading. Keep raw logs private: they may contain source and
other tool output. Newline-containing filenames remain unsupported by the line-based target seal.

New attempts use a v3 `started` reservation, then `prepared` with hashes of the frozen inputs,
then `finished` with execution and final-checkout observations. Invalid invocations fail before
reservation; failure or interruption afterward consumes the attempt. v1/v2/v3 records remain
readable without rewriting their original outcomes. An old failed receipt is not a cached success,
even if its former marker check has been retired. Final observations describe the end instant;
older receipts without them say `NOT_OBSERVED`, not pass or fail. Phase 2 binds the original and
previous review bytes, while a response-only follow-up still reviews the complete repair diff.

If a ledger has an unrecorded round directory, `status` and `report` expose its path and writes
stop with `ORPHANED_PREPARATION`: no review can be recorded for that PR ID, so the review ends as
failed, naming the path. Preserve the directory and ledger; do not delete, adopt, truncate or rename
the root to restart the budget. A v2 writer cannot safely resume a v3 root. Keep the v3 reader while
fixing it, or end the review as failed. A normally
interrupted v3 attempt can use an explicit retry only within the remaining budget.

## Host inputs and consumers

An optional top-level `REVIEW.md` in the exact candidate is the conventional repository-owned review
policy. The runner reads its Git blob rather than the working tree, accepts only a nonempty regular
UTF-8 file of at most 16 KiB, and freezes `REPOSITORY_REVIEW.md` plus
`REPOSITORY_REVIEW.json` (path, revision, digest, and size) as hashed round inputs. A malformed or
oversized declared policy fails input preparation; an absent file keeps existing consumers working.
The prompt carries the policy and any `REVIEW_REQUIREMENTS` value in separately named fields of one
host-owned JSON envelope. Candidate newlines and field-like labels therefore remain quoted data and
cannot impersonate later host fields or certify the policy. `REVIEW_REQUIREMENTS` supplies those
additional host-owned sources; `REVIEW_ROUTED`,
`REVIEW_CATALOG`, `REVIEW_SUITE_STATUS` and `REVIEW_TOOL_NOTES` fill the other prompt inputs.
`REVIEW_EXECUTOR` selects codex or claude; `REVIEW_CODEX_MODEL` optionally selects the model. Without
an explicit base, phase 1 needs `REVIEW_TARGET_BRANCH`; phase 2 inherits its base.
`REVIEW_RESPONSE` optionally names the implementer's separate response, `REVIEW_REDESIGN` a redesign,
`REVIEW_WITNESS_DISPUTED` a comma-separated list of witnesses the implementer disputes, and
`REVIEW_WITNESS_WRAPPER` a command prefix for running witnesses.

The runner sends values to `render-prompt.py` as an internal JSON object on stdin; the renderer's
`KEY=VALUE` arguments remain available for existing callers. It freezes the rendered prompt file
and passes that file as finite stdin with EOF to the configured CLI. This does not raise the CLI's
own input, token, time or cost limits. Unsupported size or transport must be reported as a failure
or `UNAVAILABLE`, without truncation, hidden summarization or an automatic repeat. Oversized
environment variables can still fail before the child starts; put large review text in files.

Git subprocesses target their explicit repository and discard inherited Git routing variables.
The source commit hook captures its source index separately, including an alternate index; staged
entries/tree are its invariant, not raw index cache bytes. Explicit Git file paths use literal
pathspecs (`--` alone does not disable globbing), and NUL-delimited path output stays separate from
diagnostic stderr. `SCOPE.json` v1 records exact base/head file status, old/new mode and object ID,
binary or null metadata and optional implementation/test hints. It is navigation, not coverage
proof. Empty phase 1 and response-only phase 2 are distinct; singleton grouping is sufficient.

The primary checkout is the exact review head. Write-required experiments belong in an authorized
separate exact-head copy, with the changed files and result reported; the runner grants no extra
permissions. The final host observation checks the primary tracked tree and copied inputs, not a
claim that every file was read or that a temporary mutation never happened. Ordinary source/test
text and repository-owned `SEAL.txt` are not proof of access to the host's private inputs. Actual
target, input hash and no-clobber checks still apply.

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
open findings, cached status, validator skips, failures, timeouts and cancellation, and the absence
of an automatic approval path. They do not measure
reviewer recall or safe merge completion. The [reassessment](../../dogfood/REASSESSMENT.md) explains
why the Markdown gates and their tests were retired.

`frontier-simplify: keep the hook while maintaining this runner; remove it when the runner is no longer
maintained here, restoring pre-commit.before-review if present.`
