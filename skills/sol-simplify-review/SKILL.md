---
name: sol-simplify-review
description: >-
  The default protocol for any merge-gate or pre-merge review: inventory the reviewed head once, exhaustively, then verify only closure and remediation regressions. Use whenever a change is about to be merged and someone is reviewing it — not only when asked for it by name, and not only when rounds have already gone badly. Writing a fresh ad-hoc review prompt for a merge is the failure this replaces, and it happens most under time pressure or when a usual reviewing model is unavailable: swap the model inside this protocol rather than abandoning it. Skip only for an ordinary small one-pass read where nothing merges.
metadata:
  author: MongLong0214 <MongLong0214@users.noreply.github.com>

---

# sol-simplify review

Review the product once. Freeze what must be true. Verify the repair once.

A sequence of valid findings is still a failed review process when each pass selects another
surface from the same finite change. Round 1 must enumerate that surface. Round 2 must close it,
not rediscover it.

`sol-simplify: the inventory prevents repeated class-local fixes; remove it when the change is
merged or abandoned.`

## Reach for this by default

If a change is about to merge and someone is reviewing it, this is the protocol. That includes the
cases where it is least convenient: a deadline, an outage of the model you normally review with, a
PR you have already reviewed several times, a change you believe you understand.

Those are the moments an ad-hoc review prompt gets written instead, and an ad-hoc prompt samples
findings rather than bounding them — which is the whole reason this exists. A model being
unavailable changes who executes the round; it does not change the round.

Switching to it late is cheap. A reviewer that has already read the code can produce the round-1
inventory as a change of output shape, not a restart.

## Why this is not a registry

The inventory is one reviewer-owned artifact for one PR head. It is not committed to the product
repository or updated after every merge. Its obligations expire with the PR; the host may retain
sealed round receipts for retrospective measurement.

Every item names product behavior, a security boundary, or an explicit requirement. Tests and
reproductions decide whether it closes. Mechanical guards check the declared accounting against
Git and the handoff; they cannot certify that the reviewer found every obligation or sibling.
There is no permanent product status database, approval graph, or count to synchronize.

The seals protect the handoff between processes. Guard acceptance means usable review evidence;
it does not by itself mean the product passes.

## Host contract

Round 1 needs:

- An exact base commit and head commit. **Base means the merge-base of the target branch and the
  head**, not the target branch tip: the seal script enforces that base is an ancestor of the head,
  and on a PR that has diverged -- which is most PRs big enough to need this protocol -- the tip is
  not. If the head has diverged from the target branch, record that in the Binding as a SCOPE-CHANGE
  risk, because a later merge of the target changes what the inventory bounds.
- Their diff and changed-file list.
- A checkout of the head, with permission to read changed files and directly affected code.
- `DIFF.patch` and `CHANGED.txt` for base..head. The host produces these; if it did not, produce them
  yourself before reading anything else and say so in the Binding.
- Permission to run focused tests or an explicit record of which tests and platforms are unavailable.
- Any issue, specification, acceptance conditions, forbidden implementations, security model, or
  definition of done that the review is expected to enforce.
- The status of the repository's ordinary full test run, when that suite is too large for the
  reviewer to run.
- Exact descriptions of known routed defects, if any. A broad category is not an exclusion.

A diff is the minimum contract. With only a diff, the reviewer can assess language/runtime
correctness, security boundaries visible in the code, regression risk, internal consistency, and
claims made by changed tests or documentation. It cannot certify unstated product intent or
completeness. The inventory must say `basis: DIFF_ONLY`.

The two-round claim applies only when the round-1 checkout and required evidence fit the reviewing
model's context and tool budget. If relevant code, tests, platforms, or requirements cannot be
examined, round 1 is `INCOMPLETE`, not approximately complete.

## Portable defect classes

Use these as questions, not assumptions:

1. **Self-asserted authority.** Does a subject-supplied label, flag, status, expected value, or
   identity decide the claim being made about that subject?
2. **Absence as success.** Can missing, null, empty, unknown, skipped, deferred, malformed, or
   exceptional input become success or a usable default?
3. **Equivalent paths diverge.** Are parallel implementations, platforms, renderers, lifecycle
   paths, nested/top-level forms, or read/write sides governed differently?
4. **Claim stronger than test.** Would the named guarantee remain green if its subject were broken?
   Include skips, early returns, fixtures, mocks, and mutation witnesses when the project uses them.
