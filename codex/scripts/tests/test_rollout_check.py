"""Unit tests for rollout_check.py."""

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
    Path(__file__).resolve().parents[1] / "hook-governance" / "rollout_check.py"
)
SPEC = importlib.util.spec_from_file_location("rollout_check", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load rollout checker module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _artifact(
    repo_path: Path,
    *,
    freshness_status: str = "fresh",
    drift_detected_at: str = "2026-04-10T00:00:00Z",
    drift_severity: str = "low",
    stages: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if stages is None:
        stages = [
            {
                "stage": "pre-commit",
                "gate_id": "docstrings",
                "owner_layer": "git_local",
                "command": "make hooks-pre-commit",
                "severity_mode": "hard-block",
                "scope": "changed-files",
                "timeout_seconds": 120,
            },
            {
                "stage": "pre-commit",
                "gate_id": "lint",
                "owner_layer": "git_local",
                "command": "make hooks-pre-commit",
                "severity_mode": "hard-block",
                "scope": "changed-files",
                "timeout_seconds": 120,
            },
            {
                "stage": "pre-commit",
                "gate_id": "typecheck",
                "owner_layer": "git_local",
                "command": "make hooks-pre-commit",
                "severity_mode": "hard-block",
                "scope": "changed-files",
                "timeout_seconds": 120,
            },
            {
                "stage": "pre-commit",
                "gate_id": "spelling",
                "owner_layer": "git_local",
                "command": "make hooks-pre-commit",
                "severity_mode": "warning",
                "scope": "changed-files",
                "timeout_seconds": 120,
            },
            {
                "stage": "pre-push",
                "gate_id": "unit",
                "owner_layer": "git_local",
                "command": "make hooks-pre-push",
                "severity_mode": "hard-block",
                "scope": "full-repo",
                "timeout_seconds": 300,
            },
            {
                "stage": "pre-commit",
                "gate_id": "formatting",
                "owner_layer": "git_local",
                "command": "make hooks-pre-commit",
                "severity_mode": "hard-block",
                "scope": "changed-files",
                "timeout_seconds": 120,
            },
        ]
    drift_flags: list[dict[str, str]] = []
    if drift_severity:
        drift_flags.append(
            {
                "id": "sample-drift",
                "severity": drift_severity,
                "summary": "sample drift for unit test",
                "detected_at": drift_detected_at,
            }
        )
    return {
        "schema_version": "hook-conformance.v1",
        "artifact_generated_at": "2026-04-10T00:00:00Z",
        "evaluated_at": "2026-04-10T00:00:00Z",
        "repo_path": str(repo_path),
        "profile": "standard-prek-wrapper",
        "frameworks_active": ["prek"],
        "hook_config_digest": "a" * 64,
        "evaluated_hook_config_digest": "a" * 64,
        "stages": stages,
        "drift_flags": drift_flags,
        "arbitration_decisions": [],
        "freshness_status": freshness_status,
    }


class RolloutCheckTests(unittest.TestCase):
    def test_reports_missing_artifact_with_explicit_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "demo"
            _fixture_resource(repo_path).mkdir()
            inventory_path = root / "repo-profile-matrix.json"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": str(root),
                        "excluded_repositories": [],
                        "repositories": [
                            {
                                "repo_name": "demo",
                                "repo_path": str(repo_path),
                                "profile_type": "standard-prek-wrapper",
                            }
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            result = MODULE.evaluate_rollout(
                inventory_path=inventory_path,
                required_gate_ids=MODULE.DEFAULT_REQUIRED_GATE_IDS,
                recovery_slo_hours=24,
                now_rfc3339="2026-04-10T03:00:00Z",
            )
            self.assertFalse(result["overall_ok"])
            issue_text = "\n".join(result["blocking_issues"])
            self.assertIn("repo 'demo' missing conformance artifact", issue_text)
            self.assertIn(".codex/hook-conformance.json", issue_text)

    def test_reports_missing_repo_path_as_blocking_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "missing"
            inventory_path = root / "repo-profile-matrix.json"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": str(root),
                        "excluded_repositories": [],
                        "repositories": [
                            {
                                "repo_name": "missing",
                                "repo_path": str(repo_path),
                                "profile_type": "standard-prek-wrapper",
                            }
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            result = MODULE.evaluate_rollout(
                inventory_path=inventory_path,
                required_gate_ids=MODULE.DEFAULT_REQUIRED_GATE_IDS,
                recovery_slo_hours=24,
                now_rfc3339="2026-04-10T03:00:00Z",
            )
            self.assertFalse(result["overall_ok"])
            repo_summary = result["repositories"][0]
            self.assertEqual(repo_summary["status"], "fail")
            issue_text = "\n".join(result["blocking_issues"])
            self.assertIn("repo 'missing' missing conformance artifact", issue_text)
            self.assertIn(".codex/hook-conformance.json", issue_text)

    def test_rejects_invalid_inventory_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inventory_path = root / "repo-profile-matrix.json"
            _fixture_resource(inventory_path).write_text(
                json.dumps({"schema_version": 1, "repositories": {}}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(MODULE.RolloutCheckError):
                MODULE.evaluate_rollout(
                    inventory_path=inventory_path,
                    required_gate_ids=MODULE.DEFAULT_REQUIRED_GATE_IDS,
                    recovery_slo_hours=24,
                    now_rfc3339="2026-04-10T03:00:00Z",
                )

    def test_flags_high_severity_drift_when_slo_expires(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "demo"
            _fixture_resource(repo_path / ".codex").mkdir(parents=True)
            artifact_path = repo_path / ".codex" / "hook-conformance.json"
            _fixture_resource(artifact_path).write_text(
                json.dumps(
                    _artifact(
                        repo_path,
                        freshness_status="fresh",
                        drift_detected_at="2026-04-09T00:00:00Z",
                        drift_severity="high",
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            inventory_path = root / "repo-profile-matrix.json"
            _fixture_resource(inventory_path).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workspace_root": str(root),
                        "excluded_repositories": [],
                        "repositories": [
                            {
                                "repo_name": "demo",
                                "repo_path": str(repo_path),
                                "profile_type": "standard-prek-wrapper",
                            }
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            result = MODULE.evaluate_rollout(
                inventory_path=inventory_path,
                required_gate_ids=MODULE.DEFAULT_REQUIRED_GATE_IDS,
                recovery_slo_hours=12,
                now_rfc3339="2026-04-10T03:00:00Z",
            )
            self.assertFalse(result["overall_ok"])
            issue_text = "\n".join(result["blocking_issues"])
            self.assertIn("recovery SLO exceeded", issue_text)
            self.assertIn("sample-drift", issue_text)


if __name__ == "__main__":
    unittest.main()
