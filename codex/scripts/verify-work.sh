#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf '❌ verify-work.sh requires bash. Run: bash scripts/verify-work.sh [options]\n' >&2
  return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '❌ verify-work.sh is CLI-only; do not source it. Run: bash scripts/verify-work.sh [options]\n' >&2
  return 2
fi

set -euo pipefail

dots_helper_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_helper_dir/admit-hook-fixture.py" '{}' || exit $?

changed_only=1
repo_root=""
fail_on_skips=0
fast_mode=0
local_memory_mode="off"
persist_fast_governance=0
fast_mode_governance_dir=""
declare -a fast_mode_temp_reports=()

if [[ "${CODEX_VERIFY_WORK_PERSIST_GOVERNANCE:-0}" == "1" ]]; then
  persist_fast_governance=1
fi

# usage prints the usage/help text describing available command-line options for verify-work.sh.
usage() {
  cat <<'USAGE'
Usage: verify-work.sh [options]

Canonical local verification runner.

Options:
  --all-skills        Validate all discovered skills (default: changed skills only)
  --changed-only      Validate only changed/new skills (default)
  --strict            Fail if any check is skipped
  --fast              Faster run: skip OpenClaw, recursive promotion, and launchd maintenance; Volatile governance reports write to .tmp unless CODEX_VERIFY_WORK_PERSIST_GOVERNANCE=1
  --repo-root PATH    Run checks in a specific repository root (default: script's own repo)
  -h, --help          Show this help text
USAGE
}

while (($# > 0)); do
  case "$1" in
    --all-skills)
      changed_only=0
      shift
      ;;
    --changed-only)
      changed_only=1
      shift
      ;;
    --strict)
      fail_on_skips=1
      shift
      ;;
    --fast)
      fast_mode=1
      shift
      ;;
    --repo-root)
      repo_root="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[verify-work] unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

script_repo_root="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ -z "$repo_root" ]]; then
  repo_root="$script_repo_root"
fi

python3 "$dots_helper_dir/helper_fixture_scope.py" --verify-bundle "$repo_root" || exit $?
cd "$repo_root"
echo "[verify-work] repo root: $repo_root"
repo_git_root="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$repo_root")"

declare -a passed_checks=()
declare -a failed_checks=()
declare -a skipped_checks=()

# run_check executes a named command, prints a header, and records the name in `passed_checks` on success or `failed_checks` on failure.
run_check() {
  local name="$1"
  shift
  echo
  echo "==> $name"
  if "$@"; then
    passed_checks+=("$name")
  else
    failed_checks+=("$name")
  fi
}

# skip_check records a skipped validation by appending the check name and reason to the `skipped_checks` array and echoing a skip message.
skip_check() {
  local name="$1"
  local reason="$2"
  skipped_checks+=("$name ($reason)")
  echo "[verify-work] skip $name: $reason"
}

source "$script_repo_root/scripts/codex-validation-lib.sh"
python_bin="$(codex_select_validation_python "verify-work")"
export CODEX_VALIDATION_PYTHON="${python_bin}"
# Keep the already-populated dependency cache when a child validator receives
# a disposable TMPDIR. Fixture isolation must not require another network fetch.
export CODEX_VALIDATION_UV_CACHE_DIR="${CODEX_VALIDATION_UV_CACHE_DIR:-${TMPDIR:-/tmp}/configs-uv-cache}"

# collect_changed_skill_dirs collects directories containing changed or untracked SKILL.md files and prints each directory path once.
collect_changed_skill_dirs() {
  {
    git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null || true
    git ls-files --others --exclude-standard 2>/dev/null || true
  } \
    | rg '/SKILL\.md$' \
    | rg -v '^SKILL\.md$' \
    | awk -F/ 'BEGIN{OFS="/"} NF>1 {NF--; print $0}' \
    | awk '!seen[$0]++'
}

collect_all_skill_dirs() {
  if command -v fd >/dev/null 2>&1; then
    fd 'SKILL\.md$' . --type f --hidden --exclude .git --exclude node_modules \
      | rg '/SKILL\.md$' \
      | rg -v '^SKILL\.md$' \
      | awk -F/ 'BEGIN{OFS="/"} NF>1 {NF--; print $0}' \
      | awk '!seen[$0]++'
  else
    rg --files \
      | rg '/SKILL\.md$' \
      | rg -v '^SKILL\.md$' \
      | awk -F/ 'BEGIN{OFS="/"} NF>1 {NF--; print $0}' \
      | awk '!seen[$0]++'
  fi
}

