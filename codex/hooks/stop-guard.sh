#!/bin/bash -p

set -euo pipefail
input_json="$(/bin/cat)"
# Native Stop retries terminate after one block. Use only the isolated system
# interpreter so retries need neither the toolchain nor admission/receipt access.
stop_hook_active="$(printf '%s' "$input_json" | /usr/bin/python3 -I -S -c '
import json, sys
payload = json.load(sys.stdin)
if not isinstance(payload, dict):
    raise ValueError("Stop input must be an object")
print("true" if payload.get("stop_hook_active") is True else "false")
')" || exit 2
if [[ "$stop_hook_active" == "true" ]]; then
  printf '%s\n' '{"continue":true}'
  exit 0
fi
# shellcheck source=codex/hooks/hook-runtime-path.sh
. "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh" || exit 2

dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
. "$hook_dir/hook-runtime-lib.sh" || exit 2
last_message="$(printf '%s' "$input_json" | jq -r '.last_assistant_message // ""')"

normalized_message="$(printf '%s' "$last_message" | tr '[:upper:]' '[:lower:]')"

block_reason=""
draft_advisory=""
line_negates_claim() {
  local line="$1"
  local claim="$2"
  printf '%s' "$line" | grep -Eqi "(^|[^[:alpha:]])(not|isn.t|never|cannot|can.t|unable to|fails? to|failed to|is[[:space:]]+not|are[[:space:]]+not|was[[:space:]]+not|were[[:space:]]+not)[[:space:]]+(yet|currently|fully|still|actually|really|necessarily|now|ever)?[[:space:]]*${claim}([^[:alpha:]]|$)|(^|[^[:alpha:]])${claim}[[:space:]]*(is|=|:)?[[:space:]]*(false|no|failed)([^[:alpha:]]|$)"
}

append_unique_claim() {
  local claim="$1"
  local existing
  set +u
  for existing in "${claims[@]}"; do
    if [[ "$existing" == "$claim" ]]; then
      set -u
      return 0
    fi
  done
  set -u
  claims+=("$claim")
}

readiness_claims_in_message() {
  local line
  local lower_line
  local claims=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    lower_line="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])mergeable([^[:alpha:]]|$)' && ! line_negates_claim "$lower_line" "mergeable"; then
      append_unique_claim "mergeable"
    fi
    if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])ready([^[:alpha:]]|$)' \
      && ! line_negates_claim "$lower_line" "ready" \
      && printf '%s' "$lower_line" | grep -Eq '(ready[[:space:]]+(to|for)[[:space:]]+(merge|ship|push|commit|review|release|use)|pr[^.!?;]*ready|branch[^.!?;]*ready|ready[^.!?;]*(pr|branch|merge|ship|release|use))'; then
      append_unique_claim "ready"
    fi
    if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])green([^[:alpha:]]|$)' \
      && ! line_negates_claim "$lower_line" "green" \
      && printf '%s' "$lower_line" | grep -Eq '(ci|check|checks|test|tests|validation|validator|build|workflow|pipeline|pr|pull request|merge)'; then
      append_unique_claim "green"
    fi
    if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])shipped([^[:alpha:]]|$)' && ! line_negates_claim "$lower_line" "shipped"; then
      append_unique_claim "shipped"
    fi
    if printf '%s' "$lower_line" | grep -Eq '^[[:space:]]*(done|completed|complete|finished)[.![:space:]]*$' \
      && ! line_negates_claim "$lower_line" "(done|completed|complete|finished)"; then
      if printf '%s' "$lower_line" | grep -Eq 'done'; then
        append_unique_claim "done"
      elif printf '%s' "$lower_line" | grep -Eq 'completed'; then
        append_unique_claim "completed"
      elif printf '%s' "$lower_line" | grep -Eq 'finished'; then
        append_unique_claim "finished"
      else
        append_unique_claim "complete"
      fi
    fi
    if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])fixed([^[:alpha:]]|$)' \
      && ! line_negates_claim "$lower_line" "fixed" \
      && printf '%s' "$lower_line" | grep -Eq '(i[[:space:]]+fixed|we[[:space:]]+fixed|this[[:space:]]+is[[:space:]]+fixed|it[[:space:]]+is[[:space:]]+fixed|issue|bug|problem|regression|failure|config|hook|sandbox|computer use|browser|playwright)'; then
      append_unique_claim "fixed"
    fi
    if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])(done|completed|complete|finished)([^[:alpha:]]|$)' \
      && ! line_negates_claim "$lower_line" "(done|completed|complete|finished)" \
      && printf '%s' "$lower_line" | grep -Eq '(i[[:space:]]+(am|have)|we[[:space:]]+(have|are)|this[[:space:]]+is|it[[:space:]]+is|work|task|goal|implementation|change|fix|pr|pull request|branch|commit|push|merge|validation|validator|checks|tests|build|required work|remaining work|no required work|nothing remains|all set)'; then
      if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])done([^[:alpha:]]|$)'; then
        append_unique_claim "done"
      fi
      if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])completed([^[:alpha:]]|$)'; then
        append_unique_claim "completed"
      fi
      if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])complete([^[:alpha:]]|$)'; then
        append_unique_claim "complete"
      fi
      if printf '%s' "$lower_line" | grep -Eq '(^|[^[:alpha:]])finished([^[:alpha:]]|$)'; then
        append_unique_claim "finished"
      fi
    fi
  done <<<"$last_message"
  local joined=""
  set +u
  for word in "${claims[@]}"; do
    if [[ -z "$joined" ]]; then
      joined="$word"
    else
      joined="${joined}, ${word}"
    fi
  done
  set -u
  printf '%s' "$joined"
}

