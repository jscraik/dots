"""Validate Codex subagent artifact contracts and optional produced artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
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


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = SCRIPT_DIR.parent
REQUIRED_TEMPLATES = {
    "review_artifact": ("WROTE: <artifact_path>", "Accountability Receipt"),
    "blocker_artifact": ("STATUS: blocked_runtime", "coordinator_next_step"),
    "coordinator_ledger": ("Agent Accounting", "Positive Performance"),
}
REQUIRED_FIXTURES = {
    "agent-native-gap",
    "dirty-worktree-validation",
    "good-reviewer",
    "introduced-regression",
    "local-memory-cli-unavailable",
    "missing-artifact-path",
    "overconfident-reviewer",
}
REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "run_id",
    "agent_role",
    "status",
    "repo",
    "task",
    "inputs",
    "outputs",
    "provenance",
    "accountability",
}
REQUIRED_ARTIFACT_PHRASES = (
    "Accountability Receipt",
    "blocked_reason",
    "coverage_gaps",
    "manifest_path",
    "validation_evidence",
)
REQUIRED_RECEIPT_FIELDS = {
    "artifact_paths",
    "blocked_reason",
    "coverage_gaps",
    "failures_or_blockers",
    "findings",
    "improvement_opportunities",
    "manifest_path",
    "next_action",
    "status",
    "strengths",
    "validation_evidence",
}
PLACEHOLDER_VALUES = {
    "",
    "<artifact_path>",
    "<manifest_path>",
    "<status>",
    "n/a",
    "tbd",
    "todo",
    "unknown",
}
BLOCKER_STATUSES = {
    "STATUS: blocked_runtime",
    "STATUS: blocked_missing_artifact",
    "STATUS: blocked_validation",
    "STATUS: blocked_local_memory_cli",
}
BLOCKER_STATUS_PATTERN = re.compile(
    "^STATUS:\\s+(?:complete|blocked_(?:runtime|missing_artifact|validation|local_memory_cli))\\s*$",
    re.MULTILINE,
)


def load_json(path: Path) -> tuple[object | None, list[str]]:
    """Load JSON and return validation errors instead of raising."""
    try:
        return (json.loads(_fixture_resource(path).read_text(encoding="utf-8")), [])
    except (OSError, json.JSONDecodeError) as exc:
        return (None, [f"{path}: unreadable JSON ({exc})"])


def validate_contract(root: Path) -> list[str]:
    """Validate retained coordinator templates, historical schema and fixtures."""
    errors: list[str] = []
    for name, phrases in REQUIRED_TEMPLATES.items():
        template_path = Path("agents/templates") / (name.replace("_", "-") + ".md")
        path = root / template_path
        if not path.is_file():
            errors.append(f"{template_path}: template does not exist")
            continue
        text = _fixture_resource(path).read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{template_path}: missing required phrase {phrase!r}")
    schema_path = root / "agents" / "schemas" / "agent-run-manifest.schema.json"
    schema, schema_errors = load_json(schema_path)
    errors.extend(schema_errors)
    if isinstance(schema, dict):
        required = set(schema.get("required", []))
        missing_manifest_fields = sorted(REQUIRED_MANIFEST_FIELDS - required)
        if missing_manifest_fields:
            errors.append(
                f"{schema_path}: manifest schema missing required fields {missing_manifest_fields}"
            )
        status_values = set(
            schema.get("properties", {}).get("status", {}).get("enum", [])
        )
        policy_path = root / "instructions" / "agents" / "09-audit-trail-policy.md"
        if policy_path.is_file():
            policy_text = _fixture_resource(policy_path).read_text(encoding="utf-8")
            missing_status_docs = sorted(
                status for status in status_values if status not in policy_text
            )
            if missing_status_docs:
                errors.append(
                    f"{policy_path}: missing manifest status values {missing_status_docs}"
                )
            if "failed_artifact_verification" in policy_text:
                errors.append(
                    f"{policy_path}: uses deprecated failed_artifact_verification; use failed_artifact_validation"
                )
        else:
            errors.append(f"{policy_path}: missing audit trail policy")
    elif not schema_errors:
        errors.append(f"{schema_path}: must be a JSON object")
    evals_path = root / "agents" / "evals" / "subagent-artifact-quality.json"
    evals, eval_errors = load_json(evals_path)
    errors.extend(eval_errors)
    if isinstance(evals, dict):
        fixtures = evals.get("fixtures")
        if not isinstance(fixtures, list):
            errors.append(f"{evals_path}: fixtures must be a list")
        else:
            fixture_ids = {
                fixture.get("id") for fixture in fixtures if isinstance(fixture, dict)
            }
            missing_fixtures = sorted(REQUIRED_FIXTURES - fixture_ids)
            if missing_fixtures:
                errors.append(f"{evals_path}: missing fixtures {missing_fixtures}")
            for index, fixture in enumerate(fixtures):
                if not isinstance(fixture, dict):
                    errors.append(f"{evals_path}: fixture {index} must be an object")
                    continue
                for key in (
                    "id",
                    "purpose",
                    "expected_agent_behavior",
                    "grader_signal",
                ):
                    if (
                        not isinstance(fixture.get(key), str)
                        or not fixture[key].strip()
                    ):
                        errors.append(
                            f"{evals_path}: fixture {index}.{key} must be non-empty"
                        )
    elif not eval_errors:
        errors.append(f"{evals_path}: must be a JSON object")
    return errors


def extract_accountability_receipt(text: str) -> dict[str, str]:
    """Extract simple key/value fields from the Accountability Receipt section."""
    match = re.search(
        "^## Accountability Receipt\\s*$([\\s\\S]*?)(?=^##\\s|^WROTE:|\\Z)",
        text,
        re.MULTILINE,
    )
    if not match:
        return {}
    fields: dict[str, str] = {}
    current_key: str | None = None
    current_parts: list[str] = []
    key_pattern = re.compile("^\\s*(?:-\\s*)?([A-Za-z_][A-Za-z0-9_]*):\\s*(.*)$")

    def flush() -> None:
        nonlocal current_key, current_parts
        if current_key is not None:
            fields[current_key] = "\n".join(
                part for part in current_parts if part
            ).strip()
        current_key = None
        current_parts = []

    for line in match.group(1).splitlines():
        key_match = key_pattern.match(line)
        if key_match:
            candidate_key = key_match.group(1)
            if candidate_key not in REQUIRED_RECEIPT_FIELDS:
                if current_key is not None:
                    current_parts.append(line.strip())
                    continue
                continue
            flush()
            current_key = candidate_key
            value = key_match.group(2).strip()
            current_parts = [value] if value else []
            continue
        if current_key is not None:
            stripped = line.strip()
            if stripped:
                current_parts.append(stripped)
    flush()
    return fields


def validate_accountability_receipt(path: Path, text: str) -> list[str]:
    """Validate produced artifacts include usable accountability receipt fields."""
    fields = extract_accountability_receipt(text)
    if not fields:
        return [f"{path}: missing Accountability Receipt section"]
    errors: list[str] = []
    missing_fields = sorted(REQUIRED_RECEIPT_FIELDS - set(fields))
    if missing_fields:
        errors.append(f"{path}: Accountability Receipt missing fields {missing_fields}")
    for field in sorted(REQUIRED_RECEIPT_FIELDS & set(fields)):
        normalized = fields[field].strip().lower()
        if normalized in PLACEHOLDER_VALUES:
            errors.append(
                f"{path}: Accountability Receipt field {field} is empty or placeholder"
            )
    return errors


def validate_manifest_path(manifest: str, root: Path) -> bool:
    """Inspect a nonempty regular manifest without following child symlinks."""
    relative = Path(manifest)
    if relative.is_absolute() or ".." in relative.parts or (not relative.parts):
        return False
    descriptors: list[int] = []
    try:
        directory = _fixture_resource(os).open(
            root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        descriptors.append(directory)
        for component in relative.parts[:-1]:
            directory = _fixture_resource(os).open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            descriptors.append(directory)
        descriptor = _fixture_resource(os).open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        descriptors.append(descriptor)
        metadata = os.fstat(descriptor)
        return stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0
    except (OSError, ValueError):
        return False
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def validate_artifact(path: Path, root: Path = DEFAULT_ROOT) -> list[str]:
    """Validate a produced Markdown artifact against the accountability contract."""
    if not path.is_file():
        return [f"{path}: artifact does not exist"]
    text = _fixture_resource(path).read_text(encoding="utf-8")
    if not text.strip():
        return [f"{path}: artifact is empty"]
    errors: list[str] = []
    has_blocker_status = bool(BLOCKER_STATUS_PATTERN.search(text))
    if "WROTE:" not in text:
        errors.append(f"{path}: missing WROTE status line")
    if re.search("^STATUS:", text, re.MULTILINE) and (not has_blocker_status):
        errors.append(f"{path}: blocker status must be an exact STATUS line")
    for phrase in REQUIRED_ARTIFACT_PHRASES:
        if phrase not in text:
            errors.append(f"{path}: missing required phrase {phrase!r}")
    errors.extend(validate_accountability_receipt(path, text))
    fields = extract_accountability_receipt(text)
    manifest = fields.get("manifest_path", "")
    if (
        manifest
        and manifest.lower() not in PLACEHOLDER_VALUES
        and not validate_manifest_path(manifest, root)
    ):
        errors.append(
            f"{path}: manifest_path must name a non-empty file of regular type relative to the validation root, without traversal or symlinks"
        )
    if "file:line" in text and "Evidence" not in text:
        errors.append(f"{path}: placeholder file:line appears without evidence section")
    return errors


def main() -> int:
    """Run artifact contract validation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=str(DEFAULT_ROOT), help="Codex subtree root path"
    )
    parser.add_argument(
        "artifacts", nargs="*", help="Optional produced artifact paths to validate"
    )
    args = _fixture_args(parser.parse_args())
    root = Path(args.root).expanduser().resolve()
    errors = validate_contract(root)
    for artifact in args.artifacts:
        artifact_path = Path(artifact)
        if not artifact_path.is_absolute():
            artifact_path = root / artifact_path
        errors.extend(validate_artifact(artifact_path, root))
    if errors:
        print("[validate-agent-artifacts] validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("[validate-agent-artifacts] OK: subagent artifact contract is explicit")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
