#!/usr/bin/env sh
# frontier-simplify-audit: deterministic measurements over a git repository.
# Arithmetic only — deciding WHICH paths are machinery vs product is the
# agent's judgment, passed in as the two regexes. Nothing is pinned; every
# number is computed fresh from the tree and history at HEAD.
#
#   scripts/measure.sh '<machinery-path-regex>' '<product-path-regex>'
#
# Example (an agent-built repo with validators and gate tests):
#   scripts/measure.sh 'scripts/(resolve|validate)|tests/(planning|gate|execution)' '^(packages|adapters)/[^/]+/src/'
#
# Requires: git, grep, awk. POSIX sh. Read-only.
set -eu
M="${1:?usage: measure.sh <machinery-regex> <product-regex>}"
P="${2:?usage: measure.sh <machinery-regex> <product-regex>}"

git rev-parse --git-dir >/dev/null

loc() { # sum lines of tracked files whose path matches $1
  git ls-files | grep -E "$1" | while IFS= read -r f; do
    [ -f "$f" ] && wc -l < "$f"
  done | awk '{s+=$1} END {print s+0}'
}

M_LOC=$(loc "$M"); P_LOC=$(loc "$P")
TOTAL=$(git rev-list --count HEAD)

LOOP=$(git log --format='%s' \
  | grep -icE 're-measure|reconcile|re-pin|repin|census|realign|re-derive|rederive|restate|re-record|after rebase' || true)

REFUSE=$(git log --format='%s' \
  | grep -icE 'refuse|blocked|unblock|deadlock|cannot proceed' || true)

PCT=$(awk -v n="$LOOP" -v t="$TOTAL" 'BEGIN { printf "%.1f", t ? n * 100 / t : 0 }')

echo "== frontier-simplify-audit: measured at $(git rev-parse --short HEAD) =="
echo "ceremony ratio : ${M_LOC} machinery LOC : ${P_LOC} product LOC"
echo "candidate loop commits : ${LOOP} of ${TOTAL} (${PCT}%) — subject-line heuristic; confirm with diffs before claiming they shipped nothing"
echo "self-refusal   : ${REFUSE} commit subjects mention refusing/blocking"
echo
echo "== churn top 20 (what the project spends its life editing) =="
git log --format='' --name-only | grep -v '^$' | sort | uniq -c | sort -rn | head -20
echo
echo "== worst loop day =="
git log --format='%ad|%s' --date=short \
  | grep -iE 're-measure|reconcile|re-pin|census|realign|re-derive' \
  | cut -d'|' -f1 | sort | uniq -c | sort -rn | head -3