# shellcheck disable=SC2329
check_maintenance_launchd_jobs() {
  local -A expected_program=(
    ["com.jamiecraik.mise-tools-updater"]="${repo_root}/scripts/mise-tools-updater.sh"
    ["com.jamiecraik.mcp-cleanup"]="${repo_root}/scripts/run-mcp-cleanup.sh"
    ["com.jamiecraik.config-projection-reconciler"]="${repo_root}/scripts/reconcile-config-projection.sh"
    ["com.jamiecraik.session-collector"]="${repo_root}/scripts/run-session-collector.sh"
  )
  local -A expected_interval=(
    ["com.jamiecraik.mise-tools-updater"]="3600"
    ["com.jamiecraik.mcp-cleanup"]="300"
    ["com.jamiecraik.config-projection-reconciler"]="600"
    ["com.jamiecraik.session-collector"]="3600"
  )
  local uid=""
  local label=""
  local launch_output=""
  local program=""
  local interval=""
  local expected_path=""
  local expected_interval_value=""
  local run_output=""
  local last_exit_code=""

  uid="$(id -u)"
  for label in "${!expected_program[@]}"; do
    launch_output="$(launchctl print "gui/${uid}/${label}" 2>/dev/null || true)"
    if [[ -z "$launch_output" ]]; then
      echo "launchd label not loaded: ${label}"
      return 1
    fi

    expected_path="${expected_program["${label}"]}"
    expected_interval_value="${expected_interval["${label}"]}"

    program="$(printf '%s\n' "$launch_output" | awk '/program[[:space:]]*=/{print $0; exit}' | sed -E 's/^[[:space:]]*program[[:space:]]*=[[:space:]]*//')"
    if [[ -z "$program" ]]; then
      echo "launchd ${label}: missing program entry"
      return 1
    fi
    if [[ "$program" != "${expected_path}" ]]; then
      echo "launchd ${label}: unexpected program '${program}' (expected '${expected_path}')"
      return 1
    fi

    interval="$(printf '%s\n' "$launch_output" | awk '/run interval[[:space:]]*=/{print $0; exit}' | sed -E 's/^[[:space:]]*run interval[[:space:]]*=[[:space:]]*//' | sed -E 's/[[:space:]]*seconds$//')"
    if [[ -n "$expected_interval_value" && -n "$interval" && "$interval" != "$expected_interval_value" ]]; then
      echo "launchd ${label}: unexpected run interval '${interval}' (expected '${expected_interval_value}')"
      return 1
    fi

    run_output="$(printf '%s\n' "$launch_output" | awk '/runs[[:space:]]*=|last exit code[[:space:]]*=/{print}')"
    last_exit_code="$(printf '%s\n' "$launch_output" | awk '/last exit code[[:space:]]*=/{print $0; exit}' | sed -E 's/^[[:space:]]*last exit code[[:space:]]*=[[:space:]]*//')"
    echo "${label}: program=${program} ${run_output:+| ${run_output}}"
    if [[ -n "$last_exit_code" && "$last_exit_code" != "(never exited)" && "$last_exit_code" != "0" ]]; then
      echo "launchd ${label}: last exit code was ${last_exit_code}"
      return 1
    fi
  done
}

echo
echo "[verify-work] running plan graph validation..."
if [[ -f "scripts/validate_plan_graphs.sh" ]]; then
  run_check "plan-graph-validation" bash "scripts/validate_plan_graphs.sh"
elif [[ -f ".agent/PLANS.md" && -f "$HOME/.codex/scripts/plan-graph-lint.py" ]]; then
  run_check "plan-graph-validation" "$python_bin" "$HOME/.codex/scripts/plan-graph-lint.py" ".agent/PLANS.md"
else
  skip_check "plan-graph-validation" "no validator script or .agent/PLANS.md found"
fi

echo
preflight_script=""
for candidate in "codex/scripts/codex-preflight.sh" "scripts/codex-preflight.sh"; do
  if [[ -f "$candidate" ]]; then
    preflight_script="$candidate"
    break
  fi
done

if [[ -n "$preflight_script" ]]; then
  if [[ "$fast_mode" -eq 1 ]]; then
    local_memory_mode="off"
  fi
  run_check "codex-preflight" bash "$preflight_script" \
    --stack repo \
    --mode "$local_memory_mode" \
    --repo-fragment "/codex" \
    --paths "AGENTS.md,instructions,hooks,scripts,README.md"
else
  skip_check "codex-preflight" "codex-preflight.sh not found"
