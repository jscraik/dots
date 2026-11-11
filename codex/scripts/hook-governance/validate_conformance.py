"""Validate per-repo hook conformance artifacts."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


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


class ConformanceValidationError(ValueError):
    """Raised when conformance artifacts fail contract validation."""


def _load_generate_module():
    module_path = Path(__file__).resolve().parent / "generate_conformance.py"
    spec = importlib.util.spec_from_file_location("generate_conformance", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Unable to load conformance generator module from {module_path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATE_MODULE = _load_generate_module()


def load_json_file(path: Path) -> object:
    try:
        return json.loads(_fixture_resource(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConformanceValidationError(
            f"unable to parse JSON payload '{path}': {exc}"
        ) from exc


def expected_schema_version(schema: dict[str, object]) -> str:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return "hook-conformance.v1"
    schema_version = properties.get("schema_version", {})
    if not isinstance(schema_version, dict):
        return "hook-conformance.v1"
    const_value = schema_version.get("const")
    if isinstance(const_value, str) and const_value:
        return const_value
    return "hook-conformance.v1"


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_stage_shape(stage: object, index: int, errors: list[str]) -> None:
    if not isinstance(stage, dict):
        errors.append(f"stages[{index}] must be an object")
        return
    required_fields = (
        "stage",
        "gate_id",
        "owner_layer",
        "command",
        "severity_mode",
        "scope",
        "timeout_seconds",
    )
    for field_name in required_fields:
        if field_name not in stage:
            errors.append(f"stages[{index}] missing required field '{field_name}'")
    if "timeout_seconds" in stage and (not isinstance(stage["timeout_seconds"], int)):
        errors.append(f"stages[{index}].timeout_seconds must be an integer")
    for field_name in (
        "stage",
        "gate_id",
        "owner_layer",
        "command",
        "severity_mode",
        "scope",
    ):
        if field_name in stage and (not _is_non_empty_string(stage[field_name])):
            errors.append(f"stages[{index}].{field_name} must be a non-empty string")


def validate_drift_flag_shape(flag: object, index: int, errors: list[str]) -> None:
    if not isinstance(flag, dict):
        errors.append(f"drift_flags[{index}] must be an object")
        return
    required_fields = ("id", "severity", "summary", "detected_at")
    for field_name in required_fields:
        if field_name not in flag:
            errors.append(f"drift_flags[{index}] missing required field '{field_name}'")
    for field_name in required_fields:
        if field_name in flag and (not _is_non_empty_string(flag[field_name])):
            errors.append(
                f"drift_flags[{index}].{field_name} must be a non-empty string"
            )
    if "severity" in flag and flag.get("severity") not in {"low", "medium", "high"}:
        errors.append(f"drift_flags[{index}].severity must be one of low|medium|high")
    if "detected_at" in flag and _is_non_empty_string(flag.get("detected_at")):
        try:
            GENERATE_MODULE.parse_rfc3339_utc(flag["detected_at"])
        except ValueError:
            errors.append(f"drift_flags[{index}].detected_at must be RFC3339 UTC")


def validate_arbitration_decision_shape(
    decision: object, index: int, errors: list[str]
) -> None:
    if not isinstance(decision, dict):
        errors.append(f"arbitration_decisions[{index}] must be an object")
        return
    required_string_fields = (
        "decision_id",
        "event_type",
        "trigger_command",
        "winner_source_path",
        "winning_gate_id",
        "winning_owner_layer",
    )
    required_int_fields = ("candidate_result_count", "suppressed_reason_count")
    for field_name in required_string_fields + required_int_fields:
        if field_name not in decision:
            errors.append(
                f"arbitration_decisions[{index}] missing required field '{field_name}'"
            )
    for field_name in required_string_fields:
        if field_name in decision and (not isinstance(decision[field_name], str)):
            errors.append(
                f"arbitration_decisions[{index}].{field_name} must be a string"
            )
    for field_name in required_int_fields:
        if field_name in decision and (not isinstance(decision[field_name], int)):
            errors.append(
                f"arbitration_decisions[{index}].{field_name} must be an integer"
            )


def validate_artifact_shape(
    artifact: object, expected_version: str, artifact_path: Path
) -> list[str]:
    errors: list[str] = []
    if not isinstance(artifact, dict):
        return [f"artifact '{artifact_path}' must be a JSON object"]
    required_top_level = (
        "schema_version",
        "artifact_generated_at",
        "evaluated_at",
        "repo_path",
        "profile",
        "frameworks_active",
        "hook_config_digest",
        "evaluated_hook_config_digest",
        "stages",
        "drift_flags",
        "arbitration_decisions",
        "freshness_status",
    )
    for field_name in required_top_level:
        if field_name not in artifact:
            errors.append(
                f"artifact '{artifact_path}' missing required field '{field_name}'"
            )
    schema_version = artifact.get("schema_version")
    if schema_version != expected_version:
        errors.append(
            f"artifact '{artifact_path}' schema_version='{schema_version}' does not match expected '{expected_version}'"
        )
    for time_field in ("artifact_generated_at", "evaluated_at"):
        value = artifact.get(time_field)
        if not _is_non_empty_string(value):
            errors.append(
                f"artifact '{artifact_path}' field '{time_field}' must be a non-empty string"
            )
            continue
        try:
            GENERATE_MODULE.parse_rfc3339_utc(value)
        except ValueError:
            errors.append(
                f"artifact '{artifact_path}' field '{time_field}' must be RFC3339 UTC"
            )
    for field_name in (
        "repo_path",
        "profile",
        "hook_config_digest",
        "evaluated_hook_config_digest",
    ):
        value = artifact.get(field_name)
        if not _is_non_empty_string(value):
            errors.append(
                f"artifact '{artifact_path}' field '{field_name}' must be a non-empty string"
            )
    frameworks_active = artifact.get("frameworks_active")
    if not isinstance(frameworks_active, list) or not all(
        isinstance(item, str) for item in frameworks_active
    ):
        errors.append(
            f"artifact '{artifact_path}' field 'frameworks_active' must be a string array"
        )
    stages = artifact.get("stages")
    if not isinstance(stages, list):
        errors.append(f"artifact '{artifact_path}' field 'stages' must be an array")
    else:
        for index, stage in enumerate(stages):
            validate_stage_shape(stage, index, errors)
    drift_flags = artifact.get("drift_flags")
    if not isinstance(drift_flags, list):
        errors.append(
            f"artifact '{artifact_path}' field 'drift_flags' must be an array"
        )
    else:
        for index, flag in enumerate(drift_flags):
            validate_drift_flag_shape(flag, index, errors)
    arbitration_decisions = artifact.get("arbitration_decisions")
    if not isinstance(arbitration_decisions, list):
        errors.append(
            f"artifact '{artifact_path}' field 'arbitration_decisions' must be an array"
        )
    else:
        for index, decision in enumerate(arbitration_decisions):
            validate_arbitration_decision_shape(decision, index, errors)
    freshness_status = artifact.get("freshness_status")
    if freshness_status not in {"fresh", "stale"}:
        errors.append(
            f"artifact '{artifact_path}' field 'freshness_status' must be fresh|stale"
        )
    return errors


def validate_conformance_artifacts(
    schema_path: Path,
    manifest_path: Path,
    ownership_path: Path,
    policy_path: Path,
    workspace_root_override: str | None = None,
) -> list[str]:
    schema = load_json_file(schema_path)
    if not isinstance(schema, dict):
        raise ConformanceValidationError("schema payload must be a JSON object")
    expected_version = expected_schema_version(schema)
    inventory = GENERATE_MODULE.build_inventory_from_manifest(
        manifest_path=manifest_path, workspace_root_override=workspace_root_override
    )
    if not isinstance(inventory, dict):
        raise ConformanceValidationError("inventory payload must be an object")
    repositories = inventory.get("repositories", [])
    if not isinstance(repositories, list):
        raise ConformanceValidationError("inventory.repositories must be a list")
    ownership = GENERATE_MODULE.load_structured_file(ownership_path)
    policy = GENERATE_MODULE.load_structured_file(policy_path)
    if not isinstance(ownership, dict):
        raise ConformanceValidationError("ownership payload must be an object")
    if not isinstance(policy, dict):
        raise ConformanceValidationError("policy payload must be an object")
    errors: list[str] = []
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        repo_name = repo.get("repo_name")
        if not isinstance(repo_name, str) or not repo_name:
            continue
        repo_path_raw = repo.get("repo_path")
        if not isinstance(repo_path_raw, str) or not repo_path_raw:
            errors.append(f"repo '{repo_name}' is missing repo_path in inventory")
            continue
        artifact_path = Path(repo_path_raw) / ".codex" / "hook-conformance.json"
        if not artifact_path.is_file():
            errors.append(
                f"repo '{repo_name}' missing conformance artifact: {artifact_path}"
            )
            continue
        artifact = load_json_file(artifact_path)
        errors.extend(
            validate_artifact_shape(artifact, expected_version, artifact_path)
        )
        if not isinstance(artifact, dict):
            continue
        evaluated_digest = GENERATE_MODULE.compute_repo_digest(repo, ownership, policy)
        recorded_evaluated_digest = artifact.get("evaluated_hook_config_digest")
        if recorded_evaluated_digest != evaluated_digest:
            errors.append(
                f"repo '{repo_name}' evaluated_hook_config_digest does not match current governance digest"
            )
        expected_freshness = GENERATE_MODULE.compute_freshness_status(
            artifact_generated_at=str(artifact.get("artifact_generated_at", "")),
            evaluated_at=str(artifact.get("evaluated_at", "")),
            hook_config_digest=str(artifact.get("hook_config_digest", "")),
            evaluated_hook_config_digest=evaluated_digest,
        )
        recorded_freshness = artifact.get("freshness_status")
        if recorded_freshness != expected_freshness:
            errors.append(
                f"repo '{repo_name}' freshness_status='{recorded_freshness}' expected '{expected_freshness}'"
            )
        if expected_freshness == "stale":
            errors.append(
                f"repo '{repo_name}' conformance artifact is stale and must be regenerated"
            )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ownership", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument(
        "--workspace-root",
        help="optional workspace_root override for manifest resolution",
    )
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    script_repo_root = Path(__file__).resolve().parents[2]
    docs_root = script_repo_root / "docs" / "hooks-governance"
    ownership_path = args.ownership or docs_root / "gate-ownership-matrix.yaml"
    policy_path = args.policy or docs_root / "stage-policy-matrix.yaml"
    try:
        errors = validate_conformance_artifacts(
            schema_path=args.schema.resolve(),
            manifest_path=args.manifest.resolve(),
            ownership_path=ownership_path.resolve(),
            policy_path=policy_path.resolve(),
            workspace_root_override=args.workspace_root,
        )
    except (ConformanceValidationError, FileNotFoundError) as exc:
        print(f"[validate_conformance] {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"[validate_conformance] {error}")
        return 1
    print("[validate_conformance] OK")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
