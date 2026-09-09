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

# 3. The reviewer must not see the target seal -- if it can read the seal it can echo
#    base, head and the changed-file list without opening any of them. The artifact
#    would then be authorizing itself, which is class G8 committed by the harness.
guard_no_seal_in_tree() {                      # <worktree>
  local hits
  hits=$(find "$1" -name 'SEAL.txt' -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null | head -5)
  [ -z "$hits" ] \
    || guard_fail seal-in-tree "SEAL.txt is visible inside the reviewed worktree: $hits"
}

#    The other half: did the reviewer reach the seal, wherever it lives? This reads what
#    the reviewer ran and what came back, so it catches a path the tree check cannot know
#    about. Measured: pointed at a diff by bare filename that was not in its cwd, a
#    reviewer searched upward, found the harness directory, and read the inputs out of
#    it -- one `cat` from the seal.
guard_seal_unseen() {                          # <events.jsonl> [<seal_dir>]
  python3 - "$1" "${2:-}" <<'PY'
import json, os, sys
bad = []
seal_dir = sys.argv[2] if len(sys.argv) > 2 else ""
seal_marker = os.path.join(seal_dir, "SEAL.txt") if seal_dir else ""
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try:
        o = json.loads(line)
    except ValueError:
        continue
    it = o.get("item") or {}
    if it.get("type") == "command_execution":
        issued = it.get("command") or ""
        received = it.get("aggregated_output") or ""
    elif o.get("type") == "assistant":
        issued = json.dumps(o.get("message") or {})
        received = ""
    elif o.get("type") == "user":
        issued = ""
        received = json.dumps(o.get("message") or {})
    else:
        continue
    # Where the string appears decides what it means. A reviewer that NAMES the seal in a
    # command is reaching for it, whatever it does with the result. A reviewer that merely
    # receives text containing the words has been handed them -- `ps aux` prints every other
    # process's full command line, and a sibling session's prompt mentioning SEAL.txt once
    # rejected an otherwise sound round. Nothing about that review's own seal was disclosed.
    # So the command side is matched on the name, the output side only on this seal's own
    # contents and its own path.
    hit = None
    for probe in ("SEAL.txt", "frontier-simplify-review-seal", "sol-simplify-review-seal", "target_sha256"):
        if probe in issued:
            hit = probe
            break
    if hit is None:
        for probe in ("frontier-simplify-review-seal", "sol-simplify-review-seal", "target_sha256", seal_marker):
            if probe and probe in received:
                hit = probe
                break
    if hit is not None:
        bad.append((hit, (issued or received)[:120]))
if bad:
    for probe, cmd in bad[:5]:
        print("GUARD FAIL [seal-seen] reviewer reached the seal (%s): %s" % (probe, cmd),
              file=sys.stderr)
    sys.exit(1)
PY
}

# 4. seal <-> head cross-check -- the tree the reviewer actually stood in must be the
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
