"""Inspection receipt is not review clearance or authority for other mutations."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import unittest
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
    "request_helper", Path(__file__).resolve().parents[1] / "pr-review-request.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
GATE = MODULE.GATE
HEAD = "a" * 40


def inspection_receipt() -> dict:
    return {
        "authority": GATE.review_inspection_authority(),
        "repo": {"base_branch": "main", "remote_base_sha": "b" * 40},
    }


class InspectionTests(unittest.TestCase):
    def reinspection_source(
        self, root: Path, args: argparse.Namespace, head: str, entries: list[dict]
    ) -> dict:
        return MODULE.reinspection_source(root, args, head, entries, ("main", "b" * 40))

    def test_authenticated_actor_requires_a_positive_integer_id_and_login(self) -> None:
        actor = {"id": 93, "login": "jscraik"}
        with patch.object(GATE, "run_command") as command:
            command.return_value = subprocess.CompletedProcess(
                [], 0, json.dumps(actor), ""
            )
            self.assertEqual(MODULE.authenticated_actor(Path.cwd()), actor)
            command.assert_called_once_with(["gh", "api", "user"], Path.cwd())
            for invalid in (
                None,
                [],
                {},
                {"id": True, "login": "jscraik"},
                {"id": "93", "login": "jscraik"},
                {"id": 0, "login": "jscraik"},
                {"id": -1, "login": "jscraik"},
                {"id": 93},
                {"id": 93, "login": ""},
                {"id": 93, "login": 7},
            ):
                command.return_value = subprocess.CompletedProcess(
                    [], 0, json.dumps(invalid), ""
                )
                with (
                    self.subTest(actor=invalid),
                    self.assertRaisesRegex(ValueError, "authenticated request actor"),
                ):
                    MODULE.authenticated_actor(Path.cwd())

    def test_quota_retry_binds_authenticated_failure_to_exact_head_request(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        args = argparse.Namespace(
            repo="jscraik/configs",
            pr=7,
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            retry_source=url + "#issuecomment-10",
        )
        failure = {
            "html_url": args.retry_source,
            "body": "quota exhausted",
            "created_at": "2026-10-17T14:22:57Z",
            "updated_at": "2026-10-17T14:22:57Z",
            "user": {"login": "chatgpt-codex-connector[bot]", "type": "Bot", "id": 8},
        }
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("codex", HEAD, False),
            "created_at": "2026-10-17T14:22:50Z",
            "updated_at": "2026-10-17T14:22:50Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        pr = {"state": "OPEN", "headRefOid": HEAD, "url": url, "reviews": []}
        with (
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess(
                    [], 0, '{"id":93,"login":"jscraik"}', ""
                ),
            ),
            patch.object(GATE, "gh_pr", return_value=(pr, None)) as hosted,
        ):
            self.assertEqual(
                MODULE.quota_retry_source(Path.cwd(), args, HEAD, [prior, failure]),
                failure,
            )
            tied_failure = {
                **failure,
                "created_at": prior["created_at"],
                "updated_at": prior["created_at"],
            }
            self.assertEqual(
                MODULE.quota_retry_source(
                    Path.cwd(), args, HEAD, [prior, tied_failure]
                ),
                tied_failure,
            )
            older_url = url + "#issuecomment-8"
            with self.assertRaisesRegex(ValueError, "must follow"):
                MODULE.quota_retry_source(
                    Path.cwd(),
                    argparse.Namespace(**vars(args) | {"retry_source": older_url}),
                    HEAD,
                    [prior, {**tied_failure, "html_url": older_url}],
                )
            for intervening in (
                {"body": "@codex review", "user": {"id": 94, "login": "other"}},
                {"body": "Completed review", "user": failure["user"]},
                {"body": "quota exhausted", "user": failure["user"]},
            ):
                event = {
                    **intervening,
                    "created_at": "2026-10-17T14:22:53Z",
                    "updated_at": "2026-10-17T14:22:53Z",
                }
                with (
                    self.subTest(event=event),
                    self.assertRaisesRegex(ValueError, "another Codex event"),
                ):
                    MODULE.quota_retry_source(
                        Path.cwd(), args, HEAD, [prior, event, failure]
                    )
            with self.assertRaisesRegex(ValueError, "chronology"):
                MODULE.quota_retry_source(
                    Path.cwd(), args, HEAD, [prior, {"body": "@codex review"}, failure]
                )
            completed = {
                "author": {"login": "chatgpt-codex-connector"},
                "commit_id": HEAD,
                "submittedAt": "2026-10-17T14:22:53Z",
            }
            for submitted in (
                "2026-10-17T14:20:00Z",
                completed["submittedAt"],
                "2026-10-17T14:23:00Z",
            ):
                hosted.return_value = (
                    {**pr, "reviews": [{**completed, "submittedAt": submitted}]},
                    None,
                )
                with (
                    self.subTest(submitted=submitted),
                    self.assertRaisesRegex(ValueError, "current-head Codex review"),
                ):
                    MODULE.quota_retry_source(Path.cwd(), args, HEAD, [prior, failure])
            hosted.return_value = (
                {
                    **pr,
                    "reviews": [
                        {
                            **completed,
                            "commit_id": "b" * 40,
                            "submittedAt": "2026-10-17T14:23:00Z",
                        }
                    ],
                },
                None,
            )
            self.assertEqual(
                MODULE.quota_retry_source(Path.cwd(), args, HEAD, [prior, failure]),
                failure,
            )
            hosted.return_value = (
                {**pr, "reviews": [{**completed, "commit_id": None}]},
                None,
            )
            with self.assertRaisesRegex(ValueError, "commit identity"):
                MODULE.quota_retry_source(Path.cwd(), args, HEAD, [prior, failure])
            hosted.return_value = (pr, None)
            for late_event in (
                {"body": "@codex review", "user": {"id": 94, "login": "other"}},
                {"body": f"No findings for {HEAD}.", "user": failure["user"]},
                {"body": "Review completed with one finding", "user": failure["user"]},
            ):
                event = {
                    **late_event,
                    "created_at": "2026-10-17T14:23:00Z",
                    "updated_at": "2026-10-17T14:23:00Z",
                }
                with (
                    self.subTest(event=event),
                    self.assertRaisesRegex(ValueError, "another Codex event"),
                ):
                    MODULE.quota_retry_source(
                        Path.cwd(), args, HEAD, [prior, failure, event]
                    )
            edited_completion = {
                "html_url": url + "#issuecomment-8",
                "body": f"No findings for {HEAD}.",
                "created_at": "2026-10-17T14:20:00Z",
                "updated_at": "2026-10-17T14:23:00Z",
                "user": failure["user"],
            }
            with self.assertRaisesRegex(ValueError, "another Codex event"):
                MODULE.quota_retry_source(
                    Path.cwd(), args, HEAD, [edited_completion, prior, failure]
                )
            retry = {
                "html_url": url + "#issuecomment-11",
                "body": MODULE.quota_retry_body(HEAD, args.retry_source),
                "created_at": "2026-10-17T14:23:00Z",
                "updated_at": "2026-10-17T14:23:00Z",
                "user": prior["user"],
            }
            self.assertEqual(
                MODULE.quota_retry_source(
                    Path.cwd(), args, HEAD, [prior, failure, retry]
                ),
                failure,
            )
            for updated_at in (
                None,
                "invalid",
                "2026-10-17T14:22:59Z",
                "2026-10-17T14:23:01Z",
            ):
                with (
                    self.subTest(updated_at=updated_at),
                    self.assertRaisesRegex(ValueError, "another Codex event"),
                ):
                    MODULE.quota_retry_source(
                        Path.cwd(),
                        args,
                        HEAD,
                        [prior, failure, {**retry, "updated_at": updated_at}],
                    )
            with self.assertRaisesRegex(ValueError, "another Codex event"):
                MODULE.quota_retry_source(
                    Path.cwd(),
                    args,
                    HEAD,
                    [prior, failure, {**retry, "user": {"id": 94, "login": "other"}}],
                )
            for changed in (
                {**failure, "user": {"login": "other[bot]", "type": "Bot", "id": 8}},
                {
                    **failure,
                    "user": {
                        "login": "chatgpt-codex-connector[bot]",
                        "type": "User",
                        "id": 8,
                    },
                },
                {
                    **failure,
                    "user": {
                        "login": "chatgpt-codex-connector[bot]",
                        "type": "Bot",
                        "id": True,
                    },
                },
                {
                    **failure,
                    "body": "quota exhausted. Also fix the missing authorization",
                },
                {**failure, "body": f"No findings for {HEAD}."},
                {**failure, "created_at": "2026-10-17T14:22:49Z"},
                {**failure, "updated_at": "invalid"},
                {**failure, "updated_at": prior["created_at"]},
                {**failure, "html_url": url.replace("/7", "/8") + "#issuecomment-10"},
            ):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    MODULE.quota_retry_source(Path.cwd(), args, HEAD, [prior, changed])
            for entries in (
                [failure],
                [prior, failure, failure],
                [{**prior, "body": prior["body"].replace(HEAD, "b" * 40)}, failure],
                [{**prior, "body": []}, failure],
                [{**prior, "user": {"id": 94, "login": "other"}}, failure],
                [{**prior, "user": {"id": 93, "login": "other"}}, failure],
                [{**prior, "user": {"id": "93", "login": "jscraik"}}, failure],
                [
                    {**prior, "html_url": url.replace("/7", "/8") + "#issuecomment-9"},
                    failure,
                ],
                [{**prior, "html_url": prior["html_url"] + "bad"}, failure],
                [{**prior, "updated_at": "2026-10-17T14:23:00Z"}, failure],
                [{**prior, "created_at": failure["created_at"]}, failure],
            ):
                with self.subTest(entries=entries), self.assertRaises(ValueError):
                    MODULE.quota_retry_source(Path.cwd(), args, HEAD, entries)
            for changed in (
                {**pr, "state": "MERGED"},
                {**pr, "headRefOid": "b" * 40},
                {**pr, "url": "https://github.com/other/repo/pull/7"},
            ):
                hosted.return_value = (changed, None)
                with self.subTest(pr=changed), self.assertRaises(ValueError):
                    MODULE.quota_retry_source(Path.cwd(), args, HEAD, [prior, failure])
        for changes in (
            {"reviewer": "coderabbitai"},
            {"clarify": True},
            {"clarify_source": args.retry_source},
            {"clarify_source": ""},
            {"reinspect_source": ""},
            {"retry_source": ""},
            {"retry_unavailable_source": ""},
            {"retry_unavailable_source": args.retry_source},
            {"reinspect_source": args.retry_source},
            {"retry_source": args.retry_source + "bad"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                MODULE.quota_retry_source(
                    Path.cwd(),
                    argparse.Namespace(**vars(args) | changes),
                    HEAD,
                    [prior, failure],
                )

    def test_quota_retry_tracks_edited_pending_and_completed_provider_summaries(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        args = argparse.Namespace(
            repo="jscraik/configs",
            pr=7,
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            retry_source=url + "#issuecomment-10",
        )
        actor = {"id": 93, "login": "jscraik"}
        bot = {"login": "chatgpt-codex-connector[bot]", "type": "Bot", "id": 8}
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("codex", HEAD, False),
            "created_at": "2026-10-17T14:22:50Z",
            "updated_at": "2026-10-17T14:22:50Z",
            "user": actor,
        }
        failure = {
            "html_url": args.retry_source,
            "body": "quota exhausted",
            "user": bot,
            "created_at": "2026-10-17T14:22:57Z",
            "updated_at": "2026-10-17T14:22:57Z",
        }
        state = {
            "code_review": {
                "commit_sha": HEAD,
                "has_any_findings": None,
                "has_unresolved_findings": None,
                "status": "running",
            },
            "security_review": {
                "commit_sha": None,
                "has_any_findings": None,
                "has_unresolved_findings": None,
                "status": None,
            },
        }
        body = (
            "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "
            + json.dumps(state)
            + " -->\n\n## Codex Review Summary\n"
        )
        summary = {
            "html_url": url + "#issuecomment-8",
            "body": body,
            "user": bot,
            "created_at": "2026-10-17T14:20:00Z",
            "updated_at": "2026-10-17T14:22:53Z",
        }
        pr = {"state": "OPEN", "headRefOid": HEAD, "url": url, "reviews": []}
        with (
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, json.dumps(actor), ""),
            ) as command,
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
        ):
            self.assertEqual(
                MODULE.quota_retry_source(
                    Path.cwd(), args, HEAD, [summary, prior, failure]
                ),
                failure,
            )
            running_security = {**state, "security_review": state["code_review"]}
            pending_both = body.replace(json.dumps(state), json.dumps(running_security))
            self.assertEqual(
                MODULE.quota_retry_source(
                    Path.cwd(),
                    args,
                    HEAD,
                    [{**summary, "body": pending_both}, prior, failure],
                ),
                failure,
            )
            for changed in (
                *(
                    {**summary, "body": body + suffix}
                    for suffix in (
                        "A finding remains.",
                        "Review completed.",
                        "Unknown provider content.",
                        "<!-- extra -->",
                    )
                ),
                {
                    **summary,
                    "body": body.replace(
                        '"security_review": {', '"security_review": {"extra": true,', 1
                    ),
                },
                {
                    **summary,
                    "body": body.replace(
                        '"security_review": {"commit_sha": null, "has_any_findings": null',
                        '"security_review": {"commit_sha": null, "has_any_findings": true',
                    ),
                },
                {**summary, "updated_at": "2026-10-17T14:23:00Z"},
                {**summary, "updated_at": failure["created_at"]},
                {**summary, "body": body.replace('"running"', '"completed"')},
                {
                    **summary,
                    "body": body.replace(
                        '"code_review":', '"code_review": {}, "code_review":', 1
                    ),
                },
                {**summary, "body": body.replace(HEAD, "b" * 40)},
                {**summary, "updated_at": "invalid"},
                {**summary, "updated_at": "2026-10-17T14:19:00Z"},
            ):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    MODULE.quota_retry_source(
                        Path.cwd(), args, HEAD, [changed, prior, failure]
                    )
            args.repo_root, args.receipt, args.dry_run = (
                Path.cwd(),
                Path("receipt.json"),
                False,
            )
            retry = {
                "html_url": url + "#issuecomment-11",
                "body": MODULE.quota_retry_body(HEAD, args.retry_source),
                "created_at": "2026-10-17T14:22:58Z",
                "updated_at": "2026-10-17T14:22:58Z",
                "user": actor,
            }
            summary = {**summary, "updated_at": "2026-10-17T14:23:00Z"}
            entries = [summary, prior, failure, retry]
            with (
                patch.object(GATE, "resolve_root", return_value=Path.cwd()),
                patch.object(
                    GATE,
                    "current_worktree",
                    return_value=("topic", HEAD, "main", ".git", ".git"),
                ),
                patch.object(
                    GATE,
                    "validate_receipt",
                    return_value=(
                        {"authority": GATE.review_inspection_authority()},
                        None,
                    ),
                ),
                patch.object(
                    GATE, "issue_comments", return_value=(entries, None)
                ) as comments,
            ):
                result = MODULE.execute(args)
                self.assertTrue(result["reused"])
                self.assertEqual(result["url"], retry["html_url"])
                self.assertFalse(result["acceptance_claims_proven"])
                for replacement in (
                    None,
                    {**retry, "updated_at": summary["updated_at"]},
                    {**retry, "user": {"id": 94, "login": "other"}},
                    {**retry, "html_url": retry["html_url"].replace("/7#", "/8#")},
                    {**retry, "body": retry["body"] + " extra"},
                    {
                        **retry,
                        "created_at": prior["created_at"],
                        "updated_at": prior["created_at"],
                    },
                ):
                    with (
                        self.subTest(replacement=replacement),
                        self.assertRaises(ValueError),
                    ):
                        MODULE.quota_retry_source(
                            Path.cwd(),
                            args,
                            HEAD,
                            [summary, prior, failure]
                            + ([replacement] if replacement else []),
                        )
                with self.assertRaises(ValueError):
                    MODULE.quota_retry_source(
                        Path.cwd(),
                        args,
                        HEAD,
                        [
                            {**summary, "body": body + "A finding remains."},
                            prior,
                            failure,
                            retry,
                        ],
                    )
                comments.side_effect = [
                    (entries, None),
                    ([summary, prior, failure], None),
                ]
                with self.assertRaises(ValueError):
                    MODULE.execute(args)
                self.assertTrue(
                    all(
                        call.args[0] == ["gh", "api", "user"]
                        for call in command.call_args_list
                    )
                )

    def test_explicit_empty_retry_source_cannot_fall_back_to_normal_request(
        self,
    ) -> None:
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            retry_source="",
            dry_run=False,
        )
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ),
            patch.object(GATE, "issue_comments", return_value=([], None)),
            patch.object(GATE, "run_command") as command,
        ):
            with self.assertRaisesRegex(ValueError, "exact-PR Codex source"):
                MODULE.execute(args)
            command.assert_not_called()

    def test_quota_retry_rechecks_failure_and_deduplicates_post(self) -> None:
        url = "https://github.com/jscraik/configs/pull/7#issuecomment-11"
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            retry_source=url.replace("-11", "-10"),
            dry_run=True,
        )
        failure = {"html_url": args.retry_source, "body": "quota exhausted"}
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ),
            patch.object(
                GATE, "issue_comments", return_value=([failure], None)
            ) as comments,
            patch.object(MODULE, "quota_retry_source", return_value=failure) as source,
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, url, ""),
            ) as command,
            patch.object(
                GATE,
                "gh_pr",
                return_value=({"state": "OPEN", "headRefOid": HEAD}, None),
            ),
        ):
            body = MODULE.execute(args)["body"]
            self.assertIn(args.retry_source, body)
            self.assertNotEqual(body, MODULE.request_body("codex", HEAD, False))
            command.assert_not_called()
            args.dry_run = False
            source.side_effect = [failure, {**failure, "body": "Changed"}]
            with self.assertRaisesRegex(ValueError, "source changed"):
                MODULE.execute(args)
            command.assert_not_called()
            source.side_effect = None
            source.reset_mock()
            initial_entries = [failure]
            refreshed_entries = [failure, {"body": "Unrelated discussion"}]
            comments.side_effect = [
                (initial_entries, None),
                (refreshed_entries, None),
                ([*refreshed_entries, {"html_url": url, "body": body}], None),
            ]
            self.assertFalse(MODULE.execute(args)["acceptance_claims_proven"])
            self.assertEqual(source.call_count, 2)
            self.assertIs(source.call_args_list[0].args[3], initial_entries)
            self.assertIs(source.call_args_list[1].args[3], refreshed_entries)
            command.assert_called_once()
            comments.side_effect = None
            comments.return_value = (
                [
                    failure,
                    {
                        "html_url": url,
                        "body": body,
                        "user": {"id": 93, "login": "jscraik"},
                        "created_at": "2026-10-19T12:00:00Z",
                        "updated_at": "2026-10-19T12:00:00Z",
                    },
                ],
                None,
            )
            command.return_value = subprocess.CompletedProcess(
                [], 0, '{"id":93,"login":"jscraik"}', ""
            )
            with patch.object(
                GATE,
                "gh_pr",
                return_value=(
                    {"state": "OPEN", "headRefOid": HEAD, "url": url.split("#")[0]},
                    None,
                ),
            ):
                self.assertTrue(MODULE.execute(args)["reused"])

    def test_reinspection_requires_a_later_authenticated_outstanding_concern(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        args = argparse.Namespace(
            repo="jscraik/configs",
            pr=7,
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=url + "#issuecomment-10",
        )
        concern = {
            "html_url": args.reinspect_source,
            "body": "Inspection incomplete for " + HEAD,
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:16:00Z",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        pr = {
            "state": "OPEN",
            "headRefOid": HEAD,
            "baseRefName": "main",
            "baseRefOid": "b" * 40,
            "url": url,
            "reviews": [],
        }
        with (
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess(
                    [], 0, '{"id":93,"login":"jscraik"}', ""
                ),
            ) as command,
            patch.object(GATE, "gh_pr", return_value=(pr, None)) as hosted,
            patch.object(
                GATE,
                "reviews_lane",
                return_value={"details": {"outstanding_bot_concerns": ["CodeRabbit"]}},
            ) as lane,
            patch.object(GATE, "_codex_completion_snapshot", return_value=(True, None)),
            patch.object(GATE, "review_comments", return_value=([], None)) as inline,
        ):
            self.assertEqual(
                self.reinspection_source(Path.cwd(), args, HEAD, [prior, concern]),
                concern,
            )
            legacy = {**prior, "body": prior["body"].replace("\n\n", " ", 1)}
            self.assertEqual(
                self.reinspection_source(Path.cwd(), args, HEAD, [legacy, concern]),
                concern,
            )
            old = {**prior, "body": MODULE.historical_full_request(prior["body"])}
            self.assertEqual(
                self.reinspection_source(Path.cwd(), args, HEAD, [old, concern]),
                concern,
            )
            for request in (prior, legacy, old):
                for updated_at in (
                    None,
                    "invalid",
                    "2026-10-16T21:29:00Z",
                    "2026-10-16T22:17:00Z",
                ):
                    with (
                        self.subTest(request=request["body"], updated_at=updated_at),
                        self.assertRaisesRegex(
                            ValueError, "must follow an authenticated"
                        ),
                    ):
                        self.reinspection_source(
                            Path.cwd(),
                            args,
                            HEAD,
                            [{**request, "updated_at": updated_at}, concern],
                        )
            with self.assertRaisesRegex(ValueError, "must follow an authenticated"):
                self.reinspection_source(
                    Path.cwd(),
                    args,
                    HEAD,
                    [{**legacy, "body": legacy["body"] + " extra"}, concern],
                )
            for earlier in ("2026-10-16T21:29:00Z", prior["created_at"]):
                with (
                    self.subTest(edited_old_concern=earlier),
                    self.assertRaisesRegex(ValueError, "must follow an authenticated"),
                ):
                    self.reinspection_source(
                        Path.cwd(),
                        args,
                        HEAD,
                        [legacy, {**concern, "created_at": earlier}],
                    )
            clearance = {
                **concern,
                "html_url": url + "#issuecomment-11",
                "body": f"No findings for {HEAD}.",
                "created_at": "2026-10-16T22:17:00Z",
                "updated_at": "2026-10-16T22:17:00Z",
            }
            clearance = {
                **clearance,
                "body": f"<!-- This is an auto-generated reply by CodeRabbit -->\n\n@jscraik\n\nNo findings for {HEAD}.\n\n_You are interacting with an AI system._",
            }
            tied_clearance = {
                **clearance,
                "created_at": concern["created_at"],
                "updated_at": concern["updated_at"],
            }
            self.assertEqual(
                self.reinspection_source(
                    Path.cwd(), args, HEAD, [prior, tied_clearance, concern]
                ),
                concern,
            )
            with self.assertRaisesRegex(ValueError, "already been cleared"):
                self.reinspection_source(
                    Path.cwd(), args, HEAD, [prior, concern, tied_clearance]
                )
            later = {
                **concern,
                "html_url": url + "#issuecomment-12",
                "created_at": "2026-10-16T22:18:00Z",
                "updated_at": "2026-10-16T22:18:00Z",
            }
            with self.assertRaisesRegex(ValueError, "already been cleared"):
                self.reinspection_source(
                    Path.cwd(), args, HEAD, [prior, concern, clearance, later]
                )
            formal = {
                **clearance,
                "state": "COMMENTED",
                "commit_id": HEAD,
                "submitted_at": clearance["created_at"],
            }
            hosted.return_value = ({**pr, "reviews": [formal]}, None)
            with self.assertRaisesRegex(ValueError, "already been cleared"):
                self.reinspection_source(
                    Path.cwd(), args, HEAD, [prior, concern, later]
                )
            hosted.return_value = (pr, None)
            inline.return_value = ([{**clearance, "commit_id": HEAD}], None)
            with self.assertRaisesRegex(ValueError, "already been cleared"):
                self.reinspection_source(
                    Path.cwd(), args, HEAD, [prior, concern, later]
                )
            inline.return_value = ([], "inventory unavailable")
            with self.assertRaisesRegex(ValueError, "inventory unavailable"):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior, concern])
            inline.return_value = ([], None)
            for changed in (
                {**concern, "body": "Inspection incomplete for " + "b" * 40},
                {**concern, "body": clearance["body"]},
                {
                    **concern,
                    "user": {"login": "coderabbitai[bot]", "type": "User", "id": 8},
                },
                {**concern, "updated_at": "invalid"},
                {**concern, "updated_at": "2026-10-16T21:00:00Z"},
                {**concern, "html_url": url.replace("/7", "/8") + "#issuecomment-10"},
            ):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    self.reinspection_source(Path.cwd(), args, HEAD, [prior, changed])
            for changed in (
                [],
                [concern],
                [prior, concern, concern],
                [{**prior, "body": []}, concern],
                [{**prior, "user": {"id": 94, "login": "other"}}, concern],
                [{**prior, "user": {"id": 93, "login": "other"}}, concern],
                [{**prior, "user": {"id": "93", "login": "jscraik"}}, concern],
                [
                    {**prior, "html_url": url.replace("/7", "/8") + "#issuecomment-9"},
                    concern,
                ],
                [{**prior, "html_url": prior["html_url"] + "bad"}, concern],
                [{**prior, "created_at": concern["updated_at"]}, concern],
                [
                    {**prior, "created_at": "2026-10-16T22:17:00Z"},
                    {**concern, "updated_at": "2026-10-16T22:18:00Z"},
                ],
            ):
                with self.subTest(entries=changed), self.assertRaises(ValueError):
                    self.reinspection_source(Path.cwd(), args, HEAD, changed)
            lane.return_value = {
                "status": "pass",
                "details": {"outstanding_bot_concerns": []},
            }
            with self.assertRaisesRegex(ValueError, "no longer"):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior, concern])
            lane.return_value = {"status": "blocked", "details": {}}
            with self.assertRaises(ValueError):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior, concern])
            lane.return_value = {
                "details": {"outstanding_bot_concerns": ["CodeRabbit"]}
            }
            hosted.return_value = ({**pr, "headRefOid": "b" * 40}, None)
            with self.assertRaisesRegex(ValueError, "identity or head"):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior, concern])
            self.assertTrue(
                all(
                    call.args[0] == ["gh", "api", "user"]
                    for call in command.call_args_list
                )
            )
        for changes in (
            {"reviewer": "codex"},
            {"clarify": True},
            {"clarify_source": args.reinspect_source},
            {"retry_unavailable_source": url + "#issuecomment-12"},
            {"reinspect_source": url.replace("/7", "/8") + "#issuecomment-10"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.reinspection_source(
                    Path.cwd(),
                    argparse.Namespace(**vars(args) | changes),
                    HEAD,
                    [prior, concern],
                )

    def test_issue_reinspection_does_not_reuse_request_older_than_updated_finding(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        source = url + "#issuecomment-10"
        args = argparse.Namespace(
            repo="jscraik/configs",
            pr=7,
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=source,
        )
        concern = {
            "html_url": source,
            "body": "Inspection incomplete for " + HEAD,
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:30:00Z",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        request = {
            **prior,
            "html_url": url + "#issuecomment-11",
            "body": GATE.reinspection_request_body(HEAD, source),
            "created_at": "2026-10-16T22:18:00Z",
            "updated_at": "2026-10-16T22:18:00Z",
        }
        pr = {
            "state": "OPEN",
            "headRefOid": HEAD,
            "baseRefName": "main",
            "baseRefOid": "b" * 40,
            "url": url,
            "reviews": [],
        }
        with (
            patch.object(
                MODULE,
                "authenticated_actor",
                return_value={"id": 93, "login": "jscraik"},
            ),
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
            patch.object(
                GATE,
                "reviews_lane",
                return_value={"details": {"outstanding_bot_concerns": ["CodeRabbit"]}},
            ),
            patch.object(GATE, "_codex_completion_snapshot", return_value=(True, None)),
            patch.object(GATE, "review_comments", return_value=([], None)),
        ):
            for updated_at in ("2026-10-16T22:18:00Z", "2026-10-16T22:30:00Z"):
                with (
                    self.subTest(updated_at=updated_at),
                    self.assertRaisesRegex(ValueError, "does not follow"),
                ):
                    self.reinspection_source(
                        Path.cwd(),
                        args,
                        HEAD,
                        [prior, {**concern, "updated_at": updated_at}, request],
                    )
            current = {
                **request,
                "created_at": "2026-10-16T22:31:00Z",
                "updated_at": "2026-10-16T22:31:00Z",
            }
            self.assertEqual(
                self.reinspection_source(
                    Path.cwd(), args, HEAD, [prior, concern, current]
                ),
                concern,
            )
            for changed in (
                {**current, "user": {"id": 94, "login": "other"}},
                {**current, "updated_at": "2026-10-16T22:32:00Z"},
            ):
                with (
                    self.subTest(request=changed),
                    self.assertRaisesRegex(
                        ValueError, "not authenticated and unedited"
                    ),
                ):
                    self.reinspection_source(
                        Path.cwd(), args, HEAD, [prior, concern, changed]
                    )

    def test_reinspection_admits_only_a_later_authenticated_current_head_inline_concern(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        source = url + "#discussion_r10"
        args = argparse.Namespace(
            repo="jscraik/configs",
            pr=7,
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=source,
        )
        concern = {
            "id": 10,
            "html_url": source,
            "commit_id": HEAD,
            "original_commit_id": HEAD,
            "pull_request_url": "https://api.github.com/repos/jscraik/configs/pulls/7",
            "body": "Record the missing validation command and outcome.",
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:17:00Z",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        pr = {
            "state": "OPEN",
            "headRefOid": HEAD,
            "baseRefName": "main",
            "baseRefOid": "b" * 40,
            "url": url,
            "reviews": [],
        }
        with (
            patch.object(
                MODULE,
                "authenticated_actor",
                return_value={"id": 93, "login": "jscraik"},
            ),
            patch.object(GATE, "gh_pr", return_value=(pr, None)) as hosted,
            patch.object(
                GATE,
                "reviews_lane",
                return_value={"details": {"outstanding_bot_concerns": ["CodeRabbit"]}},
            ) as lane,
            patch.object(GATE, "_codex_completion_snapshot", return_value=(True, None)),
            patch.object(
                GATE, "review_comments", return_value=([concern], None)
            ) as inline,
        ):
            self.assertEqual(
                self.reinspection_source(Path.cwd(), args, HEAD, [prior]), concern
            )
            for changed in (
                {**concern, "id": 11},
                {**concern, "commit_id": "b" * 40},
                {**concern, "original_commit_id": "b" * 40},
                {
                    **concern,
                    "pull_request_url": "https://api.github.com/repos/jscraik/configs/pulls/8",
                },
                {
                    **concern,
                    "user": {"login": "coderabbitai[bot]", "type": "User", "id": 8},
                },
                {**concern, "user": {"login": "other[bot]", "type": "Bot", "id": 8}},
                {
                    **concern,
                    "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": True},
                },
                {**concern, "in_reply_to_id": 9},
                {**concern, "body": ""},
                {**concern, "created_at": prior["created_at"]},
                {**concern, "updated_at": "invalid"},
            ):
                inline.return_value = ([changed], None)
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    self.reinspection_source(Path.cwd(), args, HEAD, [prior])
            for inventory in ([], [concern, concern]):
                inline.return_value = (inventory, None)
                with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                    self.reinspection_source(Path.cwd(), args, HEAD, [prior])
            inline.return_value = ([concern], None)
            with self.assertRaises(ValueError):
                self.reinspection_source(Path.cwd(), args, HEAD, [])
            old_source = url + "#issuecomment-8"
            later_request = {
                **prior,
                "html_url": url + "#issuecomment-11",
                "body": GATE.reinspection_request_body(HEAD, old_source),
                "created_at": "2026-10-16T22:18:00Z",
                "updated_at": "2026-10-16T22:18:00Z",
            }
            with self.assertRaisesRegex(ValueError, "later.*request|after.*request"):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior, later_request])
            same_request = {
                **later_request,
                "html_url": url + "#issuecomment-12",
                "body": GATE.reinspection_request_body(HEAD, source),
            }
            self.assertEqual(
                self.reinspection_source(Path.cwd(), args, HEAD, [prior, same_request]),
                concern,
            )
            for updated_at in (same_request["created_at"], "2026-10-16T22:30:00Z"):
                inline.return_value = ([{**concern, "updated_at": updated_at}], None)
                with (
                    self.subTest(source_updated=updated_at),
                    self.assertRaises(ValueError),
                ):
                    self.reinspection_source(
                        Path.cwd(), args, HEAD, [prior, same_request]
                    )
            inline.return_value = ([concern], None)
            for changed in (
                {**same_request, "user": {"id": 94, "login": "other"}},
                {**same_request, "updated_at": "2026-10-16T22:19:00Z"},
            ):
                with (
                    self.subTest(ambiguous_request=changed),
                    self.assertRaises(ValueError),
                ):
                    self.reinspection_source(Path.cwd(), args, HEAD, [prior, changed])
            clearance = {
                "body": "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                f"@jscraik\n\nNo findings for {HEAD}.\n\n_You are interacting with an AI system._",
                "user": concern["user"],
                "commit_id": HEAD,
                "state": "COMMENTED",
                "submitted_at": "2026-10-16T22:18:00Z",
            }
            hosted.return_value = ({**pr, "reviews": [clearance]}, None)
            with self.assertRaisesRegex(ValueError, "already been cleared"):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior])
            hosted.return_value = (pr, None)
            inline.return_value = (
                [
                    concern,
                    {
                        **clearance,
                        "created_at": "2026-10-16T22:18:00Z",
                        "updated_at": "2026-10-16T22:18:00Z",
                    },
                ],
                None,
            )
            with self.assertRaisesRegex(ValueError, "already been cleared"):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior])
            inline.return_value = ([concern], None)
            lane.return_value = {
                "status": "pass",
                "details": {"outstanding_bot_concerns": []},
            }
            with self.assertRaises(ValueError):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior])
            lane.return_value = {
                "details": {"outstanding_bot_concerns": ["CodeRabbit"]}
            }
            hosted.return_value = ({**pr, "headRefOid": "b" * 40}, None)
            with self.assertRaises(ValueError):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior])

    def test_reinspection_honours_verified_automatic_completion_for_the_selected_source(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        base = "b" * 40
        user = {"login": "coderabbitai[bot]", "type": "Bot", "id": 8}
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        finding = {
            "id": 10,
            "html_url": url + "#discussion_r10",
            "commit_id": HEAD,
            "original_commit_id": HEAD,
            "pull_request_url": "https://api.github.com/repos/jscraik/configs/pulls/7",
            "body": "Record the missing validation command and outcome.",
            "user": user,
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:16:00Z",
        }
        later = {
            **finding,
            "id": 11,
            "html_url": url + "#discussion_r11",
            "body": "A different concern remains.",
            "created_at": "2026-10-16T22:19:00Z",
            "updated_at": "2026-10-16T22:19:00Z",
        }
        summary_body = (
            "<!-- coderabbit-ai-generated:v1 -->\n"
            "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->\n"
            "<!-- recent_review_start -->\nNo actionable comments were generated in the recent review. 🎉\n"
            "<details><summary><strong>ℹ️ Recent review info</strong></summary>\n"
            "- **Configuration used**: Repository: jscraik/configs/.coderabbit.yaml\n"
            "- **Run ID**: `4859e27c-a72c-4fe7-83e3-371e52b4364a`\n"
            f"Reviewing files that changed from the base of the PR and between {base} and {HEAD}.\n"
            "</details><!-- recent_review_end -->\n"
            "<!-- final_review_risk_start --><!-- final_review_risk_coverage:"
            + json.dumps(
                {"sourceCommitId": HEAD, "coveredCommitId": HEAD, "kind": "reviewed"}
            )
            + " --><!-- final_review_risk_end -->"
        )
        summary = {
            "id": 12,
            "html_url": url + "#issuecomment-12",
            "body": summary_body,
            "user": user,
            "created_at": "2026-10-16T22:17:00Z",
            "updated_at": "2026-10-16T22:18:00Z",
        }
        status = {
            "id": 50,
            "context": "CodeRabbit",
            "state": "success",
            "creator": user,
            "created_at": summary["updated_at"],
        }
        pr = {
            "number": 7,
            "state": "OPEN",
            "headRefOid": HEAD,
            "headRefName": "codex/test",
            "baseRefName": "main",
            "baseRefOid": base,
            "url": url,
            "reviews": [],
            "author": {"login": "jscraik"},
        }
        with (
            patch.object(
                MODULE,
                "authenticated_actor",
                return_value={"id": 93, "login": "jscraik"},
            ),
            patch.object(GATE, "gh_pr", return_value=(pr, None)) as hosted,
            patch.object(
                GATE,
                "reviews_lane",
                return_value={"details": {"outstanding_bot_concerns": ["CodeRabbit"]}},
            ),
            patch.object(GATE, "review_comments") as comments,
            patch.object(
                GATE, "repository_slug", return_value=("jscraik/configs", None)
            ),
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, base, ""),
            ),
            patch.object(
                GATE, "_coderabbit_statuses", return_value=[status]
            ) as statuses,
            patch.object(
                GATE, "_codex_completion_snapshot", return_value=(True, None)
            ) as snapshot,
        ):
            for is_inline in (True, False):
                selected = (
                    finding
                    if is_inline
                    else {
                        **finding,
                        "html_url": url + "#issuecomment-10",
                        "body": "Inspection incomplete for " + HEAD,
                    }
                )
                inline = [finding, later] if is_inline else [later]
                entries = [prior, summary] if is_inline else [prior, selected, summary]
                args = argparse.Namespace(
                    repo="jscraik/configs",
                    pr=7,
                    reviewer="coderabbitai",
                    clarify=False,
                    clarify_source=None,
                    reinspect_source=selected["html_url"],
                )
                comments.return_value = (inline, None)
                completion, error = GATE.coderabbit_completion_review(
                    Path.cwd(), pr, HEAD, inline, entries
                )
                self.assertIsNone(error)
                self.assertIsNotNone(completion)
                self.assertEqual(
                    GATE.outstanding_bot_concerns([], inline, [completion], HEAD),
                    ["CodeRabbit"],
                )
                with (
                    self.subTest(source=selected["html_url"]),
                    self.assertRaisesRegex(ValueError, "already been cleared"),
                ):
                    self.reinspection_source(Path.cwd(), args, HEAD, entries)
                statuses.return_value = []
                self.assertEqual(
                    self.reinspection_source(Path.cwd(), args, HEAD, entries), selected
                )
                statuses.return_value = None
                with self.assertRaisesRegex(
                    ValueError, "status inventory.*unavailable"
                ):
                    self.reinspection_source(Path.cwd(), args, HEAD, entries)
                statuses.return_value = [status]
                for status_reads in (
                    [[], [status], [status], [status]],
                    [[], [], None],
                    [[status], None],
                ):
                    statuses.side_effect = status_reads
                    with (
                        self.subTest(status_reads=status_reads),
                        self.assertRaisesRegex(ValueError, "status inventory"),
                    ):
                        self.reinspection_source(Path.cwd(), args, HEAD, entries)
                statuses.side_effect = None
                snapshot.return_value = (False, "review inventory changed")
                with self.assertRaisesRegex(ValueError, "review inventory changed"):
                    self.reinspection_source(Path.cwd(), args, HEAD, entries)
                snapshot.return_value = (True, None)
                # A completion tied with the latest source update does not prove
                # ordering, and a later finding remains eligible for inspection.
                tied = {**selected, "updated_at": summary["updated_at"]}
                tied_inline = [tied, later] if is_inline else [later]
                tied_entries = [prior, summary] if is_inline else [prior, tied, summary]
                comments.return_value = (tied_inline, None)
                self.assertEqual(
                    self.reinspection_source(Path.cwd(), args, HEAD, tied_entries), tied
                )
                # A verified incremental completion is not a full clearance of
                # the selected source, even when it completed afterwards.
                earlier_head = "c" * 40
                earlier_review = {
                    "user": user,
                    "state": "COMMENTED",
                    "commit_id": earlier_head,
                    "body": f"No findings for {earlier_head}.",
                    "submittedAt": prior["created_at"],
                }
                incremental = {
                    **summary,
                    "body": summary_body.replace(base, earlier_head),
                }
                incremental_entries = (
                    [prior, incremental]
                    if is_inline
                    else [prior, selected, incremental]
                )
                comments.return_value = (inline, None)
                hosted.return_value = ({**pr, "reviews": [earlier_review]}, None)
                completion, error = GATE.coderabbit_completion_review(
                    Path.cwd(),
                    hosted.return_value[0],
                    HEAD,
                    inline,
                    incremental_entries,
                )
                self.assertIsNone(error)
                self.assertTrue(completion["incremental_completion"])
                self.assertEqual(
                    self.reinspection_source(
                        Path.cwd(), args, HEAD, incremental_entries
                    ),
                    selected,
                )
                hosted.return_value = (pr, None)
            args = argparse.Namespace(
                repo="jscraik/configs",
                pr=7,
                reviewer="coderabbitai",
                clarify=False,
                clarify_source=None,
                reinspect_source=summary["html_url"],
            )
            comments.return_value = ([later], None)
            with self.assertRaisesRegex(ValueError, "already been cleared"):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior, summary])

    def test_reinspection_rejects_changed_comment_inventory_without_a_known_completion(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        user = {"login": "coderabbitai[bot]", "type": "Bot", "id": 8}
        args = argparse.Namespace(
            repo="jscraik/configs",
            pr=7,
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=url + "#discussion_r10",
        )
        finding = {
            "id": 10,
            "html_url": args.reinspect_source,
            "commit_id": HEAD,
            "original_commit_id": HEAD,
            "pull_request_url": "https://api.github.com/repos/jscraik/configs/pulls/7",
            "user": user,
            "body": "The first concern.",
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:16:00Z",
        }
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        # This arrives after the caller read its entries, but before the lane's read.
        summary = {
            "id": 12,
            "html_url": url + "#issuecomment-12",
            "user": user,
            "body": "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->",
        }
        pr = {
            "number": 7,
            "state": "OPEN",
            "headRefOid": HEAD,
            "baseRefOid": "b" * 40,
            "headRefName": "codex/test",
            "baseRefName": "main",
            "isDraft": False,
            "url": url,
            "reviews": [],
        }
        with (
            patch.object(
                MODULE,
                "authenticated_actor",
                return_value={"id": 93, "login": "jscraik"},
            ),
            patch.object(GATE, "gh_pr", return_value=(pr, None)) as hosted,
            patch.object(
                GATE,
                "reviews_lane",
                return_value={"details": {"outstanding_bot_concerns": ["CodeRabbit"]}},
            ),
            patch.object(GATE, "review_comments", return_value=([finding], None)),
            patch.object(
                GATE, "issue_comments", return_value=([prior, summary], None)
            ) as comments,
        ):
            with self.assertRaisesRegex(ValueError, "comment inventory changed"):
                self.reinspection_source(Path.cwd(), args, HEAD, [prior])
            comments.return_value = ([prior], None)
            for change in (
                {"state": "CLOSED"},
                {"headRefName": "codex/other"},
                {"baseRefName": "other"},
                {"isDraft": True},
            ):
                hosted.side_effect = [(pr, None), ({**pr, **change}, None)]
                with (
                    self.subTest(change=change),
                    self.assertRaisesRegex(ValueError, "PR identity.*changed"),
                ):
                    self.reinspection_source(Path.cwd(), args, HEAD, [prior])

    def test_reinspection_stops_before_post_if_inventory_changes_during_final_recheck(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        user = {"login": "coderabbitai[bot]", "type": "Bot", "id": 8}
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=url + "#discussion_r10",
            dry_run=False,
        )
        finding = {
            "id": 10,
            "html_url": args.reinspect_source,
            "commit_id": HEAD,
            "original_commit_id": HEAD,
            "pull_request_url": "https://api.github.com/repos/jscraik/configs/pulls/7",
            "user": user,
            "body": "The first concern.",
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:16:00Z",
        }
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        summary = {
            "id": 12,
            "html_url": url + "#issuecomment-12",
            "user": user,
            "body": "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->",
        }
        pr = {
            "number": 7,
            "state": "OPEN",
            "headRefOid": HEAD,
            "baseRefName": "main",
            "baseRefOid": "b" * 40,
            "url": url,
            "reviews": [],
        }
        inventories = [
            ([prior], None),
            ([prior], None),
            ([prior], None),
            ([prior, summary], None),
        ]
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE, "validate_receipt", return_value=(inspection_receipt(), None)
            ),
            patch.object(
                GATE, "issue_comments", side_effect=inventories
            ) as issue_comments,
            patch.object(GATE, "review_comments", return_value=([finding], None)),
            patch.object(
                GATE,
                "reviews_lane",
                return_value={"details": {"outstanding_bot_concerns": ["CodeRabbit"]}},
            ),
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
            patch.object(
                MODULE,
                "authenticated_actor",
                return_value={"id": 93, "login": "jscraik"},
            ),
            patch.object(GATE, "run_command") as command,
        ):
            with self.assertRaisesRegex(ValueError, "comment inventory changed"):
                MODULE.execute(args)
            self.assertEqual(issue_comments.call_count, 4)
            command.assert_not_called()

    def test_reinspection_does_not_post_if_base_changes_after_receipt_validation(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        base = "b" * 40
        user = {"login": "coderabbitai[bot]", "type": "Bot", "id": 8}
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        finding = {
            "id": 10,
            "html_url": url + "#discussion_r10",
            "commit_id": HEAD,
            "original_commit_id": HEAD,
            "pull_request_url": "https://api.github.com/repos/jscraik/configs/pulls/7",
            "user": user,
            "body": "The first concern.",
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:16:00Z",
        }
        pr = {
            "number": 7,
            "state": "OPEN",
            "headRefOid": HEAD,
            "baseRefName": "main",
            "baseRefOid": base,
            "url": url,
            "reviews": [],
        }
        receipt = {
            "authority": GATE.review_inspection_authority(),
            "repo": {"base_branch": "main", "remote_base_sha": base},
        }
        for is_inline in (True, False):
            selected = (
                finding
                if is_inline
                else {
                    **finding,
                    "html_url": url + "#issuecomment-10",
                    "body": "Inspection incomplete for " + HEAD,
                }
            )
            entries = [prior] if is_inline else [prior, selected]
            inline = [finding] if is_inline else []
            args = argparse.Namespace(
                repo_root=Path.cwd(),
                repo="jscraik/configs",
                pr=7,
                receipt=Path("receipt.json"),
                reviewer="coderabbitai",
                clarify=False,
                clarify_source=None,
                reinspect_source=selected["html_url"],
                dry_run=False,
            )
            for change in ({"baseRefName": "other"}, {"baseRefOid": "c" * 40}):
                for changed_initially in (True, False):
                    initial = {**pr, **change} if changed_initially else pr
                    final = {**pr, **change}
                    with (
                        self.subTest(
                            source=selected["html_url"],
                            change=change,
                            initial=changed_initially,
                        ),
                        patch.object(GATE, "resolve_root", return_value=Path.cwd()),
                        patch.object(
                            GATE,
                            "current_worktree",
                            return_value=("topic", HEAD, "main", ".git", ".git"),
                        ),
                        patch.object(
                            GATE, "validate_receipt", return_value=(receipt, None)
                        ),
                        patch.object(
                            GATE, "issue_comments", return_value=(entries, None)
                        ),
                        patch.object(
                            GATE, "review_comments", return_value=(inline, None)
                        ),
                        patch.object(
                            GATE,
                            "reviews_lane",
                            return_value={
                                "details": {"outstanding_bot_concerns": ["CodeRabbit"]}
                            },
                        ),
                        patch.object(
                            GATE,
                            "_codex_completion_snapshot",
                            return_value=(True, None),
                        ),
                        patch.object(
                            GATE, "gh_pr", side_effect=[(initial, None), (final, None)]
                        ),
                        patch.object(GATE, "git", return_value=HEAD),
                        patch.object(
                            MODULE,
                            "authenticated_actor",
                            return_value={"id": 93, "login": "jscraik"},
                        ),
                        patch.object(
                            GATE,
                            "run_command",
                            side_effect=AssertionError("must not post"),
                        ) as command,
                    ):
                        with self.assertRaisesRegex(ValueError, "base.*receipt"):
                            MODULE.execute(args)
                        command.assert_not_called()

    def test_reinspection_requires_a_stable_well_formed_receipt_before_posting(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=url + "#discussion_r10",
            dry_run=False,
        )
        concern = {"html_url": args.reinspect_source, "body": "Concern"}
        valid = inspection_receipt()
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(GATE, "validate_receipt") as validate,
            patch.object(GATE, "issue_comments", return_value=([], None)),
            patch.object(MODULE, "reinspection_source", return_value=concern),
            patch.object(GATE, "run_command") as command,
        ):
            for bad_repo in (
                None,
                {},
                {"base_branch": "", "remote_base_sha": "b" * 40},
                {"base_branch": "main", "remote_base_sha": "invalid"},
            ):
                validate.return_value = ({**valid, "repo": bad_repo}, None)
                with (
                    self.subTest(repo=bad_repo),
                    self.assertRaisesRegex(ValueError, "receipt base is malformed"),
                ):
                    MODULE.execute(args)
            for refreshed in (
                ({}, "remote ancestry changed"),
                ({**valid, "extra": True}, None),
            ):
                validate.side_effect = [(valid, None), refreshed]
                with (
                    self.subTest(refreshed=refreshed),
                    self.assertRaisesRegex(ValueError, "changed"),
                ):
                    MODULE.execute(args)
                validate.side_effect = None
            command.assert_not_called()

    def test_inline_reinspection_reuses_its_existing_request(self) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        source = url + "#discussion_r10"
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=source,
            dry_run=False,
        )
        concern = {
            "id": 10,
            "html_url": source,
            "commit_id": HEAD,
            "original_commit_id": HEAD,
            "pull_request_url": "https://api.github.com/repos/jscraik/configs/pulls/7",
            "body": "Record the missing validation command and outcome.",
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:17:00Z",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        request = {
            **prior,
            "html_url": url + "#issuecomment-12",
            "body": GATE.reinspection_request_body(HEAD, source),
            "created_at": "2026-10-16T22:18:00Z",
            "updated_at": "2026-10-16T22:18:00Z",
        }
        pr = {
            "state": "OPEN",
            "headRefOid": HEAD,
            "baseRefName": "main",
            "baseRefOid": "b" * 40,
            "url": url,
            "reviews": [],
        }
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE, "validate_receipt", return_value=(inspection_receipt(), None)
            ),
            patch.object(GATE, "issue_comments", return_value=([prior, request], None)),
            patch.object(GATE, "review_comments", return_value=([concern], None)),
            patch.object(
                GATE,
                "reviews_lane",
                return_value={"details": {"outstanding_bot_concerns": ["CodeRabbit"]}},
            ),
            patch.object(GATE, "_codex_completion_snapshot", return_value=(True, None)),
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
            patch.object(GATE, "git", return_value=HEAD),
            patch.object(
                MODULE,
                "authenticated_actor",
                return_value={"id": 93, "login": "jscraik"},
            ),
            patch.object(GATE, "run_command") as command,
        ):
            result = MODULE.execute(args)
            self.assertTrue(result["reused"])
            self.assertEqual(result["url"], request["html_url"])
            command.assert_not_called()

    def test_inline_reinspection_rechecks_the_source_before_posting(self) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        source = url + "#discussion_r10"
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=source,
            dry_run=False,
        )
        concern = {
            "id": 10,
            "html_url": source,
            "commit_id": HEAD,
            "original_commit_id": HEAD,
            "pull_request_url": "https://api.github.com/repos/jscraik/configs/pulls/7",
            "body": "Record the missing validation command and outcome.",
            "created_at": "2026-10-16T22:16:00Z",
            "updated_at": "2026-10-16T22:17:00Z",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        prior = {
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-16T21:30:00Z",
            "updated_at": "2026-10-16T21:30:00Z",
            "user": {"id": 93, "login": "jscraik"},
        }
        pr = {
            "state": "OPEN",
            "headRefOid": HEAD,
            "baseRefName": "main",
            "baseRefOid": "b" * 40,
            "url": url,
            "reviews": [],
        }
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE, "validate_receipt", return_value=(inspection_receipt(), None)
            ),
            patch.object(GATE, "issue_comments", return_value=([prior], None)),
            patch.object(
                GATE,
                "review_comments",
                side_effect=[
                    ([concern], None),
                    ([{**concern, "body": "Changed finding"}], None),
                ],
            ),
            patch.object(
                GATE,
                "reviews_lane",
                return_value={"details": {"outstanding_bot_concerns": ["CodeRabbit"]}},
            ),
            patch.object(GATE, "_codex_completion_snapshot", return_value=(True, None)),
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
            patch.object(
                MODULE,
                "authenticated_actor",
                return_value={"id": 93, "login": "jscraik"},
            ),
            patch.object(GATE, "run_command") as command,
        ):
            with self.assertRaisesRegex(ValueError, "concern changed"):
                MODULE.execute(args)
            command.assert_not_called()

    def test_reinspection_rechecks_source_and_posts_a_distinct_deduplicated_request(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7#issuecomment-11"
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            reinspect_source=url.replace("-11", "-10"),
            dry_run=True,
        )
        concern = {"html_url": args.reinspect_source, "body": "Concern " + HEAD}
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE, "validate_receipt", return_value=(inspection_receipt(), None)
            ),
            patch.object(
                GATE, "issue_comments", return_value=([concern], None)
            ) as comments,
            patch.object(MODULE, "reinspection_source", return_value=concern) as source,
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, url, ""),
            ) as command,
            patch.object(
                GATE,
                "gh_pr",
                return_value=(
                    {
                        "state": "OPEN",
                        "headRefOid": HEAD,
                        "baseRefName": "main",
                        "baseRefOid": "b" * 40,
                    },
                    None,
                ),
            ),
        ):
            body = MODULE.execute(args)["body"]
            self.assertIn(args.reinspect_source, body)
            self.assertNotEqual(body, MODULE.request_body("coderabbitai", HEAD, False))
            command.assert_not_called()
            args.dry_run = False
            source.side_effect = [concern, {**concern, "body": "Changed"}]
            with self.assertRaisesRegex(ValueError, "concern changed"):
                MODULE.execute(args)
            command.assert_not_called()
            source.side_effect = [
                concern,
                concern,
                {**concern, "body": "Changed after receipt revalidation"},
            ]
            with self.assertRaisesRegex(ValueError, "concern changed"):
                MODULE.execute(args)
            command.assert_not_called()
            source.side_effect = None
            comments.side_effect = [
                ([concern], None),
                ([concern], None),
                ([concern, {"html_url": url, "body": body}], None),
            ]
            with self.assertRaisesRegex(ValueError, "request appeared"):
                MODULE.execute(args)
            command.assert_not_called()
            comments.side_effect = [
                ([concern], None),
                ([concern], None),
                ([concern], None),
                ([concern, {"html_url": url, "body": body}], None),
            ]
            self.assertEqual(MODULE.execute(args)["url"], url)
            command.assert_called_once()
            comments.side_effect = None
            comments.return_value = (
                [
                    concern,
                    {
                        "html_url": url,
                        "body": body,
                        "user": {"id": 93, "login": "jscraik"},
                        "created_at": "2026-10-19T12:00:00Z",
                        "updated_at": "2026-10-19T12:00:00Z",
                    },
                ],
                None,
            )
            command.return_value = subprocess.CompletedProcess(
                [], 0, '{"id":93,"login":"jscraik"}', ""
            )
            with patch.object(
                GATE,
                "gh_pr",
                return_value=(
                    {
                        "state": "OPEN",
                        "headRefOid": HEAD,
                        "baseRefName": "main",
                        "baseRefOid": "b" * 40,
                        "url": url.split("#")[0],
                    },
                    None,
                ),
            ):
                self.assertTrue(MODULE.execute(args)["reused"])
            command.reset_mock()
            with (
                patch.object(
                    GATE,
                    "gh_pr",
                    return_value=(
                        {
                            "state": "OPEN",
                            "headRefOid": HEAD,
                            "baseRefName": "other",
                            "baseRefOid": "b" * 40,
                            "url": url.split("#")[0],
                        },
                        None,
                    ),
                ),
                patch.object(
                    MODULE,
                    "authenticated_actor",
                    return_value={"id": 93, "login": "jscraik"},
                ),
                self.assertRaisesRegex(ValueError, "current-head verification failed"),
            ):
                MODULE.execute(args)
            command.assert_not_called()
            comments.side_effect = [
                ([concern], None),
                ([concern], None),
                ([concern], None),
                ([concern, {"html_url": url, "body": body}], None),
            ]
            command.return_value = subprocess.CompletedProcess([], 0, url, "")
            with (
                patch.object(
                    GATE,
                    "gh_pr",
                    return_value=(
                        {
                            "state": "OPEN",
                            "headRefOid": HEAD,
                            "baseRefName": "other",
                            "baseRefOid": "b" * 40,
                        },
                        None,
                    ),
                ),
                self.assertRaisesRegex(ValueError, "request may have been posted"),
            ):
                MODULE.execute(args)
            self.assertEqual(command.call_args.args[0][:3], ["gh", "pr", "comment"])

    def test_fixed_requests_select_supported_verdict_without_suppressing_failure(
        self,
    ) -> None:
        for reviewer, clarify, source in (
            ("codex", False, None),
            ("coderabbitai", False, None),
        ):
            with self.subTest(reviewer=reviewer, clarify=clarify):
                body = MODULE.request_body(reviewer, HEAD, clarify, source)
                subject = "the recorded code review" if clarify else "inspection"
                self.assertIn(
                    f"Only if {subject} completed and there are no remaining findings, state `No findings for {HEAD}.`; otherwise list actionable findings.",
                    body,
                )
                self.assertIn(
                    "use that standalone statement as the only prose outside the standard provider wrapper",
                    body,
                )
                self.assertIn(
                    "Only provider tool traces or fixed benign status explanations may appear in analysis",
                    body,
                )
                self.assertNotIn(
                    "put provenance and execution limits in its analysis disclosure",
                    body,
                )
                self.assertIn(
                    "Do not hide findings or a failed or incomplete "
                    + ("review" if clarify else "inspection"),
                    body,
                )
                self.assertIn("not approval, merge or thread resolution", body)
                self.assertIn("Do not enable paid services or change source", body)

    def test_clarification_requests_recorded_review_verdict_without_a_new_inspection(
        self,
    ) -> None:
        source = "https://github.com/jscraik/configs/pull/7#issuecomment-8"
        body = MODULE.request_body("coderabbitai", HEAD, clarify=True, source=source)
        self.assertIn(
            f"Report the outcome of the automated CodeRabbit code review recorded at {source} for {HEAD}",
            body,
        )
        self.assertIn("Determine whether that recorded code review completed", body)
        self.assertIn(
            "Refresh that exact linked GitHub comment once through authenticated read-only access",
            body,
        )
        self.assertIn("rather than a cached earlier version", body)
        self.assertIn("report that evidence gap", body)
        self.assertIn("Do not repeat inspection", body)
        self.assertIn(f"Recorded review status for {HEAD}", body)
        self.assertNotIn("independent inspection", body)
        self.assertIn("Report recorded findings and evidence limits", body)
        self.assertIn("Do not enable paid services or change source", body)
        self.assertFalse(
            GATE._bot_review_is_acceptable(
                {
                    "user": {"login": "coderabbitai[bot]"},
                    "state": "COMMENTED",
                    "body": body,
                },
                HEAD,
            )
        )

    def test_recorded_status_accepts_fixed_provider_wrappers_only(self) -> None:
        status = f"Recorded review status for {HEAD}: completed; no actionable comments recorded."
        wrapped = (
            "<!-- This is an auto-generated reply by CodeRabbit -->\n\n> [!TIP]\n> For best results, initiate chat on the files or code changes.\n\n@jscraik\n\n"
            + status
            + "\n\n_You are interacting with an AI system._"
        )
        entry = {
            "record_only_reply": True,
            "body": wrapped,
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        self.assertTrue(GATE._neutral_recorded_reply(entry, HEAD))
        self.assertFalse(
            GATE._neutral_recorded_reply(
                {
                    **entry,
                    "body": wrapped.replace(status, status + " Unsafe write remains."),
                },
                HEAD,
            )
        )

    @staticmethod
    def recorded_reply_fixture() -> tuple:
        url = "https://github.com/jscraik/configs/pull/7"
        owner = {"id": 93, "login": "jscraik", "type": "User"}
        source = {
            "html_url": url + "#issuecomment-8",
            "user": {"id": 8, "login": "coderabbitai[bot]", "type": "Bot"},
            "body": f"Recorded source for {HEAD}",
            "created_at": "2026-10-19T12:00:00Z",
        }
        request = {
            "html_url": url + "#issuecomment-9",
            "user": owner,
            "body": MODULE.request_body("coderabbitai", HEAD, True, source["html_url"]),
            "created_at": "2026-10-19T12:01:00Z",
            "updated_at": "2026-10-19T12:01:00Z",
        }
        reply = {
            "html_url": url + "#issuecomment-10",
            "user": source["user"],
            "body": f"No findings for {HEAD}.",
            "created_at": "2026-10-19T12:02:00Z",
        }
        return (url, owner, source, request, reply)

    def test_recorded_reply_effective_time_and_comment_order(self) -> None:
        url, _, source, request, reply = self.recorded_reply_fixture()
        request["html_url"], reply["html_url"] = (
            url + "#issuecomment-10",
            url + "#issuecomment-9",
        )

        def entries() -> list[dict]:
            return GATE.recorded_review_entries(
                {"url": url}, [source, request, reply], HEAD
            )

        for created, updated, expected in (
            ("2026-10-19T12:00:30Z", "2026-10-19T12:00:30Z", False),
            ("2026-10-19T12:00:30Z", "2026-10-19T12:01:00Z", True),
            ("2026-10-19T12:01:00Z", "2026-10-19T12:01:00Z", True),
            ("2026-10-19T12:01:00Z", "2026-10-19T12:02:00Z", True),
        ):
            with self.subTest(created=created, updated=updated):
                reply.update(created_at=created, updated_at=updated)
                self.assertEqual(bool(entries()[-1].get("record_only_reply")), expected)
        reply["updated_at"] = "invalid"
        self.assertFalse(GATE._neutral_recorded_reply(entries()[-1], HEAD))

    def test_missing_source_or_different_request_owner_cannot_clear_status(
        self,
    ) -> None:
        url, owner, source, request, reply = self.recorded_reply_fixture()
        other_request = {**request, "user": {**owner, "id": 94, "login": "maintainer"}}
        for inventory in ([request, reply], [source, other_request, reply]):
            with self.subTest(
                source_present=source in inventory, owner=inventory[-2]["user"]
            ):
                entries = GATE.recorded_review_entries({"url": url}, inventory, HEAD)
                self.assertFalse(
                    GATE._bot_review_is_acceptable(
                        {**entries[-1], "state": "COMMENTED"}, HEAD
                    )
                )

    def test_edited_clarification_retains_denial_only_provenance(self) -> None:
        url, _, _, request, reply = self.recorded_reply_fixture()
        request["updated_at"] = "2026-10-19T12:04:00Z"
        reply.update(created_at="2026-10-19T12:03:00Z", state="COMMENTED")
        selected = GATE.recorded_review_entries({"url": url}, [request, reply], HEAD)[
            -1
        ]
        self.assertTrue(selected.get("record_only_reply"))
        self.assertFalse(GATE._bot_review_is_acceptable(selected, HEAD))
        self.assertTrue(GATE._neutral_recorded_reply(selected, HEAD))

    def test_record_only_clarification_does_not_solicit_review_clearance(self) -> None:
        body = MODULE.request_body(
            "coderabbitai",
            HEAD,
            clarify=True,
            source="https://github.com/jscraik/configs/pull/7#issuecomment-8",
        )
        status = f"Recorded review status for {HEAD}: completed; no actionable comments recorded."
        self.assertIn(f"`{status}`", body)
        self.assertIn(
            "Only if the recorded review completed and has no actionable comments", body
        )
        self.assertNotIn(f"No findings for {HEAD}.", body)
        self.assertIn("informational only", body)
        self.assertIn("Do not issue a clearance verdict", body)
        reply = f"Recorded review status for {HEAD}: completed; no actionable comments recorded."
        self.assertFalse(
            GATE._bot_review_is_acceptable(
                {
                    "user": {"login": "coderabbitai[bot]"},
                    "state": "COMMENTED",
                    "body": reply,
                },
                HEAD,
            )
        )

    def test_recorded_reply_cannot_supply_or_block_independent_clearance(self) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        source = {
            "id": 8,
            "html_url": url + "#issuecomment-8",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
            "body": f"Recorded source for {HEAD}",
            "created_at": "2026-10-19T12:00:00Z",
        }
        request = {
            "id": 9,
            "html_url": url + "#issuecomment-9",
            "user": {"login": "jscraik", "type": "User", "id": 93},
            "body": MODULE.request_body("coderabbitai", HEAD, True, source["html_url"]),
            "created_at": "2026-10-19T12:01:00Z",
            "updated_at": "2026-10-19T12:01:00Z",
        }
        reply = {
            "id": 10,
            "html_url": url + "#issuecomment-10",
            "user": source["user"],
            "created_at": "2026-10-19T12:02:00Z",
            "updated_at": "2026-10-19T12:02:00Z",
        }
        independent = {
            "user": {"login": "chatgpt-codex-connector[bot]"},
            "state": "COMMENTED",
            "commit_id": HEAD,
            "body": f"No findings for {HEAD}.",
        }
        pr = {
            "number": 7,
            "url": url,
            "author": {"login": "contributor"},
            "reviews": [],
        }
        bodies = (
            f"Recorded review status for {HEAD}: completed; no actionable comments recorded.",
            f"No findings for {HEAD}.",
            f"No comments for `{HEAD}`!",
            f"<!-- This is an auto-generated reply by CodeRabbit -->\n\nNo findings for {HEAD}.\n\n_You are interacting with an AI system._",
        )
        with (
            patch.object(
                GATE, "review_threads", return_value=({"unresolved_threads": 0}, None)
            ),
            patch.object(GATE, "review_comments", return_value=([], None)),
            patch.object(GATE, "codex_completion_review", return_value=(None, None)),
            patch.object(
                GATE,
                "review_requirement",
                return_value={"risk_tier": "ordinary", "required_bot_review_count": 1},
            ),
        ):
            for body in bodies:
                with (
                    self.subTest(body=body),
                    patch.object(
                        GATE,
                        "issue_comments",
                        return_value=([source, request, {**reply, "body": body}], None),
                    ),
                ):
                    self.assertNotEqual(
                        GATE.reviews_lane(Path.cwd(), pr, HEAD)["status"], "pass"
                    )
                    with patch.object(
                        GATE,
                        "issue_comments",
                        return_value=(
                            [
                                request,
                                {**reply, "body": body},
                                {**source, "body": "No findings"},
                            ],
                            None,
                        ),
                    ):
                        self.assertEqual(
                            GATE.reviews_lane(
                                Path.cwd(), {**pr, "reviews": [independent]}, HEAD
                            )["status"],
                            "pass",
                        )
            finding = (
                f"Recorded review status for {HEAD}: finding remains: unsafe write."
            )
            with patch.object(
                GATE,
                "issue_comments",
                return_value=(
                    [
                        {**source, "body": "No findings"},
                        request,
                        {**reply, "body": finding},
                    ],
                    None,
                ),
            ):
                self.assertEqual(
                    GATE.reviews_lane(
                        Path.cwd(), {**pr, "reviews": [independent]}, HEAD
                    )["status"],
                    "fail",
                )

    def test_recorded_reply_context_preserves_identity_freshness_and_findings(
        self,
    ) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        source = {
            "html_url": url + "#issuecomment-8",
            "body": f"Review for {HEAD}",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
            "created_at": "2026-10-19T12:00:00Z",
        }
        request = {
            "html_url": url + "#issuecomment-9",
            "user": {"login": "jscraik", "type": "User", "id": 93},
            "body": MODULE.request_body("coderabbitai", HEAD, True, source["html_url"]),
            "created_at": "2026-10-19T12:01:00Z",
            "updated_at": "2026-10-19T12:01:00Z",
        }
        reply = {
            "html_url": url + "#issuecomment-10",
            "user": source["user"],
            "body": f"No findings for {HEAD}.",
            "created_at": "2026-10-19T12:03:00Z",
            "state": "COMMENTED",
        }
        pr = {"url": url, "author": {"login": "jscraik"}}
        for changed in (
            {**request, "body": request["body"] + " extra"},
            {**request, "html_url": url.replace("/7", "/8") + "#issuecomment-9"},
            {**request, "body": request["body"].replace(HEAD, "b" * 40)},
        ):
            with self.subTest(request=changed):
                entries = GATE.recorded_review_entries(
                    pr, [source, changed, reply], HEAD
                )
                self.assertFalse(entries[-1].get("record_only_reply", False))
        entries = GATE.recorded_review_entries(pr, [reply, request, source], HEAD)
        self.assertFalse(GATE._bot_review_is_acceptable(entries[0], HEAD))
        ordinary = MODULE.request_body("coderabbitai", HEAD, False)
        historical = ordinary.replace(
            f"@coderabbitai full review\n\nIndependently inspect the current PR diff for {HEAD}",
            f"@coderabbitai Clarify your inspection evidence at {source['html_url']} for {HEAD}. Confirm whether independent inspection completed; if it did not, identify the gap. Do not repeat inspection",
        )
        for source_body, request_body in (
            ("Source summary replaced after the request", request["body"]),
            (source["body"], historical),
        ):
            with self.subTest(source_body=source_body, request_body=request_body):
                changed_source = {
                    **source,
                    "body": source_body,
                    "updated_at": "2026-10-19T12:02:00Z",
                }
                changed_request = {**request, "body": request_body}
                entries = GATE.recorded_review_entries(
                    pr, [changed_source, changed_request, reply], HEAD
                )
                self.assertTrue(entries[-1].get("record_only_reply"))
                self.assertFalse(GATE._bot_review_is_acceptable(entries[-1], HEAD))
                reset = {
                    **request,
                    "body": MODULE.request_body(
                        "coderabbitai", HEAD, False, retry_source=source["html_url"]
                    ),
                }
                entries = GATE.recorded_review_entries(
                    pr, [changed_source, changed_request, reset, reply], HEAD
                )
                self.assertFalse(GATE._bot_review_is_acceptable(entries[-1], HEAD))
        for body in (
            f"Recorded review status for {HEAD}: unsafe write remains.",
            f"No findings for {HEAD}.\nFinding remains",
            "Inspection failed",
        ):
            entry = {**reply, "record_only_reply": True, "body": body}
            self.assertFalse(GATE._neutral_recorded_reply(entry, HEAD))
            self.assertFalse(GATE._bot_review_is_acceptable(entry, HEAD))
        for owner in (
            {},
            {"id": True, "login": "jscraik", "type": "User"},
            {"id": 0, "login": "jscraik", "type": "User"},
            {"id": 93, "login": "", "type": "User"},
            {"id": 93, "login": "jscraik", "type": "Bot"},
        ):
            with self.subTest(owner=owner):
                selected = GATE.recorded_review_entries(
                    pr, [source, {**request, "user": owner}, reply], HEAD
                )
                self.assertFalse(selected[-1].get("record_only_reply", False))
                self.assertFalse(GATE._bot_review_is_acceptable(selected[-1], HEAD))
        missing_time = {
            key: value for key, value in reply.items() if key != "created_at"
        }
        uncertain = GATE.recorded_review_entries(
            pr, [source, request, missing_time], HEAD
        )[-1]
        self.assertFalse(GATE._bot_review_is_acceptable(uncertain, HEAD))
        self.assertFalse(GATE._neutral_recorded_reply(uncertain, HEAD))
        full = {
            **request,
            "body": MODULE.request_body("coderabbitai", HEAD, False),
            "created_at": "2026-10-19T12:02:00Z",
            "updated_at": "2026-10-19T12:02:00Z",
        }
        reinspection = (
            MODULE.request_body("coderabbitai", HEAD, False)
            + f" Reinspection follows the later outstanding concern at {source['html_url']}. Address that concern and the current PR metadata explicitly."
        )
        for body in (
            full["body"],
            reinspection,
            MODULE.request_body(
                "coderabbitai", HEAD, False, retry_source=source["html_url"]
            ),
        ):
            with self.subTest(independent_request=body):
                entries = GATE.recorded_review_entries(
                    pr, [source, request, {**full, "body": body}, reply], HEAD
                )
                self.assertTrue(entries[-1].get("record_only_reply"))
                self.assertFalse(GATE._bot_review_is_acceptable(entries[-1], HEAD))

    def test_recorded_reply_preserves_raw_codex_completion_snapshot(self) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        body = _fixture_resource(
            Path(__file__).parent / "fixtures/codex-code-completion.txt"
        ).read_text()
        old = "009ce5732d3953b8a0d5916219403b480b7d753c"
        body = body.replace(old, HEAD).replace(old[:7], HEAD[:7])
        codex = {
            "id": 42,
            "html_url": url + "#issuecomment-42",
            "body": body,
            "user": {"login": "chatgpt-codex-connector[bot]", "type": "Bot", "id": 7},
            "created_at": "2026-10-10T17:00:00Z",
            "updated_at": "2026-10-10T17:37:47Z",
        }
        reaction = {
            "id": 99,
            "user": {"login": "chatgpt-codex-connector[bot]", "type": "User", "id": 7},
            "content": "+1",
            "created_at": "2026-10-10T17:37:50Z",
        }
        source = {
            "id": 8,
            "html_url": url + "#issuecomment-8",
            "body": "No findings",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
            "created_at": "2026-10-10T17:01:00Z",
        }
        request = {
            "id": 9,
            "html_url": url + "#issuecomment-9",
            "body": MODULE.request_body("coderabbitai", HEAD, True, source["html_url"]),
            "user": {"login": "jscraik", "type": "User", "id": 93},
            "created_at": "2026-10-10T17:02:00Z",
            "updated_at": "2026-10-10T17:02:00Z",
        }
        reply = {
            "id": 10,
            "html_url": url + "#issuecomment-10",
            "user": source["user"],
            "body": f"Recorded review status for {HEAD}: completed; no actionable comments recorded.",
            "created_at": "2026-10-10T17:03:00Z",
        }
        entries = [source, request, reply, codex]
        pr = {
            "number": 7,
            "url": url,
            "headRefOid": HEAD,
            "baseRefOid": "b" * 40,
            "reviews": [],
            "author": {"login": "jscraik"},
        }
        with (
            patch.object(
                GATE, "review_threads", return_value=({"unresolved_threads": 0}, None)
            ),
            patch.object(GATE, "review_comments", return_value=([], None)),
            patch.object(GATE, "issue_comments", return_value=(entries, None)),
            patch.object(
                GATE, "repository_slug", return_value=("jscraik/configs", None)
            ),
            patch.object(GATE, "_codex_reactions", return_value=([reaction], None)),
            patch.object(GATE, "git", return_value=HEAD),
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
            patch.object(
                GATE,
                "review_requirement",
                return_value={"risk_tier": "ordinary", "required_bot_review_count": 1},
            ),
        ):
            result = GATE.reviews_lane(Path.cwd(), pr, HEAD)
            self.assertEqual(result["status"], "pass", result)
            self.assertIsNotNone(result["details"]["codex_completion_evidence"])
        self.assertNotIn("record_only_reply", reply)

    def test_coderabbit_full_review_command_has_its_own_paragraph(self) -> None:
        body = MODULE.request_body("coderabbitai", HEAD, False)
        self.assertEqual(body.split("\n\n", 1)[0], "@coderabbitai full review")
        self.assertTrue(
            body.split("\n\n", 1)[1].startswith(
                f"Independently inspect the current PR diff for {HEAD}."
            )
        )
        for reviewer, clarify, source in (
            ("codex", False, None),
            (
                "coderabbitai",
                True,
                "https://github.com/jscraik/configs/pull/7#issuecomment-8",
            ),
        ):
            with self.subTest(reviewer=reviewer, clarify=clarify):
                self.assertNotIn(
                    "\n\n", MODULE.request_body(reviewer, HEAD, clarify, source)
                )

    def setUp(self) -> None:
        local_head = patch.object(GATE, "git", return_value=HEAD)
        local_head.start()
        self.addCleanup(local_head.stop)

    def test_head_change_during_receipt_validation_blocks_dry_run_and_post(
        self,
    ) -> None:
        for dry_run in (True, False):
            args = argparse.Namespace(
                repo_root=Path.cwd(),
                repo="jscraik/configs",
                pr=7,
                receipt=Path("receipt.json"),
                reviewer="codex",
                clarify=False,
                clarify_source=None,
                dry_run=dry_run,
            )
            with (
                self.subTest(dry_run=dry_run),
                patch.object(GATE, "resolve_root", return_value=Path.cwd()),
                patch.object(
                    GATE,
                    "current_worktree",
                    return_value=("topic", HEAD, "main", ".git", ".git"),
                ),
                patch.object(
                    GATE,
                    "validate_receipt",
                    return_value=(
                        {"authority": GATE.review_inspection_authority()},
                        None,
                    ),
                ),
                patch.object(GATE, "git", return_value="b" * 40),
                patch.object(GATE, "issue_comments", return_value=([], None)),
                patch.object(GATE, "run_command") as command,
            ):
                with self.assertRaisesRegex(ValueError, "HEAD changed before"):
                    MODULE.execute(args)
                command.assert_not_called()

    def test_clarification_rechecks_source_before_mutation(self) -> None:
        source = "https://github.com/jscraik/configs/pull/7#issuecomment-8"
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=True,
            clarify_source=source,
            dry_run=False,
        )
        entry = {
            "html_url": source,
            "body": "Inspection of " + HEAD,
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        for changed in (
            [],
            [{**entry, "body": "old head"}],
            [{**entry, "body": "Changed findings for " + HEAD}],
            [{**entry, "updated_at": "2026-10-20T18:00:00Z"}],
            [{**entry, "created_at": "2026-10-20T17:00:00Z"}],
            [{**entry, "user": {"login": "other", "type": "Bot", "id": 8}}],
            [{**entry, "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 9}}],
        ):
            with (
                self.subTest(changed=changed),
                patch.object(GATE, "resolve_root", return_value=Path.cwd()),
                patch.object(
                    GATE,
                    "current_worktree",
                    return_value=("topic", HEAD, "main", ".git", ".git"),
                ),
                patch.object(
                    GATE,
                    "validate_receipt",
                    return_value=(
                        {"authority": GATE.review_inspection_authority()},
                        None,
                    ),
                ),
                patch.object(
                    GATE,
                    "issue_comments",
                    side_effect=[([entry], None), (changed, None)],
                ),
                patch.object(GATE, "run_command") as command,
            ):
                with self.assertRaisesRegex(ValueError, "clarification source changed"):
                    MODULE.execute(args)
                command.assert_not_called()

    def test_clarification_accepts_repository_case_variants(self) -> None:
        source = "https://github.com/jscraik/configs/pull/7#issuecomment-8"
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="JSCraik/Configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=True,
            clarify_source=source,
            dry_run=True,
        )
        entry = {
            "html_url": source,
            "body": "Inspection of " + HEAD,
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ),
            patch.object(GATE, "issue_comments", return_value=([entry], None)),
            patch.object(GATE, "run_command") as command,
        ):
            self.assertIn(source, MODULE.execute(args)["body"])
            args.clarify_source = source.replace("jscraik/configs", "JSCraik/Configs")
            self.assertIn(source, MODULE.execute(args)["body"])
            command.assert_not_called()

    def test_receipt_recheck_rejects_changed_recorded_pr_url(self) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        pr = {
            "number": 8,
            "url": url.replace("/7", "/8"),
            "state": "OPEN",
            "headRefOid": HEAD,
        }
        with (
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
            patch.object(GATE, "checks_lane", return_value={"status": "pass", "evidence": "checks passed"}),
        ):
            error = GATE.recheck_hosted_state(
                Path.cwd(), "review_inspection", HEAD, expected_pr_url=url
            )
        self.assertIn("PR URL changed", error or "")
        with (
            patch.object(
                GATE, "gh_pr", return_value=({**pr, "url": url, "number": 7}, None)
            ),
            patch.object(GATE, "checks_lane", return_value={"status": "pass", "evidence": "checks passed"}),
        ):
            self.assertIsNone(
                GATE.recheck_hosted_state(
                    Path.cwd(), "review_inspection", HEAD, expected_pr_url=url
                )
            )

    def test_existing_exact_request_is_reused_without_remote_mutation(self) -> None:
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            dry_run=False,
        )
        body = MODULE.request_body("codex", HEAD, False)
        url = "https://github.com/jscraik/configs/pull/7#issuecomment-9"
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ),
            patch.object(
                GATE,
                "issue_comments",
                return_value=(
                    [
                        {
                            "html_url": url,
                            "body": body,
                            "user": {"id": 93, "login": "jscraik"},
                            "created_at": "2026-10-19T12:00:00Z",
                            "updated_at": "2026-10-19T12:00:00Z",
                        }
                    ],
                    None,
                ),
            ),
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess(
                    [], 0, '{"id":93,"login":"jscraik"}', ""
                ),
            ) as command,
            patch.object(
                GATE,
                "gh_pr",
                return_value=(
                    {"state": "OPEN", "headRefOid": HEAD, "url": url.split("#")[0]},
                    None,
                ),
            ) as pr,
            patch.object(GATE, "git", return_value=HEAD) as local_head,
        ):
            result = MODULE.execute(args)
            for state in (
                {"state": "MERGED", "headRefOid": HEAD, "url": url.split("#")[0]},
                {"state": "OPEN", "headRefOid": "b" * 40, "url": url.split("#")[0]},
                {
                    "state": "OPEN",
                    "headRefOid": HEAD,
                    "url": "https://github.com/other/repo/pull/7",
                },
            ):
                pr.return_value = (state, None)
                with self.assertRaisesRegex(ValueError, "reused request"):
                    MODULE.execute(args)
            pr.return_value = (
                {"state": "OPEN", "headRefOid": HEAD, "url": url.split("#")[0]},
                None,
            )
            local_head.return_value = "b" * 40
            with self.assertRaisesRegex(ValueError, "reused request"):
                MODULE.execute(args)
        self.assertTrue(result["reused"])
        self.assertFalse(result["acceptance_claims_proven"])
        self.assertEqual(result["url"], url)
        self.assertTrue(
            all(
                call.args[0] == ["gh", "api", "user"] for call in command.call_args_list
            )
        )

    def test_rate_limited_review_can_be_retried_from_verified_old_source(self) -> None:
        source_url = "https://github.com/jscraik/configs/pull/7#issuecomment-8"
        source = {
            "html_url": source_url,
            "body": f"No findings for {HEAD}.\nAction not completed\nReview rate limited.",
            "created_at": "2020-01-01T00:00:00Z",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            retry_unavailable_source=source_url,
            dry_run=True,
        )
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ),
            patch.object(GATE, "issue_comments", return_value=([source], None)),
        ):
            body = MODULE.execute(args)["body"]
            self.assertIn(source_url, body)
            self.assertIn("@coderabbitai full review", body)
            for invalid in (
                {**source, "body": f"No findings for {HEAD}."},
                {**source, "body": source["body"].replace(HEAD, "b" * 40)},
                {**source, "created_at": "2099-01-01T00:00:00Z"},
                {**source, "updated_at": "2099-01-01T00:00:00Z"},
                {**source, "user": {"login": "jscraik", "type": "User", "id": 8}},
            ):
                with (
                    patch.object(
                        GATE, "issue_comments", return_value=([invalid], None)
                    ),
                    self.assertRaisesRegex(ValueError, "retry requires"),
                ):
                    MODULE.execute(args)

    def test_included_quota_format_retains_retry_boundaries(self) -> None:
        source_url = "https://github.com/jscraik/configs/pull/7#issuecomment-8"
        body = f"<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->\n> ## Review limit reached\n> The included review limit has been reached and this organization has disabled usage-based review continuation.\n> **Next included review available in 54 minutes.**\n> Reviewing files between {'b' * 40} and {HEAD}.\n<!-- end of auto-generated comment: rate limited by coderabbit.ai -->"
        source = {
            "html_url": source_url,
            "body": body,
            "created_at": "2020-01-01T00:00:00Z",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        self.assertEqual(MODULE.retry_sources([source], source_url, HEAD), [source])
        for invalid in (
            {**source, "created_at": "2099-01-01T00:00:00Z"},
            {**source, "updated_at": "2099-01-01T00:00:00Z"},
            {**source, "updated_at": "invalid"},
            {**source, "body": body.replace(HEAD, "c" * 40)},
            {**source, "html_url": source_url.replace("/7#", "/8#")},
            {**source, "user": {"login": "jscraik", "type": "User", "id": 8}},
            {**source, "user": {"login": "coderabbitai[bot]", "type": "User", "id": 8}},
            {**source, "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 0}},
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(MODULE.retry_sources([invalid], source_url, HEAD), [])
        for required in (
            "<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->",
            "> ## Review limit reached",
            "The included review limit has been reached",
            "this organization has disabled usage-based review continuation.",
            "**Next included review available in 54 minutes.**",
            "<!-- end of auto-generated comment: rate limited by coderabbit.ai -->",
        ):
            with self.subTest(missing=required):
                self.assertEqual(
                    MODULE.retry_sources(
                        [{**source, "body": body.replace(required, "")}],
                        source_url,
                        HEAD,
                    ),
                    [],
                )

    def test_retry_posts_once_and_reuses_its_source_bound_request(self) -> None:
        source_url = "https://github.com/jscraik/configs/pull/7#issuecomment-8"
        retry_url = "https://github.com/jscraik/configs/pull/7#issuecomment-10"
        source = {
            "html_url": source_url,
            "body": f"{HEAD}\nAction not completed\nReview rate limited.",
            "created_at": "2020-01-01T00:00:00Z",
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=False,
            clarify_source=None,
            retry_unavailable_source=source_url,
            dry_run=False,
        )
        body = MODULE.request_body("coderabbitai", HEAD, False, retry_source=source_url)
        posted = {
            "html_url": retry_url,
            "body": body,
            "user": {"id": 93, "login": "jscraik"},
            "created_at": "2020-01-01T02:00:00Z",
            "updated_at": "2020-01-01T02:00:00Z",
        }

        def command(argv, root):
            output = (
                '{"id":93,"login":"jscraik"}'
                if argv == ["gh", "api", "user"]
                else retry_url
            )
            return subprocess.CompletedProcess([], 0, output, "")

        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ),
            patch.object(
                GATE,
                "issue_comments",
                side_effect=[
                    ([source], None),
                    ([source], None),
                    ([source, posted], None),
                ],
            ) as comments,
            patch.object(GATE, "run_command", side_effect=command) as run,
            patch.object(
                GATE,
                "gh_pr",
                return_value=(
                    {
                        "state": "OPEN",
                        "headRefOid": HEAD,
                        "url": retry_url.split("#")[0],
                    },
                    None,
                ),
            ),
        ):
            self.assertEqual(MODULE.execute(args)["url"], retry_url)
            comments.side_effect = None
            comments.return_value = ([source, posted], None)
            self.assertTrue(MODULE.execute(args)["reused"])
            historical = MODULE.historical_full_request(body)
            for old_body in (historical, historical.replace("\n\n", " ", 1)):
                comments.return_value = ([source, {**posted, "body": old_body}], None)
                self.assertTrue(MODULE.execute(args)["reused"])
            self.assertEqual(
                sum(
                    call.args[0][0:3] == ["gh", "pr", "comment"]
                    for call in run.call_args_list
                ),
                1,
            )

    def test_request_deduplication_does_not_reuse_other_heads_or_unverified_urls(
        self,
    ) -> None:
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            dry_run=False,
        )
        body = MODULE.request_body("codex", HEAD, False)
        url = "https://github.com/jscraik/configs/pull/7#issuecomment-9"
        for existing in (
            {"html_url": url, "body": body.replace(HEAD, "b" * 40)},
            {"html_url": url.replace("/7#", "/8#"), "body": body},
            {"html_url": url, "body": body, "user": {"id": 94, "login": "other"}},
            {
                "html_url": url,
                "body": body,
                "user": {"id": 93, "login": "jscraik"},
                "created_at": "2026-10-19T12:00:00Z",
                "updated_at": "2026-10-19T12:01:00Z",
            },
            {"html_url": url, "body": body},
        ):
            with (
                self.subTest(existing=existing),
                patch.object(GATE, "resolve_root", return_value=Path.cwd()),
                patch.object(
                    GATE,
                    "current_worktree",
                    return_value=("topic", HEAD, "main", ".git", ".git"),
                ),
                patch.object(
                    GATE,
                    "validate_receipt",
                    return_value=(
                        {"authority": GATE.review_inspection_authority()},
                        None,
                    ),
                ),
                patch.object(
                    GATE,
                    "issue_comments",
                    side_effect=[
                        ([existing], None),
                        ([{"html_url": url, "body": body}], None),
                    ],
                ),
                patch.object(
                    GATE,
                    "run_command",
                    side_effect=lambda argv, root: subprocess.CompletedProcess(
                        [],
                        0,
                        '{"id":93,"login":"jscraik"}'
                        if argv == ["gh", "api", "user"]
                        else url,
                        "",
                    ),
                ) as command,
                patch.object(
                    GATE,
                    "gh_pr",
                    return_value=({"state": "OPEN", "headRefOid": HEAD}, None),
                ),
                patch.object(GATE, "git", return_value=HEAD),
            ):
                self.assertEqual(MODULE.execute(args)["url"], url)
                self.assertEqual(
                    sum(
                        call.args[0][0:3] == ["gh", "pr", "comment"]
                        for call in command.call_args_list
                    ),
                    1,
                )
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ),
            patch.object(
                GATE, "issue_comments", return_value=([], "inventory unavailable")
            ),
            patch.object(GATE, "run_command") as command,
        ):
            with self.assertRaisesRegex(ValueError, "inventory unavailable"):
                MODULE.execute(args)
            command.assert_not_called()

    def test_inspection_does_not_require_open_threads_or_clear_reviews(self) -> None:
        pr = {
            "number": 7,
            "url": "https://github.com/jscraik/configs/pull/7",
            "state": "OPEN",
            "headRefOid": HEAD,
        }
        with (
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
            patch.object(
                GATE,
                "reviews_lane",
                side_effect=AssertionError("must not claim clearance"),
            ),
        ):
            result = GATE.review_inspection_lane(Path.cwd(), pr, HEAD)
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["details"]["acceptance_claims_proven"])
        self.assertEqual(
            result["details"]["allowed_mutations"], ["review_request_comment"]
        )
        for mutation in (
            "source_update",
            "merge",
            "approval",
            "review_thread_resolve",
            "review_thread_reply",
        ):
            self.assertIn(mutation, result["details"]["prohibited_mutations"])

    def test_inspection_rejects_changed_identity_but_observes_failed_ci(self) -> None:
        pr = {
            "number": 7,
            "url": "https://github.com/jscraik/configs/pull/7",
            "state": "OPEN",
            "headRefOid": HEAD,
        }
        for fresh in ({**pr, "state": "MERGED"}, {**pr, "headRefOid": "b" * 40}, None):
            with patch.object(GATE, "gh_pr", return_value=(fresh, None)):
                self.assertEqual(
                    GATE.review_inspection_lane(Path.cwd(), pr, HEAD)["status"],
                    "blocked",
                )
        with (
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
            patch.object(
                GATE,
                "checks_lane",
                return_value={"status": "fail", "evidence": "failed CI"},
            ),
        ):
            self.assertIsNone(GATE.recheck_hosted_state(Path.cwd(), "review_inspection", HEAD))
            self.assertIn("checks changed", GATE.recheck_hosted_state(Path.cwd(), "update", HEAD))

    def test_fixed_request_has_no_arbitrary_body_or_mutation_mode(self) -> None:
        for reviewer in ("codex", "coderabbitai"):
            body = MODULE.request_body(reviewer, HEAD, False)
            self.assertIn(HEAD, body)
            self.assertIn("not approval, merge or thread resolution", body)
        self.assertTrue(
            MODULE.request_body("codex", HEAD, False).startswith("@codex review ")
        )
        self.assertTrue(
            MODULE.request_body("coderabbitai", HEAD, False).startswith(
                "@coderabbitai full review\n\n"
            )
        )
        with self.assertRaises(ValueError):
            MODULE.request_body("codex", HEAD, True, "source")
        with self.assertRaises(ValueError):
            MODULE.request_body("coderabbitai", HEAD, True)
        for reviewer, head in (("other", HEAD), ("codex", "short")):
            with self.assertRaises(ValueError):
                MODULE.request_body(reviewer, head, False)

    def test_consumer_preserves_explicit_non_default_base(self) -> None:
        with (
            patch(
                "sys.argv",
                [
                    "pr-review-request.py",
                    "--repo",
                    "jscraik/configs",
                    "--pr",
                    "7",
                    "--reviewer",
                    "codex",
                    "--base",
                    "release/v1",
                    "--dry-run",
                ],
            ),
            patch.object(MODULE, "execute", return_value={"status": "pass"}) as request,
            patch("builtins.print"),
        ):
            self.assertEqual(MODULE.main(), 0)
            self.assertEqual(request.call_args.args[0].base, "release/v1")
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            base="release/v1",
            receipt=Path("receipt.json"),
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            dry_run=True,
        )
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "a" * 40, Path.cwd(), Path.cwd()),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ) as validate,
        ):
            self.assertEqual(MODULE.execute(args)["status"], "pass")
            self.assertEqual(validate.call_args.args[1].base, "release/v1")

    def test_helper_fails_before_mutation_without_correct_receipt(self) -> None:
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            dry_run=False,
        )
        for payload, error in (
            ({}, "stale receipt"),
            ({"authority": {"allowed_mutations": ["merge"]}}, None),
        ):
            with (
                patch.object(GATE, "resolve_root", return_value=Path.cwd()),
                patch.object(
                    GATE,
                    "current_worktree",
                    return_value=("topic", HEAD, "main", ".git", ".git"),
                ),
                patch.object(
                    GATE, "validate_receipt", return_value=(payload, error)
                ) as receipt,
                patch.object(GATE, "run_command") as command,
            ):
                with self.assertRaises(ValueError):
                    MODULE.execute(args)
                command.assert_not_called()
                self.assertEqual(receipt.call_args.args[1].phase, "review_inspection")
                self.assertEqual(receipt.call_args.args[1].expected_pr, 7)
                self.assertEqual(
                    receipt.call_args.args[1].expected_repo, "jscraik/configs"
                )

    def test_helper_dry_run_post_readback_and_head_drift(self) -> None:
        args = argparse.Namespace(
            repo_root=Path.cwd(),
            repo="jscraik/configs",
            pr=7,
            receipt=Path("receipt.json"),
            reviewer="coderabbitai",
            clarify=True,
            clarify_source="https://github.com/jscraik/configs/pull/7#issuecomment-8",
            dry_run=True,
        )
        url = "https://github.com/jscraik/configs/pull/7#issuecomment-9"
        body = MODULE.request_body(args.reviewer, HEAD, True, args.clarify_source)
        source = {
            "html_url": args.clarify_source,
            "body": "Inspection of " + HEAD,
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        with (
            patch.object(GATE, "resolve_root", return_value=Path.cwd()),
            patch.object(
                GATE,
                "current_worktree",
                return_value=("topic", HEAD, "main", ".git", ".git"),
            ),
            patch.object(
                GATE,
                "validate_receipt",
                return_value=({"authority": GATE.review_inspection_authority()}, None),
            ),
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, url, ""),
            ) as command,
            patch.object(
                GATE,
                "issue_comments",
                side_effect=[
                    ([source], None),
                    ([source], None),
                    ([source], None),
                    ([source, {"html_url": url, "body": body}], None),
                ],
            ) as comments,
            patch.object(
                GATE,
                "gh_pr",
                return_value=({"state": "OPEN", "headRefOid": HEAD}, None),
            ) as pr,
            patch.object(GATE, "git", return_value=HEAD),
        ):
            self.assertTrue(MODULE.execute(args)["dry_run"])
            command.assert_not_called()
            args.dry_run = False
            self.assertEqual(MODULE.execute(args)["url"], url)
            self.assertEqual(
                command.call_args.args[0],
                [
                    "gh",
                    "pr",
                    "comment",
                    "7",
                    "--repo",
                    "jscraik/configs",
                    "--body",
                    body,
                ],
            )
            comments.side_effect = None
            comments.return_value = ([source], None)
            pr.return_value = ({"state": "OPEN", "headRefOid": "b" * 40}, None)
            with self.assertRaisesRegex(ValueError, "may have been posted"):
                MODULE.execute(args)
            pr.return_value = ({"state": "OPEN", "headRefOid": HEAD}, None)
            comments.return_value = ([source], None)
            with self.assertRaisesRegex(ValueError, "may have been posted"):
                MODULE.execute(args)
            for invalid in (
                [],
                [{**source, "body": "old head"}],
                [{**source, "user": {"login": "other", "type": "Bot", "id": 8}}],
            ):
                comments.return_value = (invalid, None)
                command.reset_mock()
                with self.assertRaisesRegex(ValueError, "authenticated CodeRabbit"):
                    MODULE.execute(args)
                command.assert_not_called()

    def test_failed_activity_summary_allows_retry_but_never_clearance(self) -> None:
        url = "https://github.com/jscraik/configs/pull/7"
        actor = {"id": 93, "login": "jscraik"}
        bot = {"login": "chatgpt-codex-connector[bot]", "type": "Bot", "id": 8}
        args = argparse.Namespace(
            repo="jscraik/configs",
            pr=7,
            reviewer="codex",
            clarify=False,
            clarify_source=None,
            retry_source=url + "#issuecomment-10",
        )
        prior = {
            "html_url": url + "#issuecomment-9",
            "user": actor,
            "body": MODULE.request_body("codex", HEAD, False),
            "created_at": "2026-10-19T14:12:58Z",
            "updated_at": "2026-10-19T14:12:58Z",
        }
        failure = {
            "html_url": args.retry_source,
            "user": bot,
            "body": "You have reached your Codex usage limits for code reviews. You can see your limits in the [Codex usage dashboard](https://chatgpt.com/codex/cloud/settings/usage).",
            "created_at": "2026-10-19T14:13:15Z",
            "updated_at": "2026-10-19T14:13:15Z",
        }
        state = {
            "code_review": {
                "commit_sha": HEAD,
                "has_any_findings": True,
                "has_unresolved_findings": True,
                "status": "failed",
            },
            "security_review": {
                "commit_sha": "b" * 40,
                "has_any_findings": False,
                "has_unresolved_findings": False,
                "status": "completed",
            },
        }
        metadata = {
            "blockingSeverityThreshold": "P0",
            "headSha": "b" * 40,
            "mergeGateEnabled": False,
            "pullRequestNumber": 7,
            "repository": "jscraik/configs",
            "status": "completed",
        }
        body = (
            "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "
            + json.dumps(state)
            + " -->\n<!-- codex-security-review:v1 "
            + json.dumps(metadata)
            + ' -->\n## Codex Review Summary\n\nThis comment shows the latest Codex review activity on this pull request.\n\n| Review | Status | Commit | Review trigger |\n| --- | --- | --- | --- |\n| 📝 **Code Review** | ⚠️ **Failed** <relative-time datetime="2026-10-19T14:13:08.508330Z">2026-10-19T14:13:08.508330Z</relative-time> | `aaaaaaa` | Manual request |\n| 🔒 **Security Review** | ✅ **Completed** <relative-time datetime="2026-10-19T10:47:20.538154Z">2026-10-19T10:47:20.538154Z</relative-time> | `bbbbbbb` | Draft marked ready |\n\n<details> <summary>ℹ️ About Codex in GitHub</summary> <br/>\n[Your team has set up Codex to review pull requests in this repo](https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you\n- Open a pull request for review\n- Mark a draft as ready\n- Comment "@codex review" or "@codex security review".\n\nCodex reacts with 👀 while any review is running, comments if it has suggestions, and reacts with 👍 once all reviews finish with no findings.\n</details>'
        )
        summary = {
            "html_url": url + "#issuecomment-8",
            "user": bot,
            "body": body,
            "created_at": "2026-10-19T10:44:42Z",
            "updated_at": "2026-10-19T14:13:11Z",
        }
        pr = {"state": "OPEN", "headRefOid": HEAD, "url": url, "reviews": []}
        with (
            patch.object(
                GATE,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, json.dumps(actor), ""),
            ),
            patch.object(GATE, "gh_pr", return_value=(pr, None)),
        ):
            self.assertEqual(
                MODULE.quota_retry_source(
                    Path.cwd(), args, HEAD, [summary, prior, failure]
                ),
                failure,
            )
            self.assertFalse(
                GATE._bot_review_is_acceptable({**summary, "state": "COMMENTED"}, HEAD)
            )
            coarse_summary = {**summary, "updated_at": "2026-10-19T14:13:08Z"}
            self.assertEqual(
                MODULE.quota_retry_source(
                    Path.cwd(), args, HEAD, [coarse_summary, prior, failure]
                ),
                failure,
            )
            self.assertFalse(
                GATE._bot_review_is_acceptable(
                    {**coarse_summary, "state": "COMMENTED"}, HEAD
                )
            )
            for changed_body in (
                body.replace("10:47:20.538154Z", "14:13:09.508330Z"),
                body.replace("`bbbbbbb`", "`ccccccc`"),
                body.replace(
                    json.dumps(metadata), json.dumps({**metadata, "extra": True})
                ),
                body.replace(
                    json.dumps(metadata),
                    json.dumps(
                        {
                            key: value
                            for key, value in metadata.items()
                            if key != "headSha"
                        }
                    ),
                ),
                body.replace(
                    '"repository": "jscraik/configs"',
                    '"repository": "jscraik/configs", "repository": "jscraik/configs"',
                ),
                body.replace("14:13:08.508330Z", "14:12:57.508330Z"),
                body.replace(
                    json.dumps(metadata), json.dumps({**metadata, "repository": 7})
                ),
            ):
                with (
                    self.subTest(envelope=changed_body),
                    self.assertRaisesRegex(ValueError, "another Codex event"),
                ):
                    MODULE.quota_retry_source(
                        Path.cwd(),
                        args,
                        HEAD,
                        [{**summary, "body": changed_body}, prior, failure],
                    )
            for case_args, case_summary in (
                (
                    argparse.Namespace(**vars(args) | {"repo": "JSCRAIK/CONFIGS"}),
                    summary,
                ),
                (
                    args,
                    {
                        **summary,
                        "html_url": summary["html_url"].replace(
                            "jscraik/configs", "JSCRAIK/CONFIGS"
                        ),
                    },
                ),
                (
                    args,
                    {
                        **summary,
                        "body": body.replace(
                            '"repository": "jscraik/configs"',
                            '"repository": "JSCRAIK/CONFIGS"',
                        ),
                    },
                ),
            ):
                with self.subTest(repo=case_args.repo, summary=case_summary):
                    self.assertEqual(
                        MODULE.quota_retry_source(
                            Path.cwd(), case_args, HEAD, [case_summary, prior, failure]
                        ),
                        failure,
                    )
            for changed in (
                {**summary, "updated_at": "2026-10-19T14:13:07Z"},
                {**summary, "updated_at": "2026-10-19T14:13:08.100000Z"},
                {**summary, "body": body + "\nFix an authorization defect."},
                {**summary, "body": body.replace(HEAD, "c" * 40)},
                {
                    **summary,
                    "body": body.replace(
                        '"code_review":', '"code_review": {}, "code_review":', 1
                    ),
                },
                {
                    **summary,
                    "body": body.replace(
                        '"repository": "jscraik/configs"', '"repository": "other/repo"'
                    ),
                },
                {
                    **summary,
                    "body": body.replace('"status": "failed"', '"status": "completed"'),
                },
                {
                    **summary,
                    "body": body.replace(
                        '"has_any_findings": true', '"has_any_findings": 1'
                    ),
                },
                {**summary, "body": body.replace("`aaaaaaa`", "`ccccccc`")},
                {**summary, "user": {**bot, "id": 99}},
                {**summary, "html_url": url.replace("/7", "/8") + "#issuecomment-8"},
                {**summary, "updated_at": "2026-10-19T14:13:16Z"},
                {
                    **summary,
                    "body": body.replace("14:13:08.508330Z", "14:13:12.508330Z"),
                },
            ):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    MODULE.quota_retry_source(
                        Path.cwd(), args, HEAD, [changed, prior, failure]
                    )
