#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf 'run-auth-backed.sh requires bash. Run: bash scripts/run-auth-backed.sh -- <command> [args...]\n' >&2
  return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf 'run-auth-backed.sh is CLI-only; do not source it. Run: bash scripts/run-auth-backed.sh -- <command> [args...]\n' >&2
  return 2
fi

set -euo pipefail
dots_script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_script_dir/admit-hook-fixture.py" '{}' || exit $?

usage() {
  cat <<'USAGE'
Usage: run-auth-backed.sh [--env-file PATH | --environment ID | --require-environment] [--require-env NAME]... -- <command> [args...]
       run-auth-backed.sh [--env-file PATH | --environment ID | --require-environment] --canary NAME

Run validation or operational commands through 1Password without printing
secrets. Codex agents should select the Desktop-owned ~/.codex/.env FIFO with
--env-file; the wrapper verifies its type, owner, and mode before stable
`op run --env-file` consumes it. Run FIFO-backed commands sequentially.
When CODEX_AUTH_ENVIRONMENT_ID is present and --env-file is not selected, the
wrapper uses the managed beta CLI and `op-beta run --environment`. That XPC
route is intended for a host session that can reach 1Password Desktop.
Direct reads of ~/.codex/.env and ~/.codex/auth are blocked by the PreToolUse
guard; use this wrapper when a command genuinely needs auth.

Options:
  --env-file PATH      Explicit stable-CLI source. The canonical
                       ~/.codex/.env path must be an owner-only FIFO.
  --environment ID     1Password Environment ID to load with op-beta
                       (default: CODEX_AUTH_ENVIRONMENT_ID when set)
  --require-environment
                       Require CODEX_AUTH_ENVIRONMENT_ID and the beta Environment
                       route; never fall back to the compatibility env file
  --require-env NAME   Require and deliver NAME after loading env material;
                       repeat for every variable the child is allowed to receive
  --canary NAME        Verify one allowlisted variable (OLLAMA_API_KEY or
                       CIRCLECI_CLI_TOKEN) and print only a fixed pass result;
                       this mode runs no caller command
  -h, --help           Show this help text
USAGE
}

