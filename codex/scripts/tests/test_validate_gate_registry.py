"""Unit tests for codex/scripts/hook-governance/validate_gate_registry.py."""

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
    Path(__file__).resolve().parents[1]
    / "hook-governance"
    / "validate_gate_registry.py"
)
SPEC = importlib.util.spec_from_file_location("validate_gate_registry", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load validator module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ValidateGateRegistryTests(unittest.TestCase):
    def test_rejects_matcher_assumptions_on_stop_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inventory_path = root / "repo-profile-matrix.json"
            ownership_path = root / "gate-ownership-matrix.yaml"
            policy_path = root / "stage-policy-matrix.yaml"
            runtime_policy_path = root / "codex-hook-runtime-policy.md"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": "/tmp/workspace",
                        "excluded_repositories": [],
                        "repositories": [],
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(ownership_path).write_text(
                json.dumps({"owners": []}), encoding="utf-8"
            )
            _fixture_resource(policy_path).write_text(
                json.dumps(
                    {
                        "required_gate_categories": [],
                        "events": {
                            "PreToolUse": {"supported_blockers": []},
                            "Stop": {"matcher_supported": True},
                        },
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(runtime_policy_path).write_text(
                "Stop and UserPromptSubmit do not support matcher filtering.\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_gate_registry(
                inventory_path=inventory_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                runtime_policy_path=runtime_policy_path,
            )
            self.assertIn(
                "event 'Stop' must not declare matcher support in the stage policy",
                errors,
            )

    def test_rejects_missing_stage_entrypoints_and_commit_msg_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inventory_path = root / "repo-profile-matrix.json"
            ownership_path = root / "gate-ownership-matrix.yaml"
            policy_path = root / "stage-policy-matrix.yaml"
            runtime_policy_path = root / "codex-hook-runtime-policy.md"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": "/tmp/workspace",
                        "excluded_repositories": [],
                        "repositories": [
                            {
                                "repo_name": "oak",
                                "repo_path": "/tmp/workspace/oak",
                                "frameworks_present": ["prek"],
                                "gate_entrypoints": {
                                    "hooks-pre-commit": "make hooks-pre-commit"
                                },
                                "profile_type": "repo-specific-exception",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(ownership_path).write_text(
                json.dumps(
                    {
                        "owners": [
                            {
                                "profile_type": "repo-specific-exception",
                                "stage": "pre-commit",
                                "gate_id": "docstrings",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "repo-specific-exception",
                                "stage": "pre-commit",
                                "gate_id": "lint",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "repo-specific-exception",
                                "stage": "pre-commit",
                                "gate_id": "typecheck",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "repo-specific-exception",
                                "stage": "pre-commit",
                                "gate_id": "spelling",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "repo-specific-exception",
                                "stage": "pre-push",
                                "gate_id": "unit",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "repo-specific-exception",
                                "stage": "pre-commit",
                                "gate_id": "formatting",
                                "owner_layer": "git_local",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(policy_path).write_text(
                json.dumps(
                    {
                        "required_gate_categories": [
                            "docstrings",
                            "lint",
                            "typecheck",
                            "spelling",
                            "unit",
                            "formatting",
                        ],
                        "events": {"PreToolUse": {"supported_blockers": []}},
                        "required_stage_entrypoints": [
                            "hooks-pre-commit",
                            "hooks-pre-push",
                        ],
                        "require_commit_msg_policy": True,
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(runtime_policy_path).write_text(
                "Stop and UserPromptSubmit do not support matcher filtering.\nPreToolUse must not use continue:false because that output is unsupported.\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_gate_registry(
                inventory_path=inventory_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                runtime_policy_path=runtime_policy_path,
            )
            self.assertIn(
                "repo 'oak' missing required gate entrypoint 'hooks-pre-push'", errors
            )
            self.assertIn("repo 'oak' missing commit_msg_policy state", errors)

    def test_rejects_duplicate_owner_for_same_profile_stage_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inventory_path = root / "repo-profile-matrix.json"
            ownership_path = root / "gate-ownership-matrix.yaml"
            policy_path = root / "stage-policy-matrix.yaml"
            runtime_policy_path = root / "codex-hook-runtime-policy.md"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": "/tmp/workspace",
                        "excluded_repositories": [],
                        "repositories": [
                            {
                                "repo_name": "diagram-cli",
                                "repo_path": "/tmp/workspace/diagram-cli",
                                "frameworks_present": ["prek"],
                                "gate_entrypoints": {
                                    "hooks-pre-commit": "make hooks-pre-commit",
                                    "hooks-pre-push": "make hooks-pre-push",
                                },
                                "profile_type": "standard-prek-wrapper",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(ownership_path).write_text(
                json.dumps(
                    {
                        "owners": [
                            {
                                "profile_type": "standard-prek-wrapper",
                                "stage": "pre-commit",
                                "gate_id": "lint",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "standard-prek-wrapper",
                                "stage": "pre-commit",
                                "gate_id": "lint",
                                "owner_layer": "project_codex",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(policy_path).write_text(
                json.dumps(
                    {
                        "required_gate_categories": [
                            "docstrings",
                            "lint",
                            "typecheck",
                            "spelling",
                            "unit",
                            "formatting",
                        ],
                        "events": {"PreToolUse": {"supported_blockers": []}},
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(runtime_policy_path).write_text(
                "PreToolUse must not use continue:false because that output is unsupported.\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_gate_registry(
                inventory_path=inventory_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                runtime_policy_path=runtime_policy_path,
            )
            self.assertIn(
                "duplicate owner for profile_type='standard-prek-wrapper', stage='pre-commit', gate_id='lint'",
                errors,
            )

    def test_rejects_missing_required_gate_category_for_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inventory_path = root / "repo-profile-matrix.json"
            ownership_path = root / "gate-ownership-matrix.yaml"
            policy_path = root / "stage-policy-matrix.yaml"
            runtime_policy_path = root / "codex-hook-runtime-policy.md"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": "/tmp/workspace",
                        "excluded_repositories": [],
                        "repositories": [
                            {
                                "repo_name": "diagram-cli",
                                "repo_path": "/tmp/workspace/diagram-cli",
                                "frameworks_present": ["prek"],
                                "gate_entrypoints": {
                                    "hooks-pre-commit": "make hooks-pre-commit",
                                    "hooks-pre-push": "make hooks-pre-push",
                                },
                                "profile_type": "standard-prek-wrapper",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(ownership_path).write_text(
                json.dumps(
                    {
                        "owners": [
                            {
                                "profile_type": "standard-prek-wrapper",
                                "stage": "pre-commit",
                                "gate_id": "docstrings",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "standard-prek-wrapper",
                                "stage": "pre-commit",
                                "gate_id": "lint",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "standard-prek-wrapper",
                                "stage": "pre-commit",
                                "gate_id": "typecheck",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "standard-prek-wrapper",
                                "stage": "pre-push",
                                "gate_id": "unit",
                                "owner_layer": "git_local",
                            },
                            {
                                "profile_type": "standard-prek-wrapper",
                                "stage": "pre-commit",
                                "gate_id": "formatting",
                                "owner_layer": "git_local",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(policy_path).write_text(
                json.dumps(
                    {
                        "required_gate_categories": [
                            "docstrings",
                            "lint",
                            "typecheck",
                            "spelling",
                            "unit",
                            "formatting",
                        ],
                        "events": {"PreToolUse": {"supported_blockers": []}},
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(runtime_policy_path).write_text(
                "PreToolUse must not use continue:false because that output is unsupported.\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_gate_registry(
                inventory_path=inventory_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                runtime_policy_path=runtime_policy_path,
            )
            self.assertIn(
                "missing gate category 'spelling' for profile_type='standard-prek-wrapper'",
                errors,
            )

    def test_rejects_pretooluse_continue_false_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inventory_path = root / "repo-profile-matrix.json"
            ownership_path = root / "gate-ownership-matrix.yaml"
            policy_path = root / "stage-policy-matrix.yaml"
            runtime_policy_path = root / "codex-hook-runtime-policy.md"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": "/tmp/workspace",
                        "excluded_repositories": [],
                        "repositories": [],
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(ownership_path).write_text(
                json.dumps({"owners": []}), encoding="utf-8"
            )
            _fixture_resource(policy_path).write_text(
                json.dumps(
                    {
                        "events": {
                            "PreToolUse": {
                                "block_output": {
                                    "continue": False,
                                    "reason": "block commit",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(runtime_policy_path).write_text(
                "Supported PreToolUse blockers use permissionDecision or decision: block.\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_gate_registry(
                inventory_path=inventory_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                runtime_policy_path=runtime_policy_path,
            )
            self.assertEqual(
                errors,
                [
                    "PreToolUse blockers must not rely on continue:false; use hookSpecificOutput.permissionDecision=deny, decision=block, or exit code 2"
                ],
            )

    def test_allows_runtime_policy_to_document_continue_false_as_unsupported(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inventory_path = root / "repo-profile-matrix.json"
            ownership_path = root / "gate-ownership-matrix.yaml"
            policy_path = root / "stage-policy-matrix.yaml"
            runtime_policy_path = root / "codex-hook-runtime-policy.md"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": "/tmp/workspace",
                        "excluded_repositories": [],
                        "repositories": [],
                    }
                ),
                encoding="utf-8",
            )
            _fixture_resource(ownership_path).write_text(
                json.dumps({"owners": []}), encoding="utf-8"
            )
            _fixture_resource(policy_path).write_text(
                json.dumps({"events": {"PreToolUse": {"supported_blockers": []}}}),
                encoding="utf-8",
            )
            _fixture_resource(runtime_policy_path).write_text(
                "PreToolUse must not use continue:false because that output is unsupported.\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_gate_registry(
                inventory_path=inventory_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                runtime_policy_path=runtime_policy_path,
            )
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
