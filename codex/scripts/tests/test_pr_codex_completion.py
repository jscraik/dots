"""Provider-format completion/reaction correlation, never bare emoji approval."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "pr-readiness.py"
SPEC = importlib.util.spec_from_file_location("completion_gate", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
HEAD = "009ce5732d3953b8a0d5916219403b480b7d753c"
LOGIN = "chatgpt-codex-connector[bot]"
FIXTURE = Path(__file__).parent / "fixtures/codex-code-completion.txt"


class CodexCompletionTests(unittest.TestCase):
    def test_breezy_receipt_requires_exact_positive_body_head_and_provider(
        self,
    ) -> None:
        """Accept the exact native ending while rejecting altered trust evidence."""
        body = (
            "<!-- codex-review-receipt:v1 -->\n\n"
            "Codex Review: Didn't find any major issues. Breezy!\n\n"
            f"**Reviewed commit:** `{HEAD[:10]}`\n\n"
            + MODULE._CODEX_ABOUT_GITHUB_FOOTER
        )
        review = {
            "body": body,
            "state": "COMMENTED",
            "user": {"login": LOGIN, "type": "Bot", "id": 7},
        }
        self.assertTrue(MODULE._bot_review_is_acceptable(review, HEAD))
        for changed in (
            body.replace(HEAD[:10], "b" * 10),
            body + "\nP1: unresolved defect",
            body.replace("About Codex", "Unknown footer"),
            body.replace("Breezy!", "Breezy! Findings remain."),
        ):
            with self.subTest(body=changed):
                self.assertFalse(
                    MODULE._bot_review_is_acceptable({**review, "body": changed}, HEAD)
                )
        self.assertFalse(
            MODULE._bot_review_is_acceptable(
                {**review, "user": {"login": "untrusted"}}, HEAD
            )
        )
        self.assertFalse(
            MODULE._bot_review_is_acceptable(
                {**review, "record_only_reply": True}, HEAD
            )
        )

    def test_nice_work_receipt_retains_all_trust_boundaries(self) -> None:
        """Recognise the observed closing phrase, never arbitrary praise."""
        body = (
            "<!-- codex-review-receipt:v1 -->\n\n"
            "Codex Review: Didn't find any major issues. Nice work!\n\n"
            f"**Reviewed commit:** `{HEAD[:10]}`\n\n"
            + MODULE._CODEX_ABOUT_GITHUB_FOOTER
        )
        review = {"body": body, "state": "COMMENTED", "user": {"login": LOGIN}}
        self.assertTrue(MODULE._bot_review_is_acceptable(review, HEAD))
        for changed in (
            body.replace(HEAD[:10], "b" * 10),
            body + "\nP1: unresolved defect",
            body.replace("About Codex", "Unknown footer"),
            body.replace("Nice work!", "Nice work! Inspection incomplete."),
            body.replace("Nice work!", "Wonderful patch!"),
        ):
            with self.subTest(body=changed):
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": changed}, HEAD))
        for changed in (
            {**review, "user": {"login": "untrusted"}},
            {**review, "record_only_reply": True},
            {**review, "state": "CHANGES_REQUESTED"},
        ):
            with self.subTest(review=changed):
                self.assertFalse(MODULE._bot_review_is_acceptable(changed, HEAD))

    def code_only_state_body(self) -> tuple[str, dict]:
        state = {
            "code_review": {
                "commit_sha": HEAD,
                "has_any_findings": False,
                "has_unresolved_findings": False,
                "status": "completed",
            },
            "security_review": dict.fromkeys(
                ("commit_sha", "has_any_findings", "has_unresolved_findings", "status")
            ),
        }
        body = FIXTURE.read_text().replace(
            "<!-- codex-pull-request-review-summary -->",
            "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "
            + json.dumps(state)
            + " -->",
        )
        return body, state

    def test_draft_ready_code_review_keeps_completion_boundaries(self) -> None:
        body, state = self.code_only_state_body()
        body = body.replace("| New commits |", "| Draft marked ready |")
        self.entry["body"] = body
        review, error = self.candidate(
            reaction_error=AssertionError("optional reactions must not be read")
        )
        self.assertIsNone(error)
        self.assertIsNotNone(review)
        self.assertEqual(review["commit_id"], HEAD)
        self.assertTrue(MODULE._codex_informational_report(self.entry))

        for key, value in (
            ("status", "running"),
            ("has_any_findings", True),
            ("has_unresolved_findings", True),
            ("commit_sha", "b" * 40),
        ):
            changed = copy.deepcopy(state)
            changed["code_review"][key] = value
            self.entry["body"] = body.replace(json.dumps(state), json.dumps(changed))
            with self.subTest(key=key):
                self.assertIsNone(self.candidate()[0])
        self.entry["body"] = body.replace("Draft marked ready", "Unknown trigger")
        self.assertIsNone(self.candidate()[0])
        self.entry["body"] = body
        self.entry["user"] = {"login": "untrusted", "type": "Bot", "id": 7}
        self.assertIsNone(self.candidate()[0])

        self.setUp()
        self.entry["body"] = FIXTURE.read_text().replace(
            "| New commits |", "| Draft marked ready |"
        )
        self.assertIsNotNone(self.candidate()[0])
        self.assertIsNone(self.candidate(reactions=[])[0])
        self.assertIsNone(
            self.candidate(fresh_pr={**self.pr, "headRefOid": "b" * 40})[0]
        )

    def test_draft_ready_code_row_is_informational_with_security_activity(self) -> None:
        body = (FIXTURE.parent / "codex-summary.txt").read_text()
        body = body.replace("| Manual request |", "| Draft marked ready |")
        body = body.replace('"mergeGateEnabled":false', '"mergeGateEnabled":true')
        entry = {"user": {"login": LOGIN}, "state": "COMMENTED", "body": body}
        self.assertTrue(MODULE._codex_informational_report(entry))
        self.assertFalse(
            MODULE._bot_review_is_acceptable(
                entry, "983e9e55b0b29fc19186e3a7a86cd9a0514e7324"
            )
        )
        self.assertFalse(
            MODULE._codex_informational_report(
                {**entry, "body": body.replace("Draft marked ready", "Unknown trigger")}
            )
        )

    def test_draft_ready_security_row_keeps_bound_code_completion(self) -> None:
        body, state = self.state_body()
        before, after = body.rsplit("| Manual request |", 1)
        self.entry["body"] = before + "| Draft marked ready |" + after
        self.entry["created_at"] = "2026-10-07T15:57:00Z"
        self.entry["updated_at"] = "2026-10-07T15:58:12Z"
        review, error = self.candidate(reactions=[])
        self.assertIsNone(error)
        self.assertIsNotNone(review)
        self.assertEqual(review["commit_id"], HEAD)
        self.assertTrue(MODULE._codex_informational_report(self.entry))

        original = self.entry["body"]
        for change in (
            original.replace("Draft marked ready", "Unknown trigger"),
            original.replace(
                '"repository":"jscraik/Agent-Skills"', '"repository":"other/repo"'
            ),
        ):
            self.entry["body"] = change
            self.assertIsNone(self.candidate(reactions=[])[0])
        altered = copy.deepcopy(state)
        altered["security_review"]["has_unresolved_findings"] = True
        self.entry["body"] = original.replace(json.dumps(state), json.dumps(altered))
        self.assertIsNone(self.candidate(reactions=[])[0])

    def test_code_only_state_completion_needs_no_optional_reaction(self) -> None:
        self.entry["body"], state = self.code_only_state_body()
        review, error = self.candidate(
            reaction_error=AssertionError("optional reactions must not be read")
        )
        self.assertIsNone(error)
        self.assertIsNotNone(review)
        self.assertTrue(MODULE._bot_review_is_acceptable(review, HEAD))
        self.assertIsNone(review["completion_evidence"]["reaction_id"])
        self.entry["updated_at"] = "2026-10-10T17:45:00Z"
        self.assertIsNotNone(self.candidate(reactions=[])[0])
        for key, value in (
            ("status", "running"),
            ("has_any_findings", True),
            ("has_unresolved_findings", True),
            ("commit_sha", "b" * 40),
        ):
            with self.subTest(key=key):
                old = self.entry["body"]
                altered = copy.deepcopy(state)
                altered["code_review"][key] = value
                self.entry["body"] = old.replace(json.dumps(state), json.dumps(altered))
                self.assertIsNone(self.candidate(reactions=[])[0])
                self.entry["body"] = old

    def test_code_only_state_rejects_security_activity_and_partial_null_state(
        self,
    ) -> None:
        body, state = self.code_only_state_body()
        marker = "<!-- codex-pull-request-review-summary -->"
        mixed = self.mixed_body()
        security_row = next(
            line for line in mixed.splitlines() if "🔒 **Security Review**" in line
        )
        security_metadata = next(
            line for line in mixed.splitlines() if "codex-security-review:v1" in line
        )
        invalid = [
            body.replace("\n<details>", "\n" + security_row + "\n<details>"),
            body.replace(marker, marker + "\n" + security_metadata),
        ]
        partial = copy.deepcopy(state)
        partial["security_review"].pop("status")
        invalid.append(body.replace(json.dumps(state), json.dumps(partial)))
        for key, value in state["code_review"].items():
            altered = copy.deepcopy(state)
            altered["security_review"][key] = value
            invalid.append(body.replace(json.dumps(state), json.dumps(altered)))
        for changed in invalid:
            with self.subTest(body=changed):
                self.entry["body"] = changed
                self.assertIsNone(self.candidate(reactions=[])[0])
                self.assertFalse(MODULE._codex_informational_report(self.entry))

    def test_stale_code_only_state_summary_is_neutral_never_clearance(self) -> None:
        body, _ = self.code_only_state_body()
        self.entry["body"] = body.replace(HEAD, "b" * 40).replace(HEAD[:7], "bbbbbbb")
        self.assertIsNone(self.candidate(reactions=[])[0])
        self.assertTrue(MODULE._codex_informational_report(self.entry))
        self.assertEqual(
            MODULE.outstanding_bot_concerns([], [], [self.entry], HEAD), []
        )
        self.assertFalse(
            MODULE._codex_informational_report({**self.entry, "html_url": ""})
        )

    def test_automatic_coderabbit_summary_is_not_a_chat_clearance(self) -> None:
        ancestry = self.enterContext(
            patch.object(
                MODULE,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, "a" * 40, ""),
            )
        )
        body = (
            "<!-- coderabbit-ai-generated:v1 -->\n"
            "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->\n"
            "<!-- recent_review_start -->\nNo actionable comments were generated in the recent review. 🎉\n"
            "<details><summary><strong>ℹ️ Recent review info</strong></summary>\n"
            "- **Configuration used**: Repository: jscraik/Agent-Skills/.coderabbit.yaml\n"
            "- **Run ID**: `4859e27c-a72c-4fe7-83e3-371e52b4364a`\n"
            f"Reviewing files that changed from the base of the PR and between {'c' * 40} and {HEAD}.\n"
            "</details><!-- recent_review_end -->\n"
            "<!-- final_review_risk_start --><!-- final_review_risk_coverage:"
            + json.dumps(
                {"sourceCommitId": HEAD, "coveredCommitId": HEAD, "kind": "reviewed"}
            )
            + " --><!-- final_review_risk_end -->"
        )
        entry = {
            **self.entry,
            "body": body,
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
        }
        self.status_event = {
            "id": 90,
            "context": "CodeRabbit",
            "state": "success",
            "creator": entry["user"],
            "created_at": entry["updated_at"],
        }

        def run(
            candidate=entry,
            fresh=None,
            statuses=None,
            repo=("jscraik/Agent-Skills", None),
        ):
            with (
                patch.object(MODULE, "repository_slug", return_value=repo),
                patch.object(
                    MODULE,
                    "_coderabbit_statuses",
                    return_value=[self.status_event] if statuses is None else statuses,
                ),
                patch.object(MODULE, "gh_pr", return_value=(fresh or self.pr, None)),
                patch.object(
                    MODULE, "issue_comments", return_value=([candidate], None)
                ),
                patch.object(MODULE, "review_comments", return_value=([], None)),
            ):
                return MODULE.coderabbit_completion_review(
                    Path.cwd(), self.pr, HEAD, [], [candidate]
                )

        prior = {
            "user": entry["user"],
            "state": "COMMENTED",
            "commit_id": "c" * 40,
            "body": f"No findings for {'c' * 40}.",
            "submittedAt": "2026-10-10T17:20:00Z",
        }
        self.pr = valid_pr = {**self.pr, "reviews": [prior]}
        for code, merge_base in (
            (1, "a" * 40),
            (128, "a" * 40),
            (0, ""),
            (0, "not-a-commit"),
        ):
            ancestry.return_value = subprocess.CompletedProcess(
                [], code, merge_base, ""
            )
            with self.subTest(ancestry_exit=code, merge_base=merge_base):
                self.assertIsNone(run()[0])
        ancestry.return_value = subprocess.CompletedProcess([], 0, "a" * 40, "")
        for previous in (
            [],
            [{**prior, "commit_id": "d" * 40}],
            [{**prior, "body": "Review incomplete"}],
            [{**prior, "submittedAt": None}],
            [{**prior, "submittedAt": "2026-10-10T17:50:00Z"}],
        ):
            self.pr = {**valid_pr, "reviews": previous}
            with self.subTest(prior_reviews=previous):
                self.assertIsNone(run()[0])
        self.pr = {**valid_pr, "baseRefOid": "b" * 40, "reviews": []}
        full_range = {**entry, "body": body.replace("c" * 40, "a" * 40)}
        self.assertIsNotNone(
            run(full_range)[0],
            "verified merge-base review is full despite target-tip advancement",
        )
        self.pr = valid_pr
        review, error = run()
        ancestry.assert_called_with(
            ["git", "merge-base", "--is-ancestor", "c" * 40, HEAD],
            Path.cwd(),
            check=False,
        )
        self.assertIsNone(error)
        self.assertTrue(MODULE._bot_review_is_acceptable(review, HEAD))
        # Native organization-only configuration and separate status are
        # presentation/configuration evidence, not a narrative clearance route.
        native = body.replace(
            "<!-- recent_review_start -->\nNo actionable comments were generated in the recent review. 🎉\n",
            "<!-- recent_review_status_start -->\nNo actionable comments were generated in the recent review.\n"
            "<!-- recent_review_status_end -->\n<!-- recent_review_start -->\n<h6>\n",
        )
        native = native.replace(
            "<!-- recent_review_end -->", "\n</h6>\n<!-- recent_review_end -->"
        )
        native = native.replace(
            "- **Configuration used**: Repository: jscraik/Agent-Skills/.coderabbit.yaml",
            "- **Source mode**: Auto\n- **Repository**: Unavailable\n- **Branch**: Unavailable\n"
            "- **File**: No configuration file from this repository applied\n- **Commit**: Unavailable\n"
            "- **Layers**: Organization UI; Enforced overrides: Organization\n"
            "- **Review profile**: CHILL\n- **Plan**: Essentials",
        )
        self.assertIsNotNone(run({**entry, "body": native})[0])
        status = (
            "<!-- recent_review_status_start -->\nNo actionable comments were generated in the recent review.\n"
            "<!-- recent_review_status_end -->"
        )
        for nested in (
            native.replace(status, "").replace(
                "<!-- final_review_risk_end -->",
                status + "<!-- final_review_risk_end -->",
            ),
            native.replace(status, "")
            + "<!-- walkthrough_start -->"
            + status
            + "<!-- walkthrough_end -->",
            native.replace(status, "<blockquote>" + status + "</blockquote>"),
        ):
            with self.subTest(nested_status=nested):
                self.assertIsNone(run({**entry, "body": nested})[0])
        for changed in (
            native.replace(
                "No actionable comments were generated",
                "Review incomplete; comments were generated",
            ),
            native.replace(
                "- **Repository**: Unavailable", "- **Repository**: other/repo"
            ),
            native.replace(
                "<!-- recent_review_status_end -->",
                "Unsafe write remains.<!-- recent_review_status_end -->",
            ),
            native
            + "<!-- walkthrough_start -->Unsafe write remains.<!-- walkthrough_end -->",
            native
            + "<!-- pre_merge_checks_walkthrough_start -->Unsafe write remains.<!-- pre_merge_checks_walkthrough_end -->",
            native.replace(
                "<!-- recent_review_status_start -->",
                "<!-- recent_review_status_start -->" * 2,
            ),
            native.replace("\n</h6>", "\n</h6>\n</h6>"),
        ):
            with self.subTest(native_layout=changed):
                self.assertIsNone(run({**entry, "body": changed})[0])
        for status in (
            {**self.status_event, "state": "pending"},
            {**self.status_event, "creator": {**entry["user"], "id": 99}},
            {**self.status_event, "created_at": "2026-10-10T17:30:00Z"},
        ):
            self.assertIsNone(run(statuses=[status])[0])
        self.assertIsNone(run(statuses=[])[0])
        for wrapper in (
            "<!-- autopilot:start -->\n\t<!-- autopilot:end -->",
            "<!-- This is an auto-generated comment: all tool run failures by coderabbit.ai -->\n<!-- end of auto-generated comment: all tool run failures by coderabbit.ai -->",
            "<details>\n<summary><strong>Merge Risk:</strong> </summary>\n</details>",
        ):
            with self.subTest(empty_wrapper=wrapper):
                self.assertIsNotNone(run({**entry, "body": body + wrapper})[0])
                self.assertIsNone(
                    run(
                        {
                            **entry,
                            "body": body
                            + wrapper.replace("\n", "Unsafe write remains.", 1),
                        }
                    )[0]
                )
        self.assertIsNotNone(run(repo=(None, "repository unavailable"))[0])
        self.assertIsNone(
            run(
                repo=(None, "repository unavailable"),
                fresh={**self.pr, "url": "https://github.com/other/repo/pull/526"},
            )[0]
        )
        with (
            patch.object(
                MODULE, "_coderabbit_statuses", side_effect=[[self.status_event], []]
            ),
            patch.object(
                MODULE, "repository_slug", return_value=("jscraik/Agent-Skills", None)
            ),
            patch.object(MODULE, "gh_pr", return_value=(self.pr, None)),
            patch.object(MODULE, "issue_comments", return_value=([entry], None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
        ):
            self.assertIsNone(
                MODULE.coderabbit_completion_review(
                    Path.cwd(), self.pr, HEAD, [], [entry]
                )[0]
            )
        self.assertIsNone(run(statuses=[self.status_event, self.status_event])[0])
        self.assertIsNone(run({**entry, "updated_at": "2026-10-10T17:50:00Z"})[0])
        for changed in (
            body.replace(HEAD, "b" * 40),
            body.replace('"reviewed"', '"pending"'),
            body.replace(
                "No actionable comments were generated in the recent review. 🎉",
                "Review incomplete",
            ),
            body.replace("Agent-Skills/.coderabbit", "other/.coderabbit"),
            body.replace(".coderabbit.yaml", ".coderabbit.yaml.evil"),
            body + "\nActionable comments posted: 1",
            body + "\nUnresolved source defect",
            *(
                body
                + f"<!-- {section}_start -->Unsafe write remains.<!-- {section}_end -->"
                for section in (
                    "walkthrough",
                    "pre_merge_checks_walkthrough",
                    "review_stack_entry",
                    "finishing_touch_checkbox",
                    "tips",
                    "autopilot",
                )
            ),
            body.replace(
                "<!-- final_review_risk_end -->",
                "Unsafe write remains.<!-- final_review_risk_end -->",
            ),
            *(
                body + marker
                for marker in (
                    "<!-- This is an auto-generated comment: all tool run failures by coderabbit.ai -->",
                    "<details><summary><strong>Merge Risk:</strong>Unsafe write remains.</summary></details>",
                )
            ),
            body.replace(
                "</details><!-- recent_review_end -->",
                "</details>Unsafe write remains.<!-- recent_review_end -->",
            ),
            body.replace(
                "</details><!-- recent_review_end -->",
                "Unsafe write remains.</details><!-- recent_review_end -->",
            ),
            body.replace(
                "</details><!-- recent_review_end -->",
                "</details><!-- review_details_start -->Unsafe write remains.<!-- review_details_end --><!-- recent_review_end -->",
            ),
            body.replace(
                '"kind": "reviewed"', '"kind": "reviewed", "kind": "reviewed"'
            ),
            body.replace("4859e27c-a72c-4fe7-83e3-371e52b4364a", "-" * 36),
            body + "<!-- final_review_risk_start --><!-- final_review_risk_end -->",
            body.replace("4859e27c-a72c-4fe7-83e3-371e52b4364a", "a" * 36),
        ):
            with self.subTest(body=changed):
                self.assertIsNone(run({**entry, "body": changed})[0])
        selection = (
            "\n📒 Files selected for processing: 1\n* `codex/scripts/pr-readiness.py`\n"
        )
        selected = body.replace(
            "</details><!-- recent_review_end -->",
            selection + "</details><!-- recent_review_end -->",
        )
        self.assertIsNotNone(run({**entry, "body": selected})[0])
        self.assertIsNone(
            run({**entry, "body": selected.replace("processing: 1", "processing: 2")})[
                0
            ]
        )
        self.assertIsNone(
            run({**entry, "body": selected.replace("processing: 1", "processing: 0")})[
                0
            ]
        )
        quoted = "<!-- review_details_start --><details><summary><strong>📜 Recent review details</strong></summary><dl><dd>\n{}\n</dd></dl></details><!-- review_details_end -->"
        for prose in (
            "Unsafe write remains.",
            "Inspection could not cover the upload handler.",
        ):
            with self.subTest(context_prose=prose):
                self.assertIsNone(
                    run(
                        {
                            **entry,
                            "body": body.replace(
                                "<!-- recent_review_end -->",
                                quoted.format(prose) + "<!-- recent_review_end -->",
                            ),
                        }
                    )[0]
                )
        coverage_field = (
            "<!-- final_review_risk_coverage:"
            + body.split("<!-- final_review_risk_coverage:")[1].split(" -->")[0]
            + " -->"
        )
        for field in (
            coverage_field,
            "- **Configuration used**: Repository: jscraik/Agent-Skills/.coderabbit.yaml",
            "- **Run ID**: `4859e27c-a72c-4fe7-83e3-371e52b4364a`",
            f"Reviewing files that changed from the base of the PR and between {'c' * 40} and {HEAD}.",
        ):
            changed = body.replace(field, "").replace(
                "<!-- recent_review_end -->",
                quoted.format(field) + "<!-- recent_review_end -->",
            )
            with self.subTest(quoted_field=field):
                self.assertIsNone(run({**entry, "body": changed})[0])
        unbound_path = body.replace(
            "</details><!-- recent_review_end -->",
            "</details>\n* `Source defect remains.`\n<!-- recent_review_end -->",
        )
        self.assertIsNone(run({**entry, "body": unbound_path})[0])
        range_line = f"Reviewing files that changed from the base of the PR and between {'c' * 40} and {HEAD}."
        path_quote = body.replace(
            range_line, "📒 Files selected for processing: 1\n* `" + range_line + "`"
        )
        self.assertIsNone(run({**entry, "body": path_quote})[0])
        for user in (
            {"login": "other[bot]", "type": "Bot", "id": 8},
            {"login": "coderabbitai[bot]", "type": "User", "id": 8},
        ):
            self.assertIsNone(run({**entry, "user": user})[0])
        self.assertIsNone(run(fresh={**self.pr, "headRefOid": "b" * 40})[0])
        self.assertIsNone(run(fresh={**self.pr, "baseRefOid": "b" * 40})[0])
        finding = {
            "user": entry["user"],
            "commit_id": HEAD,
            "body": "Source defect remains",
            "created_at": "2026-10-10T17:38:00Z",
        }
        with (
            patch.object(
                MODULE, "repository_slug", return_value=("jscraik/Agent-Skills", None)
            ),
            patch.object(
                MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)
            ) as threads,
            patch.object(MODULE, "codex_completion_review", return_value=(None, None)),
            patch.object(
                MODULE, "_coderabbit_statuses", return_value=[self.status_event]
            ),
            patch.object(MODULE, "gh_pr", return_value=(self.pr, None)),
            patch.object(MODULE, "issue_comments", return_value=([entry], None)),
            patch.object(
                MODULE, "review_comments", return_value=([], None)
            ) as findings,
            patch.object(
                MODULE,
                "review_requirement",
                return_value={"risk_tier": "ordinary", "required_bot_review_count": 1},
            ),
        ):
            result = MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(
                result["details"]["coderabbit_completion_evidence"],
                review["completion_evidence"],
            )
            self.assertIsNone(result["details"]["codex_completion_evidence"])
            codex_concern = {**finding, "user": self.entry["user"]}
            findings.return_value = ([codex_concern], None)
            result = MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["details"]["outstanding_bot_concerns"], ["Codex"])
            self.assertEqual(result["details"]["review_source_diagnostics"], [])
            self.assertEqual(
                result["details"]["coderabbit_completion_evidence"],
                review["completion_evidence"],
            )
            for timestamp in ("2026-10-10T17:38:00Z", entry["updated_at"]):
                findings.return_value = ([{**finding, "created_at": timestamp}], None)
                self.assertEqual(
                    MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "fail"
                )
            older = {
                **finding,
                "commit_id": "c" * 40,
                "created_at": "2026-10-10T17:30:00Z",
            }
            findings.return_value = ([older], None)
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "fail"
            )
            full_entry = {
                **entry,
                "body": body.replace("c" * 40, self.pr["baseRefOid"]),
            }
            with patch.object(
                MODULE, "issue_comments", return_value=([full_entry], None)
            ):
                self.assertEqual(
                    MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "pass"
                )
            formal = {
                "user": entry["user"],
                "state": "COMMENTED",
                "commit_id": HEAD,
                "body": f"No findings for {HEAD}.",
                "submittedAt": "2026-10-10T17:50:00Z",
            }
            formal_pr = {**self.pr, "reviews": [formal]}
            with patch.object(MODULE, "gh_pr", return_value=(formal_pr, None)):
                self.assertEqual(
                    MODULE.reviews_lane(Path.cwd(), formal_pr, HEAD)["status"], "pass"
                )
            findings.return_value = ([], None)
            quota = {
                "user": entry["user"],
                "created_at": "2026-10-10T17:50:00Z",
                "body": "Review rate limited.",
            }
            with (
                patch.object(
                    MODULE, "issue_comments", return_value=([entry, quota], None)
                ),
                patch.object(
                    MODULE, "_codex_completion_snapshot", return_value=(True, None)
                ),
            ):
                self.assertEqual(
                    MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "pass"
                )
                quota["body"] += " Source defect remains."
                self.assertEqual(
                    MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "fail"
                )
            independent = {
                "user": self.entry["user"],
                "state": "COMMENTED",
                "commit_id": HEAD,
                "body": f"No findings for {HEAD}.",
                "submittedAt": "2026-10-10T17:50:00Z",
            }
            independent_pr = {**self.pr, "reviews": [prior, independent]}
            with (
                patch.object(
                    MODULE,
                    "repository_slug",
                    return_value=(None, "repository unavailable"),
                ),
                patch.object(MODULE, "gh_pr", return_value=(independent_pr, None)),
            ):
                independent_lane = MODULE.reviews_lane(Path.cwd(), independent_pr, HEAD)
                self.assertEqual(independent_lane["status"], "pass", independent_lane)
            threads.return_value = ({"unresolved_threads": 1}, None)
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "fail"
            )

    def state_body(self) -> tuple[str, dict]:
        body = (FIXTURE.parent / "codex-summary.txt").read_text()
        old = "983e9e55b0b29fc19186e3a7a86cd9a0514e7324"
        body = body.replace(old, HEAD).replace(old[:7], HEAD[:7])
        body = body.replace(
            '"repository":"jscraik/skills-foundry"',
            '"repository":"jscraik/Agent-Skills"',
        )
        body = body.replace('"pullRequestNumber":43', '"pullRequestNumber":526')
        body = body.replace(
            "2026-10-07T16:00:48.696815Z", "2026-10-07T15:58:11.414102Z"
        )
        state = {
            name: {
                "commit_sha": HEAD,
                "has_any_findings": False,
                "has_unresolved_findings": False,
                "status": "completed",
            }
            for name in ("code_review", "security_review")
        }
        marker = "<!-- codex-pull-request-review-summary -->"
        return body.replace(
            marker,
            marker + "\n<!-- codex-review-state:v1 " + json.dumps(state) + " -->",
        ), state

    def test_native_summary_diagnostics_never_supply_clearance(self) -> None:
        entry = {
            **self.entry,
            "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 8},
            "body": "<!-- coderabbit-ai-generated:v1 -->\n"
            "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->\n"
            "<!-- walkthrough_start -->Unsafe write remains.<!-- walkthrough_end -->",
        }
        evidence = MODULE.native_review_diagnostics([entry])
        self.assertEqual(evidence[0]["unclassified_sections"], ["walkthrough"])
        self.assertFalse(evidence[0]["qualifies_for_clearance"])
        self.assertEqual(evidence[0]["status"], "requires_independent_adjudication")
        self.assertEqual(
            MODULE.outstanding_bot_concerns([], [], [entry], HEAD), ["CodeRabbit"]
        )
        self.assertNotEqual(
            evidence,
            MODULE.native_review_diagnostics(
                [{**entry, "body": entry["body"] + "\nchanged"}]
            ),
        )
        self.assertEqual(
            MODULE.native_review_diagnostics([{**entry, "user": {"login": "other"}}]),
            [],
        )

    def test_versioned_state_summary_is_neutral_and_retains_code_completion(
        self,
    ) -> None:
        body, _ = self.state_body()
        entry = {
            "user": {"login": LOGIN},
            "state": "COMMENTED",
            "body": body,
            "html_url": "https://github.com/jscraik/Agent-Skills/pull/526#issuecomment-42",
        }
        self.assertEqual(
            MODULE._codex_code_completion(body), (HEAD, "2026-10-07T15:58:11.414102Z")
        )
        self.assertTrue(MODULE._codex_informational_report(entry))
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, HEAD))

    def test_versioned_state_requires_exact_full_head_despite_shared_abbreviation(
        self,
    ) -> None:
        self.entry["body"], _ = self.state_body()
        self.entry["created_at"] = "2026-10-07T15:57:00Z"
        self.entry["updated_at"] = "2026-10-07T15:58:12Z"
        self.reaction["created_at"] = "2026-10-07T15:58:13Z"
        review, error = self.candidate()
        self.assertIsNone(error)
        self.assertEqual(review["commit_id"], HEAD)
        foreign = HEAD[:7] + "b" * 33
        self.entry["body"] = self.entry["body"].replace(HEAD, foreign)
        review, error = self.candidate()
        self.assertIsNone(error)
        self.assertIsNone(review)

    def test_collapsed_native_summary_preserves_completion_and_rejects_extra_content(
        self,
    ) -> None:
        body, _state = self.state_body()
        heading = "## Codex Review Summary"
        wrapper = "<details>\n<summary><strong>Codex Review Summary</strong>: ✅ Completed</summary>"
        collapsed = body.replace(heading, wrapper) + "\n</details>"
        self.entry["body"] = collapsed
        self.entry["created_at"] = "2026-10-07T15:57:00Z"
        self.entry["updated_at"] = "2026-10-07T16:00:00Z"
        review, error = self.candidate(reactions=[])
        self.assertIsNone(error)
        self.assertIsNotNone(review)
        self.assertEqual(review["commit_id"], HEAD)
        self.assertTrue(MODULE._codex_informational_report(self.entry))
        for changed in (
            collapsed + "\nP1: unsafe write remains",
            collapsed.replace(wrapper, wrapper + "\nP1: unsafe write remains"),
            collapsed.replace("✅ Completed</summary>", "❌ Failed</summary>"),
            collapsed.removesuffix("\n</details>"),
            collapsed + "\n</details>",
            collapsed.replace(
                '"status": "completed"',
                '"status": "completed", "status": "completed"',
                1,
            ),
        ):
            with self.subTest(body=changed):
                self.entry["body"] = changed
                self.assertIsNone(self.candidate(reactions=[])[0])
                self.assertFalse(MODULE._codex_informational_report(self.entry))

    def test_absent_security_does_not_clear_earlier_unknown_concern(self) -> None:
        self.entry["body"], _ = self.code_only_state_body()
        review, error = self.candidate(reactions=[])
        self.assertIsNone(error)
        self.assertEqual(
            review["completion_evidence"]["security_findings"], "not_reported"
        )
        self.assertEqual(review["clearance_scope"], "code_only")
        finding = {
            "user": self.entry["user"],
            "body": "Prior security concern",
            "created_at": "2026-10-10T16:00:00Z",
        }
        self.assertEqual(
            MODULE.outstanding_bot_concerns([], [], [finding, review], HEAD), ["Codex"]
        )

    def test_versioned_state_summary_rejects_drift_findings_and_unknown_fields(
        self,
    ) -> None:
        body, state = self.state_body()
        changes = []
        for name in state:
            for key, value in (
                ("commit_sha", "b" * 40),
                ("commit_sha", []),
                ("status", "running"),
                ("has_any_findings", True),
                ("has_unresolved_findings", True),
                ("has_any_findings", 0),
                ("extra", False),
            ):
                changed = copy.deepcopy(state)
                changed[name][key] = value
                changes.append(body.replace(json.dumps(state), json.dumps(changed)))
            changed = copy.deepcopy(state)
            del changed[name]["status"]
            changes.append(body.replace(json.dumps(state), json.dumps(changed)))
        changes.extend(
            (
                body.replace("codex-review-state:v1", "codex-review-state:v2"),
                body.replace(
                    '"status": "completed"',
                    '"status": "completed", "status": "completed"',
                    1,
                ),
                body.replace('"headSha":"' + HEAD, '"headSha":"' + "b" * 40),
                body.replace("`" + HEAD[:7] + "`", "`bbbbbbb`", 1),
                body.replace(json.dumps(state), "[]"),
                body + "\nFinding: unsafe write",
                body.replace(
                    "<!-- codex-review-state:v1",
                    "<!-- codex-review-state:v1 {} -->\n<!-- codex-review-state:v1",
                    1,
                ),
            )
        )
        for changed in changes:
            with self.subTest(body=changed):
                self.assertIsNone(MODULE._codex_code_completion(changed))
                self.assertFalse(
                    MODULE._codex_informational_report(
                        {"user": {"login": LOGIN}, "body": changed}
                    )
                )

    def test_unknown_security_findings_cannot_be_cleared_by_a_reaction(self) -> None:
        body, state = self.state_body()
        unknown = copy.deepcopy(state)
        unknown["security_review"]["has_any_findings"] = None
        unknown["security_review"]["has_unresolved_findings"] = None
        self.entry["body"] = body.replace(json.dumps(state), json.dumps(unknown))
        self.entry["created_at"] = "2026-10-07T15:57:00Z"
        self.entry["updated_at"] = "2026-10-07T15:58:12Z"
        self.reaction["created_at"] = "2026-10-07T15:58:13Z"
        review, error = self.candidate()
        self.assertIsNone(error)
        self.assertIsNone(review)
        diagnostics: dict[str, list[str]] = {}
        self.assertEqual(
            MODULE.outstanding_bot_concerns(
                [], [], [self.entry], HEAD, diagnostics=diagnostics
            ),
            ["Codex"],
        )
        self.assertEqual(
            diagnostics["Codex"],
            ["codex_security_findings_unknown", "unrecognised_verdict_format"],
        )
        # An added finding is still a concern; the shape hint never clears it.
        self.entry["body"] += "\nP1: unsafe write remains."
        self.assertIsNone(self.candidate()[0])
        self.assertEqual(
            MODULE.outstanding_bot_concerns([], [], [self.entry], HEAD), ["Codex"]
        )
        # A malformed or foreign-head state cannot receive a misleading hint.
        self.assertEqual(
            MODULE._review_blocker_shape_hints(
                "chatgpt-codex-connector",
                "comment",
                self.entry["body"].replace(json.dumps(unknown), "not-json"),
                HEAD,
            ),
            set(),
        )
        self.assertEqual(
            MODULE._review_blocker_shape_hints(
                "chatgpt-codex-connector", "comment", self.entry["body"], "b" * 40
            ),
            set(),
        )

    def test_unknown_security_requires_correlated_native_provider_receipts(
        self,
    ) -> None:
        body, state = self.state_body()
        unknown = copy.deepcopy(state)
        unknown["security_review"]["has_any_findings"] = None
        unknown["security_review"]["has_unresolved_findings"] = None
        body = body.replace(json.dumps(state), json.dumps(unknown))
        lines = body.splitlines()
        security_row = next(
            i for i, line in enumerate(lines) if "🔒 **Security Review**" in line
        )
        lines[security_row] = lines[security_row].replace(
            "15:58:11.414102Z", "15:58:21.414102Z"
        )
        app = {"id": 1144995, "slug": "chatgpt-codex-connector"}
        summary = {
            **self.entry,
            "body": "\n".join(lines),
            "performed_via_github_app": app,
            "created_at": "2026-10-07T15:57:00Z",
            "updated_at": "2026-10-07T15:58:23Z",
        }
        code_body = (
            "<!-- codex-review-receipt:v1 -->\n\n"
            "Codex Review: Didn't find any major issues. Chef's kiss.\n\n"
            f"**Reviewed commit:** `{HEAD[:10]}`\n\n"
            "<details> <summary>ℹ️ About Codex in GitHub</summary>\n<br/>\n\n"
            "[Your team has set up Codex to review pull requests in this repo]"
            "(https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you\n"
            '- Open a pull request for review\n- Mark a draft as ready\n- Comment "@codex review".\n\n'
            "If Codex has suggestions, it will comment; otherwise it will react with 👍.\n\n"
            "Codex can also answer questions or update the PR. Try commenting "
            '"@codex address that feedback".\n\n</details>'
        )
        security_body = "<!-- codex-review-receipt:v1 -->\n\n" + (
            FIXTURE.parent / "codex-security.txt"
        ).read_text().replace("983e9e55b0", HEAD[:10])
        prefix = "https://github.com/jscraik/Agent-Skills/pull/526#issuecomment-"
        code = {
            **summary,
            "id": 43,
            "node_id": "code-node",
            "html_url": prefix + "43",
            "body": code_body,
            "created_at": "2026-10-07T15:58:10Z",
            "updated_at": "2026-10-07T15:58:10Z",
        }
        security = {
            **summary,
            "id": 44,
            "node_id": "security-node",
            "html_url": prefix + "44",
            "body": security_body,
            "created_at": "2026-10-07T15:58:20Z",
            "updated_at": "2026-10-07T15:58:20Z",
        }

        def inspect(entries: list[dict], resolved: str = HEAD) -> dict | None:
            with (
                patch.object(
                    MODULE,
                    "repository_slug",
                    return_value=("jscraik/Agent-Skills", None),
                ),
                patch.object(MODULE, "git", return_value=resolved),
                patch.object(MODULE, "gh_pr", return_value=(self.pr, None)),
                patch.object(MODULE, "issue_comments", return_value=(entries, None)),
                patch.object(MODULE, "review_comments", return_value=([], None)),
                patch.object(MODULE, "_codex_receipts_unedited", return_value=True),
            ):
                result, error = MODULE.codex_completion_review(
                    Path.cwd(), self.pr, HEAD, [], entries
                )
            self.assertIsNone(error)
            return result

        entries = [summary, code, security]
        completed = inspect(entries)
        self.assertIsNotNone(completed)
        self.assertEqual(
            completed["completion_evidence"]["code_receipt_url"], code["html_url"]
        )
        self.assertEqual(
            completed["completion_evidence"]["security_receipt_url"],
            security["html_url"],
        )
        self.assertTrue(MODULE._bot_review_is_acceptable(completed, HEAD))
        for altered in (
            [summary],
            [summary, code],
            [summary, security],
            entries + [security],
            entries
            + [
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "updated_at": "2026-10-07T15:58:22Z",
                }
            ],
            entries
            + [
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "user": {"login": LOGIN, "type": "Bot"},
                }
            ],
            entries
            + [
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "user": {"login": "different", "type": "Bot", "id": 7},
                }
            ],
            entries
            + [
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "user": {"login": "different", "type": "Bot", "id": 8},
                }
            ],
            entries
            + [
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "author": {"login": "different"},
                    "performed_via_github_app": None,
                    "user": {"login": LOGIN, "type": "Bot"},
                }
            ],
            entries
            + [
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "performed_via_github_app": None,
                    "user": {"login": "different", "type": "Bot", "id": "7"},
                }
            ],
            entries
            + [
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "performed_via_github_app": {"id": "1144995"},
                    "user": {"login": "different", "type": "Bot", "id": 8},
                }
            ],
            entries
            + [{**security, "id": 45, "html_url": prefix + "45", "created_at": None}],
            [summary, code, {**security, "body": security_body + "\nP1: unsafe write"}],
            [
                summary,
                code,
                {**security, "body": security_body.replace(HEAD[:10], "b" * 10)},
            ],
            [summary, code, {**security, "user": {**security["user"], "id": 8}}],
            [summary, code, {**security, "user": {**security["user"], "id": 7.0}}],
            [summary, code, {**security, "performed_via_github_app": {**app, "id": 8}}],
            [
                summary,
                code,
                {**security, "performed_via_github_app": {**app, "id": 1144995.0}},
            ],
            [
                summary,
                code,
                {**security, "html_url": prefix.replace("/526", "/527") + "44"},
            ],
            [summary, code, {**security, "updated_at": "2026-10-07T15:58:22Z"}],
            [
                summary,
                code,
                {
                    **security,
                    "created_at": "2026-10-07T15:57:00Z",
                    "updated_at": "2026-10-07T15:57:00Z",
                },
            ],
            [summary, {**code, "body": code_body + "\nP1: unsafe write"}, security],
            [summary, {**code, "updated_at": "2026-10-07T15:58:11Z"}, security],
            [
                {**summary, "body": summary["body"] + "\nP1: unsafe write"},
                code,
                security,
            ],
            [
                {**summary, "performed_via_github_app": {**app, "slug": "other"}},
                code,
                security,
            ],
            [{**summary, "author": {"login": "different"}}, code, security],
            [{**summary, "author": {**summary["user"], "id": 7.0}}, code, security],
            [
                {
                    **summary,
                    "body": summary["body"].replace(
                        '"has_any_findings": null', '"has_any_findings": true', 1
                    ),
                },
                code,
                security,
            ],
        ):
            with self.subTest(entries=altered):
                self.assertIsNone(inspect(altered))
        self.assertIsNone(inspect(entries, resolved=HEAD + "\n" + HEAD[:7] + "b" * 33))

        with (
            patch.object(
                MODULE, "repository_slug", return_value=("jscraik/Agent-Skills", None)
            ),
            patch.object(MODULE, "git", return_value=HEAD),
            patch.object(MODULE, "gh_pr", return_value=(self.pr, None)),
            patch.object(MODULE, "issue_comments", return_value=(entries, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "_codex_receipts_unedited", side_effect=[True, False]),
        ):
            changed, error = MODULE.codex_completion_review(
                Path.cwd(), self.pr, HEAD, [], entries
            )
            self.assertIsNone(changed)
            self.assertIn("edit history", error)

        finding = {
            "user": summary["user"],
            "body": "P1: unsafe write for " + HEAD,
            "created_at": "2026-10-07T15:58:22Z",
        }
        with (
            patch.object(
                MODULE, "repository_slug", return_value=("jscraik/Agent-Skills", None)
            ),
            patch.object(MODULE, "git", return_value=HEAD),
            patch.object(MODULE, "gh_pr", return_value=(self.pr, None)),
            patch.object(
                MODULE, "issue_comments", return_value=(entries, None)
            ) as inventory,
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(
                MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)
            ),
            patch.object(
                MODULE,
                "review_requirement",
                return_value={"required_bot_review_count": 1},
            ),
            patch.object(MODULE, "_codex_receipts_unedited", return_value=True),
        ):
            lane = MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)
            self.assertEqual(lane["status"], "pass", lane)
            malformed = {
                **security,
                "id": 45,
                "html_url": prefix + "45",
                "user": {"login": LOGIN, "type": "Bot"},
            }
            inventory.return_value = (entries + [malformed], None)
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "fail"
            )
            unrelated = {
                **security,
                "id": 45,
                "html_url": prefix + "45",
                "user": {"login": "different", "type": "User", "id": 8},
                "performed_via_github_app": None,
                "created_at": "2026-10-07T15:55:00Z",
                "updated_at": "2026-10-07T15:55:01Z",
            }
            inventory.return_value = (entries + [unrelated], None)
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "pass"
            )
            competing_comments = (
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "user": {"login": "different", "type": "Bot", "id": 8},
                    "performed_via_github_app": {"slug": "chatgpt-codex-connector"},
                },
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "user": {"login": "different", "type": "Bot", "id": 8},
                    "performed_via_github_app": {"node_id": "codex-app-node"},
                },
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "created_at": "2026-10-07T15:55:00Z",
                    "updated_at": "2026-10-07T15:58:20Z",
                },
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "user": {"login": "different", "type": "Bot", "id": 8},
                    "performed_via_github_app": None,
                    "updated_at": None,
                },
                {**unrelated, "created_at": None},
                {**unrelated, "updated_at": "not-a-time"},
                {**unrelated, "updated_at": "2026-10-07T15:54:59Z"},
                {**unrelated, "updated_at": "2026-10-07T15:58:20Z"},
                {
                    **security,
                    "id": 45,
                    "html_url": prefix + "45",
                    "user": {"login": "different", "type": "User", "id": 8},
                    "performed_via_github_app": None,
                },
            )
            for competing_comment in competing_comments:
                with self.subTest(competing_comment=competing_comment):
                    inventory.return_value = (entries + [competing_comment], None)
                    self.assertEqual(
                        MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "fail"
                    )
            inventory.return_value = (entries + [finding], None)
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "fail"
            )
            late_code = {
                **code,
                "created_at": "2026-10-07T15:58:13Z",
                "updated_at": "2026-10-07T15:58:13Z",
            }
            for when in ("2026-10-07T15:58:11Z", "2026-10-07T15:58:12Z"):
                with self.subTest(finding_time=when):
                    inventory.return_value = (
                        [summary, late_code, security, {**finding, "created_at": when}],
                        None,
                    )
                    self.assertEqual(
                        MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)["status"], "fail"
                    )

    def test_receipt_edit_history_must_be_complete_and_match_rest(self) -> None:
        receipts = [
            {
                "node_id": "receipt-1",
                "html_url": "https://github.com/o/r/pull/1#issuecomment-1",
                "body": "review 1",
                "created_at": "2026-10-07T15:58:10Z",
                "updated_at": "2026-10-07T15:58:10Z",
            },
            {
                "node_id": "receipt-2",
                "html_url": "https://github.com/o/r/pull/1#issuecomment-2",
                "body": "review 2",
                "created_at": "2026-10-07T15:58:20Z",
                "updated_at": "2026-10-07T15:58:20Z",
            },
        ]
        nodes = [
            {
                "id": item["node_id"],
                "url": item["html_url"],
                "body": item["body"],
                "createdAt": item["created_at"],
                "updatedAt": item["updated_at"],
                "lastEditedAt": None,
                "includesCreatedEdit": False,
                "userContentEdits": {"totalCount": 0},
            }
            for item in receipts
        ]
        response = {"data": {"nodes": nodes}}
        with patch.object(MODULE, "run_command") as command:
            command.return_value = subprocess.CompletedProcess(
                [], 0, json.dumps(response), ""
            )
            self.assertTrue(MODULE._codex_receipts_unedited(Path.cwd(), receipts))
            for change in (
                {"lastEditedAt": "2026-10-07T15:58:10Z"},
                {"includesCreatedEdit": True},
                {"userContentEdits": {"totalCount": 1}},
                {"userContentEdits": None},
                {"body": "review 1 changed"},
                {"id": "different"},
                {"url": "https://github.com/o/r/pull/2"},
            ):
                changed = copy.deepcopy(response)
                changed["data"]["nodes"][0].update(change)
                command.return_value.stdout = json.dumps(changed)
                with self.subTest(change=change):
                    self.assertFalse(
                        MODULE._codex_receipts_unedited(Path.cwd(), receipts)
                    )
            for payload in (
                {"errors": [{"message": "unavailable"}], **response},
                {"data": {"nodes": [nodes[0]]}},
                {},
            ):
                command.return_value.stdout = json.dumps(payload)
                self.assertFalse(MODULE._codex_receipts_unedited(Path.cwd(), receipts))
            command.return_value.stdout = "not JSON"
            self.assertFalse(MODULE._codex_receipts_unedited(Path.cwd(), receipts))
            command.return_value = subprocess.CompletedProcess([], 1, "", "unavailable")
            self.assertFalse(MODULE._codex_receipts_unedited(Path.cwd(), receipts))
            self.assertFalse(
                MODULE._codex_receipts_unedited(Path.cwd(), [receipts[0], receipts[0]])
            )

    def test_unknown_security_hint_requires_a_complete_unambiguous_state(self) -> None:
        body, state = self.state_body()
        state["security_review"]["has_any_findings"] = None
        state["security_review"]["has_unresolved_findings"] = None
        invalid = []
        missing_code = copy.deepcopy(state)
        del missing_code["code_review"]
        invalid.append(missing_code)
        extra = copy.deepcopy(state)
        extra["other_review"] = {}
        invalid.append(extra)
        known_finding = copy.deepcopy(state)
        known_finding["security_review"]["has_any_findings"] = True
        invalid.append(known_finding)
        code_finding = copy.deepcopy(state)
        code_finding["code_review"]["has_unresolved_findings"] = True
        invalid.append(code_finding)
        for changed in invalid:
            with self.subTest(state=changed):
                entry = {
                    **self.entry,
                    "body": body.replace(
                        json.dumps(self.state_body()[1]), json.dumps(changed)
                    ),
                }
                diagnostics: dict[str, list[str]] = {}
                self.assertEqual(
                    MODULE.outstanding_bot_concerns(
                        [], [], [entry], HEAD, diagnostics=diagnostics
                    ),
                    ["Codex"],
                )
                self.assertEqual(diagnostics["Codex"], ["unrecognised_verdict_format"])

    def test_deeply_nested_diagnostic_metadata_remains_a_blocking_concern(self) -> None:
        nested = "[" * 10000 + "0" + "]" * 10000
        for prefix in ("prefix ", ""):
            with self.subTest(prefix=prefix):
                body = (
                    prefix + "<!-- codex-pull-request-review-summary -->\n"
                    f"<!-- codex-review-state:v1 {nested} -->\n{HEAD}"
                )
                diagnostics: dict[str, list[str]] = {}
                self.assertEqual(
                    MODULE.outstanding_bot_concerns(
                        [],
                        [],
                        [{**self.entry, "body": body}],
                        HEAD,
                        diagnostics=diagnostics,
                    ),
                    ["Codex"],
                )
                self.assertEqual(diagnostics["Codex"], ["unrecognised_verdict_format"])

        body, _ = self.state_body()
        marker = next(
            line
            for line in body.splitlines()
            if "<!-- codex-security-review:v1 " in line
        )
        body = body.replace(marker, f"<!-- codex-security-review:v1 {nested} -->")
        self.assertIsNone(MODULE._codex_code_completion(body))

    def test_legacy_security_metadata_rejects_duplicate_keys(self) -> None:
        head = "983e9e55b0b29fc19186e3a7a86cd9a0514e7324"
        body = (FIXTURE.parent / "codex-summary.txt").read_text()
        entry = {
            "user": {"login": LOGIN, "type": "Bot", "id": 7},
            "body": body,
            "html_url": "https://github.com/jscraik/skills-foundry/pull/43#issuecomment-42",
        }
        self.assertIsNotNone(MODULE._codex_code_completion(body))
        self.assertTrue(MODULE._codex_informational_report(entry))
        for original, duplicate in (
            ('"status":"completed"', '"status":"failed","status":"completed"'),
            (
                '"mergeGateEnabled":false',
                '"mergeGateEnabled":true,"mergeGateEnabled":false',
            ),
            (f'"headSha":"{head}"', f'"headSha":"{"b" * 40}","headSha":"{head}"'),
        ):
            changed = body.replace(original, duplicate, 1)
            with self.subTest(duplicate=original):
                self.assertNotEqual(changed, body)
                self.assertIsNone(MODULE._codex_code_completion(changed))
                self.assertFalse(
                    MODULE._codex_informational_report({**entry, "body": changed})
                )
                self.assertEqual(
                    MODULE.outstanding_bot_concerns(
                        [], [], [{**entry, "body": changed}], head
                    ),
                    ["Codex"],
                )

    def test_versioned_security_receipt_is_neutral_not_code_clearance(self) -> None:
        body = (
            "<!-- codex-review-receipt:v1 -->\n\n"
            + (FIXTURE.parent / "codex-security.txt").read_text()
        )
        entry = {"user": {"login": LOGIN}, "state": "COMMENTED", "body": body}
        self.assertTrue(MODULE._codex_informational_report(entry))
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, HEAD))
        self.assertFalse(
            MODULE._codex_informational_report(
                {**entry, "body": body + "\nFinding remains"}
            )
        )

    def mixed_body(self) -> str:
        import json

        body = FIXTURE.read_text()
        metadata = {
            "blockingSeverityThreshold": "P0",
            "headSha": "b" * 40,
            "mergeGateEnabled": False,
            "pullRequestNumber": 526,
            "repository": "jscraik/Agent-Skills",
            "status": "completed",
        }
        marker = "<!-- codex-pull-request-review-summary -->"
        body = body.replace(
            marker,
            marker + "\n<!-- codex-security-review:v1 " + json.dumps(metadata) + " -->",
        )
        row = '| 🔒 **Security Review** | ✅ **Completed** <relative-time datetime="2026-10-10T17:00:00Z">2026-10-10T17:00:00Z</relative-time> | `bbbbbbb` | New commits |\n'
        return body.replace("\n<details>", "\n" + row + "\n<details>")

    def setUp(self) -> None:
        self.entry = {
            "id": 42,
            "user": {"login": LOGIN, "type": "Bot", "id": 7},
            "body": FIXTURE.read_text(),
            "created_at": "2026-10-10T17:00:00Z",
            "updated_at": "2026-10-10T17:37:47Z",
            "html_url": "https://github.com/jscraik/Agent-Skills/pull/526#issuecomment-42",
        }
        self.reaction = {
            "id": 99,
            "user": {"login": LOGIN, "type": "User", "id": 7},
            "content": "+1",
            "created_at": "2026-10-10T17:37:50Z",
        }
        self.pr = {
            "number": 526,
            "url": "https://github.com/jscraik/Agent-Skills/pull/526",
            "headRefOid": HEAD,
            "baseRefOid": "a" * 40,
            "reviews": [],
            "author": {"login": "jscraik"},
        }

    def candidate(
        self,
        *,
        fresh_pr=None,
        fresh_entries=None,
        reactions=None,
        resolved=HEAD,
        reaction_error=None,
    ):
        entries = [self.entry]
        with (
            patch.object(
                MODULE, "repository_slug", return_value=("jscraik/Agent-Skills", None)
            ),
            patch.object(
                MODULE,
                "_codex_reactions",
                return_value=(
                    [self.reaction] if reactions is None else reactions,
                    None,
                ),
                side_effect=reaction_error,
            ) as reaction_lookup,
            patch.object(MODULE, "git", return_value=resolved),
            patch.object(MODULE, "gh_pr", return_value=(fresh_pr or self.pr, None)),
            patch.object(
                MODULE,
                "issue_comments",
                return_value=(
                    entries if fresh_entries is None else fresh_entries,
                    None,
                ),
            ),
            patch.object(MODULE, "review_comments", return_value=([], None)),
        ):
            result = MODULE.codex_completion_review(
                Path.cwd(), self.pr, HEAD, [], entries
            )
            if reactions == [] and "<!-- codex-review-state:v1 " in self.entry["body"]:
                reaction_lookup.assert_not_called()
            return result

    def test_current_head_provider_pair_grants_explicit_normalized_evidence(
        self,
    ) -> None:
        review, error = self.candidate()
        self.assertIsNone(error)
        self.assertTrue(MODULE._bot_review_is_acceptable(review, HEAD))
        self.assertEqual(review["source"], "codex_completion_reaction")
        self.assertEqual(review["completion_evidence"]["reaction_id"], 99)

    def test_receipt_prefixed_completion_preserves_reaction_clearance(self) -> None:
        original = self.entry["body"]
        self.entry["body"] = "<!-- codex-review-receipt:v1 -->\n\n" + original
        review, error = self.candidate()
        self.assertIsNone(error)
        self.assertIsNotNone(review)
        self.assertTrue(MODULE._bot_review_is_acceptable(review, HEAD))
        self.assertIsNone(self.candidate(reactions=[])[0])
        self.entry["body"] = "<!-- codex-review-receipt:v1 -->\n\n" + self.entry["body"]
        self.assertIsNone(self.candidate()[0])

    def test_combined_summary_uses_code_head_not_older_security_head(self) -> None:
        self.entry["body"] = self.mixed_body()
        self.entry["updated_at"] = "2026-10-10T17:37:49Z"
        review, error = self.candidate()
        self.assertIsNone(error)
        self.assertEqual(review["commit_id"], HEAD)
        self.assertIsNone(self.candidate(reactions=[])[0])

    def test_combined_summary_rejects_inconsistent_or_foreign_security_activity(
        self,
    ) -> None:
        body = self.mixed_body()
        for invalid in (
            body.replace("`bbbbbbb`", "`ccccccc`"),
            body.replace('"status": "completed"', '"status": "running"'),
            body.replace(
                '"repository": "jscraik/Agent-Skills"', '"repository": "other/repo"'
            ),
            body.replace('"pullRequestNumber": 526', '"pullRequestNumber": 7'),
            body.replace('"mergeGateEnabled": false', '"mergeGateEnabled": true'),
            body + "\nFinding: unsafe write",
            body.replace("📝 **Code Review**", "🔒 **Security Review**"),
        ):
            with self.subTest(body=invalid):
                self.entry["body"] = invalid
                self.assertIsNone(self.candidate()[0])
        self.entry["body"] = body
        self.entry["updated_at"] = "2026-10-10T17:37:51Z"
        self.assertIsNone(self.candidate()[0])

    def test_summary_alone_and_unmatched_reactions_never_clear(self) -> None:
        self.assertIsNone(self.candidate(reactions=[])[0])
        for changes in (
            {"content": "eyes"},
            {"user": {"login": "other", "type": "Bot"}},
            {"user": {"login": LOGIN, "type": "User", "id": 8}},
            {"created_at": "2026-10-10T17:30:00Z"},
            {"created_at": "2026-10-10T18:00:00Z"},
            {"created_at": "invalid"},
        ):
            with self.subTest(changes=changes):
                review, _error = self.candidate(
                    reactions=[{**self.reaction, **changes}]
                )
                self.assertIsNone(review)

    def test_running_stale_spoofed_and_extended_summaries_never_clear(self) -> None:
        original = copy.deepcopy(self.entry)
        for changes in (
            {"body": original["body"].replace("Completed", "Running")},
            {"body": original["body"].replace("009ce57", "bbbbbbb")},
            {"body": original["body"] + "Finding: unsafe write\n"},
            {"body": original["body"].replace("17:37:47.535308Z", "99:37:47.535308Z")},
            {"user": {"login": "other", "type": "Bot"}},
            {"html_url": "https://github.com/other/repo/pull/526#issuecomment-42"},
        ):
            with self.subTest(changes=changes):
                self.entry = {**original, **changes}
                review, _error = self.candidate()
                self.assertIsNone(review)

    def test_head_summary_review_and_reaction_drift_block(self) -> None:
        for fresh in (
            {**self.pr, "headRefOid": "b" * 40},
            {**self.pr, "reviews": [{"body": "new finding"}]},
        ):
            with self.subTest(fresh=fresh):
                review, error = self.candidate(fresh_pr=fresh)
                self.assertIsNone(review)
                self.assertIsNotNone(error)
        review, error = self.candidate(
            fresh_entries=[{**self.entry, "body": "now running"}]
        )
        self.assertIsNone(review)
        self.assertIsNotNone(error)

    def test_later_finding_remains_blocking(self) -> None:
        review, _error = self.candidate()
        finding = {
            "user": {"login": LOGIN},
            "body": "Unsafe write for " + HEAD,
            "created_at": "2026-10-10T17:38:00Z",
        }
        self.assertEqual(
            MODULE.outstanding_bot_concerns(
                [], [], [self.entry, review, finding], HEAD
            ),
            ["Codex"],
        )
        finding["created_at"] = "2026-10-10T17:37:48Z"
        self.assertEqual(
            MODULE.outstanding_bot_concerns(
                [], [], [self.entry, review, finding], HEAD
            ),
            ["Codex"],
        )
        finding["created_at"] = "2026-10-10T17:37:47Z"
        for entries in ([self.entry, finding, review], [self.entry, review, finding]):
            self.assertEqual(
                MODULE.outstanding_bot_concerns([], [], entries, HEAD), ["Codex"]
            )
        finding["created_at"] = "2026-10-10T17:37:46Z"
        self.assertEqual(
            MODULE.outstanding_bot_concerns(
                [], [], [self.entry, finding, review], HEAD
            ),
            ["Codex"],
        )

    def test_unavailable_optional_reactions_do_not_block_independent_quorum(
        self,
    ) -> None:
        rabbit = {
            "user": {"login": "coderabbitai"},
            "state": "COMMENTED",
            "commit_id": HEAD,
            "body": "No findings for " + HEAD,
            "submitted_at": "2026-10-10T17:40:00Z",
        }
        with (
            patch.object(
                MODULE, "repository_slug", return_value=("jscraik/Agent-Skills", None)
            ),
            patch.object(MODULE, "git", return_value=HEAD),
            patch.object(
                MODULE,
                "_codex_reactions",
                return_value=([], "reaction API unavailable"),
            ),
            patch.object(
                MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)
            ),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([self.entry], None)),
            patch.object(
                MODULE,
                "review_requirement",
                return_value={"required_bot_review_count": 1},
            ) as requirement,
        ):
            pr = {**self.pr, "reviews": [rabbit]}
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), pr, HEAD)["status"], "pass"
            )
            requirement.return_value = {"required_bot_review_count": 2}
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), pr, HEAD)["status"], "fail"
            )
            finding = {
                "user": {"login": LOGIN},
                "body": "Unsafe write for " + HEAD,
                "created_at": "2026-10-10T17:41:00Z",
            }
            requirement.return_value = {"required_bot_review_count": 1}
            with patch.object(
                MODULE, "issue_comments", return_value=([self.entry, finding], None)
            ):
                self.assertEqual(
                    MODULE.reviews_lane(Path.cwd(), pr, HEAD)["status"], "fail"
                )

    def test_failed_second_reaction_read_is_optional_but_drift_blocks(self) -> None:
        for second, expected_error in (
            ([], "API unavailable"),
            ([{**self.reaction, "id": 100}], None),
        ):
            with (
                patch.object(
                    MODULE,
                    "repository_slug",
                    return_value=("jscraik/Agent-Skills", None),
                ),
                patch.object(MODULE, "git", return_value=HEAD),
                patch.object(MODULE, "gh_pr", return_value=(self.pr, None)),
                patch.object(
                    MODULE, "issue_comments", return_value=([self.entry], None)
                ),
                patch.object(MODULE, "review_comments", return_value=([], None)),
                patch.object(
                    MODULE,
                    "_codex_reactions",
                    side_effect=[([self.reaction], None), (second, expected_error)],
                ),
            ):
                review, error = MODULE.codex_completion_review(
                    Path.cwd(), self.pr, HEAD, [], [self.entry]
                )
                self.assertIsNone(review)
                if expected_error:
                    self.assertIsNone(error)
                else:
                    self.assertIsNotNone(error)

    def test_repair_inventory_contains_only_authentic_sources(self) -> None:
        candidate, _error = self.candidate()
        endorsement = {
            "user": {"login": "coderabbitai"},
            "body": "pr-repair-endorsement/v1\nproof",
        }
        entries = [self.entry, endorsement]
        with (
            patch.object(
                MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)
            ),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(entries, None)),
            patch.object(
                MODULE, "codex_completion_review", return_value=(candidate, None)
            ),
            patch.object(
                MODULE, "repair_endorsement_lane", return_value={"status": "blocked"}
            ) as repair,
        ):
            MODULE.reviews_lane(Path.cwd(), self.pr, HEAD)
            self.assertEqual(repair.call_args.args[-1], entries)

    def test_code_only_summary_is_neutral_without_reaction(self) -> None:
        self.assertTrue(MODULE._codex_informational_report(self.entry))
        self.assertFalse(MODULE._bot_review_is_acceptable(self.entry, HEAD))

    def test_ambiguous_prefix_and_unavailable_reactions_block(self) -> None:
        review, error = self.candidate(resolved=HEAD + "\n" + "009ce57" + "b" * 33)
        self.assertIsNone(review)
        self.assertIsNotNone(error)
        with patch.object(MODULE, "run_command") as command:
            command.return_value.returncode = 1
            self.assertIsNotNone(
                MODULE._codex_reactions(Path.cwd(), "jscraik/Agent-Skills", 526)[1]
            )

    def test_paginated_reactions_and_quota_neighbors_fail_closed(self) -> None:
        import json

        with patch.object(MODULE, "run_command") as command:
            command.return_value.returncode = 0
            command.return_value.stdout = json.dumps([[], [self.reaction]])
            self.assertEqual(
                MODULE._codex_reactions(Path.cwd(), "jscraik/Agent-Skills", 526),
                ([self.reaction], None),
            )
            self.assertEqual(
                command.call_args.args[0],
                [
                    "gh",
                    "api",
                    "repos/jscraik/Agent-Skills/issues/526/reactions",
                    "--paginate",
                    "--slurp",
                ],
            )
            for payload in (
                {},
                [],
                [self.reaction],
                [[{**self.reaction, "id": True}]],
                [[{**self.reaction, "created_at": "invalid"}]],
            ):
                command.return_value.stdout = json.dumps(payload)
                self.assertIsNotNone(
                    MODULE._codex_reactions(Path.cwd(), "jscraik/Agent-Skills", 526)[1]
                )
        quota = "You have reached your Codex usage limits for code reviews. You can see your limits in the [Codex usage dashboard](https://chatgpt.com/codex/cloud/settings/usage)."
        self.assertTrue(
            MODULE._bot_response_is_only_unavailability(
                quota, login="chatgpt-codex-connector"
            )
        )
        self.assertFalse(
            MODULE._bot_response_is_only_unavailability(
                quota + " Unsafe write.", login="chatgpt-codex-connector"
            )
        )
        self.assertIsNotNone(self.candidate(fresh_entries=[])[1])

    def test_review_lane_accepts_pair_but_not_later_finding_or_open_thread(
        self,
    ) -> None:
        candidate, _error = self.candidate()
        old = {
            "user": {"login": LOGIN},
            "state": "COMMENTED",
            "commit_id": "b" * 40,
            "body": "Unsafe write",
            "submitted_at": "2026-10-10T17:25:00Z",
        }
        quota = {
            "user": {"login": LOGIN},
            "created_at": "2026-10-10T17:41:00Z",
            "body": "You have reached your Codex usage limits for code reviews. You can see your limits in the [Codex usage dashboard](https://chatgpt.com/codex/cloud/settings/usage).",
        }
        with (
            patch.object(
                MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)
            ) as threads,
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(
                MODULE, "issue_comments", return_value=([self.entry, quota], None)
            ) as comments,
            patch.object(
                MODULE, "codex_completion_review", return_value=(candidate, None)
            ),
            patch.object(
                MODULE,
                "review_requirement",
                return_value={"required_bot_review_count": 1},
            ),
        ):
            pr = {**self.pr, "reviews": [old]}
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), pr, HEAD)["status"], "fail"
            )
            pr = {**self.pr, "reviews": []}
            result = MODULE.reviews_lane(Path.cwd(), pr, HEAD)
            self.assertEqual(result["status"], "pass", result)
            self.assertEqual(
                result["details"]["codex_completion_evidence"],
                candidate["completion_evidence"],
            )
            self.assertIsNone(result["details"]["coderabbit_completion_evidence"])
            later = {
                "user": {"login": LOGIN},
                "body": "Unsafe write for " + HEAD,
                "created_at": "2026-10-10T17:42:00Z",
            }
            comments.return_value = ([self.entry, quota, later], None)
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), pr, HEAD)["status"], "fail"
            )
            threads.return_value = ({"unresolved_threads": 1}, None)
            self.assertEqual(
                MODULE.reviews_lane(Path.cwd(), pr, HEAD)["status"], "fail"
            )
