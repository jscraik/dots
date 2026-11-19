import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiSupplyChainTests(unittest.TestCase):
    def test_circleci_image_is_digest_pinned(self):
        config = (ROOT / ".circleci/config.yml").read_text()
        self.assertRegex(
            config,
            r"(?m)^\s+- image: cimg/python:3\.12\.8@sha256:[0-9a-f]{64}$",
        )

    def test_circleci_installs_the_complete_hash_locked_file(self):
        config = (ROOT / ".circleci/config.yml").read_text()
        self.assertIn(
            "pip install --disable-pip-version-check --require-hashes "
            "-r requirements/codex-validation-ci.lock",
            config,
        )
        self.assertNotIn("pip install --disable-pip-version-check -r requirements/codex-validation.txt", config)

    def test_hash_lock_covers_existing_pins_and_ruff(self):
        lock_lines = (ROOT / "requirements/codex-validation-ci.lock").read_text().splitlines()
        packages = {}
        index = 0
        while index < len(lock_lines):
            line = lock_lines[index].strip()
            index += 1
            if not line or line.startswith("#"):
                continue
            self.assertTrue(line.endswith("\\"), f"{line!r} is not pinned")
            requirement = line[:-1].strip()
            self.assertRegex(requirement, r"^[A-Za-z0-9_.-]+==[^\\\s]+$")
            package, version = requirement.split("==", 1)
            hashes = []
            while index < len(lock_lines) and lock_lines[index].lstrip().startswith("--hash="):
                hash_line = lock_lines[index].strip()
                index += 1
                continues = index < len(lock_lines) and lock_lines[index].lstrip().startswith("--hash=")
                self.assertEqual(hash_line.endswith("\\"), continues,
                                 f"{package} has a detached hash line: {hash_line!r}")
                hashes.append(hash_line.removesuffix("\\").strip())
            self.assertTrue(hashes, f"{package} is missing hashes")
            self.assertTrue(all(re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", item) for item in hashes))
            packages[package.lower().replace("_", "-")] = version

        direct_pins = {}
        for line in (ROOT / "requirements/codex-validation.txt").read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                package, version = line.split("==", 1)
                direct_pins[package.lower().replace("_", "-")] = version

        self.assertEqual(
            {name: packages.get(name) for name in direct_pins},
            direct_pins,
        )
        ruff_version = tomllib.loads((ROOT / "mise/config.toml").read_text())["tools"]["ruff"]
        self.assertEqual(packages.get("ruff"), ruff_version)


if __name__ == "__main__":
    unittest.main()
