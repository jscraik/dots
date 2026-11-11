"""Unit tests for verify_gate_taxonomy.py."""

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
    Path(__file__).resolve().parents[1] / "hook-governance" / "verify_gate_taxonomy.py"
)
SPEC = importlib.util.spec_from_file_location("verify_gate_taxonomy", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load taxonomy verifier module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_repo_with_makefile(root: Path, repo_name: str) -> Path:
    repo_path = root / repo_name
    _fixture_resource(repo_path).mkdir()
    _fixture_resource(repo_path / "Makefile").write_text(
        'hooks-pre-commit:\n\t@true\nhooks-pre-push:\n\t@true\nhooks-commit-msg:\n\t@echo "$$HOOK_COMMIT_MSG" | grep -q "^feat:"\n\t@echo "$$HOOK_COMMIT_MSG" | grep -q "Co-authored-by: Codex <noreply@openai.com>"\n',
        encoding="utf-8",
    )
    return repo_path


class VerifyGateTaxonomyTests(unittest.TestCase):
    def test_rejects_missing_required_entrypoint(self) -> None:
        inventory = {
            "schema_version": 1,
            "workspace_root": "/tmp/workspace",
            "excluded_repositories": [],
            "repositories": [
                {
                    "repo_name": "demo",
                    "repo_path": "/tmp/workspace/demo",
                    "gate_entrypoints": {
                        "hooks-pre-commit": "make hooks-pre-commit",
                        "hooks-pre-push": "make hooks-pre-push",
                    },
                }
            ],
        }
        errors = MODULE.validate_entrypoints(inventory)
        self.assertIn(
            "repo 'demo' missing required gate entrypoint 'hooks-commit-msg'", errors
        )

    def test_commit_msg_vectors_pass_for_valid_and_fail_for_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = _write_repo_with_makefile(root, "demo")
            inventory = {
                "schema_version": 1,
                "workspace_root": str(root),
                "excluded_repositories": [],
                "repositories": [
                    {
                        "repo_name": "demo",
                        "repo_path": str(repo_path),
                        "gate_entrypoints": {
                            "hooks-pre-commit": "make hooks-pre-commit",
                            "hooks-pre-push": "make hooks-pre-push",
                            "hooks-commit-msg": "make hooks-commit-msg",
                        },
                    }
                ],
            }
            inventory_path = root / "repo-profile-matrix.json"
            _fixture_resource(inventory_path).write_text(
                json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            errors = MODULE.verify_gate_taxonomy(
                inventory_path=inventory_path,
                run_commit_msg_vectors_flag=True,
                make_bin="make",
            )
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
