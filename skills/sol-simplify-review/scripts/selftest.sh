#!/usr/bin/env bash
# selftest.sh -- every guard must be shown to FAIL on the thing it names. A guard only
# ever observed passing is indistinguishable from one wired to nothing, which is class G4
# committed by the tool that exists to catch G4.
#
# Builds its own throwaway repository, so it runs anywhere and depends on no project.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/lib/guards.sh"
SKILL="$(cd "$HERE/.." && pwd)/SKILL.md"
T=$(mktemp -d); trap 'git -C "$T/repo" worktree remove --force "$T/rw" >/dev/null 2>&1; rm -rf "$T"' EXIT
pass=0; fail=0
ck() { # <name> <expect: ok|fail> <cmd...>
  local n="$1" e="$2"; shift 2
  if "$@" >/dev/null 2>&1; then r=ok; else r=fail; fi
  if [ "$r" = "$e" ]; then pass=$((pass+1)); echo "ok   $n ($r)"
  else fail=$((fail+1)); echo "NOT OK $n: expected $e got $r"; fi
}

# --- a repository of our own ---------------------------------------------------------
REPO="$T/repo"; mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t; git -C "$REPO" config user.name t
for i in 1 2 3; do
  printf 'v%s\n' "$i" > "$REPO/a.txt"; printf 'w%s\n' "$i" > "$REPO/b.txt"
  git -C "$REPO" add -A >/dev/null; git -C "$REPO" commit -qm "c$i"
done
HEAD_SHA=$(git -C "$REPO" rev-parse HEAD)
BASE=$(git -C "$REPO" rev-parse HEAD~2)
OTHER=$(git -C "$REPO" rev-parse HEAD~1)

# --- target seal -----------------------------------------------------------------------
ck seal-creates            ok   "$HERE/target-seal.sh" seal "$REPO" "$BASE" "$HEAD_SHA" "$T/s"
ck seal-refuses-second     fail "$HERE/target-seal.sh" seal "$REPO" "$BASE" "$HEAD_SHA" "$T/s"
ck seal-verify             ok   "$HERE/target-seal.sh" verify "$REPO" "$T/s" "$HEAD_SHA"
ck seal-verify-wrong-head  fail "$HERE/target-seal.sh" verify "$REPO" "$T/s" "$OTHER"
ck seal-base-not-ancestor  fail "$HERE/target-seal.sh" seal "$REPO" "$HEAD_SHA" "$BASE" "$T/s2"
cp "$T/s/inventory.txt" "$T/s/inv.bak"; echo "deadbeef  tampered.txt" >> "$T/s/inventory.txt"
ck seal-tampered-inventory fail "$HERE/target-seal.sh" verify "$REPO" "$T/s"
mv "$T/s/inv.bak" "$T/s/inventory.txt"
ck seal-restored           ok   "$HERE/target-seal.sh" verify "$REPO" "$T/s"

# --- guard 1/2: event stream ------------------------------------------------------------
printf '{"type":"turn.started"}\n{"type":"item.completed","item":{"type":"agent_message","text":"x"}}\n' > "$T/truncated.jsonl"
printf '{"type":"turn.started"}\n{"type":"turn.completed"}\n' > "$T/nocmds.jsonl"
printf '{"type":"item.completed","item":{"type":"command_execution"}}\n{"type":"turn.completed"}\n' > "$T/good.jsonl"
ck turn-completed-missing  fail guard_turn_completed "$T/truncated.jsonl"
ck turn-completed-present  ok   guard_turn_completed "$T/good.jsonl"
ck cmds-zero-rejected      fail guard_cmds_nonzero  "$T/nocmds.jsonl"
ck cmds-nonzero-accepted   ok   guard_cmds_nonzero  "$T/good.jsonl"

# --- guard 3: the seal must stay out of the reviewer's reach -----------------------------
mkdir -p "$T/wt/sub"
ck seal-absent-from-tree   ok   guard_no_seal_in_tree "$T/wt"
touch "$T/wt/sub/SEAL.txt"
ck seal-leaked-into-tree   fail guard_no_seal_in_tree "$T/wt"
rm "$T/wt/sub/SEAL.txt"

