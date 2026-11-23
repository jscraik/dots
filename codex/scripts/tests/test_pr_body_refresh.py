from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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


MODULE_PATH = Path(__file__).resolve().parents[1] / "pr-body-refresh.py"
SPEC = importlib.util.spec_from_file_location("pr_body_refresh", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load PR body refresh helper from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrBodyRefreshTests(unittest.TestCase):
    def _write_template_and_body(
        self,
        *,
        body: str,
        template_text: str = "## Problem\n\n- Summary:\n\n## Testing\n\n- Evidence:\n",
    ) -> tuple[Path, Path, Path]:
        temporary = tempfile.TemporaryDirectory(prefix="pr-body-refresh-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        template = root / ".github" / "PULL_REQUEST_TEMPLATE.md"
        _fixture_resource(template.parent).mkdir(parents=True)
        _fixture_resource(template).write_text(template_text, encoding="utf-8")
        body_path = root / "description.md"
        _fixture_resource(body_path).write_text(body, encoding="utf-8")
        return (root, template, body_path)

    def test_accepts_a_positive_pr_number_and_owner_name_slug(self) -> None:
        self.assertEqual(MODULE.parse_pr_number("357"), 357)
        self.assertEqual(MODULE.parse_repo_slug("jscraik/configs"), "jscraik/configs")

    def test_rejects_unsafe_pr_number_and_repository_slug(self) -> None:
        self.assertRaises(ValueError, MODULE.parse_pr_number, "0")
        self.assertRaises(ValueError, MODULE.parse_pr_number, "357;gh")
        self.assertRaises(ValueError, MODULE.parse_repo_slug, "jscraik/configs/extra")
        self.assertRaises(ValueError, MODULE.parse_repo_slug, "jscraik configs")

    def test_receipt_validation_receives_the_explicit_mutation_target(self) -> None:
        root, _template, _body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n\n## Testing\n\n- Evidence: unit test\n"
        )
        with patch.object(
            MODULE,
            "run_command",
            return_value=MODULE.subprocess.CompletedProcess(
                [], 0, '{"status":"pass"}', ""
            ),
        ) as command:
            payload = MODULE.receipt_for_current_pr(
                root, 357, "jscraik/configs"
            )

        self.assertEqual(payload, {"status": "pass"})
        self.assertEqual(
            command.call_args.args[0],
            [
                MODULE.sys.executable,
                str(MODULE_PATH.with_name("pr-readiness.py")),
                "--phase",
                "update",
                "--repo-root",
                str(root),
                "--check-receipt",
                "--expected-pr",
                "357",
                "--expected-repo",
                "jscraik/configs",
                "--json",
            ],
        )

    def test_rejects_a_body_that_omits_a_required_template_section(self) -> None:
        _root, template, body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n"
        )
        self.assertEqual(
            MODULE.missing_template_sections(template, body_path), ["Testing"]
        )

    def test_accepts_a_body_with_every_required_template_section(self) -> None:
        _root, template, body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n\n## Testing\n\n- Evidence: unit test\n- Command: `python3 -m unittest` -> pass\n"
        )
        self.assertEqual(MODULE.missing_template_sections(template, body_path), [])

    def test_ignores_headings_and_fields_inside_fenced_markdown(self) -> None:
        template_text = (
            "## Problem\n\n- Summary:\n\n## Validation\n\n- Regression coverage:\n"
        )
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Problem\n\n- Summary: retained\n\n```markdown\n## Fake section\n- Summary: fake\n```\n\n## Validation\n\n- Regression coverage: fixture\n",
        )
        self.assertEqual(MODULE.missing_template_sections(template, body_path), [])
        self.assertEqual(MODULE.missing_template_fields(template, body_path), [])

    def test_accepts_checked_template_fields(self) -> None:
        _root, template, body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n\n## Testing\n\n- Evidence: unit test\n- Command: `python3 -m unittest` -> pass\n"
        )
        _fixture_resource(template).write_text(
            "## Problem\n\n- [ ] Summary:\n\n## Testing\n\n- [ ] Evidence:\n",
            encoding="utf-8",
        )
        _fixture_resource(body_path).write_text(
            "## Problem\n\n- [x] Summary: retained\n\n## Testing\n\n- [x] Evidence: unit test\n",
            encoding="utf-8",
        )
        self.assertEqual(MODULE.missing_template_fields(template, body_path), [])

    def test_rejects_a_template_field_without_a_concrete_value(self) -> None:
        _root, template, body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary:\n\n## Testing\n\n- Evidence: unit test\n"
        )
        self.assertEqual(
            MODULE.missing_template_fields(template, body_path), ["Summary"]
        )

    def test_scopes_duplicate_field_labels_to_their_sections(self) -> None:
        template_text = "## Release boundary\n\n- Deferred work:\n\n## Change details\n\n- Deferred work:\n"
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Release boundary\n\n- Deferred work: none with reason\n\n## Change details\n\n- Deferred work:\n",
        )
        self.assertEqual(
            MODULE.missing_template_fields(template, body_path),
            ["Change details: Deferred work"],
        )

    def test_rejects_a_literal_template_placeholder_value(self) -> None:
        template_text = "## Release boundary\n\n- Release mode: Prototype / Portfolio / Product / Harness / n.a. because reason\n"
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Release boundary\n\n- Release mode: Prototype / Portfolio / Product / Harness / n.a. because reason\n",
        )
        self.assertEqual(
            MODULE.missing_template_fields(template, body_path), ["Release mode"]
        )

    def test_preserves_checklist_text_when_the_item_is_checked(self) -> None:
        template_text = (
            "## Checklist\n\n- [ ] Required local gates run: fill in the command list\n"
        )
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Checklist\n\n- [x] Required local gates run: fill in the command list\n",
        )
        self.assertEqual(MODULE.missing_template_fields(template, body_path), [])

    def test_testing_requires_command_evidence_and_accepts_contract_shape(self) -> None:
        template_text = "## Testing\n\n- Regression coverage:\n"
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Testing\n\n- Regression coverage: fixture\n",
        )
        self.assertEqual(
            MODULE.validation_command_errors(template, body_path),
            ["Testing section must include at least one Command evidence line."],
        )
        _fixture_resource(body_path).write_text(
            "## Testing\n\n- Regression coverage: fixture\n- Command: `python3 -m unittest` -> pass\n",
            encoding="utf-8",
        )
        self.assertEqual(MODULE.validation_command_errors(template, body_path), [])

    def test_shared_evidence_section_requires_truthful_command_outcome(self) -> None:
        template_text = (
            "## Summary\n\n## Impact and risk\n\n## Evidence\n\n"
            "- **Validation:** <!-- Give exact commands and outcomes. -->\n\n"
            "## Reviewer focus\n\n## Readiness\n"
        )
        for evidence, accepted in (
            ("- Command: `python -m unittest` -> not run (preservation checkpoint)", True),
            ("- Command: `python -m unittest` -> not run", False),
            ("- **Validation:** Command: `python -m unittest` -> pass", True),
            ("- **Validation:**\n  - Command: `python -m unittest` -> pass", True),
            (
                "- **Validation:** Command: `python -m unittest` -> blocked ()\n"
                "- Command: `ruff check .` -> pass",
                False,
            ),
            ("- **Validation:** tests passed", False),
            ("- Behaviour: supplied claim only", False),
        ):
            with self.subTest(evidence=evidence):
                _root, template, body_path = self._write_template_and_body(
                    template_text=template_text,
                    body="## Summary\n\n## Impact and risk\n\n## Evidence\n"
                    + evidence
                    + "\n\n## Reviewer focus\n\n## Readiness\n",
                )
                self.assertEqual(
                    MODULE.validation_command_errors(template, body_path) == [], accepted
                )

    def test_rejects_placeholder_command_without_echoing_body_text(self) -> None:
        template_text = "## Testing\n\n- Regression coverage:\n"
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Testing\n\n- Regression coverage: fixture\n- Command: `<TOKEN value=secret>` -> pass\n",
        )
        errors = MODULE.validation_command_errors(template, body_path)
        self.assertEqual(
            errors, ["Command evidence has invalid format at testing line 1."]
        )
        self.assertNotIn("secret", " ".join(errors))

    def test_accepts_nested_parentheses_in_outcome_reasons(self) -> None:
        template_text = "## Testing\n\n- Regression coverage:\n"
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Testing\n\n- Regression coverage: fixture\n- Command: `pnpm test` -> pass (18 passed (2 skipped))\n- Command: `pnpm install` -> blocked (dependency missing (pnpm))\n",
        )
        self.assertEqual(MODULE.validation_command_errors(template, body_path), [])

    def test_requires_nonempty_reasons_only_for_unrun_commands(self) -> None:
        template_text = "## Testing\n\n- Regression coverage:\n"
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Testing\n\n- Regression coverage: fixture\n- Command: `pnpm test` -> n.a.\n",
        )
        error = ["Command evidence has invalid format at testing line 1."]
        for status in ("blocked", "not run", "n.a.", "n/a", "pass", "fail"):
            for reason, nonempty in (
                ("", False),
                (" ()", False),
                (" ( \t ).", False),
                (" (no package manifest)", True),
            ):
                with self.subTest(status=status, reason=reason):
                    _fixture_resource(body_path).write_text(
                        f"## Testing\n\n- Command: `pnpm test` -> {status}{reason}\n",
                        encoding="utf-8",
                    )
                    expected = [] if status in ("pass", "fail") or nonempty else error
                    self.assertEqual(
                        MODULE.validation_command_errors(template, body_path), expected
                    )

    def test_comment_guidance_does_not_supply_a_required_field(self) -> None:
        template_text = "## Change details\n\n- Deferred work:\n<!-- - Deferred work: guidance only -->\n"
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Change details\n\n<!-- - Deferred work: guidance only -->\n- Deferred work:\n",
        )
        self.assertEqual(
            MODULE.missing_template_fields(template, body_path), ["Deferred work"]
        )

    def test_allows_blank_fields_below_the_conditional_evidence_marker(self) -> None:
        template_text = "## Change details\n\n- Completed work:\n\n<!-- Complete the following fields only when their admission conditions apply. -->\n- Pattern scope inventory:\n"
        _root, template, body_path = self._write_template_and_body(
            template_text=template_text,
            body="## Change details\n\n- Completed work: updated validator\n- Pattern scope inventory:\n",
        )
        self.assertEqual(MODULE.missing_template_fields(template, body_path), [])

    def test_build_edit_command_has_only_the_body_file_mutation(self) -> None:
        command = MODULE.build_edit_command(
            357, "jscraik/configs", Path("/private/tmp/pr357.md")
        )
        self.assertEqual(
            command,
            [
                "gh",
                "pr",
                "edit",
                "357",
                "--repo",
                "jscraik/configs",
                "--body-file",
                "/private/tmp/pr357.md",
            ],
        )

    def test_rejects_any_pr_metadata_flag_outside_the_fixed_interface(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _fixture_args(
                MODULE.parse_args(
                    [
                        "--pr",
                        "357",
                        "--repo",
                        "jscraik/configs",
                        "--body-file",
                        "/private/tmp/pr357.md",
                        "--title",
                        "unsafe",
                    ]
                )
            )

    def test_template_free_repair_requires_verified_absence_and_retains_identity(
        self,
    ) -> None:
        root, template, body = self._write_template_and_body(
            body="Verified validation evidence."
        )
        _fixture_resource(template).unlink()
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(body),
                    "--repo-root",
                    str(root),
                    "--repair",
                    "--dry-run",
                ]
            )
        )
        for tracked, expected in (
            ("README.md\x00", None),
            (".github/PULL_REQUEST_TEMPLATE.md\x00", "template"),
            ("docs/pull_request_template.md\x00", "template"),
            (".github/pull_request_template.txt\x00", "template"),
        ):
            with (
                self.subTest(tracked=tracked),
                patch.object(
                    MODULE,
                    "run_command",
                    return_value=MODULE.subprocess.CompletedProcess([], 0, tracked, ""),
                ),
                patch.object(
                    MODULE,
                    "repair_preflight_for_current_pr",
                    return_value={"mode": "metadata_repair"},
                ),
                patch.object(
                    MODULE,
                    "current_repository_slug",
                    return_value="other/repo"
                    if expected is None
                    else "jscraik/configs",
                ),
                self.assertRaisesRegex(MODULE.RefreshBlocked, expected or "repository"),
            ):
                MODULE.execute(args)
        with (
            patch.object(
                MODULE,
                "run_command",
                return_value=MODULE.subprocess.CompletedProcess(
                    [], 0, "README.md\x00", ""
                ),
            ),
            patch.object(
                MODULE,
                "repair_preflight_for_current_pr",
                return_value={"mode": "metadata_repair"},
            ),
            patch.object(
                MODULE, "current_repository_slug", return_value="jscraik/configs"
            ),
        ):
            self.assertEqual(MODULE.execute(args)["template_sections"], [])
        args.repair = False
        with self.assertRaisesRegex(MODULE.RefreshBlocked, "explicit metadata repair"):
            MODULE.execute(args)

    def test_template_free_invalid_utf8_returns_structured_block(self) -> None:
        root, template, body = self._write_template_and_body(body="evidence")
        _fixture_resource(template).unlink()
        _fixture_resource(body).write_bytes(b"\xff")
        with (
            patch.object(
                MODULE,
                "run_command",
                return_value=MODULE.subprocess.CompletedProcess(
                    [], 0, "README.md\x00", ""
                ),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = MODULE.main(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(body),
                    "--repo-root",
                    str(root),
                    "--repair",
                    "--dry-run",
                ]
            )
        self.assertEqual(result, 2)
        self.assertIn('"status": "blocked"', output.getvalue())

    def test_subdirectory_cannot_hide_tracked_repository_template(self) -> None:
        root, _template, body = self._write_template_and_body(
            body="missing required sections"
        )
        import subprocess

        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=root,
            check=True,
        )
        directory = root / "src"
        _fixture_resource(directory).mkdir()
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(body),
                    "--repo-root",
                    str(directory),
                    "--repair",
                    "--dry-run",
                ]
            )
        )
        with self.assertRaisesRegex(MODULE.RefreshBlocked, "template exists in HEAD"):
            MODULE.execute(args)

    def test_body_symlink_is_rejected_before_any_hosted_operation(self) -> None:
        root, _template, body = self._write_template_and_body(body="private fixture")
        link = root / "linked.md"
        link.symlink_to(body)
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(link),
                    "--repo-root",
                    str(root),
                    "--repair",
                    "--dry-run",
                ]
            )
        )
        with (
            patch.object(MODULE, "run_command") as command,
            self.assertRaisesRegex(MODULE.RefreshBlocked, "symlink"),
        ):
            MODULE.execute(args)
        command.assert_not_called()

    def test_parent_traversal_is_rejected_before_open_or_hosted_operation(self) -> None:
        root, _template, body = self._write_template_and_body(body="private fixture")
        _fixture_resource(root / "nested").mkdir()
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(root / "nested" / ".." / body.name),
                    "--repo-root",
                    str(root),
                    "--repair",
                    "--dry-run",
                ]
            )
        )
        with (
            patch.object(MODULE.os, "open") as opened,
            patch.object(MODULE, "run_command") as command,
            self.assertRaisesRegex(MODULE.RefreshBlocked, "parent-directory traversal"),
        ):
            MODULE.execute(args)
        opened.assert_not_called()
        command.assert_not_called()

    def test_parent_symlink_is_rejected_before_hosted_operation(self) -> None:
        root, _template, body = self._write_template_and_body(body="private fixture")
        (root / "repair-files").symlink_to(root, target_is_directory=True)
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(root / "repair-files" / body.name),
                    "--repo-root",
                    str(root),
                    "--repair",
                    "--dry-run",
                ]
            )
        )
        with (
            patch.object(MODULE, "run_command") as command,
            self.assertRaisesRegex(MODULE.RefreshBlocked, "symlink"),
        ):
            MODULE.execute(args)
        command.assert_not_called()

    def test_validated_snapshot_does_not_follow_later_body_replacement(self) -> None:
        root, _template, body = self._write_template_and_body(body="approved evidence")
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(body),
                    "--repo-root",
                    str(root),
                    "--repair",
                ]
            )
        )

        def consume(snapshot_args):
            _fixture_resource(body).write_text("replacement bytes")
            self.assertEqual(
                _fixture_resource(snapshot_args.body_file).read_text(),
                "approved evidence",
            )
            self.assertNotEqual(snapshot_args.body_file, body)
            return {"status": "pass"}

        with patch.object(MODULE, "_execute_snapshot", side_effect=consume):
            self.assertEqual(MODULE.execute(args)["status"], "pass")

    def test_repair_does_not_consume_update_receipt(self) -> None:
        root, _template, body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n\n## Testing\n\n- Evidence: unit test\n- Command: `python3 -m unittest` -> pass\n"
        )
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(body_path),
                    "--repo-root",
                    str(root),
                    "--repair",
                    "--dry-run",
                ]
            )
        )
        with (
            patch.object(
                MODULE,
                "repair_preflight_for_current_pr",
                return_value={"mode": "metadata_repair", "pr": 357, "head_sha": "abc"},
            ),
            patch.object(
                MODULE, "current_repository_slug", return_value="jscraik/configs"
            ),
            patch.object(
                MODULE,
                "receipt_for_current_pr",
                side_effect=AssertionError("repair must not consume update receipt"),
            ),
        ):
            result = MODULE.execute(args)
        self.assertEqual(result["mode"], "metadata_repair")

    def test_repair_preflight_rejects_a_stale_local_head(self) -> None:
        root, _template, body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n\n## Testing\n\n- Evidence: unit test\n- Command: `python3 -m unittest` -> pass\n"
        )
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(body_path),
                    "--repo-root",
                    str(root),
                    "--repair",
                ]
            )
        )
        with (
            patch.object(
                MODULE,
                "run_command",
                side_effect=[
                    MODULE.subprocess.CompletedProcess(
                        [],
                        0,
                        '{"number":357,"headRefOid":"remote","state":"OPEN","isDraft":false}',
                        "",
                    ),
                    MODULE.subprocess.CompletedProcess([], 0, "local\n", ""),
                ],
            ),
            self.assertRaisesRegex(MODULE.RefreshBlocked, "local HEAD"),
        ):
            MODULE.execute(args)

    def test_repair_preflight_accepts_a_current_head_draft(self) -> None:
        root, _template, _body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n\n## Testing\n\n- Evidence: unit test\n"
        )
        with patch.object(
            MODULE,
            "run_command",
            side_effect=[
                MODULE.subprocess.CompletedProcess(
                    [],
                    0,
                    '{"number":357,"headRefOid":"current","state":"OPEN","isDraft":true}',
                    "",
                ),
                MODULE.subprocess.CompletedProcess([], 0, "current\n", ""),
            ],
        ):
            result = MODULE.repair_preflight_for_current_pr(root, 357)
        self.assertEqual(
            result, {"mode": "metadata_repair", "pr": 357, "head_sha": "current"}
        )

    def test_receipt_bound_pr_number_mismatch_stops_before_a_hosted_edit(self) -> None:
        root, _template, body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n\n## Testing\n\n- Evidence: unit test\n- Command: `python3 -m unittest` -> pass\n"
        )
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(body_path),
                    "--repo-root",
                    str(root),
                ]
            )
        )
        receipt = {
            "status": "pass",
            "lanes": {"pull_request": {"details": {"number": 358}}},
        }
        with (
            patch.object(MODULE, "receipt_for_current_pr", return_value=receipt),
            patch.object(MODULE, "current_repository_slug") as repository_slug,
            patch.object(MODULE, "run_command") as run_command,
            self.assertRaisesRegex(MODULE.RefreshBlocked, "does not match"),
        ):
            MODULE.execute(args)
        repository_slug.assert_not_called()
        run_command.assert_not_called()

    def test_dry_run_proves_the_fixed_path_without_a_hosted_mutation(self) -> None:
        root, _template, body_path = self._write_template_and_body(
            body="## Problem\n\n- Summary: retained\n\n## Testing\n\n- Evidence: unit test\n- Command: `python3 -m unittest` -> pass\n"
        )
        args = _fixture_args(
            MODULE.parse_args(
                [
                    "--pr",
                    "357",
                    "--repo",
                    "jscraik/configs",
                    "--body-file",
                    str(body_path),
                    "--repo-root",
                    str(root),
                    "--dry-run",
                ]
            )
        )
        receipt = {
            "status": "pass",
            "lanes": {"pull_request": {"details": {"number": 357}}},
        }
        with (
            patch.object(MODULE, "receipt_for_current_pr", return_value=receipt),
            patch.object(
                MODULE, "current_repository_slug", return_value="jscraik/configs"
            ),
            patch.object(MODULE, "run_command") as run_command,
        ):
            result = MODULE.execute(args)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["action"], "dry_run")
        run_command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
