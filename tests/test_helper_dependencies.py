"""Exercise migrated helpers, missing-input denial and isolation with accepted tests."""

import json
import os
import pwd
import subprocess
import tempfile
import unittest
from pathlib import Path

from helper_fixture import HelperFixture


class HelperDependencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = HelperFixture(self)

    def test_git_reported_metadata_cannot_probe_outside_the_fixture(self):
        fixture = self.fixture
        with tempfile.TemporaryDirectory(dir=Path("/tmp").resolve()) as outside:
            repository = Path(outside) / "repository"
            repository.mkdir()
            (repository / "tracked.txt").write_text("synthetic metadata fixture\n")
            for arguments in (
                ["init", "-q", str(repository)],
                ["-C", str(repository), "add", "tracked.txt"],
                [
                    "-C",
                    str(repository),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "synthetic baseline",
                ],
                [
                    "-C",
                    str(repository),
                    "worktree",
                    "add",
                    "--detach",
                    "-q",
                    str(fixture.home / "linked-worktree"),
                    "HEAD",
                ],
            ):
                subprocess.run(
                    ["git", *arguments],
                    env=fixture.env,
                    check=True,
                    text=True,
                    capture_output=True,
                    timeout=20,
                )
            result = fixture.helper(
                "git-metadata-preflight.py",
                "--repo-root",
                str(fixture.home / "linked-worktree"),
                "--json",
            )
            probes = list(Path(outside).rglob(".git-metadata-preflight.*"))
            self.assertEqual(
                probes,
                [],
                "Git-reported paths must be admitted before creating any probe",
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("disposable home", result.stdout + result.stderr)
            self.assertEqual(
                (repository / "tracked.txt").read_text(), "synthetic metadata fixture\n"
            )
        fixture.assert_preserved(self)

    def test_hosted_helpers_reject_inherited_auth_before_calling_the_cli(self):
        fixture = self.fixture
        marker = fixture.home / "gh-called.txt"
        fake_gh = fixture.bin / "gh"
        fake_gh.write_text('#!/bin/sh\nprintf called >> "$DOTS_GH_CALL_LOG"\nexit 1\n')
        fake_gh.chmod(0o755)
        recording = {"DOTS_GH_CALL_LOG": str(marker)}
        result = fixture.helper("check-branch-pr-truth.py", extra_env=recording)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            marker.exists(),
            "The recording fixture CLI must be reachable for the valid control",
        )
        scope = fixture.home / "scope.txt"
        scope.write_text("README.md\n")
        with tempfile.TemporaryDirectory(dir=Path("/tmp").resolve()) as outside:
            for script, arguments, extra in (
                ("check-branch-pr-truth.py", [], {"GH_CONFIG_DIR": outside}),
                (
                    "check-branch-pr-truth.py",
                    [],
                    {"GH_ENTERPRISE_TOKEN": "synthetic-denial-probe"},
                ),
                (
                    "check-branch-pr-truth.py",
                    [],
                    {"GITHUB_ENTERPRISE_TOKEN": "synthetic-denial-probe"},
                ),
                (
                    "pr-readiness.py",
                    ["--phase", "create", "--scope-file", str(scope)],
                    {"GH_TOKEN": "synthetic-denial-probe"},
                ),
            ):
                with self.subTest(script=script, extra=tuple(extra)):
                    marker.unlink(missing_ok=True)
                    result = fixture.helper(
                        script, *arguments, extra_env=recording | extra
                    )
                    self.assertFalse(
                        marker.exists(), "Inherited authentication reached a hosted CLI"
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertRegex(
                        result.stdout + result.stderr, "credentials|disposable home"
                    )
        fixture.assert_preserved(self)

    def test_pure_validator_and_report_entrypoints(self):
        fixture = self.fixture
        for name, arguments in (
            ("workflow-closeout.py", ["--validate-sample"]),
            ("check-evidence-freshness.py", ["--self-test"]),
            ("select-validation-for-changes.py", ["--self-test", "--json"]),
            ("validate-agent-governance.py", []),
            ("validate-agent-artifacts.py", []),
            ("validate-auto-review-scope.sh", []),
        ):
            with self.subTest(name=name):
                result = fixture.helper(name, *arguments)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fixture.assert_preserved(self)

    def test_github_auth_store_symlinks_cannot_reconnect_outside_credentials(self):
        fixture = self.fixture
        marker = fixture.home / "gh-auth-store-called.txt"
        fake_gh = fixture.bin / "gh"
        fake_gh.write_text('#!/bin/sh\nprintf called >> "$DOTS_GH_CALL_LOG"\nexit 1\n')
        fake_gh.chmod(0o755)
        inside = fixture.home / "synthetic-gh-config"
        inside.mkdir()
        default = fixture.home / ".config/gh"
        default.parent.mkdir(exist_ok=True)
        recording = {"DOTS_GH_CALL_LOG": str(marker)}
        result = fixture.helper(
            "check-branch-pr-truth.py",
            extra_env=recording | {"GH_CONFIG_DIR": str(inside)},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(marker.exists())
        with tempfile.TemporaryDirectory(dir=Path("/tmp").resolve()) as outside:
            store = Path(outside)
            secret = store / "hosts.yml"
            secret.write_text("synthetic outside auth-store sentinel\n")
            (inside / "hosts.yml").symlink_to(secret)
            default.symlink_to(store, target_is_directory=True)
            alias = fixture.home / "internal-gh-alias"
            alias.symlink_to(inside, target_is_directory=True)
            for extra in (
                {"GH_CONFIG_DIR": str(inside)},
                {"GH_CONFIG_DIR": "", "XDG_CONFIG_HOME": ""},
                {"GH_CONFIG_DIR": str(alias)},
            ):
                with self.subTest(extra=extra):
                    marker.unlink(missing_ok=True)
                    result = fixture.helper(
                        "check-branch-pr-truth.py", extra_env=recording | extra
                    )
                    self.assertFalse(
                        marker.exists(), "Auth-store redirection reached a hosted CLI"
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("disposable home", result.stdout + result.stderr)
                    self.assertEqual(
                        secret.read_text(), "synthetic outside auth-store sentinel\n"
                    )
        fixture.assert_preserved(self)

    def test_auth_provider_paths_are_confined_without_executing_a_provider(self):
        fixture = self.fixture
        provider = fixture.home / "synthetic-provider"
        provider.write_text("synthetic provider; never executed\n")
        result = fixture.helper(
            "admit-hook-fixture.py", "--provider-path", str(provider)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with tempfile.TemporaryDirectory(dir=Path("/tmp").resolve()) as outside:
            other = Path(outside) / "synthetic-provider"
            other.write_text("outside synthetic provider; never executed\n")
            result = fixture.helper(
                "admit-hook-fixture.py", "--provider-path", str(other)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("disposable home", result.stderr)
            self.assertEqual(
                other.read_text(), "outside synthetic provider; never executed\n"
            )
        fixture.assert_preserved(self)

    def test_resource_escape_and_missing_dependencies_never_clear(self):
        fixture = self.fixture
        with tempfile.TemporaryDirectory(dir=Path("/tmp").resolve()) as other:
            sentinel = Path(other) / "outside.json"
            sentinel.write_text('{"synthetic":true}')
            result = fixture.helper("check-evidence-freshness.py", str(sentinel))
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(sentinel.read_text(), '{"synthetic":true}')
        result = fixture.helper(
            "validate-agent-governance.py", "--root", str(fixture.home / "missing")
        )
        self.assertNotEqual(result.returncode, 0)
        fixture.assert_preserved(self)

    def test_typed_receipt_paths_are_confined_without_a_field_name_allowlist(self):
        fixture = self.fixture
        with tempfile.TemporaryDirectory(dir=Path("/tmp").resolve()) as outside:
            receipt = Path(outside) / "receipt.json"
            receipt.write_text('{"synthetic":true}')
            result = fixture.helper(
                "pr-review-request.py",
                "--repo",
                "fixture/project",
                "--pr",
                "7",
                "--reviewer",
                "codex",
                "--receipt",
                str(receipt),
                "--dry-run",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Path must remain within the disposable home", result.stderr)
            self.assertEqual(receipt.read_text(), '{"synthetic":true}')
            code = (
                "import argparse,sys; from pathlib import Path; "
                "from helper_fixture_scope import admit_file; "
                "admit_file(sys.argv[1], argparse.Namespace(future_path=Path(sys.argv[2]))); "
                'print("admitted")'
            )
            for path, accepted in (
                (fixture.home / "local.json", True),
                (receipt, False),
            ):
                result = subprocess.run(
                    [
                        fixture.env["CODEX_VALIDATION_PYTHON"],
                        "-B",
                        "-c",
                        code,
                        str(fixture.codex / "scripts/pr-review-request.py"),
                        str(path),
                    ],
                    cwd=fixture.repo,
                    env=fixture.env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(
                    result.returncode == 0, accepted, result.stdout + result.stderr
                )
                self.assertEqual("admitted" in result.stdout, accepted)
        fixture.assert_preserved(self)

    def test_local_git_metadata_core_preserves_locks_and_ignores_external_adapters(
        self,
    ):
        fixture = self.fixture
        result = fixture.helper(
            "git-metadata-preflight.py",
            "--repo-root",
            str(fixture.repo),
            "--json",
            extra_env={"GIT_METADATA_PREFLIGHT_SHARED": "/outside/never-selected.py"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lock = fixture.repo / ".git/index.lock"
        lock.write_bytes(b"synthetic caller-owned lock")
        result = fixture.helper(
            "git-metadata-preflight.py", "--repo-root", str(fixture.repo), "--json"
        )
        self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
        self.assertEqual(lock.read_bytes(), b"synthetic caller-owned lock")
        fixture.assert_preserved(self)

    def test_nested_homes_require_an_owned_root_and_confined_overrides(self):
        fixture = self.fixture
        child = fixture.home / "nested-home"
        child.mkdir()
        result = fixture.helper(
            "check-evidence-freshness.py", "--self-test", extra_env={"HOME": str(child)}
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        alias = fixture.home / "root-alias"
        alias.symlink_to(fixture.home, target_is_directory=True)
        invalid = (
            {
                "HOME": str(Path("/tmp").resolve()),
                "DOTS_TEST_HOME": str(Path("/tmp").resolve()),
                "DOTS_FIXTURE_ROOT": str(Path("/tmp").resolve()),
            },
            {"HOME": pwd.getpwuid(os.getuid()).pw_dir},
            {"DOTS_TEST_HOME": str(alias), "DOTS_FIXTURE_ROOT": str(alias)},
            {"CODEX_SOURCE_SCHEMA_PATH": "/outside/schema.json"},
        )
        try:
            for extra in invalid:
                with self.subTest(extra=extra):
                    result = fixture.helper(
                        "check-evidence-freshness.py", "--self-test", extra_env=extra
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('"status": "pass"', result.stdout)
        finally:
            alias.unlink()
        fixture.assert_preserved(self)

    def test_real_credentials_and_remote_telemetry_are_rejected_before_actions(self):
        fixture = self.fixture
        result = fixture.helper(
            "check-evidence-freshness.py",
            "--self-test",
            extra_env={"GH_TOKEN": "synthetic-denial-probe"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("credentials", result.stderr)
        for extra, accepted in (
            ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1"}, False),
            (
                {
                    "DOTS_LEGACY_HOOK_PROBES": "1",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1",
                },
                True,
            ),
            (
                {
                    "DOTS_LEGACY_HOOK_PROBES": "1",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "https://example.invalid",
                },
                False,
            ),
        ):
            with self.subTest(extra=extra):
                result = fixture.helper("admit-hook-fixture.py", "{}", extra_env=extra)
                self.assertEqual(
                    result.returncode == 0, accepted, result.stdout + result.stderr
                )
        fixture.assert_preserved(self)

    def test_aggregate_rejects_missing_migrated_helpers_before_skipping(self):
        fixture = self.fixture
        result = fixture.helper(
            "helper_fixture_scope.py", "--verify-bundle", str(fixture.codex)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (fixture.codex / "scripts/workflow-closeout.py").unlink()
        result = fixture.helper("verify-work.sh", "--fast")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Missing migrated helper dependency: codex/scripts/workflow-closeout.py",
            result.stderr,
        )
        self.assertNotIn("passed:", result.stdout)
        fixture.assert_preserved(self)

    def test_pinned_python_route_runs_and_unavailable_bootstrap_never_runs_payload(
        self,
    ):
        fixture = self.fixture
        marker = fixture.home / "python-payload.txt"
        arguments = (
            "-c",
            'from pathlib import Path; import sys; Path(sys.argv[1]).write_text("validated")',
            str(marker),
        )
        result = fixture.helper("codex-validation-python-uv.sh", *arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(marker.read_text(), "validated")
        marker.unlink()
        result = fixture.helper(
            "codex-validation-python-uv.sh",
            *arguments,
            extra_env={
                "CODEX_VALIDATION_PYTHON": "/usr/bin/false",
                "CODEX_VALIDATION_UV_PYTHON": str(fixture.home / "missing-python"),
                "UV_OFFLINE": "1",
                "UV_PYTHON_DOWNLOADS": "never",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dependency bootstrap failed", result.stderr)
        self.assertFalse(marker.exists())
        fixture.assert_preserved(self)

    def test_core_view_uses_validated_full_manifest_and_rejects_unknown_commands(self):
        fixture = self.fixture
        source = fixture.codex / "hooks/hooks.json"
        result = fixture.helper("core-hook-fixture-manifest.py", str(source))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        view = json.loads(result.stdout)
        self.assertEqual(len(view["hooks"]), 10)
        self.assertFalse(
            any(
                "braid" in hook["command"]
                for groups in view["hooks"].values()
                for group in groups
                for hook in group["hooks"]
            )
        )
        payload = json.loads(source.read_text())
        payload["hooks"]["Stop"][0]["hooks"][0]["command"] += " --unexpected"
        source.write_text(json.dumps(payload))
        result = fixture.helper("core-hook-fixture-manifest.py", str(source))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Complete hook manifest validation failed", result.stderr)
        fixture.assert_preserved(self)

    def test_auth_helpers_work_with_isolated_system_python_without_source_shadowing(
        self,
    ):
        fixture = self.fixture
        # A mutable sibling must never replace the standard-library parser in
        # the auth wrapper's existing system-Python -I -S route.
        (fixture.codex / "scripts/argparse.py").write_text(
            'raise AssertionError("source-directory module must not be imported")\n'
        )
        fifo = fixture.runtime / ".env"
        os.mkfifo(fifo, 0o600)
        config = fixture.home / "auth-routing.toml"
        config.write_text(
            '[shell_environment_policy.set]\nCODEX_AUTH_ENVIRONMENT_ID = "synthetic-environment"\n'
        )
        for name, arguments, output in (
            ("validate-auth-env-mount.py", ["--path", str(fifo)], ""),
            (
                "read-runtime-auth-environment.py",
                ["--config", str(config)],
                "synthetic-environment\n",
            ),
        ):
            with self.subTest(name=name):
                result = subprocess.run(
                    [
                        "/usr/bin/python3",
                        "-I",
                        "-S",
                        str(fixture.codex / "scripts" / name),
                        *arguments,
                    ],
                    cwd=fixture.repo,
                    env=fixture.env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, output)
        fixture.assert_preserved(self)

    def test_nested_runtime_snapshot_uses_the_real_generated_policy_projector(self):
        fixture = self.fixture
        fixture.prepare_governance_inputs()
        nested_home = fixture.home / "nested-canonical-home"
        destination = nested_home / "dev/dots"
        code = (
            "from pathlib import Path; import sys; "
            "from codex.scripts.tests.runtime_config_fixture import create_runtime_checkout; "
            "create_runtime_checkout(Path(sys.argv[1]), Path(sys.argv[2]))"
        )
        result = subprocess.run(
            [
                fixture.env["CODEX_VALIDATION_PYTHON"],
                "-B",
                "-c",
                code,
                str(destination),
                str(fixture.repo),
            ],
            cwd=fixture.repo,
            env=fixture.env,
            text=True,
            capture_output=True,
            timeout=75,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        runtime = nested_home / ".codex"
        self.assertEqual(
            (runtime / "config.toml").read_bytes(),
            (destination / "codex/config.toml").read_bytes(),
        )
        self.assertFalse((runtime / "hooks.json").is_symlink())
        self.assertEqual((runtime / "scripts").resolve(), destination / "codex/scripts")
        fixture.assert_preserved(self)

    def test_full_hook_harness_and_fast_aggregate(self):
        fixture = self.fixture
        fixture.prepare_governance_inputs()
        result = fixture.helper(
            "verify-work.sh",
            "--fast",
            timeout=240,
            extra_env={"CODEX_HOOKS_RUNTIME_CHECK": "skip"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("failed:  0", result.stdout)
        self.assertIn("execpolicy-rule-validation", result.stdout)
        fixture.assert_preserved(self)

    def test_accepted_governance_regressions(self):
        for pattern in (
            "test_arbitrate_hook_results.py",
            "test_docstring_ratchet.py",
            "test_inventory_repos.py",
            "test_public_api_classification.py",
            "test_rollout_check.py",
            "test_validate_gate_registry.py",
            "test_verify_gate_taxonomy.py",
            "test_conformance_schema.py",
            "test_conformance_freshness.py",
        ):
            with self.subTest(pattern=pattern):
                result = self.fixture.accepted_tests(pattern)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("skipped=", result.stderr)
        self.fixture.assert_preserved(self)

    def test_accepted_helper_regressions(self):
        for pattern in (
            "test_validate_agent_governance.py",
            "test_select_validation_for_changes.py",
            "test_duplication_advisory.py",
            "test_pr_body_refresh.py",
            "test_pr_post_merge_reconciliation.py",
            "test_git_metadata_preflight_contract.py",
        ):
            with self.subTest(pattern=pattern):
                result = self.fixture.accepted_tests(pattern, timeout=240)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("skipped=", result.stderr)
        self.fixture.assert_preserved(self)
