#!/usr/bin/env bash
# review-round.sh -- run one round of sol-simplify-review-v1 against a live model and
# refuse the answer if it cannot be shown to have read anything.
#
#   review-round.sh <round> <repo> <head> <slug> [base] [executor]
#     round     1 | 2 | 3...  (round 3+ runs the round-2 prompt; a gate that blocks twice
#               needs a third round, and an artifact labelled "round 2" that came from a
#               third is a receipt that misdescribes what produced it)
#     repo      path to the repository under review
#     head      the commit under review -- a SHA, not a branch name
#     slug      artifact directory name, e.g. pr649-r1
#     base      default: merge-base of the repo's default branch and head
#     executor  codex (default for round 1) | claude | stub
#
# The review runs in a throwaway worktree at <head>, so it reads exactly what will merge.
# Running with `cd <shared repo>` breaks two things at once: it moves a working tree
# another session is using, and it reviews uncommitted state rather than what will merge.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(cd "$HERE/.." && pwd)/SKILL.md"
. "$HERE/lib/guards.sh"

round="${1:?round}"; REPO="${2:?repo}"; ref="${3:?head}"; slug="${4:?slug}"
base_arg="${5:-}"; executor="${6:-}"
[ -n "$executor" ] || { [ "$round" = "1" ] && executor=codex || executor=claude; }

ART_ROOT="${REVIEW_ARTIFACTS:-$HOME/.sol-simplify-review}"
art="$ART_ROOT/$slug"; wt="$ART_ROOT/wt/$slug"

head=$(git -C "$REPO" rev-parse --verify "$ref^{commit}")

# The host contract says base is the MERGE-BASE of the target branch and the head, not the
# target branch tip. On a PR that has diverged -- which is most PRs big enough to need this
# protocol -- the tip is not an ancestor of the head and the seal refuses it. Defaulting to
# the tip is how that arrives as a confusing seal error instead of a scope decision.
if [ -n "$base_arg" ]; then
  basesha=$(git -C "$REPO" rev-parse --verify "$base_arg^{commit}")
else
  target="${REVIEW_TARGET_BRANCH:-$(git -C "$REPO" symbolic-ref --quiet --short HEAD 2>/dev/null || echo main)}"
  basesha=$(git -C "$REPO" merge-base "$target" "$head")
  tip=$(git -C "$REPO" rev-parse --verify "$target^{commit}")
  if [ "$tip" != "$basesha" ]; then
    # Not an error. It is a fact the Binding must carry: a later merge of the target
    # changes what this inventory bounds.
    echo "review: SCOPE-CHANGE risk -- $target has moved past the merge-base ($basesha)." >&2
    echo "review: record this in the Binding; a later merge changes what the inventory bounds." >&2
  fi
fi

[ -e "$art/SEAL.txt" ] && { echo "review: $slug already sealed; pick a new slug" >&2; exit 3; }
mkdir -p "$art" "$(dirname "$wt")"

# --- seal the target before the reviewer exists -------------------------------------
"$HERE/target-seal.sh" seal "$REPO" "$basesha" "$head" "$art"

# --- disposable worktree at the exact ref --------------------------------------------
[ -d "$wt" ] && git -C "$REPO" worktree remove --force "$wt" 2>/dev/null || true
git -C "$REPO" worktree add --detach "$wt" "$head" >/dev/null
git -C "$REPO" diff "$basesha" "$head" > "$art/DIFF.patch"

# The changed-file list is built by scanning the seal NOW, never from memory: a list
# copied from an earlier round goes stale exactly when the work moves fastest, and then a
# correct review gets rejected for reading the file that was renamed.
awk '{print $2}' "$art/inventory.txt" > "$art/CHANGED.txt"

# Both land IN the worktree. Named by bare filename while sitting only in the artifact
# directory, they send the reviewer hunting -- and a reviewer that walks up out of the
# worktree lands in the directory holding the seal. Give it the inputs where it already
# stands and it has no reason to leave.
cp "$art/DIFF.patch" "$art/CHANGED.txt" "$wt/"
[ "$round" = "1" ] || {
  for f in ROUND1_INVENTORY.md IMPLEMENTER_RESPONSE.md REMEDIATION.patch REMEDIATION_CHANGED.txt; do
    [ -f "$ART_ROOT/$f" ] && cp "$ART_ROOT/$f" "$wt/" || true
  done
}
guard_no_seal_in_tree "$wt"

