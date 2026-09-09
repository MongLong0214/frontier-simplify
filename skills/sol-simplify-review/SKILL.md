---
name: sol-simplify-review
description: >-
  Review a change for concrete defects, then check repairs and their regressions against the
  preserved review. Use for substantial PR reviews or repeated review rounds. Stops automatic
  review after at most three attempts per PR and hands off; does not guarantee safe merge convergence.
metadata:
  author: MongLong0214 <MongLong0214@users.noreply.github.com>
---

# sol-simplify review

Find defects with evidence. Preserve the findings. Check the repair and its affected siblings.

The previous automatic gate failed its own first step: one consumer PR recorded 13 attempts,
ten executed reviews, and no accepted inventory. It found useful defects but repeatedly rejected
usable prose. A finished enumeration is a reviewer's coverage claim, not proof of completeness.
Two phases are a useful review sequence, not a convergence guarantee. The host allows at most
three cumulative attempts per stable PR, including failed and interrupted attempts. On the third
attempt it hands off; later invocations launch no reviewer. New heads, new responses and phase-1
restarts do not reset the count. Legacy attempts count too; never rename a PR to evade the limit.
This guarantees bounded automatic attempts, not a deadline or a safe merge within three rounds.
Repairs can create regressions and the first review can miss blockers, so neither a frozen first
inventory nor a decreasing finding count establishes that stronger promise.

The host checks execution completion, exact commits, ancestry and preserved bytes. The reviewer
judges coverage, requirements, severity and closure from the code and evidence. No Markdown
parser, field count, or stored PASS authorizes merging. The runner returns a distinct nonzero
status even when the review recommends PASS. Use the existing maintainer review and product
checks to decide the merge; do not keep rerunning a model to satisfy a format checker.

## Host contract

Supply an exact head, its merge-base with the target, the diff and changed-file list, a disposable
checkout of that head, requirements if known, and the status of relevant tests and unavailable
platforms. Without requirements, assess the diff and label the basis DIFF_ONLY; do not invent
product intent. A changed target branch may require integration testing on the merged result.

Read and investigate before writing the final review. Use ordinary prose with stable finding IDs,
file/line references and concrete expected/actual behavior. There is no required inventory of
PASS/N/A entries for every class and no output schema. Group findings that share a cause; list
all failing sites you actually found and the siblings you checked. Never call that exhaustive
merely because the report is finished. A known blocker remains a blocker when its sweep is unfinished.

If the scope cannot be covered in this run, state exactly what remains unread or untested. Keep
confirmed findings available for repair. Split the change or delegate bounded surfaces when the
available review budget cannot cover it; a larger model may help, but missing report fields alone
do not establish which remedy is needed.

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
   For a filtered test command, measure which named witnesses actually ran. Exit 0, a positive
   pass count (which may count only a file wrapper), or one live alternative can hide another
   alternative selecting no tests. Replay the broken behavior against its claimed witness.
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

## Project history

Requirements and maintainer-selected project classes are inputs. Automatically harvested
`catalog_candidate` lines are review leads, with their source rounds attached. Repetition on the
same PR, or a reviewer's word "recurs", does not prove independent recurrence and creates no
mandatory item. Check a lead against the current code before using it. Do not copy yesterday's
symptom as today's finding. A continuing contract or confirmed recurrence across independent
changes/components can justify a standing question selected by the maintainer. Preserve the source
review and head, the new site's head and reproduction, and the repair with an unchanged regression
test failing before and passing after. Explain why the site is a different occurrence: a rerun,
rename, second finding ID or unfixed instance is not independent recurrence. Several questions may
lead to one defect; count that defect once. Human assessment establishes the shared cause and
scope; the host checks bytes and executions, not the truth of that assessment. A supplied account
without the source reproduction remains attributed evidence, not an independently verified count.

Prefer a repair that removes the cause across sites. Consider checks, validators and tests among
the affected sites, and verify that a test can fail for the behavior it claims to guard.

## Round 1 prompt

