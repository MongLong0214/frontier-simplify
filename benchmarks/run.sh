#!/usr/bin/env bash
# Reproduce the frontier-simplify benchmark: same prompt, four arms.
#
#   ./run.sh 01-prd
#   ./run.sh 02-process
#   ./run.sh 03-loop | 04-guardrail | 05-incident
#
# Requires an authenticated `codex` CLI. Outputs land in results/<prompt>-<arm>/.
set -euo pipefail

P="${1:?usage: run.sh <prompt-name>}"
MODEL="${FRONTIERSIMPLIFY_MODEL:-${SOLSIMPLIFY_MODEL:-gpt-6-astra}}"
EFFORT="${FRONTIERSIMPLIFY_EFFORT:-${SOLSIMPLIFY_EFFORT:-xhigh}}"
HERE="$(cd "$(dirname "$0")" && pwd)"
# Re-runs write to results/<prompt>-<arm>-<tag> so they never overwrite a committed result:
# SCORES.md cites line numbers inside those files, and clobbering them silently breaks
# every citation.  FRONTIERSIMPLIFY_TAG=symmetric ./run.sh 03-loop
REAL_HOME="${CODEX_HOME:-$HOME/.codex}"
TAG="${FRONTIERSIMPLIFY_TAG:-${SOLSIMPLIFY_TAG:-}}"

# Every arm runs against a throwaway CODEX_HOME built from your credentials alone, so the
# control base and the skill base differ by exactly one file: the skill. Using your real
# ~/.codex for the skill arm would let your other skills, plugins, and AGENTS.md into the
# result and make the effect unattributable. Moving ~/.codex/skills/frontier-simplify aside is
# also NOT enough for control arms: Codex's shared app-server daemon caches discovered
# skills, and a parked skill can still reach the model — silently.
CLEAN="$(mktemp -d)"
ON_HOME="$(mktemp -d)"
WORK="$(mktemp -d /tmp/frontier-benchmark.XXXXXX)"
trap 'rm -rf "$CLEAN" "$ON_HOME" "$WORK"' EXIT
[ -f "$REAL_HOME/auth.json" ] || {
  echo "no auth.json in $REAL_HOME — run 'codex login' first" >&2; exit 1; }
for H in "$CLEAN" "$ON_HOME"; do
  cp "$REAL_HOME/auth.json" "$H/"
  printf 'model = "%s"\napproval_policy = "never"\nsandbox_mode = "workspace-write"\nmodel_reasoning_effort = "%s"\n' \
    "$MODEL" "$EFFORT" > "$H/config.toml"
done
# The only difference between the control base and the skill base is the skill.
mkdir -p "$ON_HOME/skills"
cp -R "$HERE/../skills/frontier-simplify" "$ON_HOME/skills/"

run() { # $1 = arm, $2 = codex home, $3 = extra instruction (optional)
  local out="$HERE/results/$P-$1${TAG:+-$TAG}"
  local work="$WORK/$1"
  [ ! -e "$out" ] || { echo "refusing to overwrite existing benchmark: $out" >&2; exit 1; }
  mkdir -p "$out" "$work"
  if [ -d "$HERE/seeds/$P" ]; then cp -R "$HERE/seeds/$P/." "$work/"; fi
  cp "$HERE/prompts/$P.md" "$work/req.md"
  if [ -n "${3:-}" ]; then printf '\n%s\n' "$3" >> "$work/req.md"; fi
  # Do not inherit the maintainer's ancestor AGENTS.md or expose sibling benchmark outputs.
  printf '\nBenchmark scope: work only in this directory. You may read installed skills from CODEX_HOME. Do not inspect parent/home directories, other results, or delegate.\n' >> "$work/req.md"
  local rc=0
  ( cd "$work" && CODEX_HOME="$2" codex exec -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
      --sandbox workspace-write --skip-git-repo-check - < req.md > run.log 2>&1 ) || rc=$?
  cp -R "$work/." "$out/"
  [ "$rc" = 0 ] || return "$rc"
  # Count the produced document the way SCORES.md records it: wc -l of what the agent wrote.
  # req.md is the prompt and AGENTS.md is seeded, so neither is output — folding them in
  # inflates the number and makes a reproduction disagree with the committed table.
  local n; n=$(find "$out" -maxdepth 1 -type f -name '*.md' \
    ! -name req.md ! -name AGENTS.md -exec cat {} + 2>/dev/null | wc -l | tr -d ' ')
  local leak; leak=$(grep -rlE '(frontier-simplify|sol-simplify):' "$out" 2>/dev/null | grep -cv req.md || true)
  printf '%-11s %5s lines' "$1" "$n"
  if [ "$1" != on ] && [ "$leak" != 0 ]; then
    printf '   ⚠ CONTAMINATED — skill reached a control arm'
  fi
  echo
}

ONELINE_KO='불필요한 절차·문서·게이트를 만들지 마라. 요청한 것만 만들어라.'
ONELINE_EN='Make the smallest change that fully solves the task. Do not add abstractions, fallbacks, defensive guards, refactors, or features unless they are strictly required.'

run off        "$CLEAN"
run oneline    "$CLEAN" "$ONELINE_KO"
run oneline-en "$CLEAN" "$ONELINE_EN"
run on         "$ON_HOME"
