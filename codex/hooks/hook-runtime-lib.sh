#!/usr/bin/env bash

dots_lib_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_lib_dir/../scripts/admit-hook-fixture.py" '{}' || return $?

# Shared helpers for Codex hook receipts. This file is sourced by hook scripts;
# keep it dependency-light and fail-open for telemetry writes.

: "${HOOK_RUNTIME_INVOCATION_SUFFIX:=$(date -u '+%Y%m%dT%H%M%SZ' 2>/dev/null || printf 'unknown-time')-$$-${RANDOM:-0}}"

hook_runtime_now() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

hook_runtime_usage_root() {
  local usage_root
  usage_root="$HOME/.codex/usage-data"
  if [[ -n "${CODEX_HOOK_USAGE_ROOT:-}" ]]; then
    usage_root="$CODEX_HOOK_USAGE_ROOT"
  fi
  printf '%s\n' "$usage_root"
}

hook_runtime_safe_id() {
  local value
  value="$1"
  if [[ -z "$value" || "$value" == "null" ]]; then
    value="unknown"
  fi
  printf '%s' "$value" | tr -c 'A-Za-z0-9._=-' '_'
}

hook_runtime_log_path() {
  local usage_root
  usage_root="$(hook_runtime_usage_root)"
  printf '%s/%s.jsonl\n' "$usage_root" "$1"
}

hook_runtime_writer_health_path() {
  hook_runtime_log_path "hook-writer-health"
}

hook_runtime_append_writer_health() {
  local hook_name="$1"
  local target_path="$2"
  local status="$3"
  local reason="$4"
  local health_path
  local health_record

  health_path="$(hook_runtime_writer_health_path)"
  mkdir -p "$(dirname "$health_path")" 2>/dev/null || return 0
  health_record="$(
    jq -cn \
      --arg schema_version "codex-hook-writer-health/v1" \
      --arg recorded_at "$(hook_runtime_now)" \
      --arg hook_name "$hook_name" \
      --arg target_path "$target_path" \
      --arg status "$status" \
      --arg reason "$reason" \
      '{
        schema_version: $schema_version,
        recorded_at: $recorded_at,
        hook_name: $hook_name,
        target_path: $target_path,
        status: $status,
        reason: $reason
      }' 2>/dev/null || true
  )"
  if [[ -n "$health_record" ]]; then
    printf '%s\n' "$health_record" >>"$health_path" 2>/dev/null || true
  fi
}

hook_runtime_bool_enabled() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON|enabled|ENABLED)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

hook_runtime_prompt_safety_block_reason() {
  # Phrase heuristics identify direct requests only. Quotes/code are data;
  # explicitly negated phrases are not instructions to perform that action.
  python3 -I -S - "$1" <<'PY'
import re
import sys

prompt = sys.argv[1].lower()
prompt = re.sub(r"```[\s\S]*?```|~~~[\s\S]*?~~~", " ", prompt)
prompt = re.sub(r'`[^`]*`|"[^"\n]*"|(?<!\w)\x27[^\x27\n]*\x27', " ", prompt)
groups = [['ignore previous instructions', 'ignore the previous instructions', 'ignore all previous instructions', 'forget the previous instructions', 'forget previous instructions', 'override the system prompt', 'ignore system prompt', 'ignore developer instructions', 'ignore repo instructions', 'ignore project instructions', 'ignore agents.md', 'disregard agents.md', 'bypass the guardrails', 'disable the guardrails', 'ignore the guardrails'], ['skip codestyle', 'skip codestyle.md', 'skip codex/instructions/codestyle.md', 'ignore codestyle', 'ignore instructions/codestyle.md', 'ignore codex/instructions/codestyle.md', "don't read codestyle", "don't read instructions/codestyle.md", "don't read codex/instructions/codestyle.md", 'do not read codestyle', 'do not read instructions/codestyle.md', 'do not read codex/instructions/codestyle.md', 'bypass codestyle']]
messages = [
    "Cannot ignore higher-priority system or developer instructions. Resolve repo guidance conflicts using the active instruction hierarchy.",
    "Cannot bypass codestyle routing. For codex technical tasks, read instructions/CODESTYLE.md first and follow the matching codestyle module.",
]
for phrases, message in zip(groups, messages):
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(phrase) for phrase in phrases) + r")(?!\w)"
    for match in re.finditer(pattern, prompt):
        prefix = prompt[:match.start()]
        if re.search(r"(?:\bdo not|\bdon.t|\bnever|\bmust not|\bshould not|\bshouldn.t|\bmustn.t|\bnot to|\bavoid)\s+$", prefix):
            continue
        print(message)
        raise SystemExit(0)
