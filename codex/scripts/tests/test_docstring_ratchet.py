"""Unit tests for evaluate_docstring_ratchet.py."""

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
    / "evaluate_docstring_ratchet.py"
)
SPEC = importlib.util.spec_from_file_location("evaluate_docstring_ratchet", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load ratchet module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DocstringRatchetTests(unittest.TestCase):
    def _write_rules(self, path: Path) -> None:
        payload = {
            "schema_version": "public-api-rules.v1",
            "default_rules": [{"rule_id": "r1"}, {"rule_id": "r2"}],
            "repositories": {},
        }
        _fixture_resource(path).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_unknown_surface_remains_warning_and_flags_classifier_drift(self) -> None:
        classification_payload = {
            "schema_version": "public-api-classification.v1",
            "repositories": [
                {
                    "repo_name": "demo",
                    "repo_path": "/tmp/demo",
                    "files": [
                        {
                            "path": "src/index.ts",
                            "label": "public",
                            "matched_rule_id": "r1",
                        },
                        {
                            "path": "src/internal/util.ts",
                            "label": "internal",
                            "matched_rule_id": "r2",
                        },
                        {
                            "path": "scripts/helper.ts",
                            "label": "unknown-surface",
                            "matched_rule_id": "",
                        },
                    ],
                }
            ],
        }
        metrics_payload = {
            "schema_version": "docstring-ratchet-metrics.v1",
            "repositories": {
                "demo": {
                    "false_positive_rate_weekly": [0.03, 0.02],
                    "unresolved_high_conf_suppressions_over_7d": 0,
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            classification_path = root / "classification.json"
            metrics_path = root / "metrics.json"
            rules_path = root / "public-api-rules.json"
            _fixture_resource(classification_path).write_text(
                json.dumps(classification_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _fixture_resource(metrics_path).write_text(
                json.dumps(metrics_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self._write_rules(rules_path)
            result = MODULE.evaluate_docstring_ratchet(
                classification_path=classification_path,
                window_days=14,
                metrics_path=metrics_path,
                rules_path=rules_path,
            )
        repo = result["repositories"][0]
        files = {entry["path"]: entry for entry in repo["files"]}
        self.assertTrue(repo["ratchet_ready"])
        self.assertEqual(files["src/index.ts"]["severity_mode"], "hard-block")
        self.assertEqual(files["src/internal/util.ts"]["severity_mode"], "warning")
        self.assertEqual(files["scripts/helper.ts"]["severity_mode"], "warning")
        self.assertIn("classifier-drift", files["scripts/helper.ts"]["drift_flags"])

    def test_ratchet_not_ready_when_false_positive_or_stale_suppressions(self) -> None:
        classification_payload = {
            "schema_version": "public-api-classification.v1",
            "repositories": [
                {"repo_name": "demo", "repo_path": "/tmp/demo", "files": []}
            ],
        }
        metrics_payload = {
            "schema_version": "docstring-ratchet-metrics.v1",
            "repositories": {
                "demo": {
                    "false_positive_rate_weekly": [0.03, 0.08],
                    "unresolved_high_conf_suppressions_over_7d": 2,
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            classification_path = root / "classification.json"
            metrics_path = root / "metrics.json"
            rules_path = root / "public-api-rules.json"
            _fixture_resource(classification_path).write_text(
                json.dumps(classification_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _fixture_resource(metrics_path).write_text(
                json.dumps(metrics_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self._write_rules(rules_path)
            result = MODULE.evaluate_docstring_ratchet(
                classification_path=classification_path,
                window_days=14,
                metrics_path=metrics_path,
                rules_path=rules_path,
            )
        repo = result["repositories"][0]
        self.assertFalse(repo["ratchet_ready"])
        self.assertTrue(
            any("false-positive" in reason for reason in repo["ratchet_reasons"])
        )
        self.assertTrue(
            any("suppression" in reason for reason in repo["ratchet_reasons"])
        )


if __name__ == "__main__":
    unittest.main()