5. **Shape mistaken for provenance.** Is syntax, a prefix, a digest-shaped string, or an identifier
   treated as proof of who produced or verified it?
6. **Private input reaches a public sink.** Can credentials, private paths, raw errors, transcripts,
   environment values, or untrusted strings reach stored, rendered, logged, or committed output?
7. **Second authority.** Is a formula, mapping, expectation, support table, policy, or grouping
   restated outside its declared authority?
8. **Stored artifact authorizes itself.** Can persisted output declare its own validity, coverage,
   claim stage, row set, boundary result, or issuance state without recomputation from evidence?
9. **Snapshot and its certificate are not atomic.** Is evidence captured at one instant and
   digested at another, so a concurrent writer can leave a state that never existed while the
   comparison reads unchanged? Applies wherever a copy, freeze, baseline, or cache is certified by a
   digest taken separately from it.
10. **Record identity changed silently.** Did the bytes or fields covered by a digest, schema,
   cache key, cohort key, or stored record change without a version or migration?

Classes 1, 2, 3, 4, 6, 7, and 8 are portable default questions, although they may be `N/A`.
Class 5 applies only where provenance or trusted identity matters. Class 9 applies wherever evidence
is certified by a separately-taken digest. Class 10 applies only where versioned or persisted
identity exists.

Project-specific measurement semantics, contract filenames, renderer lists, isolation backends,
and mutation systems are not portable defaults.

## Project catalog

A project does not need a catalog before its first review. Seed from:

1. Explicit requirements and trust boundaries for the current change.
2. The portable classes above.
3. Any existing incident or review history the maintainer deliberately supplies.

An existing project catalog is an input to round 1. Round 1 may output a `catalog candidate`, but
must not edit or create a permanent catalog.

A project-specific class earns a standing entry when it is backed by a continuing product contract
or recurs in two independent changes or components. One isolated mistake earns a regression test,
not a standing rule. Retire the entry when the governed interface or contract is removed, or a
structural change makes the failure class impossible. Do not retain it merely because it once
caught something, and do not use a quiet-period tally as a retirement rule.

## Round 1 prompt

