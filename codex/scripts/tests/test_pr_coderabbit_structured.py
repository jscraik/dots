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
        if self._testMethodName.startswith("test_dots_notifier_assertion"):
            self.head = "0246dcea7306d2fc88e064a6131edce786370353"
            self.slug = "jscraik/dots"
        if self._testMethodName in {
            "test_observed_grammar_note_and_placeholder_controls_keep_native_binding",
            "test_observed_grammar_and_controls_reject_changed_or_unknown_findings",
        }:
            self.head = "4d940dd7d9d74459cbea0da683814fe218330e21"
            self.slug = "jscraik/rSearch"
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

    def candidate(self, *, body=None, checks=None, history=None, snapshot=True, paths=None, pull_inventory=()):
        paths = ["code.py"] if paths is None else paths
        entry, hist = copy.deepcopy(self.entry), copy.deepcopy(self.history if history is None else history)
        if body is not None:
            entry["body"] = hist["body"] = hist["userContentEdits"]["nodes"][0]["diff"] = body
        selected = [self.check] if checks is None else checks
        pull_responses = iter(pull_inventory)

        def command(args, *_args, **_kwargs):
            if args[:2] == ["git", "merge-base"]:
                return subprocess.CompletedProcess(args, 0, self.base, "")
            if args[:3] == ["git", "diff", "--name-only"]:
                return subprocess.CompletedProcess(args, 0, "\0".join(paths) + "\0", "")
            if args[:3] == ["gh", "api", "graphql"]:
                return subprocess.CompletedProcess(args, 0, json.dumps({"data": {"node": hist}}), "")
            if args[:2] == ["gh", "api"] and "check-runs" in args[2]:
                return subprocess.CompletedProcess(args, 0, json.dumps([{"check_runs": selected}]), "")
            if args == ["gh", "api", f"repos/{self.slug}/commits/{self.head}/pulls?per_page=100",
                        "--hostname", "github.com", "--paginate", "--slurp"]:
                pages = next(pull_responses, None)
                return subprocess.CompletedProcess(args, int(pages is None), json.dumps(pages), "")
            raise AssertionError(f"Unexpected command: {args}")

        with (patch.object(MODULE, "repository_slug", return_value=(self.slug, None)),
              patch.object(MODULE, "changed_paths", return_value=paths),
              patch.object(MODULE, "run_command", side_effect=command),
              patch.object(MODULE, "_codex_completion_snapshot", return_value=(snapshot, None if snapshot else "changed"))):
            return MODULE.coderabbit_completion_review(Path.cwd(), self.pr, self.head, [], [entry])

    def test_structured_summary_qualifies_with_distinct_native_check_id_and_retained_text(self):
        result, error = self.candidate()
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["created_at"], self.entry["updated_at"])
        self.assertEqual(result["completion_evidence"]["check_pr_association"], "check_run")
        self.assertEqual(result["completion_evidence"]["summary_body"], self.body)
        picture = f'<picture><img src="{ASSETS}review-stack-buttons-v1/explain-change.svg" alt="Explain Change →" height="32"></picture>'
        self.assertIsNotNone(self.candidate(body=self.body.replace('>Explain Change →</a>', '>' + picture + '</a>'))[0])

    def test_empty_native_pr_list_uses_one_independently_bound_pull(self):
        check = {**self.check, "pull_requests": []}
        pull = {**self.check["pull_requests"][0], "html_url": self.pr["url"]}
        result, error = self.candidate(checks=[check], pull_inventory=([[pull]], [[pull]]))
        self.assertIsNone(error)
        self.assertEqual(result["completion_evidence"]["check_pr_association"], "commit_pull_inventory")
        self.assertEqual(result["created_at"], self.entry["updated_at"])

        candidate_kwargs = {"checks": [check], "pull_inventory": ([[pull]], [[pull]])}
        self.assertEqual(self.review_lane(candidate_kwargs=candidate_kwargs)["status"], "pass")
        self.assertNotEqual(self.review_lane(candidate_kwargs=candidate_kwargs, codex=False)["status"], "pass")
        self.assertNotEqual(self.review_lane(candidate_kwargs=candidate_kwargs, unresolved=1)["status"], "pass")
        finding = {"user": self.entry["user"], "body": "P1: unsafe input",
                   "commit_id": self.head, "created_at": self.entry["updated_at"]}
        self.assertNotEqual(self.review_lane(candidate_kwargs=candidate_kwargs, inline=[finding])["status"], "pass")

        result, error = self.candidate(checks=[check], pull_inventory=([[pull]], [[pull], [pull]]))
        self.assertIsNone(result)
        self.assertIn("inventory changed", error)

    def test_older_empty_pr_list_does_not_add_a_lookup_to_selected_native_check(self):
        older = {**self.check, "id": 51, "pull_requests": [],
                 "completed_at": "2026-11-01T09:59:00Z"}
        pull = {**self.check["pull_requests"][0], "html_url": self.pr["url"]}
        result, error = self.candidate(checks=[older, self.check], pull_inventory=([[pull]], [[]]))
        self.assertIsNone(error)
        self.assertEqual(result["completion_evidence"]["check_pr_association"], "check_run")

    def test_empty_native_pr_list_rejects_unavailable_or_unbound_inventory(self):
        check = {**self.check, "pull_requests": []}
        pull = {**self.check["pull_requests"][0], "html_url": self.pr["url"]}
        for pages in (None, [], [[]], {"entries": [pull]}, [[pull], [pull]],
                      [[{**pull, "number": 8}]], [[{**pull, "html_url": self.pr["url"] + "8"}]],
                      [[{**pull, "head": {**pull["head"], "sha": self.base}}]],
                      [[{**pull, "base": {**pull["base"], "sha": self.head}}]],
                      [[{**pull, "head": {**pull["head"], "repo": {"url": "https://api.github.com/repos/fork/project"}}}]]):
            with self.subTest(pages=pages):
                self.assertIsNone(self.candidate(checks=[check], pull_inventory=(pages, pages))[0])
        for invalid in (
            {**check, "pull_requests": None},
            {**check, "pull_requests": [{**pull, "number": 8}]},
            {**check, "conclusion": "failure"},
            {**check, "app": {**check["app"], "id": 123}},
            {**check, "output": {**check["output"], "annotations_count": 1}},
        ):
            with self.subTest(check=invalid):
                self.assertIsNone(self.candidate(checks=[invalid], pull_inventory=([[pull]], [[pull]]))[0])
        incremental = self.body.replace(f"between {self.base} and", f"between {'c' * 40} and")
        self.assertIsNone(self.candidate(body=incremental, checks=[check], pull_inventory=([[pull]], [[pull]]))[0])

    def test_top_level_status_is_placed_in_structured_metadata_for_full_caller(self):
        verdict = "No actionable comments were generated in the recent review."
        body = self.body.replace('<!-- recent_review_start -->\n' + verdict + '\n',
            '<!-- recent_review_start -->\n<h6>\n').replace(
                '<!-- recent_review_end -->', '</h6>\n<!-- recent_review_end -->')
        header = '<!-- This is an auto-generated comment: summarize by coderabbit.ai -->'
        body = body.replace(header, header + '\n' + section('recent_review_status', verdict), 1)
        result, error = self.candidate(body=body)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result['completion_evidence']['summary_body'], body)
        for bad in (body.replace(verdict, verdict + ' Fix another concern.'),
                    body.replace(section('recent_review_status', verdict),
                                 section('recent_review_status', verdict) * 2),
                    body.replace(header, header + '\nUnknown finding', 1)):
            with self.subTest(bad=bad):
                self.assertIsNone(self.candidate(body=bad)[0])

    def test_scopeless_navigation_joins_only_authenticated_check_scope(self):
        body = self.body.replace("?scope=fixture&amp;cs_source=review_comment", "?cs_source=review_comment")
        result, error = self.candidate(body=body)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["completion_evidence"]["review_url"], self.review_url)
        competing = copy.deepcopy(self.check)
        competing["id"] += 1
        competing["details_url"] = self.review_url.replace("fixture", "other")
        self.assertIsNone(self.candidate(body=body, checks=[self.check, competing])[0])
        for suffix in ("&amp;cs_source=review_comment", "#fragment", "&amp;unknown=value"):
            with self.subTest(suffix=suffix):
                self.assertIsNone(self.candidate(body=body.replace("?cs_source=review_comment", "?cs_source=review_comment" + suffix))[0])
        for url in (self.review_url + "&scope=other", self.review_url + "#fragment", self.review_url + "&unknown=value"):
            check = copy.deepcopy(self.check)
            check["details_url"] = url
            self.assertIsNone(self.candidate(body=body, checks=[check])[0])

    def test_exact_self_check_timeout_is_retained_context_not_completion(self):
        marker = "<summary><strong>Additional context used</strong></summary>"
        timeout = details("Context from checks skipped due to timeout: 1", "* GitHub Check: CodeRabbit")
        body = self.body.replace("<details>" + marker, timeout + "<details>" + marker)
        result, error = self.candidate(body=body)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["completion_evidence"]["summary_body"], body)
        check = copy.deepcopy(self.check)
        check["conclusion"] = "failure"
        self.assertIsNone(self.candidate(body=body, checks=[check])[0])
        for bad in (timeout + timeout, timeout.replace(": 1", ": 2"), timeout.replace("CodeRabbit", "CodeRabbit\nExtra prose")):
            with self.subTest(bad=bad):
                self.assertIsNone(self.candidate(body=body.replace(timeout, bad))[0])

    def test_missing_ci_context_does_not_erase_current_ci_or_native_review_failures(self):
        marker = "<details><summary><strong>Additional context used</strong></summary>"
        timeout = details("Context from checks skipped due to timeout: 2",
                          "* GitHub Check: CodeRabbit\n* GitHub Check: Full repository validation")
        body = self.body.replace(marker, timeout + marker)
        result, error = self.candidate(body=body)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["completion_evidence"]["summary_body"], body)
        for state, expected in (("FAILURE", "fail"), ("PENDING", "blocked")):
            with self.subTest(state=state):
                pr = {**self.pr, "statusCheckRollup": [{"name": "Full repository validation", "state": state}]}
                self.assertEqual(MODULE.observed_checks_lane(pr, self.head)["status"], expected)
        self.assertNotEqual(MODULE.checks_lane({**self.pr, "statusCheckRollup": []}, self.head)["status"], "pass")
        failed = copy.deepcopy(self.check)
        failed["conclusion"] = "failure"
        self.assertIsNone(self.candidate(body=body, checks=[failed])[0])
        self.assertIsNone(self.candidate(body=body, checks=[])[0])
        stale = copy.deepcopy(self.check)
        stale["head_sha"] = self.base
        self.assertIsNone(self.candidate(body=body, checks=[stale])[0])
        for bad in (timeout.replace(": 2", ": 1"), timeout.replace(": 2", ": 0"),
                    timeout.replace("Full repository validation", "CodeRabbit"),
                    timeout.replace("Full repository validation", "Full repository validation\nFinding: unsafe"),
                    timeout.replace("Full repository validation", "<b>Full repository validation</b>"),
                    timeout + details("Context from checks skipped due to timeout: 1", "* GitHub Check: CodeQL")):
            with self.subTest(bad=bad):
                self.assertIsNone(self.candidate(body=body.replace(timeout, bad))[0])

    def approval_policy(self):
        return section("approval_policy_info", details("Automatic approval policy",
            f"Commit: `{self.head[:12]}`.\n\n"
            "| Setting | Effective value | Source |\n| :--- | :--- | :--- |\n"
            "| Automatic approvals | Enabled | Global configuration |\n"
            "| Merge risk | Minimal | Global configuration |\n"
            "| Security risk | Not set | Global configuration |\n\n"
            "**Not set** means no limit was configured after inheritance. Use `@coderabbitai configuration` to inspect the resolved settings and their sources."))

    def refreshed_history(self, body):
        hist = copy.deepcopy(self.history)
        hist["body"] = body
        hist["updatedAt"] = hist["lastEditedAt"] = "2026-11-01T10:03:00Z"
        old = hist["userContentEdits"]["nodes"][0]
        hist["userContentEdits"]["nodes"].insert(0, {
            **old, "id": "UCE_refresh", "diff": body,
            "createdAt": hist["updatedAt"], "updatedAt": hist["updatedAt"],
            "editedAt": hist["updatedAt"]})
        hist["userContentEdits"]["totalCount"] = 3
        return hist

    def test_policy_metadata_refresh_retains_original_clearance_time(self):
        body = self.body.replace("<details><summary><strong>⚙️ Run configuration", self.approval_policy() + "\n<details><summary><strong>⚙️ Run configuration", 1)
        hist = self.refreshed_history(body)
        self.entry["updated_at"] = hist["updatedAt"]
        result, error = self.candidate(body=body, history=hist)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["created_at"], "2026-11-01T10:02:00Z")
        self.assertEqual(result["completion_evidence"]["summary_body"], body)

    def delayed_policy_refresh(self):
        marker = "<!-- review_info_content -->"
        original = self.body.replace("<details><summary><strong>⚙️ Run configuration",
            marker + "\n<details><summary><strong>⚙️ Run configuration", 1)
        self.history["body"] = self.history["userContentEdits"]["nodes"][0]["diff"] = original
        body = original.replace(marker + "\n", marker + "\n\n" + self.approval_policy() + "\n\n", 1)
        history = self.refreshed_history(body)
        timestamp = "2026-11-01T10:02:07Z"
        history["updatedAt"] = history["lastEditedAt"] = self.entry["updated_at"] = timestamp
        history["userContentEdits"]["nodes"][0].update(
            createdAt=timestamp, updatedAt=timestamp, editedAt=timestamp)
        check = {**self.check, "completed_at": "2026-11-01T10:02:09Z"}
        return body, history, check

    def test_delayed_publication_joins_metadata_refresh_without_moving_clearance(self):
        body, history, check = self.delayed_policy_refresh()
        result, error = self.candidate(body=body, history=history, checks=[check])
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["created_at"], "2026-11-01T10:02:00Z")
        self.assertEqual(result["completion_evidence"]["terminal_edit_id"], "UCE_terminal")
        self.assertEqual(result["completion_evidence"]["latest_edit_id"], "UCE_refresh")
        self.assertEqual(result["completion_evidence"]["publication_edit_id"], "UCE_refresh")
        self.assertEqual(result["completion_evidence"]["publication_at"], "2026-11-01T10:02:07Z")
        self.assertEqual(result["completion_evidence"]["summary_body"], body)

    def test_publication_windows_preserve_ambiguity_and_the_five_second_bound(self):
        body, history, check = self.delayed_policy_refresh()
        late = {**check, "completed_at": "2026-11-01T10:02:13Z"}
        self.assertIsNone(self.candidate(body=body, history=history, checks=[late])[0])
        for competing in (self.check, {**self.check, "conclusion": "failure"},
                          {**self.check, "app": {"id": 99, "slug": "other"}}):
            with self.subTest(competing=competing):
                self.assertIsNone(self.candidate(body=body, history=history, checks=[check, competing])[0])
        # One record in two overlapping windows is still one record.
        self.assertIsNotNone(self.candidate(body=body, history=history, checks=[self.check])[0])

    def test_metadata_gap_handling_cannot_normalise_business_text_or_unknown_padding(self):
        body, history, check = self.delayed_policy_refresh()
        for changed in (body.replace("Contract preserved.", "Contract  preserved."),
                        body.replace("<!-- review_info_content -->\n\n", "<!-- review_info_content -->\n\nUnknown finding\n"),
                        body.replace(self.approval_policy() + "\n\n", self.approval_policy() + "\n\n\n")):
            with self.subTest(changed=changed):
                self.assertIsNone(self.candidate(body=changed, history=history, checks=[check])[0])

    def test_delayed_publication_cannot_clear_intervening_or_same_second_findings(self):
        body, history, check = self.delayed_policy_refresh()
        self.entry["body"] = body
        arguments = {"body": body, "history": history, "checks": [check]}
        self.assertEqual(self.review_lane(candidate_kwargs=arguments)["status"], "pass")
        for timestamp in ("2026-11-01T10:02:00Z", "2026-11-01T10:02:01Z", "2026-11-01T10:02:06Z"):
            finding = {"user": self.entry["user"], "body": "P1: unsafe input",
                       "commit_id": self.head, "created_at": timestamp}
            with self.subTest(timestamp=timestamp):
                self.assertNotEqual(self.review_lane(inline=[finding], candidate_kwargs=arguments)["status"], "pass")

    def test_policy_metadata_is_not_a_verdict_or_place_for_unknown_text(self):
        for policy in (self.approval_policy().replace(self.head[:12], self.base[:12]),
                       self.approval_policy() + self.approval_policy(),
                       self.approval_policy().replace("Automatic approvals | Enabled", "Automatic approvals | Disabled"),
                       self.approval_policy().replace("their sources.", "their sources. A hidden concern remains.")):
            body = self.body.replace("<details><summary><strong>⚙️ Run configuration", policy + "\n<details><summary><strong>⚙️ Run configuration", 1)
            with self.subTest(policy=policy):
                self.assertIsNone(self.candidate(body=body)[0])

    def test_repository_ui_pending_metadata_needs_native_head_bound_check(self):
        config = ("- **Source mode**: Auto\n- **Repository**: Unavailable\n- **Branch**: Unavailable\n"
                  "- **File**: No configuration file from this repository applied\n- **Commit**: Unavailable\n"
                  "- **Layers**: Repository UI (base), Organization UI (inherited); Enforced overrides: Organization\n"
                  f"- **Review profile**: ASSERTIVE\n- **Plan**: Essentials\n- **Run ID**: `{self.run_id}`\n")
        body = self.body.replace(self.config, config)
        hist = copy.deepcopy(self.history)
        nodes = hist["userContentEdits"]["nodes"]
        nodes[0]["diff"] = hist["body"] = body
        nodes[1]["diff"] = nodes[1]["diff"].replace(self.config + f"- **Commit**: [{self.head[:7]}](<https://github.com/{self.slug}/commit/{self.head}>)\n", config)
        result, error = self.candidate(body=body, history=hist)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertIsNone(self.candidate(body=body, history=hist, checks=[])[0])
        self.assertIsNone(self.candidate(body=body, history=hist, checks=[{**self.check, "head_sha": self.base}])[0])

    def test_refresh_cannot_erase_changed_business_content_or_unknown_concerns(self):
        for body in (self.body.replace("Task context", "Changed task context"),
                     self.body.replace("Contract preserved.", "A new concern remains."),
                     self.body.replace("A bounded configuration change.", "Changed risk rationale."),
                     self.body + "\nUnclassified concern"):
            hist = self.refreshed_history(body)
            self.entry["updated_at"] = hist["updatedAt"]
            with self.subTest(body=body):
                self.assertIsNone(self.candidate(body=body, history=hist)[0])

    def paused_notice(self):
        return (
            "<!-- This is an auto-generated comment: review paused by coderabbit.ai -->\n\n"
            "> [!NOTE]\n> ## Reviews paused\n> \n"
            "> It looks like this branch is under active development. To avoid overwhelming you with review comments due to an influx of new commits, CodeRabbit has automatically paused this review. You can configure this behavior by changing the `reviews.auto_review.auto_pause_after_reviewed_commits` setting.\n> \n"
            f"> - Last reviewed commit: {self.head}\n> \n"
            "> Use the following commands to manage reviews:\n"
            "> - `@coderabbitai resume` to resume automatic reviews.\n"
            "> - `@coderabbitai review` to trigger a single review.\n> \n"
            "> Use the checkboxes below for quick actions:\n"
            "> - [ ] <!-- {\"checkboxId\":\"11111111-2222-4333-8444-555555555555\"} --> Resume reviews\n"
            "> - [ ] <!-- {\"checkboxId\":\"22222222-3333-4444-8555-666666666666\"} --> Trigger review\n\n"
            "<!-- end of auto-generated comment: review paused by coderabbit.ai -->"
        )

    def provider_assertion(self):
        return details("Additional comments: 1", details("tests/ci-policy.test.ts: 1",
            "`88-89`: **Data Integrity & Integration**\n\n"
            "**The GitHub Actions identity assertion is consistent with the inspected provider contract.**\n\n"
            "The test pins the active provider to `github-actions`. The contract agrees, and it declares a `dual-provider` migration in `shadow` mode. The inspected files do not list CircleCI or Semgrep Cloud as required-check providers, so the comment's claim that this validator rejects them is not supported by repository evidence.\n\n"
            "<!-- cr-comment:v1:eef8ff526e12f7473ad5e1df -->"))

    def completed_observed_layout(self):
        body = self.body.replace("<!-- recent_review_start -->", self.paused_notice() + "\n<!-- recent_review_start -->")
        body = body.replace("\n</dd></dl></details>\n<!-- review_details_end -->",
            "\n" + self.provider_assertion() + "\n</dd></dl></details>\n<!-- review_details_end -->")
        controls = details("Finishing Touches", details("Generate unit tests (beta)",
            '- [ ] <!-- {"checkboxId": "11111111-2222-4333-8444-555555555555", "radioGroupId": "utg-output-choice-group-123"} --> Commit to this branch')
            + '\n- [ ] <!-- {"checkboxId":"custom-finishing-touch:harness%20docs%20parity-create-pr"} --> harness docs parity')
        return body + section("finishing_touch_checkbox", controls)

    def test_completed_run_can_retain_exact_scheduling_controls_and_positive_assertion(self):
        body = self.completed_observed_layout()
        # The informational assertion is only admissible when its file is part
        # of this authenticated review's complete selected-file inventory.
        body = body.replace("code.py", "tests/ci-policy.test.ts")
        paths = ["tests/ci-policy.test.ts"]
        result, error = self.candidate(body=body, paths=paths)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["completion_evidence"]["summary_body"], body)
        for checks in ([], [{**self.check, "head_sha": self.base}], [{**self.check, "conclusion": "failure"}]):
            with self.subTest(checks=checks):
                self.assertIsNone(self.candidate(body=body, checks=checks, paths=paths)[0])
        self.assertIsNone(self.candidate(body=body, snapshot=False, paths=paths)[0])
        self.assertIsNone(self.candidate(body=body, paths=["other.py"])[0])
        for check in ({**self.check, "app": {"id": 99, "slug": "coderabbitai"}},
                      {**self.check, "status": "in_progress"},
                      {**self.check, "pull_requests": []}):
            with self.subTest(check=check):
                self.assertIsNone(self.candidate(body=body, paths=paths, checks=[check])[0])
        history = copy.deepcopy(self.history)
        history["userContentEdits"]["nodes"][1]["diff"] = "Missing authenticated pending run"
        self.assertIsNone(self.candidate(body=body, history=history, paths=paths)[0])

    def test_observed_controls_and_assertion_reject_unknown_or_changed_content(self):
        body = self.completed_observed_layout().replace("code.py", "tests/ci-policy.test.ts")
        for changed in (
            body.replace("Last reviewed commit: " + self.head, "Last reviewed commit: " + self.base),
            body.replace("Trigger review", "Trigger review. A concern remains."),
            body.replace("> - [ ]", "> - [x]", 1),
            body.replace('22222222-3333-4444-8555-666666666666', '11111111-2222-4333-8444-555555555555'),
            body.replace(self.paused_notice(), self.paused_notice() + self.paused_notice()),
            body.replace("--> harness docs parity", "--> Run arbitrary command"),
            body.replace('- [ ] <!-- {"checkboxId":"custom-finishing-touch:', '- [x] <!-- {"checkboxId":"custom-finishing-touch:'),
            body.replace('custom-finishing-touch:harness%20docs%20parity-create-pr', 'custom-finishing-touch:other-create-pr'),
            body.replace("**The GitHub Actions identity assertion is consistent", "**The GitHub Actions identity assertion is inconsistent"),
            body.replace("repository evidence.", "repository evidence. Fix a security defect."),
            body.replace("Additional comments: 1", "Additional comments: 2"),
            body.replace("<!-- cr-comment:v1:eef8ff526e12f7473ad5e1df -->", "<!-- cr-comment:v1:unknown -->"),
            body.replace(self.provider_assertion(), self.provider_assertion() + self.provider_assertion()),
            body.replace("tests/ci-policy.test.ts: 1", "other.py: 1"),
            body.replace("<!-- recent_review_start -->", MODULE._coderabbit_summary_adapter().PENDING_START + "\n<!-- recent_review_start -->"),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(self.candidate(body=changed, paths=["tests/ci-policy.test.ts"])[0])

    def dots_notifier_assertions(self):
        return details("Additional comments: 3",
            details("tests/policy_fixture.py: 1", "`22-22`: LGTM!\n\n<!-- cr-comment:v1:" + "a" * 24 + " -->")
            + details("tests/test_governance_port.py: 1", "`34-34`: LGTM!\n\n<!-- cr-comment:v1:" + "b" * 24 + " -->")
            + details("tests/test_policy_projection.py: 1",
                "`70-72`: **Maintainability & Code Quality**\n\n"
                "**The notifier-cutover path does not run canonical validation first.**\n\n"
                "For the notifier-only cleanup, `main` calls `_validate_notifier_cutover_snapshot` before any backup or write. That function invokes the runtime validator (`--runtime-config-stdin`), not `--config-stdin`. The canonical validator is not called anywhere in the repair script. The exit-75 stub therefore reaches the notifier-cutover check first, so the assertions test that check directly.\n\n"
                "<!-- cr-comment:v1:" + "c" * 24 + " -->"))

    def dots_notifier_body(self):
        paths = ["tests/policy_fixture.py", "tests/test_governance_port.py", "tests/test_policy_projection.py"]
        body = self.body.replace("Files selected for processing: 1", "Files selected for processing: 3")
        body = body.replace("* `code.py`", "\n".join("* `" + path + "`" for path in paths))
        body = body.replace("\n</dd></dl></details>\n<!-- review_details_end -->",
            "\n" + self.dots_notifier_assertions() + "\n</dd></dl></details>\n<!-- review_details_end -->")
        return body, paths

    def test_dots_notifier_assertion_retains_authenticated_completion(self):
        body, paths = self.dots_notifier_body()
        result, error = self.candidate(body=body, paths=paths)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["completion_evidence"]["summary_body"], body)
        for checks in ([], [{**self.check, "head_sha": self.base}],
                       [{**self.check, "conclusion": "failure"}],
                       [{**self.check, "status": "in_progress"}],
                       [{**self.check, "app": {"id": 99, "slug": "coderabbitai"}}]):
            with self.subTest(checks=checks):
                self.assertIsNone(self.candidate(body=body, paths=paths, checks=checks)[0])
        self.assertIsNone(self.candidate(body=body, paths=paths, snapshot=False)[0])

    def test_dots_notifier_assertion_rejects_changed_or_unbound_explanation(self):
        body, paths = self.dots_notifier_body()
        for changed in (body.replace("Additional comments: 3", "Additional comments: 4"),
                        body.replace("before any backup or write", "after a backup or write"),
                        body.replace("so the assertions test that check directly.",
                                     "so the assertions test that check directly. Fix a security issue."),
                        body.replace("`22-22`: LGTM!", "`22-22`: A concern remains."),
                        body.replace("tests/test_policy_projection.py: 1", "other.py: 1"),
                        body.replace("<!-- cr-comment:v1:" + "c" * 24 + " -->", "<!-- unknown -->")):
            with self.subTest(changed=changed):
                self.assertIsNone(self.candidate(body=changed, paths=paths)[0])
        self.assertIsNone(self.candidate(body=body, paths=["other.py"])[0])
        adapter = MODULE._coderabbit_summary_adapter()
        title, content = adapter._wrapper(self.dots_notifier_assertions())
        selected = "\n".join("* `" + path + "`" for path in paths)
        for slug, head in (("other/project", self.head), (self.slug, self.base)):
            with self.subTest(slug=slug, head=head):
                self.assertFalse(adapter._known_provider_assertion(title, content, selected, slug=slug, head=head))

    def test_unclassified_additional_comments_stay_blocked(self):
        extra = details("Additional comments: 1", details("code.py: 1", "An unmarked concern may remain."))
        body = self.body.replace("\n</dd></dl></details>\n<!-- review_details_end -->",
            "\n" + extra + "\n</dd></dl></details>\n<!-- review_details_end -->")
        self.assertIsNone(self.candidate(body=body)[0])

    def observed_grammar_note(self):
        return details("LanguageTool", details("docs/robin-review.md",
            '[grammar] ~20-~20: It appears that a noun is missing after “The”.\n'
            'Context: ...ndependent reviews.  ## Free allowance  The '
            '`ROBIN_CLOUDFLARE_API_TOKEN` and `ROBIN...\n\n(THE_CC)'))

    def observed_placeholder_controls(self):
        return section("finishing_touch_checkbox", details("Finishing Touches",
            details("Generate unit tests (beta)", '\n'.join(
                '- [ ] <!-- {"checkboxId":"' + uid + '", "radioGroupId":"utg-output-choice-group-unknown_comment_id"} --> ' + label
                for uid, label in (
                    ("6ba7b810-9dad-11d1-80b4-00c04fd430c8", "Commit to this branch"),
                    ("f47ac10b-58cc-4372-a567-0e02b2c3d479", "Create a new PR"))))))

    def grammar_body(self):
        return self.body.replace("code.py", "docs/robin-review.md").replace(
            '\n</dd></dl></details>\n<!-- review_details_end -->',
            '\n' + self.observed_grammar_note() + '\n</dd></dl></details>\n<!-- review_details_end -->')

    def test_observed_grammar_note_and_placeholder_controls_keep_native_binding(self):
        for grammar, controls in ((True, False), (False, True), (True, True)):
            with self.subTest(grammar=grammar, controls=controls):
                body = self.grammar_body() if grammar else self.body.replace("code.py", "docs/robin-review.md")
                if controls:
                    body += self.observed_placeholder_controls()
                result, error = self.candidate(body=body, paths=["docs/robin-review.md"])
                self.assertIsNone(error)
                self.assertIsNotNone(result)
                self.assertEqual(result["completion_evidence"]["summary_body"], body)
                self.assertEqual(result["created_at"], self.entry["updated_at"])
                self.assertIsNone(self.candidate(body=body, paths=["other.md"])[0])
                self.assertIsNone(self.candidate(body=body, paths=["docs/robin-review.md"], checks=[])[0])
                self.assertIsNone(self.candidate(body=body, paths=["docs/robin-review.md"], snapshot=False)[0])

    def test_observed_grammar_and_controls_reject_changed_or_unknown_findings(self):
        body = self.grammar_body() + self.observed_placeholder_controls()
        adapter = MODULE._coderabbit_summary_adapter()
        _, context = adapter._block(body, "recent_review")
        _, review_details = adapter._block(context, "review_details")
        _, children = adapter._details(adapter._wrapper(review_details)[1])
        title, note = adapter._wrapper(children[-1])
        selected = "* `docs/robin-review.md`"
        self.assertTrue(adapter._known_provider_assertion(title, note, selected, slug=self.slug, head=self.head))
        # The same diagnostic and selected path on changed underlying source
        # must not reuse an earlier source-specific false-positive decision.
        for slug, head in (("another/project", self.head), (self.slug, self.base)):
            self.assertFalse(adapter._known_provider_assertion(title, note, selected, slug=slug, head=head))
        for changed in (
            body.replace('~20-~20', '~21-~21'),
            body.replace('a noun is missing', 'a security check is missing'),
            body.replace('(THE_CC)', '(OTHER_RULE)'),
            body.replace('`ROBIN...', '`OTHER...'),
            body.replace(self.observed_grammar_note(), self.observed_grammar_note() + self.observed_grammar_note()),
            body.replace('(THE_CC)', '(THE_CC)\nFix another finding.'),
            body.replace('LanguageTool', 'Another tool'),
            body.replace('unknown_comment_id', 'unknown_comment_id_extra'),
            body.replace('unknown_comment_id', '0'),
            body.replace('- [ ]', '- [x]', 1),
            body.replace('Commit to this branch', 'Run arbitrary code'),
            body.replace('6ba7b810-9dad-11d1-80b4-00c04fd430c8', 'not-a-uuid'),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(self.candidate(body=changed, paths=["docs/robin-review.md"])[0])

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

    def review_lane(self, *, notice=None, codex=True, unresolved=0, decision="", inline=None, candidate_kwargs=None):
        completion, error = self.candidate(**(candidate_kwargs or {}))
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