completion_claim_in_message() {
  local detected line
  local message
  # Join soft prose wraps, retaining paragraph, command, and standalone claim
  # boundaries. Never alter the original message used for evidence extraction.
  message="$(printf '%s\n' "$last_message" | awk '
    function flush() { if (prose != "") print prose; prose = "" }
    /^[[:space:]]*$/ || /^[[:space:]]*Command:/ { flush(); print; next }
    tolower($0) ~ /^[[:space:]]*(done|completed|complete|finished)[.!]?[[:space:]]*$/ {
      if (prose == "") { print; next }
    }
    { prose = prose (prose == "" ? "" : " ") $0 }
    /[.!?;][[:space:]]*$/ { flush() }
    END { flush() }
  ' | sed -E 's/([.!?])[[:blank:]]+/\1\
/g')"
  if printf '%s' "$message" | grep -Eqi 'no[[:space:]]+required[[:space:]]+work[[:space:]]+remains'; then
    return 0
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    # A bounded test result is not parent completion. Require an explicit
    # open-parent statement, and ignore only that test-result sentence.
    # Other completion claims and the general evidence gate remain active.
    if printf '%s' "$message" | grep -Eqi '(^|[.!?][[:space:]]|^)[[:space:]]*(the[[:space:]]+)?parent goal remains (active|incomplete|open)([.;[:space:]]|$)' \
      && printf '%s' "$line" | grep -Eqi '^[[:space:]]*((the[[:space:]]+)?([[:alnum:]_-]+[[:space:]]+)*tests (are|have been|have) (complete|completed|finished|done)|((i|we)[[:space:]]+)?(completed|finished)[[:space:]]+(the[[:space:]]+)?([[:alnum:]_-]+[[:space:]]+)*tests)[.!]?[[:space:]]*$'; then
      continue
    fi
    local last_message="$line"
    detected=", $(readiness_claims_in_message),"
    if [[ "$detected" == *", done,"* || "$detected" == *", completed,"* || "$detected" == *", complete,"* || "$detected" == *", finished,"* ]]; then
      return 0
    fi
  done <<<"$message"
  return 1
}

