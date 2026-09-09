# Consumer runs

`consumers.json` configures PR discovery and portability checks. `run.py` discovers open PRs and
calls the review entrypoint. It does not post, push or merge. Registration is configuration; it is
not evidence that a scheduler ran, a defect was fixed, or a merge completed.

Run `python3 dogfood/run.py` from an existing scheduler. On macOS the optional installer creates a
poller with a selected interval and evidence directory:

```sh
python3 dogfood/install.py --interval "$POLL_SECONDS" --artifacts "$REVIEW_ARTIFACTS"
```

It needs working `gh`, Git network access and an authenticated reviewer. The adapter attempts each
head once within a cumulative **three-attempt PR budget**; changed heads enter follow-up when an
original review is available. Failures and interruptions consume attempts too. The third attempt
hands off and later polls launch no reviewer. This guarantees termination of automatic attempts,
not safe merge convergence. See the
[runner guide](../skills/sol-simplify-review/README.md) for optional remediation responses and retries.

Runner exit 10 means review evidence was recorded; 11 means the automatic budget ended in a human
handoff. The poller treats these as completed invocations,
so a BLOCK recommendation does not appear as an infrastructure failure. Poller exit 0 means its
invocations completed, **never that any PR is approved**. Existing maintainer review and product
checks decide merging; neither this command nor its child runner belongs in an automatic approval
condition.

The catalog carries attributed leads, including those from rejected reviews. No automatic standing
class is created from repeated mentions. Refusal reports expose available leaf reasons; they do not
measure the number of distinct bugs or prove the guards are correct. The local hook tests staged
runner behavior; its existence does not establish review efficacy. The evidence and changed
protocol decisions are recorded in [REASSESSMENT.md](REASSESSMENT.md).

A completed feedback loop changes a later review or the product and preserves the evidence of
that change. For promotion, keep the original review/head and the new site's head, concrete
reproduction, repair, and unchanged regression test failing before and passing after. A person
checks the common cause and whether the occurrence is new; a rename, rerun, unclosed defect or
second class label does not become another independent incident. The same-PR new-site result
supports broader investigation, while a cross-consumer claim needs the source consumer's evidence
before it can be counted as independently reproduced. A direct user observation is attributed as
such, not discarded and not silently upgraded. No prose parser grants this status.

Use the [witness replay helper](../skills/sol-simplify-review/README.md#replay-a-regression-and-feed-it-into-later-reviews)
to turn a selected finding into a measured before/after contrast. The helper runs the same named
assertion on both commits and only publishes a lead when it fails before and passes after. Add
`"lessons": "/host/private/lessons/consumer"` to that consumer's entry, or set `REVIEW_LESSONS` for
the poller. Subsequent reviews automatically receive those leads, including follow-ups. Failed
replays publish no lead; a missing configured lesson directory is reported as an input error.

Automatic work is PR discovery, bounded review execution, artifact preservation, lead harvesting,
selected regression replay and reinjection. Humans select the causal question, implement the repair,
assess whether a reproduction is relevant and an occurrence independent, and decide the merge.
No scheduler or consumer configuration is silently installed by a replay. The demonstrated AOS
facet regression and Node empty-selector failure witnesses are recorded in
[REASSESSMENT.md](REASSESSMENT.md). This proves an executable feedback path, not a model-recall gain.

`sol-simplify: this poller supplies consumer feedback; remove it when no configured consumer uses
it.` To uninstall on macOS, boot out `gui/$(id -u)/dev.sol-simplify.review-dogfood` with `launchctl`
and remove its matching plist from `~/Library/LaunchAgents`.
