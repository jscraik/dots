#!/bin/bash -p

set -uo pipefail
# shellcheck source=codex/hooks/hook-runtime-path.sh
if . "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh"; then
  :
else
  bootstrap_status=$?
  printf 'LifeOS context unavailable: hook runtime bootstrap failed (status %s)\n' "$bootstrap_status" >&2
  printf '%s\n' '{"continue":true,"systemMessage":"LifeOS context unavailable: hook runtime bootstrap failed"}'
  exit 0
fi

# Read-only, fail-open DATA/LifeOS context adapter for Codex UserPromptSubmit.
# The installed LifeOS owner remains external to Configs; this hook only routes
# the current prompt through its deterministic retriever and returns context.
input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
if ! . "$hook_dir/hook-runtime-lib.sh"; then
  printf '%s\n' '{"continue":true,"systemMessage":"LifeOS context unavailable: hook runtime library failed"}'
  exit 0
fi
lifeos_root="${CODEX_LIFEOS_DIR:-${LIFEOS_DIR:-$HOME/.codex/LIFEOS}}"
retriever="${CODEX_LIFEOS_RETRIEVER:-$lifeos_root/TOOLS/MemoryRetriever.ts}"
# Optional providers share the already validated, installation-bound inventory.
# Neither an inherited override nor PATH may choose a different executable.
bun_bin="${CODEX_VALIDATION_PYTHON%/*}/bun"
data_project_root="${CODEX_LIFEOS_PROJECT_ROOT:-$HOME/dev/lifeOS}"
retriever_timeout_seconds="${CODEX_LIFEOS_RETRIEVER_TIMEOUT_SECONDS:-3}"

prompt="$(printf '%s' "$input_json" | jq -r '.prompt // ""' 2>/dev/null || true)"
prompt_cwd="$(printf '%s' "$input_json" | jq -r '.cwd // ""' 2>/dev/null || true)"
prompt_lc="$(printf '%s' "$prompt" | tr '[:upper:]' '[:lower:]')"

if [[ -n "$(hook_runtime_prompt_safety_block_reason "$prompt_lc" || true)" ]]; then
  jq -n '{continue: true}'
  exit 0
fi

# Canonicalize paths before comparison to prevent bypass via symlinks or .. segments.
canonical_prompt_cwd="$(cd -P "$prompt_cwd" 2>/dev/null && pwd -P || true)"
canonical_project_root="$(cd -P "$data_project_root" 2>/dev/null && pwd -P || true)"
if [[ -z "$canonical_prompt_cwd" || -z "$canonical_project_root" ]]; then
  jq -n '{continue: true}'
  exit 0
fi
if [[ "$canonical_prompt_cwd" != "$canonical_project_root" && "$canonical_prompt_cwd" != "$canonical_project_root/"* ]]; then
  jq -n '{continue: true}'
  exit 0
fi
if [[ -z "$prompt" || ! -f "$bun_bin" || ! -x "$bun_bin" || ! -f "$retriever" || ! "$retriever_timeout_seconds" =~ ^[1-9][0-9]*$ ]] || ! command -v python3 >/dev/null 2>&1; then
  jq -n '{continue: true}'
  exit 0
fi

retrieved="$({
  LIFEOS_DIR="$lifeos_root" python3 -I -S - "$retriever_timeout_seconds" "$bun_bin" "$retriever" "$prompt" <<'PY'
import os
import re
import subprocess
import sys

timeout_seconds, bun_bin, retriever, prompt = sys.argv[1:]
retriever_env = {
    "HOME": os.environ.get("HOME", ""),
    "LIFEOS_DIR": os.environ.get("LIFEOS_DIR", ""),
    "PATH": os.environ.get("PATH", ""),
}
try:
    result = subprocess.run(
        [bun_bin, retriever, "--raw", "--top", "5", "--", prompt],
        check=False,
        env=retriever_env,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        text=True,
        timeout=int(timeout_seconds),
    )
except (OSError, subprocess.TimeoutExpired, ValueError):
    raise SystemExit(1)

if result.returncode == 0:
    retrieved = re.sub(
        r"<\s*/\s*lifeos-context\s*>",
        "[lifeos-context marker removed]",
        result.stdout,
        flags=re.IGNORECASE,
    )
    retrieved = re.sub(
        r"<\s*lifeos-context\b[^>]*>",
        "[lifeos-context marker removed]",
        retrieved,
        flags=re.IGNORECASE,
    )
    sys.stdout.write(retrieved)
PY
} 2>/dev/null || true)"
if [[ -z "$retrieved" ]]; then
  jq -n '{continue: true}'
  exit 0
fi

additional_context="<lifeos-context source=\"local-curated\" retrieval=\"read-only\" root=\"codex\">
$retrieved
</lifeos-context>"

jq -n --arg additional_context "$additional_context" '{
  continue: true,
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: $additional_context
  }
}'
