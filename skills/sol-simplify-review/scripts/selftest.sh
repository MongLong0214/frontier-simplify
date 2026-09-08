#!/usr/bin/env bash
# selftest.sh -- every guard must be shown to FAIL on the thing it names. A guard only
# ever observed passing is indistinguishable from one wired to nothing, which is class G4
# committed by the tool that exists to catch G4.
#
# Builds its own throwaway repository, so it runs anywhere and depends on no project.
set -uo pipefail
# This suite builds its own repository and measures it. Inherited git environment points
# those measurements at somebody else's repository, so it is dropped here too -- the hook
# driver scrubs it as well, and a check this cheap belongs on both sides of that boundary.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_COMMON_DIR \
      GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_HERE="$HERE"
HERE="${REVIEW_TEST_SCRIPTS:-$HERE}"
export PYTHONDONTWRITEBYTECODE=1
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

# Git exports GIT_DIR into every hook. With an absolute value, `git -C <worktree> rev-parse HEAD`
# answers for the EXPORTING repository instead of the worktree named -- measured. The dangerous
# direction is not a false failure: point the leak at a repository whose HEAD equals the sealed
# head, which is exactly the case when a repository reviews itself, and a genuine mismatch reads
# as a match. The guard would then approve a tree it never looked at.
env_leak_cannot_forge_a_match() {
  git -C "$REPO" worktree add --detach "$T/leak" "$OTHER" >/dev/null 2>&1 || return 1
  # Sealed head is HEAD_SHA, the tree is at OTHER: a real mismatch the guard must catch even
  # though the leaked GIT_DIR's own HEAD is HEAD_SHA.
  ( export GIT_DIR="$REPO/.git"
    guard_seal_head_crosscheck "$T/s" "$T/leak" "$HEAD_SHA" ); r=$?
  git -C "$REPO" worktree remove --force "$T/leak" >/dev/null 2>&1
  [ "$r" -ne 0 ]
}
ck crosscheck-leak-cannot-forge-match ok env_leak_cannot_forge_a_match

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

