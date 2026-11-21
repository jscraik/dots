#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf '❌ with-writable-tmpdir.sh requires bash. Run: bash scripts/with-writable-tmpdir.sh <command> [args...]\n' >&2
  return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '❌ with-writable-tmpdir.sh is CLI-only; do not source it. Run: bash scripts/with-writable-tmpdir.sh <command> [args...]\n' >&2
  return 2
fi

set -euo pipefail

dots_helper_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_helper_dir/admit-hook-fixture.py" '{}' || exit $?

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/with-writable-tmpdir.sh <command> [args...]

Runs a validation command with TMPDIR set to a known writable repo-local
directory. Use this for validators or tests that call mktemp or Python tempfile
when the ambient sandbox TMPDIR is missing or not writable.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if (( $# == 0 )); then
  usage >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
codex_root="$(cd -- "${script_dir}/.." && pwd -P)"
tmp_base="${CODEX_VALIDATION_TMPDIR_BASE:-${codex_root}/.tmp/validation-tmpdir}"

mkdir -p "${tmp_base}"

if [[ ! -d "${tmp_base}" || ! -w "${tmp_base}" ]]; then
  printf '[with-writable-tmpdir] temp base is not writable: %s\n' "${tmp_base}" >&2
  exit 1
fi

run_tmpdir="$(mktemp -d "${tmp_base}/run.XXXXXX")"
cleanup() {
  rm -rf "${run_tmpdir}"
}
trap cleanup EXIT

export TMPDIR="${run_tmpdir}"
export TMP="${run_tmpdir}"
export TEMP="${run_tmpdir}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${codex_root}/.tmp/uv-cache}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${codex_root}/.tmp/xdg-cache}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${codex_root}/.tmp/pycache}"

mkdir -p "${UV_CACHE_DIR}" "${XDG_CACHE_HOME}" "${PYTHONPYCACHEPREFIX}"

if "$@"; then
  status=0
else
  status=$?
fi

exit "$status"
