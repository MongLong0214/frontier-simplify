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
head once; changed heads enter follow-up when an original review is available. See the
[runner guide](../skills/sol-simplify-review/README.md) for optional remediation responses and retries.

Runner exit 10 means review evidence was recorded. The poller treats it as a completed invocation,
so a BLOCK recommendation does not appear as an infrastructure failure. Poller exit 0 means its
invocations completed, **never that any PR is approved**. Existing maintainer review and product
checks decide merging; neither this command nor its child runner belongs in an automatic approval
condition.

The catalog carries attributed leads, including those from rejected reviews. No automatic standing
class is created from repeated mentions. Refusal reports expose available leaf reasons; they do not
measure the number of distinct bugs or prove the guards are correct. The local hook tests staged
runner behavior; its existence does not establish review efficacy. The evidence and changed
protocol decisions are recorded in [REASSESSMENT.md](REASSESSMENT.md).

`sol-simplify: this poller supplies consumer feedback; remove it when no configured consumer uses
it.` To uninstall on macOS, boot out `gui/$(id -u)/dev.sol-simplify.review-dogfood` with `launchctl`
and remove its matching plist from `~/Library/LaunchAgents`.
