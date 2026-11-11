"""Exercise the production CLI against disposable Git repositories."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


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


SCRIPT = Path(__file__).resolve().parents[1] / "duplication_advisory.py"
WRAPPER = SCRIPT.parent / "codex-validation-python-uv.sh"
BODY = "def total(values):\n    result = []\n    for value in values:\n        if value > 3:\n            result.append(value * 2)\n        else:\n            result.append(value + 1)\n    return sorted(result)\n"


class DuplicationAdvisoryTests(unittest.TestCase):
    def test_ci_uses_verified_actual_pr_target_not_main(self) -> None:
        main = self.git("rev-parse", "HEAD")
        self.git("branch", "main", main)
        self.write("copy.py", BODY.replace("total", "other"))
        self.git("add", "copy.py")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "release baseline")
        target = self.git("rev-parse", "HEAD")
        self.git("branch", "release/fixture", target)
        self.write("README.md", "candidate documentation\n")
        self.git("add", "README.md")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "candidate")
        head = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", str(self.root))
        self.git("update-ref", "refs/remotes/origin/main", main)
        config = yaml.safe_load(
            _fixture_resource(SCRIPT.parents[2] / ".circleci/config.yml").read_text()
        )
        step = next(
            item["run"]
            for item in config["jobs"]["run-governance-check"]["steps"]
            if isinstance(item, dict)
            and isinstance(item.get("run"), dict)
            and (item["run"]["name"] == "Prepare duplication target history for tests")
        )
        command = step["command"].replace("<< parameters.check_name >>", "test")
        env_file = self.root / "prepared.env"
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
            and key not in {"CODEX_DUPLICATION_BASE", "BASH_ENV", "ENV", "ZDOTDIR"}
        }
        environment.update(
            BASH_ENV=str(env_file),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            PR_METADATA_STATUS="loaded",
            PR_BASE_REF="release/fixture",
            PR_BASE_SHA=target,
            PR_HEAD_SHA=head,
            PR_DUPLICATION_TARGET_STATUS="loaded",
        )
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=self.root,
            env=_fixture_test_env(environment),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        selected = subprocess.check_output(
            ["bash", "-c", 'printf "%s" "$CODEX_DUPLICATION_BASE"'],
            cwd=self.root,
            env=_fixture_test_env(environment),
            text=True,
        ).strip()
        self.assertEqual(selected, target)
        code, report = self.check("--require-target-baseline", base_env=selected)
        self.assertEqual(code, 0)
        self.assertEqual(report["base"], target)
        self.assertEqual(report["advisories"], [])
        self.assertEqual(len(self.check("--base", main)[1]["advisories"]), 1)
        advanced = subprocess.run(
            [
                "git",
                "-c",
                "commit.gpgsign=false",
                "commit-tree",
                f"{target}^{{tree}}",
                "-p",
                target,
            ],
            cwd=self.root,
            input="target advanced\n",
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.git("update-ref", "refs/heads/release/fixture", advanced)
        _fixture_resource(env_file).unlink(missing_ok=True)
        fast_forward = subprocess.run(
            ["bash", "-c", command],
            cwd=self.root,
            env=_fixture_test_env(environment),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            fast_forward.returncode, 0, fast_forward.stdout + fast_forward.stderr
        )
        self.assertEqual(self.git("merge-base", head, advanced), target)
        selected_after_advance = subprocess.check_output(
            ["bash", "-c", 'printf "%s" "$CODEX_DUPLICATION_BASE"'],
            cwd=self.root,
            env=_fixture_test_env(environment),
            text=True,
        ).strip()
        self.assertEqual(selected_after_advance, target)
        with patch.dict(
            os.environ, {"CODEX_DUPLICATION_BASE": target, "BASH_ENV": str(env_file)}
        ):
            self.assertEqual(self.check("--require-target-baseline")[1]["base"], main)
        for overrides in (
            {"PR_BASE_SHA": head},
            {"PR_HEAD_SHA": main},
            {"PR_DUPLICATION_TARGET_STATUS": "blocked"},
            {"PR_BASE_REF": "bad:ref"},
            {
                "PR_METADATA_STATUS": "unavailable",
                "CIRCLE_BRANCH": "codex/unknown-target",
            },
        ):
            with self.subTest(overrides=overrides):
                _fixture_resource(env_file).unlink(missing_ok=True)
                invalid = subprocess.run(
                    ["bash", "-c", command],
                    cwd=self.root,
                    env=_fixture_test_env({**environment, **overrides}),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertNotEqual(invalid.returncode, 0)
        _fixture_resource(env_file).unlink(missing_ok=True)
        non_pr = subprocess.run(
            ["bash", "-c", command],
            cwd=self.root,
            env=_fixture_test_env(
                {
                    **environment,
                    "PR_METADATA_STATUS": "unavailable",
                    "CIRCLE_BRANCH": "main",
                }
            ),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(non_pr.returncode, 0, non_pr.stdout + non_pr.stderr)
        selected = subprocess.check_output(
            ["bash", "-c", 'printf "%s" "$CODEX_DUPLICATION_BASE"'],
            cwd=self.root,
            env=_fixture_test_env(environment),
            text=True,
        ).strip()
        self.assertEqual(selected, main)

    def test_projected_verifier_only_scans_target_owned_checker(self) -> None:
        verifier = SCRIPT.parent / "verify-work.sh"
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
            and key not in {"CODEX_DUPLICATION_BASE", "BASH_ENV", "ENV", "ZDOTDIR"}
        }
        home = self.root / "isolated-home"
        _fixture_resource(home).mkdir()
        environment.update(
            HOME=str(home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull
        )
        command = ["bash", str(verifier), "--repo-root", str(self.root), "--fast"]
        unrelated = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=_fixture_test_env(environment),
            timeout=180,
            check=False,
        )
        self.assertEqual(unrelated.returncode, 0, unrelated.stdout + unrelated.stderr)
        self.assertNotIn("==> new-duplication-advisory", unrelated.stdout)
        self.write(
            "codex/scripts/duplication_advisory.py",
            _fixture_resource(SCRIPT).read_text(),
        )
        for dependency in ("helper_fixture_scope.py", "migration_scope.py"):
            self.write(
                "codex/scripts/" + dependency, (SCRIPT.parent / dependency).read_text()
            )
        self.git(
            "update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD")
        )
        adopted = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=_fixture_test_env(environment),
            timeout=180,
            check=False,
        )
        self.assertEqual(adopted.returncode, 0, adopted.stdout + adopted.stderr)
        self.assertIn("==> new-duplication-advisory", adopted.stdout)
        self.assertIn('"service": "duplication-advisory"', adopted.stdout)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("owner.py", BODY)
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "baseline")

    def git(self, *args: str) -> str:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        hooks = self.root / ".empty-hooks"
        _fixture_resource(hooks).mkdir(exist_ok=True)
        return subprocess.check_output(
            ["git", "-c", f"core.hooksPath={hooks}", "-c", "init.templateDir=", *args],
            cwd=self.root,
            text=True,
            env=_fixture_test_env(environment),
            timeout=30,
        ).strip()

    def write(self, path: str, body: str) -> None:
        target = self.root / path
        _fixture_resource(target.parent).mkdir(parents=True, exist_ok=True)
        _fixture_resource(target).write_text(body)

    def check(self, *args: str, base_env: str | None = None) -> tuple[int, dict]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
            and key not in {"CODEX_DUPLICATION_BASE", "BASH_ENV", "ENV", "ZDOTDIR"}
        }
        if base_env is not None:
            environment["CODEX_DUPLICATION_BASE"] = base_env
        result = subprocess.run(
            ["bash", str(WRAPPER), str(SCRIPT), "--root", str(self.root), *args],
            text=True,
            capture_output=True,
            timeout=60,
            env=_fixture_test_env(environment),
            check=False,
        )
        self.assertTrue(result.stdout, result.stderr)
        return (result.returncode, json.loads(result.stdout))

    def test_new_renamed_duplicate_is_advisory_not_failure(self) -> None:
        self.write(
            "copy.py",
            BODY.replace("total", "other")
            .replace("values", "items")
            .replace("result", "answer"),
        )
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(len(report["advisories"]), 1)
        self.assertEqual(report["violations"], [])

    def test_suffix_style_test_modules_are_excluded(self) -> None:
        self.write("module_test.py", BODY.replace("total", "other"))
        self.assertEqual(self.check("--base", "HEAD")[1]["advisories"], [])
        self.write("module_test.py", BODY)
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture",
                        }
                    ],
                }
            ),
        )
        self.assertEqual(self.check("--base", "HEAD", "--policy", "policy.json")[0], 0)

    def test_non_utf8_git_path_records_do_not_abort_remaining_scan(self) -> None:
        module = runpy.run_path(str(SCRIPT))
        real_git = module["git"]
        real_is_file = Path.is_file
        self.write("copy.py", BODY.replace("total", "other"))
        for suffix, state in (
            (suffix, state)
            for suffix in (b".txt", b".py")
            for state in ("present", "deleted", "sparse")
        ):
            with self.subTest(suffix=suffix, state=state):

                def transport(root, *args, suffix=suffix, state=state):
                    output = real_git(root, *args)
                    if args[0] == "ls-tree":
                        output += (
                            b"100644 blob " + b"0" * 40 + b"\t\xff" + suffix + b"\x00"
                        )
                    elif args[:2] == ("ls-files", "-z"):
                        output += b"\xff" + suffix + b"\x00"
                    elif args[:2] == ("ls-files", "-t") and state == "sparse":
                        output += b"S \xff" + suffix + b"\x00"
                    return output

                def is_file(target, suffix=suffix, state=state):
                    if target.name == os.fsdecode(b"\xff" + suffix):
                        return state == "present"
                    return real_is_file(target)

                with (
                    patch.dict(module["analyze"].__globals__, {"git": transport}),
                    patch.object(Path, "is_file", is_file),
                ):
                    report = module["analyze"](
                        self.root.resolve(),
                        "HEAD",
                        module["Policy"](schema_version=1, boundaries=[]),
                    )
                payload = json.loads(report.model_dump_json())
                self.assertEqual(len(payload["advisories"]), 1, payload)
                self.assertEqual(
                    payload["status"],
                    "unverified" if suffix == b".py" and state != "deleted" else "pass",
                )

    def test_deleted_uninspectable_baselines_do_not_block_current_ownership(
        self,
    ) -> None:
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture",
                        }
                    ],
                }
            ),
        )
        for kind, content in (
            ("large", b"#" + b"x" * 1048576),
            ("encoding", b"\xff"),
            ("syntax", b"def broken("),
            ("missing", b"def removed(): return 0\n"),
        ):
            with self.subTest(kind=kind):
                deleted = self.root / "deleted.py"
                _fixture_resource(deleted).write_bytes(content)
                self.git("add", ".")
                self.git(
                    "-c", "commit.gpgsign=false", "commit", "-qm", "deleted fixture"
                )
                if kind == "missing":
                    oid = self.git("rev-parse", "HEAD:deleted.py")
                    _fixture_resource(
                        self.root / ".git" / "objects" / oid[:2] / oid[2:]
                    ).unlink()
                _fixture_resource(deleted).unlink()
                code, report = self.check("--base", "HEAD", "--policy", "policy.json")
                self.assertEqual(code, 0)
                self.assertEqual(report["status"], "pass")

    def test_missing_target_ref_does_not_claim_branch_comparison_passed(self) -> None:
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "unverified")
        self.assertTrue(
            any("target baseline" in item for item in report["diagnostics"])
        )
        self.assertEqual(self.check("--base", "HEAD")[1]["status"], "pass")
        code, report = self.check("--require-target-baseline")
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "unverified")
        self.git("update-ref", "refs/heads/main", "HEAD")
        self.git("remote", "add", "origin", str(self.root))
        self.git(
            "fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main"
        )
        self.assertEqual(self.check("--require-target-baseline")[0], 0)
        self.write("bad.py", "def broken(\n")
        code, report = self.check("--require-target-baseline")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "unverified")
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "checkout"
            self.git(
                "clone",
                "--depth",
                "1",
                "--branch",
                "main",
                self.root.as_uri(),
                str(clone),
            )
            original = self.root
            try:
                self.root = clone
                self.git("update-ref", "-d", "refs/remotes/origin/main")
                self.assertEqual(
                    self.git("rev-parse", "--is-shallow-repository"), "true"
                )
                self.assertEqual(self.check("--require-target-baseline")[0], 3)
                self.git("fetch", "--no-tags", "--unshallow", "origin")
                self.git(
                    "fetch",
                    "--no-tags",
                    "origin",
                    "refs/heads/main:refs/remotes/origin/main",
                )
                self.assertEqual(
                    self.git("rev-parse", "--is-shallow-repository"), "false"
                )
                self.assertEqual(self.check("--require-target-baseline")[0], 0)
            finally:
                self.root = original

    def test_definition_time_globals_remain_significant(self) -> None:
        for header in (
            "def total(values=values):",
            "def total(values: values):",
            "def total(values) -> values:",
            "@values\ndef total(values):",
        ):
            with self.subTest(header=header):
                body = BODY.replace("def total(values):", header)
                self.write("owner.py", body)
                self.write(
                    "copy.py", body.replace("total", "other").replace("values", "items")
                )
                self.assertEqual(self.check()[1]["advisories"], [])

    def test_recursive_function_renaming_retains_clone_evidence(self) -> None:
        body = BODY.replace(
            "    return sorted(result)",
            "    if values:\n        return total(values[1:])\n    return sorted(result)",
        )
        self.write("owner.py", body)
        self.write("copy.py", body.replace("total", "other"))
        self.assertEqual(len(self.check()[1]["advisories"]), 1)

    def test_recursive_keywords_normalize_but_external_keywords_do_not(self) -> None:
        body = BODY.replace("return sorted(result)", "return total(values=values[1:])")
        self.write("owner.py", body)
        self.write("copy.py", body.replace("total", "other").replace("values", "items"))
        self.assertEqual(len(self.check()[1]["advisories"]), 1)
        body = BODY.replace("return sorted(result)", "return external(values=result)")
        self.write("owner.py", body)
        self.write("copy.py", body.replace("total", "other").replace("values", "items"))
        self.assertEqual(self.check()[1]["advisories"], [])

    def test_recursive_keyword_data_does_not_normalize_non_keyword_parameters(
        self,
    ) -> None:
        for signature in ("values, /, **options", "*values, **options", "**values"):
            with self.subTest(signature=signature):
                body = BODY.replace(
                    "def total(values):", f"def total({signature}):"
                ).replace("return sorted(result)", "return total(values=result)")
                self.write("owner.py", body)
                self.write(
                    "copy.py", body.replace("total", "other").replace("values", "items")
                )
                self.assertEqual(self.check("--base", "HEAD")[1]["advisories"], [])

    def test_baseline_retains_same_name_clone_occurrence_counts(self) -> None:
        indented = "".join("    " + line + "\n" for line in BODY.splitlines())
        existing = "if ENABLED:\n" + indented
        self.write("owner.py", existing)
        self.git("add", "owner.py")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "conditional baseline")
        self.write("owner.py", existing + "if OTHER:\n" + indented)
        code, report = self.check("--base", "HEAD")
        self.assertEqual(code, 0)
        self.assertEqual(len(report["advisories"]), 1)
        self.assertEqual(len(report["advisories"][0]["locations"]), 2)
        self.git("add", "owner.py")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "two existing clones")
        self.write("owner.py", "\n\n" + (existing + "if OTHER:\n" + indented))
        self.assertEqual(self.check("--base", "HEAD")[1]["advisories"], [])

    def test_git_reads_disable_lazy_fetch_after_caller_environment_filter(self) -> None:
        module = runpy.run_path(str(SCRIPT))
        with (
            patch.dict(os.environ, {"GIT_NO_LAZY_FETCH": "0"}),
            patch("subprocess.run") as invoked,
        ):
            invoked.return_value.stdout = b"fixture"
            self.assertEqual(module["git"](self.root, "rev-parse", "HEAD"), b"fixture")
            self.assertEqual(
                invoked.call_args.kwargs["env"].get("GIT_NO_LAZY_FETCH"), "1"
            )

    def test_missing_baseline_blob_is_unverified_without_aborting_remaining_scan(
        self,
    ) -> None:
        oid = self.git("rev-parse", "HEAD:owner.py")
        _fixture_resource(self.root / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
        self.write("copy.py", BODY.replace("total", "other"))
        code, report = self.check("--base", "HEAD")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "unverified")
        self.assertTrue(any("owner.py" in item for item in report["diagnostics"]))

    def test_nested_binding_scopes_do_not_erase_global_differences(self) -> None:
        for expression in (
            "[item for item in values]",
            "{item for item in values}",
            "{item: item for item in values}",
            "(item for item in values)",
            "(lambda item: item)",
        ):
            with self.subTest(expression=expression):
                body = BODY.replace(
                    "    return sorted(result)",
                    f"    nested = {expression}\n    return item(result)",
                )
                self.write("owner.py", body)
                self.write(
                    "copy.py", body.replace("total", "other").replace("item", "entry")
                )
                self.assertEqual(self.check()[1]["advisories"], [])

    def test_normalized_binding_markers_cannot_collide_with_global_calls(self) -> None:
        for bound, external in (("values", "local_0"), ("total", "recursive_self")):
            with self.subTest(bound=bound):
                self.write(
                    "owner.py", BODY.replace("sorted(result)", f"{bound}(result)")
                )
                self.write(
                    "copy.py",
                    BODY.replace("total", "other").replace(
                        "sorted(result)", f"{external}(result)"
                    ),
                )
                self.assertEqual(self.check()[1]["advisories"], [])

    def test_scan_targets_ignore_caller_repository_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GIT_DIR": str(self.root / "missing.git"),
                "GIT_INDEX_FILE": str(self.root / "missing-index"),
            },
        ):
            self.assertEqual(self.check("--base", "HEAD")[1]["status"], "pass")
            result = subprocess.run(
                [
                    "bash",
                    str(WRAPPER),
                    str(SCRIPT),
                    "--root",
                    str(self.root),
                    "--base",
                    "HEAD",
                ],
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "pass")

    def test_nested_baseline_clones_are_not_new(self) -> None:
        self.write("lib/owner.py", BODY)
        self.write("lib/copy.py", BODY.replace("total", "other"))
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "nested baseline")
        self.assertEqual(self.check("--base", "HEAD")[1]["advisories"], [])

    def test_sparse_omissions_are_unverified_but_normal_deletions_are_not(self) -> None:
        self.write("sparse.py", BODY)
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "sparse fixture")
        self.git("update-index", "--skip-worktree", "sparse.py")
        _fixture_resource(self.root / "sparse.py").unlink()
        code, report = self.check("--base", "HEAD")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "unverified")
        self.assertTrue(any("sparse.py" in item for item in report["diagnostics"]))
        self.git("update-index", "--no-skip-worktree", "sparse.py")
        self.assertEqual(self.check("--base", "HEAD")[1]["status"], "pass")

    def test_invalid_encoding_and_oversized_baselines_are_diagnostics(self) -> None:
        _fixture_resource(self.root / "bad.py").write_bytes(b"# invalid UTF-8\n\xff")
        self.write("large.py", "#" + "x" * 1048576)
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "bounded baseline")
        self.write("copy.py", BODY.replace("total", "other"))
        code, report = self.check("--base", "HEAD")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(len(report["advisories"]), 1)
        self.assertTrue(any("bad.py" in item for item in report["diagnostics"]))
        self.assertTrue(any("large.py" in item for item in report["diagnostics"]))
        self.write("bad.py", "def total(values):\n    return 0\n")
        self.write("large.py", "def total(values):\n    return 0\n")
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture",
                        }
                    ],
                }
            ),
        )
        code, report = self.check("--base", "HEAD", "--policy", "policy.json")
        self.assertEqual(code, 3)
        self.assertEqual(report["violations"], [])

    def test_renamed_exception_target_is_a_duplicate(self) -> None:
        body = BODY.replace(
            "    return sorted(result)",
            "    try:\n        return sorted(result)\n    except ValueError as error:\n        print(error)\n        return result",
        )
        self.write("owner.py", body)
        self.write("copy.py", body.replace("total", "other").replace("error", "exc"))
        self.assertEqual(len(self.check()[1]["advisories"]), 1)

    def test_fixture_git_ignores_caller_hooks_templates_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            caller = Path(directory)
            sentinel = caller / "hook-ran"
            hooks = caller / "template" / "hooks"
            _fixture_resource(hooks).mkdir(parents=True)
            hook = hooks / "pre-commit"
            _fixture_resource(hook).write_text(
                f'#!/bin/sh\ntouch "{sentinel}"\nexit 1\n'
            )
            _fixture_resource(hook).chmod(448)
            config = caller / "gitconfig"
            _fixture_resource(config).write_text(
                f"[core]\n hooksPath = {hooks}\n[init]\n templateDir = {hooks.parent}\n"
            )
            with patch.dict(
                os.environ,
                {
                    "GIT_CONFIG_GLOBAL": str(config),
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "core.hooksPath",
                    "GIT_CONFIG_VALUE_0": str(hooks),
                },
            ):
                self.git("-c", "init.templateDir=" + str(hooks.parent), "init", "-q")
                self.write("fixture.txt", "fixture commit\n")
                self.git("add", ".")
                self.git(
                    "-c", "commit.gpgsign=false", "commit", "-qm", "isolated hooks"
                )
            self.assertFalse(sentinel.exists())

    def test_module_control_flow_definitions_block_but_nested_scopes_do_not(
        self,
    ) -> None:
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture",
                        }
                    ],
                }
            ),
        )
        for body in (
            "if True:\n    def total(values):\n        return 0\n",
            "try:\n    def total(values):\n        return 0\nexcept Exception:\n    pass\n",
            "match 1:\n    case 1:\n        def total(values):\n            return 0\n",
        ):
            with self.subTest(body=body):
                self.write("copy.py", body)
                code, report = self.check("--base", "HEAD", "--policy", "policy.json")
                self.assertEqual(code, 1)
                self.assertEqual(report["violations"][0]["location"]["symbol"], "total")
        self.write(
            "copy.py",
            "def outer():\n    def total(values):\n        return 0\nclass Other:\n    if True:\n        def total(self):\n            return 0\n",
        )
        self.assertEqual(self.check("--base", "HEAD", "--policy", "policy.json")[0], 0)

    def test_old_duplicates_and_line_only_changes_do_not_reappear(self) -> None:
        self.write("copy.py", BODY.replace("total", "other"))
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "existing clone")
        self.write(
            "copy.py",
            "# moved without changing behaviour\n" + BODY.replace("total", "other"),
        )
        self.assertEqual(self.check()[1]["advisories"], [])

    def test_committed_branch_clone_is_new_against_target_merge_base(self) -> None:
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.write("copy.py", BODY.replace("total", "other"))
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "new clone on branch")
        self.assertEqual(len(self.check()[1]["advisories"]), 1)
        self.assertEqual(self.check("--base", "HEAD")[1]["advisories"], [])

    def test_imports_methods_and_out_of_scope_symbols_are_allowed(self) -> None:
        self.write("lib/owner.py", BODY)
        self.write(
            "lib/consumer.py",
            "from owner import total\nclass Other:\n    def total(self):\n        return 0\n",
        )
        self.write("other.py", "def total(values):\n    return 0\n")
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "lib/owner.py",
                            "symbol": "total",
                            "scope": "lib",
                            "reason": "fixture owner within lib",
                        }
                    ],
                }
            ),
        )
        self.assertEqual(self.check("--base", "HEAD", "--policy", "policy.json")[0], 0)

    def test_unparseable_baseline_does_not_prove_new_owner_violation(self) -> None:
        self.write("copy.py", "def total(\n")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "unparseable baseline")
        self.write("copy.py", "def total(values):\n    return 0\n")
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture",
                        }
                    ],
                }
            ),
        )
        code, report = self.check("--base", "HEAD", "--policy", "policy.json")
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(report["violations"], [])

    def test_distinct_conditions_calls_and_constants_are_not_clones(self) -> None:
        for name, body in (
            ("threshold.py", BODY.replace("> 3", "> 8")),
            ("call.py", BODY.replace("sorted(result)", "list(result)")),
            ("operator.py", BODY.replace("value * 2", "value / 2")),
        ):
            self.write(name, body)
        self.assertEqual(self.check()[1]["advisories"], [])

    def test_fixtures_generated_tiny_helpers_and_symlinks_are_excluded(self) -> None:
        self.write("tests/copy.py", BODY)
        self.write("generated/copy.py", BODY)
        self.write(
            "small.py", "def a(x):\n    return x + 1\ndef b(x):\n    return x + 1\n"
        )
        (self.root / "link.py").symlink_to(self.root / "owner.py")
        self.assertEqual(self.check()[1]["advisories"], [])

    def test_only_declared_top_level_single_owner_definition_blocks(self) -> None:
        policy = {
            "schema_version": 1,
            "boundaries": [
                {
                    "owner": "owner.py",
                    "symbol": "total",
                    "scope": ".",
                    "reason": "fixture contract: one authoritative total implementation",
                }
            ],
        }
        self.write("policy.json", json.dumps(policy))
        self.write("copy.py", BODY.replace("total", "other"))
        self.assertEqual(self.check("--base", "HEAD", "--policy", "policy.json")[0], 0)
        self.write("copy.py", "def total(values):\n    return 0\n")
        code, report = self.check("--base", "HEAD", "--policy", "policy.json")
        self.assertEqual(code, 1)
        self.assertEqual(len(report["violations"]), 1)

    def test_missing_target_with_violation_remains_blocked(self) -> None:
        self.write("copy.py", BODY)
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture owner",
                        }
                    ],
                }
            ),
        )
        code, report = self.check(
            "--policy", "policy.json", "--require-target-baseline"
        )
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "unverified")
        self.assertTrue(report["violations"])
        self.assertTrue(
            any("target baseline unavailable" in item for item in report["diagnostics"])
        )
        code, report = self.check("--policy", "policy.json", "--base", "HEAD")
        self.assertEqual((code, report["status"]), (1, "fail"))

    def test_uninspectable_declared_owner_preserves_diagnostic(self) -> None:
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture owner",
                        }
                    ],
                }
            ),
        )
        for content, diagnostic in (
            (b"def broken(:", "syntax unavailable"),
            (b"\xff", "not valid UTF-8"),
            (b"#" * 1048577, "inspection bound"),
        ):
            with self.subTest(diagnostic=diagnostic):
                _fixture_resource(self.root / "owner.py").write_bytes(content)
                code, report = self.check("--policy", "policy.json", "--base", "HEAD")
                self.assertEqual((code, report["status"]), (3, "unverified"))
                self.assertTrue(
                    any(
                        "owner.py:" in item and diagnostic in item
                        for item in report["diagnostics"]
                    )
                )
        self.write("owner.py", BODY)
        self.write("copy.py", BODY)
        self.write("broken.py", "def broken(:")
        code, report = self.check("--policy", "policy.json", "--base", "HEAD")
        self.assertEqual((code, report["status"]), (3, "unverified"))
        self.assertTrue(report["violations"])
        self.assertTrue(report["diagnostics"])
        self.write("owner.py", "value = 1\n")
        self.assertEqual(self.check("--policy", "policy.json", "--base", "HEAD")[0], 2)

    def test_policy_path_spellings_enforce_the_same_owner(self) -> None:
        for owner, scope, copy in (
            ("./owner.py", "./.", "copy.py"),
            ("lib//owner.py", "lib//", "lib/copy.py"),
        ):
            with self.subTest(owner=owner, scope=scope):
                if owner.startswith("lib"):
                    self.write("lib/owner.py", BODY)
                self.write(copy, "def total(values):\n    return 0\n")
                self.write(
                    "policy.json",
                    json.dumps(
                        {
                            "schema_version": 1,
                            "boundaries": [
                                {
                                    "owner": owner,
                                    "symbol": "total",
                                    "scope": scope,
                                    "reason": "fixture",
                                }
                            ],
                        }
                    ),
                )
                code, report = self.check("--base", "HEAD", "--policy", "policy.json")
                self.assertEqual(code, 1, report)
                self.assertEqual(len(report["violations"]), 1)
                self.assertEqual(report["violations"][0]["owner"], str(Path(owner)))

    def test_conditional_module_functions_enter_clone_groups(self) -> None:
        body = BODY.replace("total", "other")
        indented = "\n".join("    " + line for line in body.splitlines()) + "\n"
        for wrapped in (
            "if True:\n" + indented,
            "try:\n" + indented + "except Exception:\n    pass\n",
            "match 1:\n    case 1:\n"
            + "\n".join("        " + line for line in body.splitlines())
            + "\n",
        ):
            with self.subTest(wrapped=wrapped):
                self.write("copy.py", wrapped)
                code, report = self.check("--base", "HEAD")
                self.assertEqual(code, 0)
                self.assertEqual(len(report["advisories"]), 1)
                self.assertEqual(
                    {item["symbol"] for item in report["advisories"][0]["locations"]},
                    {"total", "other"},
                )
        for wrapped in ("class Example:\n" + indented, "def enclosing():\n" + indented):
            with self.subTest(wrapped=wrapped):
                self.write("copy.py", wrapped)
                self.assertEqual(self.check("--base", "HEAD")[1]["advisories"], [])

    def test_existing_owner_violation_is_not_a_new_failure(self) -> None:
        self.write("copy.py", "def total(values):\n    return 0\n")
        self.git("add", ".")
        self.git(
            "-c", "commit.gpgsign=false", "commit", "-qm", "existing boundary violation"
        )
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture",
                        }
                    ],
                }
            ),
        )
        self.assertEqual(self.check("--base", "HEAD", "--policy", "policy.json")[0], 0)

    def test_added_reserved_definition_counts_beyond_grandfathered_occurrence(
        self,
    ) -> None:
        existing = "if True:\n    def total(values):\n        return 0\n"
        self.write("copy.py", existing)
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "existing occurrence")
        self.write(
            "policy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "boundaries": [
                        {
                            "owner": "owner.py",
                            "symbol": "total",
                            "scope": ".",
                            "reason": "fixture",
                        }
                    ],
                }
            ),
        )
        self.write("copy.py", "\n\n" + existing)
        self.assertEqual(self.check("--base", "HEAD", "--policy", "policy.json")[0], 0)
        self.write(
            "copy.py",
            existing + "if False:\n    def total(values):\n        return 1\n",
        )
        code, report = self.check("--base", "HEAD", "--policy", "policy.json")
        self.assertEqual(code, 1)
        self.assertEqual(len(report["violations"]), 1)
        self.assertEqual(report["violations"][0]["location"]["symbol"], "total")

    def test_invalid_policy_base_and_unparseable_code_are_not_success_proof(
        self,
    ) -> None:
        self.write(
            "policy.json",
            '{"schema_version":1,"boundaries":[{"owner":"../outside.py"}]}',
        )
        self.assertEqual(self.check("--policy", "policy.json")[0], 2)
        self.assertEqual(self.check("--base", "missing-ref")[0], 2)
        self.write("bad.py", "def broken(\n")
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