fi

workflow_priority_gate=""
for candidate in "codex/scripts/workflow-priority-gate.py" "scripts/workflow-priority-gate.py"; do
  if [[ -f "$candidate" ]]; then
    workflow_priority_gate="$candidate"
    break
  fi
done

if [[ -n "$workflow_priority_gate" ]]; then
  run_check "workflow-priority-gate" "$python_bin" "$workflow_priority_gate" --json --max-items 1
else
  skip_check "workflow-priority-gate" "workflow-priority-gate.py not found"
fi

workflow_closeout=""
for candidate in "codex/scripts/workflow-closeout.py" "scripts/workflow-closeout.py"; do
  if [[ -f "$candidate" ]]; then
    workflow_closeout="$candidate"
    break
  fi
done

if [[ -n "$workflow_closeout" ]]; then
  run_check "workflow-closeout-schema" "$python_bin" "$workflow_closeout" --validate-sample
else
  skip_check "workflow-closeout-schema" "workflow-closeout.py not found"
fi

evidence_freshness=""
for candidate in "codex/scripts/check-evidence-freshness.py" "scripts/check-evidence-freshness.py"; do
  if [[ -f "$candidate" ]]; then
    evidence_freshness="$candidate"
    break
  fi
done

if [[ -n "$evidence_freshness" ]]; then
  run_check "evidence-freshness-self-test" "$python_bin" "$evidence_freshness" --self-test
else
  skip_check "evidence-freshness-self-test" "check-evidence-freshness.py not found"
fi

validation_router=""
for candidate in "codex/scripts/select-validation-for-changes.py" "scripts/select-validation-for-changes.py"; do
  if [[ -f "$candidate" ]]; then
    validation_router="$candidate"
    break
  fi
done

if [[ -n "$validation_router" ]]; then
  run_check "validation-router-self-test" "$python_bin" "$validation_router" --self-test --json
else
  skip_check "validation-router-self-test" "select-validation-for-changes.py not found"
fi

validation_router_fixture="scripts/tests/fixtures/changed-files.txt"
if [[ -n "$validation_router" && -f "$validation_router_fixture" ]]; then
  run_check "validation-router" "$python_bin" "$validation_router" --changed-files "$validation_router_fixture" --json
elif [[ -z "$validation_router" ]]; then
  skip_check "validation-router" "select-validation-for-changes.py not found"
else
  skip_check "validation-router" "changed-files fixture not found"
fi

branch_pr_truth=""
for candidate in "codex/scripts/check-branch-pr-truth.py" "scripts/check-branch-pr-truth.py"; do
  if [[ -f "$candidate" ]]; then
    branch_pr_truth="$candidate"
    break
  fi
done

if [[ -n "$branch_pr_truth" ]]; then
  run_check "branch-pr-truth" "$python_bin" "$branch_pr_truth" --dry-run --json
else
  skip_check "branch-pr-truth" "check-branch-pr-truth.py not found"
fi

auth_backed_wrapper=""
for candidate in "codex/scripts/run-auth-backed.sh" "scripts/run-auth-backed.sh"; do
  if [[ -f "$candidate" ]]; then
    auth_backed_wrapper="$candidate"
    break
  fi
done

if [[ -n "$auth_backed_wrapper" ]]; then
  run_check "auth-backed-wrapper" bash "$auth_backed_wrapper" --help
else
  skip_check "auth-backed-wrapper" "run-auth-backed.sh not found"
fi

scratch_project_scrub=""
for candidate in "codex/scripts/scrub-codex-scratch-projects.py" "scripts/scrub-codex-scratch-projects.py"; do
  if [[ -f "$candidate" ]]; then
    scratch_project_scrub="$candidate"
    break
  fi
done

if [[ -n "$scratch_project_scrub" ]]; then
  run_check "codex-scratch-project-scrub-self-test" "$python_bin" "$scratch_project_scrub" --self-test --json
  run_check "codex-scratch-project-scrub-check" "$python_bin" "$scratch_project_scrub" --check --json
else
  skip_check "codex-scratch-project-scrub" "scrub-codex-scratch-projects.py not found"
fi

runtime_config_drift_repair=""
for candidate in "codex/scripts/repair-runtime-config-drift.py" "scripts/repair-runtime-config-drift.py"; do
  if [[ -f "$candidate" ]]; then
    runtime_config_drift_repair="$candidate"
    break
  fi
done

if [[ -n "$runtime_config_drift_repair" ]]; then
  run_check "runtime-config-drift-check" "$python_bin" "$runtime_config_drift_repair" --check --json
