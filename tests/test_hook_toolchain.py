"""Exercise toolchain archive containment without privileged installation."""
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hook_toolchain_prepare", ROOT / "codex/scripts/prepare-hook-toolchain.py")
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class HookToolchainTests(unittest.TestCase):
    def test_validation_selector_isolates_modules_and_rejects_writable_fallback(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory).resolve()
            scripts = home / "dev/dots/codex/scripts"
            scripts.mkdir(parents=True)
            for name in ("codex-validation-lib.sh", "admit-hook-fixture.py", "migration_scope.py"):
                shutil.copyfile(ROOT / "codex/scripts" / name, scripts / name)
            temporary = home / "tmp"
            temporary.mkdir()
            workspace = home / "workspace"
            workspace.mkdir()
            marker = home / "poisoned"
            poison = '#!/bin/sh\nprintf poisoned >> "' + str(marker) + '"\nexit 97\n'
            binary_dir = home / ".venvs/pyyaml/bin"
            binary_dir.mkdir(parents=True)
            for name in ("python", "uv"):
                path = binary_dir / name
                path.write_text(poison)
                path.chmod(0o755)
            for name in ("tomllib", "yaml"):
                (workspace / (name + ".py")).write_text(
                    'open(' + repr(str(marker)) + ', "w").write("poisoned")\nraise RuntimeError("poison")\n')
            environment = {
                "HOME": str(home), "DOTS_TEST_HOME": str(home), "TMPDIR": str(temporary),
                "PATH": os.pathsep.join((str(Path(sys.executable).parent), str(binary_dir), "/usr/bin", "/bin")),
                "CODEX_VALIDATION_PYTHON": sys.executable,
            }
            command = ["/bin/bash", "-c", '. "$1" && codex_select_validation_python fixture',
                       "fixture", str(scripts / "codex-validation-lib.sh")]
            valid = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                   text=True, timeout=15, check=False)
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            self.assertEqual(valid.stdout.strip(), sys.executable)
            # A missing protected selection must fail instead of trying HOME,
            # PATH Python, mise or the uv fallback, even if those would work.
            environment["CODEX_VALIDATION_PYTHON"] = "/opt/dots-hook-tools/" + "0" * 64 + "/bin/python3"
            missing = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                     text=True, timeout=15, check=False)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("no Python", missing.stderr)
            self.assertFalse(marker.exists())

    def archive(self, directory, members):
        archive = directory / "payload.tar"
        with tarfile.open(archive, "w") as stream:
            for name, content, link in members:
                item = tarfile.TarInfo(name)
                if link is not None:
                    item.type = tarfile.SYMTYPE
                    item.linkname = link
                    stream.addfile(item)
                else:
                    item.size = len(content)
                    item.mode = 0o755
                    stream.addfile(item, io.BytesIO(content))
        return archive

    def test_internal_executable_link_retains_complete_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "output"
            payload.mkdir()
            archive = self.archive(root, [("bin/python3.12", b"fixture", None),
                                          ("bin/python3", b"", "python3.12")])
            PREPARE.extract(archive, payload)
            self.assertEqual((payload / "bin/python3").read_bytes(), b"fixture")
            self.assertTrue((payload / "bin/python3").is_symlink())

    def test_archive_traversal_and_external_links_leave_sentinel_unchanged(self):
        for members in (
            [("../sentinel", b"changed", None)],
            [("bin/python3", b"", "../../sentinel")],
            [("bin", b"", "/tmp"), ("bin/sentinel", b"changed", None)],
        ):
            with self.subTest(members=members), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                sentinel = root / "sentinel"
                sentinel.write_bytes(b"preserve")
                payload = root / "output"
                payload.mkdir()
                with self.assertRaises(ValueError):
                    PREPARE.extract(self.archive(root, members), payload)
                self.assertEqual(sentinel.read_bytes(), b"preserve")
