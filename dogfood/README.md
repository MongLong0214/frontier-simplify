# Continuous consumer runs

`consumers.json` is deployment configuration. Consumer identities belong here, outside the portable
skill. `run.py` discovers each configured consumer's open PRs and calls the trusted review entrypoint.
It does not post reviews, change required checks, merge or push. The host retains the per-PR receipts.

Invoke `python3 dogfood/run.py` from an existing scheduler, or on macOS install the poller with a
chosen interval and private evidence directory:

```sh
python3 dogfood/install.py --interval "$POLL_SECONDS" --artifacts "$REVIEW_ARTIFACTS"
```

The scheduler requires working `gh`, Git network access and an authenticated reviewer executor.
A head is reviewed once; changed heads enter closure. Supply the separate remediation response and,
for extra rounds, named escape evidence as described in the [runner guide](../skills/sol-simplify-review/README.md).
A missing response blocks with one reason; a newly supplied response lets auto mode retry. Failures
are logged, never converted into a stored approval. This poller observes PRs; an existing merge
workflow must separately require the entrypoint's successful status if it is to enforce merging.

`sol-simplify: this poller supplies real consumer review feedback; remove it when no configured
consumer uses the protocol.` To uninstall, boot out `gui/$(id -u)/dev.sol-simplify.review-dogfood` with
`launchctl` and remove its matching plist from `~/Library/LaunchAgents`.
