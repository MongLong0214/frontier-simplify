#!/usr/bin/env bash
# Consumer entrypoint: exact PR refs in a host clone, one persistent ledger per PR.
# review-pr.sh REPOSITORY PR_NUMBER [1|2|auto|status|report|hunks] [EXECUTOR]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$HERE/lib/review-pr.py" "$@"
