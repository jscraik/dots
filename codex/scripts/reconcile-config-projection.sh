#!/bin/bash -p

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf '❌ reconcile-config-projection.sh requires bash. Run: /bin/bash -p scripts/reconcile-config-projection.sh [options]\n' >&2
  # shellcheck disable=SC2317
  return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '❌ reconcile-config-projection.sh is CLI-only; do not source it. Run: /bin/bash -p scripts/reconcile-config-projection.sh [options]\n' >&2
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

usage() {
  cat <<'USAGE'
Usage:
  /bin/bash -p codex/scripts/reconcile-config-projection.sh [--check|--repair] [--dry-run] [--scope all|codex] [--codex-home PATH]...

Defaults:
  --repair --scope all
USAGE
}

mode="repair"
scope="all"
dry_run=false
declare -a codex_homes=()
codex_home_count=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      mode="check"
      shift
      ;;
    --repair)
      mode="repair"
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --scope)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --scope" >&2
        usage
        exit 2
      fi
      scope="$2"
      shift 2
      ;;
    --codex-home)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --codex-home" >&2
        usage
        exit 2
      fi
      codex_homes+=("$2")
      codex_home_count=$((codex_home_count + 1))
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

if [[ "$scope" != "all" && "$scope" != "codex" ]]; then
  echo "Invalid --scope value: ${scope} (expected all or codex)" >&2
  exit 2
fi

if [[ "$codex_home_count" -eq 0 ]]; then
  codex_homes=("${CODEX_HOME:-${HOME}/.codex}")
  codex_home_count=1
fi

validation_python="$(codex_select_toml_python "config-projection-reconciler")"
validation_python="$(command -v "$validation_python")"
cmd=(/bin/bash -p "${REPO_ROOT}/scripts/link-configs.sh" "--${mode}" --scope "$scope")
if [[ "$dry_run" == true ]]; then
  cmd+=(--dry-run)
fi
for home in "${codex_homes[@]}"; do
  cmd+=(--codex-home "$home")
done

echo "Running projection reconcile from ${REPO_ROOT}: ${cmd[*]}"
CODEX_VALIDATION_PYTHON="$validation_python" "${cmd[@]}"

runtime_config_repair="${SCRIPT_DIR}/repair-runtime-config-drift.py"
if [[ ! -f "$runtime_config_repair" ]]; then
  echo "FAIL  runtime config drift guard is missing: ${runtime_config_repair}" >&2
  exit 1
fi

runtime_json_field() {
  printf '%s' "$runtime_output" | "$validation_python" -I -B -c '
import json, sys
data = json.load(sys.stdin)
if not isinstance(data, dict):
    raise ValueError("Runtime result must be an object")
field = sys.argv[1]
if field in ("repairs", "drift"):
    value = data.get(field, [])
    if value is None:
        value = []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("Runtime diagnostic must be a string list")
    print(", ".join(value))
else:
    if field == "reason":
        value = data.get("error") or data.get("reason") or "unknown blocker"
    else:
        value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError("Runtime status or reason must be a nonempty string")
    print(value)
' "$1"
}

runtime_config_failed=0
for home in "${codex_homes[@]}"; do
  runtime_config_path="${home}/config.toml"
  if [[ ! -f "$runtime_config_path" || -L "$runtime_config_path" ]]; then
    echo "FAIL  runtime config must be a regular file: ${runtime_config_path}" >&2
    runtime_config_failed=1
    continue
  fi

  runtime_args=(--config-path "$runtime_config_path" --json)
  if [[ "$mode" == "repair" && "$dry_run" == false ]]; then
    runtime_args+=(--repair)
  else
    runtime_args+=(--check)
  fi

  set +e
  runtime_output="$("$validation_python" -B "$runtime_config_repair" "${runtime_args[@]}" 2>&1)"
  runtime_exit=$?
  set -e

  if ! runtime_status="$(runtime_json_field status 2>/dev/null)"; then
    echo "FAIL  runtime config drift guard returned malformed output for ${runtime_config_path}: ${runtime_output}" >&2
    runtime_config_failed=1
    continue
  fi

  case "$runtime_status" in
    pass)
      if [[ "$runtime_exit" -ne 0 ]]; then
        echo "FAIL  runtime config drift guard exited ${runtime_exit} despite pass status: ${runtime_config_path}" >&2
        runtime_config_failed=1
      else
        echo "OK    runtime config drift absent: ${runtime_config_path}"
      fi
      ;;
    repaired)
      if [[ "$runtime_exit" -ne 0 ]]; then
        echo "FAIL  runtime config drift guard exited ${runtime_exit} despite repaired status: ${runtime_config_path}" >&2
        runtime_config_failed=1
      else
        runtime_repairs="$(runtime_json_field repairs)"
        echo "OK    runtime config drift repaired: ${runtime_repairs}"
      fi
      ;;
    fail)
      runtime_drift="$(runtime_json_field drift)"
      if [[ "$mode" == "repair" && "$dry_run" == true ]]; then
        echo "PLAN  runtime config drift would be repaired: ${runtime_drift}"
      else
        echo "FAIL  runtime config drift detected: ${runtime_drift}" >&2
        runtime_config_failed=1
      fi
      ;;
    blocked)
      runtime_reason="$(runtime_json_field reason)"
      echo "FAIL  runtime config drift repair blocked: ${runtime_reason}" >&2
      runtime_config_failed=1
      ;;
    *)
      echo "FAIL  runtime config drift guard returned unsupported status ${runtime_status}: ${runtime_output}" >&2
      runtime_config_failed=1
      ;;
  esac

done

if [[ "$runtime_config_failed" -ne 0 ]]; then
  exit 1
fi
