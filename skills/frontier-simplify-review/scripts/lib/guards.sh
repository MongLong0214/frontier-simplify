#!/usr/bin/env bash
# Execution and target-integrity checks. None certifies review quality or merge safety.

# The harness always names its repository with `git -C`. Inherited GIT_DIR / GIT_WORK_TREE
# override that, so a hook or CI job that exports them silently points these checks at a
# different repository -- measured: a relative GIT_DIR=.git makes the seal/head cross-check
# compare the wrong HEAD. It can fail a sound review; it can also pass a wrong one.
# Every git call here names its repository with `git -C`. Inherited GIT_DIR / GIT_WORK_TREE
# override that, so a hook or CI job that exports them silently points these checks at a different
# repository -- measured: a relative GIT_DIR=.git makes the seal/head cross-check compare the wrong
# HEAD. It can fail a sound review; it can also pass a wrong one. Scrubbed per call, not once at
# load: whoever sources this file may export them afterwards.
_git() { env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_PREFIX -u GIT_COMMON_DIR \
             -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES git "$@"; }

guard_fail() { echo "GUARD FAIL [$1] $2" >&2; return 1; }

# 1. The turn must have finished. A stream that stops early leaves a partial answer
#    that still parses.
#
#    The supported executors have different event vocabularies: codex ends with
#    `turn.completed`, claude with a `result` event. A guard that knew only one would fail every round of the other
#    for a reason that has nothing to do with the review -- and a guard that fails for
#    the wrong reason gets switched off.
guard_turn_completed() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/events.py" completed "$1" >/dev/null
}

# 2. cmds == 0 -- a reviewer that ran no command read nothing. The cheapest, least
#    interpretable signal there is: it needs no judgement to read.
guard_cmds_nonzero() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/events.py" commands "$1" >/dev/null
}

# 3. seal <-> head cross-check -- the tree the reviewer actually stood in must be the
#    commit the seal names, and that must be the commit under review upstream.
guard_seal_head_crosscheck() {                 # <seal_dir> <worktree> <upstream_head>
  local sealed wt up
  sealed=$(awk '$1=="head_sha:"{print $2}' "$1/SEAL.txt")
  wt=$(_git -C "$2" rev-parse HEAD)
  up="$3"
  [ -n "$sealed" ] || { guard_fail seal-head "no head_sha in $1/SEAL.txt"; return 1; }
  [ "$sealed" = "$wt" ] \
    || { guard_fail seal-head "sealed head $sealed != reviewed worktree HEAD $wt"; return 1; }
  [ -z "$up" ] || [ "$sealed" = "$up" ] \
    || { guard_fail seal-head "sealed head $sealed != upstream head under review $up"; return 1; }
}