```text
Review this change for concrete defects. Investigate first, then write one final review in prose.

Automatic attempt: {{ATTEMPT_NUMBER}} of {{MAX_ROUNDS}} for this PR. At the limit, this is the
final automatic review: give the remaining findings, coverage gaps and next actions for a human.
The limit never closes or downgrades a blocker and never establishes merge readiness.

Repository: {{REPOSITORY}}
Base commit: {{BASE_SHA}}
Reviewed head: {{ROUND1_HEAD_SHA}}
Requirement sources: {{REQUIREMENT_SOURCES_OR_NONE}}
Known and already routed exact defects: {{KNOWN_ROUTED_OR_NONE}}
Project history and review leads: {{PROJECT_CLASS_CATALOG_OR_NONE}}
Ordinary full-suite status: {{FULL_SUITE_STATUS_OR_UNKNOWN}}
Tool or platform notes: {{TOOL_NOTES_OR_NONE}}

Your cwd is a disposable checkout of Reviewed head. DIFF.patch is Base..Reviewed-head;
CHANGED.txt is Git's changed-file list. Verify the checkout and inspect that diff, the changed
files, and directly affected callers, authorities, readers/writers, equivalents and test bodies.
Do not audit unrelated code. Use DIFF_ONLY when no requirement source was supplied.

What can make this change produce wrong behavior or break an explicit requirement? Examine
self-asserted authority, absence becoming success, divergent equivalent paths, tests that cannot
fail for their stated claim, shape mistaken for provenance, private inputs reaching public sinks,
duplicate authorities, stored decisions authorizing themselves, non-atomic evidence/certificates,
and persisted identities reused after meaning changes. These are questions, not findings or a
required set of PASS/N/A entries. Investigate supplied project leads on the same basis.
For filtered test commands, measure each intended witness, including individual selector
alternatives: exit 0 and a positive pass count can both hide an untested named behavior, including
a runner counting an empty file wrapper as a pass. Demonstrate the regression test failing on the
broken behavior before crediting its fix.

For each confirmed defect, give a stable ID, severity (BLOCKER or NIT), the violated requirement
or behavior, exact sites, expected/actual evidence or reproduction, and a concrete closure.
Search for affected siblings and explain which ones you checked and what remains uncertain.
A structural defect is one finding with its sites, not several findings counted as independent.
A reproduced blocker stays BLOCKER even if its sibling search could not be finished.
Suppress only the exact already-routed defect, not a materially different variant.

Explain what you read, what you could not read or test, and why any unchecked surface matters.
When recommending PASS, give the checks and reasoning supporting it; an empty findings list or
successful tool execution is insufficient. BLOCK means a confirmed blocker remains. INCOMPLETE
means the available evidence cannot support a pass; if a blocker also exists, say BLOCK and name
the coverage limitation. Unavailable required evidence prevents a PASS recommendation.

Use the format that communicates the evidence clearly; no schema or field-by-field envelope.
Optional `- catalog_candidate: <class and observed sites>` lines can preserve useful future leads.
The host preserves your answer; it does not parse your prose into merge permission. Do not
promise that a finished report or a second round will establish completeness or convergence.
```

## Between rounds

The implementer fixes confirmed failures across the identified sites and runs the relevant tests.
They can provide a separate prose response with finding IDs, changes, disputes, commands/results
and limitations. A dispute answers the reproduction with evidence. Keep the original review
unchanged; a response does not replace what the reviewer said.

The host carries the original review, the previous follow-up when present, and Git's complete
remediation diff into the next review. Hunk identities are available for navigation; no prose-to-ID
mapping is a prerequisite for running the reviewer. Unrelated changes need a fresh scope review.
Record that in the review itself. A fresh scope review consumes the same PR's remaining budget;
at the limit, hand off that need instead of restarting. No escape form can buy another attempt.

## Round 2 prompt

