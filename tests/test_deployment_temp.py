"""Check native temp admission without opening or writing any real host store."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('deployment_temp_scope', ROOT / 'codex/scripts/deployment_scope.py')
SCOPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCOPE)


class DeploymentTempTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.temp = self.root / 'system/T'
        self.temp.mkdir(mode=0o700, parents=True)
        self.policy = {'default_permissions': 'work',
                       'permissions': {'work': {'extends': ':workspace'}}}
        self.data = {'mode': 'machine', 'home': str(self.home),
                     'state_dir': str(self.home / 'installation'),
                     'package_digest': 'synthetic-package',
                     'session_evidence_root': str(self.home / 'sessions')}
        for patcher in (mock.patch.object(SCOPE.sys, 'platform', 'darwin'),
                        mock.patch.object(SCOPE, '_MACOS_TEMP_PARENT', self.root / 'system'),
                        mock.patch.object(SCOPE, '_macos_temp_path', return_value=self.temp),
                        mock.patch.object(SCOPE, '_read_policy', return_value=self.policy)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_braid_read_default_does_not_override_an_explicit_limit(self):
        braid = self.root / 'hooks' / ('braid-' + 'a' * 64) / 'braid'
        braid.parent.mkdir(parents=True)
        ordinary = braid.with_name('ordinary')
        size = 16 * 1024 * 1024 + 1
        for path in (braid, ordinary):
            with path.open('wb') as stream:
                stream.truncate(size)
        self.assertEqual(len(SCOPE.read_regular(braid)), size)
        with self.assertRaises(ValueError):
            SCOPE.read_regular(ordinary)
        with self.assertRaises(ValueError):
            SCOPE.read_regular(braid, 2 * 1024 * 1024)
        with braid.open('r+b') as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            SCOPE.read_regular(braid)

    def test_owned_os_temp_matches_workspace_machine_only(self):
        self.assertEqual(SCOPE.native_temp_roots(self.data, self.policy), [self.temp])
        path = self.temp / 'report.json'
        self.assertEqual(SCOPE.require_path(path, output=True, data=self.data), path)
        self.assertEqual(SCOPE.native_temp_roots(self.data | {'mode': 'rehearsal'}, self.policy), [])
        readonly = {'default_permissions': 'read', 'permissions': {'read': {'extends': ':read-only'}}}
        self.assertEqual(SCOPE.native_temp_roots(self.data, readonly), [])
        self.temp.chmod(0o777)
        with self.assertRaises(ValueError):
            SCOPE.native_temp_roots(self.data, self.policy)

    def test_environment_cannot_select_an_arbitrary_temp_root(self):
        outside = self.root / 'caller-selected'
        outside.mkdir()
        with (mock.patch.dict(os.environ, {'HOME': str(self.home), 'TMPDIR': str(outside)}, clear=True),
              self.assertRaises(ValueError)):
            SCOPE.require_environment(self.data)
        self.assertEqual(SCOPE.native_temp_roots(self.data, self.policy), [self.temp])

    def test_native_app_metadata_does_not_grant_resource_access_or_execute_inputs(self):
        outside = self.root / 'native-app'
        outside.mkdir()
        transport = outside / 'codex'
        transport.write_bytes(b'private app transport sentinel')
        executable = outside / 'tectonic'
        marker = outside / 'executed'
        executable.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
        executable.chmod(0o700)
        environment = {'HOME': str(self.home), 'TMPDIR': str(self.temp),
                       'CODEX_APP_TOOLS_PIPE_PATH': str(transport),
                       'CODEX_TECTONIC_PATH': str(executable),
                       'CODEX_APP_RUNTIME_CLI_PATH': str(executable),
                       'CODEX_MCP_NODE_PATH': str(executable)}
        with (mock.patch.object(SCOPE, 'context', return_value=self.data),
              mock.patch.dict(os.environ, environment, clear=True)):
            self.assertEqual(SCOPE.admit_event({}), self.home)
            for path in (transport, executable):
                for output in (False, True):
                    with self.subTest(path=path.name, output=output), self.assertRaises(ValueError):
                        SCOPE.require_path(path, data=self.data, output=output)
        self.assertEqual(transport.read_bytes(), b'private app transport sentinel')
        self.assertFalse(marker.exists())

    def test_native_app_metadata_remains_scoped_in_rehearsals(self):
        temporary = self.home / 'tmp'
        temporary.mkdir()
        outside = self.root / 'native-outside'
        outside.mkdir()
        for name in ('CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_TECTONIC_PATH',
                     'CODEX_APP_RUNTIME_CLI_PATH', 'CODEX_MCP_NODE_PATH'):
            environment = {'HOME': str(self.home), 'TMPDIR': str(temporary), name: str(outside)}
            with (self.subTest(field=name),
                  mock.patch.object(SCOPE, 'context', return_value=self.data | {'mode': 'rehearsal'}),
                  mock.patch.dict(os.environ, environment, clear=True),
                  self.assertRaisesRegex(ValueError, 'Rehearsal resource leaves')):
                SCOPE.admit_event({})

    def test_machine_rejection_identifies_role_even_when_basename_is_codex(self):
        outside = self.root / 'private-sentinel/codex'
        environment = {'HOME': str(self.home), 'TMPDIR': str(self.temp),
                       'CODEX_HOOK_USAGE_ROOT': str(outside)}
        with (mock.patch.object(SCOPE, 'context', return_value=self.data),
              mock.patch.dict(os.environ, environment, clear=True),
              self.assertRaisesRegex(ValueError, 'Resource leaves the deployment policy scope: codex') as caught):
            SCOPE.admit_event({})
        self.assertEqual(caught.exception._dots_admission_diagnostic,
                         'stage=environment; field=CODEX_HOOK_USAGE_ROOT; error=ValueError')
        self.assertFalse(outside.exists())

    def test_native_app_metadata_exception_does_not_cover_other_prefixed_resources(self):
        outside = self.root / 'unadmitted'
        outside.mkdir()
        for name in ('CODEX_HOOK_USAGE_ROOT', 'DOTS_REPORT_PATH', 'CODEX_UNKNOWN_PATH',
                     'CODEX_APP_RUNTIME_CLI_PATH_EXTRA', 'CODEX_MCP_NODE_PATH_EXTRA'):
            environment = {'HOME': str(self.home), 'TMPDIR': str(self.temp), name: str(outside)}
            with (self.subTest(field=name),
                  mock.patch.object(SCOPE, 'context', return_value=self.data),
                  mock.patch.dict(os.environ, environment, clear=True),
                  self.assertRaisesRegex(ValueError, 'Resource leaves')):
                SCOPE.admit_event({})

    def test_temp_aliases_cannot_escape_or_target_retained_stores(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.temp / 'escape').symlink_to(outside, target_is_directory=True)
        sessions = self.home / 'sessions'
        sessions.mkdir()
        sentinel = sessions / 'history.json'
        sentinel.write_bytes(b'local session')
        (self.temp / 'session-alias').symlink_to(sessions, target_is_directory=True)
        for target in (self.temp / 'escape/report.json', self.temp / 'session-alias/history.json'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                SCOPE.require_path(target, output=True, data=self.data)
        self.assertEqual(sentinel.read_bytes(), b'local session')

    def test_bulk_admission_checks_every_leaf_without_repeated_root_resolution(self):
        usage = self.home / '.codex/usage-data'
        usage.mkdir(parents=True)
        for number in range(100):
            (usage / f'log-{number}.json').write_text('{}')
        protected = self.home / '.codex/pets'
        original = Path.resolve
        calls = []

        def observe(path, *args, **kwargs):
            if path == protected:
                calls.append(path)
            return original(path, *args, **kwargs)

        with (mock.patch.object(SCOPE, 'context', return_value=self.data),
              mock.patch.object(SCOPE.Path, 'resolve', observe),
              mock.patch.dict(os.environ, {'HOME': str(self.home), 'TMPDIR': str(self.temp)}, clear=True)):
            self.assertEqual(SCOPE.admit_event({}), self.home)
        self.assertLessEqual(len(calls), 5)
        self.assertEqual(len(list(usage.iterdir())), 100)
        outside = self.root / 'outside-bulk'
        outside.mkdir()
        sentinel = outside / 'sentinel.json'
        sentinel.write_bytes(b'caller data')
        (usage / 'zz-escape').symlink_to(outside, target_is_directory=True)
        with (mock.patch.object(SCOPE, 'context', return_value=self.data),
              mock.patch.dict(os.environ, {'HOME': str(self.home), 'TMPDIR': str(self.temp)}, clear=True),
              self.assertRaises(ValueError)):
            SCOPE.admit_event({})
        self.assertEqual(sentinel.read_bytes(), b'caller data')

    def test_bulk_admission_refuses_a_protected_alias_changed_during_scan(self):
        usage = self.home / '.codex/usage-data'
        usage.mkdir(parents=True)
        for number in range(2):
            (usage / f'log-{number}.json').write_text('{}')
        old, new = self.home / 'old-pets', self.home / 'new-pets'
        old.mkdir()
        new.mkdir()
        pets = self.home / '.codex/pets'
        pets.symlink_to(old, target_is_directory=True)
        original = SCOPE.require_path
        changed = False

        def replace_after_leaf(path, **kwargs):
            nonlocal changed
            result = original(path, **kwargs)
            if kwargs.get('_root_resolver') is not None and not changed:
                pets.unlink()
                pets.symlink_to(new, target_is_directory=True)
                changed = True
            return result

        with (mock.patch.object(SCOPE, 'context', return_value=self.data),
              mock.patch.object(SCOPE, 'require_path', side_effect=replace_after_leaf),
              mock.patch.dict(os.environ, {'HOME': str(self.home), 'TMPDIR': str(self.temp)}, clear=True),
              self.assertRaisesRegex(ValueError, 'alias changed during admission')):
            SCOPE.admit_event({})


class DeploymentTempPrimitiveTests(unittest.TestCase):
    def test_diagnostic_preserves_original_failure_and_specific_label(self):
        failure = ValueError('private error sentinel')
        operation = mock.Mock(side_effect=failure)
        with self.assertRaises(ValueError) as caught:
            SCOPE._checked('environment', 'configuration', SCOPE._checked,
                           'environment', 'CODEX_HOME', operation, 'argument', output=True)
        self.assertIs(caught.exception, failure)
        self.assertEqual(str(failure), 'private error sentinel')
        self.assertEqual(failure._dots_admission_diagnostic,
                         'stage=environment; field=CODEX_HOME; error=ValueError')
        operation.assert_called_once_with('argument', output=True)

    def test_diagnostic_returns_success_without_changing_arguments(self):
        sentinel = object()
        operation = mock.Mock(return_value=sentinel)
        self.assertIs(SCOPE._checked('event', 'cwd', operation, sentinel, output=False), sentinel)
        operation.assert_called_once_with(sentinel, output=False)

    def test_diagnostic_rejection_cannot_replace_original_failure(self):
        class RefusesDiagnostic(ValueError):
            def __setattr__(self, name, value):
                raise AttributeError('no diagnostic attributes')

        failure = RefusesDiagnostic('original failure')
        with self.assertRaises(RefusesDiagnostic) as caught:
            SCOPE._checked('event', 'cwd', mock.Mock(side_effect=failure))
        self.assertIs(caught.exception, failure)

    def test_diagnostic_labels_never_include_unrecognised_input(self):
        failure = OSError('private error sentinel')
        with self.assertRaises(OSError) as caught:
            SCOPE._checked('event', 'private-field-sentinel', mock.Mock(side_effect=failure))
        self.assertIs(caught.exception, failure)
        self.assertFalse(hasattr(failure, '_dots_admission_diagnostic'))

    def test_component_containment_preserves_posix_path_semantics(self):
        paths = ('/', '/home', '/home/local', '/home/local/log', '/home/locality',
                 '/home/local/../outside', '//home/local', '/home/./local')
        for value in paths:
            for parent in paths:
                with self.subTest(value=value, parent=parent):
                    path, root = Path(value), Path(parent)
                    self.assertEqual(SCOPE._within(path, root), path.is_relative_to(root))

    def test_verified_package_identity_keys_immutable_policy_cache(self):
        SCOPE._read_policy.cache_clear()
        self.addCleanup(SCOPE._read_policy.cache_clear)
        with mock.patch.object(SCOPE, 'read_regular', return_value=b'default_permissions = "read"\n') as reader:
            self.assertEqual(SCOPE._read_policy('first'), {'default_permissions': 'read'})
            self.assertEqual(SCOPE._read_policy('first'), {'default_permissions': 'read'})
            self.assertEqual(reader.call_count, 1)
            SCOPE._read_policy('second')
            self.assertEqual(reader.call_count, 2)

    def test_os_lookup_failure_is_bounded(self):
        SCOPE._macos_temp_path.cache_clear()
        self.addCleanup(SCOPE._macos_temp_path.cache_clear)
        with (mock.patch.object(SCOPE.subprocess, 'run', side_effect=subprocess.TimeoutExpired('getconf', 5)),
              self.assertRaisesRegex(ValueError, 'OS user temporary directory unavailable')):
            SCOPE._macos_temp_path()
