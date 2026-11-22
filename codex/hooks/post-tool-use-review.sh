#!/bin/bash -p

set -euo pipefail
# shellcheck source=codex/hooks/hook-runtime-path.sh
. "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh"

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
codex_repo_root="$(cd -P "$hook_dir/.." && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
. "$hook_dir/hook-runtime-lib.sh"
runtime_policy_script="$codex_repo_root/scripts/hook-governance/hook_runtime_policy.py"
timeout_class="post_quality_advisory_fail_open"

if [[ -f "$runtime_policy_script" ]]; then
  timeout_class="$(
    python3 "$runtime_policy_script" --event PostToolUse --field timeout_class 2>/dev/null \
      || printf '%s' "$timeout_class"
  )"
fi

append_repo_learning_entry() {
  local cwd="$1"
  local command_excerpt="$2"
  local output_excerpt="$3"
  local exit_code="$4"
  local output_lc="$5"
  local repo_root=''
  local learnings_file=''
  local date_stamp=''
  local reason=''
  local fix=''
  local command_label=''
  local key=''
  local entry=''

  if [[ -z "$cwd" ]]; then
    return 0
  fi
  if ! repo_root="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)"; then
    return 0
  fi
  learnings_file="${repo_root}/.harness/memory/LEARNINGS.md"
  if [[ ! -f "$learnings_file" || ! -w "$learnings_file" ]]; then
    return 0
  fi

  command_label="$(
    printf '%s\n' "$command_excerpt" \
      | awk '
          {
            for (i = 1; i <= NF; i++) {
              if ($i ~ /^[A-Za-z_][A-Za-z0-9_]*=.*/) {
                continue
              }
              print $i
              exit
            }
          }
        '
  )"
  command_label="${command_label##*/}"
  if [[ -z "$command_label" || ! "$command_label" =~ ^[A-Za-z0-9._:-]+$ ]]; then
    command_label="redacted-command"
  fi

  if [[ "$output_lc" == *"approval required by policy"* && "$output_lc" == *"askforapproval is set to never"* ]]; then
    reason="Bash command '${command_label}' was blocked by runtime approval-policy mismatch"
    fix="align approval mode/runtime policy before retrying the same command"
  elif [[ "$output_lc" == *"operation not permitted"* || "$output_lc" == *"permission denied"* ]]; then
    reason="Bash command '${command_label}' hit a sandbox or permission boundary"
    fix="request the minimal required permission or use a non-destructive fallback path"
  elif [[ "$output_lc" == *"command not found"* ]]; then
    reason="Bash command '${command_label}' failed because a required binary was unavailable"
    fix="verify tool availability and PATH before retrying"
  else
    reason="Bash command '${command_label}' failed with exit code ${exit_code:-unknown}"
    fix="summarize the failure and change approach before rerunning the same command"
  fi

  key="$(
    printf '%s|%s|%s\n' "$command_excerpt" "$exit_code" "$output_excerpt" \
      | cksum \
      | awk '{print $1}'
  )"
  if /usr/bin/grep -Fq "auto-key:${key}" "$learnings_file" 2>/dev/null; then
    return 0
  fi

  date_stamp="$(date +%Y-%m-%d)"
  entry="**${date_stamp} [Codex]:** ${reason} -> ${fix} (auto-key:${key})"
  python3 "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_metadata.py" append-learning "$repo_root" "$entry"
}

