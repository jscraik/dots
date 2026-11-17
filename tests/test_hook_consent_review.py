"""Reviewed toggles preserve hook identity and executable trust boundaries."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('consent_review', ROOT / 'codex/scripts/desktop_compatibility.py')
compat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compat)


class HookConsentReviewTests(unittest.TestCase):
    def setUp(self):
        self.identity = 'user:/fixture/.codex/hooks.json:pre_tool_use:0:0'
        self.state = {'trusted_hash': 'sha256:' + 'a' * 64, 'enabled': False}
        self.original = {'model': 'unchanged', 'hooks': {'state': {self.identity: self.state}}}

    @staticmethod
    def render(data):
        return compat.overlay('', [{'path': [key], 'after': {'present': True, 'value': value}}
                                   for key, value in data.items()])

    def test_toggle_roundtrip_preserves_every_other_field(self):
        changed = copy.deepcopy(self.original)
        changed['hooks']['state'][self.identity]['enabled'] = True
        before, after = self.render(self.original), self.render(changed)
        forward = compat.delta(before, after)
        self.assertEqual(len(forward), 1)
        self.assertEqual(forward[0]['path'], ['hooks', 'state', self.identity, 'enabled'])
        self.assertEqual(compat.overlay(before, forward), after)
        self.assertEqual(compat.overlay(after, compat.delta(after, before)), before)

    def test_toggle_cannot_grant_trust_or_change_policy(self):
        for mutation in ('hash', 'identity', 'integer', 'missing', 'provider', 'extra'):
            changed = copy.deepcopy(self.original)
            entry = changed['hooks']['state'][self.identity]
            entry['enabled'] = True
            if mutation == 'hash':
                entry['trusted_hash'] = 'sha256:' + 'b' * 64
            elif mutation == 'identity':
                changed['hooks']['state']['other'] = entry.copy()
            elif mutation == 'integer':
                entry['enabled'] = 1
            elif mutation == 'missing':
                entry.pop('enabled')
            elif mutation == 'provider':
                changed['model_provider'] = 'different'
            else:
                entry['extra'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                compat.delta(self.render(self.original), self.render(changed))

    def test_rollback_rejects_missing_or_changed_trust_identity(self):
        selected = copy.deepcopy(self.original)
        selected['hooks']['state'][self.identity]['enabled'] = True
        installed, observed = self.render(self.original), self.render(selected)
        changes = compat.delta(installed, observed)
        self.assertEqual(compat.reviewed_rollback(installed, installed, changes), observed)
        for kind in ('missing', 'hash'):
            backup = copy.deepcopy(self.original)
            if kind == 'missing':
                backup['hooks']['state'] = {}
            else:
                backup['hooks']['state'][self.identity]['trusted_hash'] = 'sha256:' + 'b' * 64
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                compat.reviewed_rollback(self.render(backup), installed, changes)

    def test_package_key_rebase_rejects_collisions_and_ignores_lookalikes(self):
        spec = importlib.util.spec_from_file_location('consent_installer', ROOT / 'codex/scripts/install-codex.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        review = {'state_dir': '/fixture/previous'}
        suffix = 'codex/hooks/hooks.json:stop:0:0'
        old_key = '/fixture/previous/payload/' + suffix
        new_key = str(ROOT) + '/' + suffix
        state = {'hooks': {'state': {old_key: self.state}}}
        result = installer.rebase_reviewed_hook_keys(self.render(state), review)
        expected = {'hooks': {'state': {new_key: self.state}}}
        self.assertEqual(result, self.render(expected))
        state['hooks']['state'][new_key] = self.state.copy()
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            installer.rebase_reviewed_hook_keys(self.render(state), review)
        lookalike = self.render({'hooks': {'state': {'/fixture/previous/payload-other/' + suffix: self.state}}})
        self.assertEqual(installer.rebase_reviewed_hook_keys(lookalike, review), lookalike)

    def test_review_preserves_selected_model_and_typed_desktop_preference(self):
        original = self.render(self.original)
        changed = copy.deepcopy(self.original)
        changed['model'] = 'gpt-6-sol'
        changed['model_reasoning_effort'] = 'low'
        changed['desktop'] = {'daybreak-enabled': {'accountId': 'synthetic-account',
                              'userId': 'synthetic-user', 'enabled': False}}
        observed = self.render(changed)
        rows = compat.delta(original, observed)
        self.assertEqual(len(rows), 3)
        self.assertEqual(compat.overlay(original, rows), observed)
        for path, value in ((('model',), ''), (('model',), 1),
                            (('desktop', 'daybreak-enabled'), {'enabled': False}),
                            (('desktop', 'daybreak-enabled'), {'accountId': 'x', 'userId': 'y', 'enabled': 0})):
            with self.subTest(path=path, value=value), self.assertRaises(ValueError):
                compat.validate_desktop_change(path, {'present': True, 'value': value})
