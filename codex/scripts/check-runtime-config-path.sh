#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf 'check-runtime-config-path.sh requires bash.\n' >&2
  return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf 'check-runtime-config-path.sh is CLI-only; invoke it with bash.\n' >&2
  return 2
fi

set -euo pipefail
dots_script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_script_dir/admit-hook-fixture.py" '{}' || exit $?

if [[ $# -ne 1 ]]; then
  printf 'Usage: bash codex/scripts/check-runtime-config-path.sh PATH\n' >&2
  exit 2
fi

runtime_config_path="$1"

if [[ -L "$runtime_config_path" ]]; then
  printf 'runtime config: symlink %s -> %s\n' "$runtime_config_path" "$(readlink "$runtime_config_path")"
elif [[ -f "$runtime_config_path" ]]; then
  printf 'runtime config: mutable regular file %s\n' "$runtime_config_path"
else
  printf 'runtime config: missing or invalid path %s\n' "$runtime_config_path" >&2
  exit 1
fi
