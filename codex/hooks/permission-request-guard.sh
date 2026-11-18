#!/usr/bin/env bash

set -euo pipefail
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
. "$hook_dir/hook-runtime-lib.sh"

parsed_fields="$(
  printf '%s' "$input_json" | jq -r '
    def tool_command:
      (if (.tool_input? | type) == "object" then .tool_input.command else null end)
      // .command
      // "";
    def tool_description:
      (if (.tool_input? | type) == "object" then .tool_input.description else null end)
      // "";
    def tool_cwd:
      ((if (.tool_input? | type) == "object" then .tool_input.cwd else null end) | select(. != ""))
      // ((if (.tool_input? | type) == "object" then .tool_input.workdir else null end) | select(. != ""))
      // (.cwd | select(. != ""))
      // "";
    def edit_payload:
      (if (.tool_input? | type) == "object" then
        [
          .tool_input.path,
          .tool_input.file_path,
          .tool_input.filePath,
          .tool_input.target_file,
          .tool_input.target,
          .tool_input.filename
        ]
      else [] end)
      + (if ((.tool_input? | type) == "object") and ((.tool_input.patch? | type) == "string") then
          (.tool_input.patch
          | split("\n")
          | map(select(test("^\\*\\*\\* (Add|Update|Delete) File: |^\\*\\*\\* Move to: ")))
          | map(
              sub("^\\*\\*\\* (Add|Update|Delete) File: "; "")
              | sub("^\\*\\*\\* Move to: "; "")
            ))
        else [] end)
      + (if (tool_command | type) == "string" and (tool_command | length) > 0 then
          (tool_command
          | split("\n")
          | map(select(test("^\\*\\*\\* (Add|Update|Delete) File: |^\\*\\*\\* Move to: ")))
          | map(
              sub("^\\*\\*\\* (Add|Update|Delete) File: "; "")
              | sub("^\\*\\*\\* Move to: "; "")
            ))
        else [] end)
      | map(select(. != null) | tostring)
      | join("\u001e");
    [
      (.tool_name // ""),
      (tool_command | @base64),
      tool_description,
      tool_cwd,
      (.permission_mode // "default"),
      edit_payload
    ] | join("\u001f")
  '
)"
IFS=$'\x1f' read -r tool_name encoded_command raw_description _command_cwd permission_mode edit_targets <<<"$parsed_fields"
raw_command="$(printf '%s' "$encoded_command" | jq -Rr '@base64d')"

command_lc="$(printf '%s' "$raw_command" | tr '\r\n\t' '   ' | tr '[:upper:]' '[:lower:]')"
description_lc="$(printf '%s' "$raw_description" | tr '[:upper:]' '[:lower:]')"
home_canon="$HOME"
if [[ -d "$HOME" ]]; then
  home_canon="$(cd -P "$HOME" && pwd -P)"
fi
home_lc="$(printf '%s' "$home_canon" | tr '[:upper:]' '[:lower:]')"

deny_reason=""
git_worktree_risk=""

canonicalize_edit_target() {
  local target="$1"
  local base_dir="${_command_cwd:-$PWD}"

  python3 - "$base_dir" "$target" <<'PY'
import sys
from pathlib import Path

base = Path(sys.argv[1]).expanduser()
target = Path(sys.argv[2]).expanduser()
if not target.is_absolute():
    target = base / target
print(target.resolve(strict=False))
PY
}

is_sensitive_edit_target() {
  local target="$1"
  local target_lc
  target_lc="$(printf '%s' "$target" | tr '[:upper:]' '[:lower:]')"

  if [[ "$target_lc" == "~/.ssh"* \
     || "$target_lc" == ".ssh/"* \
     || "$target_lc" == ".ssh" \
     || "$target_lc" == "~/.codex/auth"* \
     || "$target_lc" == ".codex/auth"* \
     || "$target_lc" == "/etc/"* \
     || "$target_lc" == "/etc" ]]; then
    return 0
  fi

  local canonical_lc
  canonical_lc="$(canonicalize_edit_target "$target" | tr '[:upper:]' '[:lower:]')"
  [[ "$canonical_lc" == "${home_lc}/.ssh"* \
    || "$canonical_lc" == "${home_lc}/.codex/auth"* \
    || "$canonical_lc" == "/etc/"* \
    || "$canonical_lc" == "/etc" \
    || "$canonical_lc" == "/private/etc/"* \
    || "$canonical_lc" == "/private/etc" ]]
}

if [[ "$tool_name" == "apply_patch" || "$tool_name" == "Edit" || "$tool_name" == "Write" ]]; then
  if [[ -z "$edit_targets" ]]; then
    deny_reason="Blocked approval request for edit tool without inspectable path target."
  else
    IFS=$'\x1e' read -r -a target_list <<<"$edit_targets"
    for edit_target in "${target_list[@]}"; do
      if is_sensitive_edit_target "$edit_target"; then
        deny_reason="Blocked approval request for edit tool targeting sensitive credential or system configuration paths."
        break
      fi
    done
  fi
elif [[ "$tool_name" != "Bash" ]]; then
  printf '{}\n'
  exit 0
elif git_worktree_risk="$(hook_runtime_destructive_git_operation "$raw_command")"; then
  case "$git_worktree_risk" in
    reset-hard)
      deny_reason="Blocked approval request for git reset --hard due to destructive reset risk."
      ;;
    checkout-paths|checkout-destructive)
      deny_reason="Blocked approval request for destructive git checkout because it can discard local changes."
      ;;
    broad-delete)
      deny_reason="Blocked approval request for broad rm -rf on root/home scope."
      ;;
    *)
      deny_reason="Blocked approval request for unsupported shell command syntax because destructive intent cannot be ruled out."
      ;;
  esac
elif [[ "$command_lc" == *"| sh"* || "$command_lc" == *"| bash"* ]]; then
  deny_reason="Blocked approval request for pipe-to-shell execution. Download and inspect script content first."
elif [[ "$command_lc" == *"curl "* && "$command_lc" == *"sh -c"* ]]; then
  deny_reason="Blocked approval request for curl-fed shell execution."
elif [[ "$description_lc" == *"full access"* && "$command_lc" == *"rm -rf"* ]]; then
  deny_reason="Blocked approval request combining broad delete intent with full-access escalation."
fi

if [[ -z "$deny_reason" ]]; then
  printf '{}\n'
  exit 0
fi

event_record="$(hook_runtime_event_envelope "$input_json" "permission-request" "permission-request-guard" "deny" "$deny_reason")"
if [[ -n "$event_record" ]]; then
  hook_runtime_append_jsonl "$(hook_runtime_log_path "hook-events")" "$event_record" "permission-request-guard" || true
fi

jq -n \
  --arg reason "$deny_reason" \
  --arg mode "$permission_mode" \
  '{
    systemMessage: ("PermissionRequest denied a risky Bash approval request in permission mode " + $mode + "."),
    hookSpecificOutput: {
      hookEventName: "PermissionRequest",
      decision: {
        behavior: "deny",
        message: $reason
      }
    }
  }'
