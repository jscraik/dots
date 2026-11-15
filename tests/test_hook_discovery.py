"""Installed Codex discovery and consent lifecycle, without starting a turn."""
import json
import os
import queue
import re
import subprocess
import threading
import time
import unittest
from pathlib import Path

from hook_fixture import HookFixture


class AppServer:
    def __init__(self, fixture, *, strict_config=False, enable_hooks=True):
        cli = Path(os.environ['DOTS_CODEX_BIN'])
        if not cli.is_absolute() or not cli.is_file():
            raise ValueError('DOTS_CODEX_BIN must name an installed CLI by absolute path')
        options = (['--strict-config'] if strict_config else []) + (['--enable', 'hooks'] if enable_hooks else [])
        self.process = subprocess.Popen([str(cli), 'app-server', '--listen', 'stdio://', *options],
            cwd=fixture.repo, env=fixture.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        self.lines, self.errors = queue.Queue(), []
        self.number = 0
        self.stdout_thread = threading.Thread(target=self.responses, daemon=True)
        self.stderr_thread = threading.Thread(target=self.read, args=(self.process.stderr, self.errors.append), daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

    @staticmethod
    def read(stream, receive):
        for line in stream:
            receive(line)

    def responses(self):
        self.read(self.process.stdout, self.lines.put)
        self.lines.put(None)

    def rpc(self, method, params):
        self.number += 1
        request_id = self.number
        try:
            self.process.stdin.write(json.dumps({'id': request_id, 'method': method, 'params': params}) + '\n')
            self.process.stdin.flush()
        except BrokenPipeError as exc:
            self.stderr_thread.join(timeout=1)
            raise RuntimeError('App-server exited: ' + ''.join(self.errors)[-1000:]) from exc
        deadline = time.monotonic() + 15
        for _ in range(50):
            try:
                line = self.lines.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise RuntimeError('App-server timed out: ' + ''.join(self.errors)[-1000:]) from exc
            if line is None:
                self.stderr_thread.join(timeout=1)
                raise RuntimeError('App-server exited: ' + ''.join(self.errors)[-1000:])
            message = json.loads(line)
            if message.get('id') == request_id:
                if 'error' in message:
                    raise RuntimeError(f'{method}: {message["error"]}')
                return message['result']
        raise RuntimeError('App-server returned no matching response')

    def close(self):
        if getattr(self, 'closed', False):
            return
        self.closed = True
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        for thread in (self.stdout_thread, self.stderr_thread):
            thread.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


@unittest.skipUnless(os.environ.get('DOTS_CODEX_BIN'), 'DOTS_CODEX_BIN required for installed-runtime proof')
class HookDiscoveryTests(unittest.TestCase):
    def test_discovery_consent_changes_and_revocation(self):
        fixture = HookFixture(self)
        self.addCleanup(fixture.assert_preserved, self)
        # A separate minimal discovery config prevents plugin/MCP auth or model
        # use. It replaces only fixture config; it is not the generated policy.
        config = fixture.runtime / 'config.toml'
        config.write_text('approval_policy = "on-request"\nsandbox_mode = "read-only"\n'
                          'check_for_update_on_startup = false\n'
                          'model = "fixture-model"\nmodel_provider = "fixture"\n'
                          '[model_providers.fixture]\nname = "Local inert fixture"\n'
                          'base_url = "http://127.0.0.1:1/v1"\nwire_api = "responses"\n'
                          'requires_openai_auth = false\n[features]\nhooks = true\n'
                          'plugin_hooks = false\n[analytics]\nenabled = false\n')
        def start():
            instance = AppServer(fixture)
            self.addCleanup(instance.close)
            info = instance.rpc('initialize', {
                'clientInfo': {'name': 'dots-isolated-hook-proof', 'version': '1.0.0'},
                'capabilities': {'experimentalApi': True},
            })
            instance.process.stdin.write(json.dumps({'method': 'initialized', 'params': {}}) + '\n')
            instance.process.stdin.flush()
            return instance, info

        server, info = start()

        def hooks():
            result = server.rpc('hooks/list', {'cwds': [str(fixture.repo)]})
            self.assertEqual(len(result['data']), 1, result)
            entry = result['data'][0]
            self.assertFalse(entry['errors'], entry)
            self.assertFalse(entry['warnings'], entry)
            self.assertTrue(entry['hooks'], entry)
            self.assertTrue(all(hook['sourcePath'] == str(fixture.target) for hook in entry['hooks']))
            return entry['hooks']

        discovered = hooks()
        expected = sum(len(group['hooks']) for groups in json.loads(fixture.target.read_text())['hooks'].values() for group in groups)
        self.assertEqual(len(discovered), expected)
        self.assertTrue(all(hook['trustStatus'] == 'untrusted' for hook in discovered), discovered)
        self.assertTrue(all(re.fullmatch(r'sha256:[0-9a-f]{64}', hook['currentHash']) for hook in discovered))
        self.assertFalse(any(hook.get('statusMessage') for hook in discovered))

        # An ephemeral loaded thread exercises runtime state without a model
        # turn. Its provider is local and inert; no production auth is copied.
        thread_id = server.rpc('thread/start', {
            'cwd': str(fixture.repo), 'ephemeral': True,
        })['thread']['id']

        def loaded_hooks():
            entry = server.rpc('hooks/list', {'threadId': thread_id})['data'][0]
            self.assertFalse(entry['errors'], entry)
            self.assertFalse(entry['warnings'], entry)
            self.assertEqual({hook['key'] for hook in entry['hooks']},
                             {hook['key'] for hook in discovered})
            return entry['hooks']

        self.assertTrue(all(hook['trustStatus'] == 'untrusted' for hook in loaded_hooks()))

        # Use the installed config API to opt into only the discovered fixture
        # definitions. No production trust hashes are copied or inferred.
        states = {hook['key']: {'enabled': True, 'trusted_hash': hook['currentHash']} for hook in discovered}

        def consent(value):
            response = server.rpc('config/value/write', {'filePath': str(config),
                'keyPath': 'hooks.state', 'value': value, 'mergeStrategy': 'replace'})
            self.assertEqual(response['status'], 'ok', response)
            self.assertEqual(response['filePath'], str(config))

        consent(states)
        # Cwd discovery reads disk, not the loaded thread's runtime. A successful
        # value write alone must not be mistaken for active hook acceptance.
        self.assertTrue(all(hook['trustStatus'] == 'trusted' for hook in hooks()))
        self.assertTrue(all(hook['trustStatus'] == 'untrusted' for hook in loaded_hooks()))
        response = server.rpc('config/batchWrite', {
            'edits': [], 'filePath': str(config), 'reloadUserConfig': True,
        })
        self.assertEqual(response['status'], 'ok', response)
        self.assertTrue(all(hook['trustStatus'] == 'trusted' and hook['enabled']
                            for hook in loaded_hooks()))
        # Restart separately to prove persisted consent as well as loaded state.
        server.close()
        server, _ = start()
        trusted = hooks()
        self.assertTrue(all(hook['trustStatus'] == 'trusted' and hook['enabled'] for hook in trusted), trusted)
        self.assertEqual({hook['key'] for hook in trusted}, set(states))

        manifest = json.loads(fixture.target.read_text())
        manifest['hooks']['PreToolUse'][0]['hooks'][0]['timeout'] += 1
        fixture.target.write_text(json.dumps(manifest))
        changed = hooks()
        modified = [hook for hook in changed if hook['trustStatus'] == 'modified']
        self.assertEqual(len(modified), 1, changed)
        self.assertNotEqual(modified[0]['currentHash'], states[modified[0]['key']]['trusted_hash'])
        self.assertNotEqual(modified[0]['trustStatus'], 'trusted')

        consent({})
        server.close()
        server, _ = start()
        revoked = hooks()
        self.assertTrue(all(hook['trustStatus'] == 'untrusted' for hook in revoked), revoked)
        fixture.assert_preserved(self)
        print(f'Installed-runtime proof: {len(discovered)} definitions; untrusted -> trusted -> modified -> revoked; userAgent={info.get("userAgent", "unknown")}')
