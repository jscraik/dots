"""Runtime project trust admits event directories, never helper resources."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_governance_port as governance


class RuntimeProjectAdmissionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('runtime_admission',
            Path(__file__).resolve().parents[1] / 'codex/scripts/deployment_scope.py')
        self.scope = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.scope)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        (self.home / '.codex').mkdir()
        self.project = self.home / 'Documents/New project'
        self.project.mkdir(parents=True)
        self.config = self.home / '.codex/config.toml'
        self.config.write_text(f'[projects."{self.project}"]\ntrust_level = "trusted"\n')
        self.data = {'mode': 'machine', 'home': str(self.home),
                     'state_dir': str(self.home / 'installation'),
                     'session_evidence_root': str(self.home / 'sessions')}

    def admit(self, path):
        with mock.patch.object(self.scope, 'require_path', side_effect=ValueError('outside')):
            return self.scope.require_event_directory(path, data=self.data)

    def test_new_trusted_project_and_descendant(self):
        self.assertEqual(self.admit(self.project), self.project)
        child = self.project / 'src'
        child.mkdir()
        self.assertEqual(self.admit(child), child)

    def test_untrusted_missing_and_rehearsal_rejected(self):
        self.config.write_text(f'[projects."{self.project}"]\ntrust_level = "untrusted"\n')
        with self.assertRaises(ValueError):
            self.admit(self.project)
        self.data['mode'] = 'rehearsal'
        with self.assertRaises(ValueError):
            self.admit(self.project)

    def test_private_store_and_alias_rejected(self):
        private = self.home / '.codex/private'
        private.mkdir()
        self.config.write_text(f'[projects."{private}"]\ntrust_level = "trusted"\n')
        with self.assertRaises(ValueError):
            self.admit(private)
        alias = self.home / 'alias'
        alias.symlink_to(self.project)
        self.config.write_text(f'[projects."{alias}"]\ntrust_level = "trusted"\n')
        with self.assertRaises(ValueError):
            self.admit(alias)

    def test_runtime_trust_does_not_widen_resource_roots(self):
        self.data['package_digest'] = 'test'
        with mock.patch.object(self.scope, '_read_policy', return_value={}), mock.patch.object(
                self.scope, 'native_temp_roots', return_value=[]):
            with self.assertRaises(ValueError):
                self.scope.require_path(self.project, data=self.data)
            with self.assertRaises(ValueError):
                self.scope.require_path(self.project, data=self.data, output=True)

    def test_unsafe_directory_and_broad_trust_rejected(self):
        self.project.chmod(0o777)
        with self.assertRaises(ValueError):
            self.admit(self.project)
        self.project.chmod(0o700)
        self.config.write_text(f'[projects."{self.home}"]\ntrust_level = "trusted"\n')
        with self.assertRaises(ValueError):
            self.admit(self.project)

    def test_retained_sessions_rejected_even_when_canonical_admits_them(self):
        sessions = self.home / 'sessions'
        sessions.mkdir()
        self.config.write_text(f'[projects."{sessions}"]\ntrust_level = "trusted"\n')
        with mock.patch.object(self.scope, 'require_path', return_value=sessions):
            with self.assertRaises(ValueError):
                self.scope.require_event_directory(sessions, data=self.data)


class EvidenceAliasValidationTests(unittest.TestCase):
    def fixture(self):
        fixture = governance.GovernancePortTests('test_complete_snapshot_and_negative_policy')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_usage_alias_accepts_exact_physical_target(self):
        fixture = self.fixture()
        alias = fixture.home / 'dev/dots/codex/usage-data'
        target = fixture.home / 'private-storage/usage-data'
        target.mkdir(parents=True)
        alias.symlink_to(target)
        policy = fixture.root
        roots = policy['permissions'][policy['default_permissions']]['workspace_roots']
        roots.pop(str(alias))
        roots[str(target)] = True
        result = fixture.validate(governance.GEN.toml_document(policy))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_session_alias_still_requires_exact_declared_root(self):
        fixture = self.fixture()
        alias = fixture.home / '.local/share/codex-storage/sessions'
        alias.parent.mkdir(parents=True)
        target = fixture.home / 'private-storage/sessions'
        target.mkdir(parents=True)
        alias.symlink_to(target)
        policy = fixture.root
        roots = policy['permissions'][policy['default_permissions']]['workspace_roots']
        roots.pop(str(alias))
        roots[str(target)] = True
        result = fixture.validate(governance.GEN.toml_document(policy))
        self.assertEqual(result.returncode, 65, result.stdout + result.stderr)
        self.assertIn(f'must include {alias} for Codex session evidence access',
                      result.stdout + result.stderr)
