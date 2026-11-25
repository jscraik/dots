import importlib.util
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SPEC = importlib.util.spec_from_file_location('stage_home', Path(__file__).resolve().parents[1] / 'scripts/stage-home.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
TEMP_ROOT = Path('/tmp').resolve()

class StagingTests(unittest.TestCase):
    def test_temp_root_is_refused_before_opening(self):
        with mock.patch.object(MODULE, 'open_directory') as open_directory:
            with self.assertRaisesRegex(ValueError, 'Target must be a disposable directory'):
                MODULE.stage(TEMP_ROOT)
            open_directory.assert_not_called()

    def test_account_home_descendant_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory) / 'child'
            target.mkdir()
            with (mock.patch.object(MODULE.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=directory)),
                  self.assertRaises(ValueError)):
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
            paths_before = set(target.rglob('*'))
            stderr = StringIO()
            with (mock.patch('sys.argv', ['stage-home.py', '--target-home', directory]),
                  redirect_stderr(stderr), self.assertRaises(SystemExit) as result):
                MODULE.main()
            self.assertEqual(result.exception.code, 1)
            self.assertIn('Staging failed: Existing different file preserved', stderr.getvalue())
            self.assertEqual(custom.read_text(), 'font-size = 18\n')
            self.assertEqual(set(target.rglob('*')), paths_before)

    def test_partial_write_reports_failure_and_preserves_output_on_retry(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory)
            first = target / '.Brewfile'
            partial = target / '.config/mise/config.toml'
            fdopen = MODULE.os.fdopen

            @contextmanager
            def fail_during_second_write(fd, mode):
                with fdopen(fd, mode) as stream:
                    if mode == 'wb' and partial.exists():
                        def write(payload):
                            stream.write(payload[:1])
                            raise OSError('injected write failure')

                        yield SimpleNamespace(write=write)
                    else:
                        yield stream

            stderr = StringIO()
            with (mock.patch('sys.argv', ['stage-home.py', '--target-home', directory]),
                  mock.patch.object(MODULE.os, 'fdopen', side_effect=fail_during_second_write),
                  redirect_stderr(stderr), self.assertRaises(SystemExit) as result):
                MODULE.main()
            self.assertEqual(result.exception.code, 1)
            self.assertEqual(stderr.getvalue(), 'Staging failed: injected write failure\n')
            self.assertEqual(first.read_bytes(), (MODULE.ROOT / 'Brewfile').read_bytes())
            payload = (MODULE.ROOT / 'mise/config.toml').read_bytes()
            self.assertEqual(partial.read_bytes(), payload[:1])
            with self.assertRaisesRegex(ValueError, 'Existing different file preserved'):
                MODULE.stage(target)
            self.assertEqual(partial.read_bytes(), payload[:1])
            self.assertFalse((target / '.config/mise/mise.lock').exists())
            first_inode = first.stat().st_ino
            partial.unlink()
            self.assertEqual(MODULE.stage(target), len(MODULE.FILES))
            self.assertEqual(partial.read_bytes(), payload)
            self.assertEqual(first.stat().st_ino, first_inode)

    def test_new_conflict_after_preflight_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory)
            custom = target / '.Brewfile'
            open_file = MODULE.os.open

            def open_after_new_file(path, flags, *args, **kwargs):
                if path == custom.name and flags & MODULE.os.O_EXCL:
                    custom.write_bytes(b'new local file')
                return open_file(path, flags, *args, **kwargs)

            with (mock.patch.object(MODULE.os, 'open', side_effect=open_after_new_file),
                  self.assertRaisesRegex(ValueError, 'Concurrent target conflict preserved')):
                MODULE.stage(target)
            self.assertEqual(custom.read_bytes(), b'new local file')
            self.assertEqual(list(target.iterdir()), [custom])

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
