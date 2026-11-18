#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf '❌ audit-project-codex-config-overrides.sh requires bash. Run: CODEX_DEV_ROOT=/path/to/dev bash scripts/audit-project-codex-config-overrides.sh [dev-root]\n' >&2
  # shellcheck disable=SC2317
  return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '❌ audit-project-codex-config-overrides.sh is CLI-only; do not source it. Run: CODEX_DEV_ROOT=/path/to/dev bash scripts/audit-project-codex-config-overrides.sh [dev-root]\n' >&2
  return 2
fi

set -euo pipefail
dots_script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_script_dir/admit-hook-fixture.py" '{}' || exit $?

script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

# usage prints usage and help text for the audit-project-codex-config-overrides.sh script.
# It documents the CODEX_DEV_ROOT/DEV_ROOT environment variable, accepted options (--check, --repair, -h/--help),
# usage prints the CLI usage and help text describing the script's purpose, expected environment variables, supported modes (--check, --repair), and option flags.
usage() {
  cat <<'USAGE'
Usage:
  CODEX_DEV_ROOT=/path/to/dev bash scripts/audit-project-codex-config-overrides.sh [--check|--repair] [dev-root]

Audits project-level Codex config files for git projects under DEV_ROOT.
Project-local .codex/config.toml files must not exist; use the global projected
~/.codex/config.toml runtime config instead. Projects should still protect
.codex/config.toml in .gitignore so accidental runtime config files are not
committed.

Options:
  --check     Audit only; do not modify files (default)
  --repair    Remove project-local config files and add .gitignore entries
  -h, --help  Show this help
USAGE
}

MODE="check"

# Root scan path for project-level Codex config projection.
# Preferred override: CODEX_DEV_ROOT=/path/to/dev
# Default when unset: $HOME/dev
DEV_ROOT="${CODEX_DEV_ROOT:-${HOME}/dev}"
CANONICAL_CONFIG="${CODEX_PROJECT_CONFIG_TARGET:-${HOME}/dev/dots/codex/config.toml}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      MODE="check"
      shift
      ;;
    --repair)
      MODE="repair"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      DEV_ROOT="$1"
      shift
      ;;
  esac
done

if [[ ! -d "$DEV_ROOT" ]]; then
  echo "Missing dev root directory: $DEV_ROOT" >&2
  exit 2
fi

DEV_ROOT="$(cd -P "$DEV_ROOT" && pwd -P)"
python3 "$script_dir/admit-hook-fixture.py" "$(jq -cn --arg cwd "$DEV_ROOT" '{cwd:$cwd}')" || exit $?
ALLOWED_LIFEOS_CONFIG="${DEV_ROOT}/lifeOS/.codex/config.toml"

if [[ ! -f "$CANONICAL_CONFIG" ]]; then
  echo "Missing canonical Codex config: $CANONICAL_CONFIG" >&2
  exit 2
fi

source "$script_dir/codex-validation-lib.sh"
python_bin="$(codex_select_validation_python "audit-project-codex-config-overrides")"
canonical_resolved="$("$python_bin" -I -B -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$CANONICAL_CONFIG")"

declare -a git_roots=()
declare -a failures=()
declare -a repaired=()
declare -a skipped=()

discover_git_roots() {
  if command -v fd >/dev/null 2>&1; then
    fd -HI '^\.git$' "$DEV_ROOT" \
      --exclude node_modules \
      --exclude .pnpm \
      --exclude .uv-cache \
      --exclude .cache \
      --exclude .playwright-tmp \
      --exclude tmp \
      --exclude dist \
      --exclude _site \
      2>/dev/null
  else
    find "$DEV_ROOT" \
      \( -path '*/node_modules' -o -path '*/.pnpm' -o -path '*/.uv-cache' -o -path '*/.cache' -o -path '*/.playwright-tmp' -o -path '*/tmp' -o -path '*/dist' -o -path '*/_site' \) -prune -o \
      -name .git \( -type d -o -type f \) -print 2>/dev/null
  fi
}

# gitignore_has_entry checks whether the specified .gitignore file exists and contains a line exactly matching the anchored pattern `/?\.codex/config\.toml`; it exits with status 0 if the entry is present, nonzero otherwise.
gitignore_has_entry() {
  local gitignore_path="$1"
  [[ -f "$gitignore_path" ]] || return 1
  grep -Eq '^/?\.codex/config\.toml$' "$gitignore_path" 2>/dev/null
}

# append_gitignore_entry ensures the given .gitignore ends with a newline when non-empty and appends `.codex/config.toml`, creating the file if it does not exist.
append_gitignore_entry() {
  local gitignore_path="$1"
  "$python_bin" "$script_dir/project_metadata.py" ensure-ignore "$(dirname "$gitignore_path")"
}