hosted_readiness_evidence_in_message() {
  # Hosted claims require hosted/current-state evidence. Local tests must not
  # authorize mergeability, PR readiness, or CI-green language.
  local evidence_line
  while IFS= read -r evidence_line || [[ -n "$evidence_line" ]]; do
    evidence_line_has_pass_result "$evidence_line" || continue
    if printf '%s' "$evidence_line" | grep -Eqi '^Command:[[:space:]]+(\(cwd=[^)]*\)[[:space:]]+)?(gh[[:space:]]+pr[[:space:]]+(checks|view)([[:space:]]|$)|gh[[:space:]]+api[[:space:]]+graphql([[:space:]]|$)|[^[:space:]]*pr-readiness[^[:space:]]*)'; then
      return 0
    fi
  done <<<"$last_message"
  printf '%s' "$normalized_message" | grep -Eq 'workflow-closeout/v1 receipt:[[:space:]]*[^[:space:]]+'
}

evidence_line_has_pass_result() {
  local evidence_line="$1"
  local result="${evidence_line##* -> }"
  [[ "$evidence_line" == Command:* ]] || return 1
  case "$result" in
    pass|"pass ("*) return 0 ;;
    *) return 1 ;;
  esac
}

local_validation_evidence_in_message_legacy() {
  # A local "fixed" claim needs a command that exercises the changed source.
  if printf '%s' "$last_message" | grep -Eqi '^Command:[[:space:]]+(\(cwd=[^)]*\)[[:space:]]+)?((pnpm|npm|yarn|bun)[[:space:]]+(run[[:space:]]+)?(test|lint|typecheck|check|verify)([[:alnum:]_.:-]*)|pytest|python(3)?[[:space:]]+-m[[:space:]]+(pytest|unittest)|uv[[:space:]]+run[[:space:]]+(pytest|[^[:space:][:cntrl:]]*(test|check|validate|verify)[^[:space:][:cntrl:]]*))[^[:cntrl:]]*[[:space:]]->[[:space:]]+pass([[:space:]]|[(]|$)'; then
    :
  fi
}

local_validation_evidence_in_message() {
  # A local "fixed" claim needs a command that exercises the changed source.
  while IFS= read -r evidence_line || [[ -n "$evidence_line" ]]; do
    [[ "$evidence_line" =~ ^Command:[[:space:]]+ ]] || continue
    evidence_line_has_pass_result "$evidence_line" || continue
    local command_text="${evidence_line#Command: }"
    command_text="${command_text% -> pass*}"
    local cwd_prefix_re='^\(cwd=[^)]*\)[[:space:]]+(.*)$'
    if [[ "$command_text" =~ $cwd_prefix_re ]]; then
      command_text="${BASH_REMATCH[1]}"
    fi
    local -a command_parts
    read -r -a command_parts <<<"$command_text"
    local interpreter="${command_parts[0]:-}"
    local script="${command_parts[1]:-}"
    if [[ "$interpreter" == "pnpm" || "$interpreter" == "npm" || "$interpreter" == "yarn" || "$interpreter" == "bun" ]]; then
      local package_script="${command_parts[1]:-}"
      if [[ "$package_script" == "run" ]]; then
        package_script="${command_parts[2]:-}"
      fi
      case "$package_script" in
        test|test:*|lint|lint:*|typecheck|typecheck:*|check|check:*|verify|verify:*) return 0 ;;
      esac
    fi
    if [[ "$interpreter" == "uv" && "${command_parts[1]:-}" == "run" ]]; then
      local uv_script="${command_parts[2]:-}"
      case "$uv_script" in
        pytest|*test*|*check*|*validate*|*verify*) return 0 ;;
      esac
    fi
    if [[ "$interpreter" == "bash" || "$interpreter" == "python" || "$interpreter" == "python3" ]]; then
      if [[ "$interpreter" == "python" || "$interpreter" == "python3" ]] && [[ "$script" == "-m" ]]; then
        case "${command_parts[2]:-}" in
          pytest|unittest) return 0 ;;
        esac
      fi
      if [[ "$script" =~ (^|[^[:alpha:]])(test|tests|validate|validation|verify|check|checks)([^[:alpha:]]|$) ]]; then
        return 0
      fi
    fi
  done <<<"$last_message"
  return 1
}

