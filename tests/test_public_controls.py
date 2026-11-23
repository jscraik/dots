"""Prove command/managed constraints, instruction pointers and local-only state."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from policy_fixture import CONTROLS, ROOT, PolicyFixture

SPEC = importlib.util.spec_from_file_location(
    "public_guidance", ROOT / "scripts/check-public-guidance.py"
)
GUIDANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUIDANCE)


class PublicControlsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PolicyFixture(self)

    def controls(self, *arguments, binary=None):
        fixture = self.fixture
        env = fixture.env | {"CODEX_EXECPOLICY_REQUIRE_CLI": "1"}
        if binary is not None:
            env["CODEX_BIN"] = binary
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(fixture.codex / "scripts/validate-execpolicy-rules.py"),
                *arguments,
            ],
            cwd=fixture.repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @unittest.skipUnless(
        os.environ.get("DOTS_CODEX_BIN"), "explicit installed Codex binary required"
    )
    def test_all_accepted_native_cases_and_exact_managed_identities(self):
        result = self.controls(binary=os.environ["DOTS_CODEX_BIN"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Validated 94 execpolicy cases", result.stdout)
        self.assertIn("2 MCP identities", result.stdout)
        self.fixture.assert_preserved(self)

    def test_missing_cli_never_reports_native_success(self):
        result = self.controls(binary=str(self.fixture.home / "no-such-codex"))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Validated 94", result.stdout)

    def test_managed_constraint_or_identity_drift_blocks_before_projection(self):
        fixture = self.fixture
        path = fixture.codex / "requirements.toml"
        original = path.read_text()
        mutations = [
            ('"workspace-write"', '"danger-full-access"'),
            ("https://policy.example.invalid/mcp", "https://other.example.invalid/mcp"),
            ("https://policy.example.invalid/mcp", "*"),
            ('"on-request", "never"', '"untrusted", "on-request", "never"'),
        ]
        for old, new in mutations:
            with self.subTest(new=new):
                self.assertIn(old, original)
                path.write_text(original.replace(old, new))
                before = fixture.managed_snapshot()
                result = fixture.project()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(fixture.managed_snapshot(), before)
        path.write_text(original)
        fixture.assert_preserved(self)

    def test_new_rule_layer_is_rejected_before_projection(self):
        fixture = self.fixture
        (fixture.codex / "rules/extra.rules").write_text(
            'prefix_rule(pattern=["env"], decision="allow")'
        )
        before = fixture.managed_snapshot()
        result = fixture.project()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(fixture.managed_snapshot(), before)
        fixture.assert_preserved(self)

    def test_global_guidance_and_rules_project_but_requirements_and_handoff_do_not(
        self,
    ):
        fixture = self.fixture
        result = fixture.project()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (fixture.runtime / "AGENTS.md").read_bytes(),
            (fixture.codex / "AGENTS.md").read_bytes(),
        )
        self.assertTrue((fixture.runtime / "rules").is_symlink())
        self.assertTrue(
            (fixture.runtime / "instructions/agents/16-git-and-release.md").is_file()
        )
        self.assertFalse((fixture.runtime / "requirements.toml").exists())
        self.assertFalse((fixture.runtime / "FORJAMIE.md").exists())
        self.assertEqual(fixture.project("--check").returncode, 0)
        fixture.assert_preserved(self)

    @unittest.skipUnless(
        os.environ.get("DOTS_CODEX_BIN"), "explicit installed Codex binary required"
    )
    def test_canary_rendering_quotes_paths_without_widening_approval(self):
        fixture = self.fixture
        home = fixture.home / "home with spaces '\";$(echo never)"
        source = home / "repo/codex"
        rules, _ = CONTROLS.render_controls(fixture.base.root, source, home)
        path = fixture.home / "quoted-default.rules"
        path.write_text(rules["default.rules"])
        script = str(source / "scripts/run-auth-backed.sh")
        base = ["bash", script, "--env-file", str(home / ".codex/.env")]
        for arguments, expected in (
            (["--canary", "OLLAMA_API_KEY"], "allow"),
            (["--require-env", "OLLAMA_API_KEY", "--", "bash", "-c", "env"], None),
        ):
            env = fixture.env | {"CODEX_HOME": str(fixture.runtime)}
            result = subprocess.run(
                [
                    os.environ["DOTS_CODEX_BIN"],
                    "execpolicy",
                    "check",
                    "--rules",
                    str(path),
                    "--",
                    *base,
                    *arguments,
                ],
                env=env,
                cwd=fixture.repo,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout).get("decision"), expected)
        fixture.assert_preserved(self)

    def test_requirement_identity_serialization_does_not_allow_toml_injection(self):
        data = tomllib.loads(self.fixture.base.generated["config"])
        injected = 'https://policy.example.invalid/mcp/";allowed_sandbox_modes=["danger-full-access"]'
        data["mcp_servers"]["codex-repo"]["url"] = injected
        _, output = CONTROLS.render_controls(
            data, self.fixture.codex, self.fixture.home
        )
        parsed = tomllib.loads(output)
        self.assertEqual(
            parsed["mcp_servers"]["codex-repo"]["identity"]["url"], injected
        )
        self.assertEqual(
            parsed["allowed_sandbox_modes"], ["read-only", "workspace-write"]
        )

    def test_invalid_managed_endpoints_are_rejected(self):
        data = tomllib.loads(self.fixture.base.generated["config"])
        for value in (
            "*",
            "http://policy.example.invalid/mcp",
            "https://policy.example.invalid/mcp\nother",
            "https://user:password@policy.example.invalid/mcp",
            "https://policy.example.invalid/mcp?token=example",
        ):
            with self.subTest(value=value):
                data["mcp_servers"]["codex-repo"]["url"] = value
                with self.assertRaises(ValueError):
                    CONTROLS.render_controls(
                        data, self.fixture.codex, self.fixture.home
                    )

    def test_non_object_events_fail_admission_without_state_changes(self):
        fixture = self.fixture
        for payload in ("[]", "null", '"fixture-string"'):
            with self.subTest(payload=payload):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(fixture.codex / "scripts/admit-hook-fixture.py"),
                        payload,
                    ],
                    env=fixture.env,
                    cwd=fixture.repo,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Hook event must be an object", result.stderr)
                fixture.assert_preserved(self)


class PublicGuidanceTests(unittest.TestCase):
    def test_full_library_provenance_scopes_and_context_pointers(self):
        self.assertEqual(GUIDANCE.check_tree(ROOT), [])
        provenance = json.loads(
            (ROOT / "codex/templates/guidance-provenance.json").read_text()
        )
        instructions = {
            row["path"]
            for row in provenance["files"]
            if row["path"].startswith("codex/instructions/")
        }
        self.assertGreater(len(instructions), 55)
        self.assertTrue(
            any(row.get("deferred_context_pointers") for row in provenance["files"])
        )

    def test_provenance_and_pointer_regressions_fail(self):
        with tempfile.TemporaryDirectory(dir=Path("/tmp").resolve()) as location:
            root = Path(location)
            # Explicit public surface list, never a copy of caller runtime state.
            paths = [
                "AGENTS.md",
                "README.md",
                "codex/templates/guidance-provenance.json",
                "codex/instructions/migration-scope.md",
            ]
            provenance = json.loads((ROOT / paths[2]).read_text())
            paths.extend(row["path"] for row in provenance["files"])
            for name in set(paths):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            (root / "codex/AGENTS.md").write_text(
                "unsafe replacement\n[missing](instructions/no-such-doc.md)\n"
            )
            errors = GUIDANCE.check_tree(root)
            self.assertTrue(any("provenance drift" in error for error in errors))
            self.assertTrue(
                any("missing local Context Pointer" in error for error in errors)
            )
            self.assertTrue(any("lost a safeguard" in error for error in errors))
