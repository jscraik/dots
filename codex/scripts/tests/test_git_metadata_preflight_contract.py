"""Regression tests for the cross-repository Git metadata guardrail."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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


ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent
VALIDATOR_PATH = (
    ROOT / "scripts" / "hook-governance" / "verify-git-metadata-preflight.py"
)
SPEC = importlib.util.spec_from_file_location(
    "verify_git_metadata_preflight", VALIDATOR_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {VALIDATOR_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ADAPTER_SPEC = importlib.util.spec_from_file_location(
    "configs_git_metadata_preflight", ROOT / "scripts/git-metadata-preflight.py"
)
if ADAPTER_SPEC is None or ADAPTER_SPEC.loader is None:
    raise RuntimeError("Unable to load Configs metadata adapter")
ADAPTER = importlib.util.module_from_spec(ADAPTER_SPEC)
ADAPTER_SPEC.loader.exec_module(ADAPTER)


def manifest_for_hook(root: Path, hook_text: str) -> Path:
    repo = root / "demo"
    _fixture_resource(repo).mkdir()
    _fixture_resource(repo / "git-metadata-preflight.py").write_text(
        "#!/usr/bin/env python3\n", encoding="utf-8"
    )
    _fixture_resource(repo / "hook.sh").write_text(hook_text, encoding="utf-8")
    manifest = root / "manifest.json"
    _fixture_resource(manifest).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "git-metadata-preflight/v1",
                "policy": {
                    "preflight_before_expensive_gates": True,
                    "write_probe": "required",
                    "cache_location": "outside_git_metadata",
                    "lock_cleanup": "manual_only",
                    "stale_lock_classification": "candidate_not_proof",
                },
                "historical_findings": [
                    {
                        "id": finding_id,
                        "historical_failure": "fixture failure",
                        "current_control": "fixture control",
                        "enforcement": "fixture enforcement",
                    }
                    for finding_id in ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
                ],
                "repositories": [
                    {
                        "repo_name": "demo",
                        "repo_path": "demo",
                        "adapter": "git-metadata-preflight.py",
                        "hook_entrypoints": ["hook.sh"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


class GitMetadataPreflightContractTests(unittest.TestCase):
    def run_adapter(
        self, args: list[str], provider: Path
    ) -> subprocess.CompletedProcess[str]:
        home = provider.parent / "account-home"
        target = (
            home
            / "dev/agent-skills/Infrastructure/scripts/validation-and-linting/git_metadata_preflight.py"
        )
        _fixture_resource(target.parent).mkdir(parents=True, exist_ok=True)
        if provider.is_file():
            shutil.copyfile(provider, target)
        stdout, stderr = (io.StringIO(), io.StringIO())
        with (
            mock.patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir=str(home))),
            mock.patch.dict(
                os.environ,
                {
                    "HOME": str(home / "untrusted"),
                    "GIT_METADATA_PREFLIGHT_SHARED": str(provider),
                },
            ),
            mock.patch.object(
                sys, "argv", [str(ROOT / "scripts/git-metadata-preflight.py"), *args]
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            mock.patch.object(ADAPTER, "shared_path", return_value=target),
        ):
            code = ADAPTER.main()
        return subprocess.CompletedProcess(
            args, code, stdout.getvalue(), stderr.getvalue()
        )

    def test_configs_adapter_blocks_unavailable_account_home(self) -> None:
        for error in (
            KeyError("missing account"),
            OSError("lookup failed"),
            ValueError("invalid home"),
            AttributeError("unsupported platform"),
            ImportError("no pwd"),
        ):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch.object(ADAPTER, "shared_path", side_effect=error),
                mock.patch.object(ADAPTER.subprocess, "run") as recipient,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(ADAPTER.main(), 78)
                self.assertEqual(
                    json.loads(output.getvalue())["reason_codes"],
                    ["unavailable_account_home"],
                )
                recipient.assert_not_called()
        for home in ("", "relative-home"):
            with (
                self.subTest(home=home),
                mock.patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir=home)),
                self.assertRaises(ValueError),
            ):
                ADAPTER.shared_path()

    def test_configs_adapter_ignores_inspected_repository_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            shared = (
                workspace
                / "agent-skills"
                / "Infrastructure"
                / "scripts"
                / "validation-and-linting"
                / "git_metadata_preflight.py"
            )
            _fixture_resource(shared.parent).mkdir(parents=True)
            _fixture_resource(shared).write_text("print('shared')\n", encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "HOME": str(workspace),
                        "GIT_METADATA_PREFLIGHT_SHARED": str(shared),
                    },
                ),
                mock.patch(
                    "pwd.getpwuid",
                    return_value=SimpleNamespace(
                        pw_dir=str(workspace / "trusted-home")
                    ),
                ),
            ):
                selected = ADAPTER.shared_path()
            self.assertNotEqual(selected, shared.resolve())
            self.assertEqual(
                selected, (ROOT / "scripts/git_metadata_core.py").resolve()
            )

    def test_configs_adapter_falls_back_to_home_governed_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            shared = (
                workspace
                / "dev"
                / "agent-skills"
                / "Infrastructure"
                / "scripts"
                / "validation-and-linting"
                / "git_metadata_preflight.py"
            )
            _fixture_resource(shared.parent).mkdir(parents=True)
            _fixture_resource(shared).write_text("print('shared')\n", encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "HOME": str(workspace / "untrusted-home"),
                        "GIT_METADATA_PREFLIGHT_SHARED": str(
                            workspace / "untrusted.py"
                        ),
                    },
                ),
                mock.patch(
                    "pwd.getpwuid", return_value=SimpleNamespace(pw_dir=str(workspace))
                ),
            ):
                self.assertEqual(
                    ADAPTER.shared_path(),
                    (ROOT / "scripts/git_metadata_core.py").resolve(),
                )

    def test_current_workspace_adoption_contract_passes(self) -> None:
        manifest = ROOT / "docs" / "hooks-governance" / "git-metadata-preflight.v1.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_manifest = Path(temp_dir) / "configs-manifest.json"
            payload = MODULE.load_manifest(manifest)
            payload["repositories"] = [
                {**record, "repo_path": "."}
                for record in payload["repositories"]
                if record["repo_name"] == "configs"
            ]
            _fixture_resource(fixture_manifest).write_text(
                json.dumps(payload), encoding="utf-8"
            )
            errors = MODULE.validate_manifest(fixture_manifest, REPO_ROOT, strict=True)
            self.assertEqual(errors, [])
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR_PATH),
                    "--manifest",
                    str(fixture_manifest),
                    "--workspace-root",
                    str(REPO_ROOT),
                    "--strict",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(
                json.loads(proc.stdout)["service"], "git-metadata-preflight-adoption"
            )

    def test_contract_rejects_cache_under_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "demo"
            _fixture_resource(repo).mkdir()
            adapter = repo / "adapter.py"
            _fixture_resource(adapter).write_text("# adapter\n", encoding="utf-8")
            hook = repo / "hook.sh"
            _fixture_resource(hook).write_text(
                "git_metadata_preflight\n.git/.cache\n", encoding="utf-8"
            )
            manifest = root / "manifest.json"
            _fixture_resource(manifest).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "contract": "git-metadata-preflight/v1",
                        "policy": {
                            "preflight_before_expensive_gates": True,
                            "write_probe": "required",
                            "cache_location": "outside_git_metadata",
                            "lock_cleanup": "manual_only",
                            "stale_lock_classification": "candidate_not_proof",
                        },
                        "repositories": [
                            {
                                "repo_name": "demo",
                                "repo_path": "demo",
                                "adapter": "adapter.py",
                                "hook_entrypoints": ["hook.sh"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate_manifest(manifest, root, strict=True)
            self.assertTrue(
                any("keeps caches under Git metadata" in error for error in errors)
            )

    def test_contract_rejects_unsafe_paths_and_comment_only_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "demo"
            _fixture_resource(repo).mkdir()
            _fixture_resource(repo / "adapter.py").write_text(
                "#!/usr/bin/env python3\n", encoding="utf-8"
            )
            _fixture_resource(repo / "hook.sh").write_text(
                "#!/usr/bin/env bash\n# git_metadata_preflight\nXDG_CACHE_HOME=/tmp/cache\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            _fixture_resource(manifest).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "contract": "git-metadata-preflight/v1",
                        "policy": {
                            "preflight_before_expensive_gates": True,
                            "write_probe": "required",
                            "cache_location": "outside_git_metadata",
                            "lock_cleanup": "manual_only",
                            "stale_lock_classification": "candidate_not_proof",
                        },
                        "repositories": [
                            {
                                "repo_name": "demo",
                                "repo_path": "../demo",
                                "adapter": "/tmp/adapter.py",
                                "hook_entrypoints": ["hook.sh"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate_manifest(manifest, root, strict=True)
            self.assertTrue(any("repo_path escapes" in error for error in errors))
            _fixture_resource(manifest).write_text(
                _fixture_resource(manifest)
                .read_text(encoding="utf-8")
                .replace('"../demo"', '"demo"')
                .replace('"/tmp/adapter.py"', '"adapter.py"'),
                encoding="utf-8",
            )
            errors = MODULE.validate_manifest(manifest, root, strict=True)
            self.assertTrue(
                any("does not call the adapter" in error for error in errors)
            )

    def test_contract_rejects_comment_only_cache_root_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "demo"
            _fixture_resource(repo).mkdir()
            _fixture_resource(repo / "adapter.py").write_text(
                "#!/usr/bin/env python3\n", encoding="utf-8"
            )
            _fixture_resource(repo / "hook.sh").write_text(
                "#!/usr/bin/env bash\npython3 adapter.py --repo-root .\n# CODEX_HOOK_CACHE_ROOT=/tmp/cache\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            _fixture_resource(manifest).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "contract": "git-metadata-preflight/v1",
                        "policy": {
                            "preflight_before_expensive_gates": True,
                            "write_probe": "required",
                            "cache_location": "outside_git_metadata",
                            "lock_cleanup": "manual_only",
                            "stale_lock_classification": "candidate_not_proof",
                        },
                        "repositories": [
                            {
                                "repo_name": "demo",
                                "repo_path": "demo",
                                "adapter": "adapter.py",
                                "hook_entrypoints": ["hook.sh"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate_manifest(manifest, root, strict=True)
            self.assertTrue(
                any(
                    "does not configure a guarded cache root" in error
                    for error in errors
                )
            )

    def test_contract_rejects_duplicate_adapter_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                "#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\npython3 git-metadata-preflight.py --repo-root . --json\npython3 git-metadata-preflight.py --repo-root . --json\npnpm lint\n",
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("exactly one adapter invocation" in error for error in errors)
            )

    def test_contract_rejects_chained_adapter_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                "#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\npython3 git-metadata-preflight.py --repo-root . --json; python3 git-metadata-preflight.py --repo-root . --json\npnpm lint\n",
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("exactly one adapter invocation" in error for error in errors)
            )

    def test_contract_ignores_adapter_name_in_non_command_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                "#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\necho git-metadata-preflight.py --repo-root .\npython3 git-metadata-preflight.py --repo-root . --json\npnpm lint\n",
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertFalse(
                any("exactly one adapter invocation" in error for error in errors)
            )

    def test_manifest_requires_the_complete_historical_control_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(Path(temp_dir), "#!/usr/bin/env bash\n")
            payload = json.loads(
                _fixture_resource(manifest).read_text(encoding="utf-8")
            )
            payload["historical_findings"] = payload["historical_findings"][:-1]
            _fixture_resource(manifest).write_text(
                json.dumps(payload), encoding="utf-8"
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("historical_findings missing ids" in error for error in errors)
            )

    def test_contract_rejects_disabled_write_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                "#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\npython3 git-metadata-preflight.py --repo-root . --no-write-probe --json\npnpm lint\n",
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("disables the required write probe" in error for error in errors)
            )

    def test_contract_rejects_variable_disabled_write_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                '#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\npreflight_args=--no-write-probe\npython3 git-metadata-preflight.py --repo-root . "$preflight_args" --json\npnpm lint\n',
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("disables the required write probe" in error for error in errors)
            )

    def test_contract_rejects_positional_disabled_write_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                '#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\npreflight_args=--no-write-probe\nset -- "$preflight_args"\npython3 git-metadata-preflight.py --repo-root . "$@" --json\npnpm lint\n',
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("disables the required write probe" in error for error in errors)
            )

    def test_contract_rejects_lock_or_worktree_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                "#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\npython3 git-metadata-preflight.py --repo-root . --json\ngit worktree remove --force ../sibling\n",
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("must not clean Git metadata" in error for error in errors)
            )

    def test_contract_rejects_shadow_adapter_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                "#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\npython3 shadow/git-metadata-preflight.py --repo-root . --json\npnpm lint\n",
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("exactly one adapter invocation" in error for error in errors)
            )

    def test_contract_rejects_variable_based_metadata_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                '#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\nlock_path="$GIT_DIR/index.lock"\npython3 git-metadata-preflight.py --repo-root . --json\nrm -f "$lock_path"\n',
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("must not clean Git metadata" in error for error in errors)
            )

    def test_contract_rejects_command_wrapped_metadata_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = manifest_for_hook(
                Path(temp_dir),
                '#!/usr/bin/env bash\nCODEX_HOOK_CACHE_ROOT=/tmp/cache\npython3 git-metadata-preflight.py --repo-root . --json\ncommand rm -f "$GIT_DIR/index.lock"\n',
            )
            errors = MODULE.validate_manifest(manifest, Path(temp_dir), strict=True)
            self.assertTrue(
                any("must not clean Git metadata" in error for error in errors)
            )

    def test_configs_adapter_keeps_json_stdout_clean_and_paths_opaque(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shared = Path(temp_dir) / "shared.py"
            _fixture_resource(shared).write_text(
                'import json, sys\nprint(\'diagnostic belongs on stderr\', file=sys.stderr)\nprint(json.dumps({\n  "schema_version": 1, "contract": "git-metadata-preflight/v1",\n  "status": "blocked", "reason_codes": ["active_index_lock"],\n  "index_lock_path": "/tmp/work tree/current/index.lock",\n  "locks": [{"path": "/tmp/work tree/other/index.lock", "classification": "active_index_lock"}]\n}))\nraise SystemExit(78)\n',
                encoding="utf-8",
            )
            proc = self.run_adapter(["--repo-root", str(ROOT), "--json"], shared)
            payload = json.loads(proc.stdout)
            self.assertEqual(proc.returncode, 78)
            self.assertEqual(
                payload["locks"][0]["path"], "/tmp/work tree/other/index.lock"
            )
            self.assertEqual(proc.stderr, "")

    def test_manifest_declares_current_main_controls_for_historical_findings(
        self,
    ) -> None:
        manifest = ROOT / "docs" / "hooks-governance" / "git-metadata-preflight.v1.json"
        payload = json.loads(_fixture_resource(manifest).read_text(encoding="utf-8"))
        controls = payload["historical_findings"]
        self.assertEqual(
            {record["id"] for record in controls},
            {"F1", "F2", "F3", "F4", "F5", "F6", "F7"},
        )
        self.assertTrue(all(record["current_control"] for record in controls))

    def test_configs_adapter_fails_closed_when_shared_source_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            proc = self.run_adapter(
                ["--repo-root", str(ROOT), "--json"], Path(temp_dir) / "missing.py"
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(proc.returncode, 78)
            self.assertEqual(payload["service"], "configs-git-metadata-preflight")
            self.assertEqual(payload["reason_codes"], ["missing_shared_adapter"])

    def test_hook_runtime_env_rejects_git_metadata_cache_root(self) -> None:
        common_dir = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--git-common-dir"], text=True
        ).strip()
        helper = REPO_ROOT / "scripts" / "git-hooks" / "hook-runtime-env.sh"
        proc = subprocess.run(
            ["bash", "-c", f"source {shlex.quote(str(helper))}"],
            cwd=REPO_ROOT,
            env=_fixture_test_env(
                {
                    **os.environ,
                    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                    "repo_root": str(REPO_ROOT),
                    "CODEX_HOOK_CACHE_ROOT": str(Path(common_dir) / "unsafe-cache"),
                }
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 78)
        self.assertIn("outside Git metadata", proc.stderr)

    def test_hook_runtime_env_ignores_inherited_git_metadata_environment(self) -> None:
        helper = REPO_ROOT / "scripts" / "git-hooks" / "hook-runtime-env.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            proc = subprocess.run(
                ["bash", "-c", f"source {shlex.quote(str(helper))}"],
                cwd=REPO_ROOT,
                env=_fixture_test_env(
                    {
                        **os.environ,
                        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                        "repo_root": str(REPO_ROOT),
                        "CODEX_HOOK_CACHE_ROOT": str(cache_root),
                        "GIT_DIR": str(Path(temp_dir) / "wrong-git-dir"),
                        "GIT_WORK_TREE": str(Path(temp_dir) / "wrong-work-tree"),
                        "GIT_INDEX_FILE": str(Path(temp_dir) / "wrong-index"),
                        "GIT_COMMON_DIR": str(Path(temp_dir) / "wrong-common-dir"),
                    }
                ),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(cache_root.is_dir())

    def test_hook_runtime_env_rejects_inherited_cache_under_git_metadata(self) -> None:
        common_dir = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--git-common-dir"], text=True
        ).strip()
        helper = REPO_ROOT / "scripts" / "git-hooks" / "hook-runtime-env.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            proc = subprocess.run(
                ["bash", "-c", f"source {shlex.quote(str(helper))}"],
                cwd=REPO_ROOT,
                env=_fixture_test_env(
                    {
                        **os.environ,
                        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                        "repo_root": str(REPO_ROOT),
                        "CODEX_HOOK_CACHE_ROOT": str(Path(temp_dir) / "cache"),
                        "XDG_CACHE_HOME": str(Path(common_dir) / "unsafe-cache"),
                    }
                ),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 78)
            self.assertIn("XDG_CACHE_HOME", proc.stderr)

    def test_pre_tool_guard_normalizes_protected_push_destinations(self) -> None:
        hook = ROOT / "hooks" / "pre-tool-use-guard.sh"
        for command in (
            "git push origin main",
            "git push upstream master",
            "git push upstream feature:main",
            "git push origin feature:refs/heads/main",
        ):
            proc = subprocess.run(
                ["bash", str(hook)],
                input=json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                ),
                env=_fixture_test_env(
                    {
                        **os.environ,
                        "HOME": os.environ["DOTS_TEST_HOME"],
                        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                    }
                ),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('"permissionDecision": "deny"', proc.stdout)

    def test_configs_adapter_blocks_unrelated_lock_with_allowed_current_lock(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shared = Path(temp_dir) / "shared.py"
            _fixture_resource(shared).write_text(
                'import json\nprint(json.dumps({\n  "schema_version": 1, "contract": "git-metadata-preflight/v1",\n  "status": "pass", "reason_codes": [],\n  "index_lock_path": "/tmp/current-index.lock",\n  "locks": [\n    {"path": "/tmp/current-index.lock", "classification": "stale_index_lock_candidate"},\n    {"path": "/tmp/other-index.lock", "classification": "active_index_lock"}\n  ]\n}))\n',
                encoding="utf-8",
            )
            proc = self.run_adapter(
                ["--repo-root", str(REPO_ROOT), "--allow-current-index-lock", "--json"],
                shared,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(proc.returncode, 78)
            self.assertEqual(payload["service"], "configs-git-metadata-preflight")
            self.assertEqual(payload["status"], "blocked")
            self.assertIn("active_index_lock", payload["reason_codes"])

    def test_configs_adapter_allows_only_current_index_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shared = Path(temp_dir) / "shared.py"
            _fixture_resource(shared).write_text(
                'import json\nprint(json.dumps({"schema_version": 1, "contract": "git-metadata-preflight/v1",\n  "status": "blocked", "reason_codes": ["active_index_lock", "current_worktree_locked"],\n  "index_lock_path": "/tmp/current-index.lock",\n  "locks": [{"path": "/tmp/../tmp/current-index.lock", "classification": "active_index_lock"}]\n}))\nraise SystemExit(78)\n',
                encoding="utf-8",
            )
            proc = self.run_adapter(
                ["--repo-root", str(REPO_ROOT), "--allow-current-index-lock", "--json"],
                shared,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(
                json.loads(proc.stdout)["service"], "configs-git-metadata-preflight"
            )

    def test_configs_adapter_does_not_hide_non_lock_blockers_with_allowed_current_lock(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shared = Path(temp_dir) / "shared.py"
            _fixture_resource(shared).write_text(
                'import json\nprint(json.dumps({"schema_version": 1, "contract": "git-metadata-preflight/v1",\n  "status": "blocked", "reason_codes": ["active_index_lock", "metadata_write_denied"],\n  "index_lock_path": "/tmp/current-index.lock",\n  "locks": [{"path": "/tmp/current-index.lock", "classification": "active_index_lock"}]\n}))\nraise SystemExit(78)\n',
                encoding="utf-8",
            )
            proc = self.run_adapter(
                ["--repo-root", str(REPO_ROOT), "--allow-current-index-lock", "--json"],
                shared,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(proc.returncode, 78)
            self.assertEqual(payload["status"], "blocked")
            self.assertIn("metadata_write_denied", payload["reason_codes"])

    def test_auth_canary_rejects_non_identifier_before_indirect_lookup(self) -> None:
        wrapper = ROOT / "scripts" / "run-auth-backed.sh"
        proc = subprocess.run(
            ["bash", str(wrapper), "--canary", "array[$(printf injected)0]"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid --canary variable name", proc.stderr)

    def test_contract_rejects_adapter_after_expensive_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "demo"
            _fixture_resource(repo).mkdir()
            _fixture_resource(repo / "git-metadata-preflight.py").write_text(
                "#!/usr/bin/env python3\n", encoding="utf-8"
            )
            _fixture_resource(repo / "hook.sh").write_text(
                "#!/usr/bin/env bash\nXDG_CACHE_HOME=/tmp/cache\npnpm lint\npython3 git-metadata-preflight.py --repo-root .\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            _fixture_resource(manifest).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "contract": "git-metadata-preflight/v1",
                        "policy": {
                            "preflight_before_expensive_gates": True,
                            "write_probe": "required",
                            "cache_location": "outside_git_metadata",
                            "lock_cleanup": "manual_only",
                            "stale_lock_classification": "candidate_not_proof",
                        },
                        "repositories": [
                            {
                                "repo_name": "demo",
                                "repo_path": "demo",
                                "adapter": "git-metadata-preflight.py",
                                "hook_entrypoints": ["hook.sh"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate_manifest(manifest, root, strict=True)
            self.assertTrue(any("after an expensive gate" in error for error in errors))

    def test_pre_commit_lock_exception_is_git_hook_only(self) -> None:
        hook = _fixture_resource(
            REPO_ROOT / "scripts" / "git-hooks" / "pre-commit.sh"
        ).read_text(encoding="utf-8")
        setup = _fixture_resource(
            REPO_ROOT / "scripts" / "setup-git-hooks.js"
        ).read_text(encoding="utf-8")
        prepare = _fixture_resource(
            REPO_ROOT / "scripts" / "prepare-worktree.sh"
        ).read_text(encoding="utf-8")
        environment_check = _fixture_resource(
            REPO_ROOT / "scripts" / "check-environment.sh"
        ).read_text(encoding="utf-8")
        prek_config = _fixture_resource(REPO_ROOT / "prek.toml").read_text(
            encoding="utf-8"
        )
        validator = _fixture_resource(
            ROOT / "scripts" / "validate-codex-hooks.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("CODEX_PRE_COMMIT_FROM_GIT", hook)
        self.assertIn("preflight_lock_arg=''", hook)
        self.assertIn("preflight_lock_arg='--allow-current-index-lock'", hook)
        self.assertIn(
            'python3 codex/scripts/git-metadata-preflight.py --repo-root "$repo_root" "$@" --json',
            hook,
        )
        self.assertEqual(
            hook.count("python3 codex/scripts/git-metadata-preflight.py"), 1
        )
        self.assertIn("PREK_PRE_COMMIT_MARKER", setup)
        self.assertIn('"export CODEX_PRE_COMMIT_FROM_GIT=1"', setup)
        self.assertIn('entry = "bash scripts/git-hooks/pre-commit.sh"', prek_config)
        self.assertIn(
            "# Run: node scripts/setup-git-hooks.js && prek run --all-files",
            prek_config,
        )
        self.assertNotIn("# Run: prek install --overwrite", prek_config)
        self.assertNotIn("CODEX_PRE_COMMIT_FROM_GIT", prek_config)
        self.assertIn(
            '"entry": "bash scripts/git-hooks/pre-commit.sh"', environment_check
        )
        self.assertIn('PREK_HOME="$CODEX_HOOK_CACHE_ROOT/prek"', setup)
        self.assertIn('mkdir -p "$PREK_HOME"', setup)
        self.assertIn("canonicalize_path()", setup)
        self.assertIn(
            'CODEX_HOOK_CACHE_ROOT="$(canonicalize_path "$CODEX_HOOK_CACHE_ROOT")"',
            setup,
        )
        self.assertLess(
            setup.index('CODEX_HOOK_CACHE_ROOT="$(canonicalize_path'),
            setup.index('case "$CODEX_HOOK_CACHE_ROOT/"'),
        )
        main_body = prepare[prepare.index("main()") :]
        self.assertLess(
            main_body.index("setup_mise"),
            main_body.index("check_git_metadata_authority"),
        )
        self.assertIn("env -u CIRCLECI_CLI_TOKEN", validator)


if __name__ == "__main__":
    unittest.main()
