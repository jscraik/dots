#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf 'codex-validation-lib.sh requires bash and must be sourced from bash scripts.\n' >&2
  return 2 2>/dev/null || exit 2
fi

dots_script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_script_dir/admit-hook-fixture.py" '{}' || return $?

_codex_python_candidates() {
  local -a candidates=()

  # Hook bootstrap supplies a verified versioned payload. Never fall back to
  # user-writable interpreters if this protected runtime becomes unavailable.
  if [[ "${CODEX_VALIDATION_PYTHON:-}" == /opt/dots-hook-tools/*/bin/python3 ]]; then
    printf '%s\n' "$CODEX_VALIDATION_PYTHON"
    return
  fi

  if [[ -n "${CODEX_VALIDATION_PYTHON:-}" ]]; then
    candidates+=("${CODEX_VALIDATION_PYTHON}")
  fi
  candidates+=("${HOME}/.venvs/pyyaml/bin/python")
  candidates+=("python3")
  candidates+=("${HOME}/.local/share/mise/installs/python/latest/bin/python")

  printf '%s\n' "${candidates[@]}"
}

codex_select_validation_python() {
  local label="${1:-codex-validation}"
  local candidate
  local script_dir
  local wrapper
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

  if [[ "${CODEX_VALIDATION_PYTHON:-}" != /opt/dots-hook-tools/*/bin/python3 ]] && command -v uv >/dev/null 2>&1; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    wrapper="${script_dir}/codex-validation-python-uv.sh"
    if "${wrapper}" - <<'PY' >/dev/null 2>&1; then
try:
    import tomllib
except ModuleNotFoundError:
    import tomli
import yaml
PY
      printf '%s\n' "${wrapper}"
      return
    fi
  fi

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