parsed_fields="$(
  printf '%s' "$input_json" | jq -r '
    def tool_command:
      (if (.tool_input? | type) == "object" then .tool_input.command else null end)
      // .command
      // "";
    def parse_resp:
      (.tool_response // null) as $r
      | if $r == null then null
        elif ($r | type) == "string" then ($r | fromjson? // $r)
        else $r
        end;
    (parse_resp) as $resp
      | [
        (.tool_name // ""),
        (.permission_mode // "default"),
        (if $resp != null and ($resp | type) == "object"
          then (
            [
              $resp.exit_code,
              $resp.exitCode,
              $resp.returncode,
              $resp.code
            ]
            | map(
                if . == null then ""
                elif (type == "number") then tostring
                elif (type == "string") then .
                else ""
                end
              )
            | map(select(test("^[0-9]+$")))
            | .[0] // ""
          )
          else ""
         end),
        (
          if $resp == null then ""
          elif ($resp | type) == "object"
            then (reduce ([$resp.stderr, $resp.output, $resp.stdout, $resp.message, $resp.error, $resp.text]
                          | map(select(. != null) | tostring | select(length > 0)))[] as $part
                  ([]; if index($part) == null then . + [$part] else . end)
                  | join(" "))
          elif ($resp | type) == "string"
            then $resp
          else ($resp | tostring)
          end
          | gsub("[\\r\\n\\t]+"; " ")
          | .[0:240]
        ),
        (tool_command | gsub("[\\r\\n\\t]+"; " ") | .[0:160]),
        (.cwd // "")
      ]
    | join("\u001f")
  '
)"
IFS=$'\x1f' read -r tool_name permission_mode exit_code output_excerpt command_excerpt cwd <<<"$parsed_fields"

if [[ "$tool_name" != "Bash" && "$tool_name" != "apply_patch" && "$tool_name" != "Edit" && "$tool_name" != "Write" ]]; then
  jq -n '{continue: true}'
  exit 0
fi

output_lc="$(printf '%s' "$output_excerpt" | tr '[:upper:]' '[:lower:]')"
is_numeric_failure=0
if [[ -n "$exit_code" && "$exit_code" =~ ^[0-9]+$ && "$exit_code" != "0" ]]; then
  is_numeric_failure=1
fi

is_approval_policy_mismatch=0
if [[ "$output_lc" == *"approval required by policy"* && "$output_lc" == *"askforapproval is set to never"* ]]; then
  is_approval_policy_mismatch=1
fi

if (( is_numeric_failure == 0 && is_approval_policy_mismatch == 0 )); then
  jq -n '{continue: true}'
  exit 0
fi

if [[ "$tool_name" == "Bash" ]]; then
  append_repo_learning_entry "$cwd" "$command_excerpt" "$output_excerpt" "$exit_code" "$output_lc" || true
fi

context_message=""
if (( is_approval_policy_mismatch == 1 )); then
  context_message="Bash command was blocked by a policy-layer mismatch: command classifier required approval, but runtime AskForApproval is set to Never (permission mode ${permission_mode}). Treat session/runtime policy as the effective source for this denial and summarize that source before choosing a fallback."
elif [[ "$tool_name" == "apply_patch" || "$tool_name" == "Edit" || "$tool_name" == "Write" ]]; then
  context_message="Previous ${tool_name} tool call failed with exit code ${exit_code}. Summarize the failure before retrying and change approach."
else
  context_message="Previous Bash command failed with exit code ${exit_code}. Summarize the failure before retrying and change approach."
fi

if [[ "$output_lc" == *"operation not permitted"* || "$output_lc" == *"permission denied"* ]]; then
  context_message="${context_message} This looks like a sandbox or approval boundary; request the minimal required permission change instead of retrying unchanged."
elif [[ "$output_lc" == *"command not found"* ]]; then
  context_message="${context_message} This looks like a missing tool dependency; verify command availability before retrying."
fi

if [[ -n "$output_excerpt" ]]; then
  context_message="${context_message} Error excerpt: ${output_excerpt}"
fi

if ! hook_runtime_should_emit_context "$input_json" "post-tool-use-review" "$context_message"; then
  event_record="$(hook_runtime_event_envelope "$input_json" "post-tool-use" "post-tool-use-review" "suppressed_duplicate" "$context_message")"
  if [[ -n "$event_record" ]]; then
    hook_runtime_append_jsonl "$(hook_runtime_log_path "hook-events")" "$event_record" "post-tool-use-review"
  fi
  jq -n '{continue: true}'
  exit 0
fi

system_message="PostToolUse noticed a failed ${tool_name} execution."
if (( is_approval_policy_mismatch == 1 )); then
  system_message="PostToolUse detected runtime approval-policy mismatch."
fi

event_record="$(hook_runtime_event_envelope "$input_json" "post-tool-use" "post-tool-use-review" "warn" "$context_message")"
if [[ -n "$event_record" ]]; then
  hook_runtime_append_jsonl "$(hook_runtime_log_path "hook-events")" "$event_record" "post-tool-use-review"
fi

jq -n \
  --arg additional_context "$context_message" \
  --arg system_message "$system_message" \
  --arg timeout_class "$timeout_class" \
  '{
    continue: true,
    systemMessage: $system_message,
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      additionalContext: $additional_context,
      arbitrationCandidate: {
        gate_id: "post-command-review",
        owner_layer: "global_codex",
        source_path: "~/.codex/hooks/post-tool-use-review.sh",
        action: "allow-with-warning",
        reason: $additional_context,
        is_canonical_owner: false,
        timeout_class: $timeout_class
      }
    }
  }'
