# Historical review protocol benchmark — not run

This describes the original two-round hypothesis, not the current runner contract. The
[consumer reassessment](../../dogfood/REASSESSMENT.md) withdrew that claim and automatic approval.
The proposed controlled benchmark below still has no results.

`skills/sol-simplify-review` ships with its design (`DESIGN.md`) and **without a measured claim.**
The rest of this repository reports numbers; this skill does not have them yet, and saying it
converges in two rounds before measuring it would be the same overclaim the protocol exists to catch.

## Where the design came from

Not from intuition. The reviewing model was given 35 of its own merge-gate verdicts from one
project (five pull requests, rounds 1-11 each), asked to diagnose why the sequence never converged,
and asked to design the protocol that fixes it. `DESIGN.md` is that answer, including the diagnosis
with citations to the individual verdicts.

The headline finding: the reviewer's findings were real every round — precision was never the
problem. **Recall and closure were.** One publication-boundary defect was found in rounds 1, 4 and
10 of the same PR as three different examples of one unfinished fix.

## What has to be measured before any claim

Arms: `plain`, `enumerate-line` (one sentence asking for all instances of each class),
`frozen-security-only` (the tempting design that lets a non-security remediation regression through),
and `skill`.

Eight scenarios, each seeded with hidden oracle tests the reviewer and implementer never see:
publication fan-out, fail-closed across layers, authority-and-migration, parallel backends,
fix-introduces-regression, adversarial handoff, an out-of-envelope guardrail case, and a diff-only case.

The metric is **safe two-round closure**, not fewer findings:

```text
safe two-round closure: X of N eligible runs
unsafe PASS:            X of N
round-1 escapes:        X of N
correct guardrail stop: X of M
```

A 5 → 1 finding sequence that leaves one real blocker did not converge. A run counts only when the
hidden oracle reports zero remaining blocking defects and no round-1 escape occurred.

## Honest limits, stated up front

The protocol claims at most two rounds only when round 1 is complete, the change is inside the
stated envelope, required platforms are available, the remediation is a descendant of the reviewed
head, and the implementer closes the inventory without unrelated changes. Outside those conditions
it is designed to declare `INCOMPLETE` or `RESTART_ROUND_1` rather than pretend.
