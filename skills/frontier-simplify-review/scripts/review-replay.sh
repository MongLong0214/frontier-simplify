#!/usr/bin/env bash
# Read an explicit ledger directory without discovery, fetch, model execution or writes.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_COMMON_DIR \
      GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$HERE/lib/replay.py" "$@"
