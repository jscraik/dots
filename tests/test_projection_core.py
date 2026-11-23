"""Exercise the accepted projector with an explicit synthetic resource allowlist."""
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from policy_fixture import PolicyFixture

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('preview_core_fixture', ROOT / 'scripts/preview-codex.py')
PREVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREVIEW)


class ProjectionCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path('/tmp').resolve())
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name).resolve()
        self.repo, self.home = root / 'dots', root / 'home'
        self.home.mkdir()
        # No repository walk: only these two reviewed source files are copied.
        for source, destination in [
            ('scripts/link-configs.sh', 'scripts/link-configs.sh'),
            ('tests/fixtures/projection-map.json', 'codex/projection-map.json'),
        ]:
            target = self.repo / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
        generated = self.repo / 'codex/generated/preview.toml'
        generated.parent.mkdir()
        generated.write_bytes(PREVIEW.render(ROOT / 'tests/fixtures/codex-machine.json'))
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.home),
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        subprocess.run(['git', 'init', '-q', str(self.repo)], env=self.env, check=True,
                       capture_output=True, timeout=20)

    def run_projector(self, *args):
        return subprocess.run(['/bin/bash', '-p',
                               str(self.repo / 'scripts/link-configs.sh'),
                               *args], env=self.env, cwd=self.repo,
                              capture_output=True, text=True, timeout=30, check=False)

    def test_repair_check_repeat_preserves_runtime(self):
        codex = self.home / '.codex'
        codex.mkdir()
        (codex / 'agents').mkdir()
        sentinels = ['config.toml', 'auth.json', 'session_index.jsonl', 'hooks.json', 'agents/manifest.json']
        for name in sentinels:
            (codex / name).write_text('synthetic sentinel')
        args = ['--scope', 'codex', '--codex-home', str(codex)]
        for mode in ['--repair', '--check', '--repair']:
            result = self.run_projector(mode, *args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in sentinels:
                self.assertEqual((codex / name).read_text(), 'synthetic sentinel')
        self.assertEqual((codex / 'preview.toml').read_bytes(),
                         (self.repo / 'codex/generated/preview.toml').read_bytes())

    def test_sanitized_launcher_blocks_startup_injection(self):
        startup = self.home.parent / 'startup.sh'
        sentinel = self.home.parent / 'injected'
        startup.write_text(f'touch "{sentinel}"\n')
        self.env.update(BASH_ENV=str(startup), ENV=str(startup))
        result = self.run_projector('--repair', '--scope', 'codex',
                                    '--codex-home', str(self.home / '.codex'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(sentinel.exists())

    def test_home_admission_precedes_selected_fixture_interpreter(self):
        fixture = PolicyFixture(self)
        self.addCleanup(fixture.assert_preserved, self)
        environment = fixture.env | {'HOME': '/missing/home',
                                     'CODEX_VALIDATION_PYTHON': '/missing/python'}
        result = subprocess.run(['/bin/bash', '-p', str(fixture.repo / 'scripts/link-configs.sh'), '--help'],
            cwd=fixture.repo, env=environment, capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('DOTS_TEST_HOME', result.stderr)

    def test_sanitized_launcher_ignores_exported_functions(self):
        marker = self.home.parent / 'exported-function-ran'
        self.env['BASH_FUNC_dirname%%'] = (
            '() { /usr/bin/touch "' + str(marker) + '"; /usr/bin/dirname "$@"; }')
        result = self.run_projector('--help')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists())

    def test_selected_interpreter_with_spaces_runs_admission(self):
        fixture = PolicyFixture(self)
        self.addCleanup(fixture.assert_preserved, self)
        selected = fixture.home / 'selected python'
        marker = fixture.home / 'selected-python-ran'
        selected.write_text('#!/bin/sh\nprintf selected > ' + shlex.quote(str(marker))
                            + '\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
        selected.chmod(0o700)
        environment = fixture.env | {'CODEX_VALIDATION_PYTHON': str(selected)}
        command = ['/bin/bash', '-p', str(fixture.repo / 'scripts/link-configs.sh'), '--help']
        result = subprocess.run(command, cwd=fixture.repo, env=environment | {'HOME': '/missing/home'},
            capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        result = subprocess.run(command, cwd=fixture.repo, env=environment,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(marker.exists())
        selected.write_text('#!/bin/sh\nexit 1\n')
        result = subprocess.run(command, cwd=fixture.repo, env=environment,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertIn('Python 3.9 or later', result.stderr)

    def test_missing_source_and_wrong_scope_fail(self):
        target = self.home / '.codex'
        result = self.run_projector('--repair')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())
        (self.repo / 'codex/generated/preview.toml').unlink()
        result = self.run_projector('--check', '--scope', 'codex', '--codex-home', str(target))
        self.assertNotEqual(result.returncode, 0)

    def test_external_symlink_and_expanded_map_fail_before_writes(self):
        outside = self.home.parent / 'outside'
        outside.mkdir()
        target = self.home / '.codex'
        target.symlink_to(outside, target_is_directory=True)
        args = ['--repair', '--scope', 'codex', '--codex-home', str(target)]
        self.assertNotEqual(self.run_projector(*args).returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])
        target.unlink()
        (self.repo / 'codex/projection-map.json').write_text('{}')
        self.assertNotEqual(self.run_projector(*args).returncode, 0)
        self.assertFalse(target.exists())

    def test_traversal_home_is_rejected(self):
        self.env['HOME'] = str(self.home / '..' / 'home')
        result = self.run_projector('--repair', '--scope', 'codex',
                                    '--codex-home', self.env['HOME'] + '/.codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('existing disposable HOME', result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