semantic_readiness_evidence_in_message() {
  local detected_claims="$1"
  if [[ "$detected_claims" == *"ready"* ]] && \
    printf '%s' "$normalized_message" | grep -Eqi '(^|[^[:alpha:]])ready[[:space:]]+(to[[:space:]]+(use|commit|push))([^[:alpha:]]|$)' && \
    ! printf '%s' "$normalized_message" | grep -Eqi '(^|[^[:alpha:]])(pr|ci|pull request|merge|release|hosted|github|pipeline|workflow)([^[:alpha:]]|$)' && \
    local_validation_evidence_in_message; then
    return 0
  fi
  if [[ "$detected_claims" == *"green"* ]] && \
    ! printf '%s' "$normalized_message" | grep -Eq '((^|[^[:alpha:]])ci([^[:alpha:]]|$)|pull request|(^|[^[:alpha:]])pr([^[:alpha:]]|$)|merge|workflow|pipeline|hosted|github)' && \
    local_validation_evidence_in_message; then
    return 0
  fi
  if [[ "$detected_claims" == *"mergeable"* || "$detected_claims" == *"ready"* || "$detected_claims" == *"green"* || "$detected_claims" == *"shipped"* ]]; then
    hosted_readiness_evidence_in_message
    return
  fi
  if [[ "$detected_claims" == *"fixed"* ]]; then
    local_validation_evidence_in_message
    return
  fi
  # Completion language remains bound to the general evidence contract.
  hosted_readiness_evidence_in_message || local_validation_evidence_in_message
}
for marker in "todo" "tbd" "fixme" "lorem ipsum" "[insert" "coming soon" "left as an exercise" "not implemented"; do
  if [[ "$normalized_message" == *"$marker"* ]]; then
    draft_advisory="Draft-marker text detected. Quoted examples, code, audit findings, and explicitly incomplete work are permitted; do not hide truthful limitations."
    break
  fi
done

if printf '%s' "$last_message" | grep -Eq '(^|[[:space:]])[-*][[:space:]]\[[[:space:]]\]'; then
  draft_advisory="Pending checklist detected. Report requested work as incomplete when appropriate; an honest blocked or pending checklist is permitted."
fi

if [[ -z "$block_reason" ]] && printf '%s' "$normalized_message" | grep -Eq '(did not run|didn.t run|have not run|haven.t run|unable to verify|could not verify|couldn.t verify)'; then
  if ! printf '%s' "$normalized_message" | grep -Eq '(because|due to|since|per your request|as requested)'; then
    block_reason="Rewrite the response before stopping: if validation was skipped, state the reason clearly or run the smallest relevant check."
  fi
fi

if [[ -z "$block_reason" ]] && completion_claim_in_message; then
  session_id="$(hook_runtime_json_field "$input_json" '.session_id')"
  turn_id="$(hook_runtime_json_field "$input_json" '.turn_id')"
  runtime_card_path="$(hook_runtime_latest_card_path "$session_id" "$turn_id")"
  if [[ -n "$runtime_card_path" && -f "$runtime_card_path" ]]; then
    active_goal_status="$(jq -r '(.goal_runtime.status // .goal.status // "")' "$runtime_card_path" 2>/dev/null || true)"
    if [[ "$active_goal_status" == "active" ]]; then
      block_reason="Rewrite before stopping: the final message claims completion, but the runtime card still shows an active goal. Update the goal truth or describe remaining work instead of claiming done."
    fi
  fi
fi

