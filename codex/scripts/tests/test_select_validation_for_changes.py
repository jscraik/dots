from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


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


MODULE_PATH = Path(__file__).resolve().parents[1] / "select-validation-for-changes.py"
SPEC = importlib.util.spec_from_file_location(
    "select_validation_for_changes", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load router module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "changed-files.txt"


class SelectValidationForChangesTests(unittest.TestCase):
    def test_build_result_routes_supported_file_types(self) -> None:
        with mock.patch.object(MODULE, "tool_available", return_value=True):
            report = MODULE.build_result(MODULE.read_changed_files(FIXTURE))
        self.assertEqual(report["schema_version"], "validation-router/v1")
        self.assertEqual(report["service"], "validation-router")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(
            [route["kind"] for route in report["routes"]],
            [
                "codex-config",
                "shell",
                "python",
                "markdown",
                "json",
                "semgrep-policy",
                "yaml",
            ],
        )
        self.assertEqual(
            report["first_action"], "python3 codex/scripts/validate-codex-config.py"
        )

    def test_fallback_commands_stay_target_specific_or_repo_owned(self) -> None:
        with mock.patch.object(MODULE, "tool_available", return_value=True):
            report = MODULE.build_result(
                ["codex/notes/example.toml", "codex/notes/example.yaml"]
            )
        self.assertEqual(report["status"], "pass")
        routes = {route["kind"]: route for route in report["routes"]}
        self.assertEqual(
            routes["toml"]["command"],
            'python3 -c "import pathlib, sys, tomllib; tomllib.loads(pathlib.Path(sys.argv[1]).read_text())" codex/notes/example.toml',
        )
        self.assertEqual(
            routes["toml"]["fallback"], "taplo check codex/notes/example.toml"
        )
        self.assertEqual(
            routes["yaml"]["command"], "node scripts/validate-config-repo.mjs lint"
        )
        self.assertEqual(
            routes["yaml"]["fallback"], "yq eval . codex/notes/example.yaml"
        )

    def test_blocks_when_primary_tool_is_missing(self) -> None:
        with mock.patch.object(
            MODULE, "tool_available", side_effect=lambda tool: tool != "python3"
        ):
            report = MODULE.build_result(["codex/notes/example.toml"])
        self.assertEqual(report["status"], "blocked")
        route = report["routes"][0]
        self.assertEqual(route["kind"], "toml")
        self.assertEqual(route["status"], "blocked")
        self.assertIn("python3 is not available on PATH", route["reason"])

    def test_reads_changed_files_ignoring_comments_and_blank_lines(self) -> None:
        self.assertEqual(
            MODULE.read_changed_files(FIXTURE),
            [
                "codex/config.toml",
                "codex/hooks/session-start.sh",
                "codex/scripts/validate-codex-config.py",
                "codex/reports/workflow-improvements/2026-07-03-daily-workflow-improvement-sweep.md",
                "codex/schemas/workflow-closeout.v1.schema.json",
                "codex/rules/workflow-anti-patterns.semgrep.yml",
                "codex/notes/runtime-rules.yaml",
            ],
        )

    def test_self_test_smoke_check(self) -> None:
        MODULE.self_test()


if __name__ == "__main__":
    unittest.main()