else
  skip_check "runtime-config-drift-check" "repair-runtime-config-drift.py not found"
fi

echo
if [[ -f "launchd/com.jamiecraik.mise-tools-updater.plist" && -f "scripts/mise-tools-updater.sh" && -f "scripts/run-mcp-cleanup.sh" ]]; then
  if [[ "$fast_mode" -eq 1 ]]; then
    skip_check "launchd-maintenance-jobs" "disabled by --fast"
  else
    run_check "launchd-maintenance-jobs" check_maintenance_launchd_jobs
  fi
else
  skip_check "launchd-maintenance-jobs" "not a codex maintenance repo"
fi

instruction_routing_validator=""
duplication_checker="$repo_git_root/codex/scripts/duplication_advisory.py"
if [[ -f "$duplication_checker" ]]; then
  run_check "new-duplication-advisory" \
    bash "$script_repo_root/scripts/codex-validation-python-uv.sh" \
    "$duplication_checker" --root "$repo_git_root" --require-target-baseline
else
  skip_check "new-duplication-advisory" "active target does not own the Configs checker"
fi

for candidate in "codex/scripts/validate-instruction-routing.py" "scripts/validate-instruction-routing.py"; do
  if [[ -f "$candidate" ]]; then
    instruction_routing_validator="$candidate"
    break
  fi
done

if [[ -n "$instruction_routing_validator" ]]; then
  run_check "instruction-routing-validation" \
    bash "$(dirname "$instruction_routing_validator")/codex-validation-python-uv.sh" \
    "$instruction_routing_validator" --root "$repo_root"
else
  skip_check "instruction-routing-validation" "validate-instruction-routing.py not found"
fi

agent_governance_validator=""
for candidate in "codex/scripts/validate-agent-governance.py" "scripts/validate-agent-governance.py"; do
  if [[ -f "$candidate" ]]; then
    agent_governance_validator="$candidate"
    break
  fi
done

if [[ -n "$agent_governance_validator" ]]; then
  run_check "agent-governance-validation" \
    "$python_bin" "$agent_governance_validator" --root "$repo_root"
else
  skip_check "agent-governance-validation" "validate-agent-governance.py not found"
fi

agent_artifact_validator=""
for candidate in "codex/scripts/validate-agent-artifacts.py" "scripts/validate-agent-artifacts.py"; do
  if [[ -f "$candidate" ]]; then
    agent_artifact_validator="$candidate"
    break
  fi
done

if [[ -n "$agent_artifact_validator" ]]; then
  run_check "agent-artifact-contract-validation" \
    "$python_bin" "$agent_artifact_validator" --root "$repo_root"
else
  skip_check "agent-artifact-contract-validation" "validate-agent-artifacts.py not found"
fi

config_validator=""
for candidate in "codex/scripts/validate-codex-config.py" "scripts/validate-codex-config.py"; do
  if [[ -f "$candidate" ]]; then
    config_validator="$candidate"
    break
  fi
done

if [[ -n "$config_validator" ]]; then
  run_check "codex-config-validation" env \
    CODEX_PROJECT_CONFIG_SEARCH_ROOTS="$repo_git_root" \
    "$python_bin" "$config_validator"
else
  skip_check "codex-config-validation" "validate-codex-config.py not found"
fi

project_override_audit=""
for candidate in "codex/scripts/audit-project-codex-config-overrides.sh" "scripts/audit-project-codex-config-overrides.sh"; do
  if [[ -f "$candidate" ]]; then
    project_override_audit="$candidate"
    break
  fi
done

if [[ -n "$project_override_audit" ]]; then
  run_check "project-codex-config-drift-audit" env \
    CODEX_DEV_ROOT="$repo_git_root" \
    CODEX_PROJECT_CONFIG_TARGET="$repo_git_root/codex/config.toml" \
    bash "$project_override_audit"
else
  skip_check "project-codex-config-drift-audit" "audit-project-codex-config-overrides.sh not found"
fi

hook_validator=""
for candidate in "codex/scripts/validate-codex-hooks.sh" "scripts/validate-codex-hooks.sh"; do
  if [[ -f "$candidate" ]]; then
    hook_validator="$candidate"
    break
  fi
done

