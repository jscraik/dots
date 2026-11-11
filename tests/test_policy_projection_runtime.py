"""Installed Codex loading the complete projected policy, without model turns."""
import json
import os
import subprocess
import tomllib
import unittest

from policy_fixture import PolicyFixture
from test_hook_discovery import AppServer


@unittest.skipUnless(os.environ.get('DOTS_CODEX_BIN'), 'DOTS_CODEX_BIN required for full projected-policy runtime proof')
class ProjectedPolicyRuntimeTests(unittest.TestCase):
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
        print('Full projected policy loaded with 29 hooks: ' + info.get('userAgent', 'unknown'))

        states = {hook['key']: {'enabled': True, 'trusted_hash': hook['currentHash']} for hook in entry['hooks']}
        # Consent is canonical-owned in this migration. Capture fresh fixture
        # hashes into the fixture source, then project; never add a runtime-only
        # exception or reuse the original machine's consent.
        response = server.rpc('config/value/write', {'filePath': str(fixture.runtime / 'config.toml'),
            'keyPath': 'hooks.state', 'value': states, 'mergeStrategy': 'replace'})
        self.assertEqual(response['status'], 'ok')
        server.close()
        # The API intentionally writes only user config. Reconstruct this
        # fixture's canonical input from its existing policy plus ONLY the
        # explicitly selected native hashes, never the entire runtime file.
        import test_governance_port as governance
        canonical = tomllib.loads((fixture.codex / 'config.toml').read_text())
        canonical['hooks']['state'] = states
        (fixture.codex / 'config.toml').write_text(governance.GEN.toml_document(canonical))
        self.assertEqual(fixture.project().returncode, 0)
        result = fixture.script('validate-codex-config.py')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        consented = AppServer(fixture, strict_config=True, enable_hooks=False)
        self.addCleanup(consented.close)
        consented.rpc('initialize', {'clientInfo': {'name': 'dots-full-policy-proof', 'version': '1.0.0'},
                                    'capabilities': {'experimentalApi': True}})
        result = consented.rpc('hooks/list', {'cwds': [str(fixture.repo)]})
        self.assertTrue(all(hook['trustStatus'] == 'trusted' for hook in result['data'][0]['hooks']))
        self.assertEqual(len(result['data'][0]['hooks']), 29)
        consented.close()
        self.assertEqual(fixture.project('--check').returncode, 0)

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
