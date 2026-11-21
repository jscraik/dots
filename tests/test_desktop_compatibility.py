"""Desktop restart exceptions must be explicit and content-bound."""
import importlib.util
import copy
import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopCompatibilityTests(unittest.TestCase):
    def test_native_consent_requires_exact_installation_bound_explicit_review(self):
        adapter, installed, _ = self.seven_fixture()
        source = '/fixture/.codex/hooks.json'
        key = 'user:' + source + ':pre_tool_use:0:0'
        states = {key: {'enabled': True, 'trusted_hash': 'sha256:' + 'a' * 64}}
        observed = adapter.overlay(installed, [{'path': ['hooks', 'state'],
            'after': {'present': True, 'value': states}}])
        self.assertRaises(ValueError, adapter.delta, installed, observed)
        changes = adapter.delta(installed, observed, hook_source=source)
        self.assertEqual([row['path'] for row in changes], [['hooks', 'state']])
        # Native CLI generations use both the exact source prefix and user:.
        adapter.delta(installed, observed.replace('user:' + source, source), hook_source=source)
        # The native schema defaults enabled to true when the field is absent.
        default_enabled = adapter.overlay(installed, [{'path': ['hooks', 'state'],
            'after': {'present': True, 'value': {key: {'trusted_hash': 'sha256:' + 'a' * 64}}}}])
        default_changes = adapter.delta(installed, default_enabled, hook_source=source)
        self.assertEqual(adapter.reviewed_rollback(installed, installed, default_changes), default_enabled)
        disabled = adapter.overlay(default_enabled, [{'path': ['hooks', 'state', key, 'enabled'],
            'after': {'present': True, 'value': False}}])
        toggle = adapter.delta(default_enabled, disabled, hook_source=source)
        self.assertEqual(adapter.reviewed_rollback(default_enabled, default_enabled, toggle), disabled)
        enabled_again = adapter.delta(disabled, default_enabled, hook_source=source)
        self.assertEqual(adapter.reviewed_rollback(disabled, disabled, enabled_again), default_enabled)
        self.assertTrue(adapter.requires_preservation(tomllib.loads(observed)))
        bad_states = [
            {key: states[key], key.removeprefix('user:'): states[key]},
            {key.replace('/fixture/', '/other/'): states[key]},
            {key: dict(states[key], enabled=1)},
            {key: dict(states[key], extra=True)},
            {key: dict(states[key], trusted_hash='invalid')},
            {key.replace('pre_tool_use', 'unknown'): states[key]},
        ]
        for value in bad_states:
            invalid = adapter.overlay(installed, [{'path': ['hooks', 'state'],
                'after': {'present': True, 'value': value}}])
            with self.subTest(value=value), self.assertRaises(ValueError):
                adapter.delta(installed, invalid, hook_source=source)
        # A reviewed fresh-consent route cannot replace previously trusted hashes.
        replacement = observed.replace('a' * 64, 'b' * 64)
        self.assertRaises(ValueError, adapter.delta, observed, replacement, hook_source=source)
        self.assertRaises(ValueError, adapter.delta, installed,
            observed.replace('on-request', 'never'), hook_source=source)

    def test_explicit_native_review_accepts_complete_revocation(self):
        adapter, installed, _ = self.seven_fixture()
        source = '/fixture/.codex/hooks.json'
        revoked = adapter.overlay(installed, [{'path': ['hooks', 'state'],
            'after': {'present': True, 'value': {}}}])
        self.assertRaises(ValueError, adapter.delta, installed, revoked)
        changes = adapter.delta(installed, revoked, hook_source=source)
        self.assertEqual(changes[0]['after'], {'present': True, 'value': {}})
        trusted = adapter.overlay(installed, [{'path': ['hooks', 'state'],
            'after': {'present': True, 'value': {source + ':pre_tool_use:0:0':
                {'enabled': True, 'trusted_hash': 'sha256:' + 'a' * 64}}}}])
        changes = adapter.delta(trusted, revoked, hook_source=source)
        self.assertEqual(adapter.overlay(trusted, changes), revoked)
        self.assertEqual(adapter.reviewed_rollback(trusted, trusted, changes), revoked)
        self.assertRaises(ValueError, adapter.reviewed_rollback,
            trusted.replace('a' * 64, 'b' * 64), trusted, changes)
        fresh = trusted.replace('a' * 64, 'b' * 64)
        self.assertRaises(ValueError, adapter.delta, revoked, fresh)
        fresh_changes = adapter.delta(revoked, fresh, hook_source=source)
        self.assertEqual(adapter.reviewed_rollback(revoked, revoked, fresh_changes), fresh)
        self.assertRaises(ValueError, adapter.reviewed_rollback, trusted, revoked, fresh_changes)
        self.assertRaises(ValueError, adapter.delta, installed,
            revoked.replace('on-request', 'never'), hook_source=source)

    def test_incremental_native_consent_preserves_existing_trust(self):
        adapter, installed, _ = self.seven_fixture()
        source = '/fixture/.codex/hooks.json'
        first = source + ':pre_tool_use:0:0'
        second = source + ':stop:0:0'
        states = {first: {'trusted_hash': 'sha256:' + 'a' * 64}}
        trusted = adapter.overlay(installed, [{'path': ['hooks', 'state'],
            'after': {'present': True, 'value': states}}])
        additional = dict(states, **{second: {'enabled': True, 'trusted_hash': 'sha256:' + 'b' * 64}})
        observed = adapter.overlay(trusted, [{'path': ['hooks', 'state'],
            'after': {'present': True, 'value': additional}}])
        self.assertRaises(ValueError, adapter.delta, trusted, observed)
        changes = adapter.delta(trusted, observed, hook_source=source)
        self.assertEqual(adapter.reviewed_rollback(trusted, trusted, changes), observed)
        self.assertRaises(ValueError, adapter.reviewed_rollback, installed, trusted, changes)
        self.assertRaises(ValueError, adapter.delta, trusted,
            observed.replace('a' * 64, 'c' * 64), hook_source=source)
        self.assertRaises(ValueError, adapter.delta, trusted,
            observed.replace(second, 'user:' + first), hook_source=source)
        foreign = trusted.replace(source, '/other/hooks.json')
        mixed = adapter.overlay(foreign, [{'path': ['hooks', 'state', second],
            'after': {'present': True, 'value': additional[second]}}])
        mixed_changes = adapter.delta(foreign, mixed, hook_source=source)
        self.assertEqual(adapter.reviewed_rollback(foreign, foreign, mixed_changes), mixed)
        empty = adapter.overlay(installed, [{'path': ['hooks', 'state'],
            'after': {'present': True, 'value': {}}}])
        empty_changes = adapter.delta(installed, empty, hook_source=source)
        self.assertRaises(ValueError, adapter.reviewed_rollback, '', installed, empty_changes)

    def paired_fixture(self):
        adapter, installed, observed = self.seven_fixture()
        source = '/fixture/.codex/hooks.json'
        key = 'user:' + source + ':pre_tool_use:0:0'
        installed = adapter.overlay(installed, [{'path': ['hooks', 'state', key],
            'after': {'present': True, 'value': {'enabled': True, 'trusted_hash': 'sha256:' + '1' * 64}}}])
        observed = adapter.overlay(observed, [{'path': ['hooks', 'state', key],
            'after': {'present': True, 'value': {'enabled': True, 'trusted_hash': 'sha256:' + '2' * 64}}}])
        layout = adapter.micro_layout()
        layout['separateMicrophoneKeys'] = True
        observed = adapter.overlay(observed, [{'path': ['desktop', 'codex-micro-layout'],
            'after': {'present': True, 'value': layout}}])
        hooks = {'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [
            {'type': 'command', 'command': '/app/braid hook --client codex'}]}]}}
        changed = copy.deepcopy(hooks)
        changed['hooks']['PreToolUse'][0]['hooks'][0]['command'] = '"/app/braid" hook --client codex'
        return adapter, installed, observed, json.dumps(hooks), json.dumps(changed), source

    def test_matched_pair_restores_old_consent_without_a_trust_exception(self):
        adapter, installed, observed, hooks, changed, source = self.paired_fixture()
        self.assertRaises(ValueError, adapter.repair_candidate, installed, observed)
        proposal = adapter.paired_repair_candidate(installed, observed, hooks, changed, hook_source=source)
        self.assertEqual(proposal['status'], 'paired_repair_candidate_only')
        self.assertEqual(proposal['hooks_candidate'], hooks)
        self.assertEqual(proposal['hooks_candidate_sha256'], adapter.sha(hooks.encode()))
        self.assertEqual(proposal['observed_hooks_sha256'], adapter.sha(changed.encode()))
        repaired = tomllib.loads(proposal['candidate'])
        self.assertEqual(repaired['hooks'], tomllib.loads(installed)['hooks'])
        self.assertIs(repaired['desktop']['codex-micro-layout']['separateMicrophoneKeys'], True)
        adapter.delta(installed, proposal['candidate'])
        again = adapter.paired_repair_candidate(installed, proposal['candidate'], hooks, hooks, hook_source=source)
        self.assertEqual(again['candidate'], proposal['candidate'])

    def test_pair_rejects_unbound_consent_and_changed_authority(self):
        adapter, installed, observed, hooks, changed, source = self.paired_fixture()
        for before, after in ((source, '/other/hooks.json'), ('enabled = true', 'enabled = false'),
                              ('sha256:', 'invalid:')):
            with self.subTest(after=after), self.assertRaises(ValueError):
                adapter.paired_repair_candidate(installed, observed.replace(before, after), hooks, changed, hook_source=source)
        self.assertRaises(ValueError, adapter.paired_repair_candidate,
            installed, observed, hooks, hooks, hook_source=source)
        self.assertRaises(ValueError, adapter.paired_repair_candidate,
            installed, observed.replace('on-request', 'never'), hooks, changed, hook_source=source)

    def test_quote_repair_rejects_shell_semantics_and_other_hook_changes(self):
        adapter, _, _, hooks, changed, _ = self.paired_fixture()
        commands = ('/app/braid hook\n--client codex', '/app/braid hook --client other',
                    '/app/braid hook --client $CODEX', '/app/braid hook ; codex',
                    '/other/braid hook --client codex', '/bin/bash hook --client codex')
        for command in commands:
            data = json.loads(changed)
            data['hooks']['PreToolUse'][0]['hooks'][0]['command'] = command
            with self.subTest(command=command), self.assertRaises(ValueError):
                adapter.hook_quote_candidate(hooks, json.dumps(data))
        for field, value in (('matcher', 'other'), ('timeout', 999)):
            data = json.loads(changed)
            data['hooks']['PreToolUse'][0][field] = value
            self.assertRaises(ValueError, adapter.hook_quote_candidate, hooks, json.dumps(data))
        self.assertRaises(ValueError, adapter.hook_quote_candidate, hooks, '{"hooks":{},"hooks":{}}')
        self.assertRaises(ValueError, adapter.hook_quote_candidate, hooks, '[]')

    def test_micro_layout_allows_only_reviewed_toml_shape_and_boolean_choice(self):
        adapter, installed, observed = self.seven_fixture()
        layout = adapter.micro_layout()
        for flag in (False, True):
            layout['separateMicrophoneKeys'] = flag
            value = adapter.overlay(observed, [{'path': ['desktop', 'codex-micro-layout'],
                'after': {'present': True, 'value': layout}}])
            adapter.repair_candidate(installed, value)
        bad = [dict(layout, separateMicrophoneKeys=1), dict(layout, version=True),
               dict(layout, encoderMode='custom'), dict(layout, extra=True)]
        custom = copy.deepcopy(layout)
        custom['analogStick']['up']['commandId'] = 'other.command'
        bad.append(custom)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                adapter.validate_desktop_change(('desktop', 'codex-micro-layout'), {'present': True, 'value': value})

    def seven_fixture(self):
        spec = importlib.util.spec_from_file_location(
            'seven_desktop', ROOT / 'codex/scripts/desktop_compatibility.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        installed = ('approval_policy = "on-request"\ndefault_permissions = "workspace"\n'
            '[permissions.workspace]\nextends = ":workspace"\n'
            '[permissions.workspace.network]\nenabled = true\n'
            '[features]\nmulti_agent = true\n'
            '[desktop]\nappearanceDarkChromeTheme = {kind = "preset", themeId = "codex"}\n')
        changes = [
            {'path': ['features', 'multi_agent'], 'after': {'present': False}},
            {'path': ['sandbox_mode'], 'after': {'present': True, 'value': 'workspace-write'}},
            {'path': ['sandbox_workspace_write'], 'after': {'present': True, 'value': {'network_access': True}}},
            {'path': ['desktop', 'appearanceDarkChromeTheme'], 'after': {'present': False}},
            {'path': ['desktop', 'appearanceDarkCodeThemeId'], 'after': {'present': True, 'value': 'codex'}},
            {'path': ['desktop', 'autoArchiveAfterDays'], 'after': {'present': True, 'value': 7}},
            {'path': ['plugins', 'codex-app-tools@openai-bundled'], 'after': {'present': True, 'value': {'enabled': True}}},
        ]
        return adapter, installed, adapter.overlay(installed, changes)

    def test_seven_field_candidate_restores_policy_without_clearing_observed_drift(self):
        adapter, installed, observed = self.seven_fixture()
        with self.assertRaises(ValueError):
            adapter.delta(installed, observed)
        proposal = adapter.repair_candidate(installed, observed)
        self.assertEqual(proposal['status'], 'repair_candidate_only')
        self.assertEqual(proposal['observed_sha256'], adapter.sha(observed.encode()))
        self.assertEqual(proposal['candidate_sha256'], adapter.sha(proposal['candidate'].encode()))
        candidate = tomllib.loads(proposal['candidate'])
        self.assertIs(candidate['features']['multi_agent'], True)
        self.assertNotIn('sandbox_mode', candidate)
        self.assertNotIn('sandbox_workspace_write', candidate)
        self.assertEqual(candidate['permissions'], tomllib.loads(installed)['permissions'])
        self.assertEqual(candidate['desktop'], {'appearanceDarkCodeThemeId': 'codex', 'autoArchiveAfterDays': 7})
        self.assertEqual(candidate['plugins'], {'codex-app-tools@openai-bundled': {'enabled': True}})
        self.assertTrue(adapter.requires_preservation(candidate))
        self.assertEqual(len(proposal['canonical_restorations']), 3)
        self.assertEqual(len(adapter.delta(installed, proposal['candidate'])), 4)
        with self.assertRaises(ValueError):
            adapter.delta(installed, proposal['candidate'].replace('on-request', 'never'))

    def test_unrelated_policy_and_plugin_changes_remain_blocking(self):
        adapter, installed, observed = self.seven_fixture()
        replacements = [
            ('approval_policy = "on-request"', 'approval_policy = "never"'),
            ('extends = ":workspace"', 'extends = ":read-only"'),
            ('network_access = true', 'network_access = false'),
            ('network_access = true', 'network_access = true\nwritable_roots = ["/outside"]'),
        ]
        for before, after in replacements:
            with self.subTest(after=after), self.assertRaises(ValueError):
                adapter.repair_candidate(installed, observed.replace(before, after))
        for extra in ('\n[desktop.unreviewed]\nenabled = true\n',
                      '\n[plugins.arbitrary]\nenabled = true\n'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                adapter.repair_candidate(installed, observed + extra)
        changed = adapter.overlay(observed, [{'path': ['features', 'multi_agent'],
            'after': {'present': True, 'value': False}}])
        self.assertRaises(ValueError, adapter.repair_candidate, installed, changed)

    def test_new_desktop_slots_reject_unvalidated_values(self):
        adapter, installed, observed = self.seven_fixture()
        bad = [
            (['desktop', 'autoArchiveAfterDays'], True),
            (['desktop', 'autoArchiveAfterDays'], -1),
            (['desktop', 'autoArchiveAfterDays'], 1.5),
            (['desktop', 'appearanceDarkCodeThemeId'], 'unverified-theme'),
            (['desktop', 'appearanceDarkChromeTheme'], {'arbitrary': True}),
            (['plugins', 'codex-app-tools@openai-bundled'], {'enabled': 1}),
            (['plugins', 'codex-app-tools@openai-bundled'], {'enabled': True, 'command': '/unverified'}),
        ]
        for path, value in bad:
            changed = adapter.overlay(observed, [{'path': path, 'after': {'present': True, 'value': value}}])
            with self.subTest(path=path, value=value), self.assertRaises(ValueError):
                adapter.repair_candidate(installed, changed)

    def test_candidate_is_idempotent_and_rejects_legacy_canonical_input(self):
        adapter, installed, observed = self.seven_fixture()
        first = adapter.repair_candidate(installed, observed)
        again = adapter.repair_candidate(installed, first['candidate'])
        self.assertEqual(first['candidate'], again['candidate'])
        self.assertEqual(again['canonical_restorations'], [])
        self.assertRaises(ValueError, adapter.repair_candidate, observed, observed)

    def test_exact_registration_and_rollback_preserve_safety(self):
        spec = importlib.util.spec_from_file_location(
            'desktop_compatibility', ROOT / 'codex/scripts/desktop_compatibility.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        installed = 'approval_policy = "on-request"\n[desktop]\nselected-avatar-id = "old"\n'
        observed = ('approval_policy = "on-request"\nnotify = ["/app/notify", "done"]\n'
                    '[desktop]\nselected-avatar-id = "new"\n'
                    '[mcp_servers.node_repl]\ncommand = "/app/node"\nargs = []\n')
        changes = adapter.delta(installed, observed)
        restored = adapter.overlay('approval_policy = "untrusted"\n', changes)
        self.assertIn('untrusted', restored)
        self.assertEqual(adapter.delta(installed, observed), changes)
        self.assertIn('/app/node', restored)
        self.assertRaises(ValueError, adapter.delta, installed,
                          observed.replace('on-request', 'never'))
        self.assertRaises(ValueError, adapter.delta, installed,
                          observed + '\n[unknown]\nenabled = true\n')

    def test_private_receipt_rejects_wrong_pin_state_alias_and_backup(self):
        spec = importlib.util.spec_from_file_location(
            'desktop_compatibility', ROOT / 'codex/scripts/desktop_compatibility.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        with tempfile.TemporaryDirectory() as name:
            state = Path(name)
            original = 'approval_policy = "on-request"\n'
            observed = original + 'notify = ["/app/notify"]\n'
            changes = adapter.delta(original, observed)
            (state / 'backups').mkdir()
            backup = state / 'backups/config.toml'
            backup.write_text(original)
            plan = {'home': str(state / 'home'), 'package_digest': 'a' * 64,
                    'expected': {'config.toml': {'sha256': adapter.sha(original.encode())}},
                    'before': {'config.toml': {'kind': 'file', 'sha256': adapter.sha(original.encode())}}}
            record = dict(schema_version=1, state_dir=str(state), home=plan['home'],
                package_digest=plan['package_digest'], plan_digest='b' * 64,
                installed=original, observed=observed, original=original,
                rollback=adapter.overlay(original, changes), changes=changes)
            raw = json.dumps(record).encode()
            path = state / 'desktop-review.json'
            path.write_bytes(raw)
            path.chmod(0o600)
            kwargs = dict(state=state, plan_digest='b' * 64, plan=plan)
            pin = adapter.sha(raw)
            self.assertEqual(adapter.load(path, pin, **kwargs), record)
            self.assertRaises(ValueError, adapter.load, path, '0' * 64, **kwargs)
            self.assertRaises(ValueError, adapter.load, path, pin,
                              **dict(kwargs, state=state / 'other'))
            path.chmod(0o644)
            self.assertRaises(ValueError, adapter.load, path, pin, **kwargs)
            path.chmod(0o600)
            alias = state / 'alias'
            alias.symlink_to(path)
            self.assertRaises(ValueError, adapter.load, alias, pin, **kwargs)
            alias.unlink()
            os.link(path, alias)
            self.assertRaises(ValueError, adapter.load, path, pin, **kwargs)
            alias.unlink()
            backup.write_text('approval_policy = "never"\n')
            self.assertRaises(ValueError, adapter.load, path, pin, **kwargs)


if __name__ == '__main__':
    unittest.main()