# remove_project_config removes the project-local Codex config file in repair mode
# and records a failure in check mode. Project-local config.toml is not allowed
# because it overrides the global projected ~/.codex/config.toml runtime config.
remove_project_config() {
  local project_root="$1"
  local project_config="$2"
  local config_display="$3"

  if [[ "$MODE" == "repair" ]]; then
    if "$python_bin" "$script_dir/project_metadata.py" remove-config "$project_root"; then
      repaired+=("${project_root}: removed project-local ${config_display}")
      return 0
    fi
    failures+=("${project_root}: failed to remove project-local ${config_display}")
    return 1
  fi

  failures+=("${project_root}: ${config_display} exists; use global ~/.codex/config.toml instead")
  return 1
}

is_allowed_project_config() {
  [[ "$1" == "$ALLOWED_LIFEOS_CONFIG" ]] || {
    [[ -n "${DOTS_PROJECT_CONFIG_EXCEPTION:-}" && "$1" == "$DOTS_PROJECT_CONFIG_EXCEPTION" ]]
  }
}

validate_allowed_project_config() {
  "$python_bin" -I -B - "$script_dir/validate-codex-config.py" "$1" <<'PY'
import importlib.util
import sys
from pathlib import Path

validator_path = Path(sys.argv[1])
config_path = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("codex_config_validator", validator_path)
if spec is None or spec.loader is None:
    print(f"unable to load validator: {validator_path}", file=sys.stderr)
    raise SystemExit(1)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
errors = module.validate_allowed_project_local_config(config_path)
for error in errors:
    print(error, file=sys.stderr)
raise SystemExit(1 if errors else 0)
PY
}

# audit_project ensures a project has no local .codex/config.toml and protects
# that path in .gitignore. In repair mode it removes local config files and
# records any .gitignore updates in the global `failures` and `repaired` arrays.
audit_project() {
  local project_root="$1"
  local project_config="${project_root}/.codex/config.toml"
  local gitignore_path="${project_root}/.gitignore"
  local resolved=""
  local config_display=""
  local project_failed=0

  if is_allowed_project_config "$project_config" && [[ -L "$project_config" ]]; then
    config_display=".codex/config.toml (allowlisted LifeOS exception) symlink"
    if [[ "$MODE" == "repair" ]]; then
      if ! remove_project_config "$project_root" "$project_config" "$config_display"; then
        project_failed=1
      fi
    else
      failures+=("${project_root}: ${config_display} must be a regular file")
      project_failed=1
    fi
  elif is_allowed_project_config "$project_config" && [[ -e "$project_config" ]]; then
    config_display=".codex/config.toml (allowlisted LifeOS exception)"
    if ! validate_allowed_project_config "$project_config"; then
      remove_project_config "$project_root" "$project_config" "$config_display" || project_failed=1
    fi
  elif [[ -L "$project_config" ]]; then
    resolved="$("$python_bin" -I -B -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$project_config")"
    config_display=".codex/config.toml symlink to ${resolved}"
    if [[ "$resolved" == "$canonical_resolved" ]]; then
      config_display=".codex/config.toml symlink to full user config"
    fi
    if ! remove_project_config "$project_root" "$project_config" "$config_display"; then
      project_failed=1
    fi
  elif [[ -e "$project_config" ]]; then
    if ! remove_project_config "$project_root" "$project_config" ".codex/config.toml"; then
      project_failed=1
    fi
  fi

  if ! gitignore_has_entry "$gitignore_path"; then
    if [[ "$MODE" == "repair" ]]; then
      if append_gitignore_entry "$gitignore_path"; then
        repaired+=("${project_root}: added .codex/config.toml to .gitignore")
      else
        failures+=("${project_root}: failed to add .codex/config.toml to .gitignore")
        project_failed=1
      fi
    else
      failures+=("${project_root}: .gitignore does not protect .codex/config.toml")
      project_failed=1
    fi
  fi

  return "$project_failed"
}

while IFS= read -r git_path; do
  [[ -n "$git_path" ]] || continue
  git_path="${git_path%/}"
  project_root="${git_path%/.git}"
  [[ -d "$project_root" ]] || continue
  git_roots+=("$project_root")
done < <(discover_git_roots | sort)

if [[ "${#git_roots[@]}" -eq 0 ]]; then
  echo "SKIP: no git projects found under $DEV_ROOT"
  exit 0
fi

for project_root in "${git_roots[@]}"; do
  audit_project "$project_root" || true
done

if [[ "${#failures[@]}" -eq 0 ]]; then
  echo "OK: ${#git_roots[@]} git project(s) have no project-local Codex config.toml files"
  if [[ "${#repaired[@]}" -gt 0 ]]; then
    echo "Repaired:"
    for item in "${repaired[@]}"; do
      echo "  - $item"
    done
  fi
  exit 0
fi

echo "FAIL: project-level .codex/config.toml drift under $DEV_ROOT" >&2
for item in "${failures[@]}"; do
  echo "  - $item" >&2
done
echo "Expected projects to use the global projected ~/.codex/config.toml only; the exact LifeOS exception is allowlisted." >&2
echo "Repair with: CODEX_DEV_ROOT=\"$DEV_ROOT\" bash scripts/audit-project-codex-config-overrides.sh --repair" >&2
exit 1
