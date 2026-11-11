"""Select the smallest repo-native validation command for each changed file."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


SERVICE = "validation-router"
SCHEMA_VERSION = "validation-router/v1"
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
FIXTURE_ROOT = SCRIPT_DIR / "tests" / "fixtures"


@dataclass(frozen=True)
class RouteSpec:
    kind: str
    tool: str | None
    primary: str
    fallback: str


CODEX_CONFIG = RouteSpec(
    "codex-config",
    "python3",
    "python3 codex/scripts/validate-codex-config.py",
    "taplo check codex/config.toml",
)
TOML = RouteSpec(
    "toml",
    "python3",
    'python3 -c "import pathlib, sys, tomllib; tomllib.loads(pathlib.Path(sys.argv[1]).read_text())" {path}',
    "taplo check {path}",
)
SHELL = RouteSpec("shell", "shellcheck", "shellcheck {path}", "bash -n {path}")
PYTHON = RouteSpec(
    "python", "ruff", "ruff check {path}", "python3 -m py_compile {path}"
)
MARKDOWN = RouteSpec(
    "markdown", "markdownlint-cli2", "markdownlint-cli2 {path}", "pnpm docs:lint"
)
JSON = RouteSpec("json", "jq", "jq -e . {path}", "python3 -m json.tool {path}")
YAML = RouteSpec(
    "yaml", "node", "node scripts/validate-config-repo.mjs lint", "yq eval . {path}"
)
SEMGREP_POLICY = RouteSpec(
    "semgrep-policy",
    "semgrep",
    "semgrep scan --config scripts/semgrep-pre-push.yml {path}",
    "python3 codex/scripts/validate-execpolicy-rules.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recommend the narrowest repo-native validation for changed files."
    )
    parser.add_argument("--changed-files", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return _fixture_args(parser.parse_args())


def resolve_changed_files_path(path: Path) -> Path:
    candidates = [path]
    if not path.is_absolute():
        candidates.append(REPO_ROOT / path)
        candidates.append(FIXTURE_ROOT / path)
        if path.parts and path.parts[0] == "fixtures":
            candidates.append(FIXTURE_ROOT / Path(*path.parts[1:]))
        candidates.append(FIXTURE_ROOT / path.name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(str(path))


def read_changed_files(path: Path) -> list[str]:
    resolved = resolve_changed_files_path(path)
    files: list[str] = []
    for line in _fixture_resource(resolved).read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if candidate and (not candidate.startswith("#")):
            files.append(candidate.replace(chr(92), "/"))
    return files


def tool_available(tool: str | None) -> bool:
    return tool is None or shutil.which(tool) is not None


def is_policy_path(path: str) -> bool:
    normalized = path.lower()
    name = Path(path).name.lower()
    return (
        normalized.startswith(("codex/rules/", "scripts/semgrep-"))
        or "/policy/" in normalized
        or ("policy" in name)
        or ("semgrep" in name)
        or name.endswith(".rules")
    )


def route_for_path(path: str) -> RouteSpec | None:
    normalized = path.lower()
    if normalized == "codex/config.toml":
        return CODEX_CONFIG
    if normalized.endswith(".toml"):
        return TOML
    if normalized.endswith((".sh", ".bash", ".zsh")):
        return SHELL
    if normalized.endswith(".py"):
        return PYTHON
    if normalized.endswith((".md", ".mdx", ".rst", ".adoc")):
        return MARKDOWN
    if normalized.endswith(".json"):
        return JSON
    if normalized.endswith((".yaml", ".yml")):
        return SEMGREP_POLICY if is_policy_path(path) else YAML
    if normalized.endswith(".rules"):
        return SEMGREP_POLICY
    return None


def render(template: str, path: str) -> str:
    return template.format(path=shlex.quote(path))


def classify_file(path: str) -> dict[str, Any]:
    spec = route_for_path(path)
    if spec is None:
        return {
            "path": path,
            "kind": "unknown",
            "tool": None,
            "command": None,
            "fallback": "git diff --check",
            "status": "blocked",
            "reason": "no router for file type",
        }
    available = tool_available(spec.tool)
    return {
        "path": path,
        "kind": spec.kind,
        "tool": spec.tool,
        "command": render(spec.primary, path),
        "fallback": render(spec.fallback, path),
        "status": "pass" if available else "blocked",
        "reason": None if available else f"{spec.tool} is not available on PATH",
    }


def build_result(changed_files: list[str]) -> dict[str, Any]:
    routes = [classify_file(path) for path in changed_files]
    blocked_routes = [route for route in routes if route["status"] == "blocked"]
    commands: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for route in routes:
        key = (route["status"], route["command"])
        if key in seen:
            continue
        seen.add(key)
        commands.append(
            {
                "command": route["command"],
                "fallback": route["fallback"],
                "paths": [route["path"]],
                "status": route["status"],
            }
        )
    first_action = commands[0]["command"] if commands else "No changed files supplied."
    return {
        "schema_version": SCHEMA_VERSION,
        "service": SERVICE,
        "status": "blocked" if blocked_routes else "pass",
        "changed_files": changed_files,
        "routes": routes,
        "recommended_commands": commands,
        "blocked_routes": blocked_routes,
        "first_action": first_action,
        "claims_boundary": {
            "live_checked": [
                "PATH tool availability for primary validators",
                "repo command contracts in codex/instructions/tooling.md",
            ],
            "does_not_prove": [
                "The recommended command was executed.",
                "Hosted PR, CI, review, tracker, and merge-readiness lanes remain separate.",
            ],
        },
    }


def human_summary(result: dict[str, Any]) -> str:
    if result["status"] == "pass":
        return f"service:{SERVICE} | Validation router: pass. First action: {result['first_action']}"
    lines = [
        f"service:{SERVICE} | Validation router: blocked ({len(result['blocked_routes'])} blocked route(s)).",
        f"First action: {result['first_action']}",
    ]
    for route in result["blocked_routes"]:
        lines.append(
            f"- {route['path']}: {route['reason']} | fallback: {route['fallback']}"
        )
    return chr(10).join(lines)


def self_test() -> None:
    result = build_result(
        [
            "codex/config.toml",
            "codex/scripts/validate-codex-config.py",
            "codex/agents/schemas/agent-run-manifest.schema.json",
            "codex/docs/hooks-governance/public-api-rules.yaml",
            "codex/docs/hooks-governance/gate-ownership-matrix.yaml",
            "codex/retired-agent-roles/agent-native-reviewer.toml",
            "codex/hooks/session-start.sh",
            "codex/README.md",
            "scripts/semgrep-pre-push.yml",
        ]
    )
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["service"] == SERVICE
    assert result["routes"][0]["kind"] == "codex-config"
    assert result["routes"][1]["kind"] == "python"
    assert result["routes"][2]["kind"] == "json"
    assert result["routes"][3]["kind"] == "yaml"
    assert result["routes"][4]["kind"] == "yaml"
    assert result["routes"][5]["kind"] == "toml"
    assert result["routes"][6]["kind"] == "shell"
    assert result["routes"][7]["kind"] == "markdown"
    assert result["routes"][8]["kind"] == "semgrep-policy"


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        payload = build_result(
            ["codex/config.toml", "codex/scripts/validate-codex-config.py"]
        )
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(human_summary(payload))
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.changed_files is None:
        raise SystemExit("--changed-files is required unless --self-test is set")
    result = build_result(read_changed_files(args.changed_files))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(human_summary(result))
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