if [[ -n "$hook_validator" ]]; then
  tmpdir_wrapper=""
  for candidate in "codex/scripts/with-writable-tmpdir.sh" "scripts/with-writable-tmpdir.sh"; do
    if [[ -f "$candidate" ]]; then
      tmpdir_wrapper="$candidate"
      break
    fi
  done

  if [[ -n "$tmpdir_wrapper" ]]; then
    run_check "codex-hook-validation" bash "$tmpdir_wrapper" bash "$hook_validator"
  else
    run_check "codex-hook-validation" bash "$hook_validator"
  fi
else
  skip_check "codex-hook-validation" "validate-codex-hooks.sh not found"
fi

hook_inventory_script=""
for candidate in "codex/scripts/hook-governance/inventory_repos.py" "scripts/hook-governance/inventory_repos.py"; do
  if [[ -f "$candidate" ]]; then
    hook_inventory_script="$candidate"
    break
  fi
done

hook_scope_manifest=""
for candidate in "codex/docs/hooks-governance/repo-scope.manifest.json" "docs/hooks-governance/repo-scope.manifest.json"; do
  if [[ -f "$candidate" ]]; then
    hook_scope_manifest="$candidate"
    break
  fi
done

hook_inventory_output=""
for candidate in "codex/docs/hooks-governance/repo-profile-matrix.json" "docs/hooks-governance/repo-profile-matrix.json"; do
  if [[ -f "$candidate" || -d "$(dirname "$candidate")" ]]; then
    hook_inventory_output="$candidate"
    break
  fi
done
if [[ -z "$hook_inventory_output" ]]; then
  hook_inventory_output="docs/hooks-governance/repo-profile-matrix.json"
fi

if [[ "$fast_mode" -eq 1 ]]; then
  skip_check "hook-governance-inventory" \
    "cross-repository inventory deferred by --fast; run full verify-work with the workspace available"
elif [[ -n "$hook_inventory_script" && -n "$hook_scope_manifest" ]]; then
  run_check "hook-governance-inventory" \
    "$python_bin" "$hook_inventory_script" \
      --manifest "$hook_scope_manifest" \
      --out "$hook_inventory_output"
else
  skip_check "hook-governance-inventory" "inventory_repos.py or repo-scope.manifest.json not found"
fi

gate_registry_validator=""
for candidate in "codex/scripts/hook-governance/validate_gate_registry.py" "scripts/hook-governance/validate_gate_registry.py"; do
  if [[ -f "$candidate" ]]; then
    gate_registry_validator="$candidate"
    break
  fi
done

gate_ownership_matrix=""
for candidate in "codex/docs/hooks-governance/gate-ownership-matrix.yaml" "docs/hooks-governance/gate-ownership-matrix.yaml"; do
  if [[ -f "$candidate" ]]; then
    gate_ownership_matrix="$candidate"
    break
  fi
done

stage_policy_matrix=""
for candidate in "codex/docs/hooks-governance/stage-policy-matrix.yaml" "docs/hooks-governance/stage-policy-matrix.yaml"; do
  if [[ -f "$candidate" ]]; then
    stage_policy_matrix="$candidate"
    break
  fi
done

codex_runtime_policy=""
for candidate in "codex/docs/hooks-governance/codex-hook-runtime-policy.md" "docs/hooks-governance/codex-hook-runtime-policy.md"; do
  if [[ -f "$candidate" ]]; then
    codex_runtime_policy="$candidate"
    break
  fi
done

if [[ -n "$gate_registry_validator" && -n "$gate_ownership_matrix" && -n "$stage_policy_matrix" && -n "$codex_runtime_policy" ]]; then
  run_check "hook-governance-gate-registry" \
    "$python_bin" "$gate_registry_validator" \
      --inventory "$hook_inventory_output" \
      --ownership "$gate_ownership_matrix" \
      --policy "$stage_policy_matrix" \
      --runtime-policy "$codex_runtime_policy"
else
  skip_check "hook-governance-gate-registry" "validate_gate_registry.py or governance matrices not found"
fi

gate_taxonomy_verifier=""
for candidate in "codex/scripts/hook-governance/verify_gate_taxonomy.py" "scripts/hook-governance/verify_gate_taxonomy.py"; do
  if [[ -f "$candidate" ]]; then
    gate_taxonomy_verifier="$candidate"
    break
  fi
done

if [[ -n "$gate_taxonomy_verifier" ]]; then
  run_check "hook-governance-gate-taxonomy" \
    "$python_bin" "$gate_taxonomy_verifier" \
      --inventory "$hook_inventory_output"
else
  skip_check "hook-governance-gate-taxonomy" "verify_gate_taxonomy.py not found"
fi

