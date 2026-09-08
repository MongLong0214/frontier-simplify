# Running the review protocol

[SKILL.md](SKILL.md) owns the prompts, statuses and verdicts. These scripts enforce the mechanical
handoff. They need Bash, Git and Python 3.9+; live execution additionally needs the configured
repository-capable executor. `selftest.sh` uses only local throwaway repositories and event fixtures.

## One PR, one sequence

Run these from a trusted installation outside the implementation checkout. `PR_ID` stays the same
for every attempt, including restarts. `BASE` is a merge-base, not the target branch tip.

```sh
scripts/review-round.sh 1 "$REPO" "$HEAD" "$PR_ID" "$BASE" codex
scripts/review-round.sh hunks "$REPO" "$REMEDIATION_HEAD" "$PR_ID"
REVIEW_RESPONSE=/host/response.md \
  scripts/review-round.sh 2 "$REPO" "$REMEDIATION_HEAD" "$PR_ID" "$BASE" claude
scripts/review-round.sh report "$REPO" HEAD "$PR_ID"
scripts/review-round.sh path "$REPO" HEAD "$PR_ID"
```

The positional `1` or `2` selects the protocol phase. The actual round number is allocated under a
per-PR lock and never supplied by the reviewer. This replaces the old per-round artifact slug.
With no base argument, phase 1 requires `REVIEW_TARGET_BRANCH`; phase 2 inherits its sealed base.
A local clone keeps the consumer's checkout and `.git` untouched. Tests run in that disposable clone.
No script pushes, comments on a PR, or merges it.

`REVIEW_ARTIFACTS` selects the host evidence directory, outside the consumer checkout (default:
`~/.sol-simplify-review`). Each PR has `ledger.jsonl` and numbered directories containing frozen
inputs, the final reviewer message, event stream, guard results and their digests. Raw executor logs
may contain private source or tool output; keep this directory private. Retain receipts for as long
as the review measurements are needed; remove them when that retention is no longer useful.

Exit 0 requires usable evidence **and** a `PASS`/`PASS WITH NITS` verdict. A BLOCK inventory is saved
as a valid handoff but exits 5. Rejected attempts also exit 5 and print a named reason. Interrupted
attempts remain in the ledger. `report` validates evidence without authorizing a merge.

`stub` exists for offline tests. It uses the same guards, records its executor identity and always
exits nonzero. A sequence containing a stub cannot become a live merge result.

## Remediation and extra rounds

Use the separate Markdown response in SKILL.md. Copy the generated hunk lines into its
`Remediation hunk accounting` section and replace the right side, for example:

```text
- H-<generated identity> "src/reader.py" @@ <generated range> @@ — G-03, O-01
- H-<generated identity> "src/new.py" whole-file (...) — UNRELATED: separate feature
```

The identities bind the two exact heads, file and zero-context hunk bytes. A mode/binary/empty-file
change gets a whole-file identity; renames account for both endpoints. Missing, duplicate, unknown
and stale identities fail before invoking the closure reviewer. An unrelated declaration explains
the hunk but requires a new phase-1 inventory. No blanket exemption is accepted.

List the original `file:symbol`/`file:line` sites in `applicable_siblings_checked` and the closure's
`sites_verified`; use backticks around sites whose paths contain spaces. The guards compare listed
sites. They cannot discover a sibling that the inventory never listed.

Round 3+ requires `REVIEW_ESCAPES=/host/escapes.md`. A phase-1 scope restart after a valid inventory
also requires this file. Each line names an **original** inventory ID:

```text
- G-03 — OPEN — prior closure left the alternate reader OPEN; reproduction still fails
```

Allowed categories are the protocol's `OPEN`, `REMEDIATION-REGRESSION`, `ROUND1-ESCAPE`, `SCOPE-CHANGE`
and `INTEGRITY`. OPEN must occur in the prior closure, ROUND1-ESCAPE in its escape section, INTEGRITY
must follow a rejected attempt; a changed head or recorded regression/scope change supports the
other categories. An incidental missed obligation is linked to the original class/obligation whose
sweep failed, not assigned a fictional new round-1 ID. Closure `Protocol escapes` entries likewise
name that ID alongside their category and evidence.

