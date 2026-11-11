"""Exercise structured provider evidence through the readiness entrypoint."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex.scripts.tests.test_pr_readiness import MODULE

ASSETS = "https://storage.googleapis.com/coderabbit_public_assets/"


def details(title: str, body: str) -> str:
    return f"<details><summary><strong>{title}</strong></summary><dl><dd><br>\n{body}\n</dd></dl></details>"


def section(name: str, body: str) -> str:
    return f"<!-- {name}_start -->\n{body}\n<!-- {name}_end -->"


class StructuredCodeRabbitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.head, self.base = "a" * 40, "b" * 40
        self.slug = "example/project"
        self.run_id = "11111111-2222-4333-8444-555555555555"
        self.pr = {"number": 7, "url": f"https://github.com/{self.slug}/pull/7", "headRefOid": self.head,
                   "baseRefOid": self.base, "headRefName": "codex/test", "reviews": [], "author": {"login": "owner"}}
        self.review_url = f"https://app.coderabbit.ai/change-stack/{self.slug}/pull/7?scope=fixture"
        self.config = (f"- **Configuration used**: Repository: {self.slug}/.coderabbit.yaml\n"
                       "- **Review profile**: ASSERTIVE\n- **Plan**: Essentials\n"
                       f"- **Run ID**: `{self.run_id}`\n")
        info = details("⚙️ Run configuration", self.config) + details("📥 Commits",
            f"Reviewing files that changed from the base of the PR and between {self.base} and {self.head}.")
        info += details("📒 Files selected for processing: 1", "* `code.py`")
        recent = "No actionable comments were generated in the recent review.\n" + details("ℹ️ Recent review info", info)
        context = details("Additional context used", details("Remote MCP Linear", "Task context from the linked issue."))
        recent += section("review_details", details("📜 Recent review details", context))
        coverage = json.dumps({"sourceCommitId": self.head, "coveredCommitId": self.head, "kind": "reviewed"})
        risk = (f"<!-- final_review_risk_label\n**Merge Risk:** **⚪ Minimal** · up to `{self.head[:5]}`\n-->\n"
                f"<!-- final_review_risk_coverage:{coverage} -->\nA bounded configuration change.")
        table = ("| Check name | Status | Explanation |\n| --- | --- | --- |\n"
                 f"| Safety | ![Passed]({ASSETS}pre-merge-checks-passed.svg) | Contract preserved. |\n")
        passed = (f'Pre-merge checks: <sup><picture><img src="{ASSETS}pre-merge-checks-counter-passed-14-v2.svg" '
                  'width="14" height="14" align="middle" alt="Passed" title="Passed"></picture></sup> 1')
        self.body = ("<!-- coderabbit-ai-generated:v1 -->\n"
                     "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->\n"
                     + section("review_stack_entry", f'<a href="{self.review_url}&amp;cs_source=review_comment">Explain Change →</a>')
                     + section("recent_review", recent)
                     + section("walkthrough", details("Summary", "The configuration now records complete evidence."))
                     + f'<details><summary><strong>Merge Risk:</strong> <strong>Minimal</strong> · up to <code>{self.head[:5]}</code></summary><dl><dd><br>\n'
                     + section("final_review_risk", risk) + "</dd></dl></details>"
                     + section("pre_merge_checks_walkthrough", details(passed, table + details("Full details: Safety", "**Explanation**\nContract preserved."))))
        self.entry = {"id": 42, "node_id": "IC_fixture", "user": {"id": 136622811, "login": "coderabbitai[bot]", "type": "Bot"},
                      "body": self.body, "created_at": "2026-11-01T10:00:00Z", "updated_at": "2026-11-01T10:02:00Z",
                      "html_url": f"{self.pr['url']}#issuecomment-42"}
        bot = {"login": "coderabbitai", "__typename": "Bot"}
        pending = ("<!-- This is an auto-generated comment: review in progress by coderabbit.ai -->\n"
                   + details("Review info", details("Run configuration", self.config + f"- **Commit**: [{self.head[:7]}](<https://github.com/{self.slug}/commit/{self.head}>)\n"))
                   + "<!-- end of auto-generated comment: review in progress by coderabbit.ai -->")
        edits = [{"id": "UCE_terminal", "createdAt": self.entry["updated_at"], "updatedAt": self.entry["updated_at"],
                  "editedAt": self.entry["updated_at"], "editor": bot, "deletedAt": None, "diff": self.body},
                 {"id": "UCE_start", "createdAt": "2026-11-01T10:02:00Z", "updatedAt": "2026-11-01T10:02:00Z",
                  "editedAt": self.entry["created_at"], "editor": bot, "deletedAt": None, "diff": pending}]
        self.history = {"id": self.entry["node_id"], "databaseId": 42, "url": self.entry["html_url"], "body": self.body,
                        "createdAt": self.entry["created_at"], "updatedAt": self.entry["updated_at"],
                        "lastEditedAt": self.entry["updated_at"], "includesCreatedEdit": True, "author": bot,
                        "userContentEdits": {"totalCount": 2, "pageInfo": {"hasNextPage": False}, "nodes": edits}}
        check_summary = ("Result: Success - Review completed\nRun ID: `aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee`\n"
                         f"CodeRabbit Review: [Open CodeRabbit Review]({self.review_url})\n\n| Step | Status | Time |\n| --- | --- | --- |\n"
                         + "".join(f"| {step} | Completed | 1s |\n" for step in (
                             "Prepare review scope", "Prepare repository workspace", "Run analysis checks", "Generate review feedback", "Publish review results"))
                         + "| Time taken | | 2m |")
        self.check = {"id": 50, "name": "CodeRabbit", "head_sha": self.head, "app": {"id": 347564, "slug": "coderabbitai"},
                      "status": "completed", "conclusion": "success", "started_at": "2026-11-01T10:00:02Z",
                      "completed_at": "2026-11-01T10:02:03Z", "details_url": self.review_url,
                      "pull_requests": [{"number": 7, "url": f"https://api.github.com/repos/{self.slug}/pulls/7",
                                         "head": {"sha": self.head, "ref": "codex/test", "repo": {"url": f"https://api.github.com/repos/{self.slug}"}},
                                         "base": {"sha": self.base, "repo": {"url": f"https://api.github.com/repos/{self.slug}"}}}],
                      "output": {"title": "Finished", "summary": check_summary, "text": None, "annotations_count": 0}}

    def candidate(self, *, body=None, checks=None, history=None, snapshot=True):
        entry, hist = copy.deepcopy(self.entry), copy.deepcopy(self.history if history is None else history)
        if body is not None:
            entry["body"] = hist["body"] = hist["userContentEdits"]["nodes"][0]["diff"] = body
        selected = [self.check] if checks is None else checks

        def command(args, *_args, **_kwargs):
            if args[:2] == ["git", "merge-base"]:
                return subprocess.CompletedProcess(args, 0, self.base, "")
            if args[:3] == ["git", "diff", "--name-only"]:
                return subprocess.CompletedProcess(args, 0, "code.py\0", "")
            if args[:3] == ["gh", "api", "graphql"]:
                return subprocess.CompletedProcess(args, 0, json.dumps({"data": {"node": hist}}), "")
            if args[:2] == ["gh", "api"] and "check-runs" in args[2]:
                return subprocess.CompletedProcess(args, 0, json.dumps([{"check_runs": selected}]), "")
            raise AssertionError(f"Unexpected command: {args}")

        with (patch.object(MODULE, "repository_slug", return_value=(self.slug, None)),
              patch.object(MODULE, "changed_paths", return_value=["code.py"]),
              patch.object(MODULE, "run_command", side_effect=command),
              patch.object(MODULE, "_codex_completion_snapshot", return_value=(snapshot, None if snapshot else "changed"))):
            return MODULE.coderabbit_completion_review(Path.cwd(), self.pr, self.head, [], [entry])

    def test_structured_summary_qualifies_with_distinct_native_check_id_and_retained_text(self):
        result, error = self.candidate()
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["created_at"], self.entry["updated_at"])
        self.assertEqual(result["completion_evidence"]["summary_body"], self.body)
        picture = f'<picture><img src="{ASSETS}review-stack-buttons-v1/explain-change.svg" alt="Explain Change →" height="32"></picture>'
        self.assertIsNotNone(self.candidate(body=self.body.replace('>Explain Change →</a>', '>' + picture + '</a>'))[0])

    def test_incomplete_and_findings_content_does_not_qualify(self):
        for body in (self.body + "\nUnknown review section", self.body.replace("No actionable comments", "Actionable comments posted: 1"),
                     self.body.replace("Task context", "<!-- cr-indicator-types:potential_issue --> Task context"),
                     self.body.replace("Recent review info", "Review in progress"),
                     self.body.replace("pre-merge-checks-passed.svg", "pre-merge-checks-failed.svg"),
                     self.body.replace("⚪ Minimal", "🔴 High"),
                     self.body.replace("Full details: Safety", "Full details: Unknown"),
                     self.body.replace("processing: 1", "processing: 2")):
            with self.subTest(body=body):
                self.assertIsNone(self.candidate(body=body)[0])

    def test_native_identity_completion_and_ambiguity_fail_closed(self):
        for key, value in (("head_sha", self.base), ("app", {"id": 99, "slug": "coderabbitai"}),
                           ("status", "in_progress"), ("conclusion", "failure"), ("pull_requests", []),
                           ("completed_at", "2026-11-01T10:04:00Z"), ("started_at", "2026-11-01T10:01:00Z")):
            with self.subTest(key=key):
                self.assertIsNone(self.candidate(checks=[{**self.check, key: value}])[0])
        self.assertIsNone(self.candidate(checks=[self.check, {**self.check, "id": 51}])[0])
        changed = copy.deepcopy(self.check)
        changed["output"]["annotations_count"] = 1
        self.assertIsNone(self.candidate(checks=[changed])[0])

    def test_unverifiable_or_edited_history_cannot_move_clearance(self):
        for change in ("deleted", "editor", "pending_run", "terminal_time", "truncated", "unknown_diff"):
            hist = copy.deepcopy(self.history)
            nodes = hist["userContentEdits"]["nodes"]
            if change == "deleted":
                nodes[1]["deletedAt"] = self.entry["updated_at"]
            elif change == "editor":
                nodes[0]["editor"] = {"login": "owner", "__typename": "User"}
            elif change == "pending_run":
                nodes[1]["diff"] = nodes[1]["diff"].replace(self.run_id, "other")
            elif change == "terminal_time":
                nodes[0]["editedAt"] = "2026-11-01T10:03:00Z"
            elif change == "truncated":
                hist["userContentEdits"]["pageInfo"]["hasNextPage"] = True
            else:
                nodes[0]["diff"] = "unrecognised edit representation"
            with self.subTest(change=change):
                self.assertIsNone(self.candidate(history=hist)[0])
        self.assertIsNone(self.candidate(snapshot=False)[0])


    def notification(self):
        body = ('<!-- coderabbit-ai-generated:v1 -->\n\n'
                '<!-- This is an auto-generated reply by CodeRabbit -->\n'
                '<!-- CodeRabbit review command invocation: v2:' + 'a' * 64 + ' -->\n'
                '<details>\n<summary>Action performed</summary>\n<dl>\n<dd>\n<br>\n\n'
                'Full review finished.\n\n</dd>\n</dl>\n</details>')
        return {**self.entry, "id": 43, "body": body,
                "created_at": "2026-11-01T10:02:06Z", "updated_at": "2026-11-01T10:02:06Z"}

    def review_lane(self, *, notice=None, codex=True, unresolved=0, decision="", inline=None):
        completion, error = self.candidate()
        self.assertIsNone(error)
        entries = [self.entry, self.notification() if notice is None else notice]
        review = {"state": "COMMENTED", "commit_id": self.head,
                  "user": {"login": "chatgpt-codex-connector[bot]", "type": "Bot"},
                  "submitted_at": "2026-11-01T10:02:10Z", "body": f"No findings for {self.head}."}
        pr = {**self.pr, "reviews": [review] if codex else [], "reviewDecision": decision}
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": unresolved, "truncated": False}, None)),
              patch.object(MODULE, "review_comments", return_value=(inline or [], None)),
              patch.object(MODULE, "issue_comments", return_value=(entries, None)),
              patch.object(MODULE, "codex_completion_review", return_value=(None, None)),
              patch.object(MODULE, "coderabbit_completion_review", return_value=(completion, None)),
              patch.object(MODULE, "review_requirement", return_value={"required_bot_review_count": 2})):
            return MODULE.reviews_lane(Path.cwd(), pr, self.head)

    def test_finished_notification_is_neutral_and_never_clearance(self):
        self.assertEqual(self.review_lane()["status"], "pass")
        self.assertNotEqual(self.review_lane(codex=False)["status"], "pass")
        self.assertFalse(MODULE._bot_review_is_acceptable({**self.notification(), "state": "COMMENTED"}, self.head))
        for changes in ({"body": self.notification()["body"] + "\nP1: unsafe input"},
                        {"body": self.notification()["body"].replace("Full review finished.", "Review failed.")},
                        {"user": {**self.entry["user"], "type": "User"}},
                        {"user": {**self.entry["user"], "id": 1}},
                        {"author": {"login": "coderabbitai", "type": "User"}}):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.review_lane(notice={**self.notification(), **changes})["status"], "pass")

    def test_structured_completion_keeps_threads_changes_requested_and_later_findings_blocking(self):
        self.assertNotEqual(self.review_lane(unresolved=1)["status"], "pass")
        self.assertNotEqual(self.review_lane(decision="CHANGES_REQUESTED")["status"], "pass")
        for timestamp in (self.entry["updated_at"], "2026-11-01T10:02:11Z"):
            finding = {"user": self.entry["user"], "body": "P1: unsafe input",
                       "commit_id": self.head, "created_at": timestamp}
            self.assertNotEqual(self.review_lane(inline=[finding])["status"], "pass")

    def test_isolated_gate_import_does_not_need_repository_python_path(self):
        with tempfile.TemporaryDirectory() as directory:
            entrypoint = Path(MODULE.__file__).resolve()
            isolated = Path(directory) / entrypoint.name
            isolated.write_bytes(entrypoint.read_bytes())
            (isolated.parent / 'migration_scope.py').write_bytes(entrypoint.with_name('migration_scope.py').read_bytes())
            for script in (entrypoint, isolated):
                result = subprocess.run([sys.executable, "-I", str(script), "--help"],
                                        cwd=directory, capture_output=True, text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_context_cannot_hide_provider_tool_failures(self):
        for text in ("<!-- This is an auto-generated comment: all tool run failures by coderabbit.ai -->\nError: failed\n<!-- end of auto-generated comment: all tool run failures by coderabbit.ai -->",
                     "Review incomplete", "<!-- cr-indicator-types:potential_issue -->"):
            with self.subTest(text=text):
                self.assertIsNone(self.candidate(body=self.body.replace("Task context from the linked issue.", text))[0])


if __name__ == "__main__":
    unittest.main()
