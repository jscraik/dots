#!/bin/bash -p
# Standalone entrypoint: /bin/bash -p scripts/link-configs.sh
# A caller may instead supply an allowlisted environment (the packaged installer does).
# Unsetting below protects children; Bash reads BASH_ENV before this file starts.
set -euo pipefail

# Projector children use only root-controlled system lookup directories. The
# packaged installer supplies its already-running Python by absolute path.
PATH="/usr/bin:/bin:/usr/sbin:/sbin"
readonly PATH
export PATH
unset BASH_ENV CDPATH ENV PYTHONHOME PYTHONINSPECT PYTHONPATH PYTHONSTARTUP
unset LD_PRELOAD LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
PYTHONNOUSERSITE=1
readonly PYTHONNOUSERSITE
export PYTHONNOUSERSITE

# Fixture admission remains strict. A packaged context has separate validation.
dots_package_root="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
validate_projector_python() {
  if [[ "$1" != /* || ! -f "$1" || ! -x "$1" ]]; then
    printf 'FAIL  projector requires an absolute executable Python\n' >&2
    exit 78
  fi
  if ! "$1" -I -S -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    printf 'FAIL  projector requires Python 3.9 or later\n' >&2
    exit 78
  fi
}

if [[ -f "$dots_package_root/codex/.deployment.json" ]]; then
  protected_bin="$(/usr/bin/python3 -I -S -B "$dots_package_root/codex/scripts/validate-hook-toolchain.py")"
  if [[ ! "$protected_bin" =~ ^/opt/dots-hook-tools/[0-9a-f]{64}/bin$ ]]; then
    printf 'FAIL  protected toolchain returned an invalid versioned path\n' >&2
    exit 78
  fi
  PROJECTOR_PYTHON="$protected_bin/python3"
elif [[ "${DOTS_PROJECTION_FIXTURE:-}" == "full-policy-v1" && -n "${CODEX_VALIDATION_PYTHON:-}" ]]; then
  /usr/bin/python3 -B -E -s "$dots_package_root/codex/scripts/admit-hook-fixture.py" '{}'
  PROJECTOR_PYTHON="$CODEX_VALIDATION_PYTHON"
else
  PROJECTOR_PYTHON="/usr/bin/python3"
fi
validate_projector_python "$PROJECTOR_PYTHON"

DEPLOYMENT_STATE=""
if [[ -f "$dots_package_root/codex/.deployment.json" ]]; then
  "$PROJECTOR_PYTHON" "$dots_package_root/codex/scripts/deployment_scope.py"
  DEPLOYMENT_STATE="$("$PROJECTOR_PYTHON" "$dots_package_root/codex/scripts/deployment_scope.py" --state-dir)"
else
"$PROJECTOR_PYTHON" -I -S - "$HOME" <<'PYHOME'
import os
from pathlib import Path
import pwd
import sys
home = Path(sys.argv[1])
roots = {Path('/tmp').resolve(), Path('/private/tmp').resolve()}
if (not home.is_absolute() or not home.is_dir() or '..' in home.parts
        or home.is_relative_to(Path(pwd.getpwuid(os.getuid()).pw_dir).resolve())
        or any(p.is_symlink() for p in (home, *home.parents))
        or not any(home.is_relative_to(root) and home != root for root in roots)):
    raise SystemExit('Migration projector requires an existing disposable HOME')
if os.environ.get('DOTS_PROJECTION_FIXTURE') != 'full-policy-v1':
    for parent, dirs, files in os.walk(home, followlinks=False):
        if any((Path(parent) / name).is_symlink() for name in dirs + files):
            raise SystemExit('Migration projector refuses symlinks in disposable HOME')
PYHOME
fi
readonly PROJECTOR_PYTHON
unset DOTS_PROJECTOR_PYTHON

MODE="check"
DRY_RUN=0
SCOPE="all"
CODEX_HOMES_RAW="${CODEX_HOMES:-}"
declare -a CODEX_HOME_LIST=()

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECTION_SOURCE_ROOT="${REPO_ROOT}"
PROJECTION_MAP=""
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
BACKUP_ROOT="${HOME}/.config-symlink-backups/${STAMP}"
if [[ -n "$DEPLOYMENT_STATE" ]]; then
  BACKUP_ROOT="$DEPLOYMENT_STATE/publisher-backups/links-$STAMP"
fi
BACKUP_ROOT_READY=0

PLUGINS_CANON_RESOLVED=""

resolve_projection_source_root() {
  if [[ -n "$DEPLOYMENT_STATE" ]]; then
    "$PROJECTOR_PYTHON" "$REPO_ROOT/codex/scripts/deployment_scope.py" >/dev/null
    printf '%s\n' "$REPO_ROOT"
    return 0
  fi
  local common_dir=""
  local common_dir_abs=""
  local common_checkout=""

  if ! common_dir="$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null)"; then
    printf 'FAIL  unable to resolve Git common directory for projection source: %s\n' "$REPO_ROOT" >&2
    return 78
  fi

  common_dir_abs="$("$PROJECTOR_PYTHON" - "$REPO_ROOT" "$common_dir" <<'PY'
import os
import sys

repo_root, common_dir = sys.argv[1:]
if not os.path.isabs(common_dir):
    common_dir = os.path.join(repo_root, common_dir)
print(os.path.realpath(common_dir))
PY
)"
  common_checkout="$(dirname "$common_dir_abs")"

  if [[ "$common_dir_abs" != "$(resolve_realpath "${REPO_ROOT}/.git")" ]]; then
    if [[ ! -d "$common_checkout" ]] ||
       [[ "$(git -C "$common_checkout" rev-parse --show-toplevel 2>/dev/null || true)" != "$common_checkout" ]]; then
      printf 'FAIL  shared checkout for projection source is unavailable: %s\n' "$common_checkout" >&2
      return 78
    fi
    printf '%s\n' "$common_checkout"
    return 0
  fi

  printf '%s\n' "$REPO_ROOT"
}

ok_count=0
fail_count=0
skip_count=0
plan_count=0

usage() {
  cat <<'USAGE'
Usage:
  /bin/bash -p scripts/link-configs.sh [--check|--repair] [--dry-run] [--scope all|codex] [--codex-home PATH]... [--help]

Modes:
  --check         Validate projection state without modifying files (default)
  --repair        Reconcile projection state by creating/fixing symlinks/copies

Options:
  --dry-run       Print planned repair actions without modifying files
  --scope         Projection scope: all (default) or codex
  --codex-home    Codex home to project/audit (repeatable). Defaults to ~/.codex
  --help          Show this help

Environment:
  CODEX_HOMES     Optional comma/colon-delimited Codex homes (used when --codex-home is not provided)
  PLUGINS_CANON   Optional override for ~/.codex/plugins source
  SKILLS_CANON    Migration only: pass the original custom skills source to archive its retired Configs alias

Standalone skills are not projected by Configs. Preserve ~/.agents/skills and
provider-managed skills; installation belongs to the selected SDK/runtime lane.
USAGE
}

log() {
  printf '%s\n' "$*"
}

mark_ok() {
  ok_count=$((ok_count + 1))
  log "OK    $*"
}

mark_fail() {
  fail_count=$((fail_count + 1))
  log "FAIL  $*"
}

mark_skip() {
  skip_count=$((skip_count + 1))
  log "SKIP  $*"
}

mark_plan() {
  plan_count=$((plan_count + 1))
  log "PLAN  $*"
}

# codex_home_count prints CODEX_HOME_LIST's length in a way that is safe on
# macOS's Bash 3.2 with `set -u`, where empty array expansion is an error.
codex_home_count() {
  local count=""
  set +u
  count="${#CODEX_HOME_LIST[@]}"
  set -u
  printf '%s\n' "$count"
}

# append_codex_home_unique adds a non-empty candidate path to CODEX_HOME_LIST if it is not already present.
append_codex_home_unique() {
  local candidate="$1"
  local existing=""
  [[ -n "$candidate" ]] || return 0
  if [[ "$(codex_home_count)" -gt 0 ]]; then
    for existing in "${CODEX_HOME_LIST[@]}"; do
      [[ "$existing" == "$candidate" ]] && return 0
    done
  fi
  CODEX_HOME_LIST+=("$candidate")
}

# resolve_default_plugins_canon prints the first existing default plugins canon directory found under the repository parent or the user's custom path (PLUGIN_CANON_FALLBACK env var) and returns non-zero if no candidate exists.
resolve_default_plugins_canon() {
  local repo_parent="${REPO_ROOT%/*}"
  local candidate=""

  for candidate in \
    "${repo_parent}/Agent-Skills/Plugins" \
    "${repo_parent}/agent-skills/plugins" \
    "${PLUGIN_CANON_FALLBACK:-}"
  do
    if [[ -d "$candidate" ]]; then
      # Log when using the fallback path so users are aware
      if [[ "$candidate" == "${PLUGIN_CANON_FALLBACK:-}" && -n "${PLUGIN_CANON_FALLBACK:-}" ]]; then
        log "INFO  Using non-standard plugin path from PLUGIN_CANON_FALLBACK: $candidate"
      fi
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

# ensure_backup_root ensures the directory in $BACKUP_ROOT exists and sets BACKUP_ROOT_READY=1 so the backup root is created only once.
ensure_backup_root() {
  if [[ "$BACKUP_ROOT_READY" -eq 0 ]]; then
    mkdir -p "$BACKUP_ROOT"
    BACKUP_ROOT_READY=1
  fi
}

resolve_tokens_from_map() {
  local section="$1"
  local codex_home="$2"

  "$PROJECTOR_PYTHON" - "$PROJECTION_MAP" "$section" "$REPO_ROOT" "$PROJECTION_SOURCE_ROOT" "$HOME" "$codex_home" "$PLUGINS_CANON_RESOLVED" <<'PY'
import json
import os
import sys

map_path, section, repo_root, projection_root, home, codex_home, plugins = sys.argv[1:]

with open(map_path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

entries = data.get(section, [])

def expand(value: str) -> str:
    replacements = {
        "{HOME}": home,
        "{CODEX_HOME}": codex_home,
        "{PLUGINS_CANON}": plugins,
    }
    rendered = value
    for token, replacement in replacements.items():
        rendered = rendered.replace(token, replacement)
    return rendered

for item in entries:
    name = str(item.get("name", ""))
    # Linked worktrees can still read a pre-retirement primary map. Never let
    # that historical row reinstate standalone skill installation ownership.
    if section == "codex_projection" and name == "skills":
        continue
    source = expand(str(item.get("source", "")))
    target = expand(str(item.get("target", "")))
    optional = "1" if bool(item.get("optional", False)) else "0"
    strategy = str(item.get("strategy", "symlink"))

    candidate_source = source
    if source and not os.path.isabs(source):
        candidate_source = os.path.join(repo_root, source)
        source = os.path.join(projection_root, source)

    print("\x1f".join([name, candidate_source, source, target, optional, strategy]))
PY
}

resolve_realpath() {
  "$PROJECTOR_PYTHON" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
}

PROJECTION_SOURCE_ROOT="$(resolve_projection_source_root)"
PROJECTION_MAP="${PROJECTION_SOURCE_ROOT}/codex/projection-map.json"

validate_candidate_source() {
  local name="$1"
  local candidate_source="$2"
  local optional="$3"

  if [[ -n "$candidate_source" && -e "$candidate_source" ]]; then
    return 0
  fi
  if [[ "$optional" == "1" ]]; then
    mark_skip "${name}: optional candidate source missing (${candidate_source:-<unset>})"
    return 1
  fi
  mark_fail "${name}: candidate source missing (${candidate_source:-<unset>})"
  return 1
}

link_matches_source() {
  local source_abs="$1"
  local target_abs="$2"
  local resolved_source=""
  local resolved_target=""

  [[ -L "$target_abs" ]] || return 1

  resolved_source="$(resolve_realpath "$source_abs")"
  resolved_target="$(resolve_realpath "$target_abs")"
  [[ "$resolved_source" == "$resolved_target" ]] && return 0
  "$PROJECTOR_PYTHON" - "$resolved_source" "$resolved_target" <<'PYCASE'
import os
import sys

source, target = sys.argv[1:]
try:
    matches = source.casefold() == target.casefold() and os.path.samefile(source, target)
except OSError:
    matches = False
raise SystemExit(0 if matches else 1)
PYCASE
}

check_projection_link() {
  local name="$1"
  local source_abs="$2"
  local target_abs="$3"
  local optional="$4"

  if [[ -z "$source_abs" || ! -e "$source_abs" ]]; then
    if [[ "$optional" == "1" ]]; then
      mark_skip "${name}: optional source missing (${source_abs:-<unset>})"
      return 0
    fi
    mark_fail "${name}: source missing (${source_abs:-<unset>})"
    return 1
  fi

  if link_matches_source "$source_abs" "$target_abs"; then
    mark_ok "${name}: ${target_abs} -> $(readlink "$target_abs")"
    return 0
  fi

  if [[ -L "$target_abs" ]]; then
    mark_fail "${name}: symlink drift ${target_abs} -> $(readlink "$target_abs") (expected ${source_abs})"
  elif [[ -e "$target_abs" ]]; then
    mark_fail "${name}: target is not a symlink (${target_abs})"
  else
    mark_fail "${name}: missing target (${target_abs})"
  fi
  return 1
}

backup_existing_target() {
  local target_abs="$1"
  local backup_path="${BACKUP_ROOT}${target_abs}"

  ensure_backup_root
  mkdir -p "$(dirname "$backup_path")"
  mv "$target_abs" "$backup_path"
  log "backup: ${target_abs} -> ${backup_path}"
}

repair_projection_link() {
  local name="$1"
  local source_abs="$2"
  local target_abs="$3"
  local optional="$4"

  if [[ -z "$source_abs" || ! -e "$source_abs" ]]; then
    if [[ "$optional" == "1" ]]; then
      mark_skip "${name}: optional source missing (${source_abs:-<unset>})"
      return 0
    fi
    mark_fail "${name}: source missing (${source_abs:-<unset>})"
    return 1
  fi

  if link_matches_source "$source_abs" "$target_abs"; then
    mark_ok "${name}: already linked ${target_abs}"
    return 0
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    if [[ -L "$target_abs" ]]; then
      mark_plan "replace symlink ${target_abs} -> ${source_abs}"
    elif [[ -e "$target_abs" ]]; then
      mark_plan "replace existing target ${target_abs} -> ${source_abs}"
    else
      mark_plan "create link ${target_abs} -> ${source_abs}"
    fi
    return 0
  fi

  mkdir -p "$(dirname "$target_abs")"

  if [[ -L "$target_abs" ]]; then
    rm "$target_abs"
  elif [[ -e "$target_abs" ]]; then
    backup_existing_target "$target_abs"
  fi

  ln -s "$source_abs" "$target_abs"

  if link_matches_source "$source_abs" "$target_abs"; then
    mark_ok "${name}: linked ${target_abs} -> ${source_abs}"
    return 0
  fi

  mark_fail "${name}: failed to link ${target_abs} -> ${source_abs}"
  return 1
}

copy_contains_source_prefix() {
  local source_abs="$1"
  local target_abs="$2"

  [[ -f "$target_abs" && ! -L "$target_abs" ]] || return 1
  "$PROJECTOR_PYTHON" - "$source_abs" "$target_abs" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_bytes()
target = Path(sys.argv[2]).read_bytes()
raise SystemExit(0 if target.startswith(source) else 1)
PY
}

check_projection_copy() {
  local name="$1"
  local source_abs="$2"
  local target_abs="$3"
  local optional="$4"

  if [[ -z "$source_abs" || ! -e "$source_abs" ]]; then
    if [[ "$optional" == "1" ]]; then
      mark_skip "${name}: optional source missing (${source_abs:-<unset>})"
      return 0
    fi
    mark_fail "${name}: source missing (${source_abs:-<unset>})"
    return 1
  fi

  if copy_contains_source_prefix "$source_abs" "$target_abs"; then
    mark_ok "${name}: ${target_abs} contains canonical prefix from ${source_abs}"
    return 0
  fi

  if [[ -L "$target_abs" ]]; then
    mark_fail "${name}: target must be a real copied file, not a symlink (${target_abs} -> $(readlink "$target_abs"))"
  elif [[ -e "$target_abs" ]]; then
    mark_fail "${name}: copied target drift (${target_abs} does not start with ${source_abs})"
  else
    mark_fail "${name}: missing target (${target_abs})"
  fi
  return 1
}

check_projection_runtime_copy() {
  local name="$1"
  local source_abs="$2"
  local target_abs="$3"
  local optional="$4"
  local check_output=""

  if [[ -z "$source_abs" || ! -e "$source_abs" ]]; then
    if [[ "$optional" == "1" ]]; then
      mark_skip "${name}: optional source missing (${source_abs:-<unset>})"
      return 0
    fi
    mark_fail "${name}: source missing (${source_abs:-<unset>})"
    return 1
  fi

  if [[ -L "$target_abs" ]]; then
    mark_fail "${name}: mutable runtime target must be a regular file, not a symlink (${target_abs} -> $(readlink "$target_abs"))"
    return 1
  elif [[ -f "$target_abs" ]]; then
    if ! check_output="$("$PROJECTOR_PYTHON" "$(dirname "$source_abs")/scripts/repair-runtime-config-drift.py" \
      --config-path "$target_abs" --check --json 2>&1)"; then
      mark_fail "${name}: runtime config differs from canonical policy (${target_abs}): ${check_output}"
      return 1
    fi
    mark_ok "${name}: runtime copy matches canonical policy at ${target_abs}"
  elif [[ -e "$target_abs" ]]; then
    mark_fail "${name}: mutable runtime target must be a regular file (${target_abs})"
    return 1
  else
    mark_fail "${name}: missing mutable runtime copy (${target_abs})"
    return 1
  fi
  return 0
}

repair_projection_copy() {
  local name="$1"
  local source_abs="$2"
  local target_abs="$3"
  local optional="$4"

  if [[ -z "$source_abs" || ! -e "$source_abs" ]]; then
    if [[ "$optional" == "1" ]]; then
      mark_skip "${name}: optional source missing (${source_abs:-<unset>})"
      return 0
    fi
    mark_fail "${name}: source missing (${source_abs:-<unset>})"
    return 1
  fi

  if copy_contains_source_prefix "$source_abs" "$target_abs"; then
    mark_ok "${name}: already copied ${target_abs}"
    return 0
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    if [[ -L "$target_abs" ]]; then
      mark_plan "replace symlink with copy ${target_abs} <= ${source_abs}"
    elif [[ -e "$target_abs" ]]; then
      mark_plan "replace existing copy target ${target_abs} <= ${source_abs}"
    else
      mark_plan "create copy ${target_abs} <= ${source_abs}"
    fi
    return 0
  fi

  mkdir -p "$(dirname "$target_abs")"

  if [[ -L "$target_abs" ]]; then
    rm "$target_abs"
  elif [[ -e "$target_abs" ]]; then
    backup_existing_target "$target_abs"
  fi

  cp -p "$source_abs" "$target_abs"

  if copy_contains_source_prefix "$source_abs" "$target_abs"; then
    mark_ok "${name}: copied ${target_abs} <= ${source_abs}"
    return 0
  fi

  mark_fail "${name}: failed to copy ${target_abs} <= ${source_abs}"
  return 1
}

repair_projection_runtime_copy() {
  local name="$1"
  local source_abs="$2"
  local target_abs="$3"
  local optional="$4"

  if [[ -z "$source_abs" || ! -e "$source_abs" ]]; then
    if [[ "$optional" == "1" ]]; then
      mark_skip "${name}: optional source missing (${source_abs:-<unset>})"
      return 0
    fi
    mark_fail "${name}: source missing (${source_abs:-<unset>})"
    return 1
  fi

  if [[ -f "$target_abs" && ! -L "$target_abs" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      local check_output=""
      if ! check_output="$("$PROJECTOR_PYTHON" "$(dirname "$source_abs")/scripts/repair-runtime-config-drift.py" \
        --config-path "$target_abs" --check --json 2>&1)"; then
        if "$PROJECTOR_PYTHON" -c 'import json,sys
try:
    value = json.load(sys.stdin)
except (ValueError, TypeError):
    raise SystemExit(1)
raise SystemExit(not (isinstance(value, dict) and value.get("status") == "fail"))' \
          <<<"$check_output"; then
          mark_plan "reconcile runtime config from canonical source ${target_abs}"
        else
          mark_fail "${name}: runtime config reconciliation would be blocked (${target_abs}): ${check_output}"
          return 1
        fi
      fi
      return 0
    fi
    local backup_args=(--json)
    if [[ -n "$DEPLOYMENT_STATE" ]]; then
      backup_args+=(--backup-path "$DEPLOYMENT_STATE/publisher-backups/config-$STAMP.toml")
    fi
    if ! "$PROJECTOR_PYTHON" "$(dirname "$source_abs")/scripts/repair-runtime-config-drift.py" \
      --config-path "$target_abs" --repair "${backup_args[@]}"; then
      mark_fail "${name}: runtime config reconciliation failed (${target_abs})"
      return 1
    fi
    mark_ok "${name}: runtime config drift repaired or absent at ${target_abs}"
    return 0
  fi

  if [[ "${DOTS_PROJECTION_FIXTURE:-}" == "full-policy-v1" || -n "$DEPLOYMENT_STATE" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      mark_plan "create validated runtime config ${target_abs}"
    elif "$PROJECTOR_PYTHON" "${PROJECTION_SOURCE_ROOT}/codex/scripts/admit-policy-fixture.py" --map "$PROJECTION_MAP" --publish-initial-config; then
      mark_ok "${name}: published validated runtime snapshot ${target_abs}"
    else
      mark_fail "${name}: initial runtime publication failed"
      return 1
    fi
    return 0
  fi
  repair_projection_copy "$name" "$source_abs" "$target_abs" "$optional"
}

check_projection_runtime_directory() {
  local name="$1"
  local target_abs="$2"

  if [[ -L "$target_abs" ]]; then
    mark_fail "${name}: runtime-owned directory must not be a symlink (${target_abs} -> $(readlink "$target_abs"))"
    return 1
  elif [[ -d "$target_abs" ]]; then
    mark_ok "${name}: runtime-owned directory isolated at ${target_abs}"
    return 0
  elif [[ -e "$target_abs" ]]; then
    mark_fail "${name}: runtime-owned target must be a directory (${target_abs})"
  else
    mark_fail "${name}: missing runtime-owned directory (${target_abs})"
  fi
  return 1
}

repair_projection_runtime_directory() {
  local name="$1"
  local target_abs="$2"

  if [[ -d "$target_abs" && ! -L "$target_abs" ]]; then
    mark_ok "${name}: preserved runtime-owned directory ${target_abs}"
    return 0
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    if [[ -L "$target_abs" ]]; then
      mark_plan "replace symlink with runtime-owned directory ${target_abs}"
    elif [[ -e "$target_abs" ]]; then
      mark_plan "replace existing target with runtime-owned directory ${target_abs}"
    else
      mark_plan "create runtime-owned directory ${target_abs}"
    fi
    return 0
  fi

  mkdir -p "$(dirname "$target_abs")"
  if [[ -L "$target_abs" || -e "$target_abs" ]]; then
    backup_existing_target "$target_abs"
  fi
  mkdir -p "$target_abs"

  check_projection_runtime_directory "$name" "$target_abs"
}

run_projection_entry() {
  local name="$1"
  local source_abs="$2"
  local target_abs="$3"
  local optional="$4"
  local strategy="$5"

  case "$strategy" in
    hook-copy)
      local hook_args=(--source "$source_abs" --target "$target_abs")
      if [[ -n "$DEPLOYMENT_STATE" ]]; then
        hook_args+=(--backup-dir "$DEPLOYMENT_STATE/publisher-backups")
      fi
      if [[ "$MODE" == "check" ]]; then
        hook_args+=(--check)
      elif [[ "$DRY_RUN" -eq 1 ]]; then
        mark_plan "publish validated regular hook copy ${target_abs}"
        return 0
      fi
      if "$PROJECTOR_PYTHON" "${PROJECTION_SOURCE_ROOT}/codex/scripts/project-codex-hooks.py" "${hook_args[@]}"; then
        mark_ok "${name}: managed regular hook copy ${target_abs}"
      else
        mark_fail "${name}: managed hook publication/check failed"
        return 1
      fi
      ;;
    symlink)
      if [[ "$MODE" == "check" ]]; then
        check_projection_link "$name" "$source_abs" "$target_abs" "$optional"
      else
        repair_projection_link "$name" "$source_abs" "$target_abs" "$optional"
      fi
      ;;
    copy-managed)
      # The installation transaction owns publication, backups and recovery.
      # The projector checks the exact files, never recreates repository links.
      "$PROJECTOR_PYTHON" "${PROJECTION_SOURCE_ROOT}/codex/scripts/install-codex.py" \
        check-copy --state-dir "$DEPLOYMENT_STATE" --name "$name" || return 1
      ;;
    copy)
      if [[ "$MODE" == "check" ]]; then
        check_projection_copy "$name" "$source_abs" "$target_abs" "$optional"
      else
        repair_projection_copy "$name" "$source_abs" "$target_abs" "$optional"
      fi
      ;;
    copy-runtime)
      if [[ "$MODE" == "check" ]]; then
        check_projection_runtime_copy "$name" "$source_abs" "$target_abs" "$optional"
      else
        repair_projection_runtime_copy "$name" "$source_abs" "$target_abs" "$optional"
      fi
      ;;
    preserve)
      if [[ -z "$DEPLOYMENT_STATE" ]]; then
        mark_fail "${name}: preservation requires a packaged deployment"
        return 1
      fi
      mark_ok "${name}: retained local state"
      ;;
    runtime-directory)
      if [[ "$MODE" == "check" ]]; then
        check_projection_runtime_directory "$name" "$target_abs"
      else
        repair_projection_runtime_directory "$name" "$target_abs"
      fi
      ;;
    *)
      mark_fail "${name}: unsupported projection strategy '${strategy}'"
      return 1
      ;;
  esac
}

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
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --scope)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --scope" >&2
        usage
        exit 2
      fi
      SCOPE="$2"
      shift 2
      ;;
    --codex-home)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --codex-home" >&2
        usage
        exit 2
      fi
      append_codex_home_unique "$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "$SCOPE" != "all" && "$SCOPE" != "codex" ]]; then
  echo "Invalid --scope value: ${SCOPE} (expected all or codex)" >&2
  exit 2
fi

if [[ "$SCOPE" != "codex" || -n "$CODEX_HOMES_RAW" || "$(codex_home_count)" -ne 1 || "${CODEX_HOME_LIST[0]}" != "${HOME}/.codex" ]]; then
  echo 'Migration projector requires --scope codex --codex-home "$HOME/.codex" and no CODEX_HOMES override' >&2
  exit 2
fi

if [[ ! -f "$PROJECTION_MAP" ]]; then
  echo "Missing projection map: ${PROJECTION_MAP}" >&2
  exit 1
fi

# Each route admits one closed map, never a caller-selected live map.
if [[ "${DOTS_PROJECTION_FIXTURE:-}" == "full-policy-v1" || -n "$DEPLOYMENT_STATE" ]]; then
  "$PROJECTOR_PYTHON" "${REPO_ROOT}/codex/scripts/admit-policy-fixture.py" --map "$PROJECTION_MAP"
elif [[ -n "${DOTS_PROJECTION_FIXTURE:-}" ]]; then
  echo 'Unknown isolated projection fixture' >&2
  exit 2
else
"$PROJECTOR_PYTHON" - "$PROJECTION_MAP" <<'PYMAP'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
if any(p.is_symlink() for p in (path, *path.parents)):
    raise SystemExit('Migration map must not be symlinked')
expected = {'schema_version': 1, 'codex_projection': [
    {'name': 'preview.toml', 'source': 'codex/generated/preview.toml',
     'target': '{CODEX_HOME}/preview.toml', 'strategy': 'copy'}],
    'global_projection': []}
if json.loads(path.read_text()) != expected:
    raise SystemExit('Only the synthetic preview map is admitted')
PYMAP
fi

PROJECTION_SOURCE_ROOT="$(resolve_projection_source_root)"

if [[ -n "$CODEX_HOMES_RAW" && "$(codex_home_count)" -eq 0 ]]; then
  IFS=',:' read -r -a raw_homes <<< "$CODEX_HOMES_RAW"
  for home in "${raw_homes[@]}"; do
    home="${home#"${home%%[![:space:]]*}"}"
    home="${home%"${home##*[![:space:]]}"}"
    append_codex_home_unique "$home"
  done
fi

if [[ "$(codex_home_count)" -eq 0 ]]; then
  append_codex_home_unique "${HOME}/.codex"
fi

if [[ -n "${PLUGINS_CANON:-}" ]]; then
  PLUGINS_CANON_RESOLVED="${PLUGINS_CANON}"
elif [[ -e "${REPO_ROOT}/.codex/plugins" ]]; then
  PLUGINS_CANON_RESOLVED="${REPO_ROOT}/.codex/plugins"
elif PLUGINS_CANON_RESOLVED="$(resolve_default_plugins_canon)"; then
  :
else
  PLUGINS_CANON_RESOLVED=""
fi

log "Repo root: ${REPO_ROOT}"
log "Projection source root: ${PROJECTION_SOURCE_ROOT}"
log "Projection map: ${PROJECTION_MAP}"
log "Mode: ${MODE}"
log "Scope: ${SCOPE}"
log "Plugins canon: ${PLUGINS_CANON_RESOLVED:-<unset>}"
if [[ "$MODE" == "repair" ]]; then
  log "Backup root: ${BACKUP_ROOT}"
fi

reconcile_retired_profiles() {
  local codex_home="$1"
  local result=""
  if ! result="$("$PROJECTOR_PYTHON" - "$codex_home" "$PROJECTION_SOURCE_ROOT" "$REPO_ROOT" "$PROJECTION_MAP" "$MODE" "$DRY_RUN" <<'PY'
import json
import os
import stat
import sys
import uuid

home, source, repo_root, map_path, mode, dry_run = sys.argv[1:]
retired = ("canary-alpha", "cron-automation", "d", "deep-review", "fast")
with open(map_path, encoding="utf-8") as stream:
    active = {entry["name"] for entry in json.load(stream)["codex_projection"]}
if not os.path.lexists(home):
    raise SystemExit(0)
home_fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
backup_fd = None
failures = []
try:
    for name in [*(f"{profile}.config.toml" for profile in retired), "skills"]:
        expected = os.path.join(source, "codex", name)
        if name != "skills" and (name in active or os.path.lexists(expected)):
            continue
        try:
            before = os.stat(name, dir_fd=home_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if name == "skills":
            # Physical/provider directories are not Configs-owned. Compare
            # lexical targets only: never follow arbitrary source aliases.
            if not stat.S_ISLNK(before.st_mode):
                continue
            target = os.readlink(name, dir_fd=home_fd)
            target = os.path.abspath(os.path.join(home, target))
            known = {
                os.path.abspath(os.path.join(source, "..", repo, ".agents", "skills"))
                for repo in ("agent-skills", "Agent-Skills")
            }
            known.update(
                os.path.abspath(os.path.join(repo_root, "..", repo, ".agents", "skills"))
                for repo in ("agent-skills", "Agent-Skills")
            )
            known.add(os.path.abspath(os.path.join(source, ".codex", "skills")))
            known.add(os.path.abspath(os.path.join(repo_root, ".codex", "skills")))
            # A former custom source cannot be inferred safely from an
            # arbitrary link. Admit it only when the operator supplies the
            # same explicit override used to create the old projection.
            custom = os.environ.get("SKILLS_CANON", "")
            if custom:
                known.add(os.path.abspath(os.path.join(source, custom)))
            if target not in known:
                failures.append("skills: retained owner-unknown skills symlink; inspect manually")
                continue
        elif not stat.S_ISLNK(before.st_mode) or os.readlink(name, dir_fd=home_fd) != expected:
            failures.append(f"{name}: retained owner-unknown retired profile; inspect manually")
            continue
        kind = "skills" if name == "skills" else "profile"
        if mode == "check":
            failures.append(f"{name}: retired repository {kind} symlink remains; run --repair")
            continue
        if dry_run == "1":
            print(f"PLAN  {name}: archive retired repository {kind} symlink")
            continue
        if backup_fd is None:
            backup_name = f".retired-profile-backups-{uuid.uuid4().hex}"
            os.mkdir(backup_name, mode=0o700, dir_fd=home_fd)
            backup_fd = os.open(backup_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home_fd)
        # Rename into a unique owned directory on the same filesystem. Keep
        # both operations bound to open directories, not replaceable paths.
        os.rename(name, name, src_dir_fd=home_fd, dst_dir_fd=backup_fd)
        after = os.stat(name, dir_fd=backup_fd, follow_symlinks=False)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            failures.append(f"{name}: concurrent replacement preserved in {backup_name}; inspect manually")
            continue
        print(f"OK    {name}: retired {kind} symlink archived in {backup_name}/{name}")
finally:
    if backup_fd is not None:
        os.close(backup_fd)
    os.close(home_fd)
for failure in failures:
    print(failure)
raise SystemExit(1 if failures else 0)
PY
)"; then
    mark_fail "retired profile reconciliation: ${result}"
    return 1
  fi
  [[ -z "$result" ]] || log "$result"
}

for codex_home in "${CODEX_HOME_LIST[@]}"; do
  log
  log "Codex home: ${codex_home}"

  # The exact synthetic map above admits preview output only. Legacy retirement
  # belongs to the original production reconciler, not this disposable preview.

  while IFS=$'\x1f' read -r name candidate_source_abs source_abs target_abs optional strategy; do
    [[ -n "$name" ]] || continue
    strategy="${strategy:-symlink}"

    if [[ "$strategy" != "runtime-directory" && "$strategy" != "preserve" ]]; then
      validate_candidate_source "$name" "$candidate_source_abs" "$optional" || continue
    fi
    if ! run_projection_entry "$name" "$source_abs" "$target_abs" "$optional" "$strategy"; then
      if [[ -n "$DEPLOYMENT_STATE" ]]; then exit 1; fi
    fi
  done < <(resolve_tokens_from_map "codex_projection" "$codex_home")
done

if [[ "$SCOPE" == "all" ]]; then
  log
  log "Global projection"
  while IFS=$'\x1f' read -r name candidate_source_abs source_abs target_abs optional strategy; do
    [[ -n "$name" ]] || continue
    strategy="${strategy:-symlink}"
    if [[ "$strategy" != "runtime-directory" ]]; then
      validate_candidate_source "$name" "$candidate_source_abs" "$optional" || continue
    fi
    run_projection_entry "$name" "$source_abs" "$target_abs" "$optional" "$strategy" || true
  done < <(resolve_tokens_from_map "global_projection" "${HOME}/.codex")
fi

log
log "Summary: ok=${ok_count} fail=${fail_count} skip=${skip_count} plan=${plan_count}"

if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi

exit 0