```text
You are the final merge-gate reviewer. This is ROUND 1: exhaustive inventory, not an ordinary
finding sampler.

Repository: {{REPOSITORY}}
Base commit: {{BASE_SHA}}
Reviewed head: {{ROUND1_HEAD_SHA}}
Requirement sources: {{REQUIREMENT_SOURCES_OR_NONE}}
Known and already routed exact defects: {{KNOWN_ROUTED_OR_NONE}}
Project-specific review classes: {{PROJECT_CLASS_CATALOG_OR_NONE}}
Ordinary full-suite status: {{FULL_SUITE_STATUS_OR_UNKNOWN}}
Tool or platform notes: {{TOOL_NOTES_OR_NONE}}

DIFF.patch is the complete Base..Reviewed-head diff. CHANGED.txt lists its files. The checkout must
be exactly Reviewed head.

Do not emit progress, provisional findings, or placeholders. Read and investigate first; emit the
inventory once at the end.

Purpose

Produce a bounded, immutable inventory of everything this head must satisfy. A competent
implementer must be able to close every failing item in one remediation pass without guessing
which sibling site you did not inspect.

Scope

1. Verify the checkout commit. Read DIFF.patch, CHANGED.txt, every changed file, and the directly
   affected behavior cone: callers or consumers whose behavior changes, canonical authorities,
   validators, persistence readers/writers, public sinks, equivalent implementations, and tests.
2. Do not audit unrelated repository code. If the behavior cone cannot fit the available review
   budget, mark the review INCOMPLETE.
3. Extract one obligation for every explicit acceptance condition, forbidden implementation,
   security boundary, compatibility promise, and changed public claim. If there is no written
   requirement, label the basis DIFF_ONLY and do not invent product intent.
4. Instantiate every portable class below and every supplied project class as an inventory item.
   N/A is allowed only with a concrete reason.
5. Before probing local examples, test whether any central claim is architecturally impossible
   under the chosen mechanism. One structural counterexample should become one inventory item,
   not a succession of symptoms.
6. For every failure, search the whole review scope for the class. Enumerate:
   - every applicable site in the changed diff;
   - directly affected unchanged consumers or authorities;
   - parallel platform, renderer, lifecycle, nested/top-level, success/error, and read/write sites;
   - the tests that claim to guard those sites.
   Do not stop after the first reproduction.
7. Run focused reproductions. Inspect test bodies, not their names. A skip, early return, fixture,
   mock, or mutation witness is evidence only for the path it actually distinguishes.
8. Treat unavailable tools, unsupported platforms, ambiguous requirements, and incomplete site
   sweeps as UNVERIFIED. They make the review INCOMPLETE.
9. Known-routed exclusions suppress only their exact stated failure signature. Report a new variant
   when its authority, source, sink, or consequence is materially different.

Portable classes

G1 self-asserted authority.
G2 absence as success.
G3 equivalent paths diverge.
G4 claim stronger than test.
G5 shape mistaken for provenance.
G6 private input reaches a public sink.
G7 second authority.
G8 stored artifact authorizes itself.
G9 snapshot and its certificate are not atomic.
G10 record identity changed silently.

Status meanings

PASS       Direct inspection or a probe supports the item at every applicable site in scope.
FAIL       At least one failure is reproduced and the class-wide site sweep is complete.
N/A        The item cannot occur in this change, with a stated reason.
UNVERIFIED The reviewer cannot reach a conclusion or cannot complete the site sweep.
NOTED      A site was reached where the class holds in isolation but is judged currently
           unreachable, latent, or dependent on a precondition that cannot occur today. The
           argument for unreachability goes in `dismissed_sites`. This is not a pass: a latent
           fail-open that contradicts its own module's rule is a one-line fix and a future
           blocker, and burying it inside a PASS is how it survives to the next release.

FAIL is not valid when only the first failing site was examined. Use UNVERIFIED and list the
confirmed sites if the sweep is incomplete.

Severity meanings

BLOCKER Wrong behavior, security exposure, data loss, fail-open behavior, compatibility break,
        unmet requirement, or a test/guard whose false claim is relied on for acceptance.
NIT     Wording, naming, style, or non-behavioral drift that does not make the product unsafe or
        violate an acceptance condition.

Output exactly this Markdown structure:

# Round 1 review inventory

## Binding
- repository:
- base_sha:
- head_sha:
- basis: SPECIFIED | DIFF_ONLY
- scope: COMPLETE | INCOMPLETE
- full_suite:
- required_platforms:
- unavailable_evidence:

## File accounting
One line per changed file:
- <path> — READ | READ_DIFF_ONLY | NOT_READ — <role in the change, or reason not read>

READ means the file was read in full. READ_DIFF_ONLY means only its hunks were read, which is
defensible for a one-hunk test change and dishonest for a file whose unchanged half decides the
behaviour under review.

Then list directly affected unchanged files that were inspected.

## Inventory

Use stable IDs: O-01... for sourced obligations, G-01...G-10 for portable classes, and P-01...
for project classes. Every explicit obligation and every supplied/default class gets an item.

### <ID> — <short assertion>
- kind: obligation | portable-class | project-class
- source: <requirement location, changed claim, class name, or inferred DIFF_ONLY invariant>
- impact: BLOCKER | NIT
- must_hold: <one falsifiable behavior>
- applies_to: <bounded behavior/surface family>
- status: PASS | FAIL | N/A | UNVERIFIED
- applicable_sites: <all sites in scope, grouped when equivalent; include file:symbol or file:line>
- failing_sites: <every failing site, or none>
- evidence: <inspection, command, result, and expected/actual behavior>
- reproduction: <minimal reproduction, or not applicable>
- class_sweep: <symbols, searches, counterparts, and platform/lifecycle variants examined>
- dismissed_sites: <every site where the class holds in isolation but was judged unreachable, each
  with the precondition that makes it unreachable, or none>
- closure: <observable condition that would close the item, including the needed regression test>
- catalog_candidate: <none, or a concise candidate justified by recurrence/standing contract>

Do not replace applicable_sites with “see diff,” “elsewhere,” or one representative example.
For a failing class, distinguish applicable sites that already pass from every site that fails.

## Routed exclusions encountered
- <exact routed defect and where encountered>, or none

## Verdict
PASS | BLOCK | INCOMPLETE

Coverage and verdict are two axes. Report both:

- enumeration: COMPLETE | INCOMPLETE. This is about whether the *space was bounded*: every changed
  file read, every obligation extracted, every class instantiated, every site sweep finished.
  INCOMPLETE if any changed file is NOT_READ, the head does not match, or a sweep could not be
  finished.
- verification: COMPLETE | PARTIAL. PARTIAL when one or more items are UNVERIFIED because the
  environment could not exercise them — an unavailable platform, a blocked network, an absent
  integration. Those items stay UNVERIFIED and are carried, by ID, into round 2.

Keep these apart. An inventory can bound the space perfectly and still contain an item this machine
cannot execute; a linux-only path reviewed from a mac, or one blocked call, must not void the whole
inventory. Only a failure to *enumerate* does that.
- verdict: PASS | BLOCK | INCOMPLETE.
  BLOCK whenever at least one BLOCKER FAIL was reproduced -- **even when coverage is INCOMPLETE**.
  A reproduced blocker is a fact; an unfinished sweep does not unmake it, and burying it under a
  verdict that reads as a process note is how a reader ships it.
  PASS requires every item PASS, N/A or NOTED, no blocker, and COMPLETE enumeration. A PASS
  carrying UNVERIFIED items must name them and say the merge rests on evidence this review could
  not obtain.
  INCOMPLETE as a *verdict* is only for the case where the enumeration itself failed and nothing
  blocking was reproduced -- there the honest answer is that the review did not establish enough
  to judge.

Two-round convergence may be promised from an inventory whose **enumeration** is COMPLETE, even when
verification is PARTIAL. It may never be promised from an incomplete enumeration.
```