public_api_classifier=""
for candidate in "codex/scripts/hook-governance/classify_public_api.py" "scripts/hook-governance/classify_public_api.py"; do
  if [[ -f "$candidate" ]]; then
    public_api_classifier="$candidate"
    break
  fi
done

public_api_rules=""
for candidate in "codex/docs/hooks-governance/public-api-rules.yaml" "docs/hooks-governance/public-api-rules.yaml"; do
  if [[ -f "$candidate" ]]; then
    public_api_rules="$candidate"
    break
  fi
done

public_api_output=""
for candidate in "codex/docs/hooks-governance/public-api-classification.json" "docs/hooks-governance/public-api-classification.json"; do
  if [[ -f "$candidate" || -d "$(dirname "$candidate")" ]]; then
    public_api_output="$candidate"
    break
  fi
done
if [[ -z "$public_api_output" ]]; then
  public_api_output="docs/hooks-governance/public-api-classification.json"
fi
if [[ "$fast_mode" -eq 1 && "$persist_fast_governance" -eq 0 ]]; then
  if [[ -z "$fast_mode_governance_dir" ]]; then
    fast_mode_governance_dir="${repo_root}/.tmp/verify-work-governance"
    mkdir -p "$fast_mode_governance_dir"
  fi
  public_api_output="${fast_mode_governance_dir}/public-api-classification.json"
  fast_mode_temp_reports+=("docs/hooks-governance/public-api-classification.json -> ${public_api_output}")
fi

if [[ -n "$public_api_classifier" && -n "$public_api_rules" ]]; then
  run_check "hook-governance-public-api-classification" \
    "$python_bin" "$public_api_classifier" \
      --inventory "$hook_inventory_output" \
      --rules "$public_api_rules" \
      --out "$public_api_output"
else
  skip_check "hook-governance-public-api-classification" "classify_public_api.py or public-api-rules.yaml not found"
fi

docstring_ratchet_evaluator=""
for candidate in "codex/scripts/hook-governance/evaluate_docstring_ratchet.py" "scripts/hook-governance/evaluate_docstring_ratchet.py"; do
  if [[ -f "$candidate" ]]; then
    docstring_ratchet_evaluator="$candidate"
    break
  fi
done

docstring_ratchet_metrics=""
for candidate in "codex/docs/hooks-governance/docstring-ratchet-metrics.json" "docs/hooks-governance/docstring-ratchet-metrics.json"; do
  if [[ -f "$candidate" ]]; then
    docstring_ratchet_metrics="$candidate"
    break
  fi
done

docstring_ratchet_output=""
for candidate in "codex/docs/hooks-governance/docstring-ratchet-report.json" "docs/hooks-governance/docstring-ratchet-report.json"; do
  if [[ -f "$candidate" || -d "$(dirname "$candidate")" ]]; then
    docstring_ratchet_output="$candidate"
    break
  fi
done
if [[ -z "$docstring_ratchet_output" ]]; then
  docstring_ratchet_output="docs/hooks-governance/docstring-ratchet-report.json"
fi
if [[ "$fast_mode" -eq 1 && "$persist_fast_governance" -eq 0 ]]; then
  if [[ -z "$fast_mode_governance_dir" ]]; then
    fast_mode_governance_dir="${repo_root}/.tmp/verify-work-governance"
    mkdir -p "$fast_mode_governance_dir"
  fi
  docstring_ratchet_output="${fast_mode_governance_dir}/docstring-ratchet-report.json"
  fast_mode_temp_reports+=("docs/hooks-governance/docstring-ratchet-report.json -> ${docstring_ratchet_output}")
fi

if [[ -n "$docstring_ratchet_evaluator" && -n "$docstring_ratchet_metrics" ]]; then
  run_check "hook-governance-docstring-ratchet" \
    "$python_bin" "$docstring_ratchet_evaluator" \
      --classification "$public_api_output" \
      --metrics "$docstring_ratchet_metrics" \
      --window-days 14 \
      --out "$docstring_ratchet_output"
else
  skip_check "hook-governance-docstring-ratchet" "evaluate_docstring_ratchet.py or docstring-ratchet-metrics.json not found"
fi

arbitration_verifier=""
for candidate in "codex/scripts/hook-governance/arbitrate_hook_results.py" "scripts/hook-governance/arbitrate_hook_results.py"; do
  if [[ -f "$candidate" ]]; then
    arbitration_verifier="$candidate"
    break
  fi
done

arbitration_fixture=""
for candidate in "codex/scripts/tests/fixtures/arbitration/competing-blocks.json" "scripts/tests/fixtures/arbitration/competing-blocks.json"; do
  if [[ -f "$candidate" ]]; then
    arbitration_fixture="$candidate"
    break
  fi
