"""Generate per-repo hook conformance artifacts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_metadata import write_metadata

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


REQUIRED_GATE_IDS = (
    "docstrings",
    "lint",
    "typecheck",
    "spelling",
    "unit",
    "formatting",
)
STAGE_TO_ENTRYPOINT = {
    "pre-commit": "hooks-pre-commit",
    "pre-push": "hooks-pre-push",
    "commit-msg": "hooks-commit-msg",
}
STAGE_TO_SCOPE = {
    "pre-commit": "changed-files",
    "pre-push": "full-repo",
    "commit-msg": "commit-message",
}
STAGE_TO_TIMEOUT_SECONDS = {"pre-commit": 120, "pre-push": 300, "commit-msg": 30}


class ConformanceGenerationError(ValueError):
    """Raised when conformance generation cannot complete safely."""


def _load_inventory_module():
    module_path = Path(__file__).resolve().parent / "inventory_repos.py"
    spec = importlib.util.spec_from_file_location("inventory_repos", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load inventory module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVENTORY_MODULE = _load_inventory_module()


def load_structured_file(path: Path) -> object:
    raw_text = _fixture_resource(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        if yaml is not None:
            return yaml.safe_load(raw_text)
    raise ConformanceGenerationError(
        f"unable to parse structured file '{path}' as JSON or YAML"
    )


def format_rfc3339_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_rfc3339_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def utc_now_rfc3339() -> str:
    return format_rfc3339_utc(datetime.now(UTC))


def stable_digest(payload: object) -> str:
    packed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(packed).hexdigest()


def compute_freshness_status(
    artifact_generated_at: str,
    evaluated_at: str,
    hook_config_digest: str,
    evaluated_hook_config_digest: str,
) -> str:
    try:
        generated = parse_rfc3339_utc(artifact_generated_at)
        evaluated = parse_rfc3339_utc(evaluated_at)
    except ValueError:
        return "stale"
    if evaluated - generated > timedelta(days=7):
        return "stale"
    if hook_config_digest != evaluated_hook_config_digest:
        return "stale"
    return "fresh"


def _validate_repos_payload(manifest: dict[str, object]) -> tuple[list[str], list[str]]:
    repos = manifest.get("repos", {})
    if not isinstance(repos, dict):
        raise ConformanceGenerationError("repos must be an object in the manifest")
    in_scope = repos.get("in_scope", [])
    excluded = repos.get("excluded", [])
    if not isinstance(in_scope, list) or not all(
        isinstance(item, str) for item in in_scope
    ):
        raise ConformanceGenerationError("repos.in_scope must be a list of repo names")
    if not isinstance(excluded, list) or not all(
        isinstance(item, str) for item in excluded
    ):
        raise ConformanceGenerationError("repos.excluded must be a list of repo names")
    overlap = sorted(set(in_scope).intersection(set(excluded)))
    if overlap:
        raise ConformanceGenerationError(
            f"excluded repo '{overlap[0]}' must not appear in repos.in_scope"
        )
    return (in_scope, excluded)


def build_inventory_from_manifest(
    manifest_path: Path, workspace_root_override: str | None = None
) -> dict[str, object]:
    manifest = INVENTORY_MODULE.load_manifest(manifest_path)
    if workspace_root_override is not None:
        manifest["workspace_root"] = workspace_root_override
    in_scope, excluded = _validate_repos_payload(manifest)
    workspace_root = INVENTORY_MODULE.resolve_workspace_root(manifest_path, manifest)
    repositories: list[dict[str, object]] = []
    missing_repositories: list[dict[str, str]] = []
    for repo_name in in_scope:
        repo_path = workspace_root / repo_name
        if not repo_path.is_dir():
            missing_repositories.append(
                {
                    "repo_name": repo_name,
                    "repo_path": str(repo_path),
                    "reason": "repo path is not present on this machine",
                }
            )
            print(
                f"[generate_conformance] skipping absent in-scope repo '{repo_name}': {repo_path}"
            )
            continue
        frameworks_present = INVENTORY_MODULE.detect_frameworks(repo_path)
        gate_entrypoints = INVENTORY_MODULE.detect_make_entrypoints(repo_path)
        repositories.append(
            {
                "repo_name": repo_name,
                "repo_path": str(repo_path),
                "frameworks_present": frameworks_present,
                "gate_entrypoints": gate_entrypoints,
                "commit_msg_policy": INVENTORY_MODULE.detect_commit_msg_policy(
                    repo_path
                ),
                "profile_type": INVENTORY_MODULE.classify_profile_type(
                    frameworks_present, gate_entrypoints
                ),
            }
        )
    return {
        "schema_version": 1,
        "workspace_root": str(workspace_root),
        "repositories": repositories,
        "missing_repositories": missing_repositories,
        "excluded_repositories": sorted(excluded),
    }


def command_for_stage(repo_record: dict[str, object], stage: str) -> str:
    gate_entrypoints = repo_record.get("gate_entrypoints", {})
    if not isinstance(gate_entrypoints, dict):
        gate_entrypoints = {}
    entrypoint = STAGE_TO_ENTRYPOINT.get(stage)
    if entrypoint is None:
        return "unmapped-stage"
    command = gate_entrypoints.get(entrypoint)
    if isinstance(command, str) and command.strip():
        return command
    if stage == "commit-msg":
        commit_msg_policy = repo_record.get("commit_msg_policy")
        if isinstance(commit_msg_policy, dict):
            policy_command = commit_msg_policy.get("command")
            if isinstance(policy_command, str) and policy_command.strip():
                return policy_command
    return "missing-command"


def build_stage_entries(
    repo_record: dict[str, object], ownership: dict[str, object]
) -> list[dict[str, object]]:
    profile_type = repo_record.get("profile_type")
    if not isinstance(profile_type, str) or not profile_type:
        return []
    owners = ownership.get("owners", [])
    if not isinstance(owners, list):
        return []
    selected: list[dict[str, object]] = []
    for entry in owners:
        if not isinstance(entry, dict):
            continue
        if entry.get("profile_type") != profile_type:
            continue
        stage = entry.get("stage")
        gate_id = entry.get("gate_id")
        owner_layer = entry.get("owner_layer")
        if not all(isinstance(v, str) and v for v in (stage, gate_id, owner_layer)):
            continue
        selected.append(
            {
                "stage": stage,
                "gate_id": gate_id,
                "owner_layer": owner_layer,
                "command": command_for_stage(repo_record, stage),
                "severity_mode": "hard-block",
                "scope": STAGE_TO_SCOPE.get(stage, "unknown"),
                "timeout_seconds": STAGE_TO_TIMEOUT_SECONDS.get(stage, 120),
            }
        )
    selected.sort(
        key=lambda item: (item["stage"], item["gate_id"], item["owner_layer"])
    )
    return selected


def load_arbitration_decisions(repo_path: Path) -> list[dict[str, object]]:
    audit_path = repo_path / ".codex" / "hook-arbitration-decisions.json"
    if not audit_path.is_file():
        return []
    try:
        payload = json.loads(_fixture_resource(audit_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    required_fields = (
        "decision_id",
        "event_type",
        "trigger_command",
        "candidate_result_count",
        "suppressed_reason_count",
        "winner_source_path",
        "winning_gate_id",
        "winning_owner_layer",
    )
    decisions: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if not all(field in item for field in required_fields):
            continue
        try:
            decisions.append(
                {
                    "decision_id": str(item["decision_id"]),
                    "event_type": str(item["event_type"]),
                    "trigger_command": str(item["trigger_command"]),
                    "candidate_result_count": int(item["candidate_result_count"]),
                    "suppressed_reason_count": int(item["suppressed_reason_count"]),
                    "winner_source_path": str(item["winner_source_path"]),
                    "winning_gate_id": str(item["winning_gate_id"]),
                    "winning_owner_layer": str(item["winning_owner_layer"]),
                }
            )
        except (TypeError, ValueError):
            continue
    return decisions


def build_drift_flags(
    repo_record: dict[str, object],
    policy: dict[str, object],
    stage_entries: list[dict[str, object]],
    detected_at: str,
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    gate_entrypoints = repo_record.get("gate_entrypoints", {})
    if not isinstance(gate_entrypoints, dict):
        gate_entrypoints = {}
    required_stage_entrypoints = policy.get("required_stage_entrypoints", [])
    if isinstance(required_stage_entrypoints, list):
        missing_entrypoints = [
            item
            for item in required_stage_entrypoints
            if isinstance(item, str) and item and (item not in gate_entrypoints)
        ]
        if missing_entrypoints:
            flags.append(
                {
                    "id": "missing-stage-entrypoints",
                    "severity": "high",
                    "summary": "missing required stage entrypoints: "
                    + ", ".join(sorted(missing_entrypoints)),
                    "detected_at": detected_at,
                }
            )
    require_commit_msg_policy = policy.get("require_commit_msg_policy", False)
    if require_commit_msg_policy and (
        not isinstance(repo_record.get("commit_msg_policy"), dict)
    ):
        flags.append(
            {
                "id": "missing-commit-msg-policy",
                "severity": "medium",
                "summary": "commit message policy state is missing",
                "detected_at": detected_at,
            }
        )
    required_gate_categories = policy.get("required_gate_categories", [])
    present_gates = {
        item.get("gate_id") for item in stage_entries if isinstance(item, dict)
    }
    if isinstance(required_gate_categories, list):
        missing_gate_categories = [
            gate_id
            for gate_id in required_gate_categories
            if isinstance(gate_id, str) and gate_id and (gate_id not in present_gates)
        ]
        if missing_gate_categories:
            flags.append(
                {
                    "id": "missing-gate-categories",
                    "severity": "high",
                    "summary": "missing required gate categories: "
                    + ", ".join(sorted(missing_gate_categories)),
                    "detected_at": detected_at,
                }
            )
    frameworks_present = repo_record.get("frameworks_present", [])
    if isinstance(frameworks_present, list) and len(frameworks_present) > 1:
        flags.append(
            {
                "id": "mixed-framework-signals",
                "severity": "medium",
                "summary": "multiple hook framework markers are active",
                "detected_at": detected_at,
            }
        )
    return flags


def build_digest_context(
    repo_record: dict[str, object],
    ownership: dict[str, object],
    policy: dict[str, object],
) -> dict[str, object]:
    profile_type = repo_record.get("profile_type")
    owners = ownership.get("owners", [])
    filtered_owners: list[dict[str, str]] = []
    if isinstance(owners, list) and isinstance(profile_type, str):
        for entry in owners:
            if not isinstance(entry, dict):
                continue
            if entry.get("profile_type") != profile_type:
                continue
            stage = entry.get("stage")
            gate_id = entry.get("gate_id")
            owner_layer = entry.get("owner_layer")
            if all(isinstance(v, str) and v for v in (stage, gate_id, owner_layer)):
                filtered_owners.append(
                    {"stage": stage, "gate_id": gate_id, "owner_layer": owner_layer}
                )
    filtered_owners.sort(
        key=lambda item: (item["stage"], item["gate_id"], item["owner_layer"])
    )
    gate_entrypoints = repo_record.get("gate_entrypoints", {})
    if not isinstance(gate_entrypoints, dict):
        gate_entrypoints = {}
    frameworks_present = repo_record.get("frameworks_present", [])
    if not isinstance(frameworks_present, list):
        frameworks_present = []
    return {
        "repo_name": repo_record.get("repo_name"),
        "repo_path": repo_record.get("repo_path"),
        "profile_type": profile_type,
        "frameworks_present": sorted(
            [item for item in frameworks_present if isinstance(item, str)]
        ),
        "gate_entrypoints": gate_entrypoints,
        "commit_msg_policy": repo_record.get("commit_msg_policy"),
        "ownership": filtered_owners,
        "required_gate_categories": policy.get(
            "required_gate_categories", list(REQUIRED_GATE_IDS)
        ),
        "required_stage_entrypoints": policy.get("required_stage_entrypoints", []),
        "require_commit_msg_policy": policy.get("require_commit_msg_policy", False),
    }


def compute_repo_digest(
    repo_record: dict[str, object],
    ownership: dict[str, object],
    policy: dict[str, object],
) -> str:
    return stable_digest(build_digest_context(repo_record, ownership, policy))


def build_conformance_artifact(
    repo_record: dict[str, object],
    ownership: dict[str, object],
    policy: dict[str, object],
    artifact_generated_at: str,
    evaluated_at: str,
) -> dict[str, object]:
    repo_path_raw = repo_record.get("repo_path")
    if not isinstance(repo_path_raw, str) or not repo_path_raw:
        raise ConformanceGenerationError("repo record missing repo_path")
    repo_path = Path(repo_path_raw)
    hook_config_digest = compute_repo_digest(repo_record, ownership, policy)
    evaluated_hook_config_digest = hook_config_digest
    stages = build_stage_entries(repo_record, ownership)
    drift_flags = build_drift_flags(repo_record, policy, stages, evaluated_at)
    arbitration_decisions = load_arbitration_decisions(repo_path)
    if not arbitration_decisions:
        drift_flags.append(
            {
                "id": "missing-arbitration-decisions",
                "severity": "low",
                "summary": "no arbitration decision records captured yet",
                "detected_at": evaluated_at,
            }
        )
    freshness_status = compute_freshness_status(
        artifact_generated_at=artifact_generated_at,
        evaluated_at=evaluated_at,
        hook_config_digest=hook_config_digest,
        evaluated_hook_config_digest=evaluated_hook_config_digest,
    )
    frameworks_active = repo_record.get("frameworks_present", [])
    if not isinstance(frameworks_active, list):
        frameworks_active = []
    profile = repo_record.get("profile_type")
    if not isinstance(profile, str) or not profile:
        profile = "unknown"
    return {
        "schema_version": "hook-conformance.v1",
        "artifact_generated_at": artifact_generated_at,
        "evaluated_at": evaluated_at,
        "repo_path": str(repo_path),
        "profile": profile,
        "frameworks_active": [
            framework for framework in frameworks_active if isinstance(framework, str)
        ],
        "hook_config_digest": hook_config_digest,
        "evaluated_hook_config_digest": evaluated_hook_config_digest,
        "stages": stages,
        "drift_flags": drift_flags,
        "arbitration_decisions": arbitration_decisions,
        "freshness_status": freshness_status,
    }


def default_governance_paths(repo_root: Path) -> tuple[Path, Path]:
    docs_root = repo_root / "docs" / "hooks-governance"
    return (
        docs_root / "gate-ownership-matrix.yaml",
        docs_root / "stage-policy-matrix.yaml",
    )


def generate_conformance_artifacts(
    manifest_path: Path,
    ownership_path: Path,
    policy_path: Path,
    out_mode: str,
    workspace_root_override: str | None = None,
    inventory_path: Path | None = None,
    artifact_generated_at: str | None = None,
    evaluated_at: str | None = None,
) -> list[dict[str, object]]:
    if out_mode not in {"repo-local", "stdout", "verify"}:
        raise ConformanceGenerationError(
            f"out_mode must be one of repo-local|stdout|verify (received '{out_mode}')"
        )
    if inventory_path is not None:
        inventory = load_structured_file(inventory_path)
    else:
        inventory = build_inventory_from_manifest(
            manifest_path=manifest_path, workspace_root_override=workspace_root_override
        )
    if not isinstance(inventory, dict):
        raise ConformanceGenerationError("inventory payload must be an object")
    repositories = inventory.get("repositories", [])
    if not isinstance(repositories, list):
        raise ConformanceGenerationError("inventory.repositories must be a list")
    ownership = load_structured_file(ownership_path)
    policy = load_structured_file(policy_path)
    if not isinstance(ownership, dict):
        raise ConformanceGenerationError("ownership payload must be an object")
    if not isinstance(policy, dict):
        raise ConformanceGenerationError("policy payload must be an object")
    evaluated_at_value = evaluated_at or utc_now_rfc3339()
    artifact_generated_at_value = artifact_generated_at or evaluated_at_value
    artifacts: list[dict[str, object]] = []
    for repo_record in repositories:
        if not isinstance(repo_record, dict):
            continue
        artifact = build_conformance_artifact(
            repo_record=repo_record,
            ownership=ownership,
            policy=policy,
            artifact_generated_at=artifact_generated_at_value,
            evaluated_at=evaluated_at_value,
        )
        artifacts.append(artifact)
        if out_mode == "repo-local":
            write_metadata(
                Path(artifact["repo_path"]),
                (".codex",),
                "hook-conformance.json",
                json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            )
    return artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--ownership", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument(
        "--out-mode", choices=("repo-local", "stdout", "verify"), default="verify"
    )
    parser.add_argument(
        "--workspace-root",
        help="optional workspace_root override for manifest resolution",
    )
    parser.add_argument("--artifact-generated-at")
    parser.add_argument("--evaluated-at")
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    script_repo_root = Path(__file__).resolve().parents[2]
    default_ownership_path, default_policy_path = default_governance_paths(
        script_repo_root
    )
    ownership_path = args.ownership or default_ownership_path
    policy_path = args.policy or default_policy_path
    try:
        artifacts = generate_conformance_artifacts(
            manifest_path=args.manifest.resolve(),
            inventory_path=args.inventory.resolve()
            if args.inventory is not None
            else None,
            ownership_path=ownership_path.resolve(),
            policy_path=policy_path.resolve(),
            out_mode=args.out_mode,
            workspace_root_override=args.workspace_root,
            artifact_generated_at=args.artifact_generated_at,
            evaluated_at=args.evaluated_at,
        )
    except ConformanceGenerationError as exc:
        print(f"[generate_conformance] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - MIG-HELPER-1: preserve final fail-closed CLI reporting; instructions/migration-scope.md#helper-boundary-decisions
        print(f"[generate_conformance] unexpected error: {exc}")
        return 1
    if args.out_mode == "stdout":
        print(json.dumps({"artifacts": artifacts}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