## Between rounds

The implementer does not edit the inventory. They produce a separate response:

```text
# Remediation response
- inventory_sha256:
- round1_head_sha:
- remediation_head_sha:

## <each FAIL item ID>
- disposition: FIXED | DISPUTED
- changed_sites:
- applicable_siblings_checked:
- implementation:
- tests_added_or_changed:
- commands_and_results:
- remaining_limitations:

## Touched PASS/N/A items
- <item ID and why the remediation touched it>, or none

## Remediation hunk accounting
- <file and hunk/symbol> — <inventory item ID or explicit unrelated-change explanation>

## New interfaces or behavior
- <anything introduced by the remediation that was not present at round 1>, or none
```

A dispute must answer the reproduction with evidence. “The test passes” is insufficient when the
inventory showed that the test did not distinguish the behavior.

Every remediation hunk must be explained. Unrelated feature work should be removed or causes a new
round-1 inventory.

## Round 2 prompt

```text
You are the final merge-gate reviewer. This is ROUND 2: closure and remediation regression only.

Repository: {{REPOSITORY}}
Base commit: {{BASE_SHA}}
Round-1 head: {{ROUND1_HEAD_SHA}}
Remediation head: {{ROUND2_HEAD_SHA}}
Trusted inventory SHA-256: {{TRUSTED_INVENTORY_SHA256}}
Inventory integrity result: {{INVENTORY_INTEGRITY_RESULT}}
Ordinary full-suite status: {{FULL_SUITE_STATUS_OR_UNKNOWN}}
Tool or platform notes: {{TOOL_NOTES_OR_NONE}}

ROUND1_INVENTORY.md is the exact reviewer-authored round-1 artifact.
IMPLEMENTER_RESPONSE.md is the implementer's separate response.
REMEDIATION.patch is Round-1-head..Remediation-head.
REMEDIATION_CHANGED.txt lists that patch's files.

The expected inventory digest and round-1 head come from a reviewer-owned channel, not from the
implementation branch. The host must verify the digest and ancestry before invoking you.

If inventory integrity is not VERIFIED, the checkout is not Remediation head, or Round-1 head is not
an ancestor of Remediation head, stop with PROTOCOL_ERROR. If the round-1 **enumeration** is
INCOMPLETE, stop with RESTART_ROUND_1 — a scope that was never bounded cannot be closed.

A round-1 **verification** of PARTIAL does not stop you. Verify the items that were verifiable,
carry each UNVERIFIED item forward by ID with the reason it could not be exercised, and report it in
the closure section as UNVERIFIABLE rather than treating the whole inventory as void. Say plainly in
the verdict that those items rest on evidence neither round obtained.

Do not perform another full review of the original PR. Do not deliberately seek new categories in
unchanged round-1 code.

Work

1. Account for every round-1 FAIL item and every implementer disposition.
2. At every listed failing site, rerun the reproduction or an equally direct check.
3. Check the listed applicable sibling sites so that a repair of one example does not leave the
   class open elsewhere.
4. Inspect changed test bodies and run the relevant tests. Do not accept names, fixture labels,
   self-declared statuses, or the implementer's response as proof.
5. Account for every remediation hunk. Recheck a round-1 PASS or N/A item only when the remediation
   touches its implementation or a dependency that can change its result.
6. Review REMEDIATION.patch and the behavior directly reached by it for regressions. This is the
   only ordinary new attack surface in round 2.

What may open in round 2

- OPEN: a round-1 item was not closed, was closed at only some listed sites, or the implementer's
  response is false.
- REMEDIATION-REGRESSION: any blocking correctness, security, privacy, data-loss, compatibility,
  fail-open, or contract defect causally introduced by Round-1-head..Remediation-head. Security is
  not the only allowed category.
- SCOPE-CHANGE: unrelated functionality, a rebase/base change, or a replacement implementation
  makes the round-1 inventory no longer bound the change. This requires RESTART_ROUND_1.
- ROUND1-ESCAPE: a blocking defect present at the round-1 head but absent from the inventory is
  encountered incidentally. Confirm it against Round-1 head, block the merge, and mark the
  two-round protocol as escaped. Do not disguise it as normal closure and do not ignore it.
- INTEGRITY: the inventory, commit binding, or trusted digest does not match.

What may not open in round 2

- A new nit, preferred design, hypothetical hardening idea, or expanded attack against unchanged
  round-1 code.
- Re-litigation of a PASS or N/A item not affected by the remediation.
- A broader version of an exact known-routed defect without a materially different source,
  authority, sink, or consequence.
- A new category merely because round 2 has remaining review budget.

If a real blocker in unchanged round-1 code is noticed, ROUND1-ESCAPE takes precedence over this
restriction. Safety is not traded for the appearance of convergence.

Output exactly:

# Round 2 closure review

## Binding
- inventory_sha256:
- integrity: VERIFIED | FAILED
- round1_head_sha:
- remediation_head_sha:
- ancestry: VERIFIED | FAILED
- round1_scope: COMPLETE | INCOMPLETE

## Response and hunk accounting
- response_items_missing:
- remediation_hunks_unexplained:
- touched_PASS_or_NA_items:

## Closure

One entry for every round-1 FAIL:

### <ID> — CLOSED | OPEN | UNVERIFIABLE
- sites_verified:
- reproduction_result:
- tests:
- response_assessment:
- remaining_failure:

## Remediation regressions
- <R-01, causal remediation hunk, reproduction, impact, and closure>, or none

## Protocol escapes
- <ROUND1-ESCAPE, SCOPE-CHANGE, or INTEGRITY with evidence>, or none

## Verdict
PASS | PASS WITH NITS | BLOCK | RESTART_ROUND_1 | PROTOCOL_ERROR

PASS requires every round-1 BLOCKER/FAIL to be CLOSED, no remediation regression, no protocol
escape, every remediation hunk accounted for, and required tests available and passing.
PASS WITH NITS may retain only round-1 nits.
BLOCK means closure failed or the remediation introduced a blocker; this sequence did not converge
in two rounds.
RESTART_ROUND_1 means the frozen scope is no longer valid or round 1 escaped.
PROTOCOL_ERROR means integrity, ancestry, or required input could not be verified.
```

