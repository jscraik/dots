#!/bin/bash -p

set -euo pipefail
# shellcheck source=codex/hooks/hook-runtime-path.sh
. "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh"

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
parsed_fields="$(printf '%s' "$input_json" | jq -r '[.source // "startup", .cwd // ".", .permission_mode // "default"] | @tsv')"
IFS=$'\t' read -r source_name cwd permission_mode <<<"$parsed_fields"

hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
codex_repo_root="$(cd -P "$hook_dir/.." && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
. "$hook_dir/hook-runtime-lib.sh"
project_override_audit_script="$codex_repo_root/scripts/audit-project-codex-config-overrides.sh"
workflow_priority_gate_script="$codex_repo_root/scripts/workflow-priority-gate.py"
computer_use_config_scrub_script="$codex_repo_root/scripts/scrub-computer-use-config.py"
runtime_config_drift_script="$codex_repo_root/scripts/repair-runtime-config-drift.py"
project_override_drift=0
project_override_audit_status="unavailable"
project_override_excerpt=""
workflow_gate_status="skipped"
workflow_gate_summary=""
workflow_gate_first_action=""
computer_use_config_scrub_status="skipped"
computer_use_config_scrub_summary=""
runtime_config_drift_status="skipped"
runtime_config_drift_backup=""
runtime_config_drift_summary=""
startup_repair_mode="${CODEX_SESSION_REPAIR_MODE-check}"
startup_repair_warning=""
startup_repair_args=("--json")
case "$startup_repair_mode" in
  repair) startup_repair_args+=("--repair") ;;
  check) ;;
  *)
    startup_repair_warning="Invalid CODEX_SESSION_REPAIR_MODE; configuration maintenance is check-only. Use repair or check."
    startup_repair_mode="check"
    ;;
esac
dev_root="${CODEX_DEV_ROOT:-${HOME}/dev}"
if [[ -d "$dev_root" ]] && physical_dev_root="$(cd -P -- "$dev_root" 2>/dev/null && pwd -P)"; then
  dev_root="$physical_dev_root"
fi
audit_cache_dir="${HOME}/.codex/state"
audit_cache_file="$audit_cache_dir/project-override-audit-cache.tsv"
audit_cache_ttl_seconds="${CODEX_PROJECT_OVERRIDE_AUDIT_CACHE_TTL_SECONDS:-300}"

if ! [[ "$audit_cache_ttl_seconds" =~ ^[0-9]+$ ]]; then
  audit_cache_ttl_seconds=300
fi

repo_root=""
git_root=""
repo_name="$(basename "${cwd:-.}")"
branch_name=""
head_sha=""
dirty_count="0"
preflight_status="skipped"
preflight_summary=""
validation_hint=""
codestyle_hint=""
system_message=""

# persist_project_override_audit_cache writes the audit timestamp, drift flag and a base64-encoded excerpt into the audit cache file atomically.
# persist_project_override_audit_cache writes the given timestamp, drift flag, and a base64-encoded excerpt into the audit cache file atomically by creating the cache directory if needed and writing to a temporary file before moving it into place; it silently does nothing if the cache directory cannot be created or the temporary write fails.
persist_project_override_audit_cache() {
  local audit_timestamp="$1"
  local audit_drift="$2"
  local audit_excerpt="$3"
  local encoded_excerpt
  local cache_tmp

  encoded_excerpt="$(encode_cache_excerpt "$audit_excerpt")"
  mkdir -p "$audit_cache_dir" 2>/dev/null || return 0
  if ! cache_tmp="$(mktemp "${audit_cache_file}.tmp.XXXXXX" 2>/dev/null)"; then
    return 0
  fi
  if printf '%s\t%s\t%s\n' "$audit_timestamp" "$audit_drift" "$encoded_excerpt" 2>/dev/null >"$cache_tmp"; then
    mv "$cache_tmp" "$audit_cache_file" 2>/dev/null || rm -f "$cache_tmp"
  else
    rm -f "$cache_tmp" 2>/dev/null || true
  fi
}

