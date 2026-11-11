import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('preview', ROOT / 'scripts/preview-codex.py')
PREVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREVIEW)


class CodexPreviewTests(unittest.TestCase):
    def test_operator_path_preserves_local_state_and_repeats(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory).resolve()
            for name in ['.codex/config.toml', '.codex/auth.json',
                         '.codex/sessions/thread.jsonl', '.codex/state.sqlite',
                         '.codex/hooks.json', '.codex/session_index.jsonl']:
                path = home / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic sentinel')
            before = {p: p.read_bytes() for p in home.rglob('*') if p.is_file()}
            command = [sys.executable, '-B', str(ROOT / 'scripts/preview-codex.py'),
                       '--machine-input', str(ROOT / 'tests/fixtures/codex-machine.json'),
                       '--target-home', str(home)]
            for _ in range(2):
                result = subprocess.run(command, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                for path, payload in before.items():
                    self.assertEqual(path.read_bytes(), payload)
            config = tomllib.loads((home / '.dots-preview/codex-config.toml').read_text())
            self.assertEqual(config['sandbox_mode'], 'read-only')

    def test_injection_is_one_quoted_path(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            path = Path(directory).resolve() / 'input.json'
            value = '/synthetic/quote"[policy]'
            path.write_text(json.dumps({'project_root': value}))
            parsed = tomllib.loads(PREVIEW.render(path).decode())
            self.assertEqual(set(parsed['projects']), {value})

    def test_invalid_input_never_stages(self):
        inputs = ['{}', '[]', '{"project_root":"/one","project_root":"/two"}',
                  '{"project_root":"/work","token":"synthetic"}',
                  '{"project_root":"relative"}', '{"project_root":"/x/../y"}',
                  '{"project_root":null}', '{"project_root":"/x\\nfield"}']
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            root = Path(directory).resolve()
            source = root / 'machine.json'
            for body in inputs:
                source.write_text(body)
                with self.assertRaises(ValueError):
                    PREVIEW.render(source)

    def test_conflict_and_symlink_leave_state_unchanged(self):
        payload = PREVIEW.render(ROOT / 'tests/fixtures/codex-machine.json')
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory).resolve()
            target = home / '.dots-preview/codex-config.toml'
            target.parent.mkdir()
            target.write_bytes(b'other')
            with self.assertRaises(ValueError):
                PREVIEW.STAGE.stage(home, preview=payload)
            self.assertFalse((home / '.Brewfile').exists())
            self.assertEqual(target.read_bytes(), b'other')
            target.unlink()
            target.symlink_to(home / 'missing')
            with self.assertRaises(ValueError):
                PREVIEW.STAGE.stage(home, preview=payload)
            self.assertTrue(target.is_symlink())

    def test_machine_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            link = Path(directory).resolve() / 'machine.json'
            link.symlink_to(ROOT / 'tests/fixtures/codex-machine.json')
            with self.assertRaises(OSError):
                PREVIEW.render(link)

    def test_cli_rejects_private_extra_field_before_writes(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            root = Path(directory).resolve()
            home = root / 'home'
            home.mkdir()
            source = root / 'input.json'
            source.write_text('{"project_root":"/synthetic","secret":"sentinel-private"}')
            result = subprocess.run(
                [sys.executable, '-B', str(ROOT / 'scripts/preview-codex.py'),
                 '--machine-input', str(source), '--target-home', str(home)],
                capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('sentinel-private', result.stdout + result.stderr)
            self.assertEqual(list(home.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