done

if [[ -n "$arbitration_verifier" && -n "$arbitration_fixture" ]]; then
  run_check "hook-governance-arbitration" \
    "$python_bin" "$arbitration_verifier" \
      --fixture "$arbitration_fixture"
else
  skip_check "hook-governance-arbitration" "arbitrate_hook_results.py or fixture not found"
fi

conformance_generator=""
for candidate in "codex/scripts/hook-governance/generate_conformance.py" "scripts/hook-governance/generate_conformance.py"; do
  if [[ -f "$candidate" ]]; then
    conformance_generator="$candidate"
    break
  fi
done

conformance_validator=""
for candidate in "codex/scripts/hook-governance/validate_conformance.py" "scripts/hook-governance/validate_conformance.py"; do
  if [[ -f "$candidate" ]]; then
    conformance_validator="$candidate"
    break
  fi
done

conformance_schema=""
for candidate in "codex/schemas/hook-conformance.v1.schema.json" "schemas/hook-conformance.v1.schema.json"; do
  if [[ -f "$candidate" ]]; then
    conformance_schema="$candidate"
    break
  fi
done

if [[ -n "$conformance_generator" && -n "$hook_scope_manifest" && -n "$gate_ownership_matrix" && -n "$stage_policy_matrix" ]]; then
  run_check "hook-governance-conformance-generate" \
    "$python_bin" "$conformance_generator" \
      --manifest "$hook_scope_manifest" \
      --inventory "$hook_inventory_output" \
      --ownership "$gate_ownership_matrix" \
      --policy "$stage_policy_matrix" \
      --out-mode verify
else
  skip_check "hook-governance-conformance-generate" "generate_conformance.py or governance inputs not found"
fi

if [[ "$fast_mode" -eq 1 ]]; then
  skip_check "hook-governance-conformance-validate" \
    "cross-repository artifact freshness deferred by --fast; run full verify-work with governed repos available"
elif [[ -n "$conformance_validator" && -n "$conformance_schema" && -n "$hook_scope_manifest" && -n "$gate_ownership_matrix" && -n "$stage_policy_matrix" ]]; then
  run_check "hook-governance-conformance-validate" \
    "$python_bin" "$conformance_validator" \
      --schema "$conformance_schema" \
      --manifest "$hook_scope_manifest" \
      --ownership "$gate_ownership_matrix" \
      --policy "$stage_policy_matrix"
else
  skip_check "hook-governance-conformance-validate" "validate_conformance.py, schema, or governance inputs not found"
fi

rollout_checker=""
for candidate in "codex/scripts/hook-governance/rollout_check.py" "scripts/hook-governance/rollout_check.py"; do
  if [[ -f "$candidate" ]]; then
    rollout_checker="$candidate"
    break
  fi
done

rollout_check_output=""
for candidate in "codex/docs/hooks-governance/rollout-check-report.json" "docs/hooks-governance/rollout-check-report.json"; do
  if [[ -f "$candidate" || -d "$(dirname "$candidate")" ]]; then
    rollout_check_output="$candidate"
    break
  fi
done
if [[ -z "$rollout_check_output" ]]; then
  rollout_check_output="docs/hooks-governance/rollout-check-report.json"
fi
if [[ "$fast_mode" -eq 1 && "$persist_fast_governance" -eq 0 ]]; then
  if [[ -z "$fast_mode_governance_dir" ]]; then
    fast_mode_governance_dir="${repo_root}/.tmp/verify-work-governance"
    mkdir -p "$fast_mode_governance_dir"
  fi
  rollout_check_output="${fast_mode_governance_dir}/rollout-check-report.json"
  fast_mode_temp_reports+=("docs/hooks-governance/rollout-check-report.json -> ${rollout_check_output}")
fi

if [[ -n "$rollout_checker" ]]; then
  run_check "hook-governance-rollout-check" \
    "$python_bin" "$rollout_checker" \
      --inventory "$hook_inventory_output" \
      --recovery-slo-hours 24 \
      --out "$rollout_check_output"
else
  skip_check "hook-governance-rollout-check" "rollout_check.py not found"
fi

execpolicy_validator=""
for candidate in "codex/scripts/validate-execpolicy-rules.py" "scripts/validate-execpolicy-rules.py"; do
  if [[ -f "$candidate" ]]; then
    execpolicy_validator="$candidate"
    break
  fi
done

