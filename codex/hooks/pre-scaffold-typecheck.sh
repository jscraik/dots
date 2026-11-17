#!/bin/bash -p
# Scaffolding has not happened at PreToolUse time. Never execute scripts from
# the existing parent project or claim the not-yet-created project was checked.
set -euo pipefail
# shellcheck source=codex/hooks/hook-runtime-path.sh
. "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh"
input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
printf '%s' "$input_json" | jq '
  if .tool_name == "Bash" then
    {
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        additionalContext: "If this command creates or changes a project scaffold, inspect its generated manifest and lockfile afterward and run its actual repository typecheck/test contract. This advisory hook did not run validation."
      }
    }
  else {continue: true}
  end
'
