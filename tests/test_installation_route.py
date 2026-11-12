"""Rehearse the real installation entrypoint without live or provider state."""
import importlib.util
import json
import os
import pwd
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from policy_fixture import PolicyFixture
from test_governance_port import ROOT


class InstallationRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PolicyFixture(self)
        self.addCleanup(self.fixture.assert_preserved, self)
        self.home = self.fixture.home
        self.state = self.home / 'installation/one'
        self.payload = self.state / 'payload'
        result = self.fixture.project()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.runtime = self.fixture.runtime
        private = self.home / 'dev/private-configs'
        private.mkdir(parents=True)
        (self.runtime / 'usage-data').rename(private / 'usage-data')
        (self.runtime / 'usage-data').symlink_to(private / 'usage-data')
        for name in ('browser', 'pets'):
            (private / name).mkdir()
            (private / name / 'preserve.json').write_text('{"local":true}')
            (self.runtime / name).symlink_to(private / name)
        recipe = json.loads((ROOT / 'tests/fixtures/governance-bindings.json').read_text())
        values = {key: value.replace('@HOME@', str(self.home)).replace(
            str(self.home / 'dev/dots'), str(self.payload)) for key, value in recipe.items()}
        values['value_0007'] = str(self.runtime / 'usage-data')
        self.bindings = self.home / 'private-bindings.json'
        self.bindings.write_text(json.dumps(values))
        self.before = self.snapshot()
        self.env = {name: value for name, value in self.fixture.env.items()
                    if not name.startswith('DOTS_')}

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/install-codex.py'),
            *map(str, args)], cwd=ROOT, env=self.env, text=True, capture_output=True, timeout=120, check=False)

    def prepare(self):
        return self.run_cli('prepare', '--home', self.home, '--state-dir', self.state,
            '--bindings', self.bindings, '--braid-bin', self.fixture.bin / 'braid', '--mode', 'rehearsal')

    def operation(self, operation, digest):
        return self.run_cli(operation, '--state-dir', self.state, '--plan-digest', digest)

    def installed_env(self):
        return self.env | {'CODEX_CONFIG_SOURCE_ROOT': str(self.payload / 'codex')}

    def snapshot(self):
        result = {}
        for path in self.runtime.iterdir():
            if path.is_symlink():
                result[path.name] = ('link', str(path.readlink()))
            elif path.is_file():
                result[path.name] = ('file', path.read_bytes())
            elif path.is_dir():
                result[path.name] = ('directory',)
        return result

    def success(self, result):
        details = ''.join(path.read_text() for path in self.state.glob('*diagnostic.json')) if result.returncode else ''
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + details)
        return json.loads(result.stdout)

    def test_cutover_repeat_and_exact_managed_rollback(self):
        config = self.runtime / 'config.toml'
        original = config.read_text().replace('model_verbosity = "medium"', 'model_verbosity = "high"', 1)
        desktop = ('[plugins."computer-use@openai-bundled"]\nenabled = false\n'
                   '[plugins."computer-use@openai-bundled".mcp_servers.computer-use.tools.click]\n'
                   'approval_mode = "prompt"\n')
        config.write_text(original.replace('\n[desktop]\n', '\n' + desktop + '\n[desktop]\n', 1))
        self.before = self.snapshot()
        prepared = self.success(self.prepare())
        self.assertEqual(prepared['status'], 'prepared')
        self.assertEqual(self.snapshot(), self.before, 'Preparation must not install')
        digest = prepared['plan_digest']
        applied = self.success(self.run_cli('apply', '--state-dir', self.state, '--plan-digest', digest))
        self.assertEqual(applied['status'], 'applied')
        self.assertEqual((self.runtime / 'scripts').resolve(), self.payload / 'codex/scripts')
        self.assertTrue((self.runtime / 'model-catalogs').is_symlink())
        self.assertFalse((self.runtime / 'config.toml').is_symlink())
        self.assertFalse((self.runtime / 'hooks.json').is_symlink())
        installed = tomllib.loads(config.read_text())
        self.assertEqual(installed['model_verbosity'], 'high')
        self.assertEqual(installed['plugins']['computer-use@openai-bundled'],
                         tomllib.loads(desktop)['plugins']['computer-use@openai-bundled'])
        first = self.snapshot()
        self.success(self.run_cli('check', '--state-dir', self.state, '--plan-digest', digest))
        self.success(self.run_cli('apply', '--state-dir', self.state, '--plan-digest', digest))
        self.assertEqual(self.snapshot(), first)
        event = self.fixture.payload | {'transcript_path': str(self.runtime / 'sessions/synthetic.jsonl')}
        for command, decision in (('git status --short', None), ('git push --no-verify origin topic', 'deny'),
                                  ('gh pr create --base main', 'deny')):
            event['tool_input'] = {'command': command}
            hook = 'pr-readiness-guard.sh' if command.startswith('gh pr') else 'pre-tool-use-dispatch.sh'
            checked = subprocess.run(['bash', str(self.runtime / 'hooks' / hook)],
                input=json.dumps(event), env=self.installed_env(), cwd=self.payload,
                text=True, capture_output=True, timeout=20, check=False)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            actual = json.loads(checked.stdout).get('hookSpecificOutput', {}).get('permissionDecision')
            self.assertEqual(actual, decision)
        rolled = self.success(self.run_cli('rollback', '--state-dir', self.state, '--plan-digest', digest))
        self.assertEqual(rolled['status'], 'rolled_back')
        self.assertEqual(self.snapshot(), self.before)
        self.success(self.run_cli('rollback', '--state-dir', self.state, '--plan-digest', digest))

    def test_changed_target_and_wrong_digest_leave_runtime_untouched(self):
        digest = self.success(self.prepare())['plan_digest']
        wrong = self.operation('apply', '0' * 64)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertEqual(self.snapshot(), self.before)
        target = self.runtime / 'docs.config.toml'
        target.unlink()
        target.write_text('newer user-owned content\n')
        current = self.snapshot()
        refused = self.operation('apply', digest)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.snapshot(), current)

    def test_rollback_cancels_an_unapplied_plan(self):
        digest = self.success(self.prepare())['plan_digest']
        result = self.success(self.operation('rollback', digest))
        self.assertEqual(result['writes'], 0)
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(json.loads((self.state / 'result.json').read_text())['status'], 'rolled_back')
        self.assertNotEqual(self.operation('apply', digest).returncode, 0)
        self.assertEqual(self.snapshot(), self.before)

    def test_helpers_cannot_overwrite_control_or_retained_state(self):
        self.success(self.prepare())
        plan = self.state / 'plan.json'
        original_plan = plan.read_bytes()
        command = [sys.executable, '-B', str(self.payload / 'codex/scripts/render-agent-artifact-summary.py'),
                   '--root', str(self.payload / 'codex')]
        def render(target):
            return subprocess.run([*command, '--out', str(target)], env=self.installed_env(),
                cwd=self.payload, capture_output=True, text=True, timeout=15, check=False)
        for target in (plan, self.runtime / 'auth.json', self.runtime / 'sessions/synthetic.jsonl',
                       self.runtime / 'state.db'):
            before = target.read_bytes()
            result = render(target)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(target.read_bytes(), before)
            publisher = subprocess.run([sys.executable, '-B',
                str(self.payload / 'codex/scripts/project-codex-hooks.py'), '--source',
                str(self.payload / 'codex/hooks/hooks.json'), '--target', str(target)],
                env=self.installed_env(), cwd=self.payload, capture_output=True, text=True, timeout=15, check=False)
            self.assertNotEqual(publisher.returncode, 0, publisher.stdout + publisher.stderr)
            self.assertEqual(target.read_bytes(), before)
        alias = self.home / 'tmp/control-alias.json'
        os.link(plan, alias)
        self.assertNotEqual(render(alias).returncode, 0)
        self.assertEqual(plan.read_bytes(), original_plan)
        alias.unlink()
        output = self.home / 'tmp/summary.md'
        result = render(output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output.is_file())
        probe = self.home / 'tmp/open-output.py'
        probe.write_text('''import importlib.util
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("output_probe", sys.argv[1])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
try:
    with helper.fixture_open(Path(sys.argv[2]), sys.argv[3]) as stream:
        if sys.argv[3] == "r":
            stream.read(0)
except ValueError:
    raise SystemExit(3)
''')
        for mode, expected in (('r', 0), ('w', 3), ('a', 3), ('r+', 3), ('x', 3)):
            checked = subprocess.run([sys.executable, '-B', str(probe),
                str(self.payload / 'codex/scripts/helper_fixture_scope.py'), str(plan), mode],
                env=self.installed_env(), cwd=self.payload, capture_output=True, text=True, timeout=15, check=False)
            self.assertEqual(checked.returncode, expected, checked.stdout + checked.stderr)
            self.assertEqual(plan.read_bytes(), original_plan)
        result = subprocess.run([sys.executable, '-B', str(self.payload / 'codex/scripts/admit-hook-fixture.py'), '{}'],
            cwd=self.payload, env=self.installed_env() | {'CODEX_COMPACT_HOOK_LOG': str(plan)},
            capture_output=True, text=True, timeout=15, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(plan.read_bytes(), original_plan)
        default_log = self.runtime / 'usage-data/compact-hooks.jsonl'
        os.link(plan, default_log)
        result = subprocess.run([sys.executable, '-B', str(self.payload / 'codex/scripts/admit-hook-fixture.py'), '{}'],
            cwd=self.payload, env=self.installed_env(), capture_output=True, text=True, timeout=15, check=False)
        self.assertNotEqual(result.returncode, 0, 'Default output leaves must reject shared control inodes')
        self.assertEqual(plan.read_bytes(), original_plan)
        default_log.unlink()
        self.assertEqual(self.snapshot(), self.before)

    def test_rollback_retries_after_pre_exchange_interruption(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        stale_stage = self.state / 'restore-config.toml'
        original = (self.state / 'backups/config.toml').read_bytes()
        stale_stage.write_bytes(original)
        result_path = self.state / 'result.json'
        result = json.loads(result_path.read_text())
        result['status'] = 'restoring'
        result_path.write_text(json.dumps(result))
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(stale_stage.read_bytes(), original, 'Prior recovery material must be retained')
        self.success(self.operation('rollback', digest))

    def test_package_tampering_and_extra_module_are_refused(self):
        digest = self.success(self.prepare())['plan_digest']
        script = self.payload / 'codex/scripts/migration_scope.py'
        original = script.read_bytes()
        script.chmod(0o600)
        script.write_bytes(original + b'\nraise RuntimeError("must never execute")\n')
        self.assertNotEqual(self.operation('apply', digest).returncode, 0)
        self.assertEqual(self.snapshot(), self.before)
        script.write_bytes(original)
        script.chmod(0o400)
        directory = script.parent
        directory.chmod(0o700)
        (directory / 'json.py').write_text('raise RuntimeError("must never import")\n')
        directory.chmod(0o500)
        self.assertNotEqual(self.operation('apply', digest).returncode, 0)
        self.assertEqual(self.snapshot(), self.before)

    def test_newer_edit_and_incomplete_result_block_rollback(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        result_path = self.state / 'result.json'
        complete = result_path.read_bytes()
        result = json.loads(complete)
        result['after'] = {}
        result_path.write_text(json.dumps(result))
        current = self.snapshot()
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        self.assertNotEqual(self.operation('rollback', digest).returncode, 0)
        self.assertEqual(self.snapshot(), current)
        result_path.write_bytes(complete)
        with (self.runtime / 'config.toml').open('a') as stream:
            stream.write('\n# newer user edit\n')
        current = self.snapshot()
        self.assertNotEqual(self.operation('rollback', digest).returncode, 0)
        self.assertEqual(self.snapshot(), current)
        self.assertTrue((self.state / 'backups/config.toml').is_file())

    def test_partial_cutover_resumes_before_rollback(self):
        digest = self.success(self.prepare())['plan_digest']
        # Interrupt at the real projector boundary after atomic config publication.
        shadow = self.fixture.bin / 'bash'
        shadow.write_text('#!/bin/sh\nexit 75\n')
        shadow.chmod(0o700)
        failed = self.operation('apply', digest)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(json.loads((self.state / 'result.json').read_text())['status'], 'failed')
        self.assertNotEqual(self.snapshot()['config.toml'], self.before['config.toml'])
        self.assertNotEqual(self.operation('rollback', digest).returncode, 0)
        shadow.unlink()
        self.success(self.operation('apply', digest))
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before)

    def test_rehearsal_refuses_credentials_and_nested_auth_alias(self):
        self.success(self.prepare())
        command = [sys.executable, '-B', str(self.payload / 'codex/scripts/admit-hook-fixture.py'), '{}']
        def run(env):
            return subprocess.run(command, env=env, cwd=self.payload,
                capture_output=True, text=True, timeout=15, check=False)
        clean = self.installed_env()
        self.assertEqual(run(clean).returncode, 0)
        self.assertNotEqual(run(clean | {'GH_TOKEN': 'synthetic-not-a-token'}).returncode, 0)
        self.assertNotEqual(run(clean | {'CODEX_HOOK_OTEL_ENDPOINT': 'https://example.invalid'}).returncode, 0)
        store = self.home / '.config/gh'
        store.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other).resolve()
            (outside / 'auth.yml').write_text('synthetic: true\n')
            alias = self.home / 'auth-alias'
            alias.mkdir()
            (alias / 'nested').symlink_to(outside, target_is_directory=True)
            (store / 'alias').symlink_to(alias, target_is_directory=True)
            self.assertNotEqual(run(clean).returncode, 0)
        self.assertEqual(self.snapshot(), self.before)

    def test_target_modes_cannot_select_the_wrong_home(self):
        for home, mode in ((Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(), 'rehearsal'),
                           (self.home, 'machine')):
            result = self.run_cli('prepare', '--home', home, '--state-dir', self.state,
                '--bindings', self.bindings, '--braid-bin', self.fixture.bin / 'braid', '--mode', mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.state.exists())
            self.assertEqual(self.snapshot(), self.before)

    def test_packaged_aikido_defaults_launch_without_widening_resource_roots(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        binary = self.runtime / 'utilities/aikido-mcp/bin/aikido-mcp'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nprintf "packaged-provider:%s\\n" "$1"\n')
        binary.chmod(0o755)
        reference = self.runtime / 'aikido-mcp.env'
        reference.write_text('SYNTHETIC_REFERENCE=fixture-only\n')
        provider = self.home / 'tmp/op-fixture'
        provider.write_text('#!/bin/sh\n[ "$1" = run ] && [ "$2" = --env-file ] && [ "$4" = -- ] || exit 99\n'
                            'shift 4\nexec "$@"\n')
        provider.chmod(0o755)
        command = ['bash', str(self.runtime / 'scripts/aikido-mcp.sh'), 'space in argument']

        def launch(**overrides):
            return subprocess.run(command, env=self.installed_env() | {'OP_BIN': str(provider)} | overrides,
                                  cwd=self.payload, capture_output=True, text=True, timeout=20, check=False)

        for overrides in ({}, {'AIKIDO_MCP_USE_OP_RUN': '0'}):
            result = launch(**overrides)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, 'packaged-provider:space in argument\n')
        spec = importlib.util.spec_from_file_location('packaged_provider_scope', self.payload / 'codex/scripts/deployment_scope.py')
        scope = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scope)
        with mock.patch.dict(os.environ, self.installed_env(), clear=True):
            context = scope.context()
            for name in ('op', 'op-beta'):
                path = Path('/usr/local/bin') / name
                self.assertEqual(scope.require_provider_input(path, 'onepassword', context | {'mode': 'machine'}), path)
                with self.assertRaises(ValueError):
                    scope.require_provider_input(path, 'onepassword', context)
            with self.assertRaises(ValueError):
                scope.require_provider_input('/bin/sh', 'onepassword', context | {'mode': 'machine'})
            for output in (binary, reference):
                with self.assertRaises(ValueError):
                    scope.require_path(output, output=True, data=context)
        # Named provider-input admission does not admit generic helper reads or outputs.
        generic = subprocess.run([sys.executable, '-B', str(self.runtime / 'scripts/admit-hook-fixture.py'),
                                  '--provider-path', str(binary)], env=self.installed_env(),
                                 cwd=self.payload, capture_output=True, text=True, timeout=15, check=False)
        self.assertNotEqual(generic.returncode, 0)
        for overrides in ({'OP_BIN': '/usr/local/bin/op'},
                          {'AIKIDO_MCP_BIN': '/bin/sh'},
                          {'AIKIDO_MCP_ENV_FILE': '/outside-reference'}):
            self.assertNotEqual(launch(**overrides).returncode, 0)
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external).resolve() / 'sentinel'
            outside.write_bytes(b'owned external fixture')
            for path in (binary, reference):
                original, mode = path.read_bytes(), path.stat().st_mode & 0o777
                path.unlink()
                path.symlink_to(outside)
                try:
                    self.assertNotEqual(launch().returncode, 0)
                    self.assertEqual(outside.read_bytes(), b'owned external fixture')
                finally:
                    path.unlink()
                    path.write_bytes(original)
                    path.chmod(mode)
        local_additions = {name: value for name, value in self.snapshot().items() if name not in self.before}
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before | local_additions)

    @unittest.skipUnless(os.environ.get('DOTS_CODEX_BIN'), 'Installed CLI required for native installation proof')
    def test_native_loading_and_hook_discovery_after_installation(self):
        from test_hook_discovery import AppServer
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        server = AppServer(SimpleNamespace(repo=self.payload, env=self.installed_env()),
                           strict_config=True, enable_hooks=False)
        self.addCleanup(server.close)
        server.rpc('initialize', {'clientInfo': {'name': 'dots-install-proof', 'version': '1.0.0'},
                                 'capabilities': {'experimentalApi': True}})
        config = server.rpc('config/read', {'cwd': str(self.payload), 'includeLayers': True})
        self.assertEqual(config['config']['approvals_reviewer'], 'auto_review')
        installed = tomllib.loads((self.runtime / 'config.toml').read_text())
        launcher = Path(installed['mcp_servers']['aikido']['command'])
        self.assertEqual(launcher, self.payload / 'codex/scripts/aikido-mcp.sh')
        self.assertTrue(launcher.is_file() and launcher.stat().st_mode & 0o111)
        self.assertEqual(installed['plugins']['drawio@drawio'], {'enabled': True})
        self.assertTrue(Path(installed['experimental_compact_prompt_file']).is_file())
        hooks = server.rpc('hooks/list', {'cwds': [str(self.payload)]})['data'][0]
        self.assertEqual(len(hooks['hooks']), 29)
        self.assertFalse(hooks['errors'], hooks)
        self.assertFalse(hooks['warnings'], hooks)
        self.assertTrue(all(hook['sourcePath'] == str(self.runtime / 'hooks.json') for hook in hooks['hooks']))
        server.close()
        for name in ('docs', 'oss-local', 'oss-local-code', 'oss-local-fallback',
                     'oss-security', 'oss-cloud', 'oss-inspect'):
            result = subprocess.run([os.environ['DOTS_CODEX_BIN'], '--profile', name,
                '-c', 'mcp_oauth_credentials_store="file"', 'mcp', 'list', '--json'],
                env=self.installed_env(), cwd=self.payload, capture_output=True, text=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if name.startswith('oss-'):
                self.assertTrue(all(not item.get('enabled', True) for item in json.loads(result.stdout)))
                profile = tomllib.loads((self.runtime / (name + '.config.toml')).read_text())
                self.assertEqual(profile['default_permissions'], 'readonly-net')
                if 'model_catalog_json' in profile:
                    self.assertTrue(Path(profile['model_catalog_json']).is_file())
        local_additions = {name: value for name, value in self.snapshot().items() if name not in self.before}
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before | local_additions)