## Model and tool boundary

The protocol assumes a repository-capable reviewing model that can follow cross-file authority,
reason about adversarial states, retain a 15–40-file inventory, and use tools. Record the model and
effort in benchmarks, but do not hard-code either into the protocol.

A weaker model usually loses site recall first: it finds a valid example but misses equivalent
renderers, platforms, error paths, or stored readers. Prompt wording cannot repair that reliably.

There is a second failure, and it looks nothing like the first. An artifact can carry its items and
lose its *fields* -- the sweep, the evidence -- and then lose its tail, ending before the Verdict
section is written. Measured twice, on two projects: one round emitted 68,338 output tokens and
stopped before `## Verdict`; another produced 82 items with `class_sweep` absent from every one of
them and no Verdict section at all. Both were refused by the guards, correctly: an artifact missing
the field that records the sweep has not recorded a sweep.

"The model was too small" and "the change is too large for one bounded review" produce that same
symptom and take different fixes, so distinguish them before choosing. Re-run with a stronger
executor first -- the protocol is built to swap the model inside it. If a stronger executor still
cannot close the artifact, the change exceeds a single bounded review and the answer is to split
it, not to buy more rounds.

Prompt-shaped work:

- Stable item statuses and IDs.
- Class-wide enumeration.
- Frozen round-2 scope.
- Implementer response requirements.
- Regression versus escape classification.