PY
}

hook_runtime_otel_enabled() {
  hook_runtime_bool_enabled "${CODEX_HOOK_OTEL:-}" \
    || hook_runtime_bool_enabled "${CODEX_HOOK_TELEMETRY:-}"
}

hook_runtime_otel_strict_enabled() {
  hook_runtime_bool_enabled "${CODEX_HOOK_OTEL_STRICT:-}" \
    || hook_runtime_bool_enabled "${CODEX_HOOK_TELEMETRY_STRICT:-}"
}

hook_runtime_otel_logs_endpoint() {
  local endpoint

  endpoint="${CODEX_HOOK_OTEL_ENDPOINT:-${OTEL_EXPORTER_OTLP_ENDPOINT:-http://127.0.0.1:4318}}"
  endpoint="${endpoint%/}"
  case "$endpoint" in
    http://*|https://*) ;;
    *)
      printf ''
      return 0
      ;;
  esac

  case "$endpoint" in
    */v1/logs)
      printf '%s\n' "$endpoint"
      ;;
    */v1/traces)
      printf '%s/v1/logs\n' "${endpoint%/v1/traces}"
      ;;
    */v1/metrics)
      printf '%s/v1/logs\n' "${endpoint%/v1/metrics}"
      ;;
    *)
      printf '%s/v1/logs\n' "$endpoint"
      ;;
  esac
}

hook_runtime_otel_timeout_seconds() {
  local timeout_seconds

  timeout_seconds="${CODEX_HOOK_OTEL_TIMEOUT_SECONDS:-1}"
  if ! [[ "$timeout_seconds" =~ ^[0-9]+$ ]] || [[ "$timeout_seconds" -lt 1 ]]; then
    timeout_seconds="1"
  fi
  printf '%s\n' "$timeout_seconds"
}

hook_runtime_otel_time_unix_nano() {
  local seconds

  seconds="$(date -u '+%s' 2>/dev/null || true)"
  if [[ ! "$seconds" =~ ^[0-9]+$ ]]; then
    seconds="0"
  fi
  printf '%s000000000\n' "$seconds"
}