printf '{"type":"item.completed","item":{"type":"command_execution","command":"cat ../artifacts/x/SEAL.txt"}}\n' > "$T/sawseal-cmd.jsonl"
printf '{"type":"item.completed","item":{"type":"command_execution","command":"ls -la ..","aggregated_output":"schema: sol-simplify-review-seal.v1\\ntarget_sha256: abc"}}\n' > "$T/sawseal-out.jsonl"
ck seal-read-by-command    fail guard_seal_unseen "$T/sawseal-cmd.jsonl" "$T/s"
ck seal-leaked-in-output   fail guard_seal_unseen "$T/sawseal-out.jsonl" "$T/s"
ck seal-never-reached      ok   guard_seal_unseen "$T/good.jsonl" "$T/s"

# The bare filename appearing in text about SOME OTHER seal is not disclosure of this one.
# A real round was rejected because `ps aux` printed a sibling session's prompt whose text
# mentioned SEAL.txt; nothing about that review's own seal was disclosed. A guard that
# rejects a sound review for an unrelated string is a guard somebody switches off.
printf '{"type":"item.completed","item":{"type":"command_execution","command":"ps aux","aggregated_output":"claude -p ... guards: turn.completed, cmds==0, SEAL.txt existence ..."}}\n{"type":"turn.completed"}\n' > "$T/foreign.jsonl"
ck seal-word-in-foreign-text ok guard_seal_unseen "$T/foreign.jsonl" "$T/s"
printf '{"type":"item.completed","item":{"type":"command_execution","command":"cat x","aggregated_output":"schema: sol-simplify-review-seal.v1"}}\n{"type":"turn.completed"}\n' > "$T/own-content.jsonl"
ck seal-own-content-caught fail guard_seal_unseen "$T/own-content.jsonl" "$T/s"
printf "{\"type\":\"item.completed\",\"item\":{\"type\":\"command_execution\",\"command\":\"cat $T/s/SEAL.txt\"}}\n{\"type\":\"turn.completed\"}\n" > "$T/own-path.jsonl"
ck seal-own-path-caught    fail guard_seal_unseen "$T/own-path.jsonl" "$T/s"

# Round 2 must run on a different executor than round 1, and the two do not share an event
# vocabulary. Every guard that reads the stream is held to BOTH, so a claude round can never
# be rejected for speaking claude.
printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"cat lib/x.mjs"}}]}}\n{"type":"result","subtype":"success"}\n' > "$T/cl-good.jsonl"
printf '{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}\n{"type":"result","subtype":"success"}\n' > "$T/cl-nocmds.jsonl"
printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"cat ../SEAL.txt"}}]}}\n{"type":"result"}\n' > "$T/cl-sawseal.jsonl"
printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}\n' > "$T/cl-truncated.jsonl"
ck claude-turn-completed   ok   guard_turn_completed "$T/cl-good.jsonl"
ck claude-truncated        fail guard_turn_completed "$T/cl-truncated.jsonl"
ck claude-cmds-nonzero     ok   guard_cmds_nonzero  "$T/cl-good.jsonl"
ck claude-cmds-zero        fail guard_cmds_nonzero  "$T/cl-nocmds.jsonl"
ck claude-seal-unseen      ok   guard_seal_unseen   "$T/cl-good.jsonl" "$T/s"
ck claude-saw-seal         fail guard_seal_unseen   "$T/cl-sawseal.jsonl" "$T/s"

# --- guard 4: seal <-> head cross-check ---------------------------------------------------
git -C "$REPO" worktree add --detach "$T/rw" "$HEAD_SHA" >/dev/null 2>&1
ck crosscheck-match        ok   guard_seal_head_crosscheck "$T/s" "$T/rw" "$HEAD_SHA"
ck crosscheck-upstream-bad fail guard_seal_head_crosscheck "$T/s" "$T/rw" "$OTHER"
git -C "$T/rw" checkout --detach "$OTHER" >/dev/null 2>&1
ck crosscheck-worktree-bad fail guard_seal_head_crosscheck "$T/s" "$T/rw" "$HEAD_SHA"
git -C "$REPO" worktree remove --force "$T/rw" >/dev/null 2>&1

