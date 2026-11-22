"""Complete generated-policy projection: actual entrypoints and rejection paths."""
import json
import hashlib
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from policy_fixture import PolicyFixture


class PolicyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PolicyFixture(self)
        self.addCleanup(self.fixture.assert_preserved, self)

    def success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def legacy_notifier_runtime(self, *, enabled=False):
        fixture = self.fixture
        self.success(fixture.project())
        runtime = fixture.runtime / 'config.toml'
        legacy = {'command': str(fixture.home / 'retired-fixture-node'), 'args': ['fixture-only']}
        digest = hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        helper = fixture.codex / 'scripts/repair-runtime-config-drift.py'
        source = helper.read_text()
        pinned = "LEGACY_PINNED_CUA_SHA256 = '149d490fc3e32e510f3b9d7926334d276315f9d6af78c6fe35edac73dd459b45'"
        self.assertIn(pinned, source)
        # Model the historical identity in this owned copy only. No retired
        # launcher executes, and the production identity pin is unchanged.
        helper.write_text(source.replace(pinned, f"LEGACY_PINNED_CUA_SHA256 = '{digest}'"))
        text = ('notify = ["SkyComputerUseClient"]\n' + runtime.read_text()
                + '\n[mcp_servers.cua_repl]\ncommand = ' + json.dumps(legacy['command'])
                + '\nargs = ["fixture-only"]\n'
                + '[plugins."computer-use@openai-bundled"]\n'
                + f'enabled = {str(enabled).lower()}\n')
        runtime.write_text(text)
        return runtime, text.encode()

    def test_legacy_notifier_cleanup_rejects_authority_before_any_write(self):
        runtime, original = self.legacy_notifier_runtime(enabled=True)
        backup = self.fixture.home / 'legacy-config-backup.toml'
        result = self.fixture.script('repair-runtime-config-drift.py', '--config-path', str(runtime),
                                     '--repair', '--backup-path', str(backup), '--json')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(runtime.read_bytes(), original)
        self.assertFalse(backup.exists())

    def test_legacy_notifier_cleanup_validates_real_policy_and_retains_launcher(self):
        runtime, original = self.legacy_notifier_runtime()
        backup = self.fixture.home / 'legacy-config-backup.toml'
        result = self.fixture.script('repair-runtime-config-drift.py', '--config-path', str(runtime),
                                     '--repair', '--backup-path', str(backup), '--json')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['reason'], 'legacy_repository_pinned_cua_cutover_required')
        self.assertEqual(backup.read_bytes(), original)
        expected = tomllib.loads(original.decode())
        del expected['notify']
        self.assertEqual(tomllib.loads(runtime.read_text()), expected)

    def test_legacy_notifier_cleanup_requires_snapshot_verdict_before_backup(self):
        runtime, original = self.legacy_notifier_runtime()
        marker = self.fixture.home / 'legacy-snapshot-checked'
        validator = self.fixture.codex / 'scripts/validate-codex-config.py'
        validator.write_text('import sys\nfrom pathlib import Path\n'
                             f'Path({str(marker)!r}).write_text(sys.stdin.read())\n'
                             'raise SystemExit(75)\n')
        backup = self.fixture.home / 'legacy-config-backup.toml'
        result = self.fixture.script('repair-runtime-config-drift.py', '--config-path', str(runtime),
                                     '--repair', '--backup-path', str(backup), '--json')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(marker.exists(), result.stdout + result.stderr)
        self.assertNotIn('notify', tomllib.loads(marker.read_text()))
        self.assertEqual(json.loads(result.stdout)['reason'], 'canonical_validation_unavailable')
        self.assertEqual(runtime.read_bytes(), original)
        self.assertFalse(backup.exists())

    def test_project_audit_validate_repeat(self):
        fixture = self.fixture
        self.success(fixture.project())
        self.assertEqual(tomllib.loads((fixture.runtime / 'config.toml').read_text()), fixture.base.root)
        self.assertFalse((fixture.runtime / 'config.toml').samefile(fixture.codex / 'config.toml'))
        self.assertFalse(fixture.target.samefile(fixture.source))
        self.success(fixture.script('validate-codex-config.py'))
        self.success(fixture.script('audit-codex-symlinks.sh', '--codex-home', str(fixture.runtime)))
        self.success(fixture.script('check-runtime-config-path.sh', str(fixture.runtime / 'config.toml')))
        before = fixture.managed_snapshot()
        self.success(fixture.script('reconcile-config-projection.sh', '--repair', '--scope', 'codex',
                                    '--codex-home', str(fixture.runtime)))
        self.success(fixture.project('--check'))
        self.assertEqual(fixture.managed_snapshot(), before)

    def test_invalid_policy_missing_schema_and_changed_map_reject_before_writes(self):
        fixture = self.fixture
        original = (fixture.codex / 'config.toml').read_text()
        schema = fixture.codex / 'schemas/config.schema.json'
        schema_bytes = schema.read_bytes()
        baseline = fixture.managed_snapshot()
        for kind in ('weakened', 'malformed', 'missing-schema', 'changed-map', 'boolean-version'):
            with self.subTest(kind=kind):
                if kind == 'weakened':
                    self.assertIn('hooks = true', original)
                    (fixture.codex / 'config.toml').write_text(original.replace('hooks = true', 'hooks = false', 1))
                elif kind == 'malformed':
                    (fixture.codex / 'config.toml').write_text('broken = [')
                elif kind == 'missing-schema':
                    schema.unlink()
                elif kind == 'changed-map':
                    altered = dict(fixture.map) | {'global_projection': [{'target': '{HOME}/unexpected'}]}
                    (fixture.codex / 'projection-map.json').write_text(json.dumps(altered))
                else:
                    (fixture.codex / 'projection-map.json').write_text(json.dumps(fixture.map | {'schema_version': True}))
                result = fixture.project()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(fixture.managed_snapshot(), baseline)
                self.assertFalse((fixture.home / '.config-symlink-backups').exists())
                (fixture.codex / 'config.toml').write_text(original)
                schema.write_bytes(schema_bytes)
                (fixture.codex / 'projection-map.json').write_text(json.dumps(fixture.map))

    def test_dry_run_preserves_all_targets(self):
        fixture = self.fixture
        before = fixture.managed_snapshot()
        self.success(fixture.project('--repair', '--dry-run'))
        self.assertEqual(fixture.managed_snapshot(), before)
        self.assertFalse((fixture.home / '.config-symlink-backups').exists())

    def test_inline_projection_ignores_workspace_python_modules(self):
        fixture = self.fixture
        marker = fixture.home / 'workspace-python-ran'
        (fixture.repo / 'json.py').write_text('from pathlib import Path\nPath('
            + repr(str(marker)) + ').touch()\nraise RuntimeError("workspace module imported")\n')
        before = fixture.managed_snapshot()
        self.success(fixture.project('--repair', '--dry-run'))
        self.assertFalse(marker.exists())
        self.assertEqual(fixture.managed_snapshot(), before)

    def test_copy_hardlinks_are_rejected_before_any_projection(self):
        fixture = self.fixture
        for relative in ('config.toml', 'hooks.json'):
            with self.subTest(relative=relative):
                source = fixture.codex / ('config.toml' if relative == 'config.toml' else 'hooks/hooks.json')
                target = fixture.runtime / relative
                original = source.read_bytes()
                os.link(source, target)
                try:
                    before = fixture.managed_snapshot()
                    self.assertNotEqual(fixture.project().returncode, 0)
                    self.assertEqual(fixture.managed_snapshot(), before)
                    self.assertEqual(source.read_bytes(), original)
                finally:
                    target.unlink()

    def test_dangling_local_directory_links_reject_before_writes(self):
        fixture = self.fixture
        for relative in ('agents', 'automations', 'usage-data'):
            with self.subTest(relative=relative):
                target = fixture.runtime / relative
                target.symlink_to(fixture.home / 'missing-directory')
                try:
                    before = fixture.managed_snapshot()
                    self.assertNotEqual(fixture.project().returncode, 0)
                    self.assertEqual(fixture.managed_snapshot(), before)
                    self.assertFalse((fixture.home / '.config-symlink-backups').exists())
                finally:
                    target.unlink()

    def test_copy_directory_conflicts_reject_before_writes(self):
        fixture = self.fixture
        for relative in ('config.toml', 'hooks.json'):
            with self.subTest(relative=relative):
                target = fixture.runtime / relative
                target.mkdir()
                try:
                    before = fixture.managed_snapshot()
                    self.assertNotEqual(fixture.project().returncode, 0)
                    self.assertEqual(fixture.managed_snapshot(), before)
                finally:
                    target.rmdir()

    def test_drift_repair_preserves_desktop_exception_and_recoverable_backup(self):
        fixture = self.fixture
        self.success(fixture.project())
        runtime = fixture.runtime / 'config.toml'
        previous = runtime.read_text().replace('approval_policy = "on-request"', 'approval_policy = "never"', 1)
        # Valid Desktop presentation is an existing exception to parsed equality.
        self.assertIn('model_verbosity = "medium"', previous)
        previous = previous.replace('model_verbosity = "medium"', 'model_verbosity = "high"', 1)
        self.assertIn('\n[desktop]\n', previous)
        plugin = '''[plugins."computer-use@openai-bundled"]
enabled = false
'''
        previous = previous.replace('\n[desktop]\n', '\n' + plugin + '\n[desktop]\n', 1)
        runtime.write_text(previous)
        self.assertNotEqual(fixture.project('--check').returncode, 0)
        repaired = self.success(fixture.project())
        data = tomllib.loads(runtime.read_text())
        self.assertEqual(data['approval_policy'], 'on-request')
        self.assertEqual(data['model_verbosity'], 'high')
        self.assertEqual(data['plugins']['computer-use@openai-bundled'],
                         tomllib.loads(previous)['plugins']['computer-use@openai-bundled'])
        self.success(fixture.script('validate-codex-config.py'))
        payloads = [json.loads(line) for line in repaired.stdout.splitlines() if line.startswith('{')]
        receipts = [item for item in payloads if item.get('backup_path')]
        self.assertTrue(receipts, 'pre-repair runtime must remain recoverable')
        backup = Path(receipts[0]['backup_path'])
        self.assertTrue(backup.is_relative_to(fixture.home))
        self.assertEqual(backup.read_bytes(), previous.encode())

    def test_drift_repair_rejects_desktop_plugin_authority(self):
        fixture = self.fixture
        self.success(fixture.project())
        runtime = fixture.runtime / 'config.toml'
        original = runtime.read_text()
        plugins = (
            '[plugins."computer-use@openai-bundled"]\nenabled = true\n',
            '[plugins."computer-use@openai-bundled"]\nenabled = false\n'
            '[plugins."computer-use@openai-bundled".mcp_servers.cua_repl]\n'
            'default_tools_approval_mode = "auto"\n',
            '[plugins."computer-use@openai-bundled"]\nenabled = false\n'
            '[plugins."computer-use@openai-bundled".mcp_servers.cua_repl]\n'
            'enabled_tools = ["click"]\n',
            '[plugins."computer-use@openai-bundled"]\nenabled = false\n'
            'command = "/unreviewed"\nenv = { TOKEN = "unreviewed" }\n',
        )
        for plugin in plugins:
            with self.subTest(plugin=plugin):
                previous = original.replace('\n[desktop]\n', '\n' + plugin + '\n[desktop]\n', 1)
                runtime.write_text(previous)
                result = fixture.project()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(runtime.read_bytes(), previous.encode())

    def test_symlink_escape_and_bad_runtime_directory_preserve_targets(self):
        fixture = self.fixture
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as outside:
            sentinel = Path(outside) / 'sentinel'
            sentinel.write_bytes(b'owned sibling sentinel')
            runtime = fixture.runtime / 'config.toml'
            runtime.symlink_to(sentinel)
            self.assertNotEqual(fixture.project().returncode, 0)
            self.assertEqual(sentinel.read_bytes(), b'owned sibling sentinel')
            runtime.unlink()
        (fixture.runtime / 'usage-data').write_text('caller-owned conflict')
        self.assertNotEqual(fixture.project().returncode, 0)
        self.assertFalse((fixture.runtime / 'config.toml').exists())
        self.assertEqual((fixture.runtime / 'usage-data').read_text(), 'caller-owned conflict')

    def test_policy_update_and_canonical_rollback_preserve_local_state(self):
        fixture = self.fixture
        self.success(fixture.project())
        source = fixture.codex / 'config.toml'
        original = source.read_bytes()
        runtime = fixture.runtime / 'config.toml'
        original_runtime = runtime.read_bytes()
        import test_governance_port as governance
        updated = tomllib.loads(original.decode())
        updated['developer_instructions'] += '\nFixture-only integration update.'
        source.write_text(governance.GEN.toml_document(updated))
        result = self.success(fixture.project())
        self.assertIn('Fixture-only integration update.', tomllib.loads(runtime.read_text())['developer_instructions'])
        payloads = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        backup = Path(next(item['backup_path'] for item in payloads if item.get('backup_path')))
        self.assertEqual(backup.read_bytes(), original_runtime)
        # Restore only the owned canonical input, then use the same supported
        # reconciliation route to roll back managed runtime policy.
        source.write_bytes(original)
        self.success(fixture.project())
        self.assertEqual(tomllib.loads(runtime.read_text()), tomllib.loads(original_runtime.decode()))
        self.success(fixture.script('validate-codex-config.py'))

    def test_consent_saved_during_validation_cannot_be_copied_to_backup(self):
        fixture = self.fixture
        self.success(fixture.project())
        runtime = fixture.runtime / 'config.toml'
        original = runtime.read_text().replace('approval_policy = "on-request"', 'approval_policy = "never"', 1)
        runtime.write_text(original)
        backup = fixture.home / 'racing-backup.toml'
        child = '''import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("racing_repair", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
validate = module._validate_runtime_snapshot
def save_consent(text):
    validate(text)
    with Path(sys.argv[2]).open("a") as stream:
        stream.write("\\n[hooks.state.racing]\\nenabled = true\\ntrusted_hash = 'fixture'\\n")
module._validate_runtime_snapshot = save_consent
raise SystemExit(module.main(["--config-path",sys.argv[2],"--repair","--json","--backup-path",sys.argv[3]]))
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'), str(runtime), str(backup)],
            env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stdout, result.stderr)
        self.assertFalse(backup.exists(), result.stdout)
        self.assertTrue(tomllib.loads(runtime.read_text())['hooks']['state']['racing']['enabled'])

    def test_absent_repair_never_replaces_a_concurrently_created_config(self):
        fixture = self.fixture
        self.success(fixture.project())
        child = '''import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("absent_repair", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
target = Path(sys.argv[2])
target.write_bytes(b"concurrent native save\\n")
try:
    module._write_repair(target, "repair\\n", expected=None)
except FileExistsError:
    pass
else:
    raise AssertionError("absent-only publication replaced an existing config")
assert target.read_bytes() == b"concurrent native save\\n"
target.unlink()
module._write_repair(target, "repair\\n", expected=None)
assert target.read_bytes() == b"repair\\n"
assert target.stat().st_nlink == 1
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'),
            str(fixture.runtime / 'absent-race.toml')], env=fixture.env, cwd=fixture.repo,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_oversized_config_is_rejected_before_publication_or_backup(self):
        fixture = self.fixture
        self.success(fixture.project())
        child = '''import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("bounded_repair", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
target = Path(sys.argv[2]); original = b"x" * (16 * 1024 * 1024 + 1)
target.write_bytes(original)
try:
    module._write_repair(target, "repair\\n", expected=original)
except OSError:
    pass
else:
    raise AssertionError("oversized original was accepted")
assert target.read_bytes() == original, "oversized original was displaced before rejection"
assert list(target.parent.iterdir()) == [target], "size rejection created recovery material"
target.write_bytes(b"small original\\n")
retained = module._write_repair(target, "repair\\n", expected=b"small original\\n")
assert target.read_bytes() == b"repair\\n"
assert retained.read_bytes() == b"small original\\n"
'''
        directory = fixture.home / 'bounded-repair'
        directory.mkdir()
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'),
            str(directory / 'config.toml')], env=fixture.env, cwd=fixture.repo,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        runtime = fixture.runtime / 'config.toml'
        original = runtime.read_bytes() + b'\n#' + b'x' * (16 * 1024 * 1024)
        runtime.write_bytes(original)
        backup = fixture.home / 'oversized-backup.toml'
        before = set(runtime.parent.iterdir())
        result = fixture.script('repair-runtime-config-drift.py', '--config-path', runtime,
            '--repair', '--backup-path', backup, '--json')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['reason'], 'config_size_limit_exceeded')
        self.assertEqual(runtime.read_bytes(), original)
        self.assertEqual(set(runtime.parent.iterdir()), before)
        self.assertFalse(backup.exists())

    def test_oversized_repaired_candidate_does_not_create_backup(self):
        fixture = self.fixture
        self.success(fixture.project())
        runtime = fixture.runtime / 'config.toml'
        canonical = runtime.read_bytes()
        original = canonical.replace(b'approval_policy = "on-request"', b'approval_policy = "never"', 1)
        self.assertLess(len(original), len(canonical))
        runtime.write_bytes(original)
        backup = fixture.home / 'candidate-size-backup.toml'
        child = '''import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("candidate_size", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
module.REPAIR_FILE_LIMIT = len(Path(sys.argv[2]).read_bytes()) + 1
raise SystemExit(module.main(["--config-path",sys.argv[2],"--repair","--backup-path",sys.argv[3],"--json"]))
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'), str(runtime), str(backup)],
            env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['reason'], 'config_size_limit_exceeded')
        self.assertEqual(runtime.read_bytes(), original)
        self.assertFalse(backup.exists(), 'candidate-size rejection created a backup')

    def test_failed_readback_reports_retained_generation(self):
        fixture = self.fixture
        self.success(fixture.project())
        runtime = fixture.runtime / 'config.toml'
        runtime.write_text(runtime.read_text().replace('approval_policy = "on-request"', 'approval_policy = "never"', 1))
        original = runtime.read_bytes()
        child = '''import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("late_readback", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
publish = module._write_repair
def save_after_publish(*args, **kwargs):
    retained = publish(*args, **kwargs)
    with Path(sys.argv[2]).open("a") as stream:
        stream.write("\\n# save after publication\\n")
    return retained
module._write_repair = save_after_publish
raise SystemExit(module.main(["--config-path",sys.argv[2],"--repair","--json"]))
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'), str(runtime)],
            env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['reason'], 'config_write_failed')
        retained = Path(payload['retained_generation_path'])
        self.assertTrue(retained.is_relative_to(fixture.runtime))
        self.assertEqual(retained.read_bytes(), original)
        self.assertIn('# save after publication', runtime.read_text())

    def test_interruption_after_recording_slot_keeps_staged_candidate(self):
        fixture = self.fixture
        self.success(fixture.project())
        child = '''import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("journal_interrupt", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
target = Path(sys.argv[2]); target.write_bytes(b"original\\n")
recorded = []
def record_then_interrupt(slot):
    recorded.append(slot)
    raise KeyboardInterrupt("synthetic interruption after recording slot")
try:
    module._write_repair(target, "repair\\n", expected=b"original\\n", before_exchange=record_then_interrupt)
except module.RepairPublicationError as error:
    assert recorded == [error.recovery_path]
    assert error.recovery_path.read_bytes() == b"repair\\n"
else:
    raise AssertionError("interrupted publication reported success")
assert target.read_bytes() == b"original\\n"
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'),
            str(fixture.runtime / 'journal-interrupt.toml')], env=fixture.env,
            cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exception_after_exchange_keeps_the_displaced_inode_named(self):
        fixture = self.fixture
        self.success(fixture.project())
        child = '''import importlib.util,os,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("exchange_interrupt", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
target = Path(sys.argv[2]); target.write_bytes(b"original\\n")
writer = os.open(target, os.O_WRONLY | os.O_APPEND)
exchange = module._exchange_paths
def interrupted(first, second):
    exchange(first, second)
    raise KeyboardInterrupt("synthetic interruption after successful syscall")
module._exchange_paths = interrupted
try:
    module._write_repair(target, "repair\\n", expected=b"original\\n")
except module.RepairPublicationError as error:
    retained = error.recovery_path
else:
    raise AssertionError("interrupted publication reported success")
os.write(writer, b"late native save\\n"); os.close(writer)
assert retained.read_bytes() == b"original\\nlate native save\\n"
assert target.read_bytes() == b"repair\\n"
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'),
            str(fixture.runtime / 'interrupted-exchange.toml')], env=fixture.env,
            cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_open_native_writers_keep_named_generations_after_publication(self):
        fixture = self.fixture
        self.success(fixture.project())
        child = '''import importlib.util,sys,os
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("held_writer", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
target = Path(sys.argv[2]); target.write_bytes(b"original\\n")
original_fd = os.open(target, os.O_WRONLY | os.O_APPEND)
exchange = module._exchange_paths
published_fd = None
calls = 0
def publish(first, second):
    global published_fd, calls
    calls += 1
    if sys.argv[3] == "race":
        os.write(original_fd, b"concurrent consent\\n")
    exchange(first, second)
    published_fd = os.open(second, os.O_WRONLY | os.O_APPEND)
module._exchange_paths = publish
try:
    retained = module._write_repair(target, "repair\\n", expected=b"original\\n")
except OSError as error:
    assert sys.argv[3] == "race", error
    assert "recovery file remains at" in str(error), error
    retained, = target.parent.glob(".held-config.toml.recovery-*/generation-*.toml")
else:
    assert sys.argv[3] == "success"
assert calls == 1, "unsafe compensating exchange"
os.write(original_fd, b"late original save\\n"); os.close(original_fd)
os.write(published_fd, b"late published save\\n"); os.close(published_fd)
assert b"late original save" in retained.read_bytes()
assert b"late published save" in target.read_bytes()
assert retained.parent.stat().st_mode & 0o777 == 0o700
'''
        for mode in ('success', 'race'):
            with self.subTest(mode=mode):
                # Each child owns a separate runtime directory and held FDs.
                target_dir = fixture.home / ('held-' + mode)
                target_dir.mkdir()
                result = subprocess.run([sys.executable, '-B', '-c', child,
                    str(fixture.codex / 'scripts/repair-runtime-config-drift.py'),
                    str(target_dir / 'held-config.toml'), mode], env=fixture.env,
                    cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def check_consent_exchange_race(self, later_edit, replace_recovery=False):
        fixture = self.fixture
        self.success(fixture.project())
        runtime = fixture.runtime / 'config.toml'
        sentinel = fixture.home / 'recovery-sentinel.toml'
        sentinel.write_text('preserve recovery target\n')
        runtime.write_text(runtime.read_text().replace('approval_policy = "on-request"', 'approval_policy = "never"', 1))
        child = '''import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("exchange_race", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
exchange = module._exchange_paths
calls = 0
def race(first, second):
    global calls
    calls += 1
    if calls == 1:
        with Path(second).open("a") as stream:
            stream.write("\\n[hooks.state.racing]\\nenabled = true\\ntrusted_hash = 'fixture'\\n")
    exchange(first, second)
    if calls == 1 and sys.argv[3] == "replace":
        Path(first).unlink()
        Path(first).symlink_to(sys.argv[4])
    if calls == 1 and sys.argv[3] == "later":
        with Path(second).open("a") as stream:
            stream.write("\\n# later independent edit\\n")
module._exchange_paths = race
raise SystemExit(module.main(["--config-path",sys.argv[2],"--repair","--json"]))
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'), str(runtime),
            'replace' if replace_recovery else 'later' if later_edit else 'restore', str(sentinel)], env=fixture.env, cwd=fixture.repo,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        if replace_recovery:
            self.assertFalse(runtime.is_symlink())
            self.assertEqual(tomllib.loads(runtime.read_text())['approval_policy'], 'on-request')
            recovery = list(runtime.parent.glob('.config.toml.recovery-*/generation-*.toml'))
            self.assertEqual(len(recovery), 1)
            self.assertTrue(recovery[0].is_symlink())
            self.assertEqual(sentinel.read_text(), 'preserve recovery target\n')
        elif later_edit:
            self.assertIn('# later independent edit', runtime.read_text())
            recovery = list(runtime.parent.glob('.config.toml.recovery-*/generation-*.toml'))
            self.assertEqual(len(recovery), 1)
            self.assertTrue(tomllib.loads(recovery[0].read_text())['hooks']['state']['racing']['enabled'])
        else:
            self.assertEqual(tomllib.loads(runtime.read_text())['approval_policy'], 'on-request')
            recovery = list(runtime.parent.glob('.config.toml.recovery-*/generation-*.toml'))
            self.assertEqual(len(recovery), 1)
            self.assertTrue(tomllib.loads(recovery[0].read_text())['hooks']['state']['racing']['enabled'])
        self.assertIn('recovery file remains at', result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(Path(payload['retained_generation_path']), recovery[0])

    def test_consent_saved_at_exchange_is_retained_for_explicit_recovery(self):
        self.check_consent_exchange_race(later_edit=False)

    def test_later_edit_preserves_live_and_displaced_consent(self):
        self.check_consent_exchange_race(later_edit=True)

    def test_replaced_recovery_source_is_not_restored_to_live_config(self):
        self.check_consent_exchange_race(later_edit=False, replace_recovery=True)

    def test_exchange_failure_keeps_last_runtime_and_backup(self):
        fixture = self.fixture
        self.success(fixture.project())
        runtime = fixture.runtime / 'config.toml'
        previous = runtime.read_text().replace('approval_policy = "on-request"', 'approval_policy = "never"', 1)
        runtime.write_text(previous)
        child = '''import importlib.util,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("fault_repair", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
def fail(*args):
    raise OSError("injected exchange failure")
module._exchange_paths = fail
raise SystemExit(module.main(["--config-path",sys.argv[2],"--repair","--json"]))
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/repair-runtime-config-drift.py'), str(runtime)],
            env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['reason'], 'config_write_failed')
        self.assertEqual(runtime.read_bytes(), previous.encode())
        backup = Path(payload['backup_path'])
        self.assertTrue(backup.is_relative_to(fixture.home))
        self.assertEqual(backup.read_bytes(), previous.encode())

    def test_canonical_change_after_snapshot_blocks_initial_publication(self):
        fixture = self.fixture
        child = '''import importlib.util,sys
from pathlib import Path
script = Path(sys.argv[1]); sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("admission", script)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
snapshot = module.preflight(Path(sys.argv[2]))
source = script.parent.parent / "config.toml"
original = source.read_text()
assert "hooks = true" in original
source.write_text(original.replace("hooks = true", "hooks = false", 1))
module.publish_initial(snapshot)
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/admit-policy-fixture.py'), str(fixture.codex / 'projection-map.json')],
            env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((fixture.runtime / 'config.toml').exists())
