#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf 'codex-validation-lib.sh requires bash and must be sourced from bash scripts.\n' >&2
  return 2 2>/dev/null || exit 2
fi

dots_script_dir="$(cd -P "${BASH_SOURCE[0]%/*}" && pwd -P)"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE PYTHONPYCACHEPREFIX
unset LD_PRELOAD LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
if [[ -n "${DOTS_TEST_HOME:-}" && ! -e "$dots_script_dir/../.deployment.json" && ! -L "$dots_script_dir/../.deployment.json" \
      && ! -e "$dots_script_dir/../.dots-package.json" && ! -L "$dots_script_dir/../.dots-package.json" ]]; then
  # This exception admits disposable resources with system Python before any
  # caller-selected fixture interpreter can execute. It grants no live route.
  /usr/bin/python3 -B -E -s "$dots_script_dir/admit-hook-fixture.py" '{}' || return $?
  dots_bootstrap_python="${CODEX_VALIDATION_PYTHON:-}"
else
  dots_protected_bin="$(/usr/bin/python3 -I -S -B "$dots_script_dir/validate-hook-toolchain.py")" || return $?
  if [[ ! "$dots_protected_bin" =~ ^/opt/dots-hook-tools/[0-9a-f]{64}/bin$ ]]; then
    printf 'Protected toolchain returned an invalid versioned path\n' >&2
    return 78
  fi
  dots_bootstrap_python="$dots_protected_bin/python3"
fi
if [[ "$dots_bootstrap_python" != /* || ! -f "$dots_bootstrap_python" || ! -x "$dots_bootstrap_python" ]]; then
  printf 'no Python from the admitted fixture or protected toolchain is available\n' >&2
  return 78
fi
CODEX_VALIDATION_PYTHON="$dots_bootstrap_python"
export CODEX_VALIDATION_PYTHON
"$dots_bootstrap_python" -B -E -s "$dots_script_dir/admit-hook-fixture.py" '{}' || return $?

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
