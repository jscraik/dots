"""Unit tests for codex/scripts/validate-agent-governance.py."""

from __future__ import annotations

import importlib.util
import shutil
import sys
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


MODULE_PATH = Path(__file__).resolve().parents[1] / "validate-agent-governance.py"
SPEC = importlib.util.spec_from_file_location("validate_agent_governance", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load validator module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValidateAgentGovernanceTests(unittest.TestCase):
    def test_prose_can_change_but_machine_markers_remain_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for check in MODULE.GOVERNANCE_CHECKS:
                source = MODULE.DEFAULT_ROOT / check.path
                target = root / check.path
                _fixture_resource(target.parent).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            self.assertEqual(MODULE.validate(root), [])
            governance = root / "instructions/agents/07b-agent-governance.md"
            original = _fixture_resource(governance).read_text(encoding="utf-8")
            paraphrased = original.replace(
                "Path verification before delegation",
                "Check required paths before dispatch",
            )
            self.assertNotEqual(paraphrased, original)
            _fixture_resource(governance).write_text(paraphrased, encoding="utf-8")
            self.assertEqual(MODULE.validate(root), [])
            _fixture_resource(governance).write_text(
                _fixture_resource(governance)
                .read_text(encoding="utf-8")
                .replace("STATUS: complete", "STATUS: finished"),
                encoding="utf-8",
            )
            self.assertTrue(MODULE.validate(root))

    def test_current_repo_contract_passes(self) -> None:
        root = MODULE.DEFAULT_ROOT
        failures = MODULE.validate(root)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
