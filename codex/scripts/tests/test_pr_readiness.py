from __future__ import annotations

import builtins
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "pr-readiness.py"
SPEC = importlib.util.spec_from_file_location("pr_readiness", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load validator module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrReadinessTests(unittest.TestCase):
    def test_ordinary_source_requires_one_independent_review(self) -> None:
        from pr_review_risk import committed_review_requirement

        for path in ('src/widget.py', 'src/components/Button.tsx', 'tests/test_widget.py',
                     'scripts/format.py', 'src/theme/tokens.json', 'docs/guide.md'):
            with self.subTest(path=path):
                result = committed_review_requirement([
                    {'path': path, 'old_mode': '100644', 'new_mode': '100644'}])
                self.assertEqual(result['required_bot_review_count'], 1)
        for path in ('src/auth/login.py', '.github/workflows/check.yml',
                     'codex/scripts/pr-readiness.py', 'migrations/001.sql',
                     'scripts/deploy.sh', 'package-lock.json', 'unknown.blob',
                     'requirements/codex-validation.txt', 'mise/config.toml',
                     'codex/config.toml', 'codex/requirements.toml', 'codex/projection-map.json',
                     'codex/scripts/admit-hook-fixture.py', 'codex/scripts/migration_scope.py',
                     'codex/templates/handler-provenance.json', 'tools/mise/config.toml',
                     '.coderabbit.yaml', 'Package.swift', 'composer.json', 'setup.py', 'build.gradle.kts'):
            with self.subTest(path=path):
                result = committed_review_requirement([
                    {'path': path, 'old_mode': '100644', 'new_mode': '100644'}])
                self.assertEqual(result['required_bot_review_count'], 2)
        for before, after in (('100644', '100755'), ('120000', '100644'), ('160000', '000000')):
            result = committed_review_requirement([
                {'path': 'src/widget.py', 'old_mode': before, 'new_mode': after}])
            self.assertEqual(result['required_bot_review_count'], 2)
        self.assertEqual(committed_review_requirement([
            {'path': 'scripts/format.sh', 'old_mode': '100755', 'new_mode': '100755'}
        ])['required_bot_review_count'], 1)

    def test_modern_coderabbit_completion_keeps_identity_and_gap_checks(self) -> None:
        head, base = "a" * 40, "b" * 40
        slug = "jscraik/configs"
        icon = '<picture><img src="https://storage.googleapis.com/coderabbit_public_assets/review-comment-icons-v1/info.svg" width="16" height="16" align="absmiddle" alt=""></picture>'
        body = ("<!-- coderabbit-ai-generated:v1 -->\n"
                "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->\n"
                "<!-- recent_review_start -->\nNo actionable comments were generated in the recent review.\n"
                f"<details>\n<summary><strong>{icon} Recent review info</strong></summary>\n"
                "<!-- review_info_content -->\n"
                "- **Source mode**: Auto\n"
                f"- **Repository**: [{slug}](<https://github.com/{slug}>)\n"
                f"- **Branch**: [codex/test](<https://github.com/{slug}/tree/codex%2Ftest>)\n"
                f"- **File**: [.coderabbit.yaml](<https://github.com/{slug}/blob/{head}/.coderabbit.yaml>)\n"
                f"- **Commit**: [{head[:7]}](<https://github.com/{slug}/commit/{head}>)\n"
                "- **Layers**: Repository YAML; Enforced overrides: Organization\n"
                "- **Review profile**: ASSERTIVE\n- **Plan**: Team\n"
                "- **Run ID**: `ac322244-dec0-4e54-a7f7-fc913274e49c`\n"
                "**Included review availability:** This review used your included allowance. 0 included reviews remain after this review. Your included PR review attempts over the past 7 days set your current allowance at 1 review per hour.\n"
                f"Reviewing files that changed from the base of the PR and between {base} and {head}.\n"
                "</details>\n<!-- recent_review_end -->\n<!-- final_review_risk_start -->\n"
                + '<!-- final_review_risk_coverage:' + json.dumps({"sourceCommitId": head, "coveredCommitId": head, "kind": "reviewed"})
                + ' -->\n<!-- final_review_risk_end -->')
        user = {"id": 136622811, "login": "coderabbitai[bot]", "type": "Bot"}
        entry = {"id": 42, "user": user, "body": body, "created_at": "2026-10-26T20:00:00Z",
                 "updated_at": "2026-10-26T20:01:00Z", "html_url": f"https://github.com/{slug}/pull/7#issuecomment-42"}
        pr = {"number": 7, "url": f"https://github.com/{slug}/pull/7", "headRefOid": head,
              "headRefName": "codex/test", "baseRefOid": base, "reviews": [], "author": {"login": "jscraik"}}
        statuses = [{"id": 50, "context": "CodeRabbit", "state": "success", "creator": user,
                     "created_at": entry["updated_at"]}]
        with (patch.object(MODULE, "repository_slug", return_value=(slug, None)),
              patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 0, base, "")),
              patch.object(MODULE, "_coderabbit_statuses", return_value=statuses),
              patch.object(MODULE, "_codex_completion_snapshot", return_value=(True, None))):
            def candidate(value=body, **changes):
                return MODULE.coderabbit_completion_review(Path.cwd(), pr, head, [], [{**entry, "body": value, **changes}])[0]
            self.assertIsNotNone(candidate())
            essentials = body.replace("- **Plan**: Team", "- **Plan**: Essentials")
            self.assertNotEqual(essentials, body)
            self.assertIsNotNone(candidate(essentials), "the observed Essentials plan label is review metadata")
            coverage = json.dumps({"sourceCommitId": head, "coveredCommitId": head, "kind": "reviewed"})
            deeply_nested = "[" * 10000 + "0" + "]" * 10000
            self.assertIsNone(candidate(essentials.replace(coverage, deeply_nested)))
            for changed in (
                essentials.replace("**Plan**: Essentials", "**Plan**: Essentials with findings"),
                essentials.replace("/commit/" + head, "/commit/" + base),
                essentials.replace("</details>", "</details> Context from checks skipped due to timeout: 1", 1),
                essentials + "\nFinding: unsafe write",
            ):
                with self.subTest(essentials_negative=changed):
                    self.assertIsNone(candidate(changed))
            details = ('<!-- review_details_start --><details><summary><strong>📜 Recent review details</strong></summary><dl><dd>'
                       '<details><summary><strong>Additional comments: 1</strong></summary><dl><dd>'
                       '<details><summary><strong>README.md: 1</strong></summary><dl><dd>'
                       '`3-4`: LGTM!<!-- cr-comment:v1:2f20a85a7ae118d9fc590a54 -->'
                       '</dd></dl></details></dd></dl></details></dd></dl></details><!-- review_details_end -->')
            with_details = body.replace('<!-- recent_review_end -->', details + '<!-- recent_review_end -->')
            self.assertIsNotNone(candidate(with_details))
            # Native summaries put a literal HTML break after metadata and
            # detail wrappers. Formatting must not become unknown evidence.
            spaced = with_details.replace('</summary>', '</summary>\n<br>\n').replace('<dd>', '<dd>\n<br>\n')
            self.assertIsNotNone(candidate(spaced))
            for changed in (
                spaced.replace('<br>', '<br data-note="Finding: unsafe write">', 1),
                spaced.replace('<br>', '<br>\nFinding: unsafe write', 1),
                spaced.replace('LGTM!', 'LGTM! Inspection incomplete.'),
                spaced.replace('Additional comments: 1', 'Remote MCP Linear'),
                spaced.replace('/commit/' + head, '/commit/' + base),
                spaced + '\nFinding: unsafe write',
            ):
                with self.subTest(html_break_negative=changed):
                    self.assertIsNone(candidate(changed))
            with patch.object(MODULE, '_coderabbit_statuses', return_value=[]):
                self.assertIsNone(candidate(spaced))
            with patch.object(MODULE, '_codex_completion_snapshot', return_value=(False, 'changed')):
                self.assertIsNone(candidate(spaced))
            timeout_details = ('<!-- review_details_start --><details><summary><strong>📜 Recent review details</strong></summary><dl><dd>'
                               '<details><summary><strong>Context from checks skipped due to timeout: 2</strong></summary><dl><dd>'
                               '* GitHub Check: CodeRabbit\n* GitHub Check: pr-pipeline - 0a09abcf'
                               '</dd></dl></details></dd></dl></details><!-- review_details_end -->')
            self.assertIsNone(candidate(essentials.replace('<!-- recent_review_end -->', timeout_details + '<!-- recent_review_end -->')))
            for changed in (with_details.replace('LGTM!', 'Fix unsafe write.'),
                            with_details.replace('Additional comments: 1', 'Additional comments: 2'),
                            with_details.replace('`3-4`', '`4-3`'),
                            with_details.replace('LGTM!', 'LGTM! Inspection failed.'),
                            with_details.replace('Additional comments: 1', 'Remote MCP Linear')):
                self.assertIsNone(candidate(changed))
            for changed in (body.replace('/commit/' + head, '/commit/' + base),
                            body.replace('codex%2Ftest', 'codex%2Fother'),
                            body.replace('**Repository**: [jscraik/configs]', '**Repository**: [other/repo]'),
                            body.replace('info.svg', 'unknown.svg'),
                            body.replace('<!-- review_info_content -->', '<!-- review_info_content --> Finding: unsafe write'),
                            body.replace('</details>', '</details> Context from checks skipped due to timeout: 1', 1),
                            body.replace('No actionable comments were generated', 'Actionable comments were generated')):
                with self.subTest(changed=changed):
                    self.assertIsNone(candidate(changed))
            self.assertIsNone(candidate(user={**user, "type": "User"}))
            with patch.object(MODULE, "_coderabbit_statuses", return_value=[]):
                self.assertIsNone(candidate())
            with patch.object(MODULE, "_coderabbit_statuses", return_value=None):
                review, error = MODULE.coderabbit_completion_review(Path.cwd(), pr, head, [], [entry])
                self.assertIsNone(review)
                self.assertEqual(error, "CodeRabbit completion status inventory unavailable")
            with patch.object(MODULE, "_codex_completion_snapshot", return_value=(False, "changed")):
                self.assertIsNone(candidate())

    def test_unknown_codex_praise_cannot_clear_a_head_bound_report(self) -> None:
        head = "a" * 40
        body = self.codex_code_report(head)
        review = {"state": "COMMENTED", "commit_id": head,
                  "user": {"login": "chatgpt-codex-connector[bot]"}, "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(review, head))
        for ending in ("Nice work!", "Keep it up!", "What shall we delve into next?"):
            with self.subTest(ending=ending):
                changed = body.replace("Already looking forward to the next diff.", ending)
                self.assertNotEqual(changed, body)
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": changed}, head))

    @staticmethod
    def coderabbit_clearance(head: str) -> str:
        return ("<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                "<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n"
                f"No findings for {head}.\n\n_You are interacting with an AI system._")

    def test_coderabbit_issue_status_never_substitutes_for_formal_review(self) -> None:
        head = "a" * 40
        entry = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED",
                 "body": f"No findings for {head}.", "created_at": "2026-10-19T10:00:00Z"}
        self.assertEqual(MODULE.current_head_bot_issue_comments([entry], head), {"coderabbitai": entry})
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, head))
        self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "commit_id": "b" * 40}, head))
        formal = {**entry, "commit": {"oid": head}, "submittedAt": "2026-10-19T10:01:00Z"}
        self.assertTrue(MODULE._bot_review_is_acceptable(formal, head))
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=([entry], None)),
              patch.object(MODULE, "codex_completion_review", return_value=(None, None)),
              patch.object(MODULE, "review_requirement", return_value={
                  "risk_tier": "ordinary", "required_bot_review_count": 1})):
            pr = {"number": 7, "reviews": []}
            self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), {**pr, "reviews": [formal]}, head)["status"], "pass")


    def test_observed_provider_envelopes_retain_clearance_boundaries(self) -> None:
        """Conversational replies and unknown praise cannot clear a review."""
        head = "a" * 40
        rabbit = (
            "<!-- coderabbit-ai-generated:v1 -->\n\n"
            "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
            "> [!TIP]\n> For best results, initiate chat on the files or code changes.\n\n"
            "<details>\n<summary>🧩 Analysis chain</summary>\n\n"
            "🏁 Script executed:\n\n```shell\ngh api repos/jscraik/websites/issues/comments/6313224709\n```\n\n"
            "Length of output: 5055\n\n---\n\n</details>\n\n"
            f"`@jscraik`\n\nNo findings for {head}.\n\n_You are interacting with an AI system._"
        )
        codex = "<!-- codex-review-receipt:v1 -->\n\n" + self.codex_code_report(head).replace(
            "Already looking forward to the next diff.", "What shall we delve into next?")
        for login, body in (("coderabbitai[bot]", rabbit), ("chatgpt-codex-connector[bot]", codex)):
            entry = {"state": "COMMENTED", "user": {"login": login}, "body": body}
            with self.subTest(login=login):
                self.assertFalse(MODULE._bot_review_is_acceptable(entry, head))
                self.assertFalse(MODULE._bot_review_is_acceptable(entry, "b" * 40))
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "user": {"login": "untrusted"}}, head))
                for malformed in (body + "\nFinding: unsafe write", body.replace(":v1", ":v2"),
                                  body.replace("No findings for", "> No findings for") if login.startswith("coderabbit")
                                  else body.replace("What shall we delve into next?", "Inspection incomplete.")):
                    self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": malformed}, head))
        duplicate = rabbit.replace("<!-- coderabbit-ai-generated:v1 -->", "<!-- coderabbit-ai-generated:v1 -->\n\n<!-- coderabbit-ai-generated:v1 -->")
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {"state": "COMMENTED", "user": {"login": "coderabbitai[bot]"}, "body": duplicate}, head))
        keep_up = codex.replace("What shall we delve into next?", "Keep it up!")
        entry = {"state": "COMMENTED", "user": {"login": "chatgpt-codex-connector[bot]"}, "body": keep_up}
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, head))
        for malformed in (keep_up + "\nFinding: unsafe write", keep_up.replace("Keep it up!", "Keep it up! Inspection incomplete.")):
            self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": malformed}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, "b" * 40))

    def test_valid_provider_controls_isolate_each_clearance_rejection(self) -> None:
        head = "a" * 40
        for login, body, mutations in (
            ("coderabbitai[bot]", self.coderabbit_clearance(head), (
                lambda text: text + "\nFinding: unsafe write",
                lambda text: text.replace("reply by CodeRabbit -->", "reply by CodeRabbit v2 -->"),
                lambda text: text.replace("No findings for", "> No findings for"))),
            ("chatgpt-codex-connector[bot]", "<!-- codex-review-receipt:v1 -->\n\n" + self.codex_code_report(head), (
                lambda text: text + "\nFinding: unsafe write",
                lambda text: text.replace(":v1", ":v2"),
                lambda text: text.replace("Already looking forward to the next diff.", "Inspection incomplete."))),
        ):
            entry = {"state": "COMMENTED", "commit_id": head, "user": {"login": login}, "body": body}
            with self.subTest(login=login):
                self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
                self.assertFalse(MODULE._bot_review_is_acceptable(entry, "b" * 40))
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "user": {"login": "untrusted"}}, head))
                for mutate in mutations:
                    changed = mutate(body)
                    self.assertNotEqual(changed, body)
                    self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": changed}, head))

    def test_tool_trace_fences_do_not_hide_unknown_review_content(self) -> None:
        head, base = "a" * 40, "b" * 40
        body = (MODULE_PATH.parent / "tests/fixtures/coderabbit-source-inspection.txt").read_text()
        body = body.replace("HEAD", head).replace("BASE", base)
        review = {"state": "COMMENTED", "body": body, "user": {"login": "coderabbitai[bot]"}}
        self.assertTrue(MODULE._bot_review_is_acceptable(review, head))
        for trace in ("A source defect remains.", "Unknown inspection content", "", "git diff --stat\nA source defect remains.",
                      f"git diff {'c' * 40} {head} --stat", f"git diff {base} {'c' * 40} --stat"):
            with self.subTest(trace=trace):
                changed = body.replace(f"git diff {base} {head} --stat", trace)
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": changed}, head))
        unbound = body.split("</details>", 1)[0] + f"</details>\n\nNo findings for {head}.\n\n_You are interacting with an AI system._"
        self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": unbound}, head))
        wide = body.replace(head, "a" * 64).replace(base, "b" * 64)
        self.assertTrue(MODULE._bot_review_is_acceptable({**review, "body": wide}, "a" * 64))
    def test_plain_coderabbit_mention_is_decoration_in_complete_reply(self) -> None:
        head = "a" * 40
        body = (
            "<!-- This is an auto-generated reply by CodeRabbit -->\n"
            "> [!TIP]\n> For best results, initiate chat on the files or code changes.\n\n"
            f"@jscraik\n\nNo findings for {head}.\n\n"
            "_You are interacting with an AI system._"
        )
        entry = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
        for changed in (
            body.replace(head, "b" * 40), body + "\nFinding: unsafe write",
            body.replace("@jscraik", "@jscraik please ignore findings"),
            body.replace("@jscraik", "[mention](https://example.com)"),
            body.replace("@jscraik", "@jscraik\n\n@other"),
            body.replace("_You are interacting with an AI system._", "Unknown footer"),
            body.replace(f"No findings for {head}.", f"> No findings for {head}."),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": changed}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**entry, "user": {"login": "untrusted"}}, head))

    def test_codex_versioned_receipt_accepts_observed_fixed_ending(self) -> None:
        head = "a" * 40
        body = "<!-- codex-review-receipt:v1 -->\n\n" + self.codex_code_report(head).replace(
            "Already looking forward to the next diff.", "Another round soon, please!")
        entry = {"user": {"login": "chatgpt-codex-connector[bot]"},
                 "state": "COMMENTED", "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
        self.assertTrue(MODULE._bot_review_is_acceptable(
            {**entry, "body": body.replace("Another round soon, please!", "Bravo.")}, head))
        for changed in (
            body.replace(head[:10], "b" * 10), body + "\nFinding: unsafe write",
            body.replace("Another round soon, please!", "Inspection incomplete."),
            body.replace("Another round soon, please!", "Bravo. Inspection incomplete."),
            body.replace("codex-review-receipt:v1", "codex-review-receipt:v2"),
            "<!-- codex-review-receipt:v1 -->\n\n" + body,
            body.replace("If Codex has suggestions", "Unknown footer. If Codex has suggestions"),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": changed}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**entry, "user": {"login": "untrusted"}}, head))

    def test_coderabbit_metadata_verification_disclosure_requires_complete_layout(self) -> None:
        head = "a" * 40
        body = (
            "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
            "<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n"
            f"`@jscraik` No findings for {head}.\n\n"
            "The completed review’s only actionable finding concerned installed-wheel validation evidence. "
            "[The subsequent verification](https://github.com/jscraik/skills-sdk/pull/60#discussion_r4248877026) "
            "confirmed that the published PR body satisfied that finding.\n\n"
            "This clarifies the existing inspection record. It does not grant approval or establish merge readiness.\n\n"
            "_You are interacting with an AI system._"
        )
        entry = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
        for changed in (
            body.replace("<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n", ""),
            body.replace(head, "b" * 40),
            body + "\nFinding: unsafe write",
            body.replace("confirmed that", "did not confirm that"),
            body.replace("https://github.com/", "https://example.com/"),
            body.replace("It does not grant approval", "It grants approval"),
            body.replace("No findings for", "Findings for"),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": changed}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**entry, "user": {"login": "untrusted-reviewer"}}, head,
        ))

    def test_metadata_verification_link_is_bound_to_active_pr_and_head(self) -> None:
        head = "a" * 40
        base = "c" * 40
        pr = {"url": "https://github.com/jscraik/skills-sdk/pull/60", "baseRefOid": base}
        link = pr["url"] + "#discussion_r4248877026"
        body = (
            "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
            "<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n"
            f"No findings for {head}.\n\n"
            "The completed review’s only actionable finding concerned installed-wheel validation evidence. "
            f"[The subsequent verification]({link}) "
            "confirmed that the published PR body satisfied that finding.\n\n"
            "This clarifies the existing inspection record. It does not grant approval or establish merge readiness.\n\n"
            "_You are interacting with an AI system._"
        )
        candidate = {"user": {"login": "coderabbitai[bot]"}, "body": body,
                     "created_at": "2026-10-12T14:02:00Z"}
        source = {"id": 4248877026, "html_url": link, "commit_id": head,
                  "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 136622811},
                  "in_reply_to_id": 4246906356, "created_at": "2026-10-12T14:01:01Z",
                  "body": (
                      "`@jscraik` Verified the published PR body. The Validation section lists all three exact "
                      "installed-phase commands with individual **pass** outcomes. It states the "
                      "wrapper-execution boundary and separates historical results.\n\n"
                      f"The head `{head}` and base `{base}` identifiers match those you supplied. This satisfies the metadata "
                      "finding. Independent review and merge-readiness remain separate gates.\n\n"
                      "✅ Review thread resolved.\n\n_You are interacting with an AI system._\n\n"
                      "<!-- This is an auto-generated reply by CodeRabbit -->")}
        parent = {"id": 4246906356, "html_url": pr["url"] + "#discussion_r4246906356",
                  "commit_id": head, "user": {**source["user"], "avatar_url": "https://example.invalid/updated"},
                  "created_at": "2026-10-12T10:18:44Z",
                  "body": "**Record the exact installed-wheel smoke commands and outcomes.**\n\nFinding."}
        unbound = {**source, "body": source["body"].replace(f"head `{head}` and base `{base}`", "head and base")}
        self.assertFalse(MODULE._inspection_provenance_matches(
            Path.cwd(), {**pr, "baseRefOid": "d" * 40}, head, candidate, [unbound, parent]))
        self.assertTrue(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, candidate, [source, parent]))
        for analysis, accepted in (("Inspected exact candidate.", True),
            ("Finding remains: installed-wheel evidence is incomplete.", False),
            ("Inspection did not complete.", False), ("HTTP 401 Unauthorized", False),
            ("<details>nested</details>", False)):
            with self.subTest(source_analysis=analysis):
                wrapped = "<details>\n<summary>🧩 Analysis chain</summary>\n\n" + analysis + "\n\n</details>\n\n"
                self.assertEqual(MODULE._inspection_provenance_matches(
                    Path.cwd(), pr, head, candidate, [{**source, "body": wrapped + source["body"]}, parent]), accepted)
        for identity in (
            {**parent["user"], "type": "User"}, {**parent["user"], "id": True},
            {**parent["user"], "id": 0}, {**parent["user"], "id": 136622812},
            {**parent["user"], "login": "other-bot"}, None,
        ):
            with self.subTest(parent_identity=identity):
                self.assertFalse(MODULE._inspection_provenance_matches(
                    Path.cwd(), pr, head, candidate, [source, {**parent, "user": identity}]))
        for changed_pr, sources in (
            ({**pr, "baseRefOid": "d" * 40}, [source]),
            ({"url": pr["url"]}, [source]),
            ({"url": "https://github.com/other/repo/pull/60"}, [source]),
            ({"url": "https://github.com/jscraik/skills-sdk/pull/61"}, [source]),
            (pr, []), (pr, [source, source]),
            (pr, [{**source, "html_url": link.replace("4248877026", "4248877027")}]),
            (pr, [{**source, "id": 4248877027}]),
            (pr, [{**source, "commit_id": "b" * 40}]),
            (pr, [{**source, "user": {"login": "pr-author", "type": "User", "id": 1}}]),
            (pr, [{**source, "user": {**source["user"], "type": "User"}}]),
            (pr, [{**source, "user": {**source["user"], "id": True}}]),
            (pr, [{**source, "body": "Finding remains"}]),
            (pr, [{**source, "body": "Unrelated current-head note"}]),
        ):
            with self.subTest(context=(changed_pr, sources)):
                self.assertFalse(MODULE._inspection_provenance_matches(
                    Path.cwd(), changed_pr, head, candidate, [*sources, parent]))
        for changed_parent, changed_source, changed_candidate in (
            ({**parent, "body": "Unrelated finding"}, source, candidate),
            ({**parent, "commit_id": "b" * 40}, source, candidate),
            ({**parent, "created_at": "2026-10-12T14:01:02Z"}, source, candidate),
            (parent, {**source, "in_reply_to_id": True}, candidate),
            (parent, source, {**candidate, "created_at": "2026-10-12T14:00:00Z"}),
            (parent, {**source, "body": source["body"] + "\nFinding remains"}, candidate),
            (parent, {**source, "body": source["body"].replace(f"head `{head}` and base `{base}`", "head and base")}, candidate),
            (parent, {**source, "body": source["body"].replace(base, "d" * 40)}, candidate),
        ):
            with self.subTest(context=(changed_parent, changed_source, changed_candidate)):
                self.assertFalse(MODULE._inspection_provenance_matches(
                    Path.cwd(), pr, head, changed_candidate, [changed_source, changed_parent]))

    def test_completed_source_verdict_does_not_turn_failed_review_into_clearance(self) -> None:
        head, base = "a" * 40, "b" * 40
        body = (MODULE_PATH.parent / "tests/fixtures/coderabbit-completed-source-verdict.txt").read_text()
        body = body.replace("HEAD", head).replace("BASE", base)
        review = {"state": "COMMENTED", "body": body, "user": {"login": "coderabbitai[bot]"}}
        pr = {"baseRefOid": base, "url": "https://github.com/jscraik/configs/pull/348"}
        self.assertTrue(MODULE._bot_review_is_acceptable(review, head))
        self.assertFalse(MODULE._independent_inspection_report(body))
        with (patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 0)),
              patch.object(MODULE, "changed_file_records", return_value=[{}] * 5)):
            self.assertTrue(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, review, []))
            self.assertFalse(MODULE._inspection_provenance_matches(
                Path.cwd(), {**pr, "baseRefOid": "c" * 40}, head, review, []))
        with patch.object(MODULE, "changed_file_records", return_value=[{}] * 4):
            self.assertFalse(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, review, []))
        for changed in (
            body.replace("did not invalidate", "invalidated"),
            body.replace("reported no remaining findings", "reported unresolved findings"),
            body.replace("all five", "all five; an unsafe write remains in the"),
            body.replace(f"for `{head}`", f"for `{'c' * 40}`"),
            body + "\n\nReview rate limited.",
            body.replace("<!-- This is an auto-generated reply by CodeRabbit -->",
                         "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                         "<details>\n<summary>🧩 Analysis chain</summary>\n\n"
                         "A source defect remains.\n\n</details>", 1),
            body + "\n\n<details>\n<summary>Action not completed</summary>\nReview failed.\n</details>",
            body.replace(f"No findings for {head}.", f"`No findings for {head}.`"),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": changed}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(review, "c" * 40))
        self.assertFalse(MODULE._bot_review_is_acceptable({**review, "state": "CHANGES_REQUESTED"}, head))
        with (patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 0)),
              patch.object(MODULE, "changed_file_records", return_value=[{}] * 6)):
            six = {**review, "body": body.replace("all five", "all six")}
            self.assertTrue(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, six, []))
            self.assertFalse(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, review, []))

    def test_source_inspection_reports_retain_complete_envelopes_and_provenance(self) -> None:
        head, base = "a" * 40, "b" * 40
        url = "https://github.com/jscraik/configs/pull/347"
        link = url + "#issuecomment-1111111111"
        fixture = MODULE_PATH.parent / "tests/fixtures"
        bodies = [(fixture / name).read_text().replace("HEAD", head).replace("BASE", base)
                  .replace("SOURCE", link) for name in (
                      "coderabbit-source-inspection.txt", "coderabbit-source-clarification.txt")]
        report, clarification = [{"state": "COMMENTED", "body": body,
                                  "user": {"login": "coderabbitai[bot]"}}
                                 for body in bodies]
        report["html_url"] = link
        pr = {"url": url, "baseRefOid": base}
        with (patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 0)),
              patch.object(MODULE, "changed_file_records", return_value=[
                  {"path": "codex/config.toml"}, {"path": "codex/scripts/validate-codex-hooks.sh"}])):
            for entry in (report, clarification):
                self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
                self.assertTrue(MODULE._inspection_provenance_matches(
                    Path.cwd(), pr, head, entry, [report]))
                for paths in ([{"path": "README.md"}, {"path": "other.py"}], [{}, {}], [{"path": "codex/config.toml"}] * 2):
                    with self.subTest(paths=paths), patch.object(MODULE, "changed_file_records", return_value=paths):
                        self.assertFalse(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, entry, [report]))
            for changed_pr, changed_entry, sources in (
                ({**pr, "baseRefOid": "c" * 40}, report, [report]),
                (pr, clarification, []),
                (pr, clarification, [{**report, "user": {"login": "pr-author"}}]),
                (pr, clarification, [clarification]),
                ({**pr, "url": "https://github.com/other/repo/pull/347"}, clarification, [report]),
                (pr, clarification, [{**report, "body": bodies[0].replace(head, "d" * 40)}]),
            ):
                with self.subTest(context=(changed_pr, changed_entry, sources)):
                    self.assertFalse(MODULE._inspection_provenance_matches(
                        Path.cwd(), changed_pr, head, changed_entry, sources))
        with patch.object(MODULE, "changed_file_records", return_value=[{}]):
            self.assertFalse(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, report, []))
        for entry in (report, clarification):
            for body in (
                entry["body"] + "\n\nA source defect remains.",
                entry["body"].replace("\n</details>", "\nA source defect remains.\n\n</details>", 1),
                entry["body"].replace("\n</details>", "\nUnexpected review narrative.\n\n</details>", 1),
                entry["body"].replace(f"No findings for {head}.", f"> No findings for {head}."),
                entry["body"].replace("Inspected both", "Unsafe writes remain; inspected both"),
                entry["body"].replace("**Inspection evidence**", "<div>Inspection evidence</div>"),
                entry["body"].replace("did not execute", "did execute"),
                entry["body"].replace("did not independently execute", "could not inspect"),
                entry["body"].replace("Length of output: 42", "Output:\n\n```stderr\nrate limit exceeded\n```"),
            ):
                if body == entry["body"]:
                    continue
                with self.subTest(body=body):
                    self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": body}, head))
            self.assertFalse(MODULE._bot_review_is_acceptable(entry, "d" * 40))
            self.assertFalse(MODULE._bot_review_is_acceptable(
                {**entry, "user": {"login": "pr-author"}}, head))

    def test_code_only_activity_summary_is_neutral_never_clearance(self) -> None:
        head = "983e9e55b0b29fc19186e3a7a86cd9a0514e7324"
        full = (MODULE_PATH.parent / "tests/fixtures/codex-summary.txt").read_text()
        body = "\n".join(line for line in full.splitlines()
                         if not line.startswith(("<!-- codex-security-review:", "| 🔒")))
        entry = {"user": {"login": "chatgpt-codex-connector[bot]"},
                 "state": "COMMENTED", "body": body, "created_at": "2026-10-13T12:00:00Z"}
        self.assertTrue(MODULE._codex_informational_report(entry))
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, head))
        self.assertEqual(MODULE.current_head_bot_issue_comments([entry], head), {})
        self.assertEqual(MODULE.outstanding_bot_concerns([], [], [entry], head), [])
        concern = {**entry, "body": "Finding: unsafe write", "created_at": "2026-10-13T11:00:00Z"}
        self.assertEqual(MODULE.outstanding_bot_concerns([], [], [concern, entry], head), ["Codex"])
        for invalid in (body + "\nFinding remains", body.replace("**Completed**", "**Failed**"),
                        body.replace("Manual request", "unknown"),
                        body.replace(f"`{head[:7]}`", "`not-a-commit`"),
                        body.replace("</details>", "Review failed</details>")):
            self.assertFalse(MODULE._codex_informational_report({**entry, "body": invalid}))
        self.assertFalse(MODULE._codex_informational_report(
            {**entry, "user": {"login": "untrusted"}}))

    def test_observed_codex_closing_preserves_clearance_boundaries(self) -> None:
        head = "a" * 40
        body = self.codex_code_report(head).replace(
            "Already looking forward to the next diff.", "Can't wait for the next one!")
        entry = {"user": {"login": "chatgpt-codex-connector[bot]"},
                 "state": "COMMENTED", "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, "b" * 40))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**entry, "user": {"login": "untrusted"}}, head))
        for invalid in (body + "\nFinding remains", body.replace("Can't wait for the next one!", ":-1:"),
                        body.replace("</details>", "Review failed</details>")):
            with self.subTest(invalid=invalid):
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": invalid}, head))

    def test_coderabbit_learning_disclosure_is_context_not_clearance(self) -> None:
        head = "a" * 40
        learning = ("---\n\n<details>\n<summary>🧠 Learnings used</summary>\n\n```\n"
                    "Learnt from: example-user\nURL: https://github.com/example/project/pull/7\n\n"
                    "Timestamp: 2026-10-13T11:52:38.816Z\n"
                    "Learning: This manifest configures cloud automation.\n```\n\n</details>\n\n")
        prefix = "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
        footer = "_You are interacting with an AI system._"
        analysis = "<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n"
        body = prefix + "`@example-user`\n\n" + analysis + f"No findings for {head}.\n\n" + learning + footer
        entry = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, "b" * 40))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**entry, "user": {"login": "untrusted"}}, head))
        invalid_bodies = (
            body.replace(f"No findings for {head}.", "Finding: unsafe write."),
            prefix + learning.replace("This manifest configures cloud automation.",
                                      f"No findings for {head}.") + footer,
            body.replace("🧠 Learnings used", "Findings"),
            body.replace("```\n\n</details>", "```\n\nFinding: unsafe write.\n\n</details>"),
            body.replace("Learning: This manifest", "Unknown: This manifest"),
            body.replace("```\nLearnt", "```output\nLearnt"),
            body.replace("</details>", "<details>hidden</details></details>"),
            body.replace(footer, learning + footer),
            body + "\nFinding remains",
            body.replace(f"No findings for {head}.", f"Review failed for {head}."),
        )
        for invalid in invalid_bodies:
            with self.subTest(invalid=invalid):
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": invalid}, head))
    def test_codex_fixed_quota_reports_are_neutral_never_clearance(self) -> None:
        head = "a" * 40
        reports = (
            ("Codex usage limits have been reached for code reviews. Please check with the admins of this repo to increase the limits by adding credits.\n"
             "Repo admins can enable using credits for code reviews in their [settings](https://chatgpt.com/codex/cloud/settings/code-review)."),
            "You have reached your Codex usage limits for code reviews. You can see your limits in the [Codex usage dashboard](https://chatgpt.com/codex/cloud/settings/usage).",
        )
        for body in reports:
            entry = {"user": {"login": "chatgpt-codex-connector[bot]"}, "body": body,
                     "state": "COMMENTED", "created_at": "2026-10-08T17:40:00Z"}
            with self.subTest(body=body):
                self.assertFalse(MODULE._bot_review_is_acceptable(entry, head))
                self.assertEqual(MODULE.outstanding_bot_concerns([], [], [entry], head), [])
                concern = {**entry, "body": "Finding: unsafe write", "created_at": "2026-10-08T17:30:00Z"}
                self.assertEqual(MODULE.outstanding_bot_concerns([], [], [concern, entry], head), ["Codex"])
                for changed in (body + "\nFinding: unsafe write", body.replace("https://chatgpt.com/", "https://example.com/")):
                    self.assertEqual(MODULE.outstanding_bot_concerns([], [], [{**entry, "body": changed}], head), ["Codex"])
                self.assertEqual(MODULE.outstanding_bot_concerns([], [], [{**entry, "user": {"login": "coderabbitai[bot]"}}], head), ["CodeRabbit"])
                clear = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "commit_id": head,
                         "body": f"No findings for {head}."}
                with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
                      patch.object(MODULE, "review_comments", return_value=([], None)),
                      patch.object(MODULE, "issue_comments", return_value=([entry], None))):
                    for count, expected in ((1, "pass"), (2, "fail")):
                        with patch.object(MODULE, "review_requirement", return_value={"required_bot_review_count": count}):
                            self.assertEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": [clear]}, head)["status"], expected)

    def test_coderabbit_fixed_learning_appendix_is_decoration(self) -> None:
        head = "a" * 40
        appendix = (
            "\n\n---\n\n<details>\n<summary>✏️ Learnings added</summary>\n\n"
            "```\nLearnt from: jscraik\nURL: https://github.com/jscraik/skills-foundry/pull/46\n\n"
            "Timestamp: 2026-10-08T17:42:35.596Z\nLearning: Preserve the exact-head gate.\n```\n\n"
            "> Note: Learnings are effective only in the context of similar code segments. To apply general coding guidelines, please configure [review instructions](https://docs.coderabbit.ai/guides/review-instructions). You can manage existing learnings in the [app](https://app.coderabbit.ai/learnings).\n\n</details>"
        )
        body = ("<!-- This is an auto-generated reply by CodeRabbit -->\n\n`@jscraik`\n\n"
                "<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n"
                f"No findings for {head}.\n\n_You are interacting with an AI system._" + appendix)
        entry = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
        self.assertTrue(MODULE._bot_review_is_acceptable({**entry, "body": body.replace(appendix, "")}, head))
        metadata = (
            "The completed review’s only actionable finding concerned installed-wheel validation evidence. "
            "[The subsequent verification](https://github.com/jscraik/skills-sdk/pull/60#discussion_r4248877026) "
            "confirmed that the published PR body satisfied that finding.\n\n"
            "This clarifies the existing inspection record. It does not grant approval or establish merge readiness.\n\n"
        )
        combined = body.replace("_You are interacting", metadata + "_You are interacting")
        self.assertTrue(MODULE._bot_review_is_acceptable({**entry, "body": combined}, head))
        for changed in (
            combined.replace(head, "b" * 40),
            combined.replace("✏️ Learnings added", "Other appendix"),
            combined + "\nFinding: unsafe write",
            combined.replace("confirmed that", "did not confirm that"),
            combined.replace("Preserve the exact-head gate.", "Preserve the exact-head gate.\nFinding: unsafe write"),
        ):
            with self.subTest(combined=changed):
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": changed}, head))
        tip = "> [!TIP]\n> For best results, initiate chat on the files or code changes.\n\n"
        marker = "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
        used = (
            "\n\n---\n\n<details>\n<summary>🧠 Learnings used</summary>\n\n"
            "```\nLearnt from: jscraik\nURL: https://github.com/jscraik/configs/pull/333\n\n"
            "Timestamp: 2026-10-10T23:01:39.207Z\nLearning: Preserve the exact-head gate.\n```\n\n</details>"
        )
        clearance = {**entry, "body": body, "created_at": "2026-10-10T23:00:00Z"}
        for analysis in ("Rate limit exceeded errors are retried", "HTTP 401 Unauthorized errors are retried",
                         f"Rate limit exceeded errors are retried for {head}"):
            unbound = tip + body.replace("Inspected exact candidate.", analysis).replace(
                f"No findings for {head}.", "No findings.")
            later = {**entry, "body": unbound, "created_at": "2026-10-10T23:01:00Z"}
            with self.subTest(unbound_analysis=analysis):
                self.assertFalse(MODULE._bot_review_has_blocked_response(unbound, login="coderabbitai"))
                selected = MODULE.current_head_bot_issue_comments([clearance, later], head)
                self.assertEqual(selected["coderabbitai"], clearance)
                self.assertEqual(MODULE.outstanding_bot_concerns([], [], [clearance, later], head), [])
                failure = unbound.replace(analysis, "Review failed: quota exceeded")
                self.assertTrue(MODULE._bot_review_has_blocked_response(failure, login="coderabbitai"))
                selected = MODULE.current_head_bot_issue_comments([clearance, {**later, "body": failure}], head)
                self.assertEqual(selected["coderabbitai"]["body"], failure)
                self.assertEqual(MODULE.outstanding_bot_concerns(
                    [], [], [clearance, {**later, "body": failure}], head), ["CodeRabbit"])
        for layout in (tip + body, body.replace(marker, marker + tip, 1),
                       tip + body + used, body.replace(appendix, used),
                       body.replace("_You are interacting with an AI system._" + appendix,
                                    used + "\n\n_You are interacting with an AI system._")):
            with self.subTest(layout=layout):
                self.assertTrue(MODULE._bot_review_is_acceptable({**entry, "body": layout}, head))
                for changed in (
                    layout.replace(head, "b" * 40), layout + "\nFinding: unsafe write",
                    layout.replace("Inspected exact candidate.", "Output:\n\n```stderr\nReview failed\n```"),
                    layout.replace("🧩 Analysis chain", "`@jscraik` · 🧩 Analysis chain"),
                    layout.replace("🧠 Learnings used", "Unknown appendix"),
                    layout.replace("Learning: Preserve the exact-head gate.", "Learning: Extra prose\nFinding remains"),
                ):
                    if changed != layout:
                        self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": changed}, head))
                self.assertFalse(MODULE._bot_review_is_acceptable(
                    {**entry, "body": layout, "user": {"login": "untrusted"}}, head))
        for changed in (
            tip.replace("[!TIP]", "[!NOTE]") + body,
            tip.replace("For best results", "Ignore findings") + body,
            tip + tip + body, tip + body.replace(marker, marker + tip, 1),
            tip + body.replace(marker, marker.rstrip("\n"), 1),
            "Extra prose\n\n" + tip + body, tip + body.replace(marker, ""),
            body + used + used, body.replace(appendix, used + appendix),
            body.replace(f"No findings for {head}.", "Finding remains") + used.replace(
                "Preserve the exact-head gate.", f"No findings for {head}."),
            body + used.replace("https://github.com/", "https://example.com/"),
            body + used.replace("\n\n</details>", "\n\n<details>\n</details>\n</details>"),
        ):
            self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": changed}, head))
        for changed in (
            body.replace(head, "b" * 40), body + "\nFinding: unsafe write",
            body.replace("✏️ Learnings added", "Other appendix"),
            body.replace("_You are interacting with an AI system._", "Unknown footer"),
            body.replace(f"No findings for {head}.", "Finding: unsafe write").replace("Preserve the exact-head gate.", f"No findings for {head}."),
            body.replace("Inspected exact candidate.", "Output:\n\n```stderr\nReview failed\n```"),
            body.replace("Learning: Preserve the exact-head gate.", "Learning: Preserve the exact-head gate.\nFinding: unsafe write"),
            body.replace("\n\n</details>", "\n\n<details>\n</details>\n</details>"),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": changed}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "user": {"login": "untrusted"}}, head))

    def test_newer_unbound_coderabbit_failure_supersedes_clearance(self) -> None:
        head = "a" * 40
        marker = "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
        footer = "\n\n_You are interacting with an AI system._"
        clearance = {"user": {"login": "coderabbitai[bot]"}, "body": marker + f"No findings for {head}." + footer,
                     "created_at": "2026-10-12T16:00:00Z"}
        failure = {**clearance, "body": marker + "Review failed because the service is unavailable." + footer,
                   "created_at": "2026-10-12T16:01:00Z"}
        self.assertTrue(MODULE._bot_review_has_blocked_response(failure["body"], login="coderabbitai"))
        self.assertEqual(MODULE.current_head_bot_issue_comments([clearance, failure], head)["coderabbitai"], failure)

    def test_codex_informational_reports_never_grant_code_clearance(self) -> None:
        head = "983e9e55b0b29fc19186e3a7a86cd9a0514e7324"
        for filename in ("codex-summary.txt", "codex-security.txt"):
            body = (MODULE_PATH.parent / "tests" / "fixtures" / filename).read_text()
            entry = {"user": {"login": "chatgpt-codex-connector[bot]"},
                     "state": "COMMENTED", "body": body, "created_at": "2026-10-07T16:00:00Z"}
            with self.subTest(filename=filename):
                self.assertTrue(MODULE._codex_informational_report(entry))
                self.assertFalse(MODULE._bot_review_is_acceptable(entry, head))
                self.assertEqual(MODULE.current_head_bot_issue_comments([entry], head), {})
                self.assertEqual(MODULE.outstanding_bot_concerns([], [], [entry], head), [])
                for changed in (body + "\nFinding: unsafe path", body.replace("completed", "failed")):
                    self.assertFalse(MODULE._codex_informational_report({**entry, "body": changed}))
                if filename == "codex-summary.txt":
                    self.assertFalse(MODULE._codex_informational_report(
                        {**entry, "body": body.replace(f"`{head[:7]}`", f"`{'b' * 7}`")}))
                    for trigger in ("PR opened", "New commits"):
                        self.assertTrue(MODULE._codex_informational_report(
                            {**entry, "body": body.replace("Manual request", trigger)}))
                    self.assertFalse(MODULE._codex_informational_report(
                        {**entry, "body": body.replace("Manual request", "Unknown trigger")}))
                self.assertFalse(MODULE._codex_informational_report(
                    {**entry, "user": {"login": "untrusted"}}))
                concern = {**entry, "body": f"Finding remains for head {head}", "created_at": "2026-10-07T15:00:00Z"}
                self.assertEqual(MODULE.outstanding_bot_concerns([], [], [concern, entry], head), ["Codex"])

    def test_codex_state_summary_is_bound_informational_evidence_only(self) -> None:
        head = "983e9e55b0b29fc19186e3a7a86cd9a0514e7324"
        summary = (MODULE_PATH.parent / "tests/fixtures/codex-summary.txt").read_text()
        state = {kind: {"commit_sha": head, "has_any_findings": False,
                       "has_unresolved_findings": False, "status": "completed"}
                 for kind in ("code_review", "security_review")}
        def decorated(value: dict[str, object]) -> str:
            marker = "<!-- codex-review-state:v1 " + json.dumps(value, separators=(",", ":")) + " -->\n"
            return summary.replace("<!-- codex-pull-request-review-summary -->\n",
                                   "<!-- codex-pull-request-review-summary -->\n" + marker, 1)
        body = decorated(state)
        entry = {"user": {"login": "chatgpt-codex-connector[bot]"}, "state": "COMMENTED", "body": body,
                 "html_url": "https://github.com/jscraik/skills-foundry/pull/43#issuecomment-1"}
        self.assertTrue(MODULE._codex_informational_report(entry))
        self.assertFalse(MODULE._bot_review_is_acceptable(entry, head))
        self.assertEqual(MODULE.current_head_bot_issue_comments([entry], head), {})
        self.assertEqual(MODULE.outstanding_bot_concerns([], [], [entry], head), [])
        concern = {**entry, "body": "Finding remains for head " + head}
        self.assertEqual(MODULE.outstanding_bot_concerns([], [], [concern, entry], head), ["Codex"])
        mutations = []
        for kind, details in state.items():
            for key, value in (("has_any_findings", True), ("has_unresolved_findings", 0),
                               ("status", "failed"), ("commit_sha", "a" * 40), ("extra", False)):
                mutations.append(decorated({**state, kind: {**details, key: value}}))
        mutations.extend((body + "\nFinding remains", body.replace('"has_any_findings":false',
                          '"has_any_findings":true,"has_any_findings":false', 1),
                          body.replace("<!-- codex-review-state:v1", "<!-- codex-review-state:v2")))
        for changed in mutations:
            self.assertFalse(MODULE._codex_informational_report({**entry, "body": changed}))
        for change in ({"user": {"login": "untrusted"}}, {"html_url": ""},
                       {"html_url": entry["html_url"].replace("/43#", "/44#")},
                       {"html_url": entry["html_url"].replace("skills-foundry", "other-repo")}):
            self.assertFalse(MODULE._codex_informational_report({**entry, **change}))

    def test_codex_summary_rejects_malformed_severity_without_crashing(self) -> None:
        """Malformed metadata remains a concern rather than raising or clearing."""
        head = "983e9e55b0b29fc19186e3a7a86cd9a0514e7324"
        body = (MODULE_PATH.parent / "tests/fixtures/codex-summary.txt").read_text()
        for severity in ([], {}, None, 0, False, "P4"):
            changed = body.replace('"blockingSeverityThreshold":"P0"',
                                   '"blockingSeverityThreshold":' + json.dumps(severity))
            entry = {"user": {"login": "chatgpt-codex-connector[bot]"},
                     "state": "COMMENTED", "body": changed}
            with self.subTest(severity=severity):
                self.assertFalse(MODULE._codex_informational_report(entry))
                self.assertFalse(MODULE._bot_review_is_acceptable(entry, head))
                self.assertEqual(MODULE.outstanding_bot_concerns([], [], [entry], head), ["Codex"])

    def test_stale_informational_reports_are_neutral_not_clearance(self) -> None:
        old = "983e9e55b0b29fc19186e3a7a86cd9a0514e7324"
        head = "a" * 40
        reports = []
        for filename in ("codex-summary.txt", "codex-security.txt"):
            body = (MODULE_PATH.parent / "tests" / "fixtures" / filename).read_text()
            report = {"user": {"login": "chatgpt-codex-connector[bot]"},
                      "body": body, "state": "COMMENTED", "commit_id": old,
                      "created_at": "2026-10-07T16:00:00Z"}
            reports.append(report)
            self.assertTrue(MODULE._codex_informational_report(report))
            self.assertFalse(MODULE._bot_review_is_acceptable(report, head))
        clear = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED",
                 "commit_id": head, "body": f"No findings for {head}"}
        concern = {"user": {"login": "chatgpt-codex-connector[bot]"},
                   "body": "An unsafe write discards user changes", "commit_id": old,
                   "state": "COMMENTED", "submitted_at": "2026-10-07T15:00:00Z"}
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=(reports, None)),
              patch.object(MODULE, "review_requirement", return_value={
                  "risk_tier": "ordinary", "required_bot_review_count": 1})):
            pr = {"number": 7, "reviews": [clear]}
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")
            self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": []}, head)["status"], "pass")
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": [concern, clear]}, head)["status"], "fail")

    @staticmethod
    def codex_code_report(head: str) -> str:
        return ("Codex Review: Didn't find any major issues. Already looking forward to the next diff.\n\n"
                 f"**Reviewed commit:** `{head[:10]}`\n\n"
                 "<details> <summary>ℹ️ About Codex in GitHub</summary>\n<br/>\n\n"
                 "[Your team has set up Codex to review pull requests in this repo](https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you\n"
                 '- Open a pull request for review\n- Mark a draft as ready\n- Comment "@codex review".\n\n'
                 "If Codex has suggestions, it will comment; otherwise it will react with 👍.\n\n"
                 'Codex can also answer questions or update the PR. Try commenting "@codex address that feedback".\n\n</details>\n')

    def test_codex_no_findings_report_rejects_unsupported_sha256_prefix_lengths(self) -> None:
        head = "a" * 64
        report = self.codex_code_report(head)
        for length in (7, 40, 64):
            with self.subTest(length=length):
                self.assertTrue(
                    MODULE._codex_no_findings_report(
                        report.replace(f"`{head[:10]}`", f"`{head[:length]}`"), head
                    )
                )
        for length in (6, 41, 63):
            with self.subTest(length=length):
                self.assertFalse(
                    MODULE._codex_no_findings_report(
                        report.replace(f"`{head[:10]}`", f"`{head[:length]}`"), head
                    )
                )

    @staticmethod
    def codex_view_task_footer() -> str:
        return " [View task →](https://chatgpt.com/s/cd_6aca5edf907081919b30c475d2f2215e)"

    def test_codex_no_findings_reply_accepts_known_footer_decoration(self) -> None:
        head = "2daf4e3cd7aa75492557e6df67503171f6c048b9"
        statement = f"No findings for {head}."
        about = (
            "<details> <summary>ℹ️ About Codex in GitHub</summary>\n<br/>\n\n"
            "[Your team has set up Codex to review pull requests in this repo]"
            "(https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you\n"
            '- Open a pull request for review\n- Mark a draft as ready\n- Comment "@codex review".\n\n'
            "If Codex has suggestions, it will comment; otherwise it will react with 👍.\n\n"
            'Codex can also answer questions or update the PR. Try commenting '
            '"@codex address that feedback".\n\n</details>\n'
        )
        view_task = self.codex_view_task_footer()
        accepted = (
            statement,
            f"{statement}\n\n{view_task}",
            f"{statement}\n\n{about}",
            f"{statement}\n\n{view_task}\n\n{about}",
        )
        for body in accepted:
            entry = {"user": {"login": "chatgpt-codex-connector[bot]"},
                     "state": "COMMENTED", "body": body}
            with self.subTest(body=body):
                self.assertTrue(MODULE._codex_no_findings_reply(body, head))
                self.assertTrue(MODULE._codex_positive_clearance(body, head))
                self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
                self.assertEqual(
                    MODULE.outstanding_bot_concerns([], [], [entry], head), [])
                self.assertIn(
                    "chatgpt-codex-connector",
                    MODULE.current_head_bot_issue_comments([entry], head),
                )

    def test_codex_no_findings_reply_rejects_extra_text_wrong_sha_and_other_authors(self) -> None:
        head = "2daf4e3cd7aa75492557e6df67503171f6c048b9"
        statement = f"No findings for {head}."
        view_task = self.codex_view_task_footer()
        body = f"{statement}\n\n{view_task}"
        entry = {"user": {"login": "chatgpt-codex-connector[bot]"},
                 "state": "COMMENTED", "body": body}
        rejected = (
            f"{statement}\n\nFinding: unsafe write\n\n{view_task}",
            f"{statement}\n\n{view_task}\n\nFinding: unsafe write",
            f"Looks good.\n\n{statement}\n\n{view_task}",
            f"No findings for {head[:7]}.\n\n{view_task}",
            f"No findings for {'b' * 40}.\n\n{view_task}",
            f"No findings for {head}\n\n{view_task}",
            f"{statement}\n\n [View task →](https://example.com/s/cd_6aca5edf907081919b30c475d2f2215e)",
            f"{statement}\n\n [View task ->](https://chatgpt.com/s/cd_6aca5edf907081919b30c475d2f2215e)",
        )
        for changed in rejected:
            with self.subTest(changed=changed):
                self.assertFalse(MODULE._codex_no_findings_reply(changed, head))
                self.assertFalse(MODULE._bot_review_is_acceptable(
                    {**entry, "body": changed}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**entry, "user": {"login": "coderabbitai[bot]"}}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**entry, "user": {"login": "untrusted-commenter"}}, head))
        self.assertEqual(
            MODULE.outstanding_bot_concerns([], [], [entry], head), [])
        self.assertEqual(
            MODULE.outstanding_bot_concerns(
                [], [], [{**entry, "body": f"{statement}\n\nextra prose"}], head),
            ["Codex"],
        )

    def test_codex_receipt_marker_preserves_identity_head_and_complete_layout(self) -> None:
        head = "a" * 40
        marker = "<!-- codex-review-receipt:v1 -->\n\n"
        for report in (self.codex_code_report(head), f"No findings for {head}."):
            entry = {"state": "COMMENTED", "user": {"login": "chatgpt-codex-connector[bot]"}, "body": marker + report}
            self.assertTrue(MODULE._bot_review_is_acceptable(entry, head))
            self.assertFalse(MODULE._bot_review_is_acceptable(entry, "b" * 40))
            self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "user": {"login": "coderabbitai[bot]"}}, head))
            self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "state": "CHANGES_REQUESTED"}, head))
            for body in (marker + marker + report, marker.replace("v1", "v2") + report,
                         "Quoted " + marker + report, marker + report + "\nFinding remains",
                         marker + "Inspection failed\n" + report):
                self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "body": body}, head))
        security = (MODULE_PATH.parent / "tests" / "fixtures" / "codex-security.txt").read_text()
        entry = {"user": {"login": "chatgpt-codex-connector[bot]"}, "body": marker + security}
        self.assertTrue(MODULE._codex_informational_report(entry))
        self.assertFalse(MODULE._bot_review_is_acceptable({**entry, "state": "COMMENTED"}, head))
        self.assertFalse(MODULE._codex_informational_report({**entry, "body": marker + security + "\nFinding remains"}))

    def test_native_bot_clearance_formats_are_identity_and_head_bound(self) -> None:
        head = "a" * 40
        codex = self.codex_code_report(head)
        rabbit = ("<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                  "<details>\n<summary>🧩 Analysis chain</summary>\n\n"
                  "Inspected exact candidate.\n\n</details>\n\n"
                  f"`@jscraik` No actionable findings for head {head}.\n\n"
                  "_You are interacting with an AI system._")
        separate = rabbit.replace("`@jscraik` No", "`@jscraik`\n\nNo")
        for login, body in (("chatgpt-codex-connector", codex),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", "Keep them coming!")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", "More of your lovely PRs please.")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", "Chef's kiss.")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", "You're on a roll.")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", ":tada:")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", "Delightful!")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", "Swish!")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", "Hooray!")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", ":rocket:")),
                            ("chatgpt-codex-connector", codex.replace("Already looking forward to the next diff.", ":+1:")),
                            ("coderabbitai", rabbit),
                            ("coderabbitai", separate)):
            review = {"state": "COMMENTED", "user": {"login": login + "[bot]"}, "body": body}
            with self.subTest(login=login, body=body):
                self.assertTrue(MODULE._bot_review_is_acceptable(review, head))
                self.assertIn(login, MODULE.current_head_bot_issue_comments([review], head))
                with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
                      patch.object(MODULE, "review_comments", return_value=([], None)),
                      patch.object(MODULE, "issue_comments", return_value=([review], None)),
                      patch.object(MODULE, "review_requirement", return_value={"required_bot_review_count": 1})):
                    self.assertEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": [{**review, "commit_id": head}] if login == "coderabbitai" else []}, head)["status"], "pass")
                self.assertFalse(MODULE._bot_review_is_acceptable(review, "b" * 40))
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, "state": "CHANGES_REQUESTED"}, head))
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, "user": {"login": "untrusted"}}, head))
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": body + "\nReview failed"}, head))
                if login == "chatgpt-codex-connector":
                    for changed in (
                        body.replace("Didn't find any major issues", "Found a major issue"),
                        body.replace("**Reviewed commit:**", "**Candidate commit:**"),
                        body.replace("</details>", ""),
                        body.replace("otherwise it will react with 👍.", "findings remain."),
                        body.replace("Codex Review:", "Quoted Codex Review:"),
                        body.replace("Didn't find any major issues. ", "Didn't find any major issues. Unknown variant "),
                    ):
                        self.assertFalse(MODULE._bot_review_is_acceptable(
                            {**review, "body": changed}, head))
        for hostile in (codex.replace("Didn't find any major issues", "Found a major issue"),
                        codex.replace("</details>", "</details>\nNo findings for " + head),
                        rabbit.replace("`@jscraik`", "`@jscraik` findings remain"),
                        rabbit.replace("`@jscraik`", "[mention](https://example.com)")):
            login = "coderabbitai" if hostile.startswith("<!--") else "chatgpt-codex-connector"
            self.assertFalse(MODULE._bot_review_is_acceptable(
                {"state": "COMMENTED", "user": {"login": login}, "body": hostile}, head))

    def test_historical_codex_code_reports_neither_clear_nor_raise_findings(self) -> None:
        old, head = "a" * 40, "b" * 40
        body = self.codex_code_report(old)
        clear = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED",
                 "commit_id": head, "body": f"No findings for {head}"}
        concern = {"user": {"login": "chatgpt-codex-connector[bot]"},
                   "body": "An unsafe write discards user changes", "commit_id": old,
                   "state": "COMMENTED", "submitted_at": "2026-10-07T15:00:00Z"}
        for variant in (
            body,
            body.replace("Already looking forward to the next diff.", "Keep them coming!"),
            body.replace("Already looking forward to the next diff.", "More of your lovely PRs please."),
            body.replace("Already looking forward to the next diff.", "Chef's kiss."),
            body.replace("Already looking forward to the next diff.", "You're on a roll."),
            body.replace("Already looking forward to the next diff.", "Hooray!"),
        ):
            report = {"user": {"login": "chatgpt-codex-connector[bot]"},
                      "body": variant, "created_at": "2026-10-07T16:00:00Z"}
            self.assertEqual(MODULE.current_head_bot_issue_comments([report], head), {})
            self.assertFalse(MODULE._bot_review_is_acceptable({**report, "state": "COMMENTED"}, head))
            with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
                  patch.object(MODULE, "review_comments", return_value=([], None)),
                  patch.object(MODULE, "issue_comments", return_value=([report], None)),
                  patch.object(MODULE, "review_requirement", return_value={
                      "risk_tier": "ordinary", "required_bot_review_count": 1})):
                self.assertEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": [clear]}, head)["status"], "pass")
                self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": []}, head)["status"], "pass")
                self.assertEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": [concern, clear]}, head)["status"], "fail")
            for malformed in (variant + "\nFinding remains", variant.replace("</details>", "Review failed</details>")):
                self.assertEqual(MODULE.outstanding_bot_concerns([], [], [{**report, "body": malformed}], head), ["Codex"])
            self.assertEqual(MODULE.outstanding_bot_concerns([], [], [{**report, "user": {"login": "untrusted"}}], head), [])

    def test_reply_parser_requires_authenticated_author_before_launch(self) -> None:
        head = "a" * 40
        body = "<!-- This is an auto-generated reply by CodeRabbit -->\nNo findings for " + head
        for collector in (MODULE.current_head_bot_reviews, MODULE.current_head_bot_issue_comments):
            for login in ("untrusted-commenter", "chatgpt-codex-connector[bot]", "coderabbitai[bot]"):
                entries = [{"user": {"login": login}, "commit_id": head,
                            "body": body + str(index), "state": "COMMENTED"} for index in range(3)]
                with self.subTest(collector=collector.__name__, login=login), patch.object(
                    MODULE, "_reply_statement_in_pinned_runtime", return_value=""
                ) as parser:
                    collector(entries, head)
                    if login == "coderabbitai[bot]":
                        self.assertGreater(parser.call_count, 0)
                    else:
                        parser.assert_not_called()

    def test_parser_timeout_stops_descendant_work(self) -> None:
        """A timed-out wrapper cannot leave its child writing after return."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started, escaped = root / "started", root / "escaped"
            child = (f"from pathlib import Path; import time; Path({str(started)!r}).touch(); "
                     f"time.sleep(2); Path({str(escaped)!r}).touch()")
            wrapper = root / "codex-validation-python-uv.sh"
            wrapper.write_text(f"#!/bin/bash\n{shlex.quote(sys.executable)} -c {shlex.quote(child)} &\nwait\n", encoding="utf-8")
            popen = subprocess.Popen

            def started_wrapper(*args, **kwargs):
                process = popen(*args, **kwargs)
                # Exercise descendant termination, independent of OS startup
                # latency. Keep the real process group and timeout unchanged.
                deadline = time.monotonic() + 5
                while not started.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                return process

            with (patch.object(MODULE, "__file__", str(root / "pr-readiness.py")),
                  patch.object(MODULE, "REPLY_TIMEOUT", 1),
                  patch.object(MODULE.subprocess, "Popen", side_effect=started_wrapper)):
                self.assertEqual(MODULE._reply_statement_in_pinned_runtime("timeout fixture"), "")
            self.assertTrue(started.exists(), "fixture child must actually start")
            time.sleep(2)
            self.assertFalse(escaped.exists(), "parser timeout left a descendant running")

    def setUp(self) -> None:
        """Keep per-invocation parser caches independent between tests."""
        MODULE._reply_statement_in_pinned_runtime.cache_clear()

    def test_parser_ignores_repository_modules_and_reuses_unique_body(self) -> None:
        """Repository imports cannot run; repeated bodies share one isolated parse."""
        head = "a" * 40
        body = ("<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                "<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n"
                f"No findings for {head}.\n\n_You are interacting with an AI system._")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            malicious = f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('repository import')\n"
            (root / "markdown_it.py").write_text(malicious, encoding="utf-8")
            (root / "sitecustomize.py").write_text(malicious, encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                with (patch.dict(os.environ, {"PYTHONPATH": directory}),
                      patch.object(MODULE.subprocess, "Popen", wraps=subprocess.Popen) as run):
                    self.assertEqual(MODULE._coderabbit_reply_statement(body), f"No findings for {head}.")
                    self.assertEqual(MODULE._coderabbit_reply_statement(body), f"No findings for {head}.")
                    self.assertEqual(run.call_count, 1)
                self.assertFalse(marker.exists())
            finally:
                os.chdir(previous)

    def test_pinned_parser_failure_and_output_contract_fail_closed(self) -> None:
        """Failed or malformed child output cannot become a clearance statement."""
        statement = f"No findings for {'a' * 40}"
        for raw, code, expected in (
            (json.dumps(statement), 0, statement), (json.dumps(statement), 1, ""),
            ("partial", 0, ""), ("[]", 0, ""), ("true", 0, ""), ("{}", 0, ""),
        ):
            MODULE._reply_statement_in_pinned_runtime.cache_clear()
            with self.subTest(raw=raw, code=code), patch.object(MODULE.subprocess, "Popen") as run:
                process = run.return_value.__enter__.return_value
                process.communicate.return_value = (raw, "")
                process.returncode = code
                self.assertEqual(MODULE._reply_statement_in_pinned_runtime("fixture body"), expected)
                self.assertEqual(MODULE._reply_statement_in_pinned_runtime("fixture body"), expected)
                self.assertEqual(run.call_count, 1)
                process.communicate.assert_called_once_with("fixture body", timeout=30)
                self.assertEqual(run.call_args.kwargs["env"]["UV_OFFLINE"], "1")
                self.assertTrue(run.call_args.kwargs["start_new_session"])
                self.assertNotIn("fixture body", run.call_args.args[0])
        for error in (OSError("fixture missing"), subprocess.TimeoutExpired("fixture", 30)):
            MODULE._reply_statement_in_pinned_runtime.cache_clear()
            with patch.object(MODULE.subprocess, "Popen", side_effect=error):
                self.assertEqual(MODULE._reply_statement_in_pinned_runtime("fixture body"), "")

    def test_native_python_uses_only_available_pinned_parser_resources(self) -> None:
        """The native entrypoint rejects absent parser resources and recovers offline."""
        head = "a" * 40
        body = ("<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                "<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n"
                f"No findings for {head}.\n\n_You are interacting with an AI system._")
        review = {"state": "COMMENTED", "user": {"login": "coderabbitai[bot]"}, "body": body}
        child = (
            "import importlib.util,json,sys; "
            "spec=importlib.util.spec_from_file_location('readiness',sys.argv[1]); "
            "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "print(module._bot_review_is_acceptable(json.load(sys.stdin),sys.argv[2]))"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "repository-import-executed"
            malicious = f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('untrusted import')\n"
            (root / "markdown_it.py").write_text(malicious, encoding="utf-8")
            (root / "sitecustomize.py").write_text(malicious, encoding="utf-8")
            runtime = root / "runtime"
            runtime.mkdir()
            isolated_module = runtime / MODULE_PATH.name
            isolated_module.write_bytes(MODULE_PATH.read_bytes())
            # The inactive port's mandatory admission travels with the runtime
            # bundle; isolated imports still cannot use the repository path.
            (runtime / 'migration_scope.py').write_bytes(MODULE_PATH.with_name('migration_scope.py').read_bytes())
            original_launcher = MODULE_PATH.with_name("codex-validation-python-uv.sh")
            launcher_bytes = original_launcher.read_bytes()
            isolated_launcher = runtime / original_launcher.name
            for available in (True, False, True):
                # An empty cache does not prove the selected runtime lacks a parser.
                # Control only this disposable launcher's resource availability.
                isolated_launcher.write_text(
                    f'#!/bin/bash\nexec bash {shlex.quote(str(original_launcher))} "$@"\n'
                    if available else "#!/bin/bash\nexit 69\n"
                )
                env = {**os.environ, "UV_OFFLINE": "1", "PYTHONPATH": directory}
                result = subprocess.run(
                    [sys.executable, "-S", "-c", child, str(isolated_module), head],
                    input=json.dumps(review), text=True, capture_output=True,
                    env=env, cwd=directory, check=False, timeout=45,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), str(available), result.stderr)
                self.assertFalse(marker.exists())
            self.assertEqual(original_launcher.read_bytes(), launcher_bytes)
            self.assertEqual(isolated_module.read_bytes(), MODULE_PATH.read_bytes())

    def test_coderabbit_reply_requires_its_existing_markdown_dependency(self) -> None:
        """Optional decorations work, but unavailable parsing never grants review."""
        original_import = builtins.__import__

        def without_markdown(name, *args, **kwargs):
            if name == "markdown_it":
                raise ModuleNotFoundError("fixture: Markdown parser unavailable")
            return original_import(name, *args, **kwargs)

        for length in (40, 64):
            head = "a" * length
            body = ("<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                    "<details>\n<summary>🧩 Analysis chain</summary>\n\nInspected exact candidate.\n\n</details>\n\n"
                    f"No findings for {head}.\n\n_You are interacting with an AI system._")
            review = {"state": "COMMENTED", "user": {"login": "coderabbitai[bot]"}, "body": body}
            self.assertTrue(MODULE._bot_review_is_acceptable(review, head))
            with (patch("builtins.__import__", side_effect=without_markdown),
                  patch.object(MODULE, "_reply_statement_in_pinned_runtime", return_value="")):
                self.assertFalse(MODULE._bot_review_is_acceptable(review, head))
                self.assertTrue(MODULE._bot_review_is_acceptable(
                    {**review, "commit_id": head, "body": f"No findings for {head}"}, head))

    def test_coderabbit_reply_requires_analysis_evidence(self) -> None:
        """A positive outer verdict cannot replace the required analysis disclosure."""
        head = "a" * 40
        prefix = "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
        footer = f"No findings for {head}.\n\n_You are interacting with an AI system._"
        analysis_prefix = "<details>\n<summary>🧩 Analysis chain</summary>\n\n"
        analysis_suffix = "\n\n</details>\n\n"
        valid_review = {"state": "COMMENTED", "user": {"login": "coderabbitai[bot]"}}
        invalid_bodies = {
            "missing analysis": prefix + footer,
            "empty analysis": prefix + analysis_prefix + analysis_suffix + footer,
            "marker only": prefix + analysis_prefix + "🏁 Script executed:" + analysis_suffix + footer,
            "output metadata only": prefix + analysis_prefix + "Length of output: 12" + analysis_suffix + footer,
        }
        for label, body in invalid_bodies.items():
            with self.subTest(disclosure=label):
                self.assertFalse(MODULE._bot_review_is_acceptable({**valid_review, "body": body}, head))

        permitted = (
            "Inspected exact candidate.",
            "Rate limit exceeded errors are retried",
            "🏁 Script executed:\n\n```shell\nprintf '</details>'\n```",
        )
        for content in permitted:
            body = prefix + analysis_prefix + content + analysis_suffix + footer
            with self.subTest(permitted=content):
                self.assertTrue(MODULE._bot_review_is_acceptable({**valid_review, "body": body}, head))

    def test_coderabbit_command_trace_rejects_additional_blank_lines(self) -> None:
        head = "a" * 40
        prefix = "<!-- This is an auto-generated reply by CodeRabbit -->\n\n<details>\n<summary>🧩 Analysis chain</summary>\n\n🏁 Script executed:\n\n```shell\n"
        suffix = f"```\n\n</details>\n\nNo findings for {head}.\n\n_You are interacting with an AI system._"
        for command in ("printf '</details>'", "gh api repos/jscraik/configs/issues/comments/123"):
            review = {"state": "COMMENTED", "user": {"login": "coderabbitai[bot]"}, "body": prefix + command + "\n" + suffix}
            self.assertTrue(MODULE._bot_review_is_acceptable(review, head))
            for trace in (command + "\n\n", "\n" + command + "\n", command + "\n \n", command + "\n# diagnostic\n"):
                with self.subTest(command=command, trace=trace):
                    self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": prefix + trace + suffix}, head))

    def test_coderabbit_reply_wrapper_preserves_review_boundaries(self) -> None:
        """Only the authenticated reply's outer verdict can clear its findings."""
        head = "a" * 40
        base, prior = "b" * 40, "c" * 40
        body = (
            "<!-- This is an auto-generated reply by CodeRabbit -->\n"
            "> [!TIP]\n> For best results, initiate chat on the files or code changes.\n\n"
            "<details>\n<summary>🧩 Analysis chain</summary>\n\n"
            "🏁 Script executed:\n\n```shell\nprintf '</details>'\n```\n\n"
            "Length of output: 10\n\n---\n\n</details>\n\n"
            f"No findings for {head}.\n\n_You are interacting with an AI system._"
        )
        review = {"state": "COMMENTED", "user": {"login": "coderabbitai[bot]"}, "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(review, head))
        clarification = (
            "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
            "`@jscraik` Independent static inspection completed, as reported in "
            "[the referenced comment](https://github.com/jscraik/configs/pull/335#issuecomment-6110922084). "
            "No actionable findings remained from that inspection.\n\n"
            f"No findings for {head}.\n\n"
            f"The completed inspection covered all 21 changed files against base `{base}`, "
            f"including repairs since `{prior}`. `git diff --check` passed. GitHub reported the "
            "requested head and base at the end of inspection.\n\n"
            "**Evidence limits:** I did not execute repository code or tests. The verdict does not "
            "establish hosted-check success, runtime correctness, or merge readiness.\n\n"
            "This reply clarifies the prior evidence. I did not repeat inspection, enable paid services, "
            "change source, approve, merge, or resolve threads.\n\n"
            "_You are interacting with an AI system._"
        )
        self.assertTrue(MODULE._bot_review_is_acceptable({**review, "body": clarification}, head))
        used = (
            "\n\n---\n\n<details>\n<summary>🧠 Learnings used</summary>\n\n"
            "```\nLearnt from: jscraik\nURL: https://github.com/jscraik/configs/pull/333\n\n"
            "Timestamp: 2026-10-10T23:01:39.207Z\nLearning: Preserve the exact-head gate.\n```\n\n</details>"
        )
        decorated = clarification.replace("\n\n_You are interacting with an AI system._", "\n\n_You are interacting with an AI system._" + used)
        self.assertTrue(MODULE._bot_review_is_acceptable({**review, "body": decorated}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**review, "body": decorated.replace("🧠 Learnings used", "Unknown appendix")}, head))
        added = (
            "\n\n---\n\n<details>\n<summary>✏️ Learnings added</summary>\n\n"
            "```\nLearnt from: jscraik\nURL: https://github.com/jscraik/configs/pull/333\n\n"
            "Timestamp: 2026-10-10T23:01:39.207Z\nLearning: Preserve the exact-head gate.\n```\n\n"
            "> Note: Learnings are effective only in the context of similar code segments. To apply general coding guidelines, please configure [review instructions](https://docs.coderabbit.ai/guides/review-instructions). You can manage existing learnings in the [app](https://app.coderabbit.ai/learnings).\n\n</details>"
        )
        both = decorated.replace(used, added + used)
        self.assertTrue(MODULE._bot_review_is_acceptable({**review, "body": both}, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**review, "body": both.replace(added + used, used + added)}, head))
        pr = {"url": "https://github.com/jscraik/configs/pull/335", "baseRefOid": base}
        source = {
            **review,
            "body": (
                "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                f"No findings for {head}.\n\n"
                f"I completed independent static inspection of all 21 changed files against base `{base}`. "
                f"I also inspected the repairs since `{prior}`.\n\n"
                "The inspection covered duplication detection, reserved-definition counts, baseline handling, "
                "fixture isolation, validation wiring, inspection receipts, authenticated request reuse, and "
                "Codex completion evidence. `git diff --check` passed. GitHub still reported the requested "
                "head and base after inspection.\n\n"
                "**Inspection limits:** I did not execute repository code or tests. This verdict does not "
                "establish hosted-check success, runtime correctness, or merge readiness.\n\n"
                "I used read-only inspection. I did not enable paid services, change source, approve, merge, "
                "or resolve threads.\n\n_You are interacting with an AI system._"
            ),
            "html_url": pr["url"] + "#issuecomment-6110922084",
        }
        decorated_source = {**source, "body": source["body"] + added + used}
        self.assertTrue(MODULE._bot_review_is_acceptable(decorated_source, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(
            {**decorated_source, "body": decorated_source["body"].replace(
                "Learning: Preserve the exact-head gate.", "Learning: Added finding\nFinding remains")}, head))
        candidate = {**review, "body": clarification}
        with (patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 0)),
              patch.object(MODULE, "changed_file_records", return_value=[{}] * 21)):
            self.assertTrue(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, candidate, [source]))
            for altered_pr, altered_reply, sources in (
                ({**pr, "baseRefOid": "d" * 40}, candidate, [source]),
                ({**pr, "url": "https://github.com/other/repo/pull/335"}, candidate, [source]),
                (pr, candidate, []),
                (pr, candidate, [{**source, "user": {"login": "pr-author"}}]),
                (pr, candidate, [{**source, "body": source["body"].replace(head, "d" * 40)}]),
                (pr, {**candidate, "body": clarification.replace(head, head[:8])}, [source]),
                (pr, {**candidate, "body": clarification.replace("all 21", "all 1")}, [source]),
                (pr, candidate, [{**source, "body": source["body"].replace("all 21", "all 1")}]),
            ):
                with self.subTest(context=(altered_pr, altered_reply, sources)):
                    self.assertFalse(MODULE._inspection_provenance_matches(
                        Path.cwd(), altered_pr, head, altered_reply, sources))
        with patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 1)):
            self.assertFalse(MODULE._inspection_provenance_matches(Path.cwd(), pr, head, candidate, [source]))
        codex = {"state": "COMMENTED", "user": {"login": "chatgpt-codex-connector"},
                 "commit_id": head, "body": f"No findings for {head}",
                 "submitted_at": "2026-10-11T10:00:00Z"}
        source["created_at"] = "2026-10-11T10:00:00Z"
        candidate["created_at"] = "2026-10-11T11:00:00Z"
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=([source, candidate], None)),
              patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 0)),
              patch.object(MODULE, "changed_file_records", return_value=[{}] * 21),
              patch.object(MODULE, "review_requirement", return_value={
                  "risk_tier": "ordinary", "required_bot_review_count": 1})):
            current_pr = {**pr, "number": 335, "reviews": [codex, {**candidate, "commit_id": head}]}
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), current_pr, head)["status"], "fail")
            formal = {**candidate, "commit_id": head, "body": f"No findings for {head}."}
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), {**current_pr, "reviews": [codex, formal]}, head)["status"], "pass")
            # Other sufficient reviewer evidence must not conceal wrong provenance.
            self.assertEqual(MODULE.reviews_lane(
                Path.cwd(), {**current_pr, "baseRefOid": "d" * 40}, head)["status"], "fail")
        for unsafe in (
            clarification.replace(head, "d" * 40),
            clarification.replace("`git diff --check` passed", "`git diff --check` failed"),
            clarification.replace("No actionable findings remained", "Actionable findings remained"),
            clarification.replace("https://github.com/", "https://untrusted.example/"),
            clarification + "\n\nFix the unsafe write.",
        ):
            with self.subTest(clarification=unsafe):
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": unsafe}, head))
        ordinary = body.replace("Length of output: 10", "The implementation enforces the rate limit.")
        self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": ordinary}, head))
        analysis_provenance = body.replace(
            "Length of output: 10", f"against base `{base}`\n\nrepairs since `{prior}`")
        with patch.object(MODULE, "run_command") as git_probe:
            self.assertFalse(MODULE._bot_review_is_acceptable({**review, "body": analysis_provenance}, head))
            git_probe.assert_not_called()
        self.assertTrue(MODULE._bot_review_has_blocked_response(ordinary, login="coderabbitai"))
        for analysis in (
            "Rate limit exceeded errors are retried",
            "The message `review failed` is returned by this code.",
            '```python\nraise RuntimeError("review failed")\n```',
            '```text\nreview failed\n```',
            'Reviewed code:\n\n```python\nprint("Rate limit exceeded")\n```',
            "Tool output:\n\n```text\nAll tests passed\n```",
            "HTTP 401 Unauthorized: token expired is an example error message.",
            'Reviewed code:\n\n```text\nHTTP 401 Unauthorized: token expired\n```',
            "Tool output:\n\n```stderr\nHTTP 401 Unauthorized errors are retried\n```",
            "The retry guidance says:\nReview failed\nwhen an example request is exhausted.",
            "The retry guidance says:  \nReview failed  \nwhen an example request is exhausted.",
            "Review failed\nmeans that the example exhausted its retries.",
        ):
            with self.subTest(ordinary_analysis=analysis):
                # Context is not an executed service failure, but unrecognised
                # analysis still cannot supply clearance through any layout.
                self.assertEqual(MODULE._bot_review_is_acceptable(
                    {**review, "body": body.replace("Length of output: 10", analysis)}, head),
                    analysis == "Rate limit exceeded errors are retried")
        for change in (
            {"user": {"login": "pr-author"}},
            {"user": {"login": "chatgpt-codex-connector[bot]"}},
            {"state": "CHANGES_REQUESTED"},
            {"body": body.replace(head, "b" * 40)},
            {"body": body.replace(f"No findings for {head}.", f"> No findings for {head}.")},
            {"body": body.replace(f"No findings for {head}.", f"```\nNo findings for {head}.\n```")},
            {"body": body + "\n\nAn unsafe write remains."},
            {"body": body.replace("Length of output: 10", "An actionable source defect remains.")},
            {"body": body.replace("Length of output: 10", "Source inspection has not reached all changed files.")},
            {"body": body.replace("Length of output: 10", "review failed: quota exceeded")},
            {"body": body.replace("Length of output: 10", "review **failed**: quota **exceeded**")},
            {"body": body.replace("Length of output: 10", "Rate limit exceeded. Try again later.")},
            {"body": body.replace("Length of output: 10", "Error: Rate limit exceeded. Try again later.")},
            {"body": body.replace("Length of output: 10", "Review unavailable: rate limit exceeded.")},
            {"body": body.replace("Length of output: 10", "- Rate limit exceeded.")},
            {"body": body.replace("Length of output: 10", "> Review failed.")},
            {"body": body.replace("Length of output: 10", "HTTP 401 Unauthorized")},
            {"body": body.replace("Length of output: 10", "HTTP 403 Forbidden")},
            {"body": body.replace("Length of output: 10", "Review failed.\nPlease retry the request.")},
            {"body": body.replace("Length of output: 10", "Review failed.  \nPlease retry the request.")},
            {"body": body.replace("Length of output: 10", "Output:\n\n```stderr\nHTTP 401 Unauthorized: token expired\n```")},
            {"body": body.replace("Length of output: 10", "```stderr\nHTTP 403 Forbidden: access denied\n```")},
            {"body": body.replace("Length of output: 10", "Tool output:\n\n    Review failed: provider unavailable")},
            {"body": body.replace("Length of output: 10", "```output\nError: Rate limit exceeded: retry after 60 seconds\n```")},
            {"body": body.replace("Length of output: 10", "Tool output:\n\n```text\nRate limit exceeded\n```")},
            {"body": body.replace("Length of output: 10", "Output:\n\n```text\nreview failed\n```")},
            {"body": body.replace("Length of output: 10", "Length of output: 55\n\n```text\nLog output\nError: Rate limit exceeded\n```")},
            {"body": body.replace("Length of output: 10", "```output\nreview failed\n```")},
            {"body": body.replace("\n</details>\n", "\n")},
            {"body": body.replace("Analysis chain", "Outstanding findings")},
            {"body": body.replace("\n</details>\n", "\n<div>hidden</div>\n</details>\n")},
        ):
            with self.subTest(change=change):
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, **change}, head))

        finding = {**review, "commit_id": "b" * 40, "body": "Fix the unsafe write",
                   "submitted_at": "2026-09-14T10:00:00Z"}
        reply = {**review, "body": body, "created_at": "2026-09-14T11:00:00Z"}
        codex = {"state": "COMMENTED", "user": {"login": "chatgpt-codex-connector"},
                 "commit_id": head, "body": f"No findings for {head}",
                 "submitted_at": "2026-09-14T11:00:00Z"}
        reply.update(commit_id=head, submitted_at=reply["created_at"])
        pr = {"number": 7, "reviews": [finding, codex, reply]}
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=([reply], None)),
              patch.object(MODULE, "review_requirement", return_value={
                  "risk_tier": "high", "required_bot_review_count": 2})):
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")
            reply["body"] = ordinary
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "fail")
            reply["body"] = body
            pr["reviews"] = [finding, reply]
            self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")
            pr["reviews"] = [finding, codex, reply]
            reply["submitted_at"] = "2026-09-14T09:00:00Z"
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "fail")

    def test_coderabbit_inspection_disclosure_is_not_arbitrary_verdict_prose(self) -> None:
        head, base, prior = "a" * 40, "b" * 40, "c" * 40
        body = (
            "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
            f"No findings for {head}.\n\n"
            f"I completed independent static inspection of all 21 changed files against base `{base}`. "
            f"I also inspected the repairs since `{prior}`.\n\n"
            "The inspection covered duplication detection, reserved-definition counts, baseline handling, "
            "fixture isolation, validation wiring, inspection receipts, authenticated request reuse, and "
            "Codex completion evidence. `git diff --check` passed. GitHub still reported the requested "
            "head and base after inspection.\n\n"
            "**Inspection limits:** I did not execute repository code or tests. This verdict does not "
            "establish hosted-check success, runtime correctness, or merge readiness.\n\n"
            "I used read-only inspection. I did not enable paid services, change source, approve, merge, "
            "or resolve threads.\n\n_You are interacting with an AI system._"
        )
        review = {"state": "COMMENTED", "user": {"login": "coderabbitai[bot]"}, "body": body}
        self.assertTrue(MODULE._bot_review_is_acceptable(review, head))
        for trace_base, trace_head, accepted in ((base, head, True), (prior, head, False), (base, prior, False), (base, head[:7] + "d" * 33, False)):
            analysis = ("<details>\n<summary>🧩 Analysis chain</summary>\n\n🏁 Script executed:\n\n```shell\n"
                        f"git diff {trace_base} {trace_head} --stat\n```\n\n</details>\n\n")
            decorated = body.replace("-->\n\n", "-->\n\n" + analysis, 1)
            for verdict, full in ((f"No findings for {head}.", True), (f"No actionable findings for {head}.", True),
                                  (f"No comments were generated for head `{head}`.", True),
                                  (f"No actionable findings for {head[:7]}.", False),
                                  (f"No findings for {head[:-1]}.", False)):
                with self.subTest(trace=(trace_base, trace_head), verdict=verdict):
                    variant = decorated.replace(f"No findings for {head}.", verdict)
                    self.assertEqual(MODULE._bot_review_is_acceptable({**review, "body": variant}, head), accepted and full)
        for change in (
            {"user": {"login": "pr-author"}},
            {"body": body.replace(head, "d" * 40)},
            {"body": body.replace(f"No findings for {head}.", f"> No findings for {head}.")},
            {"body": body.replace("independent static inspection", "incomplete static inspection")},
            {"body": body.replace("`git diff --check` passed", "`git diff --check` failed")},
            {"body": body.replace("I did not execute", "I did execute")},
            {"body": body.replace("duplication detection", "duplication detection; an unsafe write remains")},
            {"body": body + "\n\nAn unsafe write remains."},
            {"body": body.replace("I used read-only inspection.", f"No findings for {'d' * 40}.")},
            {"body": body.replace("**Inspection limits:**", "<div>Inspection limits:</div>")},
        ):
            with self.subTest(change=change):
                self.assertFalse(MODULE._bot_review_is_acceptable({**review, **change}, head))

    def test_untrusted_markers_and_sha256_quota_do_not_block_ordinary_clearance(self) -> None:
        """Ignore untrusted repair markers and quota notices when quorum is met."""
        for length in (40, 64):
            head = "a" * length
            review = {"state": "COMMENTED", "commit_id": head,
                      "user": {"login": "coderabbitai[bot]"}, "body": f"No findings for {head}"}
            comments = [{"user": {"login": "pr-author"}, "body": "pr-repair-endorsement/v1\n{}"},
                        {"user": {"login": "chatgpt-codex-connector[bot]"}, "body": f"quota exceeded for {head}"}]
            with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
                  patch.object(MODULE, "review_comments", return_value=([], None)),
                  patch.object(MODULE, "issue_comments", return_value=(comments, None)),
                  patch.object(MODULE, "review_requirement", return_value={"risk_tier": "ordinary", "required_bot_review_count": 1}),
                  patch.object(MODULE, "repair_endorsement_lane", return_value={"status": "blocked"}) as repair):
                pr = {"number": 7, "reviews": [review], "author": {"login": "pr-author"}}
                self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")
                repair.assert_not_called()
                comments[0]["user"]["login"] = "coderabbitai[bot]"
                self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "blocked")
                repair.assert_called_once()

    def test_review_blocker_diagnostics_do_not_grant_clearance(self) -> None:
        """Classify outstanding evidence without treating diagnostic labels as clearance."""
        head = "a" * 40
        for state, body, source, category in (
            ("COMMENTED", "No actionable comments. Minimal risk.", "review", "unrecognised_verdict_format"),
            ("COMMENTED", "Unsafe write discards user changes", "review", "unrecognised_verdict_format"),
            ("CHANGES_REQUESTED", "", "review", "changes_requested"),
            ("COMMENTED", "Unsafe write discards user changes", "inline", "inline_review_comment"),
        ):
            with self.subTest(state=state, body=body, source=source):
                entry = {"state": state, "commit_id": head,
                         "user": {"login": "coderabbitai[bot]"}, "body": body,
                         "submitted_at": "2026-09-14T10:00:00Z",
                         "created_at": "2026-09-14T10:00:00Z"}
                pr = {"number": 7, "reviews": [entry] if source == "review" else []}
                with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
                      patch.object(MODULE, "review_comments", return_value=([entry] if source == "inline" else [], None)),
                      patch.object(MODULE, "issue_comments", return_value=([], None)),
                      patch.object(MODULE, "review_requirement", return_value={
                          "risk_tier": "ordinary", "required_bot_review_count": 1})):
                    result = MODULE.reviews_lane(Path.cwd(), pr, head)
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["details"]["outstanding_bot_concerns"], ["CodeRabbit"])
                self.assertEqual(result["details"]["review_blocker_categories"], {"CodeRabbit": [category]})
                guidance = result["details"]["next_action"]
                self.assertIn(f"No findings for {head}.", guidance)
                self.assertIn("authorization", guidance)
                self.assertIn("CodeRabbit", guidance)
                self.assertNotIn("ask the same reviewer", guidance)
                if category == "unrecognised_verdict_format":
                    self.assertIn("may contain findings", result["evidence"])
                else:
                    self.assertNotIn("may contain findings", result["evidence"])

    def test_coderabbit_narrative_hint_keeps_the_review_blocked(self) -> None:
        head = "a" * 40
        template = ("<!-- coderabbit-ai-generated:v1 -->\n"
                    "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->\n"
                    f"Review for {head}.\n"
                    "<!-- walkthrough_start -->{content}<!-- walkthrough_end -->")
        entry = {"id": 42, "user": {"login": "coderabbitai[bot]", "type": "Bot", "id": 7},
                 "created_at": "2026-09-14T10:00:00Z", "updated_at": "2026-09-14T10:00:00Z"}
        pr = {"number": 7, "reviews": [], "author": {"login": "author"}}
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "codex_completion_review", return_value=(None, None)),
              patch.object(MODULE, "coderabbit_completion_review", return_value=(None, None)),
              patch.object(MODULE, "review_requirement", return_value={
                  "risk_tier": "ordinary", "required_bot_review_count": 1})):
            for content in ("A summary of the change.", "An unsafe write remains.", ""):
                with self.subTest(content=content), patch.object(
                    MODULE, "issue_comments", return_value=([{**entry, "body": template.format(content=content)}], None)
                ):
                    result = MODULE.reviews_lane(Path.cwd(), pr, head)
                    self.assertEqual(result["status"], "fail")
                    self.assertEqual(result["details"]["outstanding_bot_concerns"], ["CodeRabbit"])
                    categories = result["details"]["review_blocker_categories"]["CodeRabbit"]
                    self.assertIn("unrecognised_verdict_format", categories)
                    self.assertEqual("coderabbit_nonempty_review_sections" in categories, bool(content))

    def test_concern_guidance_includes_reviewers_missing_from_required_high_risk_quorum(self) -> None:
        head = "a" * 40
        concern = {
            "state": "COMMENTED",
            "commit_id": head,
            "user": {"login": "coderabbitai[bot]"},
            "body": "The path can discard unrelated user data.",
            "submitted_at": "2026-09-14T10:00:00Z",
        }
        pr = {"number": 7, "reviews": [concern]}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
            patch.object(MODULE, "review_requirement", return_value={
                "risk_tier": "high", "required_bot_review_count": 2}),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["details"]["outstanding_bot_concerns"], ["CodeRabbit"])
        guidance = result["details"]["next_action"]
        self.assertIn("CodeRabbit", guidance)
        self.assertIn("Codex", guidance)

    def test_clearance_guidance_names_missing_reviewer_without_repeating_cleared_one(self) -> None:
        head = "a" * 40
        coderabbit = {
            "state": "COMMENTED",
            "commit_id": head,
            "user": {"login": "coderabbitai[bot]"},
            "body": f"No findings for {head}",
            "submitted_at": "2026-09-14T10:00:00Z",
        }
        pr = {"number": 7, "reviews": [coderabbit]}
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=([], None)),
              patch.object(MODULE, "review_requirement", return_value={
                  "risk_tier": "high", "required_bot_review_count": 2})):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        guidance = result["details"]["next_action"]
        self.assertIn("Codex", guidance)
        self.assertNotIn("CodeRabbit", guidance)
        self.assertIn(
            "do not repeat a reviewer who already provided current-head clearance unless that reviewer subsequently raised an outstanding concern",
            guidance,
        )

    def test_ordinary_missing_bot_quorum_requests_only_one_reviewer(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviews": []}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
            patch.object(MODULE, "review_requirement", return_value={
                "risk_tier": "ordinary", "required_bot_review_count": 1}),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)

        self.assertEqual(result["status"], "fail")
        guidance = result["details"]["next_action"]
        self.assertIn("CodeRabbit", guidance)
        self.assertNotIn("Codex", guidance)

    def test_missing_reviewer_is_preferred_over_provider_with_quota_failure(self) -> None:
        head = "a" * 40
        unavailable = {
            "state": "COMMENTED",
            "commit_id": head,
            "user": {"login": "coderabbitai[bot]"},
            "body": "Review rate limited.",
        }
        pr = {"number": 7, "reviews": [unavailable]}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
            patch.object(MODULE, "review_requirement", return_value={
                "risk_tier": "ordinary", "required_bot_review_count": 1}),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)

        self.assertEqual(result["status"], "fail")
        guidance = result["details"]["next_action"]
        self.assertIn("Codex", guidance)
        self.assertNotIn("CodeRabbit", guidance)

    def test_reviewers_for_clearance_table_driven(self) -> None:
        cases = (
            ("owner", (["CodeRabbit"], set(), 1, set()), ["CodeRabbit"]),
            ("unseen-first", ([], set(), 1, {"coderabbitai"}), ["Codex"]),
            ("high-risk", ([], {"coderabbitai"}, 2, {"coderabbitai"}), ["Codex"]),
            (
                "concern-plus-shortfall",
                (["CodeRabbit"], set(), 2, {"coderabbitai"}),
                ["CodeRabbit", "Codex"],
            ),
        )

        for name, arguments, expected in cases:
            with self.subTest(case=name):
                self.assertEqual(
                    MODULE.reviewers_for_clearance(*arguments),
                    expected,
                )

    def test_qualifying_bot_with_outstanding_concern_is_still_requested(self) -> None:
        head = "a" * 40
        reviewer = {"login": "coderabbitai[bot]"}
        no_findings = {
            "state": "COMMENTED",
            "commit_id": head,
            "user": reviewer,
            "body": f"No findings for {head}",
            "submitted_at": "2026-09-14T10:00:00Z",
        }
        inline_finding = {
            "commit_id": head,
            "user": reviewer,
            "body": "The reviewer still has an unresolved finding.",
            "created_at": "2026-09-14T10:00:00Z",
        }
        pr = {"number": 7, "reviews": [no_findings]}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
            patch.object(MODULE, "review_comments", return_value=([inline_finding], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
            patch.object(MODULE, "review_requirement", return_value={
                "risk_tier": "high", "required_bot_review_count": 2}),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["details"]["outstanding_bot_concerns"], ["CodeRabbit"])
        guidance = result["details"]["next_action"]
        self.assertIn("CodeRabbit", guidance)
        self.assertIn("Codex", guidance)
        self.assertIn(
            "unless that reviewer subsequently raised an outstanding concern",
            guidance,
        )

    def test_risk_lookup_failure_preserves_known_concern_diagnostic(self) -> None:
        head = "a" * 40
        formal_blocker = {
            "state": "CHANGES_REQUESTED",
            "commit_id": head,
            "user": {"login": "coderabbitai[bot]"},
            "body": "",
            "submitted_at": "2026-09-14T10:00:00Z",
        }
        pr = {"number": 7, "reviews": [formal_blocker]}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
            patch.object(MODULE, "review_requirement", side_effect=ValueError("base unavailable")),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("known bot concerns: CodeRabbit=CHANGES_REQUESTED", result["evidence"])
        self.assertEqual(result["details"]["outstanding_bot_concerns"], ["CodeRabbit"])
        self.assertEqual(
            result["details"]["review_blocker_categories"],
            {"CodeRabbit": ["changes_requested"]},
        )
        self.assertIn("CodeRabbit", result["details"]["next_action"])

    def test_no_findings_comment_does_not_clear_hosted_changes_requested(self) -> None:
        """Keep hosted changes requested blocking until a formal review clears them."""
        head = "a" * 40
        reviewer = {"login": "coderabbitai[bot]"}
        request = {"user": reviewer, "state": "CHANGES_REQUESTED", "commit_id": head,
                   "body": "Fix the unsafe write", "submitted_at": "2026-09-14T10:00:00Z"}
        reply = {"user": reviewer, "body": (
            "<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
            f"@jscraik\n\nNo findings for {head}.\n\n"
            "_You are interacting with an AI system._"),
                 "created_at": "2026-09-14T11:00:00Z"}
        pr = {"number": 7, "reviews": [request], "reviewDecision": "CHANGES_REQUESTED"}
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=([], None)) as comments,
              patch.object(MODULE, "review_requirement", return_value={"risk_tier": "ordinary", "required_bot_review_count": 1})):
            initial = MODULE.reviews_lane(Path.cwd(), pr, head)
            self.assertEqual(initial["status"], "fail")
            guidance = initial["details"]["next_action"]
            self.assertIn("CHANGES_REQUESTED", guidance)
            self.assertIn("formal review", guidance)
            self.assertIn("separately authorized dismissal", guidance)
            comments.return_value = ([reply], None)
            still_blocked = MODULE.reviews_lane(Path.cwd(), pr, head)
            self.assertEqual(still_blocked["status"], "fail")
            self.assertIn("CHANGES_REQUESTED", still_blocked["evidence"])
            guidance = still_blocked["details"]["next_action"]
            self.assertIn("formal review", guidance)
            self.assertIn(f"Review current head {head}", guidance)
            self.assertIn(f"No findings for {head}.", guidance)
            pr["reviews"].append({**request, "state": "APPROVED", "body": reply["body"],
                                  "submitted_at": "2026-09-14T12:00:00Z"})
            pr["reviewDecision"] = "APPROVED"
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")

    def test_review_diagnostics_exclude_cleared_events_and_keep_later_unknown_text(self) -> None:
        """Exclude cleared concerns while retaining subsequent unrecognised prose."""
        head = "a" * 40
        base = {"commit_id": head, "user": {"login": "coderabbitai[bot]"}}
        reviews = [
            {**base, "state": "CHANGES_REQUESTED", "body": "Fix the write",
             "submitted_at": "2026-09-14T10:00:00Z"},
            {**base, "state": "COMMENTED", "body": f"No findings for {head}",
             "submitted_at": "2026-09-14T11:00:00Z"},
        ]
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=([], None)),
              patch.object(MODULE, "review_requirement", return_value={"risk_tier": "ordinary", "required_bot_review_count": 1})):
            pr = {"number": 7, "reviews": reviews}
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")
            reviews.append({**base, "state": "COMMENTED", "body": "Looks good overall",
                            "submitted_at": "2026-09-14T12:00:00Z"})
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["details"]["review_blocker_categories"],
                             {"CodeRabbit": ["unrecognised_verdict_format"]})

    def test_previous_head_finding_blocks_other_bots_ordinary_clearance(self) -> None:
        """Keep earlier findings blocking despite another bot's current-head clearance."""
        head, old = "a" * 40, "b" * 40
        concern = {"state": "COMMENTED", "commit_id": old,
                   "user": {"login": "chatgpt-codex-connector[bot]"},
                   "body": "An unsafe write discards user changes",
                   "submitted_at": "2026-09-11T10:00:00Z"}
        clear = {"state": "COMMENTED", "commit_id": head,
                 "user": {"login": "coderabbitai[bot]"},
                 "body": f"No findings for {head}", "submitted_at": "2026-09-11T11:00:00Z"}
        pr = {"number": 7, "reviews": [concern, clear]}
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=([], None)),
              patch.object(MODULE, "review_requirement", return_value={
                  "risk_tier": "ordinary", "required_bot_review_count": 1})):
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "fail")
            original_body = concern["body"]
            for body, state, sha, expected in (
                ("Looks good!", "COMMENTED", old, "pass"),
                ("LGTM", "COMMENTED", old, "pass"),
                ("Looks good except for the unsafe write", "COMMENTED", old, "fail"),
                ("Looks good!", "CHANGES_REQUESTED", old, "fail"),
                ("Looks good!", "COMMENTED", head, "fail"),
            ):
                with self.subTest(body=body, state=state, sha=sha):
                    concern.update(body=body, state=state, commit_id=sha)
                    self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], expected)
            concern.update(body=original_body, state="COMMENTED", commit_id=old)
            pr["reviews"].append({**clear, "user": concern["user"]})
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")

    def test_standalone_clearance_does_not_misclassify_security_discussion(self) -> None:
        head = "a" * 40
        self.assertTrue(MODULE._bot_review_has_blocked_response("authentication error while reviewing"))
        for discussion in (
            "HTTP 401 responses are correctly handled",
            "authentication error handling is correct and unauthorized access is prevented",
            "authentication failure tests pass and unauthorized access is prevented",
            "the code correctly returns HTTP 401 for unauthenticated callers",
            "the diff improves error handling",
        ):
            with self.subTest(discussion=discussion):
                body = f"No findings for {head}; {discussion}"
                # Benign discussion is not a service error, but arbitrary prose
                # cannot be machine-certified as an unambiguous clearance.
                self.assertFalse(MODULE._bot_review_has_blocked_response(body))
                comments = [{"user": {"login": login}, "body": body if index == 0 else f"No findings for {head}"}
                            for index, login in enumerate(("coderabbitai", "chatgpt-codex-connector"))]
                with (
                    patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
                    patch.object(MODULE, "review_comments", return_value=([], None)),
                    patch.object(MODULE, "issue_comments", return_value=(comments, None)),
                ):
                    self.assertEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": [{"state": "COMMENTED", "commit_id": head,
                        "user": {"login": "coderabbitai[bot]"}, "body": f"No findings for {head}"}]}, head)["status"], "fail")
                    comments[0]["body"] = f"No findings for {head}"
                    self.assertEqual(MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviews": [{"state": "COMMENTED", "commit_id": head,
                        "user": {"login": "coderabbitai[bot]"}, "body": f"No findings for {head}"}]}, head)["status"], "pass")

    def test_hosted_pr_reads_every_formal_review_page(self) -> None:
        pages = [[{"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "body": "earlier concern"}],
                 [{"user": {"login": "chatgpt-codex-connector[bot]"}, "state": "COMMENTED", "body": "later response"}]]
        outputs = [json.dumps({"number": 7, "url": "https://github.com/o/r/pull/7", "reviews": []}), json.dumps({"nameWithOwner": "o/r"}), json.dumps(pages)]
        with patch.object(MODULE, "run_command", side_effect=[MODULE.subprocess.CompletedProcess([], 0, raw, "") for raw in outputs]) as command:
            pr, error = MODULE.gh_pr(Path.cwd())
        self.assertIsNone(error)
        self.assertEqual(pr["reviews"], pages[0] + pages[1])
        self.assertEqual(command.call_args.args[0], ["gh", "api", "repos/o/r/pulls/7/reviews", "--paginate", "--slurp"])

    def test_review_inventory_rejects_failed_or_malformed_pages(self) -> None:
        for raw, code in (("[]", 0), ("{}", 0), ('[[null]]', 0), ('[[{}]]', 0),
                          ('[[{"user":{"login":"bot"},"body":5}]]', 0), ('[[]]', 1), ("partial", 1)):
            with self.subTest(raw=raw, code=code), patch.object(MODULE, "run_command",
                return_value=MODULE.subprocess.CompletedProcess([], code, raw, "")):
                entries, error = MODULE.review_inventory_collection(Path.cwd(), "repos/o/r/pulls/7/reviews")
                self.assertEqual(entries, [])
                self.assertIsNotNone(error)
        with patch.object(MODULE, "run_command", return_value=MODULE.subprocess.CompletedProcess([], 0, "[[]]", "")):
            self.assertEqual(MODULE.review_inventory_collection(Path.cwd(), "repos/o/r/pulls/7/reviews"), ([], None))

    def test_body_bound_concerns_require_later_bound_clearance_for_both_sources(self) -> None:
        head = "a" * 40
        good = [{"state": "COMMENTED", "commit_id": head, "user": {"login": login},
                 "body": f"No findings for {head}", "submitted_at": "2026-09-11T10:00:00Z"}
                for login in ("coderabbitai", "chatgpt-codex-connector")]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)) as inline,
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            for kind in ("review", "inline"):
                for binding in (head, f"commit {head[:8]}"):
                    with self.subTest(kind=kind, binding=binding):
                        finding = {"state": "COMMENTED", "user": good[1]["user"],
                                   "body": f"A substantive finding remains for {binding}",
                                   "submitted_at": "2026-09-11T11:00:00Z", "created_at": "2026-09-11T11:00:00Z"}
                        reviews = good + ([finding] if kind == "review" else [])
                        inline.return_value = ([finding] if kind == "inline" else [], None)
                        pr = {"number": 7, "reviews": reviews}
                        self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "fail")
                        pr["reviews"] = reviews + [{**finding, "body": f"No findings for {head}", "submitted_at": "2026-09-11T12:00:00Z"}]
                        self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "fail")
                        pr["reviews"] = reviews + [{**good[1], "submitted_at": "2026-09-11T13:00:00Z"}]
                        self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")

    @staticmethod
    def _review_thread_page(
        nodes: list[dict[str, object]],
        *,
        has_next_page: object,
        end_cursor: object,
    ) -> str:
        return json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": has_next_page,
                                    "endCursor": end_cursor,
                                },
                                "nodes": nodes,
                            }
                        }
                    }
                }
            }
        )

    def test_review_threads_reads_every_page_beyond_one_hundred_threads(self) -> None:
        first_page = self._review_thread_page(
            [
                {"id": f"PRRT_{index}", "isResolved": index != 99}
                for index in range(100)
            ],
            has_next_page=True,
            end_cursor="cursor-100",
        )
        second_page = self._review_thread_page(
            [{"id": "PRRT_100", "isResolved": False}],
            has_next_page=False,
            end_cursor="cursor-101",
        )
        responses = [
            MODULE.subprocess.CompletedProcess([], 0, first_page, ""),
            MODULE.subprocess.CompletedProcess([], 0, second_page, ""),
        ]

        with (
            patch.object(MODULE, "repository_slug", return_value=("jscraik/configs", None)),
            patch.object(MODULE, "run_command", side_effect=responses) as run,
        ):
            result, error = MODULE.review_threads(Path.cwd(), 7, "a" * 40)

        self.assertIsNone(error)
        self.assertEqual(result["unresolved_threads"], 2)
        self.assertEqual(
            result["unresolved_thread_ids"], ["PRRT_100", "PRRT_99"]
        )
        self.assertEqual(result["fetched_threads"], 101)
        self.assertEqual(result["pages"], 2)
        self.assertFalse(result["truncated"])
        first_command = run.call_args_list[0].args[0]
        second_command = run.call_args_list[1].args[0]
        self.assertNotIn("cursor=cursor-100", first_command)
        self.assertIn("cursor=cursor-100", second_command)

    def test_review_threads_stops_after_exactly_one_full_page(self) -> None:
        response = self._review_thread_page(
            [
                {"id": f"PRRT_{index}", "isResolved": True}
                for index in range(100)
            ],
            has_next_page=False,
            end_cursor="cursor-100",
        )

        with (
            patch.object(MODULE, "repository_slug", return_value=("jscraik/configs", None)),
            patch.object(
                MODULE,
                "run_command",
                return_value=MODULE.subprocess.CompletedProcess([], 0, response, ""),
            ) as run,
        ):
            result, error = MODULE.review_threads(Path.cwd(), 7, "a" * 40)

        self.assertIsNone(error)
        self.assertEqual(result["fetched_threads"], 100)
        self.assertEqual(result["pages"], 1)
        self.assertFalse(result["truncated"])
        run.assert_called_once()

    def test_review_threads_fails_closed_when_a_later_page_request_fails(self) -> None:
        first_page = self._review_thread_page(
            [{"id": "PRRT_one", "isResolved": True}],
            has_next_page=True,
            end_cursor="cursor-1",
        )
        responses = [
            MODULE.subprocess.CompletedProcess([], 0, first_page, ""),
            MODULE.subprocess.CompletedProcess([], 1, "", "later page unavailable"),
        ]

        with (
            patch.object(MODULE, "repository_slug", return_value=("jscraik/configs", None)),
            patch.object(MODULE, "run_command", side_effect=responses),
        ):
            result, error = MODULE.review_threads(Path.cwd(), 7, "a" * 40)

        self.assertEqual(result, {})
        self.assertIn("page 2", error or "")
        self.assertIn("later page unavailable", error or "")

    def test_review_threads_fails_closed_when_next_page_cursor_is_missing(self) -> None:
        response = self._review_thread_page(
            [{"id": "PRRT_one", "isResolved": True}],
            has_next_page=True,
            end_cursor=None,
        )

        with (
            patch.object(MODULE, "repository_slug", return_value=("jscraik/configs", None)),
            patch.object(
                MODULE,
                "run_command",
                return_value=MODULE.subprocess.CompletedProcess([], 0, response, ""),
            ),
        ):
            result, error = MODULE.review_threads(Path.cwd(), 7, "a" * 40)

        self.assertEqual(result, {})
        self.assertIn("missing endCursor", error or "")

    def test_review_threads_fails_closed_when_cursor_repeats(self) -> None:
        first_page = self._review_thread_page([], has_next_page=True, end_cursor="cursor-1")
        second_page = self._review_thread_page([], has_next_page=True, end_cursor="cursor-1")
        responses = [
            MODULE.subprocess.CompletedProcess([], 0, first_page, ""),
            MODULE.subprocess.CompletedProcess([], 0, second_page, ""),
        ]

        with (
            patch.object(MODULE, "repository_slug", return_value=("jscraik/configs", None)),
            patch.object(MODULE, "run_command", side_effect=responses),
        ):
            result, error = MODULE.review_threads(Path.cwd(), 7, "a" * 40)

        self.assertEqual(result, {})
        self.assertIn("repeated endCursor", error or "")

    def test_review_threads_rejects_malformed_pagination_metadata(self) -> None:
        response = self._review_thread_page([], has_next_page="yes", end_cursor=None)

        with (
            patch.object(MODULE, "repository_slug", return_value=("jscraik/configs", None)),
            patch.object(
                MODULE,
                "run_command",
                return_value=MODULE.subprocess.CompletedProcess([], 0, response, ""),
            ),
        ):
            result, error = MODULE.review_threads(Path.cwd(), 7, "a" * 40)

        self.assertEqual(result, {})
        self.assertIn("hasNextPage must be boolean", error or "")

    def test_review_thread_page_rejects_even_empty_errors(self) -> None:
        payload = json.loads(self._review_thread_page([], has_next_page=False, end_cursor=None))
        self.assertIsNone(MODULE._parse_review_thread_page(json.dumps(payload), 1)[3])
        for errors in ([], [{"message": "provider error"}]):
            with self.subTest(errors=errors):
                payload["errors"] = errors
                result = MODULE._parse_review_thread_page(json.dumps(payload), 1)
                self.assertIn("contained GraphQL errors", result[3] or "")

    def test_review_threads_rejects_partial_graphql_errors(self) -> None:
        payload = json.loads(
            self._review_thread_page(
                [{"id": "PRRT_one", "isResolved": False}],
                has_next_page=False,
                end_cursor=None,
            )
        )
        payload["errors"] = [{"message": "partial provider response"}]

        with (
            patch.object(MODULE, "repository_slug", return_value=("jscraik/configs", None)),
            patch.object(
                MODULE,
                "run_command",
                return_value=MODULE.subprocess.CompletedProcess(
                    [], 0, json.dumps(payload), ""
                ),
            ),
        ):
            result, error = MODULE.review_threads(Path.cwd(), 7, "a" * 40)

        self.assertEqual(result, {})
        self.assertIn("contained GraphQL errors", error or "")

    def test_review_threads_rejects_unknown_thread_identity_or_state(self) -> None:
        invalid_nodes = (
            ({"isResolved": False}, "id must be a nonempty string"),
            ({"id": "", "isResolved": False}, "id must be a nonempty string"),
            ({"id": 7, "isResolved": False}, "id must be a nonempty string"),
            ({"id": "x" * 257, "isResolved": False}, "id must be a nonempty string"),
            ({"id": "PRRT_one"}, "isResolved must be boolean"),
            ({"id": "PRRT_one", "isResolved": None}, "isResolved must be boolean"),
            ({"id": "PRRT_one", "isResolved": 0}, "isResolved must be boolean"),
            ({"id": "PRRT_one", "isResolved": "false"}, "isResolved must be boolean"),
        )
        for node, expected in invalid_nodes:
            response = self._review_thread_page(
                [node], has_next_page=False, end_cursor=None
            )
            with (
                self.subTest(node=node),
                patch.object(
                    MODULE, "repository_slug", return_value=("jscraik/configs", None)
                ),
                patch.object(
                    MODULE,
                    "run_command",
                    return_value=MODULE.subprocess.CompletedProcess([], 0, response, ""),
                ),
            ):
                result, error = MODULE.review_threads(Path.cwd(), 7, "a" * 40)

                self.assertEqual(result, {})
                self.assertIn(expected, error or "")

    def test_review_thread_parser_requires_typed_containers(self) -> None:
        invalid_payloads = (
            ([], "response must be an object"),
            ({"data": []}, "data must be an object"),
            ({"data": {"repository": []}}, "repository must be an object"),
            (
                {"data": {"repository": {"pullRequest": []}}},
                "pullRequest must be an object",
            ),
            (
                {
                    "data": {
                        "repository": {"pullRequest": {"reviewThreads": []}}
                    }
                },
                "reviewThreads must be an object",
            ),
        )
        for payload, expected in invalid_payloads:
            with self.subTest(expected=expected):
                nodes, has_next, cursor, error = MODULE._parse_review_thread_page(
                    json.dumps(payload), 1
                )

                self.assertEqual(nodes, [])
                self.assertFalse(has_next)
                self.assertIsNone(cursor)
                self.assertIn(expected, error or "")

    def test_receipt_rechecks_reject_partial_review_thread_responses(self) -> None:
        head = "a" * 40
        pr = {
            "headRefOid": head,
            "number": 7,
            "reviewDecision": "APPROVED",
            "reviews": [
                {
                    "state": "APPROVED",
                    "commit_id": head,
                    "user": {"login": "reviewer", "type": "User"},
                }
            ],
        }
        for phase in ("update", "review_reconciliation"):
            target = "PRRT_one" if phase == "review_reconciliation" else None
            payload = json.loads(self._review_thread_page(
                [{"id": "PRRT_one", "isResolved": phase == "update"}],
                has_next_page=False, end_cursor=None))
            for errors in (None, [], [{"message": "partial provider response"}]):
                response = dict(payload)
                if errors is not None:
                    response["errors"] = errors
                with (
                    self.subTest(phase=phase, errors=errors),
                    patch.object(MODULE, "gh_pr", return_value=(pr, None)),
                    patch.object(MODULE, "phase_checks_lane", return_value={"status": "pass", "evidence": "checks pass"}),
                    patch.object(MODULE, "repository_slug", return_value=("jscraik/configs", None)),
                    patch.object(MODULE, "run_command", return_value=MODULE.subprocess.CompletedProcess([], 0, json.dumps(response), "")),
                ):
                    error = MODULE.recheck_hosted_state(Path.cwd(), phase, head, expected_thread_id=target)
                    if errors is None:
                        self.assertIsNone(error)
                    else:
                        self.assertIn("contained GraphQL errors", error or "")

    def test_schema_declares_phase_bound_reconciliation_authority(self) -> None:
        schema_path = MODULE_PATH.parents[1] / "schemas" / "pr-readiness.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertIn("review_reconciliation", schema["properties"]["phase"]["enum"])
        authority = schema["properties"]["authority"]["properties"]
        self.assertEqual(
            authority["allowed_mutations"]["enum"],
            [["review_thread_reply", "review_thread_resolve"], ["review_request_comment"]],
        )
        self.assertFalse(authority["acceptance_claims_proven"]["const"])

    def test_scope_digest_is_order_independent_and_repository_relative(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr-scope-") as tmpdir:
            scope = Path(tmpdir) / "scope.txt"
            scope.write_text("b.txt\na.txt\na.txt\n", encoding="utf-8")

            paths, digest = MODULE.parse_scope(scope, Path(tmpdir))

        self.assertEqual(paths, ["a.txt", "b.txt"])
        self.assertEqual(len(digest or ""), 64)

    def test_scope_rejects_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr-scope-") as tmpdir:
            scope = Path(tmpdir) / "scope.txt"
            scope.write_text("/tmp/outside.txt\n", encoding="utf-8")

            paths, error = MODULE.parse_scope(scope, Path(tmpdir))

        self.assertEqual(paths, [])
        self.assertIn("repository-relative", error or "")

    def test_scope_result_classifies_digest_without_treating_errors_as_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pr-scope-") as tmpdir:
            scope = Path(tmpdir) / "scope.txt"
            scope.write_text("a.txt\n", encoding="utf-8")
            _paths, digest = MODULE.parse_scope(scope, Path(tmpdir))

        self.assertTrue(MODULE.is_scope_digest(digest))
        self.assertFalse(MODULE.is_scope_digest("scope path must stay repository-relative: /tmp/outside.txt"))

    def test_checks_lane_distinguishes_pending_and_failure(self) -> None:
        pr = {"statusCheckRollup": [{"name": "lint", "state": "SUCCESS"}, {"name": "tests", "state": "PENDING"}]}
        pending = MODULE.checks_lane(pr, "a" * 40)
        self.assertEqual(pending["status"], "blocked")

        pr["statusCheckRollup"][1]["state"] = "FAILURE"
        failed = MODULE.checks_lane(pr, "a" * 40)
        self.assertEqual(failed["status"], "fail")

    def test_update_checks_require_explicit_success(self) -> None:
        head = "a" * 40
        for lifecycle in (
            {"status": "COMPLETED", "conclusion": "NEUTRAL"},
            {"status": "COMPLETED", "conclusion": "SKIPPED"},
            {"status": "COMPLETED"},
        ):
            check = {"name": "test", **lifecycle}
            stale_success = {
                "name": "test",
                "conclusion": "SUCCESS",
                "completedAt": "2026-08-01T19:05:47Z",
            }
            for rollup in ([check], [stale_success, check]):
                with self.subTest(lifecycle=lifecycle, duplicate=len(rollup) == 2):
                    result = MODULE.phase_checks_lane(
                        {"statusCheckRollup": rollup},
                        head,
                        "update",
                    )
                    self.assertEqual(result["status"], "blocked")
                    self.assertEqual(result["details"]["pending"], ["test"])

        for lifecycle in (
            {"state": "SUCCESS"},
            {"status": "COMPLETED", "conclusion": "SUCCESS"},
            {"conclusion": "SUCCESSFUL"},
        ):
            with self.subTest(lifecycle=lifecycle):
                result = MODULE.phase_checks_lane(
                    {"statusCheckRollup": [{"name": "test", **lifecycle}]},
                    head,
                    "update",
                )
                self.assertEqual(result["status"], "pass")

        failed = MODULE.phase_checks_lane(
            {
                "statusCheckRollup": [
                    {"name": "test", "status": "COMPLETED", "conclusion": "FAILURE"}
                ]
            },
            head,
            "update",
        )
        self.assertEqual(failed["status"], "fail")
        self.assertEqual(failed["details"]["failures"], ["test"])

    def test_checks_lane_uses_newest_duplicate_context(self) -> None:
        head = "a" * 40
        pr = {
            "statusCheckRollup": [
                {"name": "pr-template", "conclusion": "FAILURE", "completedAt": "2026-08-01T19:05:47Z"},
                {"name": "linear-gate", "conclusion": "FAILURE", "completedAt": "2026-08-01T19:10:49Z"},
                {"name": "pr-template", "conclusion": "SUCCESS", "completedAt": "2026-08-01T19:17:42Z"},
                {"name": "linear-gate", "conclusion": "SUCCESS", "completedAt": "2026-08-01T19:18:08Z"},
            ],
        }

        result = MODULE.checks_lane(pr, head)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(result["details"]["checks"]), 2)
        self.assertEqual(
            {item["name"] for item in result["details"]["checks"]},
            {"pr-template", "linear-gate"},
        )

    def test_checks_lane_blocks_queued_duplicate_without_timestamp(self) -> None:
        head = "a" * 40
        pr = {
            "statusCheckRollup": [
                {"name": "test", "conclusion": "SUCCESS", "completedAt": "2026-08-01T19:05:47Z"},
                {"name": "test", "status": "QUEUED"},
            ],
        }

        result = MODULE.checks_lane(pr, head)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["details"]["pending"], ["test"])

    def test_checks_lane_blocks_timestampless_failure_until_later_success(self) -> None:
        head = "a" * 40
        stale_success_then_failure = {
            "statusCheckRollup": [
                {"name": "test", "conclusion": "SUCCESS", "completedAt": "2026-08-01T19:05:47Z"},
                {"name": "test", "conclusion": "FAILURE"},
            ],
        }
        result = MODULE.checks_lane(stale_success_then_failure, head)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["details"]["failures"], ["test"])

        later_success = {
            "statusCheckRollup": [
                {"name": "test", "conclusion": "FAILURE"},
                {"name": "test", "conclusion": "SUCCESS", "completedAt": "2026-08-01T19:17:42Z"},
            ],
        }
        result = MODULE.checks_lane(later_success, head)
        self.assertEqual(result["status"], "pass")

    def test_checks_lane_keeps_same_named_check_runs_from_distinct_workflows(self) -> None:
        head = "a" * 40
        pr = {
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "test",
                    "workflowName": "unit",
                    "app": {"slug": "circleci"},
                    "conclusion": "FAILURE",
                    "completedAt": "2026-08-02T19:05:47Z",
                },
                {
                    "__typename": "CheckRun",
                    "name": "test",
                    "workflowName": "integration",
                    "app": {"slug": "circleci"},
                    "conclusion": "SUCCESS",
                    "completedAt": "2026-08-02T19:17:42Z",
                },
            ],
        }

        result = MODULE.checks_lane(pr, head)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["details"]["failures"], ["test"])

    def test_checks_lane_keeps_unidentified_same_named_check_runs_separate(self) -> None:
        head = "a" * 40
        pr = {
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "test",
                    "conclusion": "FAILURE",
                    "completedAt": "2026-08-02T19:05:47Z",
                },
                {
                    "__typename": "CheckRun",
                    "name": "test",
                    "conclusion": "SUCCESS",
                    "completedAt": "2026-08-02T19:17:42Z",
                },
            ],
        }

        result = MODULE.checks_lane(pr, head)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["details"]["failures"], ["test"])

    def test_checks_lane_dedupes_status_contexts_by_context_name(self) -> None:
        head = "a" * 40
        pr = {
            "statusCheckRollup": [
                {
                    "__typename": "StatusContext",
                    "context": "ci/build",
                    "state": "FAILURE",
                    "createdAt": "2026-08-01T19:05:47Z",
                },
                {
                    "__typename": "StatusContext",
                    "context": "ci/build",
                    "state": "SUCCESS",
                    "createdAt": "2026-08-01T19:17:42Z",
                },
            ]
        }

        result = MODULE.checks_lane(pr, head)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(result["details"]["checks"]), 1)

    def test_reviews_lane_accepts_exact_solo_review_waiver(self) -> None:
        head = "a" * 40
        pr = {
            "number": 377,
            "reviewDecision": "APPROVED",
            "reviews": [
                {
                    "state": "APPROVED",
                    "commit": {"oid": head},
                    "user": {"login": "Jamie", "type": "User"},
                }
            ],
        }
        waiver = {
            "schema_version": MODULE.REVIEW_WAIVER_SCHEMA,
            "pr_number": 377,
            "head_sha": head,
            "scope": MODULE.REVIEW_WAIVER_SCOPE,
            "authorized_by": "Jamie",
            "reason": "explicit waiver for missing independent bot approvals on this exact PR head",
            "rule_or_section": "codex/AGENTS.md review quorum",
            "tracking_ticket": "JSC-411",
            "expiry_or_adr": "2026-08-31",
            "path": str(Path(tempfile.gettempdir()) / "pr-377-solo-review-waiver.json"),
            "sha256": "0" * 64,
        }
        with patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)):
            result = MODULE.reviews_lane(Path.cwd(), pr, head, waiver)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["details"]["review_mode"], "solo_review_waiver")

    def test_reviews_lane_rejects_unhosted_solo_review_waiver(self) -> None:
        head = "a" * 40
        pr = {"number": 377, "reviewDecision": "", "reviews": []}
        waiver = {
            "schema_version": MODULE.REVIEW_WAIVER_SCHEMA,
            "pr_number": 377,
            "head_sha": head,
            "scope": MODULE.REVIEW_WAIVER_SCOPE,
            "authorized_by": "Jamie",
            "reason": "locally authored waiver must not bypass independent review",
            "rule_or_section": "codex/AGENTS.md review quorum",
            "tracking_ticket": "JSC-411",
            "expiry_or_adr": "ADR-411",
            "path": str(Path(tempfile.gettempdir()) / "pr-377-solo-review-waiver.json"),
            "sha256": "0" * 64,
        }
        with patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)):
            result = MODULE.reviews_lane(Path.cwd(), pr, head, waiver)
        self.assertEqual(result["status"], "fail")
        self.assertIn("matching current-head human APPROVED review", result["evidence"])

    def test_reviews_lane_accepts_case_insensitive_waiver_approver(self) -> None:
        head = "a" * 40
        pr = {
            "number": 377,
            "reviewDecision": "APPROVED",
            "reviews": [
                {
                    "state": "APPROVED",
                    "commit": {"oid": head},
                    "user": {"login": "Jamie", "type": "User"},
                }
            ],
        }
        waiver = {
            "schema_version": MODULE.REVIEW_WAIVER_SCHEMA,
            "pr_number": 377,
            "head_sha": head,
            "scope": MODULE.REVIEW_WAIVER_SCOPE,
            "authorized_by": "jamie",
            "reason": "case-insensitive login binding",
            "rule_or_section": "codex/AGENTS.md review quorum",
            "tracking_ticket": "JSC-411",
            "expiry_or_adr": "ADR-411",
        }
        with patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)):
            result = MODULE.reviews_lane(Path.cwd(), pr, head, waiver)
        self.assertEqual(result["status"], "pass")

    def test_reviews_lane_rejects_waiver_naming_non_approver(self) -> None:
        head = "a" * 40
        pr = {
            "number": 377,
            "reviewDecision": "APPROVED",
            "reviews": [
                {
                    "state": "APPROVED",
                    "commit": {"oid": head},
                    "user": {"login": "Jamie", "type": "User"},
                }
            ],
        }
        waiver = {
            "schema_version": MODULE.REVIEW_WAIVER_SCHEMA,
            "pr_number": 377,
            "head_sha": head,
            "scope": MODULE.REVIEW_WAIVER_SCOPE,
            "authorized_by": "Robin",
            "reason": "non-approver must not authorize a waiver",
            "rule_or_section": "codex/AGENTS.md review quorum",
            "tracking_ticket": "JSC-411",
            "expiry_or_adr": "ADR-411",
        }
        with patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)):
            result = MODULE.reviews_lane(Path.cwd(), pr, head, waiver)
        self.assertEqual(result["status"], "fail")

    def test_load_review_waiver_binds_pr_and_head(self) -> None:
        head = "b" * 40
        payload = {
            "schema_version": MODULE.REVIEW_WAIVER_SCHEMA,
            "pr_number": 377,
            "head_sha": head,
            "scope": MODULE.REVIEW_WAIVER_SCOPE,
            "authorized_by": "Jamie",
            "reason": "explicit waiver for this exact PR head",
            "rule_or_section": "codex/AGENTS.md review quorum",
            "tracking_ticket": "JSC-411",
            "expiry_or_adr": "2026-08-31",
        }
        with tempfile.TemporaryDirectory(prefix="pr-waiver-") as tmpdir:
            path = Path(tmpdir) / "waiver.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded, error = MODULE.load_review_waiver(path, 377, head)
        self.assertIsNone(error)
        self.assertEqual(loaded["pr_number"], 377)
        self.assertRegex(loaded["sha256"], r"^[0-9a-f]{64}$")

    def test_load_review_waiver_rejects_missing_governance_metadata(self) -> None:
        head = "c" * 40
        payload = {
            "schema_version": MODULE.REVIEW_WAIVER_SCHEMA,
            "pr_number": 377,
            "head_sha": head,
            "scope": MODULE.REVIEW_WAIVER_SCOPE,
            "authorized_by": "Jamie",
            "reason": "explicit waiver for this exact PR head",
            "rule_or_section": "codex/AGENTS.md review quorum",
            "tracking_ticket": "JSC-411",
            "expiry_or_adr": "",
        }
        with tempfile.TemporaryDirectory(prefix="pr-waiver-") as tmpdir:
            path = Path(tmpdir) / "waiver.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded, error = MODULE.load_review_waiver(path, 377, head)
        self.assertIsNone(loaded)
        self.assertEqual(error, "review waiver expiry_or_adr is required")

    def test_load_review_waiver_rejects_binding_and_scope_mismatches(self) -> None:
        head = "d" * 40
        base = {
            "schema_version": MODULE.REVIEW_WAIVER_SCHEMA,
            "pr_number": 377,
            "head_sha": head,
            "scope": MODULE.REVIEW_WAIVER_SCOPE,
            "authorized_by": "Jamie",
            "reason": "bounded waiver fixture",
            "rule_or_section": "codex/AGENTS.md review quorum",
            "tracking_ticket": "JSC-411",
            "expiry_or_adr": "ADR-411",
        }
        cases = (
            ("pr_number", 378, "PR number does not match"),
            ("head_sha", "e" * 40, "head does not match"),
            ("scope", "other scope", "scope is not the narrow"),
        )
        with tempfile.TemporaryDirectory(prefix="pr-waiver-") as tmpdir:
            path = Path(tmpdir) / "waiver.json"
            for key, value, expected in cases:
                payload = {**base, key: value}
                path.write_text(json.dumps(payload), encoding="utf-8")
                loaded, error = MODULE.load_review_waiver(path, 377, head)
                self.assertIsNone(loaded)
                self.assertIn(expected, error or "")

            extra = {**base, "unexpected": True}
            path.write_text(json.dumps(extra), encoding="utf-8")
            loaded, error = MODULE.load_review_waiver(path, 377, head)
        self.assertIsNone(loaded)
        self.assertIn("exactly the required fields", error or "")

    def test_validate_review_waiver_record_rejects_swapped_file(self) -> None:
        head = "e" * 40
        payload = {
            "schema_version": MODULE.REVIEW_WAIVER_SCHEMA,
            "pr_number": 377,
            "head_sha": head,
            "scope": MODULE.REVIEW_WAIVER_SCOPE,
            "authorized_by": "Jamie",
            "reason": "original waiver",
            "rule_or_section": "codex/AGENTS.md review quorum",
            "tracking_ticket": "JSC-411",
            "expiry_or_adr": "ADR-411",
        }
        with tempfile.TemporaryDirectory(prefix="pr-waiver-") as tmpdir:
            path = Path(tmpdir) / "waiver.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded, error = MODULE.load_review_waiver(path, 377, head)
            self.assertIsNone(error)
            payload["authorized_by"] = "Robin"
            path.write_text(json.dumps(payload), encoding="utf-8")
            revalidated, error = MODULE.validate_review_waiver_record(loaded, 377, head)
        self.assertIsNone(revalidated)
        self.assertIn("digest changed", error or "")

    def test_reviews_lane_accepts_current_head_coderabbit_and_codex_quorum(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:00:00Z", "body": f"No actionable comments were generated for {head}"},
                {"state": "APPROVED", "commit": {"oid": head}, "author": {"login": "chatgpt-codex-connector"}, "submittedAt": "2026-07-28T10:01:00Z", "body": f"No findings for {head}"},
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["details"]["review_mode"], "bot_quorum")

    def test_reviews_lane_accepts_abbreviated_current_head_bot_review(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:00:00Z", "body": f"No findings for {head[:7]}"},
                {"state": "APPROVED", "commit": {"oid": head}, "author": {"login": "chatgpt-codex-connector"}, "submittedAt": "2026-07-28T10:01:00Z", "body": f"No findings for {head[:7]}"},
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["details"]["review_mode"], "bot_quorum")

    def test_reviews_lane_keeps_verified_completion_before_blank_native_approval(self) -> None:
        head = "a" * 40
        completion = {"id": 42, "user": {"login": "coderabbitai[bot]"},
                      "commit_id": head, "state": "COMMENTED", "source": "coderabbit_completion",
                      "body": f"No findings for {head}.",
                      "created_at": "2026-11-17T12:51:46Z", "updated_at": "2026-11-17T12:51:46Z",
                      "completion_evidence": {"completed_at": "2026-11-17T12:51:46Z"}}
        approval = {"state": "APPROVED", "commit": {"oid": head},
                    "author": {"login": "coderabbitai"}, "submittedAt": "2026-11-17T12:51:52Z", "body": ""}
        peer = {"state": "COMMENTED", "commit": {"oid": head},
                "author": {"login": "chatgpt-codex-connector"}, "submittedAt": "2026-11-17T12:49:42Z",
                "body": f"No findings for {head}."}
        pr = {"number": 7, "reviewDecision": "APPROVED", "reviews": [approval, peer]}
        with (patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
              patch.object(MODULE, "review_comments", return_value=([], None)),
              patch.object(MODULE, "issue_comments", return_value=([], None)),
              patch.object(MODULE, "codex_completion_review", return_value=(None, None)),
              patch.object(MODULE, "coderabbit_completion_review", return_value=(completion, None)) as verified):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
            self.assertEqual(result["status"], "pass", result)
            self.assertEqual(completion["created_at"], "2026-11-17T12:51:46Z")
            for mutation in ({"state": "CHANGES_REQUESTED"}, {"body": "Unknown review narrative"},
                             {"body": "Potential issue: unsafe workflow"}):
                with self.subTest(mutation=mutation):
                    changed = {**pr, "reviews": [{**approval, **mutation}, peer]}
                    self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), changed, head)["status"], "pass")
            verified.return_value = (None, None)
            self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")
            for mutation in ({"commit_id": "b" * 40}, {"id": None},
                             {"body": "Potential issue: unsafe workflow"}):
                with self.subTest(completion_mutation=mutation):
                    verified.return_value = ({**completion, **mutation}, None)
                    self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "pass")

    def test_reviews_lane_rejects_blank_bot_approval(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:00:00Z", "body": f"No findings for {head[:7]}"},
                {"state": "APPROVED", "commit": {"oid": head}, "author": {"login": "chatgpt-codex-connector"}, "submittedAt": "2026-07-28T10:01:00Z", "body": ""},
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("Codex", result["evidence"])

    def test_reviews_lane_accepts_current_head_inline_no_findings_comments(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        comments = [
            {"user": {"login": "coderabbitai[bot]"}, "commit_id": head, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "commit_id": head, "created_at": "2026-07-28T10:01:00Z", "body": f"No actionable comments for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=(comments, None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["details"]["current_head_bot_comments"], ["chatgpt-codex-connector", "coderabbitai"])

    def test_reviews_lane_accepts_current_head_issue_no_findings_comments(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        comments = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No actionable comments were generated for {head}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": f"No findings for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(
                MODULE,
                "review_comments",
                return_value=(
                    [
                        {
                            "user": {"login": "coderabbitai[bot]"},
                            "created_at": "2026-07-28T10:02:00Z",
                            "body": f"No findings for {head}",
                            "commit_id": head,
                        },
                    ],
                    None,
                ),
            ),
            patch.object(MODULE, "issue_comments", return_value=(comments, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["details"]["current_head_bot_issue_comments"], ["chatgpt-codex-connector"])

    def test_reviews_lane_ignores_unbound_positive_issue_comment_after_current_head_review(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        review_comments = [
            {"user": {"login": "coderabbitai[bot]"}, "commit_id": head, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "commit_id": head, "created_at": "2026-07-28T10:01:00Z", "body": f"No actionable comments for {head}"},
        ]
        issue_entries = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:02:00Z", "body": "No findings"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=(review_comments, None)),
            patch.object(MODULE, "issue_comments", return_value=(issue_entries, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")

    def test_reviews_lane_ignores_sha_bound_stale_blocker_review(self) -> None:
        head = "a" * 40
        stale = "b" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
                {"state": "COMMENTED", "commit": {"oid": stale}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:02:00Z", "body": f"quota exceeded for {stale}"},
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "chatgpt-codex-connector"}, "submittedAt": "2026-07-28T10:01:00Z", "body": f"No actionable comments for {head}"},
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")

    def test_reviews_lane_blocks_on_issue_comments_error(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], "some error message")),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "blocked")

    def test_issue_comment_cannot_replace_a_nonqualifying_formal_review(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:00:00Z", "body": "Review complete."},
            ],
        }
        issue_entries = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": self.coderabbit_clearance(head)},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:02:00Z", "body": f"No actionable comments for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(issue_entries, None)),
        ):
            self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], "fail")
            pr["reviews"].append({"state": "COMMENTED", "commit_id": head,
                                  "user": {"login": "coderabbitai[bot]"}, "body": f"No findings for {head}",
                                  "submitted_at": "2026-07-28T10:03:00Z"})
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["details"]["review_mode"], "bot_quorum")

    def test_reviews_lane_rejects_newer_blocked_issue_comment(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        issue_entries = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": f"Review error for {head}: quota exceeded"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:02:00Z", "body": f"No actionable comments for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(issue_entries, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_newer_blocked_review_over_older_comment(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:02:00Z", "body": f"Review error for {head}: quota exceeded"},
            ],
        }
        issue_entries = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:03:00Z", "body": f"No actionable comments for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(issue_entries, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_stale_issue_no_findings_comments(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        comments = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {'b' * 40}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": f"No findings for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(comments, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_quota_issue_comment(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        comments = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": "You have reached your Codex usage limits for code reviews."},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(comments, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("Codex", result["evidence"])

    def test_reviews_lane_rejects_incidental_request_id_as_stale_sha(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        comments = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": "review failed; request deadbeef"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(comments, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("Codex", result["evidence"])

    def test_reviews_lane_recognizes_multiword_auth_expiry(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        comments = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": "authentication token expired"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No actionable comments for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(comments, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_decorated_401_response(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        comments = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": "HTTP 401: Bad credentials (request 1234)"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No actionable comments for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(comments, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_common_403_permission_responses(self) -> None:
        head = "a" * 40
        for response in ("HTTP 403 Forbidden", "403 Forbidden", "Resource not accessible by integration"):
            pr = {"number": 7, "reviewDecision": "", "reviews": []}
            comments = [
                {
                    "user": {"login": "coderabbitai[bot]"},
                    "created_at": "2026-07-28T10:00:00Z",
                    "body": f"No findings for {head}",
                },
                {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": response},
                {
                    "user": {"login": "chatgpt-codex-connector[bot]"},
                    "created_at": "2026-07-28T10:00:00Z",
                    "body": f"No actionable comments for {head}",
                },
            ]
            with (
                patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
                patch.object(MODULE, "review_comments", return_value=([], None)),
                patch.object(MODULE, "issue_comments", return_value=(comments, None)),
            ):
                result = MODULE.reviews_lane(Path.cwd(), pr, head)
            self.assertEqual(result["status"], "fail", response)
            self.assertIn("CodeRabbit", result["evidence"], response)

    def test_reviews_lane_ignores_unbound_blocker_explicitly_bound_to_stale_sha(self) -> None:
        head = "a" * 40
        stale = "b" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": [
            {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"state": "COMMENTED", "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:01:00Z", "body": f"quota exceeded for {stale}"},
            {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "chatgpt-codex-connector"}, "submittedAt": "2026-07-28T10:00:00Z", "body": f"No actionable comments for {head}"},
        ]}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")

    def test_reviews_lane_rejects_unbound_blocker_bound_to_long_current_sha_prefix(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        comments = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
            {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": f"quota exceeded for {head[:12]}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": "2026-07-28T10:00:00Z", "body": f"No actionable comments for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(comments, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_unbound_blocker_after_current_head_no_findings(self) -> None:
        head = "a" * 40
        for login, label in (("coderabbitai[bot]", "CodeRabbit"), ("chatgpt-codex-connector[bot]", "Codex")):
            for blocker in ("quota exceeded", "rate limited", "authentication failed"):
                pr = {"number": 7, "reviewDecision": "", "reviews": [{"state": "COMMENTED",
                      "commit_id": head, "user": {"login": "coderabbitai[bot]"},
                      "body": f"No findings for {head}", "submitted_at": "2026-07-28T09:00:00Z"}]}
                comments = [
                    {"user": {"login": login}, "created_at": "2026-07-28T10:00:00Z", "body": f"No findings for {head}"},
                    {"user": {"login": login}, "created_at": "2026-07-28T10:01:00Z", "body": blocker},
                    {
                        "user": {"login": "chatgpt-codex-connector[bot]" if login.startswith("coderabbit") else "coderabbitai[bot]"},
                        "created_at": "2026-07-28T10:02:00Z",
                        "body": f"No actionable comments for {head}" if login.startswith("coderabbit") else self.coderabbit_clearance(head),
                    },
                ]
                with (
                    patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
                    patch.object(MODULE, "review_comments", return_value=([], None)),
                    patch.object(MODULE, "issue_comments", return_value=(comments, None)),
                ):
                    result = MODULE.reviews_lane(Path.cwd(), pr, head)
                self.assertEqual(result["status"], "fail", f"{label}: {blocker}")
                self.assertIn(label, result["evidence"], f"{label}: {blocker}")

    def test_reviews_lane_uses_updated_issue_comment_timestamp(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "coderabbitai"},
                    "submittedAt": "2026-07-28T10:02:00Z",
                    "body": f"No findings for {head}",
                },
            ],
        }
        comments = [
            {
                "user": {"login": "coderabbitai[bot]"},
                "created_at": "2026-07-28T10:00:00Z",
                "updated_at": "2026-07-28T10:03:00Z",
                "body": "rate limited while refreshing review",
            },
            {
                "user": {"login": "chatgpt-codex-connector[bot]"},
                "created_at": "2026-07-28T10:01:00Z",
                "body": f"No actionable comments for {head}",
            },
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(comments, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_prefers_equal_timestamp_blocker(self) -> None:
        head = "a" * 40
        timestamp = "2026-07-28T10:02:00Z"
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "coderabbitai"},
                    "submittedAt": timestamp,
                    "body": f"No findings for {head}",
                },
            ],
        }
        issue_entries = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": timestamp, "body": "quota exceeded"},
            {
                "user": {"login": "chatgpt-codex-connector[bot]"},
                "created_at": "2026-07-28T10:03:00Z",
                "body": f"No actionable comments for {head}",
            },
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(issue_entries, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_preserves_equal_timestamp_blocker_within_hosted_reviews(self) -> None:
        head = "a" * 40
        timestamp = "2026-07-28T10:02:00Z"
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": timestamp, "body": f"No findings for {head}"},
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": timestamp, "body": "quota exceeded"},
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "chatgpt-codex-connector"}, "submittedAt": timestamp, "body": f"No actionable comments for {head}"},
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_preserves_equal_timestamp_blocker_within_issue_comments(self) -> None:
        head = "a" * 40
        timestamp = "2026-07-28T10:02:00Z"
        issue_entries = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": timestamp, "body": "quota exceeded"},
            {"user": {"login": "coderabbitai[bot]"}, "created_at": timestamp, "body": f"No findings for {head}"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "created_at": timestamp, "body": f"No actionable comments for {head}"},
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(issue_entries, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviewDecision": "", "reviews": []}, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_prefers_equal_timestamp_inline_blocker_over_positive_hosted_review(self) -> None:
        head = "a" * 40
        timestamp = "2026-07-28T10:02:00Z"
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "chatgpt-codex-connector"},
                    "submittedAt": timestamp,
                    "body": f"No actionable comments for {head}",
                },
            ],
        }
        inline_comments = [
            {
                "user": {"login": "coderabbitai[bot]"},
                "commit_id": head,
                "created_at": timestamp,
                "body": f"No findings for {head}",
            },
        ]
        issue_entries = [
            {
                "user": {"login": "coderabbitai[bot]"},
                "created_at": timestamp,
                "body": "quota exceeded",
            },
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=(inline_comments, None)),
            patch.object(MODULE, "issue_comments", return_value=(issue_entries, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_issue_positive_cannot_erase_same_timestamp_review_concerns(self) -> None:
        head = "a" * 40
        timestamp = "2026-07-28T10:02:00Z"
        issue_entries = [
            {"user": {"login": "coderabbitai[bot]"}, "created_at": timestamp, "body": f"Review complete for {head}"},
            {"user": {"login": "coderabbitai[bot]"}, "created_at": timestamp, "body": self.coderabbit_clearance(head)},
            {
                "user": {"login": "chatgpt-codex-connector[bot]"},
                "created_at": timestamp,
                "body": f"No actionable comments for {head}",
            },
        ]
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=(issue_entries, None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), {"number": 7, "reviewDecision": "", "reviews": []}, head)
        self.assertEqual(result["status"], "fail")

    def test_reviews_lane_preserves_same_timestamp_api_order_for_positive_hosted_reviews(self) -> None:
        head = "a" * 40
        timestamp = "2026-07-28T10:02:00Z"
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "coderabbitai"},
                    "submittedAt": timestamp,
                    "body": f"Review complete for {head}",
                },
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "coderabbitai"},
                    "submittedAt": timestamp,
                    "body": f"No findings for {head}",
                },
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "chatgpt-codex-connector"},
                    "submittedAt": timestamp,
                    "body": f"No actionable comments for {head}",
                },
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")

    def test_reviews_lane_rejects_unbound_blocked_review_submission(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "coderabbitai"},
                    "submittedAt": "2026-07-28T10:00:00Z",
                    "body": f"No findings for {head}",
                },
                {
                    "state": "COMMENTED",
                    "author": {"login": "coderabbitai"},
                    "submittedAt": "2026-07-28T10:01:00Z",
                    "body": "authentication failed while reviewing",
                },
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "chatgpt-codex-connector"},
                    "submittedAt": "2026-07-28T10:02:00Z",
                    "body": f"No actionable comments for {head}",
                },
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_quota_or_error_in_no_findings_comments(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": []}
        for blocker in ("quota exceeded", "error: review unavailable"):
            comments = [
                {
                    "user": {"login": "coderabbitai[bot]"},
                    "created_at": "2026-07-28T10:00:00Z",
                    "body": f"No findings for {head}; {blocker}",
                },
                {
                    "user": {"login": "chatgpt-codex-connector[bot]"},
                    "created_at": "2026-07-28T10:01:00Z",
                    "body": f"No actionable comments for {head}",
                },
            ]
            with (
                patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
                patch.object(MODULE, "review_comments", return_value=([], None)),
                patch.object(MODULE, "issue_comments", return_value=(comments, None)),
            ):
                result = MODULE.reviews_lane(Path.cwd(), pr, head)
            self.assertEqual(result["status"], "fail", blocker)
            self.assertIn("CodeRabbit", result["evidence"], blocker)

    def test_reviews_lane_rejects_missing_bot_quorum_member(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": [{"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}}]}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("Codex", result["evidence"])

    def test_reviews_lane_selects_quorum_from_committed_paths(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "baseRefOid": "b" * 40, "reviewDecision": "", "reviews": [
            {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"},
             "body": f"No findings for {head}."}]}
        for path, expected in (("guide.md", "pass"), ("scripts/format.py", "pass"), ("scripts/pr-readiness.py", "fail")):
            with (self.subTest(path=path),
                  patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0}, None)),
                  patch.object(MODULE, "review_comments", return_value=([], None)),
                  patch.object(MODULE, "issue_comments", return_value=([], None)),
                  patch.object(MODULE, "changed_file_records", return_value=[
                      {"path": path, "old_mode": "100644", "new_mode": "100644"}])):
                self.assertEqual(MODULE.reviews_lane(Path.cwd(), pr, head)["status"], expected)

    def test_reviews_lane_rejects_stale_or_unknown_bot_reviews(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": "b" * 40}, "author": {"login": "coderabbitai"}},
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "unknown-bot"}},
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "chatgpt-codex-connector"}},
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_stale_review_with_current_sha_in_body(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {
                    "state": "COMMENTED",
                    "commit": {"oid": "b" * 40},
                    "author": {"login": "coderabbitai"},
                    "submittedAt": "2026-07-28T10:00:00Z",
                    "body": f"No findings for {head}",
                },
                {
                    "state": "COMMENTED",
                    "commit": {"oid": head},
                    "author": {"login": "chatgpt-codex-connector"},
                    "submittedAt": "2026-07-28T10:01:00Z",
                    "body": f"No actionable comments for {head}",
                },
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_unbound_unauthorized_response_after_no_findings(self) -> None:
        head = "a" * 40
        for blocker in (
            "Unauthorized",
            "401 unauthorized",
            "HTTP 401",
            "401",
            "Unauthorized request",
            "Bad credentials",
            "invalid credentials",
            "credentials expired",
        ):
            pr = {"number": 7, "reviewDecision": "", "reviews": []}
            comments = [
                {
                    "user": {"login": "coderabbitai[bot]"},
                    "created_at": "2026-07-28T10:00:00Z",
                    "body": f"No findings for {head}",
                },
                {"user": {"login": "coderabbitai[bot]"}, "created_at": "2026-07-28T10:01:00Z", "body": blocker},
                {
                    "user": {"login": "chatgpt-codex-connector[bot]"},
                    "created_at": "2026-07-28T10:00:00Z",
                    "body": f"No actionable comments for {head}",
                },
            ]
            with (
                patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
                patch.object(MODULE, "review_comments", return_value=([], None)),
                patch.object(MODULE, "issue_comments", return_value=(comments, None)),
            ):
                result = MODULE.reviews_lane(Path.cwd(), pr, head)
            self.assertEqual(result["status"], "fail")
            self.assertIn("CodeRabbit", result["evidence"])

    def test_reviews_lane_rejects_latest_bot_changes_requested(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "",
            "reviews": [
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:00:00Z"},
                {"state": "CHANGES_REQUESTED", "commit": {"oid": head}, "author": {"login": "coderabbitai"}, "submittedAt": "2026-07-28T10:01:00Z"},
                {"state": "COMMENTED", "commit": {"oid": head}, "author": {"login": "chatgpt-codex-connector"}, "submittedAt": "2026-07-28T10:02:00Z"},
            ],
        }
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")
        self.assertIn("CHANGES_REQUESTED", result["evidence"])

    def test_reviews_lane_preserves_human_approval_path(self) -> None:
        head = "a" * 40
        pr = {
            "number": 7,
            "reviewDecision": "APPROVED",
            "reviews": [{"state": "APPROVED", "commit": {"oid": head}, "user": {"login": "reviewer", "type": "User"}}],
        }
        with patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["details"]["review_mode"], "human_approval")

        with patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 1, "truncated": False}, None)):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "fail")

    def test_managed_user_approvals_keep_current_head_decision_and_thread_gates(self) -> None:
        """Supported managed logins do not waive approval freshness or thread gates."""
        head = "a" * 40
        for login in ("mona-cat_octo", "octo_admin"):
            for reviewed_head in (head, "b" * 40):
                for decision in ("", "APPROVED"):
                    for unresolved in (0, 1):
                        with self.subTest(login=login, reviewed_head=reviewed_head, decision=decision, unresolved=unresolved):
                            pr = {"number": 7, "reviewDecision": decision, "reviews": [
                                {"state": "APPROVED", "commit_id": reviewed_head,
                                 "user": {"login": login, "type": "User"}},
                            ]}
                            with (
                                patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": unresolved, "truncated": False}, None)),
                                patch.object(MODULE, "review_comments", return_value=([], None)),
                                patch.object(MODULE, "issue_comments", return_value=([], None)),
                            ):
                                result = MODULE.reviews_lane(Path.cwd(), pr, head)
                            expected = reviewed_head == head and decision == "APPROVED" and unresolved == 0
                            self.assertEqual(result["status"] == "pass", expected)
                            if expected:
                                self.assertEqual(result["details"]["review_mode"], "human_approval")

    def test_other_bot_approval_does_not_override_required_bot_quorum(self) -> None:
        head = "a" * 40
        for author in (
            {"login": "tessl-reviewer[bot]", "type": "Bot"},
            {"login": "another-reviewer", "type": "Bot"},
            {"login": "another-reviewer[bot]", "type": "User"},
            {"login": "reviewer"},
            {"login": 12, "type": "User"},
            {"login": "reviewer", "type": "Organization"},
            {"login": "reviewer__octo", "type": "User"},
            {"login": "reviewer_o", "type": "User"},
            {"login": "a" * 40, "type": "User"},
        ):
            for decision in ("", "APPROVED"):
                with self.subTest(author=author, decision=decision):
                    pr = {"number": 7, "reviewDecision": decision, "reviews": [
                        {"state": "APPROVED", "commit_id": head, "user": author},
                    ]}
                    with (
                        patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
                        patch.object(MODULE, "review_comments", return_value=([], None)),
                        patch.object(MODULE, "issue_comments", return_value=([], None)),
                    ):
                        result = MODULE.reviews_lane(Path.cwd(), pr, head)
                    self.assertNotEqual(result["status"], "pass")
                    self.assertEqual(result["details"].get("current_head_approvals"), [])

    def test_tessl_approval_allows_qualified_bot_quorum_evaluation(self) -> None:
        head = "a" * 40
        pr = {"number": 7, "reviewDecision": "", "reviews": [
            {"state": "APPROVED", "commit_id": head, "user": {"login": "tessl-reviewer[bot]", "type": "Bot"}},
            *[{"state": "COMMENTED", "commit_id": head, "user": {"login": login, "type": "Bot"},
               "body": f"No findings for {head}."}
              for login in ("coderabbitai[bot]", "chatgpt-codex-connector[bot]")],
        ]}
        with (
            patch.object(MODULE, "review_threads", return_value=({"unresolved_threads": 0, "truncated": False}, None)),
            patch.object(MODULE, "review_comments", return_value=([], None)),
            patch.object(MODULE, "issue_comments", return_value=([], None)),
        ):
            result = MODULE.reviews_lane(Path.cwd(), pr, head)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["details"]["review_mode"], "bot_quorum")

    def test_emitted_result_payload_has_service_identity(self) -> None:
        payload = MODULE.add_service_identity({"schema_version": MODULE.SCHEMA_VERSION, "status": "pass"})

        self.assertEqual(payload["service"], "pr-readiness")
        self.assertEqual(payload["status"], "pass")

    def test_review_reconciliation_admits_only_unresolved_thread_mutations(self) -> None:
        head = "a" * 40
        pr = {"number": 7}
        with patch.object(
            MODULE,
            "review_threads",
            return_value=(
                {
                    "unresolved_threads": 2,
                    "unresolved_thread_ids": ["PRRT_one", "PRRT_two"],
                    "truncated": False,
                },
                None,
            ),
        ):
            result = MODULE.review_reconciliation_lane(Path.cwd(), pr, head)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(
            result["details"]["allowed_mutations"],
            ["review_thread_reply", "review_thread_resolve"],
        )
        self.assertIn("source_update", result["details"]["prohibited_mutations"])
        self.assertEqual(
            result["details"]["unresolved_thread_ids"], ["PRRT_one", "PRRT_two"]
        )
        self.assertFalse(result["details"]["acceptance_claims_proven"])

    def test_command_target_must_match_receipt_repository_pr_and_thread(self) -> None:
        payload = {
            "repo": {"base_branch": "main", "branch": "codex/topic"},
            "lanes": {
                "pull_request": {"details": {"number": 7}},
                "reviews": {
                    "details": {"unresolved_thread_ids": ["PRRT_allowed"]}
                },
            }
        }

        self.assertIsNone(
            MODULE.validate_command_target(
                payload,
                repository="jscraik/configs",
                expected_repo="jscraik/configs",
                expected_pr=7,
                expected_thread_id="PRRT_allowed",
            )
        )
        self.assertIn(
            "repository target",
            MODULE.validate_command_target(
                payload,
                repository="jscraik/configs",
                expected_repo="other/repo",
                expected_pr=7,
                expected_thread_id="PRRT_allowed",
            ),
        )
        self.assertIn(
            "PR target",
            MODULE.validate_command_target(
                payload,
                repository="jscraik/configs",
                expected_repo="jscraik/configs",
                expected_pr=999,
                expected_thread_id="PRRT_allowed",
            ),
        )
        self.assertIn(
            "review-thread target",
            MODULE.validate_command_target(
                payload,
                repository="jscraik/configs",
                expected_repo="jscraik/configs",
                expected_pr=7,
                expected_thread_id="PRRT_other",
            ),
        )
        self.assertIn(
            "base target",
            MODULE.validate_command_target(
                payload,
                repository="jscraik/configs",
                expected_repo="jscraik/configs",
                expected_pr=7,
                expected_thread_id="PRRT_allowed",
                expected_base="release",
            ),
        )
        self.assertIn(
            "head target",
            MODULE.validate_command_target(
                payload,
                repository="jscraik/configs",
                expected_repo="jscraik/configs",
                expected_pr=7,
                expected_thread_id="PRRT_allowed",
                expected_head="owner:other",
            ),
        )

    def test_review_reconciliation_blocks_when_no_threads_remain(self) -> None:
        with patch.object(
            MODULE,
            "review_threads",
            return_value=({"unresolved_threads": 0, "truncated": False}, None),
        ):
            result = MODULE.review_reconciliation_lane(Path.cwd(), {"number": 7}, "a" * 40)

        self.assertEqual(result["status"], "blocked")

    def test_pending_ci_is_observed_without_granting_merge_readiness(self) -> None:
        head = "a" * 40
        pr = {"headRefOid": head, "statusCheckRollup": [
            {"name": "test", "status": "IN_PROGRESS", "conclusion": ""},
        ]}
        for phase in ("review_inspection", "review_reconciliation", "update"):
            with self.subTest(phase=phase):
                result = MODULE.phase_checks_lane(pr, head, phase)
                self.assertEqual(result["status"], "pass" if phase != "update" else "blocked")
                if phase != "update":
                    self.assertFalse(result["details"]["acceptance_claims_proven"])
                    self.assertEqual(result["details"]["ci_status"], "blocked")
        for rollup in ([], [{"name": "test", "conclusion": "FAILURE", "status": "COMPLETED"}],
                       [{"name": "test", "status": "MYSTERY"}], [None]):
            inspection = MODULE.phase_checks_lane({**pr, "statusCheckRollup": rollup}, head, "review_inspection")
            self.assertEqual(inspection["status"], "pass")
            self.assertFalse(inspection["details"]["acceptance_claims_proven"])
            for phase in ("review_reconciliation", "update"):
                self.assertNotEqual(MODULE.phase_checks_lane({**pr, "statusCheckRollup": rollup}, head, phase)["status"], "pass")
        self.assertEqual(MODULE.phase_checks_lane(pr, "b" * 40, "review_inspection")["status"], "blocked")

    def test_review_receipt_consumption_allows_pending_ci_but_rechecks_identity(self) -> None:
        head = "a" * 40
        pr = {"headRefOid": head, "number": 7, "state": "OPEN", "url": "https://github.com/o/r/pull/7",
              "statusCheckRollup": [{"name": "test", "status": "IN_PROGRESS"}]}
        for phase in ("review_inspection", "review_reconciliation"):
            with self.subTest(phase=phase), patch.object(MODULE, "gh_pr", return_value=(pr, None)), patch.object(
                MODULE, "review_reconciliation_lane", return_value={"status": "pass", "details": {"unresolved_thread_ids": ["thread"]}}
            ):
                self.assertIsNone(MODULE.recheck_hosted_state(Path.cwd(), phase, head))
                original = pr["statusCheckRollup"]
                for changed in ([{"name": "test", "status": "COMPLETED", "conclusion": "FAILURE"}],
                                [{"name": "test", "status": "MYSTERY"}],
                                original + [{"name": "other", "status": "MYSTERY"}], []):
                    pr["statusCheckRollup"] = changed
                    outcome = MODULE.recheck_hosted_state(Path.cwd(), phase, head)
                    if phase == "review_inspection":
                        self.assertIsNone(outcome)
                    else:
                        self.assertIn("hosted checks changed", outcome)
                pr["statusCheckRollup"] = original
                self.assertIn("head changed", MODULE.recheck_hosted_state(Path.cwd(), phase, "b" * 40))
                self.assertIn("target review thread", MODULE.recheck_hosted_state(Path.cwd(), "review_reconciliation", head, expected_thread_id="other"))

    def test_update_receipt_rechecks_current_hosted_checks_and_reviews(self) -> None:
        head = "a" * 40
        pr = {"headRefOid": head}
        with (
            patch.object(MODULE, "gh_pr", return_value=(pr, None)),
            patch.object(MODULE, "checks_lane", return_value={"status": "pass", "evidence": "checks pass"}),
            patch.object(MODULE, "reviews_lane", return_value={"status": "pass", "evidence": "reviews pass"}),
        ):
            error = MODULE.recheck_hosted_state(Path.cwd(), "update", head)

        self.assertIsNone(error)

    def test_update_receipt_blocks_when_hosted_base_branch_changes(self) -> None:
        head = "a" * 40
        pr = {"headRefOid": head, "baseRefName": "release", "baseRefOid": "b" * 40}
        with patch.object(MODULE, "gh_pr", return_value=(pr, None)):
            error = MODULE.recheck_hosted_state(
                Path.cwd(),
                "update",
                head,
                base_branch="main",
                base_sha="b" * 40,
            )

        self.assertEqual(
            error, "hosted PR base branch changed after the receipt was written"
        )

    def test_update_receipt_blocks_when_hosted_base_commit_changes(self) -> None:
        head = "a" * 40
        pr = {"headRefOid": head, "baseRefName": "main", "baseRefOid": "c" * 40}
        with patch.object(MODULE, "gh_pr", return_value=(pr, None)):
            error = MODULE.recheck_hosted_state(
                Path.cwd(),
                "update",
                head,
                base_branch="main",
                base_sha="b" * 40,
            )

        self.assertEqual(
            error, "hosted PR base commit changed after the receipt was written"
        )

    def test_update_receipt_blocks_when_hosted_checks_change(self) -> None:
        head = "a" * 40
        pr = {"headRefOid": head}
        with (
            patch.object(MODULE, "gh_pr", return_value=(pr, None)),
            patch.object(
                MODULE,
                "checks_lane",
                return_value={"status": "blocked", "evidence": "tests are still pending"},
            ),
        ):
            error = MODULE.recheck_hosted_state(Path.cwd(), "update", head)

        self.assertIn("hosted checks changed", error or "")

    def test_review_reconciliation_recheck_does_not_require_approval(self) -> None:
        head = "a" * 40
        pr = {"headRefOid": head, "number": 7}
        with (
            patch.object(MODULE, "gh_pr", return_value=(pr, None)),
            patch.object(MODULE, "checks_lane", return_value={"status": "pass", "evidence": "checks pass"}),
            patch.object(
                MODULE,
                "review_reconciliation_lane",
                return_value={"status": "pass", "evidence": "threads admitted"},
            ),
            patch.object(MODULE, "reviews_lane") as final_reviews,
        ):
            error = MODULE.recheck_hosted_state(Path.cwd(), "review_reconciliation", head)

        self.assertIsNone(error)
        final_reviews.assert_not_called()


