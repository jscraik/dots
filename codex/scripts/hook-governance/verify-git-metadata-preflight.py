"""Verify the cross-repository git-metadata-preflight/v1 adoption contract."""

from __future__ import annotations

import argparse
import json
import re
import shlex
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


CONTRACT = "git-metadata-preflight/v1"
SERVICE = "git-metadata-preflight-adoption"
PREFLIGHT_INVOCATION = re.compile(
    "(?m)^\\s*(?:python(?:3)?|bash)\\s+[^#\\n]*git[-_]metadata[-_]preflight\\.py\\b[^#\\n]*--repo-root\\b"
)
EXPENSIVE_GATE_INVOCATION = re.compile(
    "(?m)^\\s*(?:pnpm|npm|yarn|bun|cargo|pytest|ruff|mypy|make|semgrep)\\b"
)
CACHE_ROOT_ASSIGNMENT = re.compile(
    "(?m)^\\s*(?:export\\s+)?(?:CODEX_HOOK_CACHE_ROOT|XDG_CACHE_HOME|UV_CACHE_DIR)\\s*="
)
CACHE_ROOT_HELPER = re.compile(
    "(?m)^\\s*(?:source|\\.)\\s+[^#\\n]*(?:hook-runtime-env|_sandbox_env)\\.sh(?:\\s|[\\\"']|$)"
)
DESTRUCTIVE_GIT_COMMANDS = {
    ("git", "worktree", "prune"),
    ("git", "worktree", "unlock"),
    ("git", "worktree", "remove"),
}
EXPECTED_HISTORICAL_FINDING_IDS = {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}


class ContractError(ValueError):
    """Raised when the adoption contract is malformed or incomplete."""


def _relative_path(
    value: str, base: Path, label: str
) -> tuple[Path | None, str | None]:
    candidate = Path(value)
    if candidate.is_absolute():
        return (None, f"{label} must be relative: {value}")
    resolved_base = base.resolve()
    resolved = (resolved_base / candidate).resolve()
    try:
        resolved.relative_to(resolved_base)
    except ValueError:
        return (None, f"{label} escapes its allowed root: {value}")
    return (resolved, None)


def _report(status: str, errors: list[str] | None = None) -> None:
    print(
        json.dumps(
            {
                "schema_version": 1,
                "service": SERVICE,
                "contract": CONTRACT,
                "status": status,
                "errors": errors or [],
            },
            indent=2,
            sort_keys=True,
        )
    )


def _preflight_precedes_expensive_gate(text: str) -> bool:
    """Return whether the first adapter call precedes the first expensive gate."""
    preflight = PREFLIGHT_INVOCATION.search(text)
    if preflight is None:
        return False
    gate = EXPENSIVE_GATE_INVOCATION.search(text)
    return gate is None or preflight.start() < gate.start()


def _has_executable_cache_root_config(text: str) -> bool:
    """Require an executable assignment or guarded runtime helper invocation."""
    return bool(CACHE_ROOT_ASSIGNMENT.search(text) or CACHE_ROOT_HELPER.search(text))


def _executable_lines(text: str) -> list[tuple[int, str]]:
    """Return non-empty, non-comment shell lines with their source line numbers."""
    return [
        (line_number, line.strip())
        for line_number, raw_line in enumerate(text.splitlines(), start=1)
        if (line := raw_line.strip()) and (not line.startswith("#"))
    ]


def _shell_tokens(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=True, posix=True)
    except ValueError:
        return []


def _is_adapter_invocation_at(
    tokens: list[str], index: int, expected_adapter: str
) -> bool:
    """Recognize an interpreter followed by the exact manifest adapter path."""
    if index <= 0 or Path(tokens[index - 1]).name not in {"python", "python3", "bash"}:
        return False
    candidate = Path(tokens[index]).as_posix().lstrip("./")
    expected = Path(expected_adapter).as_posix().lstrip("./")
    return candidate == expected


def _adapter_invocations(text: str, expected_adapter: str) -> list[tuple[int, str]]:
    """Find executable calls to the manifest's Git metadata adapter."""
    invocations: list[tuple[int, str]] = []
    for line_number, line in _executable_lines(text):
        tokens = _shell_tokens(line)
        invocations.extend(
            (line_number, line)
            for index in range(len(tokens))
            if _is_adapter_invocation_at(tokens, index, expected_adapter)
        )
    return invocations


