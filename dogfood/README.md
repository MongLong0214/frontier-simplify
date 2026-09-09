# Consumer runs

Frontier-simplify's local consumer runner supports the Fable/Astra-oriented workflow through
the executor available on your host. `REVIEW_CODEX_MODEL=gpt-6-astra` selects Astra for Codex;
Fable use depends on your configured executor, not an assumed model alias in this runner.

`consumers.json` configures PR discovery and portability checks. `run.py` discovers open PRs and
calls the review entrypoint. It does not post, push or merge. Registration is configuration; it is
not evidence that a scheduler ran, a defect was fixed, or a merge completed.

The checked-in paths are this maintainer's local checkouts, not automatic clone instructions.
Point `REVIEW_CONSUMERS_CONFIG` at your own JSON file with `consumers` entries containing
`repository` paths (and optional `lessons` and portability `markers`). Each checkout needs an
`origin` remote. This skill repository is deliberately not its own consumer.

```sh
python3 dogfood/run.py --status  # live PR discovery + local status; no model or Git fetch
python3 dogfood/run.py           # one discovery/review pass, then exit
```

Discovery reports the number of open PRs per consumer, including zero, and reads up to 1,000 per
repository. A consumer lookup failure is reported and does not skip the remaining consumers.
`--status` returning 0 means the lookup completed, not that every PR has a fresh review.

Run the one-shot command from an existing scheduler if desired. On macOS the optional installer
creates a poller with a selected interval, config and evidence directory:

```sh
python3 dogfood/install.py --interval "$POLL_SECONDS" --artifacts "$REVIEW_ARTIFACTS" \
  --config "$REVIEW_CONSUMERS_CONFIG"
```

The installer starts the poller immediately and records the current PATH, selected reviewer/model,
timeout and supplied prompt/lesson settings; rerun it after changing these settings or moving this
installation. It does not install dependencies or copy authentication tokens. Use a working Python
with the standard `plistlib` module. Logs are `dogfood.log` and `dogfood.err` in the evidence directory.
To inspect the installed job, run `launchctl print "gui/$(id -u)/dev.frontier-simplify.review-dogfood"`.
Plugin installation alone does not install this job.
When replacing the old `dev.sol-simplify.review-dogfood` job, the installer stops it and keeps
its plist as `.plist.disabled` before starting the renamed job. Keep the same artifact directory.

It needs working `gh`, Git network access and an authenticated reviewer. Auto mode reuses unchanged
inputs within a cumulative **three-attempt PR budget**. Changes to heads, target tips, supplied
context, response/lesson bytes, executor/model, timeout or protocol permit a new remaining attempt.
Generated same-PR history never invalidates itself. Changed heads enter follow-up when compatible;
a changed base or rewritten history starts a fresh scope review without resetting the count.
Failures and interruptions consume attempts too. The third attempt
hands off and later polls launch no reviewer. This guarantees termination of automatic attempts,
not safe merge convergence. See the
[runner guide](../skills/frontier-simplify-review/README.md) for optional remediation responses and retries.

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

Use the [witness replay helper](../skills/frontier-simplify-review/README.md#replay-a-regression-and-feed-it-into-later-reviews)
to turn a selected finding into a measured before/after contrast. The helper runs the same named
assertion on both commits and only publishes a lead when it fails before and passes after. Add
`"lessons": "/host/private/lessons/consumer"` to that consumer's entry, or set `REVIEW_LESSONS` for
the poller. Subsequent reviews automatically receive those leads, including follow-ups. Failed
replays publish no lead; a missing configured lesson directory is reported as an input error.

The poller automates PR discovery, bounded review execution, artifact preservation, lead harvesting
and delivery of configured lessons. Regression replay is a separate, explicitly invoked helper;
the poller does not discover repairs or publish lessons by itself. Humans select the causal question, implement the repair,
assess whether a reproduction is relevant and an occurrence independent, and decide the merge.
No scheduler or consumer configuration is silently installed by a replay. The demonstrated AOS
facet regression and Node empty-selector failure witnesses are recorded in
[REASSESSMENT.md](REASSESSMENT.md). This proves an executable feedback path, not a model-recall gain.

`frontier-simplify: this poller supplies consumer feedback; remove it when no configured consumer uses
it.` To uninstall on macOS, boot out `gui/$(id -u)/dev.frontier-simplify.review-dogfood` with `launchctl`
and remove its matching plist from `~/Library/LaunchAgents`.