is_valid_env_name() {
  [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
}

is_valid_environment_id() {
  case "$1" in
    (*[!a-z0-9-]*) return 1 ;;
  esac
  [[ ${#1} -eq 26 || "$1" == ????????-????-????-????-???????????? ]]
}

is_allowed_canary_name() {
  case "$1" in
    OLLAMA_API_KEY|CIRCLECI_CLI_TOKEN) return 0 ;;
    (*) return 1 ;;
  esac
}

is_child_runtime_env_name() {
  case "$1" in
    HOME|PATH|TMPDIR|USER|LOGNAME|SHELL|LANG|LC_ALL|LC_CTYPE|TERM|CODEX_HOME) return 0 ;;
    (*) return 1 ;;
  esac
}

# Normalize parent directories without resolving the final path component.
# The final component must remain visible to lstat so an equivalent spelling
# of ~/.codex/.env cannot bypass the FIFO/symlink validator.
normalize_path() {
  local path="$1"
  local directory=""
  local basename=""
  local normalized_directory=""

  if [[ "$path" != /* ]]; then
    path="$PWD/$path"
  fi
  directory="${path%/*}"
  basename="${path##*/}"
  if [[ -z "$directory" ]]; then
    directory="/"
  fi
  if normalized_directory="$(cd -P "$directory" 2>/dev/null && pwd -P)"; then
    printf '%s/%s\n' "${normalized_directory%/}" "$basename"
  else
    printf '%s\n' "$path"
  fi
}

run_runtime_python() {
  if [[ ! -x /usr/bin/python3 ]]; then
    printf 'run-auth-backed.sh: isolated system python3 is required for auth validation\n' >&2
    return 69
  fi
  /usr/bin/python3 -I -S "$@"
}

# macOS Bash 3.2 treats an empty declared array as unbound under `set -u`.
# Keep the command wrapper safe when no --require-env option was supplied.
required_env_count() {
  local count=""
  set +u
  count="${#required_env[@]}"
  set -u
  printf '%s\n' "$count"
}

mounted_env_file="$HOME/.codex/.env"
env_file="${CODEX_AUTH_ENV_FILE:-$mounted_env_file}"
environment_id="${CODEX_AUTH_ENVIRONMENT_ID:-}"
declare -a required_env=()
canary_env=""
env_file_overridden=false
environment_overridden=false
environment_required=false
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while (($# > 0)); do
  case "$1" in
    --env-file)
      if (($# < 2)); then
        printf 'run-auth-backed.sh: --env-file requires a path operand\n' >&2
        usage >&2
        exit 2
      fi
      env_file="${2:-}"
      env_file_overridden=true
      environment_id=""
      shift 2
      ;;
    --environment)
      if (($# < 2)); then
        printf 'run-auth-backed.sh: --environment requires an ID operand\n' >&2
        usage >&2
        exit 2
      fi
      environment_id="${2:-}"
      environment_overridden=true
      if [[ -z "$environment_id" ]]; then
        printf 'run-auth-backed.sh: --environment requires a non-empty ID\n' >&2
        exit 2
      fi
      shift 2
      ;;
    --require-environment)
      environment_required=true
      shift
      ;;
    --require-env)
      if (($# < 2)); then
        printf 'run-auth-backed.sh: --require-env requires a variable name operand\n' >&2
        usage >&2
        exit 2
      fi
      required_env+=("${2:-}")
      shift 2
      ;;
    --canary)
      if (($# < 2)); then
        printf 'run-auth-backed.sh: --canary requires a variable name operand\n' >&2
        usage >&2
        exit 2
      fi
      if [[ -n "$canary_env" || "$(required_env_count)" -gt 0 ]]; then
        printf 'run-auth-backed.sh: --canary cannot be combined with --require-env\n' >&2
        exit 2
      fi
      canary_env="${2:-}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'run-auth-backed.sh: unknown argument before --: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mounted_env_file="$(normalize_path "$mounted_env_file")"
env_file="$(normalize_path "$env_file")"

if [[ "$env_file_overridden" == true && "$environment_overridden" == true ]]; then
  printf 'run-auth-backed.sh: --env-file and --environment are mutually exclusive\n' >&2
  exit 2
fi

if [[ -n "$canary_env" && $# -gt 0 ]]; then
  printf 'run-auth-backed.sh: --canary cannot be combined with a command\n' >&2
  usage >&2
  exit 2
fi

if [[ -z "$canary_env" && $# == 0 ]]; then
  printf 'run-auth-backed.sh: missing command after --\n' >&2
  usage >&2
  exit 2
fi

if [[ -n "$canary_env" ]]; then
  if ! is_valid_env_name "$canary_env"; then
    printf 'run-auth-backed.sh: invalid --canary variable name: %s\n' "$canary_env" >&2
    exit 2
  fi
  if ! is_allowed_canary_name "$canary_env"; then
    printf 'run-auth-backed.sh: --canary variable is not allowlisted: %s\n' "$canary_env" >&2
    exit 2
  fi
  if [[ -z "$environment_id" && "$env_file" != "$mounted_env_file" ]]; then
    printf 'run-auth-backed.sh: --env-file only permits the canonical ~/.codex/.env\n' >&2
    exit 2
  fi
  required_env=("$canary_env")
fi

if [[ -z "$environment_id" && "$env_file_overridden" == false && "$environment_overridden" == false ]]; then
  runtime_config="$HOME/.codex/config.toml"
  if [[ -f "$runtime_config" && ! -L "$runtime_config" ]]; then
    if resolved_environment_id="$(run_runtime_python "$script_dir/read-runtime-auth-environment.py" --config "$runtime_config" 2>/dev/null)"; then
      environment_id="$resolved_environment_id"
    fi
  fi
fi

if [[ "$environment_required" == true && -z "$environment_id" ]]; then
  printf 'run-auth-backed.sh: CODEX_AUTH_ENVIRONMENT_ID is required for this command\n' >&2
  exit 67
fi

if [[ -n "$environment_id" ]]; then
  if ! is_valid_environment_id "$environment_id"; then
    printf 'run-auth-backed.sh: invalid 1Password Environment ID\n' >&2
    exit 2
  fi
  op_bin="op-beta"
  run_source_args=(--environment "$environment_id")
else
  if [[ -z "$env_file" ]]; then
    printf 'run-auth-backed.sh: empty env file path\n' >&2
    exit 2
  fi
  # The FIFO is the sole supported stable-CLI source. Do not let an arbitrary
  # readable file or alternate FIFO become a credential source inside the
  # sandbox; equivalent spellings of the canonical path normalize identically.
  if [[ "$env_file" != "$mounted_env_file" ]]; then
    printf 'run-auth-backed.sh: --env-file only permits the canonical ~/.codex/.env\n' >&2
    exit 66
  fi

  run_runtime_python "$script_dir/validate-auth-env-mount.py" --path "$env_file"
  op_bin="op"
  run_source_args=(--env-file "$env_file")
fi

if [[ -n "${CODEX_AUTH_OP_BIN:-}" ]]; then
  printf 'run-auth-backed.sh: caller-selected 1Password binaries are unsupported\n' >&2
  exit 64
fi

trusted_realpath() {
  local utility
  for utility in /bin/realpath /usr/bin/realpath; do
    if [[ -x "$utility" ]]; then
      "$utility" "$1"
      return
    fi
  done
  run_runtime_python -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"
}

resolve_trusted_op() {
  local name="$1" candidate="" resolved="" install_root="" current=""
  # Documented install roots only; caller-writable path components fail closed.
  for candidate in \
    "/opt/homebrew/bin/$name" \
    "/usr/local/bin/$name"; do
    [[ -x "$candidate" ]] || continue
    resolved="$(trusted_realpath "$candidate")" || continue
    case "$resolved/" in
      *$'\n'*|*//*|*/../*|*/./*) continue ;;
    esac
    install_root="$(dirname "$(dirname "$candidate")")"
    case "$resolved" in
      "$install_root"/*)
        current="$resolved"
        while [[ "$current" != "/" ]]; do
          [[ -w "$current" ]] && continue 2
          [[ "$current" == "$install_root" ]] && { printf '%s\n' "$resolved"; return 0; }
          current="$(dirname "$current")"
        done
        ;;
    esac
  done
  return 1
}
if ! op_bin="$(resolve_trusted_op "$op_bin")"; then
  printf 'run-auth-backed.sh: trusted 1Password CLI is unavailable: %s\n' "$op_bin" >&2
  exit 69
fi
python3 -I -S -B "$dots_script_dir/admit-hook-fixture.py" --provider-path "$op_bin" || exit $?

if [[ "$(required_env_count)" -gt 0 ]]; then
  for env_name in "${required_env[@]}"; do
    if ! is_valid_env_name "$env_name"; then
      printf 'run-auth-backed.sh: invalid --require-env name: %s\n' "$env_name" >&2
      exit 2
    fi
    if is_child_runtime_env_name "$env_name"; then
      printf 'run-auth-backed.sh: --require-env name is reserved for pre-injection runtime context: %s\n' "$env_name" >&2
      exit 2
    fi
  done
fi

if [[ -n "$canary_env" ]]; then
  if [[ -n "${!canary_env+x}" ]]; then
    printf 'run-auth-backed.sh: --canary variable must not already be set before auth load: %s\n' "$canary_env" >&2
    exit 67
  fi
  exec "$op_bin" run "${run_source_args[@]}" -- /bin/bash -p -c '
    set -euo pipefail
    env_name="$1"
    if [[ -z "${!env_name:-}" ]]; then
      printf "run-auth-backed.sh: auth injection canary failed\n" >&2
      exit 67
    fi
    printf "run-auth-backed.sh: auth injection canary passed\n"
  ' bash "$canary_env"
fi

# Capture only the benign process context needed by ordinary command-line
# children before 1Password can add or replace environment values. The trusted
# post-injection shell below reconstructs the child environment from this list
# and the explicitly requested names, so unrelated credentials cannot survive.
declare -a child_runtime_env=("PATH=${PATH:-/usr/bin:/bin}")
for env_name in HOME TMPDIR USER LOGNAME SHELL LANG LC_ALL LC_CTYPE TERM CODEX_HOME; do
  if [[ -n "${!env_name+x}" ]]; then
    child_runtime_env+=("$env_name=${!env_name}")
  fi
done

required_count="$(required_env_count)"
declare -a child_launch_args=("$required_count" "${#child_runtime_env[@]}")
if [[ "$required_count" -gt 0 ]]; then
  child_launch_args+=("${required_env[@]}")
fi
child_launch_args+=("${child_runtime_env[@]}" "$@")

exec "$op_bin" run "${run_source_args[@]}" -- /usr/bin/python3 -I -S -c '
import os, signal, sys
required_count, runtime_count = map(int, sys.argv[1:3])
names = sys.argv[3:3 + required_count]
runtime = sys.argv[3 + required_count:3 + required_count + runtime_count]
command = sys.argv[3 + required_count + runtime_count:]
child_env = {}
for name in names:
    value = os.environ.get(name)
    if not value:
        print("run-auth-backed.sh: required env var is missing after auth load: " + name, file=sys.stderr)
        sys.exit(67)
    child_env[name] = value
child_env.update(item.split("=", 1) for item in runtime)
for name in ("SIGPIPE", "SIGXFZ", "SIGXFSZ"):
    if hasattr(signal, name):
        signal.signal(getattr(signal, name), signal.SIG_DFL)
os.execvpe(command[0], command, child_env)
' "${child_launch_args[@]}"