hook_runtime_otel_log_payload() {
  local record="$1"
  local hook_name="$2"
  local time_unix_nano

  time_unix_nano="$(hook_runtime_otel_time_unix_nano)"
  printf '%s' "$record" | jq -c \
    --arg time_unix_nano "$time_unix_nano" \
    --arg hook_name "$hook_name" \
    '
      def string_value($value):
        if $value == null then null else ($value | tostring) end;
      def bounded($value):
        (string_value($value)) as $string
        | if ($string == null or ($string | length) > 96) then null else $string end;
      def attr($key; $value):
        (bounded($value)) as $string
        | if ($string == null or $string == "") then empty
          else {key: $key, value: {stringValue: $string}}
          end;
      def event_name:
        bounded(.event // .hook_event_name // $hook_name);
      def decision_name:
        bounded(.decision // .status // .artifact_status // .validation_runtime.preflight_status);
      def failure_class:
        bounded(.failure_class)
        // (if ((.decision // "") | tostring) == "deny" then "policy_denied"
            elif ((.decision // "") | tostring) == "block" then "completion_blocked"
            elif ((.status // "") | tostring | test("^failed")) then "writer_failure"
            elif ((.status // "") | tostring | test("^blocked")) then ((.status // "") | tostring)
            else null
            end);
      def severity:
        if (((.decision // "") | tostring) == "deny")
          or (((.decision // "") | tostring) == "block")
          or (((.status // "") | tostring | test("^(failed|blocked)")))
        then "WARN"
        else "INFO"
        end;
      {
        resourceLogs: [
          {
            resource: {
              attributes: [
                attr("service.name"; "codex-hooks"),
                attr("service.namespace"; "codex"),
                attr("repo.name"; .repo.name)
              ]
            },
            scopeLogs: [
              {
                scope: {
                  name: "codex.hooks",
                  version: "codex-hook-otel/v1"
                },
                logRecords: [
                  {
                    timeUnixNano: $time_unix_nano,
                    severityText: severity,
                    body: {
                      stringValue: ("codex.hook." + ((event_name // $hook_name) | gsub("[^A-Za-z0-9_.-]"; "_")))
                    },
                    attributes: [
                      attr("hook.name"; $hook_name),
                      attr("hook.event"; event_name),
                      attr("hook.decision"; decision_name),
                      attr("agent.role"; .agent_type),
                      attr("tool.name"; .tool_name),
                      attr("validator.name"; .validator_name),
                      attr("validation.status"; .validation_runtime.preflight_status),
                      attr("command.exit_code"; .command_exit_code // .exit_code),
                      attr("failure_class"; failure_class),
                      attr("artifact.status"; .artifact_status),
                      attr("runtime_card.schema"; .runtime_card.version // .runtime_card_schema),
                      attr("runtime_card.hash_present"; ((.runtime_card.sha256 // .runtime_card_hash // null) != null)),
                      attr("telemetry.confidence"; .telemetry_confidence)
                    ]
                  }
                ]
              }
            ]
          }
        ]
      }
    ' 2>/dev/null || true
}

hook_runtime_emit_otel_log() {
  local record="$1"
  local hook_name="$2"
  local endpoint
  local payload
  local timeout_seconds

  if ! hook_runtime_otel_enabled; then
    return 0
  fi

  endpoint="$(hook_runtime_otel_logs_endpoint)"
  if [[ -z "$endpoint" ]]; then
    hook_runtime_append_writer_health "$hook_name" "otel" "failed" "otel_endpoint_invalid"
    if hook_runtime_otel_strict_enabled; then
      return 1
    fi
    return 0
  fi

  payload="$(hook_runtime_otel_log_payload "$record" "$hook_name")"
  if [[ -z "$payload" ]]; then
    hook_runtime_append_writer_health "$hook_name" "$endpoint" "failed" "otel_payload_json_failed"
    if hook_runtime_otel_strict_enabled; then
      return 1
    fi
    return 0
  fi

  if ! command -v curl >/dev/null 2>&1; then
    hook_runtime_append_writer_health "$hook_name" "$endpoint" "failed" "otel_curl_unavailable"
    if hook_runtime_otel_strict_enabled; then
      return 1
    fi
    return 0
  fi

  timeout_seconds="$(hook_runtime_otel_timeout_seconds)"
  if ! printf '%s' "$payload" | curl -fsS -m "$timeout_seconds" \
    -H "Content-Type: application/json" \
    --data-binary @- \
    "$endpoint" >/dev/null 2>&1; then
    hook_runtime_append_writer_health "$hook_name" "$endpoint" "failed" "otel_export_failed"
    if hook_runtime_otel_strict_enabled; then
      return 1
    fi
  fi
  return 0
}

hook_runtime_append_jsonl() {
  local log_path="$1"
  local record="$2"
  local hook_name="$3"

  if [[ -z "$record" || "$record" != \{* || "$record" != *\} ]]; then
    return 0
  fi
  if [[ "$record" == *$'\n'* || "$record" == *$'\r'* || "$record" =~ ^[[:space:]] || "$record" =~ [[:space:]]$ ]]; then
    hook_runtime_append_writer_health "$hook_name" "$log_path" "failed" "invalid_record"
    return 0
  fi
  if ! printf '%s' "$record" | jq -ce 'if type == "object" then . else empty end' >/dev/null 2>&1; then
    hook_runtime_append_writer_health "$hook_name" "$log_path" "failed" "invalid_record"
    return 0
  fi
  if ! mkdir -p "$(dirname "$log_path")" 2>/dev/null; then
    hook_runtime_append_writer_health "$hook_name" "$log_path" "failed" "mkdir_failed"
    return 0
  fi
  if ! printf '%s\n' "$record" >>"$log_path" 2>/dev/null; then
    hook_runtime_append_writer_health "$hook_name" "$log_path" "failed" "append_failed"
    return 0
  fi
  if ! hook_runtime_emit_otel_log "$record" "$hook_name"; then
    return 1
  fi
  return 0
}

hook_runtime_json_field() {
  local input_json="$1"
  local filter="$2"
  printf '%s' "$input_json" | jq -r "$filter // \"\"" 2>/dev/null || true
}

hook_runtime_should_emit_context() {
  local input_json="$1"
  local hook_name="$2"
  local context_message="$3"
  local session_id
  local cache_root
  local cache_key
  local cache_path

  if hook_runtime_bool_enabled "${CODEX_HOOK_CONTEXT_DEDUP_DISABLE:-}"; then
    return 0
  fi
  if [[ -z "$context_message" ]]; then
    return 1
  fi

  session_id="$(hook_runtime_json_field "$input_json" '.session_id')"
  if [[ -z "$session_id" || "$session_id" == "null" ]]; then
    return 0
  fi

  cache_root="$(hook_runtime_usage_root)/context-dedupe"
  cache_key="$(
    printf '%s\037%s\037%s' "$session_id" "$hook_name" "$context_message" \
      | shasum -a 256 \
      | awk '{print $1}'
  )"
  if [[ -z "$cache_key" ]]; then
    return 0
  fi

  cache_path="$cache_root/$cache_key"
  if [[ -e "$cache_path" ]]; then
    return 1
  fi
  mkdir -p "$cache_root" 2>/dev/null || return 0
  printf '%s\n' "$(hook_runtime_now)" >"$cache_path" 2>/dev/null || return 0
  return 0
}

hook_runtime_card_dir_for_session() {
  local session_id="$1"
  local usage_root
  local safe_session

  usage_root="$(hook_runtime_usage_root)"
  safe_session="$(hook_runtime_safe_id "$session_id")"
  printf '%s/runtime-cards/%s\n' "$usage_root" "$safe_session"
}

hook_runtime_card_path_for_ids() {
  local session_id="$1"
  local turn_id="$2"
  local unique_suffix
  local safe_turn

  if [[ -z "$session_id" || "$session_id" == "null" || -z "$turn_id" || "$turn_id" == "null" ]]; then
    unique_suffix="$HOOK_RUNTIME_INVOCATION_SUFFIX"
    if [[ -z "$session_id" || "$session_id" == "null" ]]; then
      session_id="unknown-session-$unique_suffix"
    fi
    if [[ -z "$turn_id" || "$turn_id" == "null" ]]; then
      turn_id="unknown-turn-$unique_suffix"
    fi
  fi
  safe_turn="$(hook_runtime_safe_id "$turn_id")"
  printf '%s/%s.json\n' "$(hook_runtime_card_dir_for_session "$session_id")" "$safe_turn"
}

hook_runtime_card_path_for_input() {
  local input_json="$1"
  local session_id
  local turn_id

  session_id="$(hook_runtime_json_field "$input_json" '.session_id')"
  turn_id="$(hook_runtime_json_field "$input_json" '.turn_id')"
  hook_runtime_card_path_for_ids "$session_id" "$turn_id"
}

hook_runtime_latest_card_path() {
  local session_id="$1"
  local turn_id="$2"
  local exact_path
  local card_dir

  if [[ -n "${CODEX_RUNTIME_CARD_PATH:-}" && -f "$CODEX_RUNTIME_CARD_PATH" ]]; then
    printf '%s\n' "$CODEX_RUNTIME_CARD_PATH"
    return 0
  fi

  if [[ -n "$session_id" && "$session_id" != "null" && -n "$turn_id" && "$turn_id" != "null" ]]; then
    exact_path="$(hook_runtime_card_path_for_ids "$session_id" "$turn_id")"
    if [[ -f "$exact_path" ]]; then
      printf '%s\n' "$exact_path"
      return 0
    fi
  fi

	if [[ -z "$session_id" || "$session_id" == "null" ]]; then
		return 0
	fi
	card_dir="$(hook_runtime_card_dir_for_session "$session_id")"
	if [[ -d "$card_dir" ]]; then
		if [[ "$(stat -f '%m' "$card_dir" 2>/dev/null || true)" =~ ^[0-9]+$ ]]; then
			find "$card_dir" -type f -name '*.json' -exec stat -f '%m %N' {} \; 2>/dev/null | sort -n | tail -n 1 | cut -d' ' -f2-
		else
			find "$card_dir" -type f -name '*.json' -exec stat -c '%Y %n' {} \; 2>/dev/null | sort -n | tail -n 1 | cut -d' ' -f2-
		fi
	fi
}

hook_runtime_sha256_file() {
  local path="$1"

  if [[ -z "$path" || ! -f "$path" ]]; then
    printf ''
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" 2>/dev/null | awk '{print $1}'
    return 0
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" 2>/dev/null | awk '{print $1}'
    return 0
  fi
  printf ''
}

hook_runtime_card_hash_for_input() {
  local input_json="$1"
  local session_id
  local turn_id
  local card_path

  session_id="$(hook_runtime_json_field "$input_json" '.session_id')"
  turn_id="$(hook_runtime_json_field "$input_json" '.turn_id')"
  card_path="$(hook_runtime_latest_card_path "$session_id" "$turn_id")"
  hook_runtime_sha256_file "$card_path"
}

hook_runtime_card_ref_args() {
  local input_json="$1"
  local session_id
  local turn_id
  local card_path
  local card_hash

  session_id="$(hook_runtime_json_field "$input_json" '.session_id')"
  turn_id="$(hook_runtime_json_field "$input_json" '.turn_id')"
  card_path="$(hook_runtime_latest_card_path "$session_id" "$turn_id")"
  card_hash="$(hook_runtime_sha256_file "$card_path")"
  printf '%s\037%s\n' "$card_path" "$card_hash"
}

hook_runtime_write_card() {
  local input_json="$1"
  local repo_root="$2"
  local git_root="$3"
  local repo_name="$4"
  local branch_name="$5"
  local head_sha="$6"
  local dirty_count="$7"
  local preflight_status="$8"
  local preflight_summary="$9"
  shift 9
  local project_override_drift="$1"
  local project_override_excerpt="$2"
  local card_path
  local tmp_path
  local card_record

  card_path="$(hook_runtime_card_path_for_input "$input_json")"
  mkdir -p "$(dirname "$card_path")" 2>/dev/null || {
    hook_runtime_append_writer_health "session-start" "$card_path" "failed" "runtime_card_mkdir_failed"
    return 0
  }

  card_record="$(
    printf '%s' "$input_json" | jq -c \
      --arg schema_version "codex-runtime-card/v2" \
      --arg recorded_at "$(hook_runtime_now)" \
      --arg repo_root "$repo_root" \
      --arg git_root "$git_root" \
      --arg repo_name "$repo_name" \
      --arg branch_name "$branch_name" \
      --arg head_sha "$head_sha" \
      --arg dirty_count "$dirty_count" \
      --arg preflight_status "$preflight_status" \
      --arg preflight_summary "$preflight_summary" \
      --arg project_override_drift "$project_override_drift" \
      --arg project_override_excerpt "$project_override_excerpt" \
      '{
        schema_version: $schema_version,
        recorded_at: $recorded_at,
        runtime_card: {
          version: "codex-runtime-card/v2",
          freshness: {
            status: "fresh",
            generated_at: $recorded_at,
            source_hook: "SessionStart"
          }
        },
        session: {
          session_id: (.session_id // null),
          turn_id: (.turn_id // null),
          source: (.source // "startup"),
          cwd: (.cwd // null),
          model: (.model // null),
          permission_mode: (.permission_mode // "default"),
          transcript_path: (.transcript_path // null)
        },
        repo: {
          root: (if $repo_root == "" then null else $repo_root end),
          git_root: (if $git_root == "" then null else $git_root end),
          name: (if $repo_name == "" then null else $repo_name end),
          branch: (if $branch_name == "" then null else $branch_name end),
          head_sha: (if $head_sha == "" then null else $head_sha end),
          dirty_count: (($dirty_count | tonumber?) // 0)
        },
        validation_runtime: {
          preflight_status: $preflight_status,
          preflight_summary: (if $preflight_summary == "" then null else $preflight_summary end),
          project_override_drift: ($project_override_drift == "1"),
          project_override_excerpt: (if $project_override_excerpt == "" then null else $project_override_excerpt end)
        },
        resume_reconciliation: {
          required: ((.source // "startup") == "resume"),
          status: (if (.source // "startup") == "resume" then "required" else "not_required" end),
          checklist: [
            "reconcile_current_goal",
            "reconcile_memory_runtime",
            "reconcile_mcp_inventory",
            "reconcile_evidence_artifacts"
          ]
        },
        tool_inventory: {
          scope: "thread",
          status: "unknown",
          source: "hook_payload_unavailable"
        },
        memory_runtime: {
          status: "unknown",
          source: "hook_payload_unavailable"
        },
        permission_profile: {
          mode: (.permission_mode // "default"),
          decision_trace_required: true
        },
        subagent_receipts: {
          schema_version: "codex-subagent-lifecycle/v1",
          artifact_receipt_schema: "codex-subagent-artifact-receipt/v1",
          blocked_statuses: ["blocked_runtime", "blocked_missing_artifact", "blocked_validation"]
        },
        compaction_continuity: {
          receipt_schema: "codex-compaction-continuity/v1",
          last_pre_compact_hash: null,
          last_post_compact_hash: null
        },
        review_state: {
          status: "unknown",
          source: "hook_payload_unavailable"
        },
        goal_claim_verifier: {
          status: "armed",
          confidence: "only_blocks_explicit_runtime_card_contradictions"
        },
        evidence_writer_health: {
          status: "ok",
          health_log: "hook-writer-health.jsonl"
        }
      }' 2>/dev/null || true
  )"

  if [[ -z "$card_record" ]]; then
    hook_runtime_append_writer_health "session-start" "$card_path" "failed" "runtime_card_json_failed"
    return 0
  fi

  tmp_path="$(mktemp "${card_path}.tmp.XXXXXX" 2>/dev/null)" || {
    hook_runtime_append_writer_health "session-start" "$card_path" "failed" "runtime_card_tmp_create_failed"
    return 0
  }
  if printf '%s\n' "$card_record" >"$tmp_path" 2>/dev/null && mv "$tmp_path" "$card_path" 2>/dev/null; then
    return 0
  fi
  rm -f "$tmp_path" 2>/dev/null || true
  hook_runtime_append_writer_health "session-start" "$card_path" "failed" "runtime_card_write_failed"
  return 0
}

hook_runtime_event_envelope() {
  local input_json="$1"
  local event="$2"
  local hook_name="$3"
  local decision="$4"
  local reason="$5"
  local card_ref
  local runtime_card_path
  local runtime_card_hash

  card_ref="$(hook_runtime_card_ref_args "$input_json")"
  IFS=$'\037' read -r runtime_card_path runtime_card_hash <<<"$card_ref"
  printf '%s' "$input_json" | jq -c \
    --arg schema_version "codex-hook-event/v1" \
    --arg recorded_at "$(hook_runtime_now)" \
    --arg event "$event" \
    --arg hook_name "$hook_name" \
    --arg decision "$decision" \
    --arg reason "$reason" \
    --arg runtime_card_path "$runtime_card_path" \
    --arg runtime_card_hash "$runtime_card_hash" \
    '{
      schema_version: $schema_version,
      recorded_at: $recorded_at,
      event: $event,
      hook_name: $hook_name,
      hook_event_name: (.hook_event_name // null),
      session_id: (.session_id // null),
      turn_id: (.turn_id // null),
      cwd: (.cwd // null),
      model: (.model // null),
      permission_mode: (.permission_mode // null),
      decision: $decision,
      reason: (if $reason == "" then null else $reason end),
      runtime_card: {
        path: (if $runtime_card_path == "" then null else $runtime_card_path end),
        sha256: (if $runtime_card_hash == "" then null else $runtime_card_hash end)
      },
      telemetry_confidence: "hook_observed"
    }' 2>/dev/null || true
}
