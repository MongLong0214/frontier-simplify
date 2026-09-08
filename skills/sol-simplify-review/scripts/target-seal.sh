#!/usr/bin/env bash
# target-seal.sh -- bind a review to an exact (base, head) pair and an inventory of what
# changed between them, so a later response can be checked against a target it could not
# have chosen for itself.
#
#   target-seal.sh seal   <repo> <base_sha> <head_sha> <outdir>
#   target-seal.sh verify <repo> <outdir> [<expected_head_sha>]
#
# This is NOT review-seal.sh. The two seal different things and both are needed:
#   review-seal.sh  seals the reviewer's inventory document -- it stops the implementer
#                   editing the round-1 artifact between rounds.
#   target-seal.sh  seals the target -- it stops the reviewer choosing, or drifting off,
#                   what it was supposed to read.
#
# The seal is written OUTSIDE the reviewed worktree. A reviewer that can read the seal can
# echo its values without reading anything, which is the failure this file exists to
# prevent -- see guard_no_seal_in_tree in lib/guards.sh.
set -euo pipefail

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$@" | awk '{print $1}'
  else openssl dgst -sha256 "$@" | awk '{print $NF}'; fi
}

build_inventory() {   # <repo> <base> <head>  -> stdout: "<blob_sha>  <path>" sorted
  python3 - "$@" <<'PYTHON'
import subprocess, sys
repo, base, head = sys.argv[1:]
def git(*args):
    return subprocess.check_output(['git', '-C', repo, *args], stderr=subprocess.PIPE)
paths = sorted(p for p in git('diff', '--no-renames', '--name-only', '-z', base, head).split(b'\0') if p)
for raw in paths:
    path = raw.decode('utf-8')
    if '\n' in path or '\r' in path:
        sys.exit('GUARD FAIL [target-path] newline filenames cannot be represented in Markdown file accounting')
    p = subprocess.run(['git', '-C', repo, 'rev-parse', '--verify', '--quiet', head + ':' + path], capture_output=True)
    blob = p.stdout.decode().strip() if p.returncode == 0 else 'absent'
    print(blob + '  ' + path)
PYTHON
}

cmd_seal() {
  local repo="$1" base="$2" head="$3" out="$4"
  mkdir -p "$out"
  # Refuse to overwrite: a sealed directory is evidence, and a second seal over the same
  # directory is how a stored artifact comes to describe a tree it never saw.
  if [ -e "$out/SEAL.txt" ]; then
    echo "target-seal: refuse -- $out/SEAL.txt already exists; seal once per round" >&2
    exit 3
  fi
  base=$(git -C "$repo" rev-parse --verify "$base^{commit}")
  head=$(git -C "$repo" rev-parse --verify "$head^{commit}")
  git -C "$repo" merge-base --is-ancestor "$base" "$head" || {
    echo "target-seal: refuse -- base $base is not an ancestor of head $head" >&2; exit 3; }

  build_inventory "$repo" "$base" "$head" > "$out/inventory.txt"
  local n inv
  n=$(wc -l < "$out/inventory.txt" | tr -d ' ')
  [ "$n" -gt 0 ] || { echo "target-seal: refuse -- empty inventory ($base..$head)" >&2; exit 3; }
  inv=$(sha256 "$out/inventory.txt")

  cat > "$out/SEAL.txt" <<EOF
schema: sol-simplify-review-seal.v1
repo: $(git -C "$repo" rev-parse --show-toplevel)
base_sha: $base
head_sha: $head
inventory_files: $n
target_sha256: $inv
sealed_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
  echo "sealed $n files  base=$base  head=$head  target_sha256=$inv"
}

seal_field() { awk -v k="$2:" '$1==k{print $2}' "$1/SEAL.txt"; }

cmd_verify() {
  local repo="$1" out="$2" expect="${3:-}"
  [ -f "$out/SEAL.txt" ] || { echo "target-seal: no SEAL.txt in $out" >&2; exit 3; }
  local base head inv n
  base=$(seal_field "$out" base_sha); head=$(seal_field "$out" head_sha)
  inv=$(seal_field "$out" target_sha256); n=$(seal_field "$out" inventory_files)

  local recomputed; recomputed=$(mktemp "$out/.inventory.XXXXXX")
  build_inventory "$repo" "$base" "$head" > "$recomputed"
  local now stored
  [ "$(wc -l < "$out/inventory.txt" | tr -d ' ')" = "$n" ] || { echo "FAIL inventory-count: count differs from seal" >&2; exit 4; }
  now=$(sha256 "$recomputed"); stored=$(sha256 "$out/inventory.txt")
  rm -f "$recomputed"

  # Two different failures, named apart on purpose. The first says the stored list was
  # edited; the second says the repository moved under a list that was not.
  [ "$stored" = "$inv" ] || { echo "FAIL inventory-integrity: inventory.txt digests $stored != sealed $inv" >&2; exit 4; }
  [ "$now"    = "$inv" ] || { echo "FAIL inventory-drift: $base..$head now digests $now, sealed $inv" >&2; exit 4; }
  if [ -n "$expect" ]; then
    local e; e=$(git -C "$repo" rev-parse --verify "$expect^{commit}")
    [ "$e" = "$head" ] || { echo "FAIL seal-head-crosscheck: sealed head $head != expected $e" >&2; exit 4; }
  fi
  echo "seal ok  base=$base head=$head files=$n target_sha256=$inv"
}

case "${1:-}" in
  seal)   shift; cmd_seal "$@" ;;
  verify) shift; cmd_verify "$@" ;;
  *) echo "usage: target-seal.sh seal <repo> <base> <head> <outdir> | verify <repo> <outdir> [head]" >&2; exit 2 ;;
esac