def load_tests(loader, tests, pattern):
    """Include provider completion regressions in the maintained policy lane."""
    from codex.scripts.tests import (
        test_pr_coderabbit_structured,
        test_pr_codex_completion,
        test_pr_maintainer_acceptance,
        test_pr_review_request,
    )

    tests.addTests(loader.loadTestsFromModule(test_pr_codex_completion))
    tests.addTests(loader.loadTestsFromModule(test_pr_coderabbit_structured))
    tests.addTests(loader.loadTestsFromModule(test_pr_review_request))
    tests.addTests(loader.loadTestsFromModule(test_pr_maintainer_acceptance))
    return tests


class TesslReviewTests(unittest.TestCase):
    def test_known_historical_dismissed_clean_review_is_neutral_not_clearance(self):
        head, old = 'a' * 40, 'b' * 40
        body = (Path(__file__).parent / 'fixtures/tessl-name-mismatch-clean.txt').read_text().rstrip('\n')
        review = {'id': 123, 'user': {'login': 'tessl-reviewer[bot]', 'type': 'Bot', 'id': 325629464},
                  'state': 'DISMISSED', 'commit_id': old, 'submitted_at': '2026-11-10T14:12:12Z',
                  'body': body}
        self.assertEqual(MODULE.outstanding_bot_concerns([review], [], [], head), [])
        self.assertFalse(MODULE._bot_review_is_acceptable(review, head))
        self.assertFalse(MODULE._bot_review_is_acceptable({**review, 'commit_id': head}, head))
        run = '01a1c5cc-0702-711a-82c1-1a1cde72f069'
        check = {'id': 42, 'name': 'Tessl Reviewer', 'status': 'completed', 'conclusion': 'success',
                 'head_sha': head, 'app': {'id': 4850038, 'slug': 'tessl-reviewer'},
                 'details_url': 'https://tessl.io/go/code-review-runs/' + run}
        pr = {'headRefOid': head, 'tessl_check_runs': [check]}
        eligible = {**review, 'state': 'APPROVED', 'commit_id': head}
        historical = MODULE._join_tessl_review_check(eligible, pr)
        canonical_body = (Path(__file__).parent / 'fixtures/tessl-missing-description-clean.txt').read_text().rstrip('\n')
        canonical_check = {**check, 'details_url': 'https://tessl.io/go/code-review-runs/01a19712-8790-71a8-b1a7-553041dc02cf'}
        canonical = MODULE._join_tessl_review_check(
            {**eligible, 'body': canonical_body}, {**pr, 'tessl_check_runs': [canonical_check]})
        self.assertTrue(historical['tessl_check_verified'])
        self.assertTrue(MODULE._bot_review_is_acceptable(canonical, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(historical, head))
        finding = {**review, 'id': 122, 'body': 'P1: unsafe input remains',
                   'submitted_at': '2026-11-10T14:11:00Z'}
        self.assertIn('Tessl Reviewer', MODULE.outstanding_bot_concerns([finding, review], [], [], head))
        for changes in (
            {'body': body + '\nP1: unsafe input remains'},
            {'body': body.replace('findings-total=0', 'findings-total=1')},
            {'body': body.replace('No actionable concerns were supplied', 'Actionable concerns remain')},
            {'body': body + '\n<!-- tessl-code-review:result:v1 approved=true findings-total=0 findings-unplaced=0 -->'},
            {'body': body.replace('01a1c5cc-0702-711a-82c1-1a1cde72f069', 'invalid-run')},
            {'state': 'CHANGES_REQUESTED'},
            {'user': {'login': 'tessl-reviewer[bot]', 'type': 'Bot', 'id': 1}},
        ):
            with self.subTest(changes=changes):
                self.assertIn('Tessl Reviewer', MODULE.outstanding_bot_concerns([{**review, **changes}], [], [], head))

    def test_native_bot_seat_skip_is_neutral_only_as_complete_known_status(self):
        body = MODULE.CODERABBIT_BOT_SEAT_SKIP_TEMPLATE.format(
            run='39dc3fa1-06a8-4057-8713-5c0281cb4231',
            checkbox='2708ad07-9f24-4260-9c11-7dc76a49f2e3')
        self.assertTrue(MODULE._bot_response_is_only_unavailability(body, login='coderabbitai'))
        changed_ids = MODULE.CODERABBIT_BOT_SEAT_SKIP_TEMPLATE.format(
            run='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            checkbox='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')
        self.assertTrue(MODULE._bot_response_is_only_unavailability(changed_ids, login='coderabbitai'))
        for changed in (body + '\nP1: Fix unsafe input.',
                        body.replace('Review skipped', 'Review skipped; unsafe input remains'),
                        body.replace('- [ ]', '- [x]'),
                        body.replace('<!-- autopilot:end -->', ''),
                        body.replace('**Commit**: Unavailable', '**Commit**: ' + 'a' * 40),
                        body.replace('39dc3fa1-06a8-4057-8713-5c0281cb4231', 'unknown-run')):
            with self.subTest(changed=changed):
                self.assertFalse(MODULE._bot_response_is_only_unavailability(changed, login='coderabbitai'))
        self.assertFalse(MODULE._bot_response_is_only_unavailability(body, login='other'))
        head = 'a' * 40
        skip = {'user': {'login': 'coderabbitai[bot]'}, 'body': body}
        self.assertEqual(MODULE.outstanding_bot_concerns([], [], [skip], head), [])
        self.assertFalse(MODULE._bot_review_is_acceptable({**skip, 'state': 'COMMENTED', 'commit_id': head}, head))
        finding = {**skip, 'body': body + '\nP1: Fix unsafe input.'}
        self.assertIn('CodeRabbit', MODULE.outstanding_bot_concerns([], [], [finding], head))

    def test_review_lane_accepts_tessl_without_waiving_quorum_or_later_findings(self):
        head = 'a' * 40
        run = '01a19712-8790-71a8-b1a7-553041dc02cf'
        review = {'id': 123, 'user': {'login': 'tessl-reviewer[bot]', 'type': 'Bot', 'id': 325629464},
                  'state': 'APPROVED', 'commit_id': head, 'submitted_at': '2026-11-01T12:00:00Z',
                  'body': (Path(__file__).parent / 'fixtures/tessl-missing-description-clean.txt').read_text().rstrip('\n')}
        check = {'id': 42, 'name': 'Tessl Reviewer', 'status': 'completed', 'conclusion': 'success',
                 'head_sha': head, 'app': {'id': 4850038, 'slug': 'tessl-reviewer'},
                 'details_url': 'https://tessl.io/go/code-review-runs/' + run}
        pr = {'number': 114, 'headRefOid': head, 'baseRefOid': 'b' * 40,
              'reviewDecision': '', 'reviews': [review], 'tessl_check_runs': [check]}
        with (patch.object(MODULE, 'review_threads', return_value=({'unresolved_threads': 0}, None)),
              patch.object(MODULE, 'review_comments', return_value=([], None)),
              patch.object(MODULE, 'issue_comments', return_value=([], None)),
              patch.object(MODULE, 'codex_completion_review', return_value=(None, None)),
              patch.object(MODULE, 'coderabbit_completion_review', return_value=(None, None)),
              patch.object(MODULE, 'review_requirement', return_value={'required_bot_review_count': 1})):
            with self.subTest(tessl_only=True):
                self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), pr, head)['status'], 'pass')
            with patch.object(MODULE, 'review_requirement', return_value={'required_bot_review_count': 2}):
                self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), pr, head)['status'], 'pass')
            later = {**review, 'id': 124, 'state': 'CHANGES_REQUESTED',
                     'submitted_at': '2026-11-01T12:01:00Z', 'body': 'P1: missing input validation'}
            self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), {**pr, 'reviews': [review, later]}, head)['status'], 'pass')
            self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), {**pr, 'tessl_check_runs': []}, head)['status'], 'pass')
            old = {**review, 'commit_id': 'c' * 40}
            peers = [{'state': 'COMMENTED', 'commit_id': head, 'user': {'login': login},
                      'body': f'No findings for {head}.', 'submitted_at': '2026-11-01T12:01:00Z'}
                     for login in ('coderabbitai', 'chatgpt-codex-connector')]
            with patch.object(MODULE, 'review_requirement', return_value={'required_bot_review_count': 2}):
                for peer in peers:
                    with self.subTest(missing_required_peer=peer['user']['login']):
                        self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), {**pr, 'reviews': [review, peer]}, head)['status'], 'pass')
                earlier = {**review, 'id': 122, 'state': 'CHANGES_REQUESTED',
                           'submitted_at': '2026-11-01T11:59:00Z', 'body': 'P1: unsafe input remains'}
                self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), {**pr, 'reviews': [earlier, review, *peers]}, head)['status'], 'pass')
                self.assertEqual(MODULE.reviews_lane(Path.cwd(), {**pr, 'reviews': [review, *peers]}, head)['status'], 'pass')
                no_check = MODULE.reviews_lane(
                    Path.cwd(), {**pr, 'reviews': [review, *peers], 'tessl_check_runs': []}, head)
                self.assertNotEqual(no_check['status'], 'pass')
                self.assertIn('Tessl Reviewer', no_check['details']['outstanding_bot_concerns'])
                self.assertEqual(MODULE.reviews_lane(Path.cwd(), {**pr, 'reviews': [old, *peers]}, head)['status'], 'pass')
                dirty_old = {**old, 'body': old['body'] + '\nP1: Fix unsafe input validation.'}
                self.assertNotEqual(MODULE.reviews_lane(Path.cwd(), {**pr, 'reviews': [dirty_old, *peers]}, head)['status'], 'pass')
                history_run = '01a1c5cc-0702-711a-82c1-1a1cde72f069'
                history_body = (Path(__file__).parent / 'fixtures/tessl-name-mismatch-clean.txt').read_text().rstrip('\n')
                history = {**review, 'body': history_body}
                history_check = {**check, 'details_url': 'https://tessl.io/go/code-review-runs/' + history_run}
                history_pr = {**pr, 'tessl_check_runs': [history_check]}
                self.assertTrue(MODULE._join_tessl_review_check(history, history_pr)['tessl_check_verified'])
                cases = (('current historical', history, history_pr, 'fail'),
                         ('current canonical', review, pr, 'pass'),
                         ('old historical', {**history, 'commit_id': 'c' * 40}, history_pr, 'pass'),
                         ('dismissed old historical', {**history, 'state': 'DISMISSED', 'commit_id': 'c' * 40}, history_pr, 'pass'))
                for label, candidate, candidate_pr, expected in cases:
                    with self.subTest(tessl_review=label):
                        lane = MODULE.reviews_lane(Path.cwd(), {**candidate_pr, 'reviews': [candidate, *peers]}, head)
                        self.assertEqual(lane['status'], expected, lane)
                        if label == 'current historical':
                            self.assertIn('Tessl Reviewer', lane['details']['outstanding_bot_concerns'])

    def test_tessl_check_retrieval_rejects_unavailable_or_malformed_pages(self):
        head = "a" * 40
        with patch.object(MODULE, "run_command") as run:
            for invalid in (None, "a" * 12, "not-a-head"):
                self.assertIsNotNone(MODULE.tessl_check_inventory(Path.cwd(), "o/r", invalid)[1])
            run.assert_not_called()
        for status, payload in ((1, "{}"), (0, "invalid"), (0, "[]"), (0, "[null]"),
                                (0, '[{"check_runs": null}]'), (0, '[{"check_runs": [null]}]')):
            with self.subTest(status=status, payload=payload), patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], status, payload, "")):
                checks, error = MODULE.tessl_check_inventory(Path.cwd(), "o/r", head)
                self.assertEqual(checks, [])
                self.assertIsNotNone(error)
        pages = [{"check_runs": [{"id": 1}]}, {"check_runs": [{"id": 2}]}]
        with patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 0, json.dumps(pages), "")) as run:
            self.assertEqual(MODULE.tessl_check_inventory(Path.cwd(), "o/r", head, "github.example"), ([{"id": 1}, {"id": 2}], None))
            self.assertIn("--paginate", run.call_args.args[0])
            self.assertIn("--slurp", run.call_args.args[0])
            self.assertIn("github.example", run.call_args.args[0])

    def test_gh_pr_propagates_tessl_check_retrieval_failure(self):
        head = "a" * 40
        pr = {"number": 7, "headRefOid": head}
        with (patch.object(MODULE, "run_command", return_value=subprocess.CompletedProcess([], 0, json.dumps(pr), "")),
              patch.object(MODULE, "repository_slug", return_value=("o/r", None)),
              patch.object(MODULE, "review_inventory_collection", return_value=([{"user": {"login": "tessl-reviewer[bot]"}}], None)),
              patch.object(MODULE, "tessl_check_inventory", return_value=([], "check retrieval failed"))):
            self.assertEqual(MODULE.gh_pr(Path.cwd(), number=7), (None, "check retrieval failed"))

    def test_optional_tessl_cannot_supply_completed_repair_review_coverage(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from codex.scripts import pr_review_clearance, pr_review_risk
        endorsement = SimpleNamespace(MARKER="pr-repair-endorsement/v1\n",
            parse_endorsement=Mock(side_effect=AssertionError("unexpected endorsement parser")),
            verify_endorsements=Mock(side_effect=RuntimeError("required reviewers reached endorsement verification")))
        head = "a" * 40
        pr = {"number": 7, "url": "https://github.com/o/r/pull/7", "author": {"login": "author"},
              "baseRefOid": "b" * 40, "reviewDecision": ""}
        reviews = [{"user": {"login": login}, "state": "APPROVED", "commit_id": head,
                    "html_url": "https://github.com/o/r/pull/7#pullrequestreview-" + str(index),
                    "body": "Inspected current tree."}
                   for index, login in enumerate(("chatgpt-codex-connector[bot]", "tessl-reviewer[bot]"), 1)]
        with (patch.dict(sys.modules, {"pr_repair_endorsement": endorsement, "pr_review_risk": pr_review_risk,
                                            "pr_review_clearance": pr_review_clearance}),
              patch.object(MODULE, "repository_slug", return_value=("o/r", None)),
              patch.object(MODULE, "changed_file_records", return_value=[{"path": "scripts/pr-readiness.py", "old_mode": "100644", "new_mode": "100644"}]),
              patch.object(MODULE, "git", side_effect=lambda root, *args: head if args[-1].endswith("^{commit}") else "c" * 40)):
            result = MODULE.repair_endorsement_lane(Path.cwd(), pr, head, reviews, [], [], require_protected_run=False)
            endorsement.verify_endorsements.assert_not_called()
            peers = [reviews[0], {**reviews[1], "user": {"login": "coderabbitai[bot]"}}]
            try:
                positive = MODULE.repair_endorsement_lane(Path.cwd(), pr, head, peers, [], [], require_protected_run=False)
            except RuntimeError as error:
                self.assertIn("required reviewers reached", str(error))
            else:
                self.fail(str(positive))
        self.assertEqual(result["evidence"], "completed independent review coverage is missing", result)
        self.assertEqual(result["details"]["completed_reviewers"], ["chatgpt-codex-connector"])

    def test_native_review_requires_identity_head_zero_findings_and_completed_check(self):
        head = 'a' * 40
        run = '01a19712-8790-71a8-b1a7-553041dc02cf'
        body = (Path(__file__).parent / 'fixtures/tessl-missing-description-clean.txt').read_text().rstrip('\n')
        review = {'id': 123, 'user': {'login': 'tessl-reviewer[bot]', 'type': 'Bot', 'id': 325629464},
                  'state': 'APPROVED', 'commit_id': head, 'body': body}
        check = {'id': 42, 'name': 'Tessl Reviewer', 'status': 'completed', 'conclusion': 'success',
                 'head_sha': head, 'app': {'id': 4850038, 'slug': 'tessl-reviewer'},
                 'details_url': 'https://tessl.io/go/code-review-runs/' + run}
        joined = MODULE._join_tessl_review_check(review, {'headRefOid': head, 'tessl_check_runs': [check]})
        self.assertTrue(MODULE._bot_review_is_acceptable(joined, head))
        for changes in ({'commit_id': 'b' * 40}, {'state': 'COMMENTED'}, {'state': 'CHANGES_REQUESTED'},
                        {'body': body.replace('findings-total=0', 'findings-total=1')},
                        {'body': body.replace('findings-unplaced=0', 'findings-unplaced=1')},
                        {'body': body + '\n<!-- tessl-code-review:result:v1 approved=true findings-total=0 findings-unplaced=0 -->'},
                        {'body': 'No findings for ' + head + '.'},
                        {'body': body + '\nP1: Fix unsafe input validation.'},
                        {'user': {'login': 'tessl-reviewer[bot]', 'type': 'User', 'id': 325629464}},
                        {'user': {'login': 'tessl-reviewer[bot]', 'type': 'Bot', 'id': 1}}):
            with self.subTest(changes=changes):
                self.assertFalse(MODULE._bot_review_is_acceptable({**joined, **changes}, head))
        for changes in ({'conclusion': 'failure'}, {'status': 'in_progress'}, {'conclusion': 'skipped'},
                        {'head_sha': 'b' * 40}, {'app': {'id': 1, 'slug': 'tessl-reviewer'}},
                        {'app': {'id': 4850038, 'slug': 'other'}}, {'id': True},
                        {'details_url': check['details_url'] + '-other'}):
            candidate = MODULE._join_tessl_review_check(review, {'headRefOid': head, 'tessl_check_runs': [{**check, **changes}]})
            self.assertFalse(MODULE._bot_review_is_acceptable(candidate, head))
        for checks in ([], [check, check]):
            candidate = MODULE._join_tessl_review_check(review, {'headRefOid': head, 'tessl_check_runs': checks})
            self.assertFalse(MODULE._bot_review_is_acceptable(candidate, head))
        self.assertFalse(MODULE._bot_review_is_acceptable(review, head))

    def test_known_skip_is_neutral_but_added_findings_are_not(self):
        body = ('<!-- coderabbit-ai-generated:v1 -->\n\n'
                '<!-- This is an auto-generated reply by CodeRabbit -->\n'
                '<!-- CodeRabbit review command invocation: v2:' + 'a' * 64 + ' -->\n'
                '<details>\n<summary>Action not completed</summary>\n<dl>\n<dd>\n\n'
                'Review skipped.\n\n</dd>\n</dl>\n</details>\n')
        self.assertTrue(MODULE._bot_response_is_only_unavailability(body, login='coderabbitai'))
        self.assertFalse(MODULE._bot_response_is_only_unavailability(body + 'P1: unsafe input', login='coderabbitai'))
        self.assertFalse(MODULE._bot_response_is_only_unavailability(body, login='other'))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
