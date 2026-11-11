#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  printf '❌ validate-auto-review-scope.sh requires bash. Run: bash scripts/validate-auto-review-scope.sh [options]\n' >&2
  # shellcheck disable=SC2317
  return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '❌ validate-auto-review-scope.sh is CLI-only; do not source it. Run: bash scripts/validate-auto-review-scope.sh [options]\n' >&2
  return 2
fi

set -euo pipefail

dots_helper_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_helper_dir/admit-hook-fixture.py" '{}' || exit $?

script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -P "$script_dir/.." && pwd -P)"
hooks_file="$repo_root/hooks/hooks.json"
readme_file="$repo_root/hooks/README.md"
config_file="$repo_root/config.toml"

fail() {
  echo "[validate-auto-review-scope] $1" >&2
  exit 1
}

assert_jq() {
  local input="$1"
  local filter="$2"
  local message="$3"

  if ! printf '%s' "$input" | jq -e "$filter" >/dev/null; then
    fail "assertion failed: $message"
  fi
}

source "$script_dir/codex-validation-lib.sh"

[[ -f "$hooks_file" ]] || fail "missing hooks file: $hooks_file"
[[ -f "$readme_file" ]] || fail "missing hooks README: $readme_file"
[[ -f "$config_file" ]] || fail "missing config file: $config_file"

hooks_json="$(cat "$hooks_file")"
python_bin="$(codex_select_validation_python "validate-auto-review-scope")"

assert_jq "$hooks_json" '[.hooks | to_entries[] | .value[]?.hooks[]?.type] | all(. == "command")' "all configured hook types must stay command-based"
assert_jq "$hooks_json" '[.. | objects | .type? // empty] | all(. != "agent" and . != "prompt")' "hooks must not rely on runtime-skipped type=agent/type=prompt enforcement"

if ! "${python_bin}" - "$readme_file" <<'PY'; then
import pathlib
import re
import sys

readme_path = pathlib.Path(sys.argv[1])
content = readme_path.read_text(encoding="utf-8")
normalized = re.sub(r"\s+", " ", content).lower()
required = "auto-review is configured through codex approvals settings"
forbidden = "guardian-subagent review"
if required not in normalized or forbidden in normalized:
    raise SystemExit(1)
PY
  fail "hooks README must document auto-review approval scope without legacy guardian-subagent wording"
fi

if ! "${python_bin}" - "$config_file" <<'PY'; then
import importlib.util
import pathlib
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

config_path = pathlib.Path(sys.argv[1])
repo_root = config_path.parent
sys.path.insert(0, str(repo_root / "scripts"))
spec = importlib.util.spec_from_file_location(
    "validate_codex_config", repo_root / "scripts" / "validate-codex-config.py"
)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load canonical config validator")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
with config_path.open("rb") as fh:
    data = tomllib.load(fh)

errors = validator.validate_root_approvals_reviewer(data)
validator.validate_default_auto_review_policy(data, "root config", errors)
if data.get("approval_policy") != "on-request":
    errors.append("root approval_policy must stay on-request for automatic review")
if "guardian_approval" in data.get("features", {}):
    errors.append("legacy guardian_approval must remain absent")

permissions = data.get("permissions")
readonly = permissions.get("readonly-net") if isinstance(permissions, dict) else None
network = readonly.get("network") if isinstance(readonly, dict) else None
domains = network.get("domains") if isinstance(network, dict) else None
if not isinstance(domains, dict) or domains.get("ollama.com") != "allow":
    errors.append("readonly-net must retain the approved Ollama endpoint")

profiles = validator.load_profile_configs(errors)
for name, profile in profiles.items():
    validator.validate_default_auto_review_policy(profile, name, errors)
    if profile.get("approvals_reviewer", data.get("approvals_reviewer")) != "auto_review":
        errors.append(f"{name} must retain approvals_reviewer=auto_review")
    if "guardian_approval" in profile.get("features", {}):
        errors.append(f"{name} must not restore guardian_approval")
validator.validate_oss_profile_contracts(profiles, errors)
if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
PY
  fail "config must retain automatic review and inherit the active reviewer policy"
fi

echo "[validate-auto-review-scope] OK"