# encode_cache_excerpt encodes the provided excerpt to base64 and echoes the result with all CR/LF characters removed; echoes an empty string if the excerpt is empty.
encode_cache_excerpt() {
  local excerpt="$1"
  if [[ -z "$excerpt" ]]; then
    printf ''
    return 0
  fi
  printf '%s' "$excerpt" | base64 | tr -d '\r\n'
}

# decode_cache_excerpt decodes a base64-encoded excerpt, echoes the decoded text to stdout, and returns 0 on success or 1 on failure.
decode_cache_excerpt() {
  local encoded="$1"
  local decoded
  if [[ -z "$encoded" ]]; then
    printf ''
    return 0
  fi
  if decoded="$(printf '%s' "$encoded" | base64 --decode 2>/dev/null)"; then
    printf '%s' "$decoded"
    return 0
  fi
  if decoded="$(printf '%s' "$encoded" | base64 -D 2>/dev/null)"; then
    printf '%s' "$decoded"
    return 0
  fi
  return 1
}

# load_project_override_audit_cache loads a previously persisted project-override audit from the cache file into the globals project_override_drift and project_override_excerpt when the cache file exists, contains valid fields and is within the configured TTL; it returns success only in that case.
load_project_override_audit_cache() {
  local now_ts
  local cached_ts
  local cached_drift
  local cached_excerpt_encoded
  local cached_excerpt
  local cache_age

  if [[ ! -r "$audit_cache_file" ]]; then
    return 1
  fi

  IFS=$'\t' read -r cached_ts cached_drift cached_excerpt_encoded <"$audit_cache_file" || return 1

  if ! [[ "$cached_ts" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  if [[ "$cached_drift" != "0" && "$cached_drift" != "1" ]]; then
    return 1
  fi

  now_ts="$(date +%s 2>/dev/null || true)"
  if ! [[ "$now_ts" =~ ^[0-9]+$ ]]; then
    return 1
  fi

  cache_age=$((now_ts - cached_ts))
  if (( cache_age < 0 || cache_age > audit_cache_ttl_seconds )); then
    return 1
  fi

  if ! cached_excerpt="$(decode_cache_excerpt "$cached_excerpt_encoded")"; then
    return 1
  fi

  # Older hooks cached any execution failure as drift. Only the audit's exact
  # finding header establishes drift; also bind that evidence to this dev root.
  if [[ "$cached_drift" == "1" && "$cached_excerpt" != "FAIL: project-level .codex/config.toml drift under ${dev_root}" && "$cached_excerpt" != "FAIL: project-level .codex/config.toml drift under ${dev_root} "* ]]; then
    return 1
  fi

  project_override_drift="$cached_drift"
  project_override_audit_status="pass"
  [[ "$cached_drift" == "1" ]] && project_override_audit_status="drift"
  project_override_excerpt="$cached_excerpt"
  return 0
}

# run_project_override_audit runs the project override audit script and records its outcome.
# An unavailable audit is not a configuration finding and must not be cached
# as one. The retained audit CLI emits this exact header only for findings.
run_project_override_audit() {
  local now_ts
  local project_override_output
  local audit_exit=0

  now_ts="$(date +%s 2>/dev/null || printf '0')"
  project_override_output="$(CODEX_DEV_ROOT="$dev_root" bash "$project_override_audit_script" 2>&1)" || audit_exit=$?
  if [[ "$audit_exit" -ne 0 ]]; then
    project_override_audit_status="unavailable"
    if [[ "$audit_exit" -eq 1 && "${project_override_output%%$'\n'*}" == "FAIL: project-level .codex/config.toml drift under ${dev_root}" ]]; then
      project_override_drift=1
      project_override_audit_status="drift"
    fi
    project_override_excerpt="$(
      printf '%s\n' "$project_override_output" \
        | head -n 4 \
        | tr '\n' ' ' \
        | sed -E 's/[[:space:]]+/ /g' \
        | sed -E 's/^[[:space:]]+|[[:space:]]+$//g'
    )"
    project_override_excerpt="${project_override_excerpt//$'\t'/ }"
  else
    project_override_drift=0
    project_override_audit_status="pass"
    project_override_excerpt=""
  fi

  if [[ "$project_override_audit_status" != "unavailable" ]]; then
    persist_project_override_audit_cache "$now_ts" "$project_override_drift" "$project_override_excerpt"
  fi
}

if [[ -x "$project_override_audit_script" ]]; then
  if ! load_project_override_audit_cache; then
    run_project_override_audit
  fi
fi

if [[ -f "$computer_use_config_scrub_script" ]]; then
  computer_use_config_scrub_args=("${startup_repair_args[@]}")
  if [[ -n "${CODEX_COMPUTER_USE_CONFIG_SCRUB_PATH:-}" ]]; then
    computer_use_config_scrub_args+=("--config-path" "$CODEX_COMPUTER_USE_CONFIG_SCRUB_PATH")
  fi
  computer_use_config_scrub_output="$(python3 "$computer_use_config_scrub_script" "${computer_use_config_scrub_args[@]}" 2>/dev/null || true)"
  if [[ -n "$computer_use_config_scrub_output" ]] && printf '%s' "$computer_use_config_scrub_output" | jq -e '.schema_version == "computer-use-config-scrub/v1"' >/dev/null 2>&1; then
    computer_use_config_scrub_status="$(printf '%s' "$computer_use_config_scrub_output" | jq -r '.status // "unknown"')"
    computer_use_config_scrub_count="$(printf '%s' "$computer_use_config_scrub_output" | jq -r '.removed_count // 0')"
    computer_use_config_scrub_reason="$(printf '%s' "$computer_use_config_scrub_output" | jq -r '.reason // ""')"
    if [[ "$computer_use_config_scrub_status" == "repaired" ]]; then
      computer_use_config_scrub_summary="removed ${computer_use_config_scrub_count} forbidden Computer Use client notifier(s) from the helper's configured target"
    elif [[ "$computer_use_config_scrub_status" == "fail" ]]; then
      computer_use_config_scrub_summary="Computer Use notifier drift detected; check-only startup did not repair it"
    elif [[ "$computer_use_config_scrub_status" == "blocked" ]]; then
      computer_use_config_scrub_summary="Computer Use config scrub blocked: ${computer_use_config_scrub_reason}"
    fi
    computer_use_retained_generation="$(printf '%s' "$computer_use_config_scrub_output" | jq -r '.retained_generation_path | select(type == "string" and length > 0) // ""')"
    if [[ -n "$computer_use_retained_generation" ]]; then
      computer_use_config_scrub_summary+="; retained generation: ${computer_use_retained_generation}; inspect native saves before explicit recovery"
    fi
  else
    computer_use_config_scrub_status="unavailable"
  fi
fi

if [[ -f "$runtime_config_drift_script" ]]; then
  runtime_config_drift_args=("${startup_repair_args[@]}")
  # App-owned bundle health is not a prerequisite for repository-owned repair.
  # Keep explicit installed-contract diagnostics separate from session startup.
  runtime_config_drift_args+=("--config-path" "${CODEX_RUNTIME_CONFIG_DRIFT_PATH:-${CODEX_HOME:-$HOME/.codex}/config.toml}")
  runtime_config_drift_output="$(python3 "$runtime_config_drift_script" "${runtime_config_drift_args[@]}" 2>/dev/null || true)"
  if [[ -n "$runtime_config_drift_output" ]] && printf '%s' "$runtime_config_drift_output" | jq -e '.schema_version == "runtime-config-drift-repair/v1"' >/dev/null 2>&1; then
    runtime_config_drift_status="$(printf '%s' "$runtime_config_drift_output" | jq -r '.status // "unknown"')"
    runtime_config_drift_repairs="$(printf '%s' "$runtime_config_drift_output" | jq -r '(.repairs // []) | join(", ")')"
    runtime_config_drift_reason="$(printf '%s' "$runtime_config_drift_output" | jq -r '[.reason, .error] | map(select(type == "string")) | join(": ")')"
    runtime_config_drift_backup="$(printf '%s' "$runtime_config_drift_output" | jq -r '.backup_path | select(type == "string") // ""')"
    if [[ "$runtime_config_drift_status" == "repaired" ]]; then
      runtime_config_drift_summary="repaired ${runtime_config_drift_repairs}"
    elif [[ "$runtime_config_drift_status" == "blocked" ]]; then
      runtime_config_drift_summary="runtime config drift repair blocked: ${runtime_config_drift_reason}. Inspect the repair diagnostic before changing config; this blocker does not establish host-profile, compact-prompt, or skills-projection drift."
    elif [[ "$runtime_config_drift_status" == "fail" ]]; then
      runtime_config_drift_summary="runtime config drift detected but not repaired"
    fi
    runtime_retained_generation="$(printf '%s' "$runtime_config_drift_output" | jq -r '.retained_generation_path | select(type == "string" and length > 0) // ""')"
    if [[ -n "$runtime_retained_generation" ]]; then
      runtime_config_drift_summary+="; retained generation: ${runtime_retained_generation}; inspect native saves before explicit recovery"
    fi
  else
    runtime_config_drift_status="unavailable"
  fi
fi

if [[ -f "$workflow_priority_gate_script" ]]; then
  workflow_gate_output="$(python3 "$workflow_priority_gate_script" --json --max-items 3 2>/dev/null || true)"
  if [[ -n "$workflow_gate_output" ]] && printf '%s' "$workflow_gate_output" | jq -e '.schema_version == "workflow-priority-gate/v1"' >/dev/null 2>&1; then
    workflow_gate_status="$(printf '%s' "$workflow_gate_output" | jq -r '.gate_status // "unknown"')"
    workflow_gate_first_action="$(printf '%s' "$workflow_gate_output" | jq -r '.first_action // ""')"
    workflow_gate_summary="$(
      printf '%s' "$workflow_gate_output" \
        | jq -r '
            if (.p0_items | length) == 0 then
              "no open P0 workflow guardrails"
            else
              (.p0_items | map((.ticket_id // "untracked") + " " + (.title // "untitled")) | join("; "))
            end
          ' \
        | tr '\n' ' ' \
        | sed -E 's/[[:space:]]+/ /g' \
        | sed -E 's/^[[:space:]]+|[[:space:]]+$//g'
    )"
    workflow_gate_summary="${workflow_gate_summary//$'\t'/ }"
  else
    workflow_gate_status="unavailable"
  fi
fi

if git -C "$cwd" rev-parse --show-toplevel >/dev/null 2>&1; then
  git_root="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)"
  candidate_root="$cwd"

  while true; do
    if [[ -f "$candidate_root/scripts/codex-preflight.sh" \
       || -f "$candidate_root/AGENTS.md" \
       || -f "$candidate_root/pnpm-lock.yaml" \
       || -f "$candidate_root/package-lock.json" \
       || -f "$candidate_root/Cargo.toml" \
       || -f "$candidate_root/pyproject.toml" \
       || -f "$candidate_root/go.mod" ]]; then
      repo_root="$candidate_root"
      break
    fi

    if [[ "$candidate_root" == "$git_root" ]]; then
      break
    fi

    parent_root="$(dirname "$candidate_root")"
    if [[ "$parent_root" == "$candidate_root" ]]; then
      break
    fi
    candidate_root="$parent_root"
  done

  if [[ -z "$repo_root" ]]; then
    repo_root="$git_root"
  fi

  repo_name="$(basename "$repo_root")"
  branch_name="$(git -C "$git_root" symbolic-ref --quiet --short HEAD 2>/dev/null || git -C "$git_root" rev-parse --short HEAD 2>/dev/null || true)"
  head_sha="$(git -C "$git_root" rev-parse HEAD 2>/dev/null || true)"
  # Automatic observation must not execute helpers selected by repository-local config.
  dirty_count="$(git -c core.fsmonitor=false -C "$git_root" status --porcelain=v1 -- "$repo_root" 2>/dev/null | wc -l | tr -d '[:space:]')"
  dirty_count="${dirty_count:-0}"

  printf -v preflight_command 'bash %q --mode optional' "$repo_root/scripts/codex-preflight.sh"
  if [[ -f "$repo_root/scripts/codex-preflight.sh" ]]; then
    preflight_status="available"
  fi

  if [[ -f "$repo_root/scripts/validate-codex-config.py" ]]; then
    validation_hint="After config edits, run validate-codex-config.py and then ${preflight_command}."
  elif [[ -f "$repo_root/pnpm-lock.yaml" ]]; then
    validation_hint="After edits, prefer the smallest relevant pnpm validation command before broader checks."
  elif [[ -f "$repo_root/package-lock.json" ]]; then
    validation_hint="After edits, prefer the smallest relevant npm validation command before broader checks."
  elif [[ -f "$repo_root/Cargo.toml" ]]; then
    validation_hint="After edits, prefer the smallest relevant cargo validation command before broader checks."
  fi

  if [[ -f "$repo_root/instructions/CODESTYLE.md" ]]; then
    codestyle_hint="For technical tasks in this repo, read instructions/CODESTYLE.md before deeper instruction modules."
  elif [[ -f "$repo_root/codex/instructions/CODESTYLE.md" ]]; then
    codestyle_hint="For codex subtree technical tasks, read codex/instructions/CODESTYLE.md before deeper instruction modules."
  fi

  if [[ "$dirty_count" != "0" ]]; then
    system_message="Dirty worktree detected in ${repo_name}; keep unrelated changes intact."
  fi
fi

declare -a context_parts=()

if [[ -n "$repo_root" ]]; then
  context_parts+=("Session opened in repo ${repo_name}.")
  if [[ -n "$branch_name" ]]; then
    context_parts+=("Current branch: ${branch_name}.")
  fi
  if [[ "$dirty_count" != "0" ]]; then
    context_parts+=("Worktree already has ${dirty_count} local change(s); do not revert unrelated edits.")
  fi
else
  context_parts+=("Session opened in ${repo_name}.")
fi

context_parts+=("Inspect local instructions before edits.")

if [[ -n "$codestyle_hint" ]]; then
  context_parts+=("$codestyle_hint")
fi

if [[ "$preflight_status" == "available" ]]; then
  context_parts+=("Repo preflight available: ${preflight_command}; not run automatically. Inspect and run it only within the authorised task.")
fi

if [[ -n "$validation_hint" ]]; then
  context_parts+=("$validation_hint")
fi

if [[ "$startup_repair_mode" == "check" ]]; then
  context_parts+=("Startup configuration maintenance is check-only; config repairs were not authorized by this mode. Runtime-card and audit-cache writes remain separate.")
fi
if [[ -n "$startup_repair_warning" ]]; then
  context_parts+=("$startup_repair_warning")
fi

if [[ "$computer_use_config_scrub_status" == "repaired" && -n "$computer_use_config_scrub_summary" ]]; then
  context_parts+=("Computer Use config scrub repaired drift: ${computer_use_config_scrub_summary}. Do not launch the retired SkyComputerUseClient through notify. Preserve desktop-managed MCP registrations and plugin consent.")
elif [[ ( "$computer_use_config_scrub_status" == "blocked" || "$computer_use_config_scrub_status" == "fail" ) && -n "$computer_use_config_scrub_summary" ]]; then
  context_parts+=("WARNING: ${computer_use_config_scrub_summary}")
elif [[ "$computer_use_config_scrub_status" == "unavailable" ]]; then
  context_parts+=("Computer Use config scrub could not run; verify codex/scripts/scrub-computer-use-config.py before trusting Computer Use launch routing.")
fi

if [[ "$runtime_config_drift_status" == "repaired" && -n "$runtime_config_drift_summary" ]]; then
  context_parts+=("Runtime config drift guard repaired drift: ${runtime_config_drift_summary}. The repository owns canonical policy; Desktop-owned Computer Use plugin consent is preserved from the runtime file.")
elif [[ ( "$runtime_config_drift_status" == "blocked" || "$runtime_config_drift_status" == "fail" ) && -n "$runtime_config_drift_summary" ]]; then
  context_parts+=("WARNING: ${runtime_config_drift_summary}")
elif [[ "$runtime_config_drift_status" == "unavailable" ]]; then
  context_parts+=("Runtime config drift guard could not run; verify codex/scripts/repair-runtime-config-drift.py before trusting Codex runtime config.")
fi

if [[ -n "$runtime_config_drift_backup" && "${runtime_config_drift_reason:-}" != config_backup_failed* ]]; then
  context_parts+=("Runtime configuration backup: ${runtime_config_drift_backup}")
  context_parts+=("Preserve this private backup before temporary-file cleanup if you need to recover pre-reconciliation settings.")
fi

if [[ "$project_override_drift" -eq 1 ]]; then
  context_parts+=("Project-level .codex/config.toml drift detected under ${dev_root}; remove full-config symlinks or unsupported project-local keys, then rerun bash ${project_override_audit_script}.")
  if [[ -n "$project_override_excerpt" ]]; then
    context_parts+=("Override audit summary: ${project_override_excerpt}")
  fi
  if [[ -z "$system_message" ]]; then
    system_message="Project Codex config drift detected."
  else
    system_message="${system_message} Project Codex config drift detected."
  fi
elif [[ "$project_override_audit_status" == "unavailable" ]]; then
  context_parts+=("Project config audit unavailable; no project-config drift was established. Diagnose the audit before changing project configuration.")
  if [[ -n "$project_override_excerpt" ]]; then
    context_parts+=("Override audit diagnostic: ${project_override_excerpt}")
  fi
fi

if [[ "$workflow_gate_status" == "blocked_by_p0" ]]; then
  context_parts+=("Workflow priority gate reports blocked_by_p0. Assess whether the reported guardrail blocks the named outcome; pause only dependent actions and continue independent authorized work. Do not adopt unrelated repairs without authority.")
  if [[ -n "$workflow_gate_first_action" ]]; then
    context_parts+=("Workflow first action: ${workflow_gate_first_action}")
  fi
  if [[ -n "$workflow_gate_summary" ]]; then
    context_parts+=("Open workflow P0s: ${workflow_gate_summary}")
  fi
  if [[ -z "$system_message" ]]; then
    system_message="Workflow P0 guardrail work is open."
  else
    system_message="${system_message} Workflow P0 guardrail work is open."
  fi
elif [[ "$workflow_gate_status" == "pass" ]]; then
  context_parts+=("Workflow priority gate passed.")
elif [[ "$workflow_gate_status" == "unavailable" ]]; then
  context_parts+=("Workflow priority gate could not be read; treat workflow-priority status as unknown.")
fi

case "$permission_mode" in
  bypassPermissions)
    context_parts+=("Full-access permission mode is active; verify before destructive commands.")
    if [[ -z "$system_message" ]]; then
      system_message="High-autonomy permission mode is active."
    fi
    ;;
  dontAsk)
    context_parts+=("Autonomous permission mode is active; avoid risky commands unless clearly necessary.")
    context_parts+=("Runtime AskForApproval=Never can still deny classifier-gated commands; if blocked, report session/runtime policy as the effective source before citing config defaults.")
    ;;
  acceptEdits)
    context_parts+=("Edits are pre-approved, but verification still matters.")
    ;;
  plan)
    context_parts+=("Plan permission mode is active; inspect and explain before making edits or running risky commands.")
    ;;
