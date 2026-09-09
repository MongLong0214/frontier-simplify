---
name: frontier-simplify-audit
description: Diagnoses a repository that has accumulated agent-built bureaucracy. Measures how much of the codebase exists to police the work rather than do it, finds the maintenance loops that produce commits with no product value, and ranks what to delete. Use when the user says "audit this repo for ceremony", "why is this repo so slow", "we spend all our time on tooling", "find the bureaucracy", "frontier-simplify-audit", or when a project is visibly stalled on its own gates and validators. One-shot report; deletes nothing.
metadata:
  author: MongLong0214 <MongLong0214@users.noreply.github.com>

---

# Frontier-simplify audit

Built for frontier coding agents including Fable and Astra (`gpt-6-astra`); the method is model-independent.

Find the machinery that exists to govern the work rather than perform it, and price it.
Report only; the user decides what dies.

## Measure

First decide, by reading the tree, which path patterns are *machinery* (validators, resolvers,
gate/contract/planning tests, governance registries) and which are *product* (application and
library source). That classification is your judgment and you must state it in the report.

The arithmetic is not your judgment. If this skill is installed with its directory, run:

```bash
scripts/measure.sh '<machinery-path-regex>' '<product-path-regex>'
```

It computes the ceremony ratio, loop-commit count and share, self-refusal mentions, the churn
top-20, and the worst loop day — fresh from HEAD, nothing cached, read-only. Use its output
verbatim; do not re-derive numbers it already printed.

If only this file was installed, fall back to the same measurements by hand:

**Ceremony ratio.** Lines of process machinery against lines of product.

```bash
# process machinery: validators, resolvers, gate/contract/planning tests, governance docs
# product: application and library source
```

Classify by what a file is *for*, not where it sits. A test that asserts the software behaves
is product. A test that asserts a document is well-formed, a count matches, or a gate was
observed is machinery. A ratio approaching or exceeding 1:1 is the headline finding.

**Loop commits.** Commits that only re-sync the checking system with itself:

```bash
git log --format='%ad %s' --date=short | grep -Ei \
  're-measure|reconcile|re-pin|census|realign|re-derive|restate|re-record|after rebase'
```

These are candidate loop commits, not proof that nothing shipped. Confirm with diffs before
classifying them. Report the candidate count, share, and worst single day with that limitation.

**Churn concentration.** The files the project actually spends its life on:

```bash
git log --format='' --name-only | grep -v '^$' | sort | uniq -c | sort -rn | head -20
```

If the top entries are validators, gate registries, and contract tests rather than product
source, the project's real output is its own governance. Say so with the numbers.

**Self-refusal.** Evidence that the process blocked the work:

```bash
git log --format='%ad %s' --date=short | grep -Ei 'refuse|blocked|unblock|deadlock|cannot proceed'
```

Also read AGENTS.md, CLAUDE.md, and any governance doc for rules that gate work on artifacts
the repository itself produces. Circular authority — a rule whose precondition only the rule's
own machinery can satisfy — is the most expensive finding there is.

**Expiring process.** Process deliberately kept carries its own removal trigger:

```bash
grep -rnE '(#|//|<!--) ?(frontier-simplify|sol-simplify):' .
```

Each hit is a row: what it is, why it exists, the condition that retires it. Any marker with no
removal condition gets a `no-trigger` tag — those are the ones that become permanent.

## Report

One line per finding, biggest cut first:

`<tag> <what to delete>. <what replaces it>. [path] (<cost: lines / commits>)`

Tags:

- `machinery:` tooling that authorizes, validates, or tracks work instead of doing it. Replacement: nothing, or a one-line check.
- `pin:` a frozen count or inventory that unrelated changes invalidate. Replacement: compute it, or drop it.
- `ceremony:` a document, registry, or record that exists so a process looks observed. Replacement: nothing.
- `circular:` a rule that gates work on something only its own machinery can produce. Replacement: delete the rule.
- `metatest:` a test that asserts process compliance rather than behavior. Replacement: nothing.

Close with the two numbers that matter:

```
ceremony ratio: <machinery LOC> : <product LOC>
loop commits:   <N> of <total> (<pct>%) — shipped nothing
```

Nothing to cut: `No manufactured process here. Ship.`

## Honesty boundary

Report only what you counted. Never state how much the project "would have saved" — the lean
version was never written, so there is no baseline to subtract from. The ceremony ratio, the
loop-commit count, and the churn table are real measurements; anything else is a guess. Say
which findings you are confident about and which need the maintainer to confirm intent.

## Boundaries

Scope is invented process only. Correctness bugs, security holes, and performance belong to a
normal review — do not report them here. Never flag as ceremony: tests that exercise behavior,
CI that builds and runs the suite, a CHANGELOG, a README, a LICENSE, or any process the user
adopted deliberately rather than an agent manufacturing it. Ask before assuming a governance
artifact was agent-built; some teams genuinely need gates. Lists findings, applies none.
