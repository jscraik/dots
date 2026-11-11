"""Unit tests for codex/scripts/hook-governance/inventory_repos.py."""

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
    Path(__file__).resolve().parents[1] / "hook-governance" / "inventory_repos.py"
)
SPEC = importlib.util.spec_from_file_location("inventory_repos", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load inventory module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InventoryReposTests(unittest.TestCase):
    def test_rejects_missing_repo_path_with_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "repo-scope.manifest.json"
            _fixture_resource(manifest_path).write_text(
                json.dumps(
                    {
                        "workspace_root": ".",
                        "repos": {"in_scope": ["missing-repo"], "excluded": []},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                MODULE.ManifestValidationError,
                "missing repo path for in-scope repo 'missing-repo'.*create the repo or remove it from repos.in_scope",
            ):
                MODULE.build_inventory(manifest_path)

    def test_rejects_excluded_repo_in_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _fixture_resource(root / "agent-skills").mkdir()
            manifest_path = root / "repo-scope.manifest.json"
            _fixture_resource(manifest_path).write_text(
                json.dumps(
                    {
                        "workspace_root": ".",
                        "repos": {
                            "in_scope": ["agent-skills", "codex"],
                            "excluded": ["codex"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                MODULE.ManifestValidationError,
                "excluded repo 'codex' must not appear in repos.in_scope",
            ):
                MODULE.build_inventory(manifest_path)

    def test_detects_wrapper_targets_and_simple_git_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "coding-harness"
            _fixture_resource(repo_path).mkdir()
            _fixture_resource(repo_path / "Makefile").write_text(
                ".PHONY: hooks-pre-commit hooks-pre-push\nhooks-pre-commit:\n\tpnpm lint\nhooks-pre-push:\n\tpnpm test\n",
                encoding="utf-8",
            )
            _fixture_resource(repo_path / "package.json").write_text(
                json.dumps(
                    {
                        "name": "coding-harness",
                        "simple-git-hooks": {
                            "pre-commit": "make hooks-pre-commit",
                            "commit-msg": "node scripts/validate-commit-msg.js $1",
                            "pre-push": "make hooks-pre-push",
                        },
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = root / "repo-scope.manifest.json"
            _fixture_resource(manifest_path).write_text(
                json.dumps(
                    {
                        "workspace_root": ".",
                        "repos": {"in_scope": ["coding-harness"], "excluded": []},
                    }
                ),
                encoding="utf-8",
            )
            inventory = MODULE.build_inventory(manifest_path)
            self.assertEqual(
                inventory["repositories"],
                [
                    {
                        "repo_name": "coding-harness",
                        "repo_path": str(repo_path.resolve()),
                        "frameworks_present": ["simple-git-hooks"],
                        "gate_entrypoints": {
                            "hooks-commit-msg": "node scripts/validate-commit-msg.js $1",
                            "hooks-pre-commit": "make hooks-pre-commit",
                            "hooks-pre-push": "make hooks-pre-push",
                        },
                        "commit_msg_policy": {
                            "source": "simple-git-hooks",
                            "command": "node scripts/validate-commit-msg.js $1",
                        },
                        "profile_type": "repo-specific-exception",
                    }
                ],
            )
            self.assertEqual(inventory["schema_version"], 1)

    def test_detects_multiple_framework_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "oak"
            _fixture_resource(repo_path).mkdir()
            _fixture_resource(repo_path / ".pre-commit-config.yaml").write_text(
                "repos: []\n", encoding="utf-8"
            )
            _fixture_resource(repo_path / ".githooks").mkdir()
            _fixture_resource(repo_path / "prek.toml").write_text(
                "[tools]\n", encoding="utf-8"
            )
            manifest_path = root / "repo-scope.manifest.json"
            _fixture_resource(manifest_path).write_text(
                json.dumps(
                    {
                        "workspace_root": ".",
                        "repos": {"in_scope": ["oak"], "excluded": []},
                    }
                ),
                encoding="utf-8",
            )
            inventory = MODULE.build_inventory(manifest_path)
            self.assertEqual(
                inventory["repositories"][0]["frameworks_present"],
                [".githooks", "pre-commit", "prek"],
            )

    def test_emits_repo_profile_type_and_schema_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "diagram-cli"
            _fixture_resource(repo_path).mkdir()
            _fixture_resource(repo_path / "prek.toml").write_text(
                "[tools]\n", encoding="utf-8"
            )
            _fixture_resource(repo_path / "Makefile").write_text(
                "hooks-pre-commit:\n\techo pre-commit\nhooks-pre-push:\n\techo pre-push\nhooks-commit-msg:\n\techo commit-msg\n",
                encoding="utf-8",
            )
            manifest_path = root / "repo-scope.manifest.json"
            _fixture_resource(manifest_path).write_text(
                json.dumps(
                    {
                        "workspace_root": ".",
                        "repos": {"in_scope": ["diagram-cli"], "excluded": []},
                    }
                ),
                encoding="utf-8",
            )
            inventory = MODULE.build_inventory(manifest_path)
            self.assertEqual(
                inventory,
                {
                    "schema_version": 1,
                    "workspace_root": str(root.resolve()),
                    "excluded_repositories": [],
                    "repositories": [
                        {
                            "repo_name": "diagram-cli",
                            "repo_path": str(repo_path.resolve()),
                            "frameworks_present": ["prek"],
                            "gate_entrypoints": {
                                "hooks-commit-msg": "make hooks-commit-msg",
                                "hooks-pre-commit": "make hooks-pre-commit",
                                "hooks-pre-push": "make hooks-pre-push",
                            },
                            "commit_msg_policy": None,
                            "profile_type": "standard-prek-wrapper",
                        }
                    ],
                },
            )


if __name__ == "__main__":
    unittest.main()
