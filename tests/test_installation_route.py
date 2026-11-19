"""Rehearse the real installation entrypoint without live or provider state."""
import hashlib
import importlib.util
import json
import os
import pwd
import re
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

from policy_fixture import PolicyFixture
from test_governance_port import ROOT, GEN


class InstallationRouteTests(unittest.TestCase):
    def test_transition_preserves_only_existing_hook_revocation(self):
        installer = self.import_installer(ROOT)
        baseline = {'hooks': {'state': {'known': {'trusted_hash': 'bound'}}}, 'model': 'original'}
        disabled = {'hooks': {'state': {'known': {'trusted_hash': 'bound', 'enabled': False}}}, 'model': 'original'}
        self.assertEqual(installer.preserve_hook_disables(baseline, disabled), disabled)
        self.assertNotIn('enabled', baseline['hooks']['state']['known'])
        for state in ({'known': {'trusted_hash': 'changed', 'enabled': False}},
                      {'unknown': {'trusted_hash': 'bound', 'enabled': False}},
                      {'known': {'trusted_hash': 'bound', 'enabled': True}},
                      {'known': {'trusted_hash': 'bound', 'enabled': 0}}):
            with self.subTest(state=state), self.assertRaises(ValueError):
                installer.preserve_hook_disables(baseline, {'hooks': {'state': state}})

    def test_update_renderer_keeps_existing_hooks_disabled(self):
        installer = self.import_installer(ROOT)
        canonical = '[hooks.state.known]\ntrusted_hash = "bound"\n'
        observed = canonical + 'enabled = false\n'
        scope = installer.module('renderer_test_scope', ROOT / 'codex/scripts/migration_scope.py')
        with (mock.patch.object(installer, 'effective_previous_review', return_value=None),
              mock.patch.dict(sys.modules, {'migration_scope': scope}),
              mock.patch.dict(os.environ, self.fixture.env, clear=True)):
            rendered = installer.update_desktop_text(canonical, observed)
        self.assertEqual(tomllib.loads(rendered), tomllib.loads(observed))

    def test_standalone_live_usage_swap_refuses_before_any_state_change(self):
        installer = self.import_installer(ROOT)
        args = SimpleNamespace(mode='machine', operation='repair-usage-directory')
        with mock.patch.object(installer.SCOPE, 'target_home') as target:
            with self.assertRaisesRegex(ValueError, 'invalidate active hook admission'):
                installer.repair_usage_directory(args)
            target.assert_not_called()

    def test_dangling_usage_repair_preserves_link_identity_and_retry_journal(self):
        import hashlib
        target = (self.runtime / 'usage-data').resolve()
        # This synthetic retired store contains no caller data.
        shutil.rmtree(target)
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        plan = json.loads((self.state / 'plan.json').read_text())
        repair_state = self.home / 'retained-repair'
        command = ('repair-usage-directory', '--home', self.home, '--mode', 'rehearsal',
            '--state-dir', repair_state, '--previous-plan-digest', digest,
            '--previous-package-digest', plan['package_digest'],
            '--previous-marker-sha256', hashlib.sha256((self.payload / 'codex/.deployment.json').read_bytes()).hexdigest(),
            '--previous-observed-config-sha256', hashlib.sha256((self.runtime / 'config.toml').read_bytes()).hexdigest())
        link_inode = (self.runtime / 'usage-data').lstat().st_ino
        managed = self.runtime / 'AGENTS.md'
        saved, metadata = managed.read_bytes(), managed.stat()
        managed.chmod(0o600)
        managed.write_bytes(saved + b'\nchanged\n')
        self.assertNotEqual(self.run_cli(*command).returncode, 0)
        self.assertFalse(repair_state.exists())
        managed.write_bytes(saved)
        managed.chmod(metadata.st_mode & 0o777)
        os.utime(managed, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        self.success(self.run_cli(*command))
        proof = json.loads((repair_state / 'proof.json').read_text())
        self.assertTrue((self.runtime / 'usage-data').is_dir())
        self.assertFalse((self.runtime / 'usage-data').is_symlink())
        self.assertEqual((repair_state / 'usage-data').lstat().st_ino, link_inode)
        self.assertFalse(target.exists(), 'The retired repository was not recreated')
        log = self.runtime / 'usage-data/synthetic-log.txt'
        log.write_text('preserve new usage data')
        # A crash after the atomic exchange may leave no completion journal.
        (repair_state / 'result.json').unlink()
        self.success(self.run_cli(*command))
        self.assertEqual(log.read_text(), 'preserve new usage data')
        managed.chmod(0o600)
        managed.write_bytes(saved + b'\nchanged again\n')
        self.assertNotEqual(self.run_cli(*command).returncode, 0)
        self.assertTrue(log.is_file())
        managed.write_bytes(saved)
        managed.chmod(metadata.st_mode & 0o777)
        os.utime(managed, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        scope = self.import_installer(ROOT).SCOPE
        self.assertEqual(scope.usage_directory_pair(self.home, proof), 'migrated')
        for key, value in (('new_directory', dict(proof['new_directory'], inode=0)),
                           ('old_link', dict(proof['old_link'], link='/unrelated')),
                           ('parents', [])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                scope.usage_directory_pair(self.home, dict(proof, **{key: value}))
        inverse = ('restore-usage-directory', *command[1:])
        target.mkdir()
        self.assertNotEqual(self.run_cli(*inverse).returncode, 0)
        self.assertTrue(log.exists())
        target.rmdir()
        self.success(self.run_cli(*inverse))
        self.assertEqual((self.runtime / 'usage-data').lstat().st_ino, link_inode)
        self.assertEqual((repair_state / 'usage-data/synthetic-log.txt').read_text(), 'preserve new usage data')
        (repair_state / 'result.json').unlink()
        self.success(self.run_cli(*inverse))
        self.success(self.operation('check', digest))
        self.success(self.run_cli(*command))
        self.assertEqual(log.read_text(), 'preserve new usage data')

    def test_selected_interpreter_survives_poisoned_path_for_apply_check_and_rollback(self):
        digest = self.success(self.prepare())['plan_digest']
        poison = self.home / 'poison-bin'
        poison.mkdir()
        marker = self.home / 'shim-executed'
        shim = poison / 'python3'
        shim.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 73\n')
        shim.chmod(0o700)
        jq_shim = poison / 'jq'
        jq_shim.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 75\n')
        jq_shim.chmod(0o700)
        self.env['PATH'] = str(poison) + os.pathsep + self.env['PATH']
        applied = self.operation('apply', digest)
        if applied.returncode:
            self.success(self.operation('rollback', digest))
        self.success(applied)
        self.success(self.operation('check', digest))
        self.success(self.operation('rollback', digest))
        self.assertFalse(marker.exists(), 'bootstrap executed a PATH-selected Python shim')
        self.assertEqual(self.snapshot(), self.before)

    def test_selected_interpreter_with_spaces_does_not_shadow_other_tools(self):
        runtime = self.home / 'selected runtime with spaces'
        runtime.mkdir()
        interpreter = runtime / 'python3'
        interpreter.symlink_to(sys.executable)
        marker = self.home / 'sibling-git-executed'
        sibling = runtime / 'git'
        sibling.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 74\n')
        sibling.chmod(0o700)

        def selected_cli(*args):
            return subprocess.run([str(interpreter), '-B', str(ROOT / 'scripts/install-codex.py'),
                *map(str, args)], cwd=ROOT, env=self.env, text=True,
                capture_output=True, timeout=120, check=False)

        self.run_cli = selected_cli
        self.test_selected_interpreter_survives_poisoned_path_for_apply_check_and_rollback()
        self.assertFalse(marker.exists(), 'selected Python directory shadowed another tool')

    def test_unavailable_explicit_bootstrap_interpreter_fails_before_projection(self):
        before = self.snapshot()
        self.fixture.env['CODEX_VALIDATION_PYTHON'] = str(self.home / 'missing interpreter')
        result = self.fixture.project('--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_managed_readiness_create_reaches_gate_with_contained_receipt(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        source = self.home / 'dev/readiness-source'
        source.mkdir()
        root = self.home / '.codex/worktrees/readiness/repository'
        root.parent.mkdir(parents=True)
        for args in (['init', '-q', '--initial-branch=main', str(source)],
                     ['-C', str(source), '-c', 'user.name=Fixture', '-c',
                      'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'fixture'],
                     ['-C', str(source), 'remote', 'add', 'origin', str(source)],
                     ['-C', str(source), 'update-ref', 'refs/remotes/origin/main', 'HEAD'],
                     ['-C', str(source), 'worktree', 'add', '-b', 'candidate', str(root), 'HEAD']):
            subprocess.run(['git', *args], env=self.env, check=True, capture_output=True, timeout=15)
        (root / '.tmp').mkdir()
        (root / '.tmp/scope.txt').write_text('example.py\n')
        exclude = source / '.git/info/exclude'
        exclude.write_text(exclude.read_text() + '\n/.tmp/pr-readiness.v1.json\n/.tmp/readiness.json\n')
        probe = subprocess.run(['git', 'rev-parse', 'main'], cwd=root,
                               env=self.installed_env(), text=True, capture_output=True, check=False)
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        command = [sys.executable, '-B', str(self.runtime / 'scripts/pr-readiness.py'),
                   '--phase', 'create', '--remote', 'origin', '--base', 'main',
                   '--scope-file', '.tmp/scope.txt', '--receipt', '.tmp/readiness.json',
                   '--write-receipt', '--json']
        result = subprocess.run(command, cwd=root, env=self.installed_env(),
                                text=True, capture_output=True, timeout=60, check=False)
        self.assertIn(result.returncode, (1, 2), result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['phase'], 'create')
        self.assertIn(payload['status'], ('blocked', 'fail'))
        self.assertNotIn('deployment policy scope', result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertTrue((root / '.tmp/readiness.json').is_file(), result.stdout + result.stderr)
        self.assertEqual(payload['repo']['root'], str(root))
        default_command = [item for item in command]
        index = default_command.index('--receipt')
        del default_command[index:index + 2]
        result = subprocess.run(default_command, cwd=root, env=self.installed_env(),
                                text=True, capture_output=True, timeout=60, check=False)
        self.assertIn(result.returncode, (1, 2), result.stdout + result.stderr)
        default_path = root / '.tmp/pr-readiness.v1.json'
        self.assertTrue(default_path.is_file(), result.stdout + result.stderr)
        check_command = [item for item in default_command if item != '--write-receipt'] + ['--check-receipt']
        checked = subprocess.run(check_command, cwd=root, env=self.installed_env(),
                                 text=True, capture_output=True, timeout=60, check=False)
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertNotIn('resource admission', checked.stdout)
        self.assertNotIn('deployment policy scope', checked.stderr)
        saved = default_path.read_bytes()
        outside = source / 'outside-scope.txt'
        outside.write_text('preserve\n')
        alias = root / '.tmp/alias.txt'
        alias.symlink_to(outside)
        for scope in (outside, alias):
            rejected_command = list(default_command)
            rejected_command[rejected_command.index('--scope-file') + 1] = str(scope)
            rejected = subprocess.run(rejected_command, cwd=root, env=self.installed_env(),
                                      text=True, capture_output=True, timeout=60, check=False)
            self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
            self.assertIn('resource admission failed', rejected.stdout)
            self.assertEqual(default_path.read_bytes(), saved)

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

    def test_prepare_content_addresses_braid_in_managed_hook_store(self):
        external = self.fixture.bin / 'braid'
        original = external.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        prepared = self.success(self.prepare())
        relative = Path('braid-' + digest) / 'braid'
        packaged = self.payload / 'codex/hooks' / relative
        runtime = self.runtime / 'hooks' / relative
        manifest = json.loads((self.payload / 'codex/hooks/hooks.json').read_text())
        commands = [hook['command'] for groups in manifest['hooks'].values()
                    for group in groups for hook in group['hooks']
                    if Path(shlex.split(hook['command'])[0]).name == 'braid']
        self.assertTrue(commands)
        self.assertEqual({shlex.split(command)[0] for command in commands}, {str(runtime)})
        self.assertEqual(packaged.read_bytes(), original)
        self.assertEqual(packaged.stat().st_mode & 0o777, 0o500)
        external.write_text('#!/bin/sh\nexit 99\n')
        self.assertEqual(packaged.read_bytes(), original)
        self.success(self.operation('apply', prepared['plan_digest']))
        self.assertEqual(runtime.read_bytes(), original)
        self.assertEqual(runtime.stat().st_mode & 0o777, 0o500)

    def test_prepare_rejects_nonexecutable_original_braid(self):
        external = self.fixture.bin / 'braid'
        before = external.read_bytes()
        external.chmod(0o600)
        runtime_before = self.snapshot()
        rejected = self.prepare()
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('original Braid input must be executable', rejected.stdout + rejected.stderr)
        self.assertEqual(external.read_bytes(), before)
        self.assertEqual(external.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.snapshot(), runtime_before)

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
                if path.name in {'hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules'}:
                    result[path.name] = ('directory', tuple(
                        (str(child.relative_to(path)), child.read_bytes() if child.is_file() else None)
                        for child in sorted(path.rglob('*'))))
                else:
                    result[path.name] = ('directory',)
        return result

    def success(self, result):
        details = ''.join(path.read_text() for path in self.state.glob('*diagnostic.json')) if result.returncode else ''
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + details)
        return json.loads(result.stdout)

    def test_seven_field_repair_requires_repaired_bytes_before_review(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        spec = importlib.util.spec_from_file_location(
            'packaged_seven', self.payload / 'codex/scripts/desktop_compatibility.py')
        compat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compat)
        path = self.runtime / 'config.toml'
        installed = path.read_text()
        changes = []
        for keys, present, value in (
            (['features', 'multi_agent'], False, None),
            (['sandbox_mode'], True, 'workspace-write'),
            (['sandbox_workspace_write'], True, {'network_access': True}),
            (['desktop', 'appearanceDarkChromeTheme'], False, None),
            (['desktop', 'appearanceDarkCodeThemeId'], True, 'codex'),
            (['desktop', 'autoArchiveAfterDays'], True, 7),
            (['plugins', 'codex-app-tools@openai-bundled'], True, {'enabled': True}),
        ):
            after = {'present': present}
            if present:
                after['value'] = value
            changes.append({'path': keys, 'after': after})
        observed = compat.overlay(installed, changes)
        path.write_text(observed)
        records = {name: (self.state / name).read_bytes()
                   for name in ('plan.json', 'result.json', 'backups/config.toml')}
        self.assertNotEqual(self.operation('prepare-desktop-review', digest).returncode, 0)
        proposal = compat.repair_candidate(installed, observed)
        self.assertEqual(path.read_text(), observed)
        path.write_text(proposal['candidate'])  # This fixture home is disposable.
        review = self.success(self.operation('prepare-desktop-review', digest))
        pin = review['review_sha256']
        self.success(self.run_cli('check', '--state-dir', self.state,
            '--plan-digest', digest, '--desktop-review-sha256', pin))
        self.assertNotEqual(self.run_cli('check', '--state-dir', self.state,
            '--plan-digest', digest, '--desktop-review-sha256', '0' * 64).returncode, 0)
        self.success(self.run_cli('rollback', '--state-dir', self.state,
            '--plan-digest', digest, '--desktop-review-sha256', pin))
        restored = tomllib.loads(path.read_text())
        self.assertEqual(restored['desktop']['autoArchiveAfterDays'], 7)
        self.assertEqual(restored['plugins']['codex-app-tools@openai-bundled'], {'enabled': True})
        self.assertIs(restored['features']['multi_agent'], True)
        self.assertNotIn('sandbox_mode', restored)
        for name in ('plan.json', 'backups/config.toml'):
            self.assertEqual((self.state / name).read_bytes(), records[name])

    def test_quote_pair_blocks_mixed_publication_and_preserves_micro_layout(self):
        # Replace one deliberately synthetic identity only in this fixture input.
        bindings = json.loads(self.bindings.read_text())
        bindings['value_0144'] = str(self.runtime / 'hooks.json') + ':pre_tool_use:2:0'
        bindings['value_0145'] = 'sha256:' + 'a' * 64
        self.bindings.write_text(json.dumps(bindings))
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        spec = importlib.util.spec_from_file_location(
            'packaged_pair', self.payload / 'codex/scripts/desktop_compatibility.py')
        compat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compat)
        config_path, hooks_path = self.runtime / 'config.toml', self.runtime / 'hooks.json'
        installed, expected_hooks = config_path.read_text(), hooks_path.read_text()
        declarations = json.loads(expected_hooks)
        states = tomllib.loads(installed)['hooks']['state']
        selected = None
        for event, groups in declarations['hooks'].items():
            for group_index, group in enumerate(groups):
                for handler_index, handler in enumerate(group['hooks']):
                    command = handler.get('command', '')
                    tokens = shlex.split(command)
                    for key, state in states.items():
                        parts = key.rsplit(':', 3)
                        if (tokens and Path(tokens[0]).name == 'braid' and len(parts) == 4
                                and parts[0] in {str(hooks_path), 'user:' + str(hooks_path)}
                                and re.sub('[^a-z]', '', parts[1].lower()) == re.sub('[^a-z]', '', event.lower())
                                and parts[-2:] == [str(group_index), str(handler_index)]
                                and re.fullmatch('sha256:[0-9a-f]{64}', state.get('trusted_hash', ''))):
                            selected = key, handler, tokens
                            break
                    if selected:
                        break
                if selected:
                    break
            if selected:
                break
        self.assertIsNotNone(selected, 'Fixture must retain a bound canonical Braid consent entry')
        key, handler, tokens = selected
        handler['command'] = '"' + tokens[0] + '" ' + ' '.join(tokens[1:])
        observed_hooks = json.dumps(declarations)
        layout = compat.micro_layout()
        layout['separateMicrophoneKeys'] = True
        observed = compat.overlay(installed, [
            {'path': ['desktop', 'codex-micro-layout'], 'after': {'present': True, 'value': layout}},
            {'path': ['hooks', 'state', key, 'trusted_hash'],
             'after': {'present': True, 'value': 'sha256:' + 'e' * 64}},
        ])
        config_path.write_text(observed)
        hooks_path.write_text(observed_hooks)
        proposal = compat.paired_repair_candidate(installed, observed, expected_hooks,
            observed_hooks, hook_source=str(hooks_path))
        self.assertEqual(config_path.read_text(), observed)
        self.assertEqual(hooks_path.read_text(), observed_hooks)
        config_path.write_text(proposal['candidate'])
        self.assertNotEqual(self.operation('prepare-desktop-review', digest).returncode, 0)
        config_path.write_text(observed)
        hooks_path.write_text(proposal['hooks_candidate'])
        self.assertNotEqual(self.operation('prepare-desktop-review', digest).returncode, 0)
        config_path.write_text(proposal['candidate'])
        review = self.success(self.operation('prepare-desktop-review', digest))
        self.success(self.run_cli('check', '--state-dir', self.state,
            '--plan-digest', digest, '--desktop-review-sha256', review['review_sha256']))
        self.assertEqual(tomllib.loads(config_path.read_text())['hooks']['state'], states)

    def desktop_restart(self):
        path = self.runtime / 'config.toml'
        data = tomllib.loads(path.read_text())
        data['notify'] = [str(self.home / 'app/notify'), 'done']
        data['mcp_servers']['node_repl'] = {
            'command': str(self.home / 'app/node'), 'args': [],
            'env': {'CODEX_HOME': str(self.runtime), 'TRUSTED_SERVICES': 'synthetic'}}
        data['desktop']['selected-avatar-id'] = 'synthetic-new-avatar'
        data['marketplaces']['openai-bundled'].pop('last_updated', None)
        for name in ('computer-use', 'unified-computer-use', 'computer-history'):
            data['plugins'][name + '@openai-bundled'] = {'enabled': True}
        path.write_text(GEN.toml_document(data))
        return path.read_bytes()

    def test_reviewed_desktop_restart_check_and_preserving_rollback(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        receipt = (self.state / 'result.json').read_bytes()
        backup = (self.state / 'backups/config.toml').read_bytes()
        observed = self.desktop_restart()
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        proposal = self.success(self.operation('prepare-desktop-review', digest))
        pin = proposal['review_sha256']
        self.assertEqual(proposal['status'], 'proposal_only')
        # A proposal alone cannot clear the normal gate.
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        self.success(self.run_cli('check', '--state-dir', self.state,
                                 '--plan-digest', digest, '--desktop-review-sha256', pin))
        env = self.installed_env() | {'DOTS_DESKTOP_REVIEW_STATE': str(self.state),
                                     'DOTS_DESKTOP_REVIEW_SHA256': pin}
        repair = subprocess.run([sys.executable, '-B', str(self.payload / 'codex/scripts/repair-runtime-config-drift.py'),
            '--config-path', str(self.runtime / 'config.toml'), '--repair', '--json'],
            env=env, cwd=self.payload, capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(repair.returncode, 0)
        self.assertEqual((self.runtime / 'config.toml').read_bytes(), observed)
        # SessionStart invokes ordinary repair without temporary review flags.
        # Neither that route nor the historical scrubber may erase Desktop.
        for script in ('repair-runtime-config-drift.py', 'scrub-computer-use-config.py'):
            ordinary = subprocess.run([sys.executable, '-B', str(self.payload / 'codex/scripts' / script),
                '--config-path', str(self.runtime / 'config.toml'), '--repair', '--json'],
                env=self.installed_env(), cwd=self.payload,
                capture_output=True, text=True, timeout=30, check=False)
            self.assertNotEqual(ordinary.returncode, 0, ordinary.stdout + ordinary.stderr)
            self.assertEqual((self.runtime / 'config.toml').read_bytes(), observed)
        self.assertNotEqual(self.operation('rollback', digest).returncode, 0)
        args = ('rollback', '--state-dir', self.state, '--plan-digest', digest,
                '--desktop-review-sha256', pin)
        self.success(self.run_cli(*args))
        restored = self.snapshot()
        for name, value in self.before.items():
            if name != 'config.toml':
                self.assertEqual(restored[name], value)
        expected = tomllib.loads(backup.decode())
        actual = tomllib.loads((self.runtime / 'config.toml').read_text())
        for key in ('approval_policy', 'permissions', 'hooks', 'default_permissions'):
            self.assertEqual(actual.get(key), expected.get(key))
        self.assertEqual(actual['mcp_servers']['node_repl']['command'], str(self.home / 'app/node'))
        self.assertEqual(actual['notify'], [str(self.home / 'app/notify'), 'done'])
        self.assertEqual((self.state / 'result.json').read_bytes(), receipt)
        self.assertEqual((self.state / 'backups/config.toml').read_bytes(), backup)
        self.success(self.run_cli(*args))

    def test_desktop_review_rejects_new_policy_or_changed_executable(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        observed = self.desktop_restart()
        config = self.runtime / 'config.toml'
        config.write_bytes(observed.replace(b'approval_policy = "on-request"', b'approval_policy = "never"'))
        self.assertNotEqual(self.operation('prepare-desktop-review', digest).returncode, 0)
        self.assertFalse((self.state / 'desktop-review.json').exists())
        config.write_bytes(observed)
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        config.write_bytes(observed.replace(b'/app/node', b'/app/unreviewed'))
        before = self.snapshot()
        for action in ('check', 'rollback'):
            result = self.run_cli(action, '--state-dir', self.state, '--plan-digest', digest,
                                  '--desktop-review-sha256', pin)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.snapshot(), before)
        config.write_bytes(observed)
        review = self.state / 'desktop-review.json'
        review.write_bytes(review.read_bytes() + b' ')
        self.assertNotEqual(self.run_cli('check', '--state-dir', self.state, '--plan-digest', digest,
                            '--desktop-review-sha256', pin).returncode, 0)

    def test_desktop_rollback_retry_and_concurrent_edit_preservation(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        # Unknown changes on any other target must block before restoration.
        target = self.runtime / 'AGENTS.md'
        original = target.read_bytes()
        target.chmod(0o600)
        target.write_text('concurrent operator change\n')
        current = self.snapshot()
        args = ('rollback', '--state-dir', self.state, '--plan-digest', digest,
                '--desktop-review-sha256', pin)
        self.assertNotEqual(self.run_cli(*args).returncode, 0)
        self.assertEqual(self.snapshot(), current)
        target.write_bytes(original)
        target.chmod(0o400)
        installer = self.import_installer(self.payload)
        load_module = installer.module
        exchanges = []

        def interrupt(name, path):
            result = load_module(name, path)
            if name == 'restoration_exchange':
                exchange = result._exchange_paths

                def fail_after_exchange(staged, destination):
                    exchange(staged, destination)
                    exchanges.append(destination)
                    raise OSError('synthetic interrupted restoration')

                result._exchange_paths = fail_after_exchange
            return result

        with mock.patch.dict(os.environ, self.installed_env(), clear=True):
            with mock.patch.object(sys, 'path', [str(self.payload / 'codex/scripts'), *sys.path]), \
                    mock.patch.object(installer, 'module', side_effect=interrupt), \
                    mock.patch.dict(sys.modules):
                sys.modules.pop('migration_scope', None)
                with self.assertRaisesRegex(OSError, 'synthetic interrupted'):
                    installer.restore(self.state, digest, pin)
        self.assertEqual(len(exchanges), 1)
        self.success(self.run_cli(*args))
        self.assertIn('node_repl', tomllib.loads((self.runtime / 'config.toml').read_text())['mcp_servers'])

    def test_partial_desktop_registration_requires_review_before_repair(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        config = self.runtime / 'config.toml'
        installed = config.read_bytes()
        for kind in ('history', 'notify'):
            with self.subTest(kind=kind):
                data = tomllib.loads(installed.decode())
                if kind == 'history':
                    data['plugins']['computer-history@openai-bundled'] = {'enabled': True}
                else:
                    data['notify'] = [str(self.home / 'app/desktop-notify'), 'done']
                config.write_text(GEN.toml_document(data))
                observed = config.read_bytes()
                result = subprocess.run([sys.executable, '-B',
                    str(self.payload / 'codex/scripts/repair-runtime-config-drift.py'),
                    '--config-path', str(config), '--repair', '--json'],
                    env=self.installed_env(), cwd=self.payload,
                    capture_output=True, text=True, timeout=30, check=False)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(config.read_bytes(), observed)

    def test_initial_prepare_cannot_discard_independent_desktop_registration(self):
        config = self.runtime / 'config.toml'
        data = tomllib.loads(config.read_text())
        data['plugins']['computer-history@openai-bundled'] = {'enabled': True}
        config.write_text(GEN.toml_document(data))
        before = self.snapshot()
        self.assertNotEqual(self.prepare().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_metadata_only_proposal_also_blocks_ordinary_repair(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        config = self.runtime / 'config.toml'
        data = tomllib.loads(config.read_text())
        data['desktop']['selected-avatar-id'] = 'independent-avatar-change'
        config.write_text(GEN.toml_document(data))
        observed = config.read_bytes()
        self.success(self.operation('prepare-desktop-review', digest))
        for script in ('repair-runtime-config-drift.py', 'scrub-computer-use-config.py'):
            result = subprocess.run([sys.executable, '-B', str(self.payload / 'codex/scripts' / script),
                '--config-path', str(config), '--repair', '--json'],
                env=self.installed_env(), cwd=self.payload,
                capture_output=True, text=True, timeout=30, check=False)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(config.read_bytes(), observed)

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
        self.assertFalse((self.runtime / 'scripts').is_symlink())
        self.assertFalse((self.runtime / 'model-catalogs').is_symlink())
        for name in ('hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules'):
            self.assertTrue((self.runtime / name).is_dir())
            for source in (self.payload / 'codex' / name).rglob('*'):
                if source.is_file():
                    copied = self.runtime / name / source.relative_to(self.payload / 'codex' / name)
                    self.assertFalse(copied.is_symlink())
                    self.assertFalse(copied.samefile(source))
                    self.assertEqual(copied.read_bytes(), source.read_bytes())
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

    def second_installation(self):
        old = self.payload
        self.state = self.home / 'installation/two'
        self.payload = self.state / 'payload'
        values = json.loads(self.bindings.read_text())
        self.bindings.write_text(json.dumps({key: value.replace(str(old), str(self.payload))
                                            for key, value in values.items()}))

    def import_installer(self, root):
        spec = importlib.util.spec_from_file_location('copy_installation_probe', root / 'codex/scripts/install-codex.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        return installer

    def test_copy_publication_rejects_edit_after_apply_preflight(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        installer = self.import_installer(self.payload)
        target = self.runtime / 'AGENTS.md'
        before = installer.describe(target)
        expected = installer.semantic(installer.describe(self.payload / 'codex/AGENTS.md'))
        target.chmod(0o600)
        target.write_text('Concurrent local edit must survive.\n')
        with mock.patch.dict(os.environ, self.installed_env(), clear=True):
            with self.assertRaisesRegex(ValueError, 'changed after preparation'):
                installer.publish_copy(self.state, {'name': 'AGENTS.md', 'source': 'codex/AGENTS.md'},
                                       expected, before, None)
        self.assertEqual(target.read_text(), 'Concurrent local edit must survive.\n')

    def test_prepare_rejects_drift_during_package_assembly(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.second_installation()
        installer = self.import_installer(ROOT)
        public_files = installer.public_files
        target = self.runtime / 'AGENTS.md'
        def change_after_initial_check(source):
            result = public_files(source)
            target.chmod(0o600)
            target.write_text('Edit during preparation must survive.\n')
            return result
        arguments = SimpleNamespace(home=self.home, mode='rehearsal', state_dir=self.state,
                                    bindings=self.bindings, braid_bin=self.fixture.bin / 'braid',
                                    previous_desktop_review_sha256=None)
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(
                installer, 'public_files', side_effect=change_after_initial_check):
            with self.assertRaisesRegex(ValueError, 'Preparation refused'):
                installer.assemble(arguments)
        self.assertEqual(target.read_text(), 'Edit during preparation must survive.\n')
        diagnostic = json.loads((self.state / 'diagnostic.json').read_text())
        self.assertIn('Runtime drift', diagnostic['stdout'])
        self.assertFalse((self.state / 'plan.json').exists())

    def test_absent_target_recovery_preserves_a_racing_directory_edit(self):
        installer = self.import_installer(ROOT)
        directory = self.home / 'tmp/model-catalogs'
        directory.mkdir()
        (directory / 'original.json').write_text('original')
        before = installer.describe(directory)
        recovery = self.home / 'tmp/recovery'
        recovery.mkdir()
        rename = installer.os.rename
        def concurrent_write(source, destination):
            (source / 'new-local.json').write_text('must survive')
            rename(source, destination)
        with mock.patch.object(installer.os, 'rename', side_effect=concurrent_write):
            with self.assertRaisesRegex(ValueError, 'Concurrent replacement preserved'):
                installer.retire_created_target(directory, recovery, before)
        held = list(recovery.glob('.restore-created-*/model-catalogs'))
        self.assertEqual(len(held), 1)
        self.assertEqual((held[0] / 'new-local.json').read_text(), 'must survive')
        self.assertEqual((held[0] / 'original.json').read_text(), 'original')
        self.fixture.assert_preserved(self)

    def test_copies_preserve_nested_directory_modes(self):
        installer = self.import_installer(ROOT)
        source = self.home / 'tmp/source/scripts'
        nested = source / 'nested'
        nested.mkdir(parents=True)
        source.chmod(0o700)
        nested.chmod(0o700)
        (nested / 'data.txt').write_text('synthetic')
        target = self.home / 'tmp/destination/scripts'
        target.parent.mkdir()
        installer.copy_resource(source, target)
        self.assertEqual(installer.describe(source), installer.describe(target))
        self.assertEqual((target / 'nested').stat().st_mode & 0o777, 0o700)

    def test_linux_rename_modes_are_journalled_and_restored_on_error(self):
        installer = self.import_installer(ROOT)
        state = self.home / 'tmp/linux-rename'
        staged = state / '.copy-test/scripts'
        target = self.home / 'tmp/runtime/scripts'
        staged.mkdir(parents=True)
        target.mkdir(parents=True)
        staged.chmod(0o500)
        target.chmod(0o500)
        with mock.patch.object(installer.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                with installer.renameable_directories(state, staged, target):
                    self.assertEqual(staged.stat().st_mode & 0o777, 0o700)
                    self.assertEqual(target.stat().st_mode & 0o777, 0o700)
                    self.assertTrue((state / 'rename-modes.json').exists())
                    raise RuntimeError('synthetic failure')
        self.assertEqual(staged.stat().st_mode & 0o777, 0o500)
        self.assertEqual(target.stat().st_mode & 0o777, 0o500)
        self.assertFalse((state / 'rename-modes.json').exists())
        self.fixture.assert_preserved(self)

    @unittest.skipUnless(sys.platform == 'darwin' or sys.platform.startswith('linux'),
                         'Atomic directory exchange is supported on macOS and Linux')
    def test_killed_directory_swap_recovers_modes_before_and_after_exchange(self):
        installer = self.import_installer(ROOT)
        for phase in ('before', 'after'):
            with self.subTest(phase=phase):
                state = self.home / 'tmp' / phase
                staged = state / '.copy-kill/scripts'
                runtime = self.home / 'tmp' / ('runtime-' + phase)
                target = runtime / 'scripts'
                staged.mkdir(parents=True)
                target.mkdir(parents=True)
                (staged / 'identity.txt').write_text('new')
                (target / 'identity.txt').write_text('old')
                staged.chmod(0o500)
                target.chmod(0o500)
                probe = """import ctypes, importlib.util, os, signal, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('rename_kill_probe', sys.argv[1])
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
state, staged, target = map(Path, sys.argv[2:5])
with installer.renameable_directories(state, staged, target):
    if sys.argv[5] == 'after':
        library = ctypes.CDLL(None, use_errno=True)
        if sys.platform == 'darwin':
            rename = library.renamex_np
            rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
            result = rename(os.fsencode(staged), os.fsencode(target), 2)
        else:
            rename = library.renameat2
            rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
            result = rename(-100, os.fsencode(staged), -100, os.fsencode(target), 2)
        assert result == 0
    os.kill(os.getpid(), signal.SIGKILL)
"""
                result = subprocess.run([sys.executable, '-B', '-c', probe,
                    str(ROOT / 'codex/scripts/install-codex.py'), str(state), str(staged), str(target), phase],
                    env=self.env, text=True, capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, -9, result.stdout + result.stderr)
                self.assertEqual(staged.stat().st_mode & 0o777, 0o700)
                self.assertEqual(target.stat().st_mode & 0o777, 0o700)
                self.assertTrue((state / 'rename-modes.json').exists())
                installer.recover_rename_permissions(state, runtime)
                self.assertEqual(staged.stat().st_mode & 0o777, 0o500)
                self.assertEqual(target.stat().st_mode & 0o777, 0o500)
                self.assertEqual((target / 'identity.txt').read_text(), 'new' if phase == 'after' else 'old')
                self.assertFalse((state / 'rename-modes.json').exists())

    def test_copied_helpers_resolve_the_installed_source(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        environment = self.installed_env()
        environment.pop('CODEX_CONFIG_SOURCE_ROOT', None)
        commands = [
            [sys.executable, '-B', str(self.runtime / 'scripts/validate-codex-config.py')],
            [sys.executable, '-B', str(self.runtime / 'scripts/validate-execpolicy-rules.py'), '--static-only'],
            ['bash', str(self.runtime / 'scripts/audit-codex-symlinks.sh')],
            ['bash', str(self.runtime / 'scripts/reconcile-config-projection.sh'), '--check', '--scope', 'codex'],
        ]
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(command, env=environment, cwd=self.home / 'tmp',
                    text=True, capture_output=True, timeout=60, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before)

    def test_reviewed_desktop_update_preserves_accepted_state_and_rollback(self):
        first_digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', first_digest))
        first_state = self.state
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', first_digest))['review_sha256']
        self.assertNotEqual(self.operation('check', first_digest).returncode, 0)
        observed = self.snapshot()
        self.second_installation()
        result = self.run_cli('prepare', '--home', self.home, '--state-dir', self.state,
            '--bindings', self.bindings, '--braid-bin', self.fixture.bin / 'braid',
            '--mode', 'rehearsal', '--previous-desktop-review-sha256', pin)
        digest = self.success(result)['plan_digest']
        self.assertEqual(self.snapshot(), observed)
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        current = tomllib.loads((self.runtime / 'config.toml').read_text())
        previous = tomllib.loads(observed['config.toml'][1].decode())
        for key in ('notify', 'mcp_servers', 'desktop', 'plugins', 'marketplaces'):
            if key == 'mcp_servers':
                self.assertEqual(current[key]['node_repl'], previous[key]['node_repl'])
            else:
                self.assertEqual(current[key], previous[key])
        config = self.runtime / 'config.toml'
        accepted = config.read_bytes()
        pending = self.state / 'desktop-review.json'
        pending.write_text('{}')
        command = [sys.executable, '-B', str(self.payload / 'codex/scripts/repair-runtime-config-drift.py'),
                   '--config-path', str(config), '--repair', '--json']
        result = subprocess.run(command, cwd=self.payload, env=self.installed_env(),
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(config.read_bytes(), accepted)
        pending.unlink()
        current['notify'].append('unapproved-newer-registration')
        config.write_text(GEN.toml_document(current))
        newer = config.read_bytes()
        result = subprocess.run(command, cwd=self.payload, env=self.installed_env(),
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(config.read_bytes(), newer)
        config.write_bytes(accepted)
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), observed)
        self.success(self.run_cli('check', '--state-dir', first_state,
            '--plan-digest', first_digest, '--desktop-review-sha256', pin))

    def test_empty_followup_review_preserves_effective_desktop_state(self):
        first = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', first))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', first))['review_sha256']
        self.second_installation()
        prepared = self.success(self.run_cli('prepare', '--home', self.home,
            '--state-dir', self.state, '--bindings', self.bindings,
            '--braid-bin', self.fixture.bin / 'braid', '--mode', 'rehearsal',
            '--previous-desktop-review-sha256', pin))
        second = prepared['plan_digest']
        self.success(self.operation('apply', second))
        reviewed = self.success(self.operation('prepare-desktop-review', second))
        self.assertEqual(reviewed['changed_paths'], [])
        previous = (self.runtime / 'config.toml').read_text()
        old_payload = self.payload
        self.state = self.home / 'installation/three'
        self.payload = self.state / 'payload'
        values = json.loads(self.bindings.read_text())
        self.bindings.write_text(json.dumps({key:value.replace(str(old_payload), str(self.payload))
                                            for key,value in values.items()}))
        third = self.success(self.run_cli('prepare', '--home', self.home,
            '--state-dir', self.state, '--bindings', self.bindings,
            '--braid-bin', self.fixture.bin / 'braid', '--mode', 'rehearsal',
            '--previous-desktop-review-sha256', reviewed['review_sha256']))['plan_digest']
        self.success(self.operation('apply', third))
        self.success(self.operation('check', third))
        installer = self.import_installer(self.payload)
        compat = installer.module('third_generation_compat', self.payload / 'codex/scripts/desktop_compatibility.py')
        expected = tomllib.loads(previous.replace(str(old_payload), str(self.payload)))
        actual = tomllib.loads((self.runtime / 'config.toml').read_text())
        self.assertTrue(compat.equal(actual, expected), 'An empty follow-up review must retain all accepted Desktop values and absences')
        preserved = self.snapshot()
        for name in ('config.toml', '.deployment.json'):
            path = old_payload / 'codex' / name
            raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
            try:
                path.chmod(0o600)
                if name == 'config.toml':
                    path.write_bytes(raw + b'\n# tampered prior canonical input\n')
                else:
                    marker = json.loads(raw)
                    marker['files'] = []
                    path.write_text(json.dumps(marker))
                with mock.patch.dict(os.environ, self.installed_env(), clear=True):
                    with self.assertRaisesRegex(ValueError, 'Previous Desktop (canonical input|package inventory) changed'):
                        installer.packaged_previous_review()
                self.assertEqual(self.snapshot(), preserved)
            finally:
                path.write_bytes(raw)
                path.chmod(mode)

    def test_reviewed_update_restart_review_uses_overlay_baseline(self):
        first_digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', first_digest))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', first_digest))['review_sha256']
        previous = self.snapshot()
        self.second_installation()
        digest = self.success(self.prepare_reviewed_update(pin))['plan_digest']
        self.success(self.operation('apply', digest))
        config = self.runtime / 'config.toml'
        reformatted = config.read_bytes() + b'\n# Desktop formatting only\n'
        changed = tomllib.loads(reformatted.decode())
        changed['sandbox_mode'] = 'read-only'
        config.write_text(GEN.toml_document(changed))
        semantic_drift = self.snapshot()
        self.assertNotEqual(self.operation('prepare-desktop-review', digest).returncode, 0)
        self.assertFalse((self.state / 'desktop-review.json').exists())
        self.assertEqual(self.snapshot(), semantic_drift)
        config.write_bytes(reformatted)
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        proposal = self.success(self.operation('prepare-desktop-review', digest))
        self.assertEqual(proposal['changed_paths'], [])
        self.assertEqual(config.read_bytes(), reformatted)
        rollback = json.loads((self.state / 'desktop-review.json').read_text())['rollback']
        self.assertEqual(tomllib.loads(rollback), tomllib.loads(previous['config.toml'][1].decode()))
        previous['config.toml'] = ('file', rollback.encode())
        review = proposal['review_sha256']
        self.success(self.run_cli('check', '--state-dir', self.state, '--plan-digest', digest,
                                 '--desktop-review-sha256', review))
        config.write_text(GEN.toml_document(changed))
        semantic_drift = self.snapshot()
        self.assertNotEqual(self.run_cli('check', '--state-dir', self.state, '--plan-digest', digest,
                                        '--desktop-review-sha256', review).returncode, 0)
        self.assertNotEqual(self.run_cli('rollback', '--state-dir', self.state, '--plan-digest', digest,
                                        '--desktop-review-sha256', review).returncode, 0)
        self.assertEqual(self.snapshot(), semantic_drift)
        config.write_bytes(reformatted)
        self.success(self.run_cli('rollback', '--state-dir', self.state, '--plan-digest', digest,
                                 '--desktop-review-sha256', review))
        self.assertEqual(self.snapshot(), previous)

    def formatting_review_args(self, digest):
        import hashlib
        plan = json.loads((self.state / 'plan.json').read_text())
        return ('prepare-formatting-review', '--state-dir', self.state, '--plan-digest', digest,
                '--package-digest', plan['package_digest'], '--expected-config-sha256',
                plan['expected']['config.toml']['sha256'], '--observed-config-sha256',
                hashlib.sha256((self.runtime / 'config.toml').read_bytes()).hexdigest())

    def test_external_formatting_review_pins_chain_and_refusals(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        prior_state = self.state
        self.second_installation()
        digest = self.success(self.prepare_reviewed_update(pin))['plan_digest']
        self.success(self.operation('apply', digest))
        config = self.runtime / 'config.toml'
        config.write_bytes(config.read_bytes() + b'\n# harmless formatting\n')
        formatted = config.read_bytes()
        config_mode = config.stat().st_mode & 0o777
        args = self.formatting_review_args(digest)

        def refused(arguments=args):
            before = self.snapshot()
            result = self.run_cli(*arguments)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertFalse((self.state / 'desktop-review.json').exists())
            self.assertEqual(self.snapshot(), before)

        for index in (4, 6, 8, 10):
            with self.subTest(pin_index=index):
                changed = list(args)
                changed[index] = '0' * 64
                refused(changed)
        data = tomllib.loads(formatted.decode())
        data['features']['multi_agent'] = 1  # Python bool == int must not clear a policy change.
        config.write_text(GEN.toml_document(data))
        refused(self.formatting_review_args(digest))
        config.write_bytes(formatted)
        review = prior_state / 'desktop-review.json'
        original = review.read_bytes()
        review.write_bytes(original + b'\n')
        refused()
        review.write_bytes(original)
        plan_alias = self.home / 'shared-plan.json'
        os.link(self.state / 'plan.json', plan_alias)
        refused()
        plan_alias.unlink()
        config.unlink()
        config.symlink_to(self.home / 'other-config.toml')
        (self.home / 'other-config.toml').write_bytes(formatted)
        refused()
        config.unlink()
        config.write_bytes(formatted)
        config.chmod(config_mode)
        proposal = self.success(self.run_cli(*args))
        self.assertEqual(proposal['changed_paths'], [])
        self.assertEqual(config.read_bytes(), formatted)
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        self.success(self.run_cli('check', '--state-dir', self.state, '--plan-digest', digest,
                                 '--desktop-review-sha256', proposal['review_sha256']))

    def test_external_formatting_review_rechecks_late_evidence(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        prior_state = self.state
        self.second_installation()
        digest = self.success(self.prepare_reviewed_update(pin))['plan_digest']
        self.success(self.operation('apply', digest))
        config = self.runtime / 'config.toml'
        config.write_bytes(config.read_bytes() + b'\n# formatting\n')
        options = self.formatting_review_args(digest)
        arguments = SimpleNamespace(plan_digest=options[4], package_digest=options[6],
                                    expected_config_sha256=options[8], observed_config_sha256=options[10])
        installer = self.import_installer(ROOT)
        verify = installer.verified_public_payload
        for path in (config, self.runtime / 'AGENTS.md', self.state / 'plan.json',
                     self.state / 'result.json', prior_state / 'desktop-review.json',
                     self.payload / 'codex/.deployment.json', self.payload / 'README.md'):
            with self.subTest(path=path.name):
                original, mode = path.read_bytes(), path.stat().st_mode & 0o777
                calls = []

                def race(*args, **kwargs):
                    result = verify(*args, **kwargs)
                    calls.append(None)
                    if len(calls) == 2:
                        path.chmod(0o600)
                        path.write_bytes(original + b'\n')
                        path.chmod(mode)
                    return result

                try:
                    with mock.patch.dict(os.environ, self.installed_env(), clear=True), \
                            mock.patch.object(installer, 'verified_public_payload', side_effect=race):
                        with self.assertRaises(ValueError):
                            installer.prepare_formatting_review(arguments, self.state)
                    self.assertEqual(len(calls), 2)
                    self.assertFalse((self.state / 'desktop-review.json').exists())
                    self.assertEqual(path.read_bytes(), original + b'\n')
                finally:
                    path.chmod(0o600)
                    path.write_bytes(original)
                    path.chmod(mode)

    def test_external_presentation_review_preserves_only_selected_themes(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        self.second_installation()
        digest = self.success(self.prepare_reviewed_update(pin))['plan_digest']
        self.success(self.operation('apply', digest))
        config = self.runtime / 'config.toml'
        data = tomllib.loads(config.read_text())
        data['desktop'].pop('appearanceDarkChromeTheme', None)
        data['desktop'].pop('appearanceDarkCodeThemeId')
        config.write_text(GEN.toml_document(data))
        selected = config.read_bytes()

        def arguments():
            options = list(self.formatting_review_args(digest))
            options[0] = 'prepare-presentation-review'
            return options

        self.assertNotEqual(self.run_cli(*self.formatting_review_args(digest)).returncode, 0)
        for section, key, value in (('plugins', 'computer-history@openai-bundled', {'enabled': False}),
                                    (None, 'sandbox_mode', 'read-only')):
            changed = tomllib.loads(selected.decode())
            target = changed if section is None else changed[section]
            target[key] = value
            config.write_text(GEN.toml_document(changed))
            snapshot = self.snapshot()
            self.assertNotEqual(self.run_cli(*arguments()).returncode, 0)
            self.assertFalse((self.state / 'desktop-review.json').exists())
            self.assertEqual(self.snapshot(), snapshot)
        config.write_bytes(selected)
        snapshot = self.snapshot()
        proposal = self.success(self.run_cli(*arguments()))
        self.assertTrue(proposal['changed_paths'])
        self.assertTrue(all(path in [['desktop', 'appearanceDarkChromeTheme'],
                                    ['desktop', 'appearanceDarkCodeThemeId']]
                            for path in proposal['changed_paths']))
        self.assertEqual(self.snapshot(), snapshot)
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        self.success(self.run_cli('check', '--state-dir', self.state, '--plan-digest', digest,
                                 '--desktop-review-sha256', proposal['review_sha256']))
        self.assertEqual(config.read_bytes(), selected)

    def legacy_reviewed_state(self):
        """Build two real old-policy generations, never copy caller runtime state."""
        source = self.home / 'legacy-source'
        source.mkdir()
        installer = self.import_installer(ROOT)
        for row in installer.public_files(ROOT):
            target = source / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / row['path'], target)
        bundle_path = source / 'codex/templates/policy-bundle.json'
        bundle = json.loads(bundle_path.read_text())
        legacy = json.loads((ROOT / 'tests/fixtures/legacy-root-preferences.json').read_text())
        bundle['config']['model'] = legacy['model']
        bundle['config']['model_reasoning_effort'] = legacy['model_reasoning_effort']
        bundle['config']['desktop'].update(legacy['desktop'])
        bundle['config']['desktop'].pop('autoArchiveAfterDays', None)
        bundle['config']['marketplaces']['openai-primary-runtime']['last_updated'] = '2026-07-04T17:07:48Z'
        for key in ('@local:value_0174', '@local:value_0175', '@local:value_0176', '@local:value_0177'):
            bundle['config']['projects'].pop(key)
        bundle_path.write_text(json.dumps(bundle))
        subprocess.run(['git', 'init', '-q', str(source)], env=self.env, check=True, capture_output=True)
        values = json.loads(self.bindings.read_text())
        projects = [values.pop(key) for key in ('value_0174', 'value_0175', 'value_0176', 'value_0177')]
        self.bindings.write_text(json.dumps(values))

        def source_cli(*args):
            return subprocess.run([sys.executable, '-B', str(source / 'codex/scripts/install-codex.py'),
                *map(str, args)], cwd=source, env=self.env, text=True, capture_output=True,
                timeout=180, check=False)

        digest = self.success(source_cli('prepare', '--home', self.home, '--state-dir', self.state,
            '--bindings', self.bindings, '--braid-bin', self.fixture.bin / 'braid', '--mode', 'rehearsal'))['plan_digest']
        self.success(self.packaged_operation('apply', digest))
        self.desktop_restart()
        pin = self.success(self.packaged_operation('prepare-desktop-review', digest))['review_sha256']
        self.second_installation()
        digest = self.success(source_cli('prepare', '--home', self.home, '--state-dir', self.state,
            '--bindings', self.bindings, '--braid-bin', self.fixture.bin / 'braid', '--mode', 'rehearsal',
            '--previous-desktop-review-sha256', pin))['plan_digest']
        self.success(self.packaged_operation('apply', digest))
        return digest, projects

    def packaged_operation(self, operation, digest):
        return subprocess.run([sys.executable, '-B', str(self.payload / 'scripts/install-codex.py'),
            operation, '--state-dir', str(self.state), '--plan-digest', digest], cwd=self.payload,
            env=self.installed_env(), text=True, capture_output=True, timeout=180, check=False)

    def test_policy_transition_preserves_selected_preferences_and_exact_rollback(self):
        import hashlib
        previous_digest, projects = self.legacy_reviewed_state()
        previous_state, previous_payload = self.state, self.payload
        config = self.runtime / 'config.toml'
        selected = tomllib.loads(config.read_text())
        selected['model'] = 'gpt-6-astra'
        selected['model_reasoning_effort'] = 'high'
        selected['desktop'].pop('appearanceDarkChromeTheme', None)
        selected['desktop']['appearanceDarkCodeThemeId'] = 'codex'
        selected['desktop']['autoArchiveAfterDays'] = 1
        del selected['marketplaces']['openai-primary-runtime']['last_updated']
        for project in projects:
            selected['projects'][project] = {'trust_level': 'trusted'}
        config.write_text(GEN.toml_document(selected))
        before = self.snapshot()
        previous_plan = json.loads((self.state / 'plan.json').read_text())
        self.state = self.home / 'installation/three'
        self.payload = self.state / 'payload'
        values = {key: value.replace(str(previous_payload), str(self.payload))
                  for key, value in json.loads(self.bindings.read_text()).items()}
        values.update(dict(zip(('value_0174', 'value_0175', 'value_0176', 'value_0177'), projects)))
        self.bindings.write_text(json.dumps(values))
        args = ('prepare-policy-update', '--home', self.home, '--state-dir', self.state,
            '--bindings', self.bindings, '--bindings-sha256', hashlib.sha256(self.bindings.read_bytes()).hexdigest(),
            '--braid-bin', self.fixture.bin / 'braid', '--mode', 'rehearsal',
            '--previous-plan-digest', previous_digest, '--previous-package-digest', previous_plan['package_digest'],
            '--previous-marker-sha256', hashlib.sha256((previous_payload / 'codex/.deployment.json').read_bytes()).hexdigest(),
            '--previous-expected-config-sha256', previous_plan['expected']['config.toml']['sha256'],
            '--previous-observed-config-sha256', hashlib.sha256(config.read_bytes()).hexdigest())
        for flag in ('--bindings-sha256', '--previous-plan-digest', '--previous-package-digest',
                     '--previous-marker-sha256', '--previous-expected-config-sha256',
                     '--previous-observed-config-sha256'):
            with self.subTest(wrong_pin=flag):
                changed = list(args)
                changed[changed.index(flag) + 1] = '0' * 64
                self.assertNotEqual(self.run_cli(*changed).returncode, 0)
                self.assertFalse(self.state.exists())
                self.assertEqual(self.snapshot(), before)
        selected_bytes = config.read_bytes()
        for mutation in ('extra-project', 'changed-trust', 'removed-trust', 'unselected-policy',
                         'archive-bool', 'archive-other-int', 'metadata-value', 'metadata-bool',
                         'metadata-source', 'metadata-type', 'metadata-other-marketplace'):
            with self.subTest(runtime_drift=mutation):
                drift = tomllib.loads(selected_bytes.decode())
                existing = next(path for path in drift['projects'] if path not in projects)
                if mutation == 'extra-project':
                    drift['projects'][str(self.home / 'unselected')] = {'trust_level': 'trusted'}
                elif mutation == 'changed-trust':
                    drift['projects'][existing]['trust_level'] = 'untrusted'
                elif mutation == 'removed-trust':
                    del drift['projects'][existing]
                elif mutation == 'archive-bool':
                    drift['desktop']['autoArchiveAfterDays'] = True
                elif mutation == 'archive-other-int':
                    drift['desktop']['autoArchiveAfterDays'] = 2
                elif mutation in ('metadata-value', 'metadata-bool'):
                    drift['marketplaces']['openai-primary-runtime']['last_updated'] = (
                        True if mutation == 'metadata-bool' else '2026-07-04T17:07:48Z')
                elif mutation == 'metadata-source':
                    drift['marketplaces']['openai-primary-runtime']['source'] += '/changed'
                elif mutation == 'metadata-type':
                    drift['marketplaces']['openai-primary-runtime']['source_type'] = 'git'
                elif mutation == 'metadata-other-marketplace':
                    other = next(key for key in drift['marketplaces'] if key != 'openai-primary-runtime')
                    drift['marketplaces'][other]['last_updated'] = '2026-07-04T17:07:48Z'
                else:
                    drift['approval_policy'] = 'never'
                config.write_text(GEN.toml_document(drift))
                changed = list(args)
                changed[-1] = hashlib.sha256(config.read_bytes()).hexdigest()
                snapshot = self.snapshot()
                self.assertNotEqual(self.run_cli(*changed).returncode, 0)
                self.assertFalse(self.state.exists())
                self.assertEqual(self.snapshot(), snapshot)
                config.write_bytes(selected_bytes)
        alias = self.home / 'config-hardlink'
        os.link(config, alias)
        self.assertNotEqual(self.run_cli(*args).returncode, 0)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.snapshot(), before)
        alias.unlink()
        installer = self.import_installer(ROOT)
        generator = installer.module('transition_generation_race', ROOT / 'scripts/generate-codex-policy.py')
        render = generator.render
        binding_bytes = self.bindings.read_bytes()
        def changed_bindings(path):
            rendered = render(path)
            path.write_bytes(binding_bytes + b' ')
            return rendered
        admission_args = SimpleNamespace(home=self.home, state_dir=self.state, mode='rehearsal',
            bindings=self.bindings, previous_desktop_review_sha256=None)
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(installer, 'module', return_value=generator), \
                mock.patch.object(generator, 'render', side_effect=changed_bindings), \
                self.assertRaisesRegex(ValueError, 'bindings changed during generation'):
            installer.assemble(admission_args, policy_update=True)
        self.bindings.write_bytes(binding_bytes)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.snapshot(), before)
        digest = self.success(self.run_cli(*args))['plan_digest']
        self.assertEqual(self.snapshot(), before)
        proof = json.loads((self.payload / 'codex/.policy-transition.json').read_text())
        canonical = tomllib.loads((self.payload / 'codex/config.toml').read_text())
        for key, value in (('schema_version', True), ('previous', []), ('approved_projects', 'bad')):
            with self.subTest(malformed_proof=key), \
                    self.assertRaisesRegex(ValueError, 'Invalid canonical policy transition proof'):
                installer.validate_policy_transition(self.home, dict(proof, **{key: value}),
                    (self.payload / 'codex/config.toml').read_text())
        for value in ('malformed', []):
            with self.subTest(malformed_projects=value):
                malformed = dict(canonical, projects=value)
                raw = GEN.toml_document(malformed)
                bound = dict(proof, canonical_sha256=hashlib.sha256(raw.encode()).hexdigest())
                with mock.patch.dict(os.environ, self.env, clear=True), \
                        self.assertRaisesRegex(ValueError, 'project trust must be a table'):
                    installer.validate_policy_transition(self.home, bound, raw)
        for path in (config, self.runtime / '.dots-package.json', self.runtime / 'AGENTS.md', previous_state / 'result.json',
                     previous_payload / 'codex/.previous-desktop-review.json'):
            with self.subTest(apply_race=path.name):
                raw, metadata = path.read_bytes(), path.stat()
                path.chmod(0o600)
                path.write_bytes(raw + b'\n ')
                snapshot = self.snapshot()
                self.assertNotEqual(self.operation('apply', digest).returncode, 0)
                self.assertEqual(self.snapshot(), snapshot)
                path.write_bytes(raw)
                path.chmod(metadata.st_mode & 0o777)
                os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        # Fail at the existing real projector boundary, then retry the prepared
        # transition with its partially published config and managed resources.
        shadow = self.fixture.bin / 'bash'
        shadow.write_text('#!/bin/sh\nexit 75\n')
        shadow.chmod(0o700)
        self.assertNotEqual(self.operation('apply', digest).returncode, 0)
        self.assertEqual(json.loads((self.state / 'result.json').read_text())['status'], 'failed')
        self.assertNotEqual(self.snapshot(), before)
        shadow.unlink()
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        actual = tomllib.loads(config.read_text())
        for key in ('model', 'model_reasoning_effort', 'desktop'):
            self.assertEqual(actual[key], selected[key])
        for project in projects:
            self.assertEqual(actual['projects'][project], selected['projects'][project])
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), before)
        old_check = subprocess.run([sys.executable, '-B', str(previous_payload / 'scripts/install-codex.py'),
            'check', '--state-dir', str(previous_state), '--plan-digest', previous_digest],
            cwd=previous_payload, env=self.env | {'CODEX_CONFIG_SOURCE_ROOT': str(previous_payload / 'codex')},
            text=True, capture_output=True, timeout=30, check=False)
        self.assertNotEqual(old_check.returncode, 0)

    def prepare_usage_policy_update(self, *, disable_hooks=False, additional_project=False,
                                   bind_additional_project=True, desktop_preferences=False):
        import hashlib
        shutil.rmtree((self.runtime / 'usage-data').resolve())
        previous_digest, projects = self.legacy_reviewed_state()
        previous_payload = self.payload
        previous_plan = json.loads((self.state / 'plan.json').read_text())
        config = self.runtime / 'config.toml'
        previous_config = config.read_bytes()
        selected = tomllib.loads(config.read_text())
        extra = str(self.home / 'Documents/Codex/another-workspace')
        if additional_project:
            Path(extra).mkdir(parents=True)
            selected['projects'][extra] = {'trust_level': 'trusted'}
        selected['model'] = 'gpt-6-astra'
        selected['model_reasoning_effort'] = 'high'
        selected['desktop'].pop('appearanceDarkChromeTheme', None)
        selected['desktop']['appearanceDarkCodeThemeId'] = 'codex'
        selected['desktop']['autoArchiveAfterDays'] = 1
        del selected['marketplaces']['openai-primary-runtime']['last_updated']
        for project in projects:
            selected['projects'][project] = {'trust_level': 'trusted'}
        if disable_hooks:
            for entry in selected['hooks']['state'].values():
                entry['enabled'] = False
        config.write_text(GEN.toml_document(selected))
        if desktop_preferences:
            selected['desktop']['git-commit-instructions'] = 'Use a specific subject.\nExplain the change.'
            selected['model'] = 'gpt-6-sol'
            selected['model_reasoning_effort'] = 'low'
            selected['desktop']['daybreak-enabled'] = {
                'accountId': 'synthetic-account', 'userId': 'synthetic-user', 'enabled': False}
            selected['sandbox_mode'] = 'workspace-write'
            selected['sandbox_workspace_write'] = {'network_access': True}
            config.write_text(GEN.toml_document(selected))
        before = self.snapshot()
        pins = ('--previous-plan-digest', previous_digest,
            '--previous-package-digest', previous_plan['package_digest'],
            '--previous-marker-sha256', hashlib.sha256((previous_payload / 'codex/.deployment.json').read_bytes()).hexdigest(),
            '--previous-observed-config-sha256', hashlib.sha256(config.read_bytes()).hexdigest())
        repair_state = self.home / 'retained-repair'
        if disable_hooks:
            # Reproduce the incident order: repair the expected generation,
            # then the operator disables hooks before preparing the update.
            config.write_bytes(previous_config)
            repair_pins = (*pins[:-1], hashlib.sha256(previous_config).hexdigest())
        else:
            repair_pins = pins
        self.success(self.run_cli('repair-usage-directory', '--home', self.home,
            '--state-dir', repair_state, '--mode', 'rehearsal', *repair_pins))
        if disable_hooks:
            proof = json.loads((repair_state / 'proof.json').read_text())
            self.assertEqual(proof['observed_config_sha256'], previous_plan['expected']['config.toml']['sha256'])
            config.write_text(GEN.toml_document(selected))
        (self.runtime / 'usage-data/new-log').write_text('retained after rollback')
        self.state = self.home / 'installation/three'
        self.payload = self.state / 'payload'
        values = {key: value.replace(str(previous_payload), str(self.payload))
                  for key, value in json.loads(self.bindings.read_text()).items()}
        values.update(dict(zip(('value_0174', 'value_0175', 'value_0176', 'value_0177'), projects)))
        if additional_project and bind_additional_project:
            values['additional_trusted_projects'] = [extra]
        self.bindings.write_text(json.dumps(values))
        digest = self.success(self.run_cli('prepare-policy-update', '--home', self.home,
            '--state-dir', self.state, '--mode', 'rehearsal', '--bindings', self.bindings,
            '--bindings-sha256', hashlib.sha256(self.bindings.read_bytes()).hexdigest(),
            '--braid-bin', self.fixture.bin / 'braid', *pins,
            '--previous-expected-config-sha256', previous_plan['expected']['config.toml']['sha256'],
            '--usage-directory-repair', repair_state / 'proof.json'))['plan_digest']
        return digest, before, repair_state

    def test_initial_install_preserves_partial_hook_disable(self):
        config = self.runtime / 'config.toml'
        selected = tomllib.loads(config.read_text())
        identity = next(key for key in selected['hooks']['state']
                        if key.endswith('/hooks.json:pre_tool_use:0:0'))
        selected['hooks']['state'][identity]['enabled'] = False
        config.write_text(GEN.toml_document(selected))
        original = config.read_bytes()
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        states = tomllib.loads(config.read_text())['hooks']['state']
        self.assertFalse(states[identity]['enabled'])
        self.assertEqual(states[identity]['trusted_hash'],
                         selected['hooks']['state'][identity]['trusted_hash'])
        self.assertTrue(any(row.get('enabled') is not False for key, row in states.items()
                            if key != identity))
        self.success(self.operation('rollback', digest))
        self.assertEqual(config.read_bytes(), original)

    def test_initial_install_preserves_all_hook_disables(self):
        config = self.runtime / 'config.toml'
        selected = tomllib.loads(config.read_text())
        for value in selected['hooks']['state'].values():
            value['enabled'] = False
        config.write_text(GEN.toml_document(selected))
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        expected = tomllib.loads(config.read_text())
        drifted = dict(expected, model='synthetic-drift')
        config.write_text(GEN.toml_document(drifted))
        result = subprocess.run([sys.executable, '-B', str(self.runtime / 'scripts/repair-runtime-config-drift.py'),
            '--config-path', str(config), '--repair', '--json'], env=self.installed_env(),
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(tomllib.loads(config.read_text()), expected)
        states = tomllib.loads(config.read_text())['hooks']['state']
        self.assertTrue(states)
        self.assertTrue(all(row['enabled'] is False for row in states.values()))

    def test_policy_update_preserves_current_desktop_preferences(self):
        digest, _before, _repair = self.prepare_usage_policy_update(
            disable_hooks=True, desktop_preferences=True)
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        actual = tomllib.loads((self.runtime / 'config.toml').read_text())
        self.assertEqual(actual['desktop']['git-commit-instructions'],
                         'Use a specific subject.\nExplain the change.')
        self.assertEqual(actual['model'], 'gpt-6-sol')
        self.assertEqual(actual['model_reasoning_effort'], 'low')
        self.assertEqual(actual['desktop']['daybreak-enabled'], {
            'accountId': 'synthetic-account', 'userId': 'synthetic-user', 'enabled': False})
        self.assertNotIn('sandbox_mode', actual)
        self.assertNotIn('sandbox_workspace_write', actual)
        self.assertEqual(actual['default_permissions'], 'workspace-net')
        self.assertTrue(all(row['enabled'] is False for row in actual['hooks']['state'].values()))

    def test_reviewed_hook_enablement_requires_pin_and_preserves_receipts(self):
        digest, _before, _repair = self.prepare_usage_policy_update(disable_hooks=True)
        self.success(self.operation('apply', digest))
        config = self.runtime / 'config.toml'
        original = config.read_bytes()
        receipt = (self.state / 'result.json').read_bytes()
        selected = tomllib.loads(original.decode())
        identity = next(key for key in selected['hooks']['state'] if key.startswith(str(self.runtime / 'hooks.json') + ':'))
        selected['hooks']['state'][identity]['enabled'] = True
        config.write_text(GEN.toml_document(selected))
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        proposal = self.success(self.operation('prepare-desktop-review', digest))
        pin = proposal['review_sha256']
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        self.success(self.run_cli('check', '--state-dir', self.state,
            '--plan-digest', digest, '--desktop-review-sha256', pin))
        self.assertEqual((self.state / 'result.json').read_bytes(), receipt)
        accepted = config.read_bytes()
        selected['hooks']['state'][identity]['trusted_hash'] += '-changed'
        config.write_text(GEN.toml_document(selected))
        self.assertNotEqual(self.run_cli('check', '--state-dir', self.state,
            '--plan-digest', digest, '--desktop-review-sha256', pin).returncode, 0)
        config.write_bytes(original)
        self.success(self.operation('check', digest))
        config.write_bytes(accepted)
        first_state, first_payload, first_pin = self.state, self.payload, pin
        updates = []
        for generation in ('four', 'five'):
            old_payload = self.payload
            self.state = self.home / 'installation' / generation
            self.payload = self.state / 'payload'
            values = json.loads(self.bindings.read_text())
            self.bindings.write_text(json.dumps({key: value.replace(str(old_payload), str(self.payload))
                                                for key, value in values.items()}))
            next_digest = self.success(self.run_cli('prepare', '--home', self.home,
                '--state-dir', self.state, '--bindings', self.bindings,
                '--braid-bin', self.fixture.bin / 'braid', '--mode', 'rehearsal',
                '--previous-desktop-review-sha256', pin))['plan_digest']
            updates.append((self.state, self.payload, next_digest))
            self.success(self.operation('apply', next_digest))
            self.success(self.operation('check', next_digest))
            actual = tomllib.loads(config.read_text())['hooks']['state']
            self.assertTrue(actual[identity]['enabled'])
            self.assertTrue(all(row['enabled'] is False for key, row in actual.items() if key != identity))
            proposal = self.success(self.operation('prepare-desktop-review', next_digest))
            self.assertEqual(proposal['changed_paths'], [])
            pin = proposal['review_sha256']
        for state, payload, update_digest in reversed(updates):
            self.state, self.payload = state, payload
            self.success(self.operation('rollback', update_digest))
        self.state, self.payload = first_state, first_payload
        self.success(self.run_cli('rollback', '--state-dir', self.state,
            '--plan-digest', digest, '--desktop-review-sha256', first_pin))
        restored = tomllib.loads(config.read_text())['hooks']['state']
        self.assertTrue(restored[identity]['enabled'])
        self.assertEqual(restored[identity]['trusted_hash'], tomllib.loads(original.decode())['hooks']['state'][identity]['trusted_hash'])
        self.assertEqual((self.state / 'result.json').read_bytes(), receipt)

    def test_selected_additional_project_survives_disabled_hook_migration(self):
        digest, before, _repair_state = self.prepare_usage_policy_update(
            disable_hooks=True, additional_project=True)
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        config = tomllib.loads((self.runtime / 'config.toml').read_text())
        self.assertEqual(config['projects'][str(self.home / 'Documents/Codex/another-workspace')], {'trust_level': 'trusted'})
        self.assertTrue(all(value.get('enabled') is False for value in config['hooks']['state'].values()))
        self.success(self.packaged_operation('rollback', digest))
        self.assertEqual(self.snapshot(), before)

    def test_unselected_additional_project_still_blocks_migration(self):
        with self.assertRaisesRegex(AssertionError, 'Desktop delta contains an unreviewable policy change'):
            self.prepare_usage_policy_update(disable_hooks=True, additional_project=True,
                                            bind_additional_project=False)

    def test_usage_policy_update_cancel_preserves_nonempty_logs(self):
        digest, before, repair_state = self.prepare_usage_policy_update()
        self.success(self.packaged_operation('rollback', digest))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((repair_state / 'usage-data/new-log').read_text(), 'retained after rollback')
        self.success(self.packaged_operation('rollback', digest))

    def test_usage_policy_update_preserves_disabled_hooks_through_apply_and_rollback(self):
        import hashlib
        digest, before, repair_state = self.prepare_usage_policy_update(disable_hooks=True)
        config = self.runtime / 'config.toml'
        original = tomllib.loads(config.read_text())
        states = original['hooks']['state']
        self.assertTrue(states)
        self.assertTrue(all(entry['enabled'] is False for entry in states.values()))
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        applied = tomllib.loads(config.read_text())
        self.assertTrue(applied['hooks']['state'])
        self.assertTrue(all(entry['enabled'] is False for entry in applied['hooks']['state'].values()))
        expected = json.loads((self.state / 'plan.json').read_text())['expected']['config.toml']
        self.assertEqual(hashlib.sha256(config.read_bytes()).hexdigest(), expected['sha256'])
        self.success(self.packaged_operation('rollback', digest))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((repair_state / 'usage-data/new-log').read_text(), 'retained after rollback')

    def test_usage_policy_update_applied_rollback_is_replayable(self):
        digest, before, repair_state = self.prepare_usage_policy_update()
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        applied = json.loads((self.state / 'result.json').read_text())
        self.success(self.packaged_operation('rollback', digest))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((repair_state / 'usage-data/new-log').read_text(), 'retained after rollback')
        # Crash after the inverse exchange but before the final journal write:
        # the prior restoring snapshot still describes the applied generation.
        (self.state / 'result.json').write_text(json.dumps(dict(applied, status='restoring')))
        self.success(self.packaged_operation('rollback', digest))
        self.success(self.packaged_operation('rollback', digest))

    def test_reviewed_usage_rollback_recovery_retains_original_receipt(self):
        digest, _before, repair_state = self.prepare_usage_policy_update(disable_hooks=True)
        self.success(self.operation('apply', digest))
        original = (self.state / 'result.json').read_bytes()
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        command = [sys.executable, '-B', str(self.payload / 'scripts/install-codex.py'),
                   'rollback', '--state-dir', str(self.state), '--plan-digest', digest,
                   '--desktop-review-sha256', pin]
        def rollback():
            return subprocess.run(command, cwd=self.payload, env=self.installed_env(),
                                  capture_output=True, text=True, timeout=180, check=False)
        self.success(rollback())
        recovery = self.state / ('desktop-' + pin + '-result.json')
        data = json.loads(recovery.read_text())
        data['status'] = 'restoring'
        recovery.write_text(json.dumps(data))
        self.success(rollback())
        self.assertEqual((self.state / 'result.json').read_bytes(), original)
        self.assertEqual((repair_state / 'usage-data/new-log').read_text(), 'retained after rollback')

    def prepare_reviewed_update(self, pin):
        return self.run_cli('prepare', '--home', self.home, '--state-dir', self.state,
            '--bindings', self.bindings, '--braid-bin', self.fixture.bin / 'braid',
            '--mode', 'rehearsal', '--previous-desktop-review-sha256', pin)

    def test_reviewed_update_rejects_wrong_pin_and_newer_runtime(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        self.second_installation()
        before = self.snapshot()
        self.assertNotEqual(self.prepare_reviewed_update('0' * 64).returncode, 0)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.snapshot(), before)
        path = self.runtime / 'config.toml'
        data = tomllib.loads(path.read_text())
        data['notify'].append('unapproved-new-argument')
        path.write_text(GEN.toml_document(data))
        changed = self.snapshot()
        self.assertNotEqual(self.prepare_reviewed_update(pin).returncode, 0)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.snapshot(), changed)

    def test_reviewed_update_rejects_apply_race_reference_and_source_conflict(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        self.second_installation()
        update_digest = self.success(self.prepare_reviewed_update(pin))['plan_digest']
        installer = self.import_installer(self.payload)
        canonical = tomllib.loads((self.payload / 'codex/config.toml').read_text())
        canonical['desktop']['selected-avatar-id'] = 'conflicting-new-policy'
        with mock.patch.object(sys, 'path', [str(self.payload / 'codex/scripts'), *sys.path]), \
                mock.patch.dict(os.environ, self.installed_env(), clear=True), \
                mock.patch.dict(sys.modules):
            sys.modules.pop('migration_scope', None)
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                installer.update_desktop_text(GEN.toml_document(canonical),
                    (self.runtime / 'config.toml').read_text())
        config = self.runtime / 'config.toml'
        raw = config.read_bytes()
        data = tomllib.loads(raw.decode())
        data['notify'].append('newer-runtime')
        config.write_text(GEN.toml_document(data))
        changed = self.snapshot()
        self.assertNotEqual(self.operation('apply', update_digest).returncode, 0)
        self.assertEqual(self.snapshot(), changed)
        config.write_bytes(raw)
        old_review = self.home / 'installation/one/desktop-review.json'
        review_raw = old_review.read_bytes()
        old_review.write_bytes(review_raw + b'\n')
        before = self.snapshot()
        self.assertNotEqual(self.operation('apply', update_digest).returncode, 0)
        self.assertEqual(self.snapshot(), before)
        old_review.write_bytes(review_raw)
        reference = self.runtime / '.dots-package.json'
        reference_raw = reference.read_bytes()
        reference.unlink()
        changed = self.snapshot()
        self.assertNotEqual(self.operation('apply', update_digest).returncode, 0)
        self.assertEqual(self.snapshot(), changed)
        reference.write_bytes(reference_raw)
        content = json.loads(reference.read_text())
        content['state_dir'] = str(self.home / 'installation/third')
        reference.write_text(json.dumps(content))
        changed = self.snapshot()
        self.assertNotEqual(self.operation('apply', update_digest).returncode, 0)
        self.assertEqual(self.snapshot(), changed)

    def test_previous_review_inventory_uses_the_validated_metadata_snapshot(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        self.desktop_restart()
        pin = self.success(self.operation('prepare-desktop-review', digest))['review_sha256']
        descriptor = {'state_dir': str(self.state), 'home': str(self.home),
                      'plan_digest': digest, 'review_sha256': pin}
        installer = self.import_installer(ROOT)
        loader = installer.load_previous_review

        def swap_after_validation(*args):
            validated = loader(*args)
            name = 'docs.config.toml'
            target = self.runtime / name
            raw = target.read_bytes()
            target.unlink()
            target.write_bytes(raw + b'\n# unreviewed managed edit\n')
            plan = json.loads((self.state / 'plan.json').read_text())
            result = json.loads((self.state / 'result.json').read_text())
            plan['expected'].pop(name)
            result['after'].pop(name)
            (self.state / 'plan.json').write_text(json.dumps(plan))
            (self.state / 'result.json').write_text(json.dumps(result))
            return validated

        with mock.patch.object(installer, 'load_previous_review', side_effect=swap_after_validation):
            with self.assertRaisesRegex(ValueError, 'Runtime drift'):
                installer.verify_previous(self.home, descriptor)

    def test_update_copies_new_version_then_restores_previous_runtime(self):
        first_digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', first_digest))
        first_state = self.state
        first_snapshot = self.snapshot()
        self.second_installation()
        digest = self.success(self.prepare())['plan_digest']
        self.assertEqual(self.snapshot(), first_snapshot)
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        self.assertNotEqual((self.runtime / 'config.toml').read_bytes(), first_snapshot['config.toml'][1])
        self.assertEqual((self.runtime / 'scripts').is_symlink(), False)
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), first_snapshot)
        self.success(self.run_cli('check', '--state-dir', first_state, '--plan-digest', first_digest))
        self.success(self.run_cli('rollback', '--state-dir', first_state, '--plan-digest', first_digest))
        self.assertEqual(self.snapshot(), self.before)

    def test_update_stops_on_directory_drift_and_keeps_private_state(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        changed = self.runtime / 'instructions/compact-prompt.md'
        changed.chmod(0o600)
        original = changed.read_bytes()
        changed.write_bytes(original + b'\nLocal change requiring review.\n')
        before = self.snapshot()
        self.second_installation()
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Runtime drift', result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state.exists())
        self.fixture.assert_preserved(self)

    def test_runtime_and_recovery_do_not_need_source_checkout(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        # Use only installed copies and the pinned recovery entrypoint. The
        # development fixture is removed from its original location, not edited.
        moved = self.home / 'source-checkout-unavailable'
        self.fixture.repo.rename(moved)
        event = self.fixture.payload | {'cwd': str(self.home / 'tmp')}
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(event), env=self.env, cwd=self.home / 'tmp',
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        command = [sys.executable, '-B', str(self.payload / 'scripts/install-codex.py'),
                   'rollback', '--state-dir', str(self.state), '--plan-digest', digest]
        result = subprocess.run(command, env=self.env, cwd=self.home / 'tmp',
            text=True, capture_output=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        moved.rename(self.fixture.repo)
        self.assertEqual(self.snapshot(), self.before)

    def test_copied_script_and_profile_hardlinks_are_rejected(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        target = self.runtime / 'docs.config.toml'
        target.unlink()
        os.link(self.payload / 'codex/docs.config.toml', target)
        self.assertNotEqual(self.operation('check', digest).returncode, 0)
        self.fixture.assert_preserved(self)

    def test_admission_diagnostics_keep_denial_without_private_resource_values(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        script = self.runtime / 'hooks/pre-tool-use-dispatch.sh'
        marker = 'private-diagnostic-sentinel'
        outside = str(self.home.parent / marker)
        cases = (
            ({'cwd': outside}, {}, 'stage=event; field=cwd'),
            ({}, {'CODEX_HOOK_USAGE_ROOT': outside},
             'stage=environment; field=CODEX_HOOK_USAGE_ROOT'),
            ({}, {'CODEX_PRIVATE_DIAGNOSTIC_SENTINEL': outside},
             'stage=environment; field=other_CODEX_path'),
            ({}, {'DOTS_PRIVATE_DIAGNOSTIC_SENTINEL': outside},
             'stage=environment; field=other_DOTS_path'),
            ({}, {'XDG_CACHE_HOME': outside},
             'stage=environment; field=XDG_CACHE_HOME'),
        )
        for event, environment, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                result = subprocess.run(['bash', str(script)],
                    input=json.dumps(self.fixture.payload | event),
                    env=self.installed_env() | environment, cwd=self.payload,
                    text=True, capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn(diagnostic, result.stderr)
                self.assertIn('error=ValueError', result.stderr)
                self.assertNotIn(marker, result.stderr)
                self.assertNotIn('CODEX_PRIVATE_DIAGNOSTIC_SENTINEL', result.stderr)
                self.assertNotIn('DOTS_PRIVATE_DIAGNOSTIC_SENTINEL', result.stderr)
                self.assertEqual(result.stderr,
                                 f'hook fixture admission failed: {diagnostic}; error=ValueError\n')
        result = subprocess.run(['bash', str(script)],
            input=json.dumps(self.fixture.payload), env=self.installed_env(),
            cwd=self.payload, text=True, capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertEqual(result.stderr, '')
        result = subprocess.run(['bash', str(script)], input='not-json',
            env=self.installed_env(), cwd=self.payload, text=True,
            capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr,
                         'hook fixture admission failed: Expecting value: line 1 column 1 (char 0)\n')
        self.fixture.assert_preserved(self)

    def test_managed_worktree_of_allowed_project_is_admitted(self):
        project = self.home / 'dev/agent-skills'
        worktree = self.runtime / 'worktrees/saved-release-circleci/skills-sdk'
        worktree.parent.mkdir(parents=True)
        for args in (
            ['init', '-q', str(project)],
            ['-C', str(project), '-c', 'user.name=Fixture',
             '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
             'commit', '--allow-empty', '-qm', 'synthetic baseline'],
            ['-C', str(project), 'worktree', 'add', '--detach', '-q', str(worktree), 'HEAD'],
        ):
            subprocess.run(['git', *args], env=self.env, check=True,
                           text=True, capture_output=True, timeout=20)
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(self.fixture.payload | {'cwd': str(worktree)}),
            env=self.installed_env(), cwd=self.payload,
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        denied_command = self.fixture.payload | {
            'cwd': str(worktree),
            'tool_input': {'command': 'git commit --no-verify -m probe'},
        }
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(denied_command), env=self.installed_env(), cwd=self.payload,
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(self.fixture.payload | {
                'cwd': str(worktree), 'transcript_path': str(self.runtime / 'sessions/synthetic.jsonl')}),
            env=self.installed_env(), cwd=self.payload,
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        nested = worktree / 'nested'
        nested.mkdir()
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(self.fixture.payload | {'cwd': str(nested)}),
            env=self.installed_env(), cwd=self.payload,
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        event = self.fixture.payload | {'tool_input': self.fixture.payload['tool_input'] | {'cwd': str(nested)}}
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(event), env=self.installed_env(), cwd=self.payload,
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        private = self.runtime / 'sessions'
        (worktree / 'escape').symlink_to(private, target_is_directory=True)
        forged = self.runtime / 'worktrees/forged/skills-sdk'
        forged.mkdir(parents=True)
        (forged / '.git').write_bytes((worktree / '.git').read_bytes())
        untrusted_project = self.home / 'untrusted'
        untrusted_project.mkdir()
        untrusted_tree = self.runtime / 'worktrees/untrusted/project'
        untrusted_tree.parent.mkdir(parents=True)
        for args in (
            ['init', '-q', str(untrusted_project)],
            ['-C', str(untrusted_project), '-c', 'user.name=Fixture',
             '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
             'commit', '--allow-empty', '-qm', 'synthetic baseline'],
            ['-C', str(untrusted_project), 'worktree', 'add', '--detach', '-q', str(untrusted_tree), 'HEAD'],
        ):
            subprocess.run(['git', *args], env=self.env, check=True,
                           text=True, capture_output=True, timeout=20)
        for denied in (private, worktree / 'escape', worktree / '../skills-sdk', forged, untrusted_tree):
            with self.subTest(denied=denied):
                result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
                    input=json.dumps(self.fixture.payload | {'cwd': str(denied)}),
                    env=self.installed_env(), cwd=self.payload,
                    text=True, capture_output=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('stage=event; field=cwd; error=ValueError', result.stderr)
        event = self.fixture.payload | {'tool_input': self.fixture.payload['tool_input'] | {'workdir': str(forged)}}
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(event), env=self.installed_env(), cwd=self.payload,
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('stage=event; field=tool_input.workdir; error=ValueError', result.stderr)
        gitdir = Path((worktree / '.git').read_text().strip().removeprefix('gitdir: '))
        common = gitdir / 'commondir'
        original_common = common.read_bytes()
        for invalid in (b'wrong\n', b'\xff\n', b'x' * 4097):
            common.write_bytes(invalid)
            result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
                input=json.dumps(self.fixture.payload | {'cwd': str(worktree)}),
                env=self.installed_env(), cwd=self.payload,
                text=True, capture_output=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        common.write_bytes(original_common)
        original_mode = gitdir.stat().st_mode & 0o777
        gitdir.chmod(original_mode | 0o020)
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(self.fixture.payload | {'cwd': str(worktree)}),
            env=self.installed_env(), cwd=self.payload,
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        gitdir.chmod(original_mode)
        extra_link = self.home / 'tmp/worktree-marker-hardlink'
        os.link(worktree / '.git', extra_link)
        result = subprocess.run(['bash', str(self.runtime / 'hooks/pre-tool-use-dispatch.sh')],
            input=json.dumps(self.fixture.payload | {'cwd': str(worktree)}),
            env=self.installed_env(), cwd=self.payload,
            text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        extra_link.unlink()
        spec = importlib.util.spec_from_file_location('worktree_scope', self.payload / 'codex/scripts/deployment_scope.py')
        scope = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scope)
        with mock.patch.dict(os.environ, self.installed_env(), clear=True):
            for output in (False, True):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    scope.require_path(worktree, output=output)
            original_read = scope.read_regular
            for mutation in ('nested-alias', 'nested-identity', 'metadata-mode',
                             'metadata-data', 'retained-alias'):
                with self.subTest(admission_race=mutation):
                    parked = worktree / 'nested-before-race'
                    parked_private = self.home / 'tmp/sessions-before-race'
                    swapped = False
                    def racing_read(path, *args, **kwargs):
                        nonlocal swapped
                        raw = original_read(path, *args, **kwargs)
                        if Path(path) == common and not swapped:
                            swapped = True
                            if mutation.startswith('nested-'):
                                nested.rename(parked)
                                if mutation == 'nested-alias':
                                    nested.symlink_to(private, target_is_directory=True)
                                else:
                                    nested.mkdir()
                            elif mutation == 'metadata-mode':
                                gitdir.chmod(original_mode | 0o020)
                            elif mutation == 'metadata-data':
                                common.write_bytes(b'../wrong\n')
                            else:
                                private.rename(parked_private)
                                private.symlink_to(nested, target_is_directory=True)
                        return raw
                    try:
                        with mock.patch.object(scope, 'read_regular', side_effect=racing_read), \
                                self.assertRaises(ValueError):
                            scope.require_event_directory(nested, data=scope.context())
                        self.assertTrue(swapped)
                    finally:
                        if swapped and mutation.startswith('nested-'):
                            if nested.is_symlink():
                                nested.unlink()
                            else:
                                nested.rmdir()
                            parked.rename(nested)
                        elif swapped and mutation == 'metadata-mode':
                            gitdir.chmod(original_mode)
                        elif swapped and mutation == 'metadata-data':
                            common.write_bytes(original_common)
                        elif swapped:
                            private.unlink()
                            parked_private.rename(private)
            original_identity = scope._event_directory_identity
            changed_baseline = False
            def unsafe_baseline(directory):
                nonlocal changed_baseline
                if directory == gitdir and not changed_baseline:
                    changed_baseline = True
                    gitdir.chmod(original_mode | 0o020)
                return original_identity(directory)
            try:
                with mock.patch.object(scope, '_event_directory_identity', side_effect=unsafe_baseline), \
                        self.assertRaises(ValueError):
                    scope.require_event_directory(nested, data=scope.context())
                self.assertTrue(changed_baseline)
            finally:
                gitdir.chmod(original_mode)
            self.assertEqual(scope.require_event_directory(nested, data=scope.context()), nested)
        self.fixture.assert_preserved(self)

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

    def test_bound_session_storage_keeps_existing_permissions_and_local_state(self):
        values = json.loads(self.bindings.read_text())
        session_root = self.home / 'private-storage/sessions'
        values['value_0006'] = str(session_root)
        self.bindings.write_text(json.dumps(values))
        prepared = self.success(self.prepare())
        self.assertEqual(self.snapshot(), self.before)
        marker = json.loads((self.payload / 'codex/.deployment.json').read_text())
        self.assertEqual(marker['session_evidence_root'], str(session_root))
        canonical = tomllib.loads((self.payload / 'codex/config.toml').read_text())
        roots = canonical['permissions'][canonical['default_permissions']]['workspace_roots']
        self.assertIn(str(session_root), roots)
        self.assertNotIn(str(self.home / '.local/share/codex-storage/sessions'), roots)
        digest = prepared['plan_digest']
        self.success(self.operation('apply', digest))
        self.success(self.operation('check', digest))
        self.assertFalse(session_root.exists(), 'Installation must not create or copy sessions')
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before)

    def test_bound_session_storage_cannot_escape_rehearsal_home(self):
        values = json.loads(self.bindings.read_text())
        values['value_0006'] = str(self.home.parent / 'outside/sessions')
        self.bindings.write_text(json.dumps(values))
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), self.before)
        self.assertFalse((self.home.parent / 'outside/sessions').exists())

    def test_packaged_helper_cannot_overwrite_bound_sessions_or_aliases(self):
        values = json.loads(self.bindings.read_text())
        session_root = self.home / 'dev/private-history/sessions'
        values['value_0006'] = str(session_root)
        self.bindings.write_text(json.dumps(values))
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        session_root.mkdir(parents=True)
        sentinel = session_root / 'synthetic-session.json'
        sentinel.write_bytes(b'local session must survive')
        alias = self.home / 'dev/session-evidence-alias'
        alias.symlink_to(session_root, target_is_directory=True)
        for target in (sentinel, alias / sentinel.name):
            result = subprocess.run([sys.executable, '-B',
                str(self.payload / 'codex/scripts/render-agent-artifact-summary.py'),
                '--root', str(self.payload / 'codex'), '--out', str(target)],
                env=self.installed_env(), cwd=self.payload, capture_output=True,
                text=True, timeout=15, check=False)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(sentinel.read_bytes(), b'local session must survive')
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before)

    def test_packaged_validator_discovers_its_source_without_environment_override(self):
        digest = self.success(self.prepare())['plan_digest']
        self.success(self.operation('apply', digest))
        environment = self.installed_env()
        environment.pop('CODEX_CONFIG_SOURCE_ROOT', None)
        result = subprocess.run([sys.executable, '-B',
            str(self.payload / 'codex/scripts/validate-codex-config.py')],
            env=environment, cwd=self.payload, capture_output=True, text=True,
            timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before)

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

    def test_partial_cutover_rolls_back_without_resuming_activation(self):
        digest = self.success(self.prepare())['plan_digest']
        # Interrupt at the real projector boundary after atomic config publication.
        shadow = self.fixture.bin / 'bash'
        shadow.write_text('#!/bin/sh\nexit 75\n')
        shadow.chmod(0o700)
        failed = self.operation('apply', digest)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(json.loads((self.state / 'result.json').read_text())['status'], 'failed')
        self.assertNotEqual(self.snapshot()['config.toml'], self.before['config.toml'])
        self.success(self.operation('rollback', digest))
        shadow.unlink()
        self.assertEqual(self.snapshot(), self.before)
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
        local_additions = {name: value for name, value in self.snapshot().items()
                           if name not in self.before and name != '.dots-package.json'}
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
        local_additions = {name: value for name, value in self.snapshot().items()
                           if name not in self.before and name != '.dots-package.json'}
        self.success(self.operation('rollback', digest))
        self.assertEqual(self.snapshot(), self.before | local_additions)
