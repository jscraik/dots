"""Negative controls for thread-only merged-PR reconciliation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch


def _fixture_test_env(environment):
    import os

    selected = {
        name: os.environ[name]
        for name in (
            "HOME",
            "DOTS_TEST_HOME",
            "DOTS_FIXTURE_ROOT",
            "TMPDIR",
            "CODEX_VALIDATION_PYTHON",
            "PYTHONPATH",
            "UV_OFFLINE",
        )
        if name in os.environ
    }
    selected.update(environment)
    return selected


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


SPEC = importlib.util.spec_from_file_location(
    "post_merge",
    Path(__file__).resolve().parents[1] / "pr-post-merge-reconciliation.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
HEAD, BASE, MERGE, TREE = (value * 40 for value in "abcd")


class PostMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd()
        self.args = argparse.Namespace(
            repo="owner/repo", pr=99, base="main", thread="PRRT_example", run=7
        )
        self.pr = {
            "url": "https://github.com/owner/repo/pull/99",
            "number": 99,
            "state": "MERGED",
            "headRefOid": HEAD,
            "baseRefOid": BASE,
            "baseRefName": "main",
            "mergeCommit": {"oid": MERGE},
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "validate",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "detailsUrl": "https://github.com/owner/repo/actions/runs/7/job/8",
                }
            ],
        }
        self.thread = {
            "id": self.args.thread,
            "isResolved": False,
            "isOutdated": False,
            "pullRequest": {"url": self.pr["url"], "number": 99, "headRefOid": HEAD},
            "comments": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [
                    {
                        "id": "comment1",
                        "body": "Await Linux validation",
                        "originalCommit": {"oid": HEAD},
                        "author": {"login": "coderabbitai", "__typename": "Bot"},
                    }
                ],
            },
        }
        self.args.source_comment = "comment1"
        self.args.source_sha256 = hashlib.sha256(b"Await Linux validation").hexdigest()
        self.run = {
            "id": 7,
            "head_sha": HEAD,
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/owner/repo/actions/runs/7",
            "repository": {"full_name": "owner/repo"},
            "updated_at": "2026-10-21T13:05:03Z",
        }

    def git_output(self, root: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return MERGE
        if args[0] == "ls-remote":
            return MERGE + "\trefs/heads/main"
        if args[0] == "rev-list":
            return MERGE + " " + BASE
        if args[0] == "rev-parse":
            return TREE
        raise AssertionError(args)

    def test_exact_accepted_tree_is_admitted(self) -> None:
        with (
            patch.object(MODULE, "git", side_effect=self.git_output),
            patch.object(
                MODULE.GATE, "repository_slug", return_value=("owner/repo", None)
            ),
            patch.object(MODULE.GATE, "dirty_lane", return_value={"status": "pass"}),
        ):
            result = MODULE.check_identity(self.root, self.args, self.pr)
            self.assertEqual(
                result,
                {
                    "reviewed_head": HEAD,
                    "original_base": BASE,
                    "merge": MERGE,
                    "tree": TREE,
                },
            )
            for changes in (
                {"state": "OPEN"},
                {"number": 98},
                {"url": "https://github.com/other/repo/pull/99"},
                {"headRefOid": "bad"},
                {"baseRefName": "other"},
                {"mergeCommit": {}},
                {"mergeCommit": None},
            ):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    MODULE.check_identity(self.root, self.args, self.pr | changes)
            with (
                patch.object(
                    MODULE.GATE, "dirty_lane", return_value={"status": "fail"}
                ),
                self.assertRaises(ValueError),
            ):
                MODULE.check_identity(self.root, self.args, self.pr)

    def test_tree_parent_checkout_and_remote_drift_reject(self) -> None:
        commands = [
            ("rev-parse", "HEAD"),
            ("ls-remote", "origin", "refs/heads/main"),
            ("rev-list", "--parents", "-n", "1", MERGE),
            ("rev-parse", f"{HEAD}^{{tree}}"),
        ]
        with (
            patch.object(
                MODULE.GATE, "repository_slug", return_value=("owner/repo", None)
            ),
            patch.object(MODULE.GATE, "dirty_lane", return_value={"status": "pass"}),
        ):
            for command in commands:

                def changed(
                    root: Path, *args: str, expected: tuple[str, ...] = command
                ) -> str:
                    return (
                        "e" * 40 if args == expected else self.git_output(root, *args)
                    )

                with (
                    self.subTest(command=command),
                    patch.object(MODULE, "git", side_effect=changed),
                    self.assertRaises(ValueError),
                ):
                    MODULE.check_identity(self.root, self.args, self.pr)

    def test_thread_author_head_completeness_and_identity_reject(self) -> None:
        variants = []
        for key, value in (
            ("id", "PRRT_other"),
            ("isResolved", True),
            ("isOutdated", True),
            ("pullRequest", {}),
            ("comments", {"nodes": []}),
        ):
            variants.append(self.thread | {key: value})
        for field, value in (
            ("author", {"login": "coderabbitai", "__typename": "User"}),
            ("originalCommit", {"oid": BASE}),
            ("originalCommit", None),
            ("body", ""),
        ):
            changed = copy.deepcopy(self.thread)
            changed["comments"]["nodes"][0][field] = value
            variants.append(changed)
        changed = copy.deepcopy(self.thread)
        changed["comments"]["pageInfo"]["hasNextPage"] = True
        variants.append(changed)
        for thread in [self.thread, *variants]:
            with patch.object(
                MODULE, "read_json", return_value={"data": {"node": thread}}
            ):
                if thread is self.thread:
                    self.assertEqual(
                        MODULE.read_thread(self.root, self.args, HEAD), thread
                    )
                else:
                    with self.subTest(thread=thread), self.assertRaises(ValueError):
                        MODULE.read_thread(self.root, self.args, HEAD)

    def test_original_review_commit_binds_source_after_current_commit_changes(
        self,
    ) -> None:
        thread = copy.deepcopy(self.thread)
        source = thread["comments"]["nodes"][0]
        source.update(originalCommit={"oid": HEAD}, commit={"oid": BASE})
        with patch.object(MODULE, "read_json", return_value={"data": {"node": thread}}):
            self.assertEqual(MODULE.read_thread(self.root, self.args, HEAD), thread)
        source.update(originalCommit={"oid": BASE}, commit={"oid": HEAD})
        with (
            patch.object(MODULE, "read_json", return_value={"data": {"node": thread}}),
            self.assertRaises(ValueError),
        ):
            MODULE.read_thread(self.root, self.args, HEAD)

    def test_collect_requires_successful_exact_head_ci_and_fixed_reply(self) -> None:
        identity = {
            "reviewed_head": HEAD,
            "original_base": BASE,
            "merge": MERGE,
            "tree": TREE,
        }
        with (
            patch.object(MODULE, "check_identity", return_value=identity),
            patch.object(MODULE, "validate_run"),
            patch.object(
                MODULE,
                "command_evidence",
                return_value={"steps": [{"command": "tested", "outcome": "pass"}]},
            ),
            patch.object(MODULE, "read_thread", return_value=self.thread),
        ):
            for run in [
                self.run,
                *[
                    self.run | {key: value}
                    for key, value in (
                        ("id", 8),
                        ("head_sha", BASE),
                        ("event", "push"),
                        ("status", "in_progress"),
                        ("conclusion", "failure"),
                        ("repository", {}),
                        ("html_url", "https://other"),
                    )
                ],
            ]:
                with patch.object(
                    MODULE,
                    "read_json",
                    side_effect=[self.pr, run, {"id": 1, "login": "owner"}],
                ):
                    if run is self.run:
                        snapshot = MODULE.collect(self.root, self.args)
                        self.assertFalse(snapshot["acceptance_claims_proven"])
                        self.assertEqual(
                            snapshot["allowed_mutations"],
                            ["thread_reply", "thread_resolve"],
                        )
                        self.assertIn(
                            "does not establish retrospective", snapshot["reply"]
                        )
                        self.assertIn("Command: `tested` -> pass", snapshot["reply"])
                    else:
                        with self.subTest(run=run), self.assertRaises(ValueError):
                            MODULE.collect(self.root, self.args)

    def test_duplicate_fixed_replies_reject_during_collection(self) -> None:
        identity = {
            "reviewed_head": HEAD,
            "original_base": BASE,
            "merge": MERGE,
            "tree": TREE,
        }
        with (
            patch.object(MODULE, "check_identity", return_value=identity),
            patch.object(MODULE, "validate_run"),
            patch.object(
                MODULE,
                "command_evidence",
                return_value={"steps": [{"command": "tested", "outcome": "pass"}]},
            ),
        ):

            def collect(thread: dict) -> dict:
                with (
                    patch.object(MODULE, "read_thread", return_value=thread),
                    patch.object(
                        MODULE,
                        "read_json",
                        side_effect=[self.pr, self.run, {"id": 1, "login": "owner"}],
                    ),
                ):
                    return MODULE.collect(self.root, self.args)

            baseline = collect(self.thread)
            for count in (0, 1, 2, 3):
                thread = copy.deepcopy(self.thread)
                thread["comments"]["nodes"].extend(
                    {
                        "id": f"reply-{index}",
                        "body": baseline["reply"],
                        "author": {"login": "owner"},
                    }
                    for index in range(count)
                )
                if count < 2:
                    self.assertEqual(collect(thread)["thread"], thread)
                else:
                    with self.assertRaisesRegex(
                        ValueError, "multiple matching evidence replies"
                    ):
                        collect(thread)
            for identifier in (None, "", 0, False, [], {}):
                thread = copy.deepcopy(self.thread)
                thread["comments"]["nodes"].append(
                    {
                        "id": identifier,
                        "body": baseline["reply"],
                        "author": {"login": "owner"},
                    }
                )
                with (
                    self.subTest(identifier=identifier),
                    self.assertRaisesRegex(ValueError, "later thread comments"),
                ):
                    collect(thread)

    def test_exact_commands_require_supported_workflow_and_executed_successful_steps(
        self,
    ) -> None:
        source = "supported immutable workflow"
        digest = hashlib.sha256(source.encode()).hexdigest()
        url = "https://github.com/owner/repo/actions/runs/7/job/9"
        job = {
            "id": 9,
            "run_id": self.args.run,
            "head_sha": HEAD,
            "html_url": url,
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {
                    "number": index,
                    "name": name,
                    "status": "completed",
                    "conclusion": "success",
                }
                for index, name in enumerate(MODULE.COMMAND_STEPS, 1)
            ],
        }
        with (
            patch.object(MODULE, "WORKFLOW_SHA256", digest),
            patch.object(MODULE.GATE, "run_command") as transport,
            patch.object(MODULE, "read_json", return_value=job),
        ):
            transport.return_value.stdout = source
            evidence = MODULE.command_evidence(self.root, self.args, HEAD, url)
            self.assertEqual(evidence["workflow_sha256"], digest)
            self.assertEqual(
                [item["command"] for item in evidence["steps"]],
                [
                    f"bash scripts/validate-repository.sh {phase}"
                    for phase in MODULE.COMMAND_STEPS.values()
                ],
            )
            transport.return_value.stdout = "changed workflow"
            with self.assertRaises(ValueError):
                MODULE.command_evidence(self.root, self.args, HEAD, url)
            transport.return_value.stdout = source
            variants = [
                job | {field: value}
                for field, value in (
                    ("id", 10),
                    ("run_id", 8),
                    ("head_sha", BASE),
                    ("html_url", "other"),
                    ("status", "queued"),
                    ("conclusion", "failure"),
                    ("steps", None),
                    ("steps", []),
                )
            ]
            for outcome in ("skipped", "failure", None):
                altered = copy.deepcopy(job)
                altered["steps"][1]["conclusion"] = outcome
                variants.append(altered)
            variants.append(job | {"steps": job["steps"] + [job["steps"][0]]})
            for variant in variants:
                with (
                    patch.object(MODULE, "read_json", return_value=variant),
                    self.assertRaises(ValueError),
                ):
                    MODULE.command_evidence(self.root, self.args, HEAD, url)

    def test_stale_changed_and_racing_receipts_never_mutate(self) -> None:
        snapshot = {
            "thread": self.thread,
            "reply": "fixed",
            "actor": {"login": "owner"},
            "reviewed_head": HEAD,
        }
        with tempfile.TemporaryDirectory() as temporary:
            self.args.receipt = Path(temporary) / "receipt.json"
            for age, evidence in (
                (601, snapshot),
                (-10, snapshot),
                (0, snapshot | {"reply": "other"}),
            ):
                _fixture_resource(self.args.receipt).write_text(
                    json.dumps(
                        {
                            "checked_at": (
                                datetime.now(UTC) - timedelta(seconds=age)
                            ).isoformat(),
                            "evidence": evidence,
                        }
                    )
                )
                with (
                    patch.object(MODULE, "read_json") as mutation,
                    self.assertRaises(ValueError),
                ):
                    MODULE.execute(self.root, self.args, snapshot)
                mutation.assert_not_called()
            _fixture_resource(self.args.receipt).write_text(
                json.dumps(
                    {"checked_at": datetime.now(UTC).isoformat(), "evidence": snapshot}
                )
            )
            with (
                patch.object(
                    MODULE, "collect", return_value=snapshot | {"reply": "changed"}
                ),
                patch.object(MODULE, "read_json") as mutation,
                self.assertRaises(ValueError),
            ):
                MODULE.execute(self.root, self.args, snapshot)
            mutation.assert_not_called()

    def test_ci_requires_correct_workflow_and_pr_association(self) -> None:
        run = self.run | {
            "workflow_id": 4,
            "path": ".github/workflows/validate.yml",
            "pull_requests": [{"number": 99}],
        }
        workflow = {"id": 4, "path": ".github/workflows/validate.yml"}
        with (
            patch.object(MODULE, "git"),
            patch.object(MODULE, "read_json", return_value=workflow),
        ):
            MODULE.validate_run(self.root, self.args, run, HEAD)
            for changes in (
                {"workflow_id": None},
                {"path": "other.yml"},
                {"pull_requests": [{"number": 98}]},
                {"pull_requests": [{"number": 99}, {"number": 98}]},
                {"pull_requests": [None]},
                {"pull_requests": None},
            ):
                with (
                    self.subTest(changes=changes),
                    self.assertRaises((ValueError, TypeError)),
                ):
                    MODULE.validate_run(self.root, self.args, run | changes, HEAD)
            command = MODULE.GATE.run_command
            with patch.object(MODULE.GATE, "run_command") as transport:
                transport.return_value.stdout = json.dumps(
                    [[{"number": 99, "html_url": self.pr["url"]}]]
                )
                MODULE.validate_run(
                    self.root, self.args, run | {"pull_requests": []}, HEAD
                )
                for pages in (
                    [],
                    [[None]],
                    {},
                    [
                        [
                            {
                                "number": 99,
                                "html_url": "https://github.com/other/repo/pull/99",
                            }
                        ]
                    ],
                    [[{"number": 98, "html_url": self.pr["url"]}]],
                    [[{"number": 99, "html_url": self.pr["url"]}] for _ in range(2)],
                ):
                    transport.return_value.stdout = json.dumps(pages)
                    with self.assertRaises(ValueError):
                        MODULE.validate_run(
                            self.root, self.args, run | {"pull_requests": []}, HEAD
                        )
            self.assertIs(MODULE.GATE.run_command, command)

    def test_exact_source_binding_rejects_wrong_comment_or_changed_body(self) -> None:
        for field, value in (("id", "other"), ("body", "A correctness defect remains")):
            thread = copy.deepcopy(self.thread)
            thread["comments"]["nodes"][0][field] = value
            with (
                patch.object(
                    MODULE, "read_json", return_value={"data": {"node": thread}}
                ),
                self.assertRaises(ValueError),
            ):
                MODULE.read_thread(self.root, self.args, HEAD)

    def mutation_snapshots(self) -> tuple[dict, dict, dict]:
        snapshot = {
            "thread": self.thread,
            "reply": "fixed",
            "actor": {"login": "owner"},
            "reviewed_head": HEAD,
        }
        after_reply = copy.deepcopy(snapshot)
        after_reply["thread"]["comments"]["nodes"].append(
            {"id": "reply", "body": "fixed", "author": {"login": "owner"}}
        )
        resolved = copy.deepcopy(after_reply)
        resolved["thread"]["isResolved"] = True
        return (snapshot, after_reply, resolved)

    def test_successful_reply_resolution_and_post_mutation_drift(self) -> None:
        snapshot, after_reply, resolved = self.mutation_snapshots()
        with tempfile.TemporaryDirectory() as temporary:
            self.args.receipt = Path(temporary) / "receipt.json"
            _fixture_resource(self.args.receipt).write_text(
                json.dumps(
                    {"checked_at": datetime.now(UTC).isoformat(), "evidence": snapshot}
                )
            )
            for final in (resolved, resolved | {"reviewed_head": BASE}):
                responses = [
                    {
                        "data": {
                            "addPullRequestReviewThreadReply": {
                                "comment": {"id": "reply"}
                            }
                        }
                    },
                    {
                        "data": {
                            "resolveReviewThread": {"thread": {"id": self.args.thread}}
                        }
                    },
                ]
                with (
                    patch.object(
                        MODULE,
                        "collect",
                        side_effect=[snapshot, after_reply, after_reply, final],
                    ),
                    patch.object(
                        MODULE, "read_json", side_effect=responses
                    ) as transport,
                ):
                    result = MODULE.execute(self.root, self.args, snapshot)
                    self.assertEqual(transport.call_count, 2)
                    self.assertFalse(result["acceptance_claims_proven"])
                    self.assertEqual(
                        result["status"], "pass" if final is resolved else "blocked"
                    )
                    if final is not resolved:
                        self.assertEqual(
                            result["mutation_outcome"],
                            "resolution_requested_outcome_unknown",
                        )

    def test_mutation_transport_and_readback_failures_retain_outcome(self) -> None:
        snapshot, after_reply, _resolved = self.mutation_snapshots()
        reply_result = {
            "data": {"addPullRequestReviewThreadReply": {"comment": {"id": "reply"}}}
        }
        with tempfile.TemporaryDirectory() as temporary:
            self.args.receipt = Path(temporary) / "receipt.json"
            _fixture_resource(self.args.receipt).write_text(
                json.dumps(
                    {"checked_at": datetime.now(UTC).isoformat(), "evidence": snapshot}
                )
            )
            cases = [
                (
                    [snapshot],
                    [OSError("lost reply response")],
                    "reply_requested_outcome_unknown",
                ),
                (
                    [snapshot, OSError("reply readback failed")],
                    [reply_result],
                    "reply_requested_outcome_unknown",
                ),
                (
                    [snapshot, after_reply, after_reply],
                    [reply_result, OSError("lost resolution response")],
                    "resolution_requested_outcome_unknown",
                ),
                (
                    [
                        snapshot,
                        after_reply,
                        after_reply,
                        OSError("final proof unavailable"),
                    ],
                    [reply_result, {}],
                    "resolution_requested_outcome_unknown",
                ),
                ([snapshot, after_reply, snapshot], [reply_result], "reply_verified"),
            ]
            for reads, writes, expected in cases:
                with (
                    self.subTest(expected=expected, reads=reads),
                    patch.object(MODULE, "collect", side_effect=reads),
                    patch.object(MODULE, "read_json", side_effect=writes),
                ):
                    result = MODULE.execute(self.root, self.args, snapshot)
                    self.assertEqual(
                        (result["status"], result["mutation_outcome"]),
                        ("blocked", expected),
                    )
                    self.assertFalse(result["acceptance_claims_proven"])

    def test_malformed_receipts_never_mutate(self) -> None:
        snapshot, _, _ = self.mutation_snapshots()
        envelopes = [
            "not JSON",
            "[]",
            "{}",
            '{"checked_at":1}',
            '{"checked_at":"not a timestamp"}',
            json.dumps({"checked_at": datetime.now(UTC).isoformat(), "evidence": None}),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            self.args.receipt = Path(temporary) / "receipt.json"
            for envelope in envelopes:
                _fixture_resource(self.args.receipt).write_text(envelope)
                with (
                    self.subTest(envelope=envelope),
                    patch.object(MODULE, "read_json") as mutation,
                    self.assertRaises((ValueError, TypeError)),
                ):
                    MODULE.execute(self.root, self.args, snapshot)
                mutation.assert_not_called()

    def test_existing_reply_is_not_duplicated_and_unverified_replies_cannot_resolve(
        self,
    ) -> None:
        snapshot, after_reply, resolved = self.mutation_snapshots()
        with tempfile.TemporaryDirectory() as temporary:
            self.args.receipt = Path(temporary) / "receipt.json"
            _fixture_resource(self.args.receipt).write_text(
                json.dumps(
                    {
                        "checked_at": datetime.now(UTC).isoformat(),
                        "evidence": after_reply,
                    }
                )
            )
            with (
                patch.object(
                    MODULE, "collect", side_effect=[after_reply, after_reply, resolved]
                ),
                patch.object(MODULE, "read_json", return_value={}) as transport,
            ):
                self.assertEqual(
                    MODULE.execute(self.root, self.args, after_reply)["status"], "pass"
                )
                self.assertEqual(transport.call_count, 1)
                self.assertIn(
                    "query=" + MODULE.RESOLVE_QUERY, transport.call_args.args[1]
                )
            _fixture_resource(self.args.receipt).write_text(
                json.dumps(
                    {"checked_at": datetime.now(UTC).isoformat(), "evidence": snapshot}
                )
            )
            for field, value in (
                ("id", "wrong"),
                ("body", "wrong"),
                ("author", {"login": "other"}),
            ):
                changed = copy.deepcopy(after_reply)
                changed["thread"]["comments"]["nodes"][-1][field] = value
                with (
                    patch.object(MODULE, "collect", side_effect=[snapshot, changed]),
                    patch.object(
                        MODULE,
                        "read_json",
                        return_value={
                            "data": {
                                "addPullRequestReviewThreadReply": {
                                    "comment": {"id": "reply"}
                                }
                            }
                        },
                    ) as transport,
                ):
                    result = MODULE.execute(self.root, self.args, snapshot)
                    self.assertEqual(result["status"], "blocked")
                    self.assertEqual(transport.call_count, 1)

    def test_matching_missing_or_non_string_reply_ids_cannot_resolve(self) -> None:
        snapshot, after_reply, _resolved = self.mutation_snapshots()
        with tempfile.TemporaryDirectory() as temporary:
            self.args.receipt = Path(temporary) / "receipt.json"
            _fixture_resource(self.args.receipt).write_text(
                json.dumps(
                    {"checked_at": datetime.now(UTC).isoformat(), "evidence": snapshot}
                )
            )
            for identifier in (None, "", 0, False, [], {}):
                changed = copy.deepcopy(after_reply)
                changed["thread"]["comments"]["nodes"][-1]["id"] = identifier
                response = {
                    "data": {
                        "addPullRequestReviewThreadReply": {
                            "comment": {"id": identifier}
                        }
                    }
                }
                with (
                    self.subTest(identifier=identifier),
                    patch.object(MODULE, "collect", side_effect=[snapshot, changed]),
                    patch.object(
                        MODULE, "read_json", return_value=response
                    ) as transport,
                ):
                    result = MODULE.execute(self.root, self.args, snapshot)
                    self.assertEqual(result["status"], "blocked")
                    self.assertEqual(
                        result["mutation_outcome"], "reply_requested_outcome_unknown"
                    )
                    self.assertFalse(result["acceptance_claims_proven"])
                    self.assertEqual(transport.call_count, 1)

    def test_existing_malformed_reply_identity_blocks_before_mutation(self) -> None:
        _snapshot, after_reply, _resolved = self.mutation_snapshots()
        with tempfile.TemporaryDirectory() as temporary:
            self.args.receipt = Path(temporary) / "receipt.json"
            for identifier in (None, "", 0, False, [], {}):
                changed = copy.deepcopy(after_reply)
                changed["thread"]["comments"]["nodes"][-1]["id"] = identifier
                _fixture_resource(self.args.receipt).write_text(
                    json.dumps(
                        {
                            "checked_at": datetime.now(UTC).isoformat(),
                            "evidence": changed,
                        }
                    )
                )
                with (
                    self.subTest(identifier=identifier),
                    patch.object(MODULE, "collect", return_value=changed),
                    patch.object(MODULE, "read_json") as mutation,
                    self.assertRaisesRegex(
                        ValueError, "existing evidence reply identity"
                    ),
                ):
                    MODULE.execute(self.root, self.args, changed)
                mutation.assert_not_called()

    def test_duplicate_replies_block_before_mutation_and_during_readback(self) -> None:
        snapshot, after_reply, _resolved = self.mutation_snapshots()
        duplicates = copy.deepcopy(after_reply)
        duplicates["thread"]["comments"]["nodes"].append(
            {"id": "duplicate", "body": "fixed", "author": {"login": "owner"}}
        )
        with tempfile.TemporaryDirectory() as temporary:
            self.args.receipt = Path(temporary) / "receipt.json"
            _fixture_resource(self.args.receipt).write_text(
                json.dumps(
                    {
                        "checked_at": datetime.now(UTC).isoformat(),
                        "evidence": duplicates,
                    }
                )
            )
            with (
                patch.object(MODULE, "collect", return_value=duplicates),
                patch.object(MODULE, "read_json") as mutation,
                self.assertRaisesRegex(
                    ValueError, "multiple matching evidence replies"
                ),
            ):
                MODULE.execute(self.root, self.args, duplicates)
            mutation.assert_not_called()
            _fixture_resource(self.args.receipt).write_text(
                json.dumps(
                    {"checked_at": datetime.now(UTC).isoformat(), "evidence": snapshot}
                )
            )
            with (
                patch.object(MODULE, "collect", side_effect=[snapshot, duplicates]),
                patch.object(
                    MODULE,
                    "read_json",
                    return_value={
                        "data": {
                            "addPullRequestReviewThreadReply": {
                                "comment": {"id": "reply"}
                            }
                        }
                    },
                ) as mutation,
            ):
                result = MODULE.execute(self.root, self.args, snapshot)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(
                    result["mutation_outcome"], "reply_requested_outcome_unknown"
                )
                self.assertFalse(result["acceptance_claims_proven"])
                self.assertEqual(mutation.call_count, 1)
                self.assertIn("query=" + MODULE.REPLY_QUERY, mutation.call_args.args[1])

    def cli_args(self, receipt: Path, mode: str) -> list[str]:
        return [
            "prog",
            "--repo-root",
            str(self.root),
            "--repo",
            "owner/repo",
            "--pr",
            "99",
            "--thread",
            "PRRT_example",
            "--run",
            "7",
            "--source-comment",
            "PRRC_example",
            "--source-sha256",
            "0" * 64,
            "--evidence-only",
            "--receipt",
            str(receipt),
            mode,
        ]

    def test_cli_rejects_unbounded_targets_before_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            for flag, value in (
                ("--repo", "bad"),
                ("--thread", "bad"),
                ("--source-comment", "bad"),
                ("--source-sha256", "bad"),
                ("--base", "develop"),
                ("--pr", "0"),
                ("--run", "-1"),
            ):
                output = io.StringIO()
                with (
                    self.subTest(flag=flag),
                    patch(
                        "sys.argv", self.cli_args(receipt, "--dry-run") + [flag, value]
                    ),
                    patch.object(MODULE, "collect") as collect,
                    redirect_stdout(output),
                ):
                    self.assertEqual(MODULE.main(), 2)
                    self.assertEqual(json.loads(output.getvalue())["status"], "blocked")
                    collect.assert_not_called()
                self.assertFalse(receipt.exists())

    def test_cli_receipt_inside_accepted_tree_is_rejected_before_collection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            accepted = Path(temporary) / "accepted"
            _fixture_resource(accepted).mkdir()
            alias = Path(temporary) / "alias"
            alias.symlink_to(accepted, target_is_directory=True)
            for receipt in (accepted / "receipt.json", alias / "receipt.json"):
                output = io.StringIO()
                with (
                    self.subTest(receipt=receipt),
                    patch.object(self, "root", accepted),
                    patch("sys.argv", self.cli_args(receipt, "--write-receipt")),
                    patch.object(MODULE, "collect", return_value={}) as collect,
                    redirect_stdout(output),
                ):
                    self.assertEqual(MODULE.main(), 2)
                    self.assertEqual(json.loads(output.getvalue())["status"], "blocked")
                    collect.assert_not_called()
                self.assertFalse(receipt.exists())
            self.assertEqual(list(_fixture_resource(accepted).iterdir()), [])

    def test_cli_dry_run_and_real_receipt_producer_consumer_round_trip(self) -> None:
        snapshot, after_reply, resolved = self.mutation_snapshots()
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            with (
                patch("sys.argv", self.cli_args(receipt, "--dry-run")),
                patch.object(MODULE, "collect", return_value=snapshot),
                patch.object(MODULE, "read_json") as mutation,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(MODULE.main(), 0)
                mutation.assert_not_called()
            self.assertFalse(receipt.exists())
            with (
                patch("sys.argv", self.cli_args(receipt, "--write-receipt")),
                patch.object(MODULE, "collect", return_value=snapshot),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(MODULE.main(), 0)
            envelope = json.loads(_fixture_resource(receipt).read_text())
            self.assertEqual(envelope["evidence"], snapshot)
            self.assertEqual(envelope["status"], "pass")
            self.assertIsNotNone(datetime.fromisoformat(envelope["checked_at"]).tzinfo)
            responses = [
                {
                    "data": {
                        "addPullRequestReviewThreadReply": {"comment": {"id": "reply"}}
                    }
                },
                {},
            ]
            output = io.StringIO()
            with (
                patch("sys.argv", self.cli_args(receipt, "--execute")),
                patch.object(
                    MODULE,
                    "collect",
                    side_effect=[
                        snapshot,
                        snapshot,
                        after_reply,
                        after_reply,
                        resolved,
                    ],
                ),
                patch.object(MODULE, "read_json", side_effect=responses) as mutation,
                redirect_stdout(output),
            ):
                self.assertEqual(MODULE.main(), 0)
                self.assertEqual(mutation.call_count, 2)
                self.assertEqual(
                    json.loads(output.getvalue())["mutation_outcome"],
                    "resolution_verified",
                )
            _fixture_resource(receipt).write_text("[]")
            output = io.StringIO()
            with (
                patch("sys.argv", self.cli_args(receipt, "--execute")),
                patch.object(MODULE, "collect", return_value=snapshot),
                patch.object(MODULE, "read_json") as mutation,
                redirect_stdout(output),
            ):
                self.assertEqual(MODULE.main(), 2)
                self.assertEqual(json.loads(output.getvalue())["status"], "blocked")
                mutation.assert_not_called()

    def test_later_substantive_comments_and_wrong_workflow_lookup_reject(self) -> None:
        identity = {
            "reviewed_head": HEAD,
            "original_base": BASE,
            "merge": MERGE,
            "tree": TREE,
        }
        thread = copy.deepcopy(self.thread)
        thread["comments"]["nodes"].append(
            {
                "body": "A live correctness finding remains",
                "author": {"login": "coderabbitai"},
            }
        )
        with (
            patch.object(MODULE, "check_identity", return_value=identity),
            patch.object(MODULE, "command_evidence", return_value={"steps": []}),
            patch.object(MODULE, "validate_run"),
            patch.object(MODULE, "read_thread", return_value=thread),
            patch.object(
                MODULE,
                "read_json",
                side_effect=[self.pr, self.run, {"id": 1, "login": "owner"}],
            ),
            self.assertRaisesRegex(ValueError, "later thread comments"),
        ):
            MODULE.collect(self.root, self.args)
        run = self.run | {
            "workflow_id": 4,
            "path": ".github/workflows/validate.yml",
            "pull_requests": [{"number": 99}],
        }
        for workflow in (
            {},
            {"id": 5, "path": run["path"]},
            {"id": 4, "path": "other.yml"},
        ):
            with (
                patch.object(MODULE, "read_json", return_value=workflow),
                self.assertRaises(ValueError),
            ):
                MODULE.validate_run(self.root, self.args, run, HEAD)


if __name__ == "__main__":
    unittest.main()