```text
Review the repair against the preserved findings and check the repair for regressions.

Automatic attempt: {{ATTEMPT_NUMBER}} of {{MAX_ROUNDS}} for this PR. At the limit, this is the
final automatic review: give the remaining findings, coverage gaps and next actions for a human.
The limit never closes or downgrades a blocker and never establishes merge readiness.

Repository: {{REPOSITORY}}
Base commit: {{BASE_SHA}}
Round-1 head: {{ROUND1_HEAD_SHA}}
Remediation head: {{ROUND2_HEAD_SHA}}
Trusted original review SHA-256: {{TRUSTED_INVENTORY_SHA256}}
Original review integrity: {{INVENTORY_INTEGRITY_RESULT}}
Requirement sources: {{REQUIREMENT_SOURCES_OR_NONE}}
Known and already routed exact defects: {{KNOWN_ROUTED_OR_NONE}}
Project history and replayed review leads: {{PROJECT_CLASS_CATALOG_OR_NONE}}
Ordinary full-suite status: {{FULL_SUITE_STATUS_OR_UNKNOWN}}
Tool or platform notes: {{TOOL_NOTES_OR_NONE}}

ROUND1_INVENTORY.md contains the exact original review, including any coverage limitations.
PREVIOUS_REVIEW.md contains the latest follow-up, or the original review on the first follow-up.
IMPLEMENTER_RESPONSE.md contains the separate response, or a note that none was supplied.
REMEDIATION.patch and REMEDIATION_CHANGED.txt cover Round-1-head..Remediation-head.
The host checked original bytes and ancestry. Verify your checkout is Remediation head.
If integrity or the checkout is wrong, stop and report PROTOCOL_ERROR.

First assess whether the original review gives enough evidence to bound this follow-up. If it
only asserts PASS, contains placeholders, or leaves coverage unexplained, say that a fresh scope
review is needed; do not treat the preserved bytes as a completed review.

For every original finding and any later open finding, independently determine CLOSED, OPEN,
DISPUTED or UNVERIFIABLE. Preserve the IDs. Rerun the reproduction or an equally direct check,
inspect the changed test bodies, and check affected siblings. Give evidence for closure; neither
the implementer's response nor a passing test name establishes it. With no implementer response,
derive the repair from the diff and say where its intent remains unclear.
When a repair renames tests, remeasure the commands that select them. A combined selector can
remain nonempty while silently dropping the only witness for one behavior.

Read the entire remediation diff and behavior directly affected by it. Report causal remediation
regressions, including correctness, data loss, availability, security and contract failures.
Recheck a previously passing surface if the repair can change it. Explain unrelated changes and
whether a new scope review is needed. Address explicitly stated coverage gaps; if they still
cannot be reviewed or tested, carry the limitation and do not recommend PASS.

Do not start an unrestricted search for more categories in unchanged original code. If you
incidentally encounter a real original blocker, report it as ROUND1-ESCAPE with evidence at the
original head. Keep it blocking; do not hide it to make the sequence appear to converge.

Write a concise prose review. Recommend PASS only when the blocking findings are closed or
disproved with evidence, the repair introduces no known blocker, and required review/tests are
complete and passing. PASS WITH NITS may retain only nonblocking findings. Otherwise say BLOCK
or INCOMPLETE and name the remaining work. A recommendation is for the maintainer to assess;
the host never converts it into automatic merge authorization. The third attempt ends automatic
review even when BLOCK or INCOMPLETE remains. Do not suggest a fourth automatic review to obtain
PASS. Preserve new blockers as blocking in the handoff; do not move them out merely to converge.
```

## Runner and limits

The [runner guide](README.md) describes the disposable checkout, receipts, consumer adapter and
offline selftest. Legacy receipts retain their original accept/reject outcomes. Fresh reviews are
recorded without a Markdown gate; failed execution and altered bytes are still detected. Neither
receipt integrity nor evidence of tool use proves that the reviewer read enough or judged correctly.

This design retains defect discovery and focused follow-up while withdrawing unproved automatic
approval. Safe merge completion has not been demonstrated by the available consumer sequences.
The [reassessment](../../dogfood/REASSESSMENT.md) records the evidence and the cost of this change.

`sol-simplify: preserve review evidence for the PR's repair and retrospective; remove the receipts
when neither is needed. No standing product inventory or new approval workflow is required.`