# GOVERNANCE: Changes to verify-work.sh require running $validation-contract-check
# (including the execpolicy-rule-validation step) per AGENTS.md, and capturing
# the workflow run ID or log artifact.
if [[ -n "$execpolicy_validator" ]]; then
  execpolicy_timeout_default=12
  execpolicy_retries_default=1
  if [[ "$fast_mode" -eq 1 ]]; then
    execpolicy_timeout_default=2
    execpolicy_retries_default=0
  fi
  run_check "execpolicy-rule-validation" env \
    CODEX_EXECPOLICY_TIMEOUT_SEC="${CODEX_EXECPOLICY_TIMEOUT_SEC:-$execpolicy_timeout_default}" \
    CODEX_EXECPOLICY_RETRIES="${CODEX_EXECPOLICY_RETRIES:-$execpolicy_retries_default}" \
    "$python_bin" "$execpolicy_validator"
else
  skip_check "execpolicy-rule-validation" "validate-execpolicy-rules.py not found"
fi

quick_validator="utilities/skill-creator/scripts/quick_validate.py"
skill_gate="utilities/skill-creator/scripts/skill_gate.py"
openclaw_guard="utilities/skill-creator/scripts/openclaw_skill_guard.py"

if [[ -f "$quick_validator" && -f "$skill_gate" ]]; then
  skill_dirs=()
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    skill_dirs+=("$line")
  done < <(
    if [[ "$changed_only" -eq 1 ]]; then
      collect_changed_skill_dirs
    else
      collect_all_skill_dirs
    fi
  )

  if [[ ${#skill_dirs[@]} -eq 0 ]]; then
    skip_check "skill-validations" "no skill directories matched selection mode"
  else
    echo
    echo "[verify-work] validating ${#skill_dirs[@]} skill directory(ies)..."
    for skill_dir in "${skill_dirs[@]}"; do
      run_check "quick-validate:$skill_dir" \
        "$python_bin" "$quick_validator" "$skill_dir" --target codex --mode compat
      run_check "skill-gate:$skill_dir" \
        "$python_bin" "$skill_gate" "$skill_dir"
      if [[ "$fast_mode" -eq 1 ]]; then
        skip_check "openclaw-guard:$skill_dir" "disabled by --fast"
      elif [[ -f "$openclaw_guard" ]]; then
        run_check "openclaw-guard:$skill_dir" \
          "$python_bin" "$openclaw_guard" "$skill_dir" --mode both
      else
        skip_check "openclaw-guard:$skill_dir" "openclaw_skill_guard.py not found"
      fi
    done
  fi
else
  skip_check "skill-validations" "skill-creator validators not found in repo"
fi

if [[ "$fast_mode" -eq 1 ]]; then
  skip_check "recursive-promotion-validation" "disabled by --fast"
elif [[ -f "scripts/validate_recursive_promotions.sh" ]]; then
  run_check "recursive-promotion-validation" bash "scripts/validate_recursive_promotions.sh"
else
  skip_check "recursive-promotion-validation" "scripts/validate_recursive_promotions.sh not found"
fi

if [[ "$fast_mode" -eq 1 && "$persist_fast_governance" -eq 0 && ${#fast_mode_temp_reports[@]} -gt 0 ]]; then
  echo
  echo "[verify-work] fast mode wrote volatile governance reports to temporary paths:"
  for item in "${fast_mode_temp_reports[@]}"; do
    echo "  - $item"
  done
  echo "[verify-work] canonical docs/hooks-governance report files were left unchanged."
fi

echo
echo "=== verify-work summary ==="
echo "passed:  ${#passed_checks[@]}"
if [[ ${#passed_checks[@]} -gt 0 ]]; then
  for item in "${passed_checks[@]}"; do
    echo "  - $item"
  done
fi

echo "skipped: ${#skipped_checks[@]}"
if [[ ${#skipped_checks[@]} -gt 0 ]]; then
  for item in "${skipped_checks[@]}"; do
    echo "  - $item"
  done
fi

echo "failed:  ${#failed_checks[@]}"
if [[ ${#failed_checks[@]} -gt 0 ]]; then
  for item in "${failed_checks[@]}"; do
    echo "  - $item"
  done
fi

if [[ ${#failed_checks[@]} -gt 0 ]]; then
  exit 1
fi

if [[ "$fail_on_skips" -eq 1 && ${#skipped_checks[@]} -gt 0 ]]; then
  echo "[verify-work] strict mode failed: one or more checks were skipped." >&2
  exit 1
fi

exit 0
