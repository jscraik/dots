"""Installed Codex loading the complete projected policy, without model turns."""
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace

from policy_fixture import PolicyFixture
from test_hook_discovery import AppServer


@unittest.skipUnless(os.environ.get('DOTS_CODEX_BIN'), 'DOTS_CODEX_BIN required for full projected-policy runtime proof')
class ProjectedPolicyRuntimeTests(unittest.TestCase):
    def test_launcher_cleanup_preserves_external_targets_and_rejects_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, outside = root / 'home', root / 'outside'
            runtime = home / '.codex'
            launchers = runtime / 'tmp/arg0'
            launchers.mkdir(parents=True)
            outside.mkdir()
            sentinel = outside / 'keep'
            sentinel.write_text('preserved')
            (launchers / 'wrapper').symlink_to(sentinel)
            fixture = SimpleNamespace(home=home, runtime=runtime)
            self.clear_native_launchers(fixture)
            self.assertFalse(launchers.exists())
            self.assertEqual(sentinel.read_text(), 'preserved')
            launchers.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(AssertionError):
                self.clear_native_launchers(fixture)
            self.assertEqual(sentinel.read_text(), 'preserved')
            launchers.unlink()
            launchers.parent.rmdir()
            launchers.parent.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(AssertionError):
                self.clear_native_launchers(fixture)
            self.assertEqual(sentinel.read_text(), 'preserved')

    def clear_native_launchers(self, fixture):
        # Older CLIs leave external executable symlinks here after shutdown.
        # Remove only fixture-owned transient launchers, never admit the links
        # as projection resources or clean any live runtime directory.
        launchers = fixture.runtime / 'tmp/arg0'
        self.assertFalse(launchers.is_symlink())
        self.assertTrue(launchers.resolve().is_relative_to(fixture.home.resolve()))
        if launchers.exists():
            shutil.rmtree(launchers)

    def test_full_policy_loading_and_hook_discovery(self):
        fixture = PolicyFixture(self)
        self.addCleanup(fixture.assert_preserved, self)
        result = fixture.project()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        server = AppServer(fixture, strict_config=True, enable_hooks=False)
        self.addCleanup(server.close)
        info = server.rpc('initialize', {
            'clientInfo': {'name': 'dots-full-policy-proof', 'version': '1.0.0'},
            'capabilities': {'experimentalApi': True},
        })
        server.process.stdin.write(json.dumps({'method': 'initialized', 'params': {}}) + '\n')
        server.process.stdin.flush()
        config = server.rpc('config/read', {'cwd': str(fixture.repo), 'includeLayers': True})
        self.assertEqual(config['config']['approval_policy'], fixture.base.root['approval_policy'])
        self.assertEqual(config['config']['approvals_reviewer'], 'auto_review')
        self.assertTrue(config['config']['features']['hooks'])
        result = server.rpc('hooks/list', {'cwds': [str(fixture.repo)]})
        self.assertEqual(len(result['data']), 1)
        entry = result['data'][0]
        self.assertFalse(entry['warnings'], entry)
        self.assertFalse(entry['errors'], entry)
        self.assertEqual(len(entry['hooks']), 29)
        self.assertTrue(all(hook['sourcePath'] == str(fixture.target) for hook in entry['hooks']))
        self.assertTrue(all(hook['trustStatus'] == 'untrusted' for hook in entry['hooks']))
        self.assertNotIn('hooks', tomllib.loads((fixture.codex / 'config.toml').read_text()))
        print('Full projected policy loaded with 29 hooks: ' + info.get('userAgent', 'unknown'))
        server.close()
        self.clear_native_launchers(fixture)
        result = fixture.project('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_standalone_profiles_load_through_native_metadata_route(self):
        fixture = PolicyFixture(self)
        self.addCleanup(fixture.assert_preserved, self)
        result = fixture.project()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ('docs', 'oss-local', 'oss-local-code', 'oss-local-fallback',
                     'oss-security', 'oss-cloud', 'oss-inspect'):
            with self.subTest(profile=name):
                source = fixture.runtime / (name + '.config.toml')
                text = source.read_text()
                expected = tomllib.loads(text)
                # mcp list reads configured metadata; it does not invoke the
                # configured servers. Force file-only credential storage so
                # the fixture cannot consult the caller's system keychain.
                result = subprocess.run([os.environ['DOTS_CODEX_BIN'], '--profile', name,
                    '-c', 'mcp_oauth_credentials_store="file"', 'mcp', 'list', '--json'],
                    env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=20, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                servers = json.loads(result.stdout)
                if name.startswith('oss-'):
                    self.assertTrue(all(not server.get('enabled', True) for server in servers), name)
                    self.assertEqual(expected['default_permissions'], 'readonly-net')
        print('Seven native profile metadata loads passed; no model or MCP server execution')
