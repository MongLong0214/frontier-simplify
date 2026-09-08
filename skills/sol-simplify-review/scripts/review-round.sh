#!/usr/bin/env bash
# review-round.sh <1|2|report|path|hunks> REPO HEAD PR_ID [BASE] [EXECUTOR]
# Phase 1 enumerates; phase 2 closes. The host assigns actual rounds per stable PR ID.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$HERE/lib/run-review.py" "$@"
