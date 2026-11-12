from __future__ import annotations

import json
import unittest


class MaintainerAcceptanceFixture:
    def setUp(self) -> None:
        from codex.scripts import pr_maintainer_acceptance as acceptance
        self.api = acceptance
        self.head, self.base = "a" * 40, "b" * 40
        self.identity = {"repository": "jscraik/configs", "pr_number": 7, "head_sha": self.head, "base_sha": self.base}
        self.report = dict(schema_version=acceptance.REPORT.rstrip(), **self.identity,
                           writer_task="/root", reviewer_task="/root/reviewer",
                           covered_paths=["codex/scripts/guard.py"], unresolved_findings=[],
                           conclusion="no_remaining_findings", reviewer_kind="separate_read_only_agent",
                           review_summary="Inspected the complete diff and existing findings; static review only.")
        self.entries = [self.entry(1, "You have reached your Codex usage limits for code reviews. "
                                   "You can see your limits in the [Codex usage dashboard]"
                                   "(https://chatgpt.com/codex/cloud/settings/usage).",
                                   login="chatgpt-codex-connector[bot]", kind="Bot"),
                        self.entry(2, acceptance.REPORT + json.dumps(self.report))]
        self.acceptance = dict(schema_version=acceptance.ACCEPT.rstrip(), **self.identity,
                               report_url=self.entries[1]["html_url"],
                               report_sha256=acceptance.body_digest(self.entries[1]),
                               outage_url=self.entries[0]["html_url"],
                               outage_sha256=acceptance.body_digest(self.entries[0]),
                               independence_verified=True, accepted=True)
        self.entries.append(self.entry(3, acceptance.ACCEPT + json.dumps(self.acceptance)))

    @staticmethod
    def entry(number: int, body: str, login: str = "jscraik", kind: str = "User") -> dict:
        return {"id": number, "html_url": f"https://github.com/jscraik/configs/pull/7#issuecomment-{number}",
                    "body": body, "user": {"login": login, "type": kind},
                    "created_at": f"2026-10-11T18:00:0{number}Z", "updated_at": f"2026-10-11T18:00:0{number}Z"}

    def verify(self) -> dict | None:
        return self.api.verify_acceptance(entries=self.entries, outages=[self.entries[0]], number=7,
                                          head=self.head, base=self.base, paths=["codex/scripts/guard.py"],
                                          head_time="2026-10-11T18:00:00Z")


class MaintainerAcceptanceTests(MaintainerAcceptanceFixture, unittest.TestCase):
    def test_exact_report_and_personal_acceptance_pass(self) -> None:
        result = self.verify()
        self.assertEqual(result["review_mode"], "maintainer_accepted_independent_report")
        self.assertEqual(result["independence_basis"], "personal maintainer attestation")
        self.assertEqual(result["head_sha"], self.head)

    def test_report_alone_is_never_acceptance(self) -> None:
        self.entries.pop()
        self.assertIsNone(self.verify())

    def test_deleted_or_invalid_users_cannot_supply_acceptance(self) -> None:
        for user in (None, [], "jscraik", 42):
            with self.subTest(user=user):
                self.setUp()
                ghost = self.entry(4, self.api.ACCEPT + "not-json")
                ghost["user"] = user
                self.entries.append(ghost)
                self.assertIsNotNone(self.verify())
                self.entries[2]["user"] = user
                self.assertIsNone(self.verify())

    def test_source_edit_times_cannot_postdate_the_accepted_evidence(self) -> None:
        for index, stamp in ((0, "2026-10-11T18:00:04Z"), (1, "2026-10-11T18:00:04Z"),
                             (0, "2026-10-11T18:00:02Z"), (1, "2026-10-11T18:00:03Z"),
                             (0, "invalid"), (1, None), (2, "2026-10-11T18:00:02Z")):
            with self.subTest(index=index, stamp=stamp):
                self.setUp()
                self.entries[index]["updated_at"] = stamp
                if index in (0, 1):
                    self.entries[index]["body"] += " "
                    key = "outage_sha256" if index == 0 else "report_sha256"
                    self.acceptance[key] = self.api.body_digest(self.entries[index])
                    self.entries[2]["body"] = self.api.ACCEPT + json.dumps(self.acceptance)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_source_edits_before_the_next_record_are_valid(self) -> None:
        self.entries[0]["updated_at"] = "2026-10-11T18:00:01.500Z"
        self.entries[1]["updated_at"] = "2026-10-11T18:00:02.500Z"
        self.assertIsNotNone(self.verify())

    def test_obsolete_base_acceptance_does_not_block_current_candidate(self) -> None:
        old = {**self.acceptance, "base_sha": "c" * 40}
        self.entries.append(self.entry(4, self.api.ACCEPT + json.dumps(old)))
        self.assertIsNotNone(self.verify())

    def test_changed_sources_and_forged_or_ambiguous_acceptance_fail(self) -> None:
        changes = [lambda: self.entries[1].update(body=self.entries[1]["body"] + " "),
                   lambda: self.entries[0].update(body="No findings"),
                   lambda: self.entries.append(dict(self.entries[2])),
                   lambda: self.entries[1].update(html_url="https://github.com/foreign/repo/pull/7#issuecomment-2"),
                   lambda: self.entries[0].update(created_at="2026-10-10T18:00:01Z"),
                   lambda: self.entries[2].update(created_at="2026-10-11T18:00:01Z")]
        for change in changes:
            self.setUp()
            change()
            with self.assertRaises(ValueError):
                self.verify()

    def test_foreign_markers_cannot_supply_or_block_acceptance(self) -> None:
        for body in (self.api.ACCEPT + "not-json", self.entries[2]["body"]):
            self.setUp()
            self.entries.append(self.entry(4, body, login="other-owner"))
            self.assertIsNotNone(self.verify())
        for user in ({"login": "other-owner", "type": "User"}, {"login": "jscraik", "type": "Bot"}):
            self.setUp()
            self.entries[2]["user"] = user
            self.assertIsNone(self.verify())
        self.setUp()
        self.entries.append(self.entry(4, self.api.ACCEPT + "not-json"))
        with self.assertRaises(ValueError):
            self.verify()

    def test_candidate_and_review_attestation_controls(self) -> None:
        for key, value in (("head_sha", "c" * 40), ("base_sha", "c" * 40), ("pr_number", True),
                           ("repository", "foreign/repo"), ("independence_verified", "true"),
                           ("accepted", False), ("schema_version", "unknown")):
            self.setUp()
            self.acceptance[key] = value
            self.entries[2]["body"] = self.api.ACCEPT + json.dumps(self.acceptance)
            with self.assertRaises(ValueError):
                self.verify()
        for key, value in (("writer_task", " /root/reviewer "), ("reviewer_task", ""),
                           ("covered_paths", []), ("covered_paths", ["codex/scripts/guard.py"] * 2),
                           ("unresolved_findings", ["P1"]), ("conclusion", "quota exceeded"),
                           ("review_summary", ""), ("head_sha", "c" * 40)):
            self.setUp()
            self.report[key] = value
            self.entries[1]["body"] = self.api.REPORT + json.dumps(self.report)
            self.acceptance["report_sha256"] = self.api.body_digest(self.entries[1])
            self.entries[2]["body"] = self.api.ACCEPT + json.dumps(self.acceptance)
            with self.assertRaises(ValueError):
                self.verify()



if __name__ == "__main__":
    unittest.main()