# Reviewers write the far side of a rename as `...new.txt`, and did so in two of four rounds on
# one PR. Read literally that is a file that does not exist, so the round is rejected twice: once
# as a fabricated path, once for the real file left silent. It resolves only when exactly one
# sealed path ends with the suffix -- the sealed list is fixed before the reviewer exists, so that
# is arithmetic, not charity. An ambiguous suffix must still fail, or the shorthand becomes a way
# to claim a file without naming it.
mkinv "$T/inv-elided.md" "- a.txt — READ — changed
- \`a.txt\` \u2192 \`...b.txt\` — READ — renamed" "$GOODITEM" "$GOODV"
ck coverage-elided-unique-resolves ok acct "$T/inv-elided.md"
mkinv "$T/inv-elided-ambiguous.md" "- a.txt — READ — changed
- \`...txt\` — READ — matches both sealed files" "$GOODITEM" "$GOODV"
ck coverage-elided-ambiguous-fails fail acct "$T/inv-elided-ambiguous.md"
mkinv "$T/inv-elided-nomatch.md" "- a.txt — READ — changed
- b.txt — READ — changed
- \`...nowhere.mjs\` — READ — no sealed path ends with this" "$GOODITEM" "$GOODV"
ck coverage-elided-nomatch-fails fail acct "$T/inv-elided-nomatch.md"

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
# A defect in a comment has no runtime reproduction, and SKILL.md's template says so: it reads
# `reproduction: <minimal reproduction, or not applicable>`. What a FAIL cannot be without is
# evidence a reader can go and check.
NOREPRO=$(printf '%s' "$BLOCKITEM" | sed 's|^- reproduction: .*$|- reproduction: not applicable|')
mkinv "$T/inv-norepro.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$NOREPRO" "- enumeration: COMPLETE
- verification: COMPLETE
- verdict: BLOCK"
ck item-fail-not-applicable-repro ok guard_item_fields "$T/inv-norepro.md"
NOEVID=$(printf '%s' "$NOREPRO" | sed 's|^- evidence: .*$|- evidence: none|')
mkinv "$T/inv-noevid.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$NOEVID" "- enumeration: COMPLETE
- verification: COMPLETE
- verdict: BLOCK"
ck item-fail-without-evidence fail guard_item_fields "$T/inv-noevid.md"
ck item-good               ok   guard_item_fields "$T/inv-full.md"
ck item-blocker-good       ok   guard_item_fields "$T/inv-blockblock.md"

# --- emphasis and placeholder position ---
# A reviewer writes its verdict in bold. Measured: an inventory reporting `- verdict: **BLOCK**`
# with both axes in bold was rejected for reporting neither axis, and the same run was rejected a
# second time because one closure line recommended a "durable pending record" -- the product's
# vocabulary, in a field that was not a verdict.
mkinv "$T/inv-bold.md" "- a.txt — READ — changed
- b.txt — READ — changed" "$BLOCKITEM" "- enumeration: **COMPLETE**. every changed file read
- verification: **COMPLETE**. no item is UNVERIFIED
- verdict: **BLOCK**"
ck verdict-reads-through-emphasis ok guard_verdict_consistent "$T/inv-bold.md"
printf '# Round 1 review inventory\n\n## Verdict\n- verdict: BLOCK\n- closure: write it through a durable pending record replayed on next open\n' > "$T/domain-word.md"
ck placeholder-domain-word-allowed ok guard_no_placeholder "$T/domain-word.md"
printf '# Round 1 review inventory\n\n## Inventory\n### O-01 — x\n- status: TBD\n' > "$T/ph-value.md"
ck placeholder-as-value-rejected fail guard_no_placeholder "$T/ph-value.md"
printf '# Round 1 review inventory\n\n## Inventory\n### O-01 — x\n- status: **pending**\n' > "$T/ph-bold.md"
ck placeholder-value-through-emphasis fail guard_no_placeholder "$T/ph-bold.md"

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
# Measured: a reviewer emitted a complete inventory, then appended one corrected line after its
# mutation sweep finished. The earlier message must not be sealed -- its author has revised it --
# but the caller was left an empty file and a shape error naming every missing section, which
# describes neither what happened nor what to do.
python3 - "$T" <<'PY'
import json, sys
T = sys.argv[1]
with open(T + "/amended.jsonl", "w") as f:
    for t in ("# Round 1 review inventory\nFULL\n",
              "One correction to the coverage line; the verdict is unchanged.\n"):
        f.write(json.dumps({"type": "assistant",
                            "message": {"content": [{"type": "text", "text": t}]}}) + "\n")
    f.write(json.dumps({"type": "result", "subtype": "success"}) + "\n")
PY
ck extract-amended-refused fail ex "$T/amended.jsonl"
# stderr goes to a file, not through `2>&1`: ck redirects the function's stdout to /dev/null
# before the body runs, so `2>&1` would duplicate /dev/null and the message would vanish.
amended_says_why() { ex "$T/amended.jsonl" 2>"$T/amended.err" >/dev/null
  grep -q 'amended by a later message' "$T/amended.err"; }
ck extract-amended-names-the-cause ok amended_says_why

ck extract-finds           ok   ex "$T/two.jsonl"
ck extract-absent          fail ex "$T/none.jsonl"
got=$(ex "$T/two.jsonl" | tr -d '\n')
if [ "$got" = "# Round 1 review inventoryFINAL" ]; then
  pass=$((pass+1)); echo "ok   extract-takes-last (ok)"
else
  fail=$((fail+1)); echo "NOT OK extract-takes-last: got '$got'"
fi

python3 "$TEST_HERE/selftest-protocol.py" "$HERE" > "$T/protocol.log" 2>&1
extra_rc=$?
cat "$T/protocol.log"
extra_pass=$(awk '/^protocol-selftest:/{print $2}' "$T/protocol.log")
extra_fail=$(awk '/^protocol-selftest:/{print $4}' "$T/protocol.log")
pass=$((pass + ${extra_pass:-0}))
fail=$((fail + ${extra_fail:-0}))
if [ "$extra_rc" -ne 0 ] && [ "${extra_fail:-0}" -eq 0 ]; then fail=$((fail+1)); fi
echo "--- selftest: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