def _variable_names(token: str) -> set[str]:
    """Extract simple shell variable references without regex parsing."""
    names: set[str] = set()
    index = 0
    while index < len(token):
        if token[index] != "$":
            index += 1
            continue
        index += 1
        if index < len(token) and token[index] == "{":
            end = token.find("}", index + 1)
            if end == -1:
                break
            candidate = token[index + 1 : end]
            index = end + 1
        else:
            start = index
            while index < len(token) and (
                token[index].isalnum() or token[index] == "_"
            ):
                index += 1
            candidate = token[start:index]
        if candidate.isidentifier():
            names.add(candidate)
    return names


def _mentions_git_metadata(token: str) -> bool:
    lowered = token.lower()
    return (
        "index.lock" in lowered
        or "/worktrees/" in lowered
        or "git_dir" in lowered
        or ("git_common_dir" in lowered)
    )


def _simple_assignments(text: str) -> dict[str, str]:
    """Collect simple shell assignments for bounded variable-flow checks."""
    assignments: dict[str, str] = {}
    for _, line in _executable_lines(text):
        for token in _shell_tokens(line):
            name, separator, value = token.partition("=")
            if separator and name.isidentifier():
                assignments[name] = value
    return assignments


def _disables_write_probe(tokens: list[str], assignments: dict[str, str]) -> bool:
    """Reject a direct or simple variable-mediated write-probe bypass."""
    if any("--no-write-probe" in token for token in tokens):
        return True
    disabled_variables = {
        name for name, value in assignments.items() if "--no-write-probe" in value
    }
    if any(_variable_names(token) & disabled_variables for token in tokens):
        return True
    return bool(disabled_variables) and any(token in {"$@", "${@}"} for token in tokens)


def _has_destructive_git_cleanup(text: str) -> bool:
    """Reject hook-side cleanup that can delete or unlock shared Git metadata."""
    assignments = _simple_assignments(text)
    metadata_variables = {
        name for name, value in assignments.items() if _mentions_git_metadata(value)
    }
    executable_lines = _executable_lines(text)
    for _, line in executable_lines:
        tokens = _shell_tokens(line)
        if any(
            tuple(tokens[index : index + len(command)]) == command
            for command in DESTRUCTIVE_GIT_COMMANDS
            for index in range(len(tokens) - len(command) + 1)
        ):
            return True
        command_index = 1 if tokens and tokens[0] == "command" else 0
        if len(tokens) > command_index and Path(tokens[command_index]).name == "rm":
            targets = tokens[command_index + 1 :]
            if any(
                _mentions_git_metadata(token)
                or _variable_names(token) & metadata_variables
                for token in targets
            ):
                return True
    return False