# --- prompt, rendered from SKILL.md ---------------------------------------------------
# SKILL.md is the authority for the prompt. Rendering from it means the harness cannot
# drift from the protocol it claims to run.
if [ "$round" = "1" ]; then
  marker="# Round 1 review inventory"
  python3 "$HERE/lib/render-prompt.py" "$SKILL" 1 \
    "REPOSITORY=$(git -C "$REPO" rev-parse --show-toplevel)" \
    "BASE_SHA=$basesha" "ROUND1_HEAD_SHA=$head" \
    "REQUIREMENT_SOURCES_OR_NONE=${REVIEW_REQUIREMENTS:-none}" \
    "KNOWN_ROUTED_OR_NONE=${REVIEW_ROUTED:-none}" \
    "PROJECT_CLASS_CATALOG_OR_NONE=${REVIEW_CATALOG:-none}" \
    "FULL_SUITE_STATUS_OR_UNKNOWN=${REVIEW_SUITE_STATUS:-UNKNOWN}" \
    "TOOL_NOTES_OR_NONE=${REVIEW_TOOL_NOTES:-none}" > "$art/prompt.txt"
else
  marker="# Round 2 closure review"
  python3 "$HERE/lib/render-prompt.py" "$SKILL" 2 \
    "REPOSITORY=$(git -C "$REPO" rev-parse --show-toplevel)" \
    "BASE_SHA=$basesha" "ROUND1_HEAD_SHA=${REVIEW_ROUND1_HEAD:?REVIEW_ROUND1_HEAD}" \
    "ROUND2_HEAD_SHA=$head" \
    "TRUSTED_INVENTORY_SHA256=${REVIEW_INVENTORY_SHA256:?REVIEW_INVENTORY_SHA256}" \
    "INVENTORY_INTEGRITY_RESULT=${REVIEW_INTEGRITY:?REVIEW_INTEGRITY}" \
    "FULL_SUITE_STATUS_OR_UNKNOWN=${REVIEW_SUITE_STATUS:-UNKNOWN}" \
    "TOOL_NOTES_OR_NONE=${REVIEW_TOOL_NOTES:-none}" > "$art/prompt.txt"
fi

# --- live model call -------------------------------------------------------------------
# The response is written by THIS invocation. Nothing is read back from a previous round's
# artifact: a stored answer that approves the current head is class G8.
echo "review: $executor reviewing $head (round $round) ..." >&2
case "$executor" in
  codex)
    ( cd "$wt" && echo "" | codex exec --json -m "${REVIEW_CODEX_MODEL:-gpt-5.6-sol}" \
        -c 'model_reasoning_effort="xhigh"' -s read-only "$(cat "$art/prompt.txt")" ) \
      > "$art/events.jsonl" 2> "$art/executor.err" || true ;;
  claude)
    ( cd "$wt" && claude -p --output-format stream-json --verbose \
        --permission-mode bypassPermissions "$(cat "$art/prompt.txt")" ) \
      > "$art/events.jsonl" 2> "$art/executor.err" || true ;;
  stub)
    # selftest only: replays a canned event stream so the plumbing around the model call
    # can be exercised without spending a review.
    cp "${REVIEW_STUB:?REVIEW_STUB}" "$art/events.jsonl" ;;
  *) echo "review: unknown executor $executor" >&2; exit 2 ;;
esac

# --- guards -----------------------------------------------------------------------------
rc=0
guard_turn_completed "$art/events.jsonl" || rc=1
guard_cmds_nonzero "$art/events.jsonl" || rc=1
# Counted with the same pattern the guard uses. A metrics line that counted only codex's
# word once reported commands_executed=0 beside a claude round that ran 55 -- the guard was
# right and the number next to it was not, which is the worse of the two failures.
cmds=$(grep -cE '"type"[[:space:]]*:[[:space:]]*"(command_execution|tool_use)"' "$art/events.jsonl" || true)
guard_seal_head_crosscheck "$art" "$wt" "$head" || rc=1
guard_no_seal_in_tree "$wt" || rc=1
guard_seal_unseen "$art/events.jsonl" "$art" || rc=1
"$HERE/target-seal.sh" verify "$REPO" "$art" "$head" || rc=1

out="$art/ARTIFACT.md"
python3 "$HERE/lib/extract.py" "$art/events.jsonl" "$marker" > "$out" || rc=1
if [ -s "$out" ]; then
  guard_no_placeholder "$out" || rc=1
  guard_inventory_shape "$out" "$round" || rc=1
  if [ "$round" = "1" ]; then
    guard_verdict_consistent "$out" || rc=1
    guard_item_fields "$out" || rc=1
    python3 "$HERE/lib/inventory-parse.py" --accounting "$out" > "$art/accounting.json"
    guard_coverage "$art/accounting.json" "$art" "$REPO" "$head" || rc=1
  fi
else
  echo "GUARD FAIL [no-response] executor produced no artifact starting with '$marker'" >&2; rc=1
fi

echo "commands_executed=${cmds:-0}" | tee "$art/metrics.txt"
git -C "$REPO" worktree remove --force "$wt" 2>/dev/null || true

if [ "$rc" -ne 0 ]; then
  echo "review: REJECTED -- guards failed; this response is not evidence. $art" >&2
  exit 5
fi
echo "review: accepted -- $out"