detected_claims="$(readiness_claims_in_message)"
advisory_reason="$draft_advisory"
if [[ -z "$block_reason" && -n "$detected_claims" ]]; then
  if ! semantic_readiness_evidence_in_message "$detected_claims"; then
    if [[ "$detected_claims" == *"mergeable"* || "$detected_claims" == *"ready"* || "$detected_claims" == *"green"* || "$detected_claims" == *"shipped"* ]]; then
      if [[ "${CODEX_STOP_CLAIM_MODE:-advisory}" == "block" ]]; then
        block_reason="Stop hook blocked delivery/readiness claim(s): ${detected_claims}. Preserve the substantive answer above; only revise the claim/evidence portion. Add exact hosted evidence using \"Command: <exact hosted command> -> pass (<reason>)\", or cite a workflow-closeout/v1 receipt path/reference. If hosted evidence is unavailable, narrow only the unsupported claim."
      else
        advisory_reason="Delivery/readiness claim(s) lack lane-appropriate evidence: ${detected_claims}. Check hosted state before relying on the claim."
      fi
    elif [[ "$detected_claims" == *"fixed"* ]]; then
      if [[ "${CODEX_STOP_CLAIM_MODE:-advisory}" == "block" ]]; then
        block_reason="Stop hook blocked delivery/readiness claim(s): ${detected_claims}. Preserve the substantive answer above; only revise the claim/evidence portion. Add exact local validation evidence using \"Command: <exact command> -> pass (<reason>)\". A workflow-closeout/v1 receipt does not substantiate a fixed-only claim; if local evidence is unavailable, narrow only the unsupported claim."
      else
        advisory_reason="Local fixed claim lacks proving validation evidence: ${detected_claims}. Check the changed behavior before relying on the claim."
      fi
    else
      if [[ "${CODEX_STOP_CLAIM_MODE:-advisory}" == "block" ]]; then
        block_reason="Stop hook blocked delivery/readiness claim(s): ${detected_claims}. Preserve the substantive answer above; only revise the claim/evidence portion. Add exact lane-appropriate evidence using \"Command: <exact command> -> pass (<reason>)\", or cite a workflow-closeout/v1 receipt path/reference when it proves that lane. If evidence is unavailable, narrow only the unsupported claim."
      else
        advisory_reason="Completion claim lacks lane-appropriate evidence: ${detected_claims}. Check the relevant evidence before relying on the claim."
      fi
    fi
  fi
fi

if [[ -n "$block_reason" ]]; then
  evidence_lines_json="$(printf '%s\n' "$last_message" | jq -Rsc '[split("\n")[] | select(test("^[[:space:]]*(([-*][[:space:]]+)|(>[[:space:]]+))?([[:alnum:] _-]+:[[:space:]]+)?[Cc]ommand:[[:space:]]+"))]')"
  event_record="$(hook_runtime_event_envelope "$input_json" "stop" "stop-guard" "block" "$block_reason")"
  if [[ -n "$event_record" ]]; then
    hook_runtime_append_jsonl "$(hook_runtime_log_path "hook-events")" "$event_record" "stop-guard" || true
  fi
  jq -n \
    --arg reason "$block_reason" \
    --argjson evidence_lines "$evidence_lines_json" \
    '{
      continue: true,
      decision: "block",
      reason: $reason,
      systemMessage: "Stop hook blocked an unsupported claim. Preserve every existing command-evidence line verbatim. If none exist, add only the required lane-specific passing evidence when available; otherwise narrow the unsupported claim.",
      evidence_preservation: {mode: "verbatim", command_lines: $evidence_lines}
    }'
elif [[ -n "$advisory_reason" ]]; then
  event_record="$(hook_runtime_event_envelope "$input_json" "stop" "stop-guard" "observed" "$advisory_reason")"
  if [[ -n "$event_record" ]]; then
    hook_runtime_append_jsonl "$(hook_runtime_log_path "hook-events")" "$event_record" "stop-guard" || true
  fi
  jq -n \
    --arg reason "$advisory_reason" \
    '{
      continue: true,
      hookSpecificOutput: {
        hookEventName: "Stop",
        additionalContext: ("Advisory evidence check: " + $reason)
      }
    }'
else
  jq -n '{continue: true}'
fi
