"""Unit tests for arbitrate_hook_results.py."""

from __future__ import annotations

import importlib.util
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
    / "arbitrate_hook_results.py"
)
SPEC = importlib.util.spec_from_file_location("arbitrate_hook_results", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load arbitration module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArbitrateHookResultsTests(unittest.TestCase):
    def test_canonical_block_wins_over_noncanonical_block_and_warning(self) -> None:
        """
        Verify a canonical block candidate overrides non-canonical block and warning candidates.

        Constructs a payload with a non-canonical block, a canonical block and an allow-with-warning candidate, then asserts the arbitration selects the canonical block as the winning action (`"block"`), reports its reason and owner layer, and records zero suppressed reasons.
        """
        payload = {
            "event_name": "PreToolUse",
            "candidates": [
                {
                    "gate_id": "lint",
                    "owner_layer": "global_codex",
                    "source_path": "/a",
                    "decision": "block",
                    "reason": "global block",
                    "is_canonical_owner": False,
                },
                {
                    "gate_id": "lint",
                    "owner_layer": "project_codex",
                    "source_path": "/b",
                    "decision": "block",
                    "reason": "canonical block",
                    "is_canonical_owner": True,
                },
                {
                    "gate_id": "lint",
                    "owner_layer": "git_local",
                    "source_path": "/c",
                    "action": "allow-with-warning",
                    "reason": "warning",
                },
            ],
        }
        decision = MODULE.arbitrate_results(payload)
        self.assertEqual(decision["action"], "block")
        self.assertEqual(decision["winning_reason"], "canonical block")
        self.assertEqual(decision["owner_layer"], "project_codex")
        self.assertEqual(decision["suppressed_reason_count"], 0)

    def test_competing_canonical_blocks_use_owner_precedence_then_lexical(self) -> None:
        """
        Ensure that when multiple canonical `block` candidates conflict, arbitration selects the candidate by owner-layer precedence and then by lexical `source_path`.

        Test scenario: three canonical `block` candidates from two owner layers; the decision must pick the `git_local` owner and the lexicographically earliest `source_path` (`/a`), produce action `"block"`, and report two suppressed reasons.
        """
        payload = {
            "event_name": "PreToolUse",
            "candidates": [
                {
                    "gate_id": "unit",
                    "owner_layer": "global_codex",
                    "source_path": "/z",
                    "decision": "block",
                    "reason": "global",
                    "is_canonical_owner": True,
                },
                {
                    "gate_id": "unit",
                    "owner_layer": "git_local",
                    "source_path": "/a",
                    "decision": "block",
                    "reason": "git-local",
                    "is_canonical_owner": True,
                },
                {
                    "gate_id": "unit",
                    "owner_layer": "git_local",
                    "source_path": "/b",
                    "decision": "block",
                    "reason": "git-local-later",
                    "is_canonical_owner": True,
                },
            ],
        }
        decision = MODULE.arbitrate_results(payload)
        self.assertEqual(decision["action"], "block")
        self.assertEqual(decision["owner_layer"], "git_local")
        self.assertEqual(decision["source_path"], "/a")
        self.assertEqual(decision["suppressed_reason_count"], 2)

    def test_noncanonical_block_downgrades_to_warning_without_canonical_block(
        self,
    ) -> None:
        """
        Verifies that a non-canonical `block` is downgraded to `allow-with-warning` when an explicit warning candidate exists.

        Sets up a `PreToolUse` payload with a non-canonical `block` candidate and an `allow-with-warning` candidate and asserts the arbitration result chooses `"allow-with-warning"` and records one suppressed reason.
        """
        payload = {
            "event_name": "PreToolUse",
            "candidates": [
                {
                    "gate_id": "formatting",
                    "owner_layer": "global_codex",
                    "source_path": "/a",
                    "decision": "block",
                    "reason": "noncanonical block",
                    "is_canonical_owner": False,
                },
                {
                    "gate_id": "formatting",
                    "owner_layer": "project_codex",
                    "source_path": "/b",
                    "action": "allow-with-warning",
                    "reason": "explicit warning",
                },
            ],
        }
        decision = MODULE.arbitrate_results(payload)
        self.assertEqual(decision["action"], "allow-with-warning")
        self.assertEqual(decision["suppressed_reason_count"], 1)

    def test_allows_when_no_warning_or_block_candidates_exist(self) -> None:
        """
        Verifies arbitration returns "allow" when no warning or block candidates are present.

        Asserts the decision's action is "allow", the winning reason is an empty string, and no reasons were suppressed (suppressed_reason_count == 0).
        """
        payload = {
            "event_name": "PostToolUse",
            "candidates": [
                {
                    "gate_id": "post-edit",
                    "owner_layer": "project_codex",
                    "source_path": "/repo/.codex/hooks/post-edit.sh",
                    "action": "allow",
                }
            ],
        }
        decision = MODULE.arbitrate_results(payload)
        self.assertEqual(decision["action"], "allow")
        self.assertEqual(decision["winning_reason"], "")
        self.assertEqual(decision["suppressed_reason_count"], 0)


if __name__ == "__main__":
    unittest.main()