Tool-shaped work:

- Commit and ancestry verification.
- Reading full files and affected dependencies.
- Repository search.
- Running tests and direct reproductions.
- Comparing Round-1-head..Remediation-head.
- Sealing and verifying the inventory bytes.

The bundled [scripts](README.md) implement this tool-shaped work:

- `scripts/target-seal.sh` binds the base, head and changed blobs before review.
- `scripts/review-seal.sh` seals/verifies a standalone inventory handoff;
  `scripts/review-round.sh` binds the same exact bytes into host-owned round receipts.
- `scripts/review-round.sh` renders these fenced prompts through `lib/render-prompt.py`,
  gives the reviewer a disposable checkout and Git-generated inputs, and runs the guards.
  File reading, searches, reproductions and test execution remain reviewer tool work.
- `scripts/review-round.sh hunks` generates hunk identities from the sealed round-1 head
  to the remediation head. The response maps every identity to existing item IDs or an
  `UNRELATED:` explanation. Binary, mode-only, deletion, empty-file and rename endpoints
  are included. Unrelated functionality requires a scope restart, not a waived hunk.
- `scripts/review-round.sh report` recomputes guard results and counts from sealed artifacts.
  A stable PR ID owns an automatically numbered sequence; a new phase-1 inventory does
  not reset it. Round 3+ requires original inventory IDs, an escape category and evidence
  tied to the prior review or changed head. Protocol escape evidence in a closure also
  names the original class/obligation ID whose enumeration failed.
- `scripts/review-pr.sh` resolves a configured consumer PR into this sequence. The host
  supplies consumer paths, project classes, executors and any model selection as configuration.
- `scripts/install-hook.sh` installs an offline commit check on staged skill changes;
  an installed test suite and the candidate suite both exercise the staged scripts.

Guards require all ten portable IDs, supplied host obligation/project IDs, consistent coverage,
FAIL dispositions, listed sibling checks and closure evidence. A host cannot derive unstated
requirements from a count; enumerating obligations and proving a sweep exhaustive remain review work.

The round report shows the distinct original item IDs tagged `ROUND1-ESCAPE` divided by original
inventory items, as well as IDs responsible for extra closure rounds and their categories. These
are observed item escape rates, not an estimate of all undiscovered defects. A rejected or interrupted
attempt remains visible. The receipts are host-owned audit evidence, not reviewer-supplied pass files.

Without file access and executable tests, this is a structured opinion, not a P0 merge gate.

## Limits

Complete enumeration can support the two-round plan described in the round-1 prompt, even with
PARTIAL verification. Do not claim *verified* two-round convergence when:

- Round 1 contains UNVERIFIED items.
- The change or its behavior cone exceeds the review context.
- A required platform or integration cannot be exercised.
- The remediation is rebased, replaces the design, or adds unrelated functionality.
- The implementer does not answer every failing item and changed hunk.
- The requirement itself is incompatible with the chosen architecture.

`enumeration: COMPLETE` is the reviewer's claim about its own coverage, and it is not a
guarantee that a second reviewer on the same head would produce the same inventory. Measured on
one PR: two round-1 runs at one sealed head, neither carrying a catalog, produced 19 items and
14 items, and **each reproduced a real blocker the other did not raise** -- one an unchecked
acquisition in two of three callers, the other a census whose file list omitted the authority
under review. Both were confirmed in the code.

That does not void the protocol; a bounded surface reviewed once still beats an unbounded
surface reviewed five times, which is what this replaces. It bounds what COMPLETE buys: a
finished sweep of the classes the reviewer instantiated, not proof that no other reviewer would
instantiate another. Where a change is small enough to re-seal cheaply, a second independent
round-1 is worth its cost; where it is not, say plainly that the promise rests on one
enumeration. n=2, reported by a consumer, and worth more observations.

In those cases, say which condition failed in the existing PR round receipts. Do not create a second ledger or exception process.
