#!/bin/bash -p

# Bootstrap only through the system interpreter before trusting the selected payload.
PATH="/usr/bin:/bin:/usr/sbin:/sbin"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE PYTHONPYCACHEPREFIX BASH_ENV ENV
unset LD_PRELOAD LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
PYTHONNOUSERSITE=1
PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE PYTHONDONTWRITEBYTECODE

dots_hook_runtime_dir="${BASH_SOURCE[0]%/*}"
if ! dots_hook_runtime_bin="$(/usr/bin/python3 -I -S -B "$dots_hook_runtime_dir/../scripts/validate-hook-toolchain.py")"; then
  printf '%s\n' 'Security hook blocked: protected toolchain validation failed.' >&2
  return 1 2>/dev/null || exit 1
fi
PATH="$dots_hook_runtime_bin:$PATH"
CODEX_VALIDATION_PYTHON="$dots_hook_runtime_bin/python3"
export PATH CODEX_VALIDATION_PYTHON
unset dots_hook_runtime_dir dots_hook_runtime_bin
