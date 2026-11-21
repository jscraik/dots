#!/bin/bash -p

set -euo pipefail
# shellcheck source=codex/hooks/hook-runtime-path.sh
. "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh"

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
. "$hook_dir/hook-runtime-lib.sh"

if ! command -v jq >/dev/null 2>&1; then
  printf '{"continue":true}\n'
  exit 0
fi

trigger="$(jq -r '.trigger // ""' <<<"$input_json" 2>/dev/null || true)"
case "$trigger" in
  manual|auto) ;;
  *)
    printf '{"continue":true}\n'
    exit 0
    ;;
esac

event_record="$(
  jq -c \
    --arg schema_version "codex-compaction-continuity/v1" \
    --arg event "pre-compact" \
    --arg recorded_at "$(hook_runtime_now)" \
    --arg runtime_card_hash "$(hook_runtime_card_hash_for_input "$input_json")" \
    '{
      schema_version: $schema_version,
      recorded_at: $recorded_at,
      event: $event,
      hook_event_name: (.hook_event_name // null),
      session_id: (.session_id // null),
      turn_id: (.turn_id // null),
      cwd: (.cwd // null),
      transcript_path: (.transcript_path // null),
      model: (.model // null),
      trigger: (.trigger // null),
      runtime_card_hash: (if $runtime_card_hash == "" then null else $runtime_card_hash end),
      continuity_gate: "pre_compact_receipt"
    }' <<<"$input_json" 2>/dev/null || true
)"

if [[ -n "$event_record" ]]; then
  log_path="${CODEX_COMPACT_HOOK_LOG:-$(hook_runtime_log_path "compact-hooks")}"
  hook_runtime_append_jsonl "$log_path" "$event_record" "pre-compact"
fi

printf '{"continue":true}\n'