# --- the inventory as data ----------------------------------------------------------------
mkinv() { # <file> <accounting-block> <items-block> <verdict-block>
  cat > "$1" <<EOF
# Round 1 review inventory

## Binding
- repository: $REPO
- base_sha: $BASE
- head_sha: $HEAD_SHA
- basis: DIFF_ONLY
- scope: COMPLETE

## File accounting
$2

## Inventory
$3

## Routed exclusions encountered
- none

## Verdict
$4
EOF
}
GOODITEM='### G-01 — absence is not success
- kind: portable-class
- source: G2
- impact: BLOCKER
- must_hold: a missing value never becomes a default
- applies_to: a.txt readers
- status: PASS
- applicable_sites: a.txt:1
- failing_sites: none
- evidence: read a.txt, no default path exists
- reproduction: not applicable
- class_sweep: a.txt, b.txt
- dismissed_sites: none
- closure: not applicable
- catalog_candidate: none'
GOODV='- enumeration: COMPLETE
- verification: COMPLETE
- verdict: PASS'

mkinv "$T/inv-full.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$GOODITEM" "$GOODV"
mkinv "$T/inv-partial.md" "- a.txt — READ — changed" "$GOODITEM" "$GOODV"
mkinv "$T/inv-declared.md" "- a.txt — READ — changed
- b.txt — NOT_READ — out of budget" "$GOODITEM" "- enumeration: INCOMPLETE
- verification: PARTIAL
- verdict: INCOMPLETE"
mkinv "$T/inv-fab.md" "- a.txt — READ — changed
- b.txt — READ — changed
- no/such/file.mjs — READ — invented" "$GOODITEM" "$GOODV"
mkinv "$T/inv-empty.md" "- a.txt — NOT_READ — skipped
- b.txt — NOT_READ — skipped" "$GOODITEM" "$GOODV"

acct() { python3 "$HERE/lib/inventory-parse.py" --accounting "$1" > "$1.json" && \
         guard_coverage "$1.json" "$T/s" "$REPO" "$HEAD_SHA"; }
ck coverage-full           ok   acct "$T/inv-full.md"
ck coverage-declared-unread ok  acct "$T/inv-declared.md"
ck coverage-silent-partial fail acct "$T/inv-partial.md"
ck coverage-fabricated     fail acct "$T/inv-fab.md"
ck coverage-empty          fail acct "$T/inv-empty.md"

# READ_DIFF_ONLY is coverage, not silence -- the skill allows it for a one-hunk change.
mkinv "$T/inv-diffonly.md" "- a.txt — READ — changed
- b.txt — READ_DIFF_ONLY — one-hunk test change" "$GOODITEM" "$GOODV"
ck coverage-read-diff-only ok   acct "$T/inv-diffonly.md"

# --- shape ---------------------------------------------------------------------------------
printf 'The change looks fine to me.\n' > "$T/prose.md"
ck shape-prose-rejected    fail guard_inventory_shape "$T/prose.md" 1
ck shape-good-accepted     ok   guard_inventory_shape "$T/inv-full.md" 1
mkinv "$T/inv-noitems.md" "- a.txt — READ — changed
- b.txt — READ — changed" "" "$GOODV"
ck shape-no-items-rejected fail guard_inventory_shape "$T/inv-noitems.md" 1

# --- verdict consistency ---------------------------------------------------------------------
# "A reproduced blocker is a fact; an unfinished sweep does not unmake it."
BLOCKITEM='### G-02 — self-asserted authority
- kind: portable-class
- source: G1
- impact: BLOCKER
- must_hold: a caller-supplied label never decides the claim
- applies_to: a.txt
- status: FAIL
- applicable_sites: a.txt:1, b.txt:1
- failing_sites: a.txt:1
- evidence: ran it, a.txt:1 accepts the caller label
- reproduction: printf x > a.txt && run
- class_sweep: a.txt, b.txt
- dismissed_sites: none
- closure: recompute from evidence plus a regression test
- catalog_candidate: none'
mkinv "$T/inv-blockpass.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$BLOCKITEM" "$GOODV"
ck verdict-blocker-as-pass fail guard_verdict_consistent "$T/inv-blockpass.md"
mkinv "$T/inv-blockblock.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$BLOCKITEM" "- enumeration: COMPLETE
- verification: COMPLETE
- verdict: BLOCK"
ck verdict-blocker-as-block ok  guard_verdict_consistent "$T/inv-blockblock.md"
mkinv "$T/inv-incpass.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$GOODITEM" "- enumeration: INCOMPLETE
- verification: COMPLETE
- verdict: PASS"
ck verdict-incomplete-pass fail guard_verdict_consistent "$T/inv-incpass.md"
mkinv "$T/inv-oneaxis.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$GOODITEM" "- verdict: PASS"
ck verdict-one-axis-only   fail guard_verdict_consistent "$T/inv-oneaxis.md"
ck verdict-good            ok   guard_verdict_consistent "$T/inv-full.md"

