#!/bin/bash -p

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf '❌ audit-codex-symlinks.sh requires bash. Run: /bin/bash -p scripts/audit-codex-symlinks.sh [options]\n' >&2
  # shellcheck disable=SC2317
  return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '❌ audit-codex-symlinks.sh is CLI-only; do not source it. Run: /bin/bash -p scripts/audit-codex-symlinks.sh [options]\n' >&2
  return 2
fi

set -euo pipefail
PATH='/usr/bin:/bin:/usr/sbin:/sbin'
readonly PATH
export PATH
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONINSPECT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=codex/scripts/codex-validation-lib.sh
. "${SCRIPT_DIR}/codex-validation-lib.sh"
POLICY_ROOT="$("$dots_bootstrap_python" -B -E -s "$SCRIPT_DIR/migration_scope.py" --source-root)"
REPO_ROOT="$(dirname "$POLICY_ROOT")"

declare -a codex_homes=()
legacy_skills_canon=""
legacy_plugins_canon=""

usage() {
  cat <<'USAGE'
Usage:
  /bin/bash -p codex/scripts/audit-codex-symlinks.sh [--codex-home PATH]...

Options:
  --codex-home PATH  Codex home to audit (repeatable). Defaults to ~/.codex
  -h, --help         Show help

Legacy positional compatibility:
  audit-codex-symlinks.sh [CANON_ROOT] [CODEX_HOME] [IGNORED_SKILLS_CANON] [PLUGINS_CANON]
  Standalone skills are not Configs projections; the third argument is ignored.
USAGE
}

append_home_unique() {
  local candidate="$1"
  local existing=""
  [[ -n "$candidate" ]] || return 0
  if [[ ${#codex_homes[@]} -gt 0 ]]; then
    for existing in "${codex_homes[@]}"; do
      [[ "$existing" == "$candidate" ]] && return 0
    done
  fi
  codex_homes+=("$candidate")
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex-home)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --codex-home" >&2
        usage
        exit 2
      fi
      append_home_unique "$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
    *)
      # Legacy positional compatibility: [CANON_ROOT] [CODEX_HOME] [SKILLS_CANON] [PLUGINS_CANON]
      legacy_canon_root="${1:-}"
      legacy_codex_home="${2:-}"
      legacy_skills_canon="${3:-}"
      legacy_plugins_canon="${4:-}"
      if [[ -n "$legacy_canon_root" && "$legacy_canon_root" != "${REPO_ROOT}/codex" ]]; then
        echo "warning: CANON_ROOT positional argument is deprecated and ignored; using ${REPO_ROOT}/codex" >&2
      fi
      if [[ -n "$legacy_codex_home" ]]; then
        append_home_unique "$legacy_codex_home"
      fi
      break
      ;;
  esac
done

if [[ ${#codex_homes[@]} -eq 0 ]]; then
  append_home_unique "${HOME}/.codex"
fi

validation_python="$(codex_select_toml_python "codex-symlink-auditor")"
validation_python="$(command -v "$validation_python")"
cmd=(/bin/bash -p "${REPO_ROOT}/scripts/link-configs.sh" --check --scope codex)
for home in "${codex_homes[@]}"; do
  cmd+=(--codex-home "$home")
done

echo "Auditing Codex projection via ${REPO_ROOT}/scripts/link-configs.sh"
if [[ -n "$legacy_skills_canon" ]]; then
  echo "warning: SKILLS_CANON is retired and ignored; standalone skills are not projected" >&2
fi
if [[ -n "$legacy_plugins_canon" ]]; then
  CODEX_VALIDATION_PYTHON="$validation_python" PLUGINS_CANON="$legacy_plugins_canon" "${cmd[@]}"
else
  CODEX_VALIDATION_PYTHON="$validation_python" "${cmd[@]}"
fi
