#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf 'codex-validation-lib.sh requires bash and must be sourced from bash scripts.\n' >&2
  return 2 2>/dev/null || exit 2
fi

dots_script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
dots_bootstrap_python="${CODEX_VALIDATION_PYTHON:-}"
if [[ -z "$dots_bootstrap_python" ]]; then
  # Inspect only existing configured installation roots, never inherited
  # PATH shims or executable mise configuration.
  for dots_candidate in "${HOME}/.venvs/pyyaml/bin/python" "${HOME}"/.local/share/mise/installs/python/*/bin/python3 /usr/bin/python3; do
    [[ -f "$dots_candidate" && -x "$dots_candidate" ]] || continue
    if "$dots_candidate" -I -B -c 'import sys, tomllib; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      dots_bootstrap_python="$dots_candidate"
      break
    fi
  done
fi
if [[ "$dots_bootstrap_python" != /* || ! -f "$dots_bootstrap_python" || ! -x "$dots_bootstrap_python" ]]; then
  printf 'Validation bootstrap requires an absolute executable Python.\n' >&2
  return 78
fi
if ! "$dots_bootstrap_python" -I -B -c 'import sys, tomllib; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
  printf 'Validation bootstrap requires a configured Python 3.12 or newer with tomllib.\n' >&2
  return 78
fi
"$dots_bootstrap_python" -B -E -s "$dots_script_dir/admit-hook-fixture.py" '{}' || return $?
# Nested selectors must retain the interpreter that passed bootstrap admission.
CODEX_VALIDATION_PYTHON="$dots_bootstrap_python"
export CODEX_VALIDATION_PYTHON

_codex_python_candidates() {
  printf '%s\n' "$dots_bootstrap_python"
}

codex_select_validation_python() {
  local label="${1:-codex-validation}"
  local candidate
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    if ! command -v "${candidate}" >/dev/null 2>&1; then
      continue
    fi
    if "${candidate}" -I -B - <<'PY' >/dev/null 2>&1; then
try:
    import tomllib
except ModuleNotFoundError:
    import tomli
import yaml
PY
      printf '%s\n' "${candidate}"
      return
    fi
  done < <(_codex_python_candidates)

  printf '[%s] no Python with tomllib/tomli and PyYAML available\n' "${label}" >&2
  return 1
}

codex_select_toml_python() {
  local label="${1:-codex-toml-validation}"
  local candidate
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    if ! command -v "${candidate}" >/dev/null 2>&1; then
      continue
    fi
    if "${candidate}" -I -B - <<'PY' >/dev/null 2>&1; then
import tomllib
PY
      printf '%s\n' "${candidate}"
      return
    fi
  done < <(_codex_python_candidates)

  printf '[%s] no Python with stdlib tomllib available\n' "${label}" >&2
  return 1
}
