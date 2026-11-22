#!/usr/bin/env bash
set -euo pipefail

dots_script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_script_dir/admit-hook-fixture.py" '{}' || exit $?

prepend_path_if_dir() {
  local path_dir="$1"
  if [[ -d "${path_dir}" ]]; then
    PATH="${path_dir}:${PATH}"
  fi
}

prepend_path_if_dir "/opt/homebrew/bin"
prepend_path_if_dir "/usr/local/bin"
prepend_path_if_dir "${HOME}/.local/bin"
prepend_path_if_dir "${HOME}/.local/share/mise/shims"
export PATH

aikido_mcp_version="${AIKIDO_MCP_VERSION:-1.0.10}"
binary="${AIKIDO_MCP_BIN:-${HOME}/.codex/utilities/aikido-mcp/bin/aikido-mcp}"
env_file="${AIKIDO_MCP_ENV_FILE:-${HOME}/.codex/aikido-mcp.env}"
use_op_run="${AIKIDO_MCP_USE_OP_RUN:-1}"
python3 -I -S -B "$dots_script_dir/admit-hook-fixture.py" --aikido-input aikido-binary "$binary" || exit $?
python3 -I -S -B "$dots_script_dir/admit-hook-fixture.py" --aikido-input aikido-reference "$env_file" || exit $?

if [[ ! -f "${binary}" || ! -x "${binary}" ]]; then
  printf 'aikido MCP binary is not installed or executable: %s\n' "${binary}" >&2
  printf 'Install @aikidosec/mcp@%s into ~/.codex/utilities/aikido-mcp or set AIKIDO_MCP_BIN to a pinned local binary path.\n' "${aikido_mcp_version}" >&2
  exit 127
fi

if [[ "${use_op_run}" == "1" && -e "${env_file}" ]]; then
  if [[ ! -r "${env_file}" ]]; then
    printf 'Aikido MCP env file exists but is not readable: %s\n' "${env_file}" >&2
    exit 127
  fi
  op_binary="${OP_BIN:-}"
  if [[ -z "${op_binary}" ]]; then
    if [[ -x "/opt/homebrew/bin/op" ]]; then
      op_binary="/opt/homebrew/bin/op"
    else
      op_binary="$(command -v op || true)"
    fi
  fi
  if [[ -z "${op_binary}" || ! -x "${op_binary}" ]]; then
    printf '1Password CLI is required to read Aikido MCP env file: %s\n' "${env_file}" >&2
    printf 'Install op or set OP_BIN to an executable 1Password CLI path.\n' >&2
    exit 127
  fi
  python3 -I -S -B "$dots_script_dir/admit-hook-fixture.py" --provider-path "$op_binary" || exit $?
  exec "${op_binary}" run --env-file "${env_file}" -- "${binary}" "$@"
fi

exec "${binary}" "$@"
