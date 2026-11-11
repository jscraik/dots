import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location('stage_home', Path(__file__).resolve().parents[1] / 'scripts/stage-home.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
TEMP_ROOT = Path('/tmp').resolve()

class StagingTests(unittest.TestCase):
    def test_account_home_descendant_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory) / 'child'
            target.mkdir()
            with mock.patch.object(MODULE.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=directory)):
                with self.assertRaises(ValueError):
                    MODULE.stage(target)
            self.assertEqual(list(target.iterdir()), [])

    def test_stages_defaults_without_auth_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory)
            (target / 'machine.local').write_text('retain this override')
            self.assertEqual(MODULE.stage(target), len(MODULE.FILES))
            snapshot = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            self.assertEqual(MODULE.stage(target), len(MODULE.FILES))
            self.assertEqual(snapshot, {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()})
            self.assertEqual((target / 'machine.local').read_text(), 'retain this override')
            self.assertFalse((target / '.codex/auth.json').exists())
            self.assertFalse((target / '.env').exists())

    def test_existing_machine_override_blocks_without_partial_install(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory)
            (target / '.config/ghostty').mkdir(parents=True)
            custom = target / '.config/ghostty/config'
            custom.write_text('font-size = 18\n')
            with self.assertRaisesRegex(ValueError, 'Existing different'):
                MODULE.stage(target)
            self.assertEqual(custom.read_text(), 'font-size = 18\n')
            self.assertFalse((target / '.Brewfile').exists())

    def test_symlink_directory_cannot_escape_target(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            target = Path(directory)
            (target / '.config').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                MODULE.stage(target)
            self.assertEqual(list(Path(outside).iterdir()), [])
            self.assertFalse((target / '.Brewfile').exists())

    def test_dangling_symlink_file_is_not_replaced(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory)
            link = target / '.Brewfile'
            link.symlink_to(target / 'missing')
            with self.assertRaises(ValueError):
                MODULE.stage(target)
            self.assertTrue(link.is_symlink())

    def test_source_is_not_a_target(self):
        with self.assertRaises(ValueError):
            MODULE.stage(MODULE.ROOT)
        with self.assertRaises(ValueError):
            MODULE.stage(Path.home())

if __name__ == '__main__':
    unittest.main()
