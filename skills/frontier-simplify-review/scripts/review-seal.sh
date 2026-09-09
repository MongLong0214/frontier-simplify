#!/bin/sh
set -eu

usage() {
  echo "usage:" >&2
  echo "  review-seal.sh seal INVENTORY BASE_SHA ROUND1_HEAD_SHA" >&2
  echo "  review-seal.sh verify INVENTORY EXPECTED_SHA256 ROUND1_HEAD_SHA [ROUND2_HEAD_SHA]" >&2
  exit 2
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$1" | awk '{print $NF}'
  else
    echo "no SHA-256 implementation found" >&2
    exit 2
  fi
}

case "${1-}" in
  seal)
    [ "$#" -eq 4 ] || usage
    inventory=$2
    base=$(git rev-parse "$3^{commit}")
    round1=$(git rev-parse "$4^{commit}")
    checkout=$(git rev-parse HEAD)

    [ -f "$inventory" ] || {
      echo "inventory not found: $inventory" >&2
      exit 1
    }
    [ "$checkout" = "$round1" ] || {
      echo "checkout is not ROUND1_HEAD_SHA" >&2
      exit 1
    }
    git merge-base --is-ancestor "$base" "$round1" || {
      echo "BASE_SHA is not an ancestor of ROUND1_HEAD_SHA" >&2
      exit 1
    }

    echo "review_protocol=frontier-simplify-review-v1"
    echo "inventory_sha256=$(sha256_file "$inventory")"
    echo "base_sha=$base"
    echo "round1_head_sha=$round1"
    ;;

  verify)
    [ "$#" -eq 4 ] || [ "$#" -eq 5 ] || usage
    inventory=$2
    expected=$3
    round1=$(git rev-parse "$4^{commit}")
    round2=$(git rev-parse "${5:-HEAD}^{commit}")
    checkout=$(git rev-parse HEAD)

    [ -f "$inventory" ] || {
      echo "inventory not found: $inventory" >&2
      exit 1
    }
    [ "$(sha256_file "$inventory")" = "$expected" ] || {
      echo "inventory digest mismatch" >&2
      exit 1
    }
    [ "$checkout" = "$round2" ] || {
      echo "checkout is not ROUND2_HEAD_SHA" >&2
      exit 1
    }
    git merge-base --is-ancestor "$round1" "$round2" || {
      echo "ROUND1_HEAD_SHA is not an ancestor of ROUND2_HEAD_SHA" >&2
      exit 1
    }

    echo "inventory_integrity=VERIFIED"
    echo "inventory_sha256=$expected"
    echo "round1_head_sha=$round1"
    echo "round2_head_sha=$round2"
    ;;

  *)
    usage
    ;;
esac
