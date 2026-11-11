#!/usr/bin/env bash
set -euo pipefail

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
. "$hook_dir/hook-runtime-lib.sh"

# Completion text is evidence for the coordinator, not an artifact assignment.
# Required artifacts are checked explicitly with validate-agent-artifacts.py.
# Never block a child or read arbitrary paths inferred from WROTE:/STATUS: text.
if command -v jq >/dev/null 2>&1 && printf '%s' "$input_json" | jq -e 'type == "object"' >/dev/null 2>&1; then
  telemetry_record="$(
    printf '%s' "$input_json" | jq -c \
      --arg recorded_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg runtime_card_hash "$(hook_runtime_card_hash_for_input "$input_json")" \
      '{
        schema_version: "codex-subagent-lifecycle/v1",
        recorded_at: $recorded_at,
        event: "subagent-stop",
        hook_event_name: (.hook_event_name // "SubagentStop"),
        hook_name: "subagent-stop",
        session_id: (.session_id // null),
        turn_id: (.turn_id // null),
        agent_id: (.agent_id // null),
        agent_type: (.agent_type // null),
        cwd: (.cwd // null),
        classification: "completed_no_artifact_required",
        runtime_card_hash: (if $runtime_card_hash == "" then null else $runtime_card_hash end),
        telemetry_confidence: "hook_observed"
      }' 2>/dev/null || true
  )"
  if [[ -n "$telemetry_record" ]]; then
    log_file="${CODEX_SUBAGENT_HOOK_LOG:-}"
    if [[ -z "$log_file" ]]; then
      log_file="$(hook_runtime_log_path "subagent-hooks")"
    fi
    hook_runtime_append_jsonl "$log_file" "$telemetry_record" "subagent-stop" || true
  fi
fi

printf '{"continue":true}\n'