esac

if [[ "$source_name" == "resume" ]]; then
  context_parts+=("Resume from the existing session state before re-exploring.")
fi

additional_context="$(printf '%s ' "${context_parts[@]}")"
additional_context="${additional_context% }"

hook_runtime_write_card "$input_json" "$repo_root" "$git_root" "$repo_name" "$branch_name" "$head_sha" "$dirty_count" "$preflight_status" "$preflight_summary" "$project_override_drift" "$project_override_excerpt" "$project_override_audit_status" || true
runtime_card_path="$(hook_runtime_card_path_for_input "$input_json")"
runtime_card_hash="$(hook_runtime_sha256_file "$runtime_card_path")"
if [[ -n "$runtime_card_hash" ]]; then
  additional_context="${additional_context} Runtime card: $runtime_card_path (sha256:$runtime_card_hash)."
fi

session_event="$(hook_runtime_event_envelope "$input_json" "session-start" "session-start" "observed" "$preflight_status")"
if [[ -n "$session_event" ]]; then
  hook_runtime_append_jsonl "$(hook_runtime_log_path "hook-events")" "$session_event" "session-start" || true
fi

jq -n \
  --arg additional_context "$additional_context" \
  --arg system_message "$system_message" \
  '{
    continue: true,
    systemMessage: (if $system_message == "" then null else $system_message end),
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $additional_context
    }
  }'
