"""Validate the cross-repo gate registry against current Codex runtime rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


def _fixture_scope():
    import importlib.util
    from pathlib import Path

    directory = Path(__file__).resolve().parent
    if directory.name == "hook-governance":
        directory = directory.parent
    spec = importlib.util.spec_from_file_location(
        "dots_helper_scope", directory / "helper_fixture_scope.py"
    )
    scope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scope)
    return scope


def _fixture_args(arguments):
    return _fixture_scope().admit_file(__file__, arguments)


def _fixture_resource(value):
    return _fixture_scope().resource(value)


def _fixture_text(text):
    from pathlib import Path

    directory = Path(__file__).resolve().parent
    if directory.name == "hook-governance":
        directory = directory.parent
    policy = directory.parent
    return (
        text.replace("@POLICY_SOURCE@", str(policy))
        .replace("@REPO@", str(policy.parent))
        .replace("@HOME@", str(Path.home()))
    )


def _fixture_open(*args, **kwargs):
    return _fixture_scope().fixture_open(*args, **kwargs)


class GateRegistryValidationError(ValueError):
    """Raised when the gate registry violates the runtime contract."""


def load_structured_file(path: Path) -> object:
    raw_text = _fixture_resource(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        if yaml is not None:
            return yaml.safe_load(raw_text)
    raise GateRegistryValidationError(
        f"unable to parse structured registry file '{path}' as JSON or YAML"
    )


def contains_continue_false(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("continue") is False:
            return True
        return any(contains_continue_false(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_continue_false(item) for item in value)
    return False


def runtime_policy_claims_continue_false_supported(runtime_policy: str) -> bool:
    lowered = runtime_policy.lower()
    if "continue:false" not in lowered:
        return False
    unsupported_markers = ("unsupported", "must not", "do not use", "not supported")
    return not any(marker in lowered for marker in unsupported_markers)


def collect_active_profile_types(inventory: object) -> set[str]:
    if not isinstance(inventory, dict):
        return set()
    repositories = inventory.get("repositories", [])
    if not isinstance(repositories, list):
        return set()
    active_profile_types: set[str] = set()
    for repo in repositories:
        if isinstance(repo, dict):
            profile_type = repo.get("profile_type")
            if isinstance(profile_type, str) and profile_type:
                active_profile_types.add(profile_type)
    return active_profile_types


def validate_ownership_entries(
    ownership: object,
    required_gate_categories: list[str],
    active_profile_types: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(ownership, dict):
        return ["ownership registry must be a mapping"]
    owners = ownership.get("owners", [])
    if not isinstance(owners, list):
        return ["ownership registry must define an owners list"]
    seen_keys: set[tuple[str, str, str]] = set()
    gates_by_profile: dict[str, set[str]] = {
        profile_type: set() for profile_type in active_profile_types
    }
    for entry in owners:
        if not isinstance(entry, dict):
            errors.append("ownership entries must be mappings")
            continue
        profile_type = entry.get("profile_type")
        stage = entry.get("stage")
        gate_id = entry.get("gate_id")
        if not all(
            isinstance(value, str) and value for value in (profile_type, stage, gate_id)
        ):
            errors.append(
                "ownership entries must include non-empty profile_type, stage, and gate_id"
            )
            continue
        key = (profile_type, stage, gate_id)
        if key in seen_keys:
            errors.append(
                f"duplicate owner for profile_type='{profile_type}', stage='{stage}', gate_id='{gate_id}'"
            )
        else:
            seen_keys.add(key)
        if profile_type in gates_by_profile:
            gates_by_profile[profile_type].add(gate_id)
    for profile_type in sorted(active_profile_types):
        present_gates = gates_by_profile.get(profile_type, set())
        for gate_id in required_gate_categories:
            if gate_id not in present_gates:
                errors.append(
                    f"missing gate category '{gate_id}' for profile_type='{profile_type}'"
                )
    return errors


def validate_event_capabilities(policy: dict[str, object]) -> list[str]:
    errors: list[str] = []
    events = policy.get("events", {})
    if not isinstance(events, dict):
        return ["stage policy registry events must be a mapping"]
    for event_name in ("Stop", "UserPromptSubmit"):
        event_policy = events.get(event_name)
        if (
            isinstance(event_policy, dict)
            and event_policy.get("matcher_supported") is True
        ):
            errors.append(
                f"event '{event_name}' must not declare matcher support in the stage policy"
            )
    return errors


def validate_repo_entrypoints(
    inventory: object,
    required_stage_entrypoints: list[str],
    require_commit_msg_policy: bool,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(inventory, dict):
        return errors
    repositories = inventory.get("repositories", [])
    if not isinstance(repositories, list):
        return errors
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        repo_name = repo.get("repo_name")
        if not isinstance(repo_name, str) or not repo_name:
            continue
        gate_entrypoints = repo.get("gate_entrypoints", {})
        if not isinstance(gate_entrypoints, dict):
            gate_entrypoints = {}
        for entrypoint in required_stage_entrypoints:
            if entrypoint not in gate_entrypoints:
                errors.append(
                    f"repo '{repo_name}' missing required gate entrypoint '{entrypoint}'"
                )
        commit_msg_policy = repo.get("commit_msg_policy")
        if require_commit_msg_policy and (not isinstance(commit_msg_policy, dict)):
            errors.append(f"repo '{repo_name}' missing commit_msg_policy state")
    return errors


def validate_gate_registry(
    inventory_path: Path,
    ownership_path: Path,
    policy_path: Path,
    runtime_policy_path: Path,
) -> list[str]:
    inventory = load_structured_file(inventory_path)
    ownership = load_structured_file(ownership_path)
    policy = load_structured_file(policy_path)
    runtime_policy = _fixture_resource(runtime_policy_path).read_text(encoding="utf-8")
    errors: list[str] = []
    if not isinstance(inventory, dict) or inventory.get("schema_version") != 1:
        errors.append("inventory schema_version must be 1")
    active_profile_types = collect_active_profile_types(inventory)
    if not isinstance(policy, dict):
        errors.append("stage policy registry must be a mapping")
    else:
        errors.extend(validate_event_capabilities(policy))
        required_gate_categories = policy.get("required_gate_categories", [])
        if not isinstance(required_gate_categories, list) or not all(
            isinstance(item, str) and item for item in required_gate_categories
        ):
            errors.append(
                "stage policy registry must define required_gate_categories as a list of gate ids"
            )
            required_gate_categories = []
        required_stage_entrypoints = policy.get("required_stage_entrypoints", [])
        if required_stage_entrypoints is None:
            required_stage_entrypoints = []
        if not isinstance(required_stage_entrypoints, list) or not all(
            isinstance(item, str) and item for item in required_stage_entrypoints
        ):
            errors.append(
                "stage policy registry must define required_stage_entrypoints as a list of entrypoint ids"
            )
            required_stage_entrypoints = []
        require_commit_msg_policy = policy.get("require_commit_msg_policy", False)
        if not isinstance(require_commit_msg_policy, bool):
            errors.append(
                "stage policy registry must define require_commit_msg_policy as a boolean"
            )
            require_commit_msg_policy = False
        errors.extend(
            validate_ownership_entries(
                ownership=ownership,
                required_gate_categories=required_gate_categories,
                active_profile_types=active_profile_types,
            )
        )
        errors.extend(
            validate_repo_entrypoints(
                inventory=inventory,
                required_stage_entrypoints=required_stage_entrypoints,
                require_commit_msg_policy=require_commit_msg_policy,
            )
        )
        events_raw = policy.get("events", {})
        if not isinstance(events_raw, dict):
            events = {}
        else:
            events = events_raw
        pre_tool_use = events.get("PreToolUse")
        if contains_continue_false(pre_tool_use):
            errors.append(
                "PreToolUse blockers must not rely on continue:false; use hookSpecificOutput.permissionDecision=deny, decision=block, or exit code 2"
            )
    if runtime_policy_claims_continue_false_supported(runtime_policy):
        errors.append(
            "runtime policy must describe continue:false as unsupported for PreToolUse blockers"
        )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--ownership", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--runtime-policy", required=True, type=Path)
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    errors = validate_gate_registry(
        inventory_path=args.inventory.resolve(),
        ownership_path=args.ownership.resolve(),
        policy_path=args.policy.resolve(),
        runtime_policy_path=args.runtime_policy.resolve(),
    )
    if errors:
        for error in errors:
            print(f"[validate_gate_registry] {error}")
        return 1
    print("[validate_gate_registry] OK")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