# An UNVERIFIED item with verification: COMPLETE is the shape that quietly promotes an
# item nobody could exercise.
UNVITEM=$(printf '%s' "$GOODITEM" | sed 's/^- status: PASS$/- status: UNVERIFIED/')
mkinv "$T/inv-unv.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$UNVITEM" "$GOODV"
ck verdict-unverified-complete fail guard_verdict_consistent "$T/inv-unv.md"

# --- item fields -------------------------------------------------------------------------------
NASWEEP=$(printf '%s' "$GOODITEM" | sed -e 's/^- status: PASS$/- status: N\/A/' -e 's/^- evidence: .*$/- evidence:/' -e 's/^- source: G2$/- source:/')
mkinv "$T/inv-na.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$NASWEEP" "$GOODV"
ck item-na-without-reason  fail guard_item_fields "$T/inv-na.md"
NOSWEEP=$(printf '%s' "$BLOCKITEM" | sed 's/^- class_sweep: .*$/- class_sweep: none/')
mkinv "$T/inv-nosweep.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$NOSWEEP" "- enumeration: COMPLETE
- verification: COMPLETE
- verdict: BLOCK"
ck item-fail-without-sweep fail guard_item_fields "$T/inv-nosweep.md"
ck item-good               ok   guard_item_fields "$T/inv-full.md"
ck item-blocker-good       ok   guard_item_fields "$T/inv-blockblock.md"

# --- placeholder ---------------------------------------------------------------------------------
printf '# Round 1 review inventory\n\n## Verdict\n- verdict: BLOCK\n- evidence: TBD, reading the diff first\n' > "$T/ph.md"
ck placeholder-rejected    fail guard_no_placeholder "$T/ph.md"
ck placeholder-clean       ok   guard_no_placeholder "$T/inv-full.md"

# --- prompt rendering ------------------------------------------------------------------------------
r1() { python3 "$HERE/lib/render-prompt.py" "$SKILL" 1 REPOSITORY=r BASE_SHA=b ROUND1_HEAD_SHA=h \
  REQUIREMENT_SOURCES_OR_NONE=none KNOWN_ROUTED_OR_NONE=none PROJECT_CLASS_CATALOG_OR_NONE=none \
  FULL_SUITE_STATUS_OR_UNKNOWN=UNKNOWN TOOL_NOTES_OR_NONE=none; }
ck render-round1           ok   r1
ck render-unsubstituted    fail python3 "$HERE/lib/render-prompt.py" "$SKILL" 1 REPOSITORY=r
ck render-no-such-round    fail python3 "$HERE/lib/render-prompt.py" "$SKILL" 9

# --- extraction --------------------------------------------------------------------------------------
# Only the LAST agent message counts: an earlier draft that gets scored is a stored artifact
# approving itself in miniature.
python3 - "$T" <<'PY'
import json, sys
T = sys.argv[1]
draft = "# Round 1 review inventory\nDRAFT\n"
final = "# Round 1 review inventory\nFINAL\n"
with open(T + "/two.jsonl", "w") as f:
    for t in (draft, final):
        f.write(json.dumps({"type": "item.completed",
                            "item": {"type": "agent_message", "text": t}}) + "\n")
    f.write(json.dumps({"type": "turn.completed"}) + "\n")
with open(T + "/none.jsonl", "w") as f:
    f.write(json.dumps({"type": "item.completed",
                        "item": {"type": "agent_message", "text": "no artifact here"}}) + "\n")
PY
ex() { python3 "$HERE/lib/extract.py" "$1" "# Round 1 review inventory"; }
ck extract-finds           ok   ex "$T/two.jsonl"
ck extract-absent          fail ex "$T/none.jsonl"
got=$(ex "$T/two.jsonl" | tr -d '\n')
if [ "$got" = "# Round 1 review inventoryFINAL" ]; then
  pass=$((pass+1)); echo "ok   extract-takes-last (ok)"
else
  fail=$((fail+1)); echo "NOT OK extract-takes-last: got '$got'"
fi

echo "--- selftest: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
