#!/bin/bash -p
set -euo pipefail
# shellcheck source=codex/hooks/hook-runtime-path.sh
. "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh"

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
. "$hook_dir/hook-runtime-lib.sh"

if ! command -v jq >/dev/null 2>&1; then
  printf '{"continue":true}\n'
  exit 0
fi

if ! printf '%s' "$input_json" | jq -e . >/dev/null 2>&1; then
  printf '{"continue":true}\n'
  exit 0
fi

agent_id="$(printf '%s' "$input_json" | jq -r '.agent_id // ""')"
agent_type="$(printf '%s' "$input_json" | jq -r '.agent_type // ""')"
expected_artifact=""
expected_manifest=""

append_telemetry() {
  local record="$1"
  local log_file=""

  set +u
  log_file="$CODEX_SUBAGENT_HOOK_LOG"
  set -u

  if [[ -z "$log_file" ]]; then
    log_file="$(hook_runtime_log_path "subagent-hooks")"
  fi

  hook_runtime_append_jsonl "$log_file" "$record" "subagent-start"
}

telemetry_record="$(
  printf '%s' "$input_json" | jq -c \
    --arg recorded_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --arg expected_artifact "$expected_artifact" \
    --arg expected_manifest "$expected_manifest" \
    --arg runtime_card_hash "$(hook_runtime_card_hash_for_input "$input_json")" \
    '{
      schema_version: "codex-subagent-lifecycle/v1",
      recorded_at: $recorded_at,
      event: "subagent-start",
      hook_event_name: (.hook_event_name // "SubagentStart"),
      hook_name: "subagent-start",
      session_id: (.session_id // null),
      turn_id: (.turn_id // null),
      agent_id: (.agent_id // null),
      agent_type: (.agent_type // null),
      cwd: (.cwd // null),
      transcript_path: (.transcript_path // null),
      expected_artifact: (if $expected_artifact == "" then null else $expected_artifact end),
      expected_artifacts: (if $expected_artifact == "" then [] else [$expected_artifact] end),
      expected_manifest: (if $expected_manifest == "" then null else $expected_manifest end),
      runtime_card_hash: (if $runtime_card_hash == "" then null else $runtime_card_hash end),
      telemetry_confidence: "hook_observed"
    }' 2>/dev/null || true
)"

if [[ -n "$telemetry_record" ]]; then
  append_telemetry "$telemetry_record"
fi

if [[ -z "$agent_id" ]]; then
  agent_id="unknown"
fi

if [[ -z "$agent_type" ]]; then
  agent_type="unknown"
fi

context="Subagent lifecycle context:
- agent_id=$agent_id
- agent_type=$agent_type
- Return candidate, scope, findings or verdict, exact commands/results, and limitations directly to the coordinator.
- The coordinator owns durable records and preserves attribution of reported versus independently reproduced evidence.
- Write source files and tests only within assigned implementation scope. Write coordination artifacts only when explicitly assigned, never merely because of a role name.
- Treat the latest orchestrator/mailbox instruction as binding task input. If it conflicts with an earlier task message, follow the newest mailbox instruction unless a higher-priority system/developer/role contract blocks it.
- If blocked, return STATUS: blocked_runtime, STATUS: blocked_missing_artifact, or STATUS: blocked_validation with exact failure text and the coordinator next step."


jq -n --arg context "$context" '{
  continue: true,
  hookSpecificOutput: {
    hookEventName: "SubagentStart",
    additionalContext: $context
  }
}'
