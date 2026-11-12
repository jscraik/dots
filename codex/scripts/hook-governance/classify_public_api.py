"""Classify repository files into public/internal/unknown API surface."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from datetime import UTC, datetime
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


DEFAULT_CLASSIFIABLE_EXTENSIONS = (".cjs", ".js", ".jsx", ".mjs", ".py", ".ts", ".tsx")


class PublicApiClassificationError(ValueError):
    """Raised when public API classification inputs are invalid."""


def load_structured_file(path: Path) -> object:
    raw_text = _fixture_resource(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        if yaml is not None:
            return yaml.safe_load(raw_text)
    raise PublicApiClassificationError(
        f"unable to parse structured file '{path}' as JSON or YAML"
    )


def utc_now_rfc3339() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def portable_path(path: Path, *, anchor: Path | None = None) -> str:
    """Render canonical paths relative to `anchor` when possible."""
    resolved_path = path.expanduser().resolve(strict=False)
    if anchor is not None:
        resolved_anchor = anchor.expanduser().resolve(strict=False)
        try:
            return resolved_path.relative_to(resolved_anchor).as_posix()
        except ValueError:
            pass
    return resolved_path.as_posix()


def _normalize_extensions(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PublicApiClassificationError(
            "classifiable_extensions must be a list of file extensions"
        )
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise PublicApiClassificationError(
                "classifiable_extensions entries must be strings"
            )
        extension = item.strip()
        if not extension:
            raise PublicApiClassificationError(
                "classifiable_extensions entries must be non-empty"
            )
        normalized.append(extension)
    return tuple(sorted(set(normalized)))


def _normalize_rules(value: object, context: str) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PublicApiClassificationError(f"{context} must be a list")
    normalized: list[dict[str, object]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise PublicApiClassificationError(f"{context}[{index}] must be an object")
        rule_id = entry.get("rule_id")
        kind = entry.get("kind")
        priority = entry.get("priority")
        patterns = entry.get("patterns")
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise PublicApiClassificationError(
                f"{context}[{index}] must include a non-empty rule_id"
            )
        if kind not in ("public", "internal"):
            raise PublicApiClassificationError(
                f"{context}[{index}] kind must be 'public' or 'internal'"
            )
        if not isinstance(priority, int):
            raise PublicApiClassificationError(
                f"{context}[{index}] priority must be an integer"
            )
        if not isinstance(patterns, list) or not patterns:
            raise PublicApiClassificationError(
                f"{context}[{index}] patterns must be a non-empty list"
            )
        cleaned_patterns: list[str] = []
        for pattern in patterns:
            if not isinstance(pattern, str) or not pattern.strip():
                raise PublicApiClassificationError(
                    f"{context}[{index}] patterns must contain non-empty strings"
                )
            cleaned_patterns.append(pattern.strip())
        normalized.append(
            {
                "rule_id": rule_id.strip(),
                "kind": kind,
                "priority": priority,
                "patterns": cleaned_patterns,
            }
        )
    return normalized


def normalize_rule_config(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise PublicApiClassificationError("public-api rule source must be an object")
    default_extensions = payload.get("default_classifiable_extensions")
    if default_extensions is None:
        normalized_default_extensions = DEFAULT_CLASSIFIABLE_EXTENSIONS
    else:
        normalized_default_extensions = _normalize_extensions(default_extensions)
    default_rules = _normalize_rules(payload.get("default_rules"), "default_rules")
    repositories = payload.get("repositories", {})
    if repositories is None:
        repositories = {}
    if not isinstance(repositories, dict):
        raise PublicApiClassificationError("repositories must be an object")
    normalized_repositories: dict[str, dict[str, object]] = {}
    for repo_name, repo_entry in repositories.items():
        if not isinstance(repo_name, str) or not repo_name:
            raise PublicApiClassificationError(
                "repositories keys must be non-empty strings"
            )
        if not isinstance(repo_entry, dict):
            raise PublicApiClassificationError(
                f"repositories.{repo_name} must be an object"
            )
        repo_rules = _normalize_rules(
            repo_entry.get("rules"), f"repositories.{repo_name}.rules"
        )
        repo_extensions = repo_entry.get("classifiable_extensions")
        normalized_repo_extensions: tuple[str, ...] | None = None
        if repo_extensions is not None:
            normalized_repo_extensions = _normalize_extensions(repo_extensions)
        public_api_rule_id = repo_entry.get("public_api_rule_id")
        if not isinstance(public_api_rule_id, str) or not public_api_rule_id.strip():
            public_api_rule_id = f"{repo_name}-default"
        public_api_rule_version = repo_entry.get("public_api_rule_version")
        if (
            not isinstance(public_api_rule_version, str)
            or not public_api_rule_version.strip()
        ):
            public_api_rule_version = "unspecified"
        framework_mapping_source = repo_entry.get("framework_mapping_source")
        if (
            not isinstance(framework_mapping_source, str)
            or not framework_mapping_source.strip()
        ):
            framework_mapping_source = "default"
        normalized_repositories[repo_name] = {
            "rules": repo_rules,
            "classifiable_extensions": normalized_repo_extensions,
            "public_api_rule_id": public_api_rule_id,
            "public_api_rule_version": public_api_rule_version,
            "framework_mapping_source": framework_mapping_source,
        }
    return {
        "default_classifiable_extensions": normalized_default_extensions,
        "default_rules": default_rules,
        "repositories": normalized_repositories,
    }


def list_repo_files(repo_path: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise PublicApiClassificationError(
            f"unable to list files for repo '{repo_path}': {exc.stderr.strip() or exc}"
        ) from exc
    files = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    files.sort()
    return files


def rule_matches(path: str, rule: dict[str, object]) -> bool:
    patterns = rule.get("patterns", [])
    if not isinstance(patterns, list):
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def choose_rule(path: str, rules: list[dict[str, object]]) -> dict[str, object] | None:
    matches = [rule for rule in rules if rule_matches(path, rule)]
    if not matches:
        return None
    matches.sort(key=lambda item: (-int(item["priority"]), str(item["rule_id"])))
    return matches[0]


def is_classifiable(path: str, extensions: tuple[str, ...]) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(extension) for extension in extensions)


def classify_repository(
    repo_record: dict[str, object],
    rule_config: dict[str, object],
    *,
    path_anchor: Path | None,
) -> dict[str, object]:
    repo_name = repo_record.get("repo_name")
    repo_path_value = repo_record.get("repo_path")
    if not isinstance(repo_name, str) or not repo_name:
        raise PublicApiClassificationError("inventory repository is missing repo_name")
    if not isinstance(repo_path_value, str) or not repo_path_value:
        raise PublicApiClassificationError(
            f"inventory repo '{repo_name}' is missing repo_path"
        )
    repo_path = Path(repo_path_value)
    if not repo_path.is_dir():
        raise PublicApiClassificationError(
            f"inventory repo '{repo_name}' path does not exist: {repo_path}"
        )
    repository_rules = rule_config["repositories"].get(repo_name, {})
    repo_specific_rules = repository_rules.get("rules", [])
    if not isinstance(repo_specific_rules, list):
        repo_specific_rules = []
    default_rules = rule_config["default_rules"]
    if not isinstance(default_rules, list):
        default_rules = []
    effective_rules = [*default_rules, *repo_specific_rules]
    classifiable_extensions = repository_rules.get("classifiable_extensions")
    if isinstance(classifiable_extensions, tuple):
        extensions = classifiable_extensions
    else:
        extensions = rule_config["default_classifiable_extensions"]
    base_payload: dict[str, object] = {
        "repo_name": repo_name,
        "repo_path": portable_path(repo_path, anchor=path_anchor),
        "public_api_rule_id": repository_rules.get(
            "public_api_rule_id", f"{repo_name}-default"
        ),
        "public_api_rule_version": repository_rules.get(
            "public_api_rule_version", "unspecified"
        ),
        "framework_mapping_source": repository_rules.get(
            "framework_mapping_source", "default"
        ),
        "classification_updated_at": utc_now_rfc3339(),
    }
    try:
        repo_files = list_repo_files(repo_path)
    except PublicApiClassificationError as exc:
        return {
            **base_payload,
            "classification_status": "error",
            "classification_error": str(exc),
            "classified_file_count": 0,
            "unknown_surface_file_count": 0,
            "files": [],
        }
    file_rows: list[dict[str, str]] = []
    unknown_surface_file_count = 0
    for relative_path in repo_files:
        if not is_classifiable(relative_path, extensions):
            continue
        winner = choose_rule(relative_path, effective_rules)
        if winner is None:
            label = "unknown-surface"
            matched_rule_id = ""
            unknown_surface_file_count += 1
        else:
            label = str(winner["kind"])
            matched_rule_id = str(winner["rule_id"])
        file_rows.append(
            {"path": relative_path, "label": label, "matched_rule_id": matched_rule_id}
        )
    file_rows.sort(key=lambda item: item["path"])
    return {
        **base_payload,
        "classification_status": "ok",
        "classification_error": "",
        "classified_file_count": len(file_rows),
        "unknown_surface_file_count": unknown_surface_file_count,
        "files": file_rows,
    }


def classify_public_api(inventory_path: Path, rules_path: Path) -> dict[str, object]:
    working_dir = Path.home()
    inventory_payload = load_structured_file(inventory_path)
    if not isinstance(inventory_payload, dict):
        raise PublicApiClassificationError("inventory must be a JSON object")
    if inventory_payload.get("schema_version") != 1:
        raise PublicApiClassificationError("inventory schema_version must be 1")
    repositories = inventory_payload.get("repositories", [])
    if not isinstance(repositories, list):
        raise PublicApiClassificationError("inventory.repositories must be a list")
    rules_payload = load_structured_file(rules_path)
    rule_config = normalize_rule_config(rules_payload)
    classified_repos = [
        classify_repository(
            repo_record=repo_record, rule_config=rule_config, path_anchor=working_dir
        )
        for repo_record in repositories
        if isinstance(repo_record, dict)
    ]
    classified_repos.sort(key=lambda item: item["repo_name"])
    return {
        "schema_version": "public-api-classification.v1",
        "inventory_path": portable_path(inventory_path, anchor=working_dir),
        "rules_path": portable_path(rules_path, anchor=working_dir),
        "repositories": classified_repos,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    try:
        result = classify_public_api(
            inventory_path=args.inventory, rules_path=args.rules
        )
    except (PublicApiClassificationError, FileNotFoundError) as exc:
        print(f"[classify_public_api] {exc}")
        return 1
    output = json.dumps(result, indent=2, sort_keys=True)
    if args.out is None:
        print(output)
    else:
        _fixture_scope().output(args.out.parent).mkdir(parents=True, exist_ok=True)
        _fixture_scope().output(args.out).write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
