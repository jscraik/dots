"""Exercise the complete governance entrypoint only in disposable homes."""
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('generator', ROOT / 'scripts/generate-codex-policy.py')
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)
DEPENDENCIES = ('scripts/validate-codex-config.py', 'scripts/repair-runtime-config-drift.py',
                'scripts/migration_scope.py', 'schemas/config.schema.json',
                'instructions/compact-prompt.md', 'scripts/project-codex-hooks.py',
                'model-catalogs/oss-local-qwen35.json',
                'model-catalogs/oss-inspect-gemma4-12b-mlx.json',
                'model-catalogs/oss-security-h4rithd-coder.json')


class GovernancePortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path('/tmp').resolve())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.repo = self.home / 'dev/dots'
        self.codex = self.repo / 'codex'
        for relative in DEPENDENCIES:
            target = self.codex / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'codex' / relative, target)
        recipes = GEN.read_json(ROOT / 'tests/fixtures/governance-bindings.json')
        bindings = {key: value.replace('@HOME@', str(self.home)) for key, value in recipes.items()}
        binding_file = self.home / 'bindings.json'
        binding_file.write_text(json.dumps(bindings))
        self.generated = GEN.render(binding_file)
        for name, text in self.generated.items():
            filename = 'config.toml' if name == 'config' else name + '.config.toml'
            (self.codex / filename).write_text(text)
        self.root = tomllib.loads(self.generated['config'])
        # The generated policy names synthetic projects under this disposable
        # home. Make them real on every OS so the runtime's stale-temporary-
        # project check evaluates the fixture consistently.
        for value in self.root.get('projects', {}):
            project = Path(value)
            if not project.is_absolute() or not project.is_relative_to(self.home):
                raise ValueError('Fixture project leaves its disposable home')
            project.mkdir(parents=True, exist_ok=True)
        # Test-only registry contents exercise discovery; no installed cache is copied.
        for name, marketplace in self.root['marketplaces'].items():
            location = Path(marketplace['source'])
            location.mkdir(parents=True, exist_ok=True)
            (location / 'marketplace.json').write_text(json.dumps({'name': name, 'plugins': [
                {'name': plugin.split('@')[0], 'source': {'source': 'local', 'path': plugin.split('@')[0]}}
                for plugin in self.root['plugins'] if plugin.endswith('@' + name)]}))
        for plugin in self.root['plugins']:
            name, market = plugin.split('@')
            if market in self.root['marketplaces']:
                marker = Path(self.root['marketplaces'][market]['source']) / name / '.codex-plugin'
                marker.mkdir(parents=True, exist_ok=True)
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.home),
                    'DOTS_TEST_HOME': str(self.home), 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        subprocess.run(['git', 'init', '-q', str(self.repo)], env=self.env, check=True,
                       capture_output=True, timeout=10)

    def runtime_fixture(self):
        runtime = self.home / '.codex'
        runtime.mkdir(exist_ok=True)
        for name, text in self.generated.items():
            filename = 'config.toml' if name == 'config' else name + '.config.toml'
            destination = runtime / filename
            if name == 'config':
                destination.write_text(text)
            else:
                destination.symlink_to(self.codex / filename)
        source = self.codex / 'hooks/hooks.json'
        source.parent.mkdir(parents=True)
        manifest = (ROOT / 'codex/templates/hooks.json').read_text().replace(
            '@BRAID_COMMAND@', shlex.quote(str(self.home / '.local/bin/braid')))
        source.write_text(manifest)
        # No handler is run, no registry is trusted, and no consent is installed.
        for name in ('auth.json', 'session_index.json', 'state.db'):
            (runtime / name).write_bytes(b'caller-owned synthetic sentinel')
        return source, runtime / 'hooks.json'

    def publish(self, source, target, *args):
        return subprocess.run([sys.executable, '-B', str(self.codex / 'scripts/project-codex-hooks.py'),
                               '--source', str(source), '--target', str(target), *args],
                              env=self.env, capture_output=True, text=True, timeout=15, check=False)

    def test_full_runtime_check_with_managed_hook_copy(self):
        source, target = self.runtime_fixture()
        target.symlink_to(source)
        result = self.publish(source, target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(target.is_symlink())
        self.assertFalse(target.samefile(source))
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertTrue(list(target.parent.glob('.hooks-backup-*')))
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for args in (('--check',), ()):
            result = self.publish(source, target, *args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('unchanged', result.stdout)
        for name in ('auth.json', 'session_index.json', 'state.db'):
            self.assertEqual((target.parent / name).read_bytes(), b'caller-owned synthetic sentinel')
        target.write_text('{}')
        self.assertNotEqual(self.validate().returncode, 0)

    def test_incomplete_hooks_do_not_replace_runtime(self):
        source, target = self.runtime_fixture()
        target.write_text('preserve-me')
        manifest = json.loads(source.read_text())
        del manifest['hooks']['Stop']
        source.write_text(json.dumps(manifest))
        result = self.publish(source, target)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), 'preserve-me')
        self.assertFalse(list(target.parent.glob('.hooks-backup-*')))

    def test_hook_hardlink_and_external_target_rejected(self):
        source, target = self.runtime_fixture()
        os.link(source, target)
        self.assertNotEqual(self.publish(source, target).returncode, 0)
        self.assertNotEqual(self.validate().returncode, 0)
        outside = self.home.parent / (self.home.name + '-outside')
        self.assertNotEqual(self.publish(source, outside).returncode, 0)
        self.assertFalse(outside.exists())

    def validate(self, text=None):
        command = [sys.executable, '-B', str(self.codex / 'scripts/validate-codex-config.py')]
        if text is not None:
            command.append('--config-stdin')
        return subprocess.run(command, input=text, env=self.env, capture_output=True,
                              text=True, timeout=30, check=False)

    def test_complete_snapshot_and_negative_policy(self):
        result = self.validate(self.generated['config'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for old, new in (('hooks = true', 'hooks = false'),
                         ('log_user_prompt = false', 'log_user_prompt = true')):
            self.assertIn(old, self.generated['config'])
            result = self.validate(self.generated['config'].replace(old, new))
            self.assertEqual(result.returncode, 65, result.stdout + result.stderr)

    def test_networked_profiles_deny_auth_fifo(self):
        fifo = str(self.home / '.codex/.env')
        for profile_name in ('workspace-net', 'readonly-net'):
            with self.subTest(profile=profile_name):
                profile = self.root['permissions'][profile_name]
                self.assertEqual(profile['filesystem'][fifo], 'deny')
                weakened = tomllib.loads(self.generated['config'])
                weakened['permissions'][profile_name]['filesystem'][fifo] = 'read'
                result = self.validate(GEN.toml_document(weakened))
                self.assertEqual(result.returncode, 65, result.stdout + result.stderr)
                self.assertIn(
                    f'permissions.{profile_name}.filesystem must deny access to {fifo}',
                    result.stdout,
                )

    def test_missing_schema_is_unavailable_not_pass(self):
        (self.codex / 'schemas/config.schema.json').unlink()
        result = self.validate(self.generated['config'])
        self.assertEqual(result.returncode, 69, result.stdout + result.stderr)

    def test_missing_profile_and_registry_never_pass(self):
        (self.codex / 'docs.config.toml').unlink()
        self.assertEqual(self.validate(self.generated['config']).returncode, 65)
        (self.codex / 'docs.config.toml').write_text(self.generated['docs'])
        registry = Path(self.root['marketplaces']['agent-skills-local']['source']) / 'marketplace.json'
        registry.unlink()
        self.assertNotEqual(self.validate(self.generated['config']).returncode, 0)

    def test_disabled_computer_use_transport_rejects_enabled_or_executable_variants(self):
        profile_path = self.codex / 'oss-cloud.config.toml'
        original = tomllib.loads(profile_path.read_text())
        self.assertEqual(original['mcp_servers']['cua_repl'],
                         {'command': '/usr/bin/false', 'enabled': False, 'required': False})
        for field, value in (('enabled', True), ('required', True),
                             ('command', '/bin/sh'), ('args', ['-c', 'true'])):
            with self.subTest(field=field):
                data = tomllib.loads(self.generated['oss-cloud'])
                data['mcp_servers']['cua_repl'][field] = value
                profile_path.write_text(GEN.toml_document(data))
                result = self.validate(self.generated['config'])
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        profile_path.write_text(self.generated['oss-cloud'])

    def test_runtime_repair_preserves_policy_and_state(self):
        _source, target = self.runtime_fixture()
        runtime = target.parent / 'config.toml'
        runtime.write_text(runtime.read_text().replace('approval_policy = "on-request"',
                                                      'approval_policy = "never"', 1))
        result = subprocess.run([sys.executable, '-B', str(self.codex / 'scripts/repair-runtime-config-drift.py'),
            '--config-path', str(runtime), '--repair', '--json'], env=self.env,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(tomllib.loads(runtime.read_text())['approval_policy'], 'on-request')
        self.assertEqual((target.parent / 'auth.json').read_bytes(), b'caller-owned synthetic sentinel')

    def test_generated_project_paths_exist_in_disposable_home(self):
        for value in self.root['projects']:
            with self.subTest(project=value):
                project = Path(value)
                self.assertTrue(project.is_relative_to(self.home))
                self.assertTrue(project.is_dir())

    def test_live_home_without_explicit_scope_rejected(self):
        env = dict(self.env)
        env.pop('DOTS_TEST_HOME')
        result = subprocess.run([sys.executable, '-B', str(self.codex / 'scripts/validate-codex-config.py')],
                                env=env, capture_output=True, text=True, timeout=10, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('disposable', result.stderr)

    def test_account_home_descendant_is_not_disposable(self):
        spec = importlib.util.spec_from_file_location('scope_test', ROOT / 'codex/scripts/migration_scope.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Both directories are owned test fixtures; simulate the account-home
        # boundary without creating or reading anything in the caller's home.
        with (mock.patch.dict(os.environ, {'HOME': str(self.home), 'DOTS_TEST_HOME': str(self.home),
                                          'TMPDIR': str(self.home.parent)}, clear=True),
              mock.patch.object(module.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=str(self.home.parent))),
              self.assertRaises(RuntimeError)):
            module.require_disposable_scope()

    def test_without_braid_rejects_outside_source(self):
        source, _ = self.runtime_fixture()
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as other:
            external = Path(other) / 'hooks.json'
            external.write_bytes(source.read_bytes())
            result = subprocess.run([sys.executable, '-B', str(self.codex / 'scripts/project-codex-hooks.py'),
                                    '--source', str(external), '--without-braid'], env=self.env,
                                   capture_output=True, text=True, timeout=10, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('PreToolUse', result.stdout)


if __name__ == '__main__':
    unittest.main()