The report distinguishes `ROUND1-ESCAPE rate` (distinct original IDs implicated in incidental missed
blockers / original inventory item count) from `closure escape rate` (distinct IDs explaining extra
executed rounds / that same denominator). It prints reasons and all attempts, including guards that
prevented execution. This is an item-level diagnostic; it cannot measure defects nobody found.

## Host inputs and trust

`REVIEW_REQUIREMENTS`, `REVIEW_ROUTED`, `REVIEW_CATALOG`, `REVIEW_SUITE_STATUS` and `REVIEW_TOOL_NOTES`
fill the existing prompt placeholders. `REVIEW_EXPECTED_IDS` is a comma-separated list of host-known
obligation/project IDs. A supplied catalog requires it; all G-01 through G-10 are always required.
`REVIEW_EXECUTOR` selects an executor when the positional argument is absent. Optional
`REVIEW_CODEX_MODEL` configures that executor; there is no model default in the skill.

The old `REVIEW_INTEGRITY`, `REVIEW_INVENTORY_SHA256` and `REVIEW_ROUND1_HEAD` assertions are no longer
inputs. Phase 2 derives them from this PR's sealed artifacts and checks ancestry before model work.
Ordinary tests/suite/platform claims and semantic evidence still need independent reviewer judgment.
The unchanged prompts have a known tension: round-1 PASS wording both excludes and permits explicitly
carried UNVERIFIED items. The harness follows the prompt's two coverage axes and does not silently
resolve that product-verdict ambiguity. Phase-2 PASS cannot silently carry an unclosed item.

A digest proves byte equality, not authorship. The host directory, installed runner and installed
hook must be protected from the implementation/reviewer actor by the execution environment. Event
checks detect common seal access and record actual tool envelopes; they do not prove exhaustive
reading or provide an OS sandbox. Same-user filesystem access can rewrite an entire history, including
its digests, or disable a Git hook. Do not treat the hash chain as a signature or a remote merge gate.
Audit reruns the installed guards; a later guard version can reject older receipts. It does not
silently rewrite those receipts into approvals. Newline-containing filenames are rejected explicitly
because the protocol's line-based Markdown file accounting cannot represent them.

## Offline commit check and consumer PRs

```sh
scripts/selftest.sh
scripts/install-hook.sh "$SKILL_REPOSITORY"
scripts/review-pr.sh "$CONSUMER_REPO" "$PR_NUMBER" auto
```

The installer preserves an existing pre-commit hook. Its installed copy runs against a single staged
Git tree, then runs the staged selftest. Candidate test edits cannot replace the installed failure
witnesses; the hook does not read a stored pass flag. To adopt changed test expectations, deliberately
reinstall from a maintainer-selected version. Remove the hook when this repository no longer maintains
the review skill (restore `pre-commit.before-review` if present).

`review-pr.sh` uses `gh` to resolve the PR number and exact commits, fetches into a persistent host
clone and calls `review-round.sh`. `auto` runs phase 1 on first observation, then phase 2 on a changed
head; it reports an already-attempted head without spending another model call. Explicit `1`/`2`
can retry a head, with the same round budget. Supply `REVIEW_RESPONSE` and `REVIEW_ESCAPES` normally,
or place `pr-N-response.md` and `pr-N-escapes.md` in the printed consumer host directory.

A host scheduler or the consumer's existing PR workflow must invoke this entrypoint and use its exit
status. Scheduling and remote required-check settings are external to the skill. Keep consumer
configuration outside this directory. `REVIEW_CONSUMERS_CONFIG` names a host JSON file containing
`consumers` entries with `repository` and optional `markers`; the portability check scans every file
under the skill for those identities. The maintainer repository's `dogfood/` directory supplies its
own configuration and scheduler command. Installing a local hook alone does not create a remote
required PR check.

`sol-simplify-audit` measures repository-wide manufactured process and proposes deletions. This
protocol reviews one PR for product defects. No measurement or deletion logic is shared with audit.
