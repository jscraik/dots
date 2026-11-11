"""Unit tests for conformance schema generation and validation."""

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


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "hook-governance"
GENERATE_PATH = SCRIPT_ROOT / "generate_conformance.py"
GENERATE_SPEC = importlib.util.spec_from_file_location(
    "generate_conformance", GENERATE_PATH
)
if GENERATE_SPEC is None or GENERATE_SPEC.loader is None:
    raise RuntimeError(f"Unable to load generator module from {GENERATE_PATH}")
GENERATE = importlib.util.module_from_spec(GENERATE_SPEC)
GENERATE_SPEC.loader.exec_module(GENERATE)
VALIDATE_PATH = SCRIPT_ROOT / "validate_conformance.py"
VALIDATE_SPEC = importlib.util.spec_from_file_location(
    "validate_conformance", VALIDATE_PATH
)
if VALIDATE_SPEC is None or VALIDATE_SPEC.loader is None:
    raise RuntimeError(f"Unable to load validator module from {VALIDATE_PATH}")
VALIDATE = importlib.util.module_from_spec(VALIDATE_SPEC)
VALIDATE_SPEC.loader.exec_module(VALIDATE)
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "hook-conformance.v1.schema.json"
)


def _write_repo_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    repo_path = root / "demo"
    _fixture_resource(repo_path).mkdir()
    _fixture_resource(repo_path / "prek.toml").write_text("[tools]\n", encoding="utf-8")
    _fixture_resource(repo_path / "scripts").mkdir()
    _fixture_resource(repo_path / "scripts" / "validate-commit-msg.js").write_text(
        "process.exit(0)\n", encoding="utf-8"
    )
    _fixture_resource(repo_path / "Makefile").write_text(
        "hooks-pre-commit:\n\techo pre-commit\nhooks-pre-push:\n\techo pre-push\nhooks-commit-msg:\n\techo commit-msg\n",
        encoding="utf-8",
    )
    manifest_path = root / "repo-scope.manifest.json"
    _fixture_resource(manifest_path).write_text(
        json.dumps(
            {"workspace_root": ".", "repos": {"in_scope": ["demo"], "excluded": []}}
        ),
        encoding="utf-8",
    )
    ownership_path = root / "gate-ownership-matrix.yaml"
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
                        "stage": "pre-commit",
                        "gate_id": "spelling",
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
    policy_path = root / "stage-policy-matrix.yaml"
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
                "required_stage_entrypoints": ["hooks-pre-commit", "hooks-pre-push"],
                "require_commit_msg_policy": True,
            }
        ),
        encoding="utf-8",
    )
    return (repo_path, manifest_path, ownership_path, policy_path)


class ConformanceSchemaTests(unittest.TestCase):
    def test_publication_rejects_linked_directory_and_leaf(self) -> None:
        for ancestor in (True, False):
            with (
                self.subTest(ancestor=ancestor),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                repo, manifest, ownership, policy = _write_repo_fixture(root)
                outside = root / "outside"
                _fixture_resource(outside).mkdir()
                sentinel = outside / "hook-conformance.json"
                _fixture_resource(sentinel).write_text("preserve")
                if ancestor:
                    (repo / ".codex").symlink_to(outside, target_is_directory=True)
                else:
                    _fixture_resource(repo / ".codex").mkdir()
                    (repo / ".codex/hook-conformance.json").symlink_to(sentinel)
                with self.assertRaises(OSError):
                    GENERATE.generate_conformance_artifacts(
                        manifest_path=manifest,
                        ownership_path=ownership,
                        policy_path=policy,
                        out_mode="repo-local",
                    )
                self.assertEqual(_fixture_resource(sentinel).read_text(), "preserve")

    def test_verify_mode_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path, manifest_path, ownership_path, policy_path = _write_repo_fixture(
                root
            )
            artifacts = GENERATE.generate_conformance_artifacts(
                manifest_path=manifest_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                out_mode="verify",
            )
            self.assertEqual(len(artifacts), 1)
            self.assertFalse((repo_path / ".codex" / "hook-conformance.json").exists())

    def test_generated_artifact_validates_against_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _, manifest_path, ownership_path, policy_path = _write_repo_fixture(root)
            GENERATE.generate_conformance_artifacts(
                manifest_path=manifest_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                out_mode="repo-local",
            )
            errors = VALIDATE.validate_conformance_artifacts(
                schema_path=SCHEMA_PATH,
                manifest_path=manifest_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
            )
            self.assertEqual(errors, [])

    def test_rejects_outdated_artifact_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path, manifest_path, ownership_path, policy_path = _write_repo_fixture(
                root
            )
            GENERATE.generate_conformance_artifacts(
                manifest_path=manifest_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
                out_mode="repo-local",
            )
            artifact_path = repo_path / ".codex" / "hook-conformance.json"
            artifact = json.loads(
                _fixture_resource(artifact_path).read_text(encoding="utf-8")
            )
            artifact["schema_version"] = "hook-conformance.v0"
            _fixture_resource(artifact_path).write_text(
                json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            errors = VALIDATE.validate_conformance_artifacts(
                schema_path=SCHEMA_PATH,
                manifest_path=manifest_path,
                ownership_path=ownership_path,
                policy_path=policy_path,
            )
            self.assertTrue(
                any(
                    "schema_version='hook-conformance.v0'" in error for error in errors
                ),
                errors,
            )


if __name__ == "__main__":
    unittest.main()
