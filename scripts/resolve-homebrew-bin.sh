#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 || "$1" == */* || -z "$1" ]]; then
  printf 'Usage: bash scripts/resolve-homebrew-bin.sh BINARY\n' >&2
  exit 2
fi

binary="$1"
if command -v "$binary" >/dev/null 2>&1; then
  command -v "$binary"
  exit 0
fi

command -v brew >/dev/null 2>&1 || exit 1

formula_prefix="$(brew --prefix "$binary" 2>/dev/null || true)"
candidate="${formula_prefix}/bin/${binary}"
if [[ -n "$formula_prefix" && -x "$candidate" ]]; then
  printf '%s\n' "$candidate"
  exit 0
fi

exit 1
