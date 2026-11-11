"""Unit tests for classify_public_api.py."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _fixture_scope():
    import importlib.util
    from pathlib import Path

    directory = Path(__file__).resolve().parent
    if directory.name in ("hook-governance", "tests"):
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
    if directory.name in ("hook-governance", "tests"):
        directory = directory.parent
    policy = directory.parent
    return (
        text.replace("@POLICY_SOURCE@", str(policy))
        .replace("@REPO@", str(policy.parent))
        .replace("@HOME@", str(Path.home()))
    )


def _fixture_open(*args, **kwargs):
    return _fixture_scope().fixture_open(*args, **kwargs)


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "hook-governance" / "classify_public_api.py"
)
SPEC = importlib.util.spec_from_file_location("classify_public_api", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load classifier module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_rules(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "default_classifiable_extensions": [".ts", ".py"],
        "default_rules": [
            {
                "rule_id": "100-framework-index",
                "kind": "public",
                "priority": 100,
                "patterns": ["src/index.ts"],
            },
            {
                "rule_id": "200-internal",
                "kind": "internal",
                "priority": 200,
                "patterns": ["src/internal/**"],
            },
        ],
        "repositories": {
            "demo": {
                "public_api_rule_id": "demo-default",
                "public_api_rule_version": "2026-04-10",
                "framework_mapping_source": "unit-test-v1",
                "rules": [
                    {
                        "rule_id": "050-explicit-public",
                        "kind": "public",
                        "priority": 300,
                        "patterns": ["src/lib/public_api.ts"],
                    },
                    {
                        "rule_id": "100-tie-b",
                        "kind": "public",
                        "priority": 250,
                        "patterns": ["src/lib/tie.ts"],
                    },
                    {
                        "rule_id": "100-tie-a",
                        "kind": "public",
                        "priority": 250,
                        "patterns": ["src/lib/tie.ts"],
                    },
                ],
            }
        },
    }
    _fixture_resource(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_inventory(path: Path, repo_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "workspace_root": str(repo_path.parent),
        "excluded_repositories": [],
        "repositories": [
            {
                "repo_name": "demo",
                "repo_path": str(repo_path),
                "frameworks_present": ["prek"],
                "gate_entrypoints": {
                    "hooks-pre-commit": "make hooks-pre-commit",
                    "hooks-pre-push": "make hooks-pre-push",
                    "hooks-commit-msg": "make hooks-commit-msg",
                },
                "profile_type": "standard-prek-wrapper",
                "commit_msg_policy": {
                    "command": "node scripts/validate-commit-msg.js $1",
                    "source": "validate-commit-msg.js",
                },
            }
        ],
    }
    _fixture_resource(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _git_init(repo_path: Path) -> None:
    import subprocess

    subprocess.run(
        ["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "add", "."], cwd=repo_path, check=True, capture_output=True, text=True
    )


class PublicApiClassificationTests(unittest.TestCase):
    def test_classification_is_deterministic_and_unknown_surface_is_emitted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "demo"
            _fixture_resource(repo_path / "src" / "internal").mkdir(parents=True)
            _fixture_resource(repo_path / "src" / "lib").mkdir(parents=True)
            _fixture_resource(repo_path / "scripts").mkdir(parents=True)
            _fixture_resource(repo_path / "src" / "index.ts").write_text(
                'export * from "./lib/public_api"\n', encoding="utf-8"
            )
            _fixture_resource(repo_path / "src" / "internal" / "util.ts").write_text(
                "export const i = 1\n", encoding="utf-8"
            )
            _fixture_resource(repo_path / "src" / "lib" / "public_api.ts").write_text(
                "export const p = 1\n", encoding="utf-8"
            )
            _fixture_resource(repo_path / "src" / "lib" / "tie.ts").write_text(
                "export const t = 1\n", encoding="utf-8"
            )
            _fixture_resource(repo_path / "scripts" / "helper.ts").write_text(
                "export const h = 1\n", encoding="utf-8"
            )
            _git_init(repo_path)
            inventory_path = root / "repo-profile-matrix.json"
            rules_path = root / "public-api-rules.yaml"
            _write_inventory(inventory_path, repo_path)
            _write_rules(rules_path)
            first = MODULE.classify_public_api(
                inventory_path=inventory_path, rules_path=rules_path
            )
            second = MODULE.classify_public_api(
                inventory_path=inventory_path, rules_path=rules_path
            )
            self.assertEqual(
                first["repositories"][0]["files"], second["repositories"][0]["files"]
            )
            files = {
                entry["path"]: entry for entry in first["repositories"][0]["files"]
            }
            self.assertEqual(files["src/index.ts"]["label"], "public")
            self.assertEqual(files["src/lib/public_api.ts"]["label"], "public")
            self.assertEqual(files["src/internal/util.ts"]["label"], "internal")
            self.assertEqual(files["scripts/helper.ts"]["label"], "unknown-surface")
            self.assertEqual(files["src/lib/tie.ts"]["matched_rule_id"], "100-tie-a")

    def test_classification_degrades_when_repo_file_listing_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "demo"
            _fixture_resource(repo_path).mkdir(parents=True)
            _fixture_resource(repo_path / "src").mkdir(parents=True)
            _fixture_resource(repo_path / "src" / "index.ts").write_text(
                "export const value = 1\n", encoding="utf-8"
            )
            inventory_path = root / "repo-profile-matrix.json"
            rules_path = root / "public-api-rules.yaml"
            _write_inventory(inventory_path, repo_path)
            _write_rules(rules_path)
            result = MODULE.classify_public_api(
                inventory_path=inventory_path, rules_path=rules_path
            )
            repo = result["repositories"][0]
            self.assertEqual(repo["repo_name"], "demo")
            self.assertEqual(repo["classification_status"], "error")
            self.assertIn("unable to list files for repo", repo["classification_error"])
            self.assertEqual(repo["classified_file_count"], 0)
            self.assertEqual(repo["unknown_surface_file_count"], 0)
            self.assertEqual(repo["files"], [])


if __name__ == "__main__":
    unittest.main()
