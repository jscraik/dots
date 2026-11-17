"""Full-bundle generation rejects malformed bindings without touching runtime."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('policy_generator', ROOT / 'scripts/generate-codex-policy.py')
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


class PolicyGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'bindings.json'
        self.bindings = GEN.read_json(ROOT / 'tests/fixtures/policy-bindings.json')

    def render(self):
        self.path.write_text(json.dumps(self.bindings))
        return GEN.render(self.path)

    def test_all_profiles_preserve_policy_and_isolation(self):
        result = self.render()
        self.assertEqual(set(result), set(GEN.NAMES))
        root = tomllib.loads(result['config'])
        self.assertEqual(root['approval_policy'], 'on-request')
        self.assertEqual(root['approvals_reviewer'], 'auto_review')
        self.assertTrue(root['features']['hooks'])
        for name in GEN.NAMES:
            if name.startswith('oss-'):
                profile = tomllib.loads(result[name])
                self.assertEqual(profile['default_permissions'], 'readonly-net')
                self.assertEqual(profile['approval_policy'], 'on-request')
                self.assertFalse(profile['features']['apps'])

    def test_missing_extra_and_non_string_bindings_rejected(self):
        original = dict(self.bindings)
        self.bindings.pop(next(iter(self.bindings)))
        with self.assertRaises(KeyError):
            self.render()
        self.bindings = dict(original, unexpected='extra')
        with self.assertRaises(ValueError):
            self.render()
        self.bindings = original
        self.bindings[next(iter(original))] = {'approval_policy': 'never'}
        with self.assertRaises(ValueError):
            self.render()

    def test_drawio_registration_keeps_its_local_source_as_data(self):
        root = tomllib.loads(self.render()['config'])
        self.assertEqual(root['plugins']['drawio@drawio'], {'enabled': True})
        self.assertEqual(root['marketplaces']['drawio']['source_type'], 'local')
        self.assertTrue(root['marketplaces']['drawio']['source'].startswith('/synthetic/'))
        self.assertRegex(root['marketplaces']['drawio']['last_revision'], r'^sha256:[0-9a-f]{64}$')
        self.assertEqual(root['approval_policy'], 'on-request')
        self.assertEqual(root['approvals_reviewer'], 'auto_review')

    def test_quotes_cannot_inject_policy(self):
        self.bindings = {key: value + '\"\n[attack]\nallow=true' for key, value in self.bindings.items()}
        result = self.render()
        self.assertNotIn('attack', tomllib.loads(result['config']))

    def test_duplicate_input_keys_rejected(self):
        self.path.write_text('{"a":"one","a":"two"}')
        with self.assertRaises(ValueError):
            GEN.render(self.path)

    def test_table_key_collisions_rejected(self):
        with self.assertRaises(ValueError):
            GEN.substitute({'@local:a': True, '@local:b': False}, {'a': 'same', 'b': 'same'}, set())

    def test_cli_no_values_or_runtime_writes(self):
        self.render()
        before = self.path.read_bytes()
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/generate-codex-policy.py'),
                                 '--bindings', str(self.path)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('8 policies', result.stdout)
        self.assertNotIn('/synthetic/', result.stdout + result.stderr)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == '__main__':
    unittest.main()
