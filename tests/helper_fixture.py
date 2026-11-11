"""Accepted helper resources assembled exclusively inside the owned test HOME."""

import json
import shutil
import subprocess
import sys

from policy_fixture import ROOT, PolicyFixture


class HelperFixture(PolicyFixture):
    def __init__(self, testcase):
        super().__init__(testcase)
        self.provenance = json.loads(
            (ROOT / "codex/templates/helper-provenance.json").read_text()
        )
        for row in self.provenance["files"]:
            source = ROOT / row["path"]
            relative = row["path"].removeprefix("tests/fixtures/configs-contract/")
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for name in (
            "codex/scripts/helper_fixture_scope.py",
            "codex/templates/helper-provenance.json",
            "codex/scripts/adapt-hook-fixture-event.py",
            "codex/scripts/core-hook-fixture-manifest.py",
            "AGENTS.md",
            "README.md",
            ".gitignore",
        ):
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        self.env.update(
            {
                "GH_CONFIG_DIR": str(self.home / ".config/gh"),
                "DOTS_FIXTURE_ROOT": str(self.home),
                "PYTHONPATH": str(self.codex / "scripts"),
                "GH_PROMPT_DISABLED": "1",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        self.env.pop("CODEX_VALIDATION_UV_PYTHON", None)
        self.env["CODEX_VALIDATION_PYTHON"] = sys.executable

    def prepare_governance_inputs(self):
        """Create fictional workspace observations; never import private records."""
        docs = self.codex / "docs/hooks-governance"
        example = self.home / "dev/example-project"
        example.mkdir()
        (example / "prek.toml").write_text("[tools]\n")
        (example / "Makefile").write_text(
            "hooks-pre-commit:\n\techo fixture\nhooks-pre-push:\n\techo fixture\nhooks-commit-msg:\n\techo fixture\n"
        )
        (example / "example.py").write_text(
            'def public_example():\n    """Synthetic public API."""\n    return 1\n'
        )
        (example / "package.json").write_text(
            json.dumps(
                {
                    "simple-git-hooks": {
                        "commit-msg": "node scripts/synthetic-commit-policy.js $1"
                    }
                }
            )
        )
        manifest = docs / "repo-scope.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "workspace_root": str(self.home / "dev"),
                    "repos": {"in_scope": ["example-project"], "excluded": []},
                }
            )
        )
        inventory = docs / "repo-profile-matrix.json"
        result = self.helper(
            "hook-governance/inventory_repos.py",
            "--manifest",
            str(manifest),
            "--out",
            str(inventory),
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        rules = json.loads((docs / "public-api-rules.yaml").read_text())
        rules["repositories"]["example-project"] = {
            "public_api_rule_id": "fixture-public",
            "public_api_rule_version": "2026-11-11",
            "framework_mapping_source": "explicit-synthetic-fixture",
            "rules": [],
        }
        (docs / "public-api-rules.yaml").write_text(json.dumps(rules))
        (docs / "docstring-ratchet-metrics.json").write_text(
            json.dumps(
                {
                    "schema_version": "docstring-ratchet-metrics.v1",
                    "repositories": {
                        "example-project": {
                            "false_positive_rate_weekly": [0.01, 0.01],
                            "unresolved_high_conf_suppressions_over_7d": 0,
                        }
                    },
                }
            )
        )
        result = self.helper(
            "hook-governance/generate_conformance.py",
            "--manifest",
            str(manifest),
            "--inventory",
            str(inventory),
            "--out-mode",
            "repo-local",
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        report = self.home / "synthetic-workflow.json"
        report.write_text(
            json.dumps({"items": [], "schema_version": "fixture-workflow/v1"})
        )
        self.env["CODEX_WORKFLOW_PRIORITY_GATE_REPORT"] = str(report)
        # The duplication validator needs a real, local target-history baseline.
        for arguments in (
            ["add", "."],
            [
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "synthetic validator fixture",
            ],
            ["update-ref", "refs/heads/main", "HEAD"],
            ["update-ref", "refs/remotes/origin/main", "HEAD"],
        ):
            subprocess.run(
                ["git", "-C", str(self.repo), *arguments],
                env=self.env,
                check=True,
                capture_output=True,
                timeout=15,
            )
        result = self.project()
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def helper(self, name, *arguments, timeout=90, extra_env=None):
        command = ["bash"] if name.endswith(".sh") else [sys.executable, "-B"]
        return subprocess.run(
            [*command, str(self.codex / "scripts" / name), *arguments],
            cwd=self.codex,
            env=self.env | (extra_env or {}),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def accepted_tests(self, pattern, timeout=120):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(self.codex / "scripts/tests"),
                "-p",
                pattern,
                "-v",
            ],
            env=self.env,
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