def load_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(_fixture_resource(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("manifest must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ContractError("manifest schema_version must be 1")
    if payload.get("contract") != CONTRACT:
        raise ContractError(f"manifest contract must be {CONTRACT}")
    return payload


def _validate_historical_findings(manifest: dict[str, object]) -> list[str]:
    findings = manifest.get("historical_findings")
    if not isinstance(findings, list) or not findings:
        return ["manifest.historical_findings must be a non-empty list"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"historical_findings[{index}] must be an object")
            continue
        finding_id = finding.get("id")
        if not isinstance(finding_id, str) or not finding_id.strip():
            errors.append(f"historical_findings[{index}].id must be a non-empty string")
        elif finding_id in seen:
            errors.append(f"historical_findings contains duplicate id {finding_id!r}")
        else:
            seen.add(finding_id)
        for key in ("historical_failure", "current_control", "enforcement"):
            value = finding.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"historical_findings[{index}].{key} must be a non-empty string"
                )
    missing = sorted(EXPECTED_HISTORICAL_FINDING_IDS - seen)
    unexpected = sorted(seen - EXPECTED_HISTORICAL_FINDING_IDS)
    if missing:
        errors.append(f"historical_findings missing ids: {missing}")
    if unexpected:
        errors.append(f"historical_findings has unexpected ids: {unexpected}")
    return errors


def validate_manifest(
    manifest_path: Path, workspace_root: Path, strict: bool = False
) -> list[str]:
    manifest = load_manifest(manifest_path)
    workspace_root = workspace_root.resolve()
    policy = manifest.get("policy")
    if not isinstance(policy, dict):
        return ["manifest.policy must be an object"]
    expected_policy = {
        "preflight_before_expensive_gates": True,
        "write_probe": "required",
        "cache_location": "outside_git_metadata",
        "lock_cleanup": "manual_only",
        "stale_lock_classification": "candidate_not_proof",
    }
    errors = [
        f"policy.{key} must be {value!r}"
        for key, value in expected_policy.items()
        if policy.get(key) != value
    ]
    errors.extend(_validate_historical_findings(manifest))
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        return errors + ["manifest.repositories must be a non-empty list"]
    for record in repositories:
        if not isinstance(record, dict):
            errors.append("repository records must be objects")
            continue
        name = record.get("repo_name")
        repo_path = record.get("repo_path")
        adapter = record.get("adapter")
        hooks = record.get("hook_entrypoints")
        if not all(
            isinstance(value, str) and value for value in (name, repo_path, adapter)
        ):
            errors.append(
                "repository records require repo_name, repo_path, and adapter"
            )
            continue
        if (
            not isinstance(hooks, list)
            or not hooks
            or (not all(isinstance(value, str) and value for value in hooks))
        ):
            errors.append(f"repository {name!r} must declare hook_entrypoints")
            continue
        repo_root, path_error = _relative_path(
            repo_path, workspace_root, f"repository {name!r} repo_path"
        )
        if path_error:
            errors.append(path_error)
            continue
        adapter_path, path_error = _relative_path(
            adapter, repo_root, f"repository {name!r} adapter"
        )
        if path_error:
            errors.append(path_error)
            continue
        assert repo_root is not None
        assert adapter_path is not None
        if not repo_root.is_dir():
            message = f"repository {name!r} is absent at {repo_root}"
            if strict:
                errors.append(message)
            continue
        if not adapter_path.is_file():
            errors.append(f"repository {name!r} adapter is missing: {adapter_path}")
        for hook in hooks:
            hook_path, path_error = _relative_path(
                hook, repo_root, f"repository {name!r} hook_entrypoint"
            )
            if path_error:
                errors.append(path_error)
                continue
            assert hook_path is not None
            if not hook_path.is_file():
                errors.append(
                    f"repository {name!r} hook entrypoint is missing: {hook_path}"
                )
                continue
            text = _fixture_resource(hook_path).read_text(encoding="utf-8")
            adapter_invocations = _adapter_invocations(text, adapter)
            if not PREFLIGHT_INVOCATION.search(text):
                errors.append(
                    f"repository {name!r} hook does not call the adapter: {hook_path}"
                )
            elif len(adapter_invocations) != 1:
                errors.append(
                    f"repository {name!r} hook must contain exactly one adapter invocation: {hook_path}"
                )
            elif _disables_write_probe(
                _shell_tokens(adapter_invocations[0][1]), _simple_assignments(text)
            ):
                errors.append(
                    f"repository {name!r} hook disables the required write probe: {hook_path}"
                )
            elif _has_destructive_git_cleanup(text):
                errors.append(
                    f"repository {name!r} hook must not clean Git metadata: {hook_path}"
                )
            elif not _preflight_precedes_expensive_gate(text):
                errors.append(
                    f"repository {name!r} hook calls the adapter after an expensive gate: {hook_path}"
                )
            if not _has_executable_cache_root_config(text):
                errors.append(
                    f"repository {name!r} hook does not configure a guarded cache root: {hook_path}"
                )
            if re.search(
                "(?i)(?:\\.git|git_common_dir)[^\\n]*cache|cache[^\\n]*(?:\\.git|git_common_dir)",
                text,
            ):
                errors.append(
                    f"repository {name!r} hook keeps caches under Git metadata: {hook_path}"
                )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    try:
        errors = validate_manifest(
            args.manifest.resolve(), args.workspace_root.resolve(), args.strict
        )
    except ContractError as exc:
        _report("blocked", [str(exc)])
        return 1
    if errors:
        _report("blocked", errors)
        return 1
    _report("pass")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
