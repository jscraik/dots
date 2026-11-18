"""Exercise readiness resources in real disposable managed Git worktrees."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('readiness_repository_scope', ROOT / 'codex/scripts/deployment_scope.py')
SCOPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCOPE)


class ReadinessRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve() / 'home'
        self.source = self.home / 'dev/source'
        self.source.mkdir(parents=True)
        self.root = self.home / '.codex/worktrees/slot/repository'
        self.root.parent.mkdir(parents=True)
        environment = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin',
                       'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}
        for args in (['init', '-q', str(self.source)],
                     ['-C', str(self.source), '-c', 'user.name=Fixture', '-c',
                      'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'fixture'],
                     ['-C', str(self.source), 'worktree', 'add', '--detach', str(self.root), 'HEAD']):
            subprocess.run(['git', *args], env=environment, check=True, capture_output=True, timeout=15)
        (self.root / '.tmp').mkdir()
        self.scope = self.root / '.tmp/scope.txt'
        self.scope.write_text('src/example.py\n')
        self.receipt = self.root / '.tmp/receipt.json'
        self.data = {'mode': 'machine', 'home': str(self.home),
                     'state_dir': str(self.home / 'installation'), 'package_digest': 'fixture',
                     'session_evidence_root': str(self.home / 'sessions')}
        policy = {'projects': {str(self.home / 'dev'): {'trust_level': 'trusted'}}}
        for patcher in (mock.patch.object(SCOPE, 'context', return_value=self.data),
                        mock.patch.object(SCOPE, '_read_policy', return_value=policy),
                        mock.patch.object(SCOPE, 'native_temp_roots', return_value=[])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_contained_input_and_atomic_receipt_keep_general_roots_closed(self):
        exclude = self.source / '.git/info/exclude'
        exclude.write_text(exclude.read_text() + '\n/.tmp/pr-readiness.v1.json\n')
        with self.assertRaises(ValueError):
            SCOPE.require_path(self.root)
        self.assertEqual(SCOPE.repository_read(self.root, self.scope), b'src/example.py\n')
        self.assertEqual(SCOPE.repository_receipt(self.root, self.source / '.git/receipt'),
                         self.root / '.tmp/pr-readiness.v1.json')
        SCOPE.write_repository_receipt(self.root, self.receipt, b'{"status":"blocked"}')
        self.assertEqual(SCOPE.repository_read(self.root, self.receipt), b'{"status":"blocked"}')

    def test_outside_alias_hardlink_and_git_paths_are_refused(self):
        outside = self.home / 'private'
        outside.mkdir()
        (outside / 'sentinel').write_text('preserve')
        (self.root / 'alias').symlink_to(outside, target_is_directory=True)
        hardlink = self.root / '.tmp/hardlink.json'
        os.link(outside / 'sentinel', hardlink)
        for path in (outside / 'sentinel', self.root / 'alias/sentinel', hardlink,
                     self.root / '.git', self.root / '.tmp/../escape.json'):
            for output in (False, True):
                with self.subTest(path=path.name, output=output), self.assertRaises(ValueError):
                    SCOPE.require_repository_path(self.root, path, output=output)
        self.assertEqual((outside / 'sentinel').read_text(), 'preserve')

    def test_changed_metadata_and_missing_parent_refuse_receipt(self):
        marker = (self.root / '.git').read_text()
        (self.root / '.git').write_text('gitdir: /unselected/.git/worktrees/other\n')
        with self.assertRaises((ValueError, OSError)):
            SCOPE.write_repository_receipt(self.root, self.receipt, b'blocked')
        (self.root / '.git').write_text(marker)
        (self.root / '.tmp').rename(self.root / 'old-tmp')
        with self.assertRaises((ValueError, OSError)):
            SCOPE.write_repository_receipt(self.root, self.receipt, b'blocked')
        self.assertFalse(self.receipt.exists())

    def test_metadata_replacement_before_publication_keeps_receipt_absent(self):
        original = SCOPE.require_repository_path
        calls = []

        def replace_metadata(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                (self.root / '.git').write_text('gitdir: /unselected/.git/worktrees/other\n')
            return original(*args, **kwargs)

        with mock.patch.object(SCOPE, 'require_repository_path', side_effect=replace_metadata):
            with self.assertRaises((ValueError, OSError)):
                SCOPE.write_repository_receipt(self.root, self.receipt, b'blocked')
        self.assertFalse(self.receipt.exists())
        self.assertFalse(list((self.root / '.tmp').glob('.readiness-*')))

    def test_unsafe_receipt_leaves_and_stale_identity_are_refused(self):
        for kind in ('dangling', 'fifo', 'directory', 'writable'):
            path = self.root / '.tmp' / (kind + '.json')
            if kind == 'dangling':
                path.symlink_to(self.home / 'absent')
            elif kind == 'fifo':
                os.mkfifo(path)
            elif kind == 'directory':
                path.mkdir()
            else:
                path.write_text('preserve')
                path.chmod(0o666)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                SCOPE.write_repository_receipt(self.root, path, b'blocked')
        identity = SCOPE.repository_identity(self.root)
        self.root.chmod(0o700)
        with self.assertRaises(ValueError):
            SCOPE.require_repository_identity(self.root, identity)
        with self.assertRaises(ValueError):
            SCOPE.write_repository_receipt(self.root, self.receipt, b'blocked', identity)
        self.assertFalse(self.receipt.exists())
