"""Native tool/hook execution with a deterministic loopback-only provider."""
import json
import os
import queue
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from test_hook_discovery import AppServer
import test_installation_route as installation_tests


class LocalProvider:
    """Return two fixed tool calls, never model-generated commands."""

    def __init__(self, repo):
        self.repo = repo
        self.requests = []
        self.errors = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                self.connection.settimeout(5)
                size = int(self.headers.get('Content-Length', '0'))
                if self.path != '/v1/responses' or not 0 < size < 4 * 1024 * 1024:
                    self.send_error(400, 'Unexpected fixture request')
                    return
                request = json.loads(self.rfile.read(size))
                owner.requests.append(request)
                if self.headers.get('Authorization'):
                    owner.errors.append('Unexpected authentication header')
                    self.send_error(400, 'Authentication is not used by this fixture')
                    return
                try:
                    events = owner.events(request, len(owner.requests) - 1)
                except (KeyError, TypeError, ValueError) as error:
                    owner.errors.append(str(error))
                    self.send_error(400, 'Invalid fixture request')
                    return
                data = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'

    def events(self, request, step):
        if step > 2:
            raise ValueError('Native turn exceeded the three-request fixture budget')
        if step < 2:
            names = {tool.get('name') for tool in request['tools']}
            # The denied form has no durable side effect even if a regression
            # accidentally admits it. It reaches the hook, unlike no-verify,
            # which native execution policy can reject before hook dispatch.
            command = 'git status --short' if step == 0 else 'cd .; git status --short'
            if 'exec_command' in names:
                name = 'exec_command'
                arguments = {'cmd': command, 'workdir': str(self.repo), 'login': False,
                             'yield_time_ms': 1000, 'max_output_tokens': 2000}
            elif 'shell_command' in names:
                name = 'shell_command'
                arguments = {'command': command, 'workdir': str(self.repo), 'timeout_ms': 1000}
            elif 'shell' in names:
                name = 'shell'
                arguments = {'command': ['/bin/sh', '-c', command],
                             'workdir': str(self.repo), 'timeout_ms': 1000}
            else:
                raise ValueError('No supported shell tool in fixture request: ' + str(sorted(names)))
            item = {'type': 'function_call', 'id': f'fc_{step}', 'call_id': f'call_{step}',
                    'name': name, 'arguments': json.dumps(arguments), 'status': 'completed'}
        else:
            item = {'type': 'message', 'id': 'msg_fixture', 'role': 'assistant',
                    'status': 'completed', 'content': [{'type': 'output_text',
                    'text': 'native-turn-proof-complete', 'annotations': []}]}
        response = {'id': f'resp_{step}', 'object': 'response', 'model': 'fixture-model',
                    'status': 'completed', 'output': [item],
                    'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
        return [
            {'type': 'response.created', 'response': response | {'status': 'in_progress', 'output': []}},
            {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
            {'type': 'response.completed', 'response': response},
        ]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@unittest.skipUnless(os.environ.get('DOTS_CODEX_BIN'), 'DOTS_CODEX_BIN required for active-turn proof')
class HookActiveTurnTests(unittest.TestCase):
    def test_native_turn_runs_safe_command_and_preserves_hook_denial(self):
        self.run_native_proof(include_core=False)

    def test_initial_core_hooks_complete_native_turn(self):
        self.run_native_proof(include_core=True)

    def run_native_proof(self, *, include_core):
        installation = installation_tests.InstallationRouteTests()
        self.addCleanup(installation.doCleanups)
        installation.setUp()
        fixture = installation.fixture
        self.addCleanup(fixture.assert_preserved, self)
        digest = installation.success(installation.prepare())['plan_digest']
        installation.success(installation.operation('apply', digest))
        fixture.env = installation.installed_env()
        provider = LocalProvider(fixture.repo)
        self.addCleanup(provider.close)
        # Use the installed payload's exact dispatcher, without unrelated
        # lifecycle hooks or synthetic Braid. Only disposable HOME is changed.
        manifest = json.loads(fixture.target.read_text())
        selected = {'PreToolUse': [manifest['hooks']['PreToolUse'][0]]}
        if include_core:
            selected['PreToolUse'] = manifest['hooks']['PreToolUse'][:2]
            selected['SessionStart'] = manifest['hooks']['SessionStart'][:1]
            selected['PermissionRequest'] = manifest['hooks']['PermissionRequest'][:2]
        fixture.target.write_text(json.dumps({'hooks': selected}))
        expected_count = 5 if include_core else 1
        config = fixture.runtime / 'config.toml'
        config.write_text('approval_policy = "never"\nsandbox_mode = "read-only"\n'
                          'check_for_update_on_startup = false\n'
                          'model = "fixture-model"\nmodel_provider = "fixture"\n'
                          '[model_providers.fixture]\nname = "Local deterministic fixture"\n'
                          f'base_url = "{provider.url}"\nwire_api = "responses"\n'
                          'requires_openai_auth = false\nsupports_websockets = false\n'
                          'request_max_retries = 0\nstream_max_retries = 0\n'
                          '[features]\nhooks = true\nplugin_hooks = false\n'
                          '[analytics]\nenabled = false\n')
        fixture.env.update({'HTTP_PROXY': 'http://127.0.0.1:1',
                            'HTTPS_PROXY': 'http://127.0.0.1:1',
                            'ALL_PROXY': 'http://127.0.0.1:1', 'NO_PROXY': '127.0.0.1,localhost'})
        (fixture.repo / 'native-turn-sentinel.txt').write_text('synthetic native proof\n')

        def start():
            server = AppServer(fixture)
            self.addCleanup(server.close)
            info = server.rpc('initialize', {
                'clientInfo': {'name': 'dots-active-turn-proof', 'version': '1.0.0'},
                'capabilities': {'experimentalApi': True},
            })
            server.process.stdin.write(json.dumps({'method': 'initialized', 'params': {}}) + '\n')
            server.process.stdin.flush()
            return server, info

        server, _ = start()
        hooks = server.rpc('hooks/list', {'cwds': [str(fixture.repo)]})['data'][0]
        self.assertFalse(hooks['errors'], hooks)
        self.assertEqual(len(hooks['hooks']), expected_count)
        hook = hooks['hooks'][0]
        self.assertEqual(hook['trustStatus'], 'untrusted')
        server.rpc('config/value/write', {'filePath': str(config), 'keyPath': 'hooks.state',
            'value': {row['key']: {'enabled': True, 'trusted_hash': row['currentHash']} for row in hooks['hooks']},
            'mergeStrategy': 'replace'})
        server.close()
        server, info = start()
        thread_id = server.rpc('thread/start', {'cwd': str(fixture.repo), 'ephemeral': True})['thread']['id']
        loaded = server.rpc('hooks/list', {'threadId': thread_id})['data'][0]['hooks']
        self.assertEqual(len(loaded), expected_count)
        self.assertEqual(loaded[0]['trustStatus'], 'trusted')
        self.assertTrue(loaded[0]['enabled'])
        server.rpc('turn/start', {'threadId': thread_id,
                                 'input': [{'type': 'text', 'text': 'Run the synthetic local proof.'}]})
        deadline = time.monotonic() + 45
        notices = []
        while time.monotonic() < deadline:
            try:
                line = server.lines.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                self.fail('Native turn timed out: ' + str(provider.errors) + ''.join(server.errors)[-1000:])
            self.assertIsNotNone(line, ''.join(server.errors)[-1000:])
            message = json.loads(line)
            notices.append(message)
            if message.get('method') == 'turn/completed':
                self.assertEqual(message['params']['turn']['status'], 'completed', message)
                break
        else:
            self.fail('Native turn did not complete')
        if include_core:
            completed = [row['params'] for row in server.notifications if row.get('method') == 'hook/completed']
            self.assertTrue(completed, server.notifications)
            outcomes = [(row['run']['eventName'], row['run']['status']) for row in completed]
            self.assertIn(('sessionStart', 'completed'), outcomes)
            self.assertIn(('preToolUse', 'completed'), outcomes)
            self.assertIn(('preToolUse', 'blocked'), outcomes)
            self.assertFalse(any(status == 'failed' for _, status in outcomes), completed)
            print('Core hook outcomes: ' + repr(outcomes))
        self.assertFalse(provider.errors, provider.errors)
        self.assertEqual(len(provider.requests), 3, notices)
        def tool_output(request, call_id):
            return json.dumps([item.get('output') for item in request['input']
                               if item.get('type') == 'function_call_output' and item.get('call_id') == call_id])

        safe_output = tool_output(provider.requests[1], 'call_0')
        denied_output = tool_output(provider.requests[2], 'call_1')
        escaping = [str(path.relative_to(fixture.home)) for path in fixture.home.rglob('*')
                    if path.is_symlink() and not path.resolve().is_relative_to(fixture.home)]
        self.assertIn('native-turn-sentinel.txt', safe_output,
                      safe_output + '; outside-fixture link names: ' + str(escaping))
        self.assertIn('Blocked protected or uninspectable indirect shell execution', denied_output)
        self.assertIn('native-turn-proof-complete', json.dumps(notices))
        server.close()
        fixture.assert_preserved(self)
        print('Active native turn: safe status executed; indirect shell form denied by hook; loopback-only provider; '
              + info.get('userAgent', 'unknown'))
