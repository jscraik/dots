"""Exercise toolchain archive containment without privileged installation."""
import importlib.util
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hook_toolchain_prepare", ROOT / "codex/scripts/prepare-hook-toolchain.py")
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class HookToolchainTests(unittest.TestCase):
    def test_runtime_probes_cannot_add_cli_state_to_payload(self):
        spec = importlib.util.spec_from_file_location('runtime_probe_installer', ROOT / 'codex/scripts/install-hook-toolchain.py')
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            outer = Path(directory)
            payload = outer / 'payload'
            (payload / 'bin').mkdir(parents=True)
            receipt = outer / 'probe-homes.txt'
            script = ('#!/usr/bin/python3\nimport os,pathlib\n'
                + 'home=pathlib.Path(os.environ["HOME"])\n'
                + 'assert home == pathlib.Path.cwd() and home != pathlib.Path(' + repr(str(payload)) + ')\n'
                + 'assert "PYTHONPATH" not in os.environ and "GITHUB_TOKEN" not in os.environ\n'
                + 'state=pathlib.Path(os.environ["XDG_STATE_HOME"])/"gh"; state.mkdir(parents=True,exist_ok=True)\n'
                + '(state/"device-id").write_text("fixture")\n'
                + 'with open(' + repr(str(receipt)) + ',"a") as stream: stream.write(str(home)+"\\n")\n')
            for name in ('python3', 'jq', 'gh', 'bun'):
                path = payload / 'bin' / name
                path.write_text(script)
                path.chmod(0o700)
            before = publisher.inventory(payload)
            with mock.patch.dict(os.environ, {'PYTHONPATH': str(outer), 'GITHUB_TOKEN': 'fixture-only'}):
                publisher.check_runtime(payload)
            self.assertEqual(publisher.inventory(payload), before)
            homes = receipt.read_text().splitlines()
            self.assertEqual(len(homes), 4)
            self.assertTrue(all(not Path(home).exists() for home in homes))
            # Optional providers participate in the same immutable inventory.
            identity = publisher.digest(before)
            (payload / 'bin/bun').write_text('#!/bin/sh\nexit 0\n')
            self.assertNotEqual(publisher.digest(publisher.inventory(payload)), identity)

    def test_runtime_selection_must_match_packaged_binding(self):
        spec = importlib.util.spec_from_file_location('runtime_selection', ROOT / 'codex/scripts/validate-hook-toolchain.py')
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            root = Path(directory)
            scripts = root / 'scripts'
            scripts.mkdir()
            (root / '.dots-package.json').write_text('{}')
            selected = Path('/opt/dots-hook-tools') / ('a' * 64) / 'bin'
            metadata = scripts / '.hook-toolchain.json'
            with mock.patch.object(validator, '__file__', str(scripts / 'validate-hook-toolchain.py')), \
                    mock.patch.object(validator, 'resolve', return_value=selected):
                with self.assertRaisesRegex(ValueError, 'binding is missing'):
                    validator.runtime_resolve()
                metadata.write_text(json.dumps({'schema_version': 1, 'bin_dir': str(selected),
                    'payload_sha256': 'a' * 64}))
                self.assertEqual(validator.runtime_resolve(), selected)
                with mock.patch.object(validator, 'resolve', return_value=selected.parent.parent / ('b' * 64) / 'bin'):
                    with self.assertRaisesRegex(ValueError, 'differs from the sealed'):
                        validator.runtime_resolve()
                metadata.write_text('[]')
                with self.assertRaisesRegex(ValueError, 'differs from the sealed'):
                    validator.runtime_resolve()

    def test_admin_prefix_creation_ignores_restrictive_umask(self):
        spec = importlib.util.spec_from_file_location('prefix_installer', ROOT / 'codex/scripts/install-hook-toolchain.py')
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            prefix = Path(directory) / 'new-parent/tools'
            original_lstat = Path.lstat
            def admin_info(path):
                info = original_lstat(path)
                return SimpleNamespace(st_uid=0, st_mode=info.st_mode & ~0o022)
            previous = os.umask(0o077)
            try:
                with mock.patch.object(publisher, 'PREFIX', prefix), mock.patch.object(Path, 'lstat', admin_info):
                    publisher.ensure_prefix()
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(prefix.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(prefix.parent.stat().st_mode), 0o755)

    def test_installer_child_ignores_user_site_environment_and_working_directory(self):
        spec = importlib.util.spec_from_file_location('isolated_child_installer', ROOT / 'codex/scripts/install-codex.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory)
            marker = home / 'untrusted-startup-ran'
            poison = 'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()\n'
            site = home / '.local/lib' / ('python' + '.'.join(map(str, sys.version_info[:2]))) / 'site-packages'
            site.mkdir(parents=True)
            (site / 'usercustomize.py').write_text(poison)
            (home / 'sitecustomize.py').write_text(poison)
            (home / 'json.py').write_text(poison + 'raise RuntimeError("cwd module loaded")\n')
            script = home / 'probe.py'
            script.write_text('import json,sys; print(json.dumps({"isolated":sys.flags.isolated,"ok":True}))\n')
            with mock.patch.object(installer, 'protected_python_executable', return_value=sys.executable):
                environment = installer.clean_environment(home, home)
                environment['PYTHONPATH'] = str(home)
                result = subprocess.run(installer.protected_python_command(script),
                    env=environment, cwd=home, capture_output=True, text=True, timeout=15, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'isolated': 1, 'ok': True})
            self.assertFalse(marker.exists())

    def test_isolated_installer_loads_admission_and_repair_siblings(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory)
            (home / 'tmp').mkdir()
            marker = home / 'untrusted-sibling-ran'
            source = home / 'source'
            scripts = source / 'codex/scripts'
            scripts.mkdir(parents=True)
            for name in ('install-codex.py', 'migration_scope.py', 'deployment_scope.py',
                         'admit-policy-fixture.py', 'admit-hook-fixture.py',
                         'repair-runtime-config-drift.py', 'desktop_compatibility.py'):
                shutil.copyfile(ROOT / 'codex/scripts' / name, scripts / name)
            (home / 'migration_scope.py').write_text('from pathlib import Path; Path('
                + repr(str(marker)) + ').touch(); raise RuntimeError("cwd scope loaded")\n')
            program = home / 'probe.py'
            program.write_text('import importlib.util, pathlib, sys\n'
                + 'root = pathlib.Path(' + repr(str(source)) + ')\n'
                + 'spec = importlib.util.spec_from_file_location("installer", root / "codex/scripts/install-codex.py")\n'
                + 'installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)\n'
                + 'for name in ("admit-policy-fixture.py", "repair-runtime-config-drift.py"):\n'
                + '    installer.module("isolated_" + name, root / "codex/scripts" / name)\n'
                + 'assert "migration_scope" not in sys.modules\n'
                + 'print("isolated siblings loaded")\n')
            result = subprocess.run([sys.executable, '-I', '-B', str(program)],
                env={'HOME': str(home), 'DOTS_TEST_HOME': str(home), 'TMPDIR': str(home / 'tmp'),
                     'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(home)}, cwd=home,
                capture_output=True, text=True, timeout=15, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'isolated siblings loaded')
            self.assertFalse(marker.exists())

    def test_projection_rejects_unadmitted_home_before_fixture_interpreter(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            root = Path(directory)
            marker = root / 'untrusted-interpreter-ran'
            interpreter = root / 'python'
            interpreter.write_text('#!/bin/sh\n/usr/bin/touch "' + str(marker) + '"\nexit 75\n')
            interpreter.chmod(0o700)
            result = subprocess.run(['/bin/bash', '-p', str(ROOT / 'scripts/link-configs.sh'), '--check'],
                cwd=ROOT, env={'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()),
                    'DOTS_PROJECTION_FIXTURE': 'full-policy-v1', 'CODEX_VALIDATION_PYTHON': str(interpreter)},
                capture_output=True, text=True, timeout=15, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('disposable', result.stderr)
            self.assertFalse(marker.exists())

    def test_machine_bootstrap_never_executes_writable_python_candidates(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory)
            scripts = home / 'codex/scripts'
            scripts.mkdir(parents=True)
            for name in ('codex-validation-lib.sh', 'admit-hook-fixture.py', 'migration_scope.py',
                         'deployment_scope.py', 'validate-hook-toolchain.py', 'install-hook-toolchain.py'):
                shutil.copyfile(ROOT / 'codex/scripts' / name, scripts / name)
            (scripts.parent / '.deployment.json').write_text('{}')
            binaries = home / '.venvs/pyyaml/bin'
            binaries.mkdir(parents=True)
            marker = home / 'untrusted-python-ran'
            for name in ('python', 'python3', 'dirname'):
                path = binaries / name
                path.write_text('#!/bin/sh\n/usr/bin/touch "' + str(marker) + '"\nexit 75\n')
                path.chmod(0o700)
            result = subprocess.run(['/bin/bash', '-p', '-c', '. "$1"', 'bootstrap-probe',
                                     str(scripts / 'codex-validation-lib.sh')],
                                    env={'HOME': str(home), 'PATH': str(binaries) + ':/usr/bin:/bin',
                                         'CODEX_VALIDATION_PYTHON': str(binaries / 'python')},
                                    capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_installer_binds_toolchain_before_apply_or_check_writes(self):
        spec = importlib.util.spec_from_file_location('toolchain_binding_installer', ROOT / 'codex/scripts/install-codex.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        expected = {'schema_version': 1, 'bin_dir': '/opt/dots-hook-tools/' + 'a' * 64 + '/bin',
                    'payload_sha256': 'a' * 64}
        changed = {**expected, 'bin_dir': '/opt/dots-hook-tools/' + 'b' * 64 + '/bin',
                   'payload_sha256': 'b' * 64}
        with mock.patch.object(installer.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(expected), stderr='')) as run:
            self.assertEqual(installer.hook_toolchain_snapshot(), expected)
            self.assertIn('--identity', run.call_args.args[0])
        with mock.patch.object(installer, 'hook_toolchain_snapshot', return_value=expected):
            installer.verify_hook_toolchain({'hook_toolchain': expected})
            with mock.patch.object(sys, 'executable', '/tmp/replaced-venv/python'), \
                    mock.patch.dict(os.environ, {'PATH': '/tmp/poison-tools', 'PYTHONPATH': '/tmp/poison-modules'}):
                environment = installer.clean_environment(Path('/tmp/home'), Path('/tmp/payload'))
                self.assertEqual(environment['CODEX_VALIDATION_PYTHON'], expected['bin_dir'] + '/python3')
                self.assertEqual(environment['PATH'], expected['bin_dir'] + ':/usr/bin:/bin:/usr/sbin:/sbin')
                self.assertNotIn('PYTHONPATH', environment)
        for plan in ({'hook_toolchain': expected}, {}):
            with mock.patch.object(installer, 'load_plan', return_value=plan), \
                    mock.patch.object(installer, 'hook_toolchain_snapshot', return_value=changed), \
                    mock.patch.object(installer, 'installation_lock', side_effect=AssertionError('write boundary reached')), \
                    mock.patch.object(installer, 'load_result', side_effect=AssertionError('check continued')):
                for operation in (installer.apply, installer.check):
                    with self.subTest(operation=operation.__name__, bound=bool(plan)), \
                            self.assertRaisesRegex(ValueError, 'toolchain changed or was not bound'):
                        operation(Path('/unused'), 'unused')

    def test_source_dispatch_rejects_changed_toolchain_before_child_start(self):
        spec = importlib.util.spec_from_file_location('prelaunch_binding_installer', ROOT / 'codex/scripts/install-codex.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        expected = {'schema_version': 1, 'bin_dir': '/opt/dots-hook-tools/' + 'a' * 64 + '/bin',
                    'payload_sha256': 'a' * 64}
        changed = {**expected, 'bin_dir': '/opt/dots-hook-tools/' + 'b' * 64 + '/bin',
                   'payload_sha256': 'b' * 64}
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory)
            state = home / 'state'
            scripts = state / 'payload/codex/scripts'
            scripts.mkdir(parents=True)
            (scripts / '.hook-toolchain.json').write_text(json.dumps(expected))
            frozen = {'revision': 'a' * 40}
            (state / 'origin.json').write_text(json.dumps(frozen))
            marker = {'home': str(home), 'state_dir': str(state), 'before': {},
                      'package_digest': installer.SCOPE.identity(installer.SCOPE.fingerprint(state / 'payload'))}
            plan = {'schema_version': 1, 'home': str(home), 'before': {}, 'expected': {},
                    'package_digest': marker['package_digest'], 'hook_toolchain': expected}
            raw_plan = json.dumps(plan).encode()
            (state / 'plan.json').write_bytes(raw_plan)
            args = SimpleNamespace(state_dir=state, previous_desktop_review_sha256=None,
                desktop_review_sha256=None, bindings_sha256=None, previous_plan_digest=None,
                previous_package_digest=None, previous_marker_sha256=None,
                previous_expected_config_sha256=None, previous_observed_config_sha256=None,
                usage_directory_repair=None, plan_digest=hashlib.sha256(raw_plan).hexdigest())
            with (mock.patch.object(installer.SCOPE, 'physical', side_effect=lambda path: path),
                  mock.patch.object(installer, 'source_candidate', return_value=frozen),
                  mock.patch.object(installer, 'verified_public_payload', return_value=marker),
                  mock.patch.object(installer, 'hook_toolchain_snapshot', return_value=changed),
                  mock.patch.object(installer.subprocess, 'run', side_effect=AssertionError('child started'))):
                for operation in ('apply', 'check'):
                    args.operation = operation
                    with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'toolchain changed'):
                        installer.dispatch(args)
            # A matching selection reaches the legitimate child; an admin
            # selection change between environment and command construction
            # must still stop before spawn. Rollback retains its recovery path.
            with (mock.patch.object(installer.SCOPE, 'physical', side_effect=lambda path: path),
                  mock.patch.object(installer, 'source_candidate', return_value=frozen),
                  mock.patch.object(installer, 'verified_public_payload', return_value=marker)):
                for operation in ('apply', 'check', 'rollback'):
                    args.operation = operation
                    selected = changed if operation == 'rollback' else expected
                    with (mock.patch.object(installer, 'hook_toolchain_snapshot', return_value=selected),
                          mock.patch.object(installer.subprocess, 'run', return_value=SimpleNamespace(
                              returncode=0, stdout='{"ok": true}', stderr='')) as child):
                        self.assertEqual(installer.dispatch(args), {'ok': True})
                        self.assertEqual(child.call_args.args[0][0], selected['bin_dir'] + '/python3')
                        self.assertEqual(child.call_args.kwargs['env']['CODEX_VALIDATION_PYTHON'],
                                         selected['bin_dir'] + '/python3')
                args.operation = 'apply'
                with (mock.patch.object(installer, 'hook_toolchain_snapshot', side_effect=[expected, changed]),
                      mock.patch.object(installer.subprocess, 'run', side_effect=AssertionError('child started')),
                      self.assertRaisesRegex(ValueError, 'toolchain changed')):
                    installer.dispatch(args)
                for replaced in (changed, None):
                    (scripts / '.hook-toolchain.json').write_text(json.dumps(replaced))
                    with (mock.patch.object(installer, 'hook_toolchain_snapshot', return_value=changed),
                          mock.patch.object(installer.subprocess, 'run', side_effect=AssertionError('child started')),
                          self.subTest(tampered_binding=replaced),
                          self.assertRaisesRegex(ValueError, 'toolchain|package')):
                        installer.dispatch(args)

    def test_plan_retains_exact_toolchain_binding_and_legacy_readability(self):
        spec = importlib.util.spec_from_file_location('toolchain_plan_installer', ROOT / 'codex/scripts/install-codex.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            state = Path(directory)
            payload = state / 'payload'
            (payload / 'codex/scripts').mkdir(parents=True)
            snapshot = {'schema_version': 1, 'bin_dir': '/opt/dots-hook-tools/' + 'a' * 64 + '/bin',
                        'payload_sha256': 'a' * 64}
            metadata = payload / 'codex/scripts/.hook-toolchain.json'
            metadata.write_text(json.dumps(snapshot))
            context = {'state_dir': str(state), 'home': str(state / 'home'), 'before': {}, 'package_digest': 'a' * 64}
            plan = {'schema_version': 1, 'home': context['home'], 'before': {}, 'expected': {},
                    'package_digest': context['package_digest'], 'hook_toolchain': snapshot}
            def store(value):
                raw = json.dumps(value).encode()
                (state / 'plan.json').write_bytes(raw)
                return installer.hashlib.sha256(raw).hexdigest()
            with mock.patch.object(installer, 'ROOT', payload):
                digest = store(plan)
                self.assertEqual(installer.load_plan(state, digest, verified_context=context), plan)
                metadata.write_text(json.dumps({**snapshot, 'payload_sha256': 'b' * 64}))
                with self.assertRaisesRegex(ValueError, 'packaged hook toolchain identity disagree'):
                    installer.load_plan(state, digest, verified_context=context)
                legacy = {name: value for name, value in plan.items() if name != 'hook_toolchain'}
                self.assertEqual(installer.load_plan(state, store(legacy), verified_context=context), legacy)

    def test_toolchain_identity_detects_payload_edits_and_selection_changes(self):
        def load(name):
            spec = importlib.util.spec_from_file_location(name, ROOT / ('codex/scripts/' + name + '.py'))
            result = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(result)
            return result
        validator = load('validate-hook-toolchain')
        publisher = load('install-hook-toolchain')
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            prefix = Path(directory)
            payload = prefix / 'staging'
            (payload / 'bin').mkdir(parents=True)
            for name in ('python3', 'jq', 'gh'):
                path = payload / 'bin' / name
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o700)
            digest = publisher.digest(publisher.inventory(payload))
            payload = payload.rename(prefix / digest)
            (prefix / 'current').symlink_to(payload.name)
            def protected(path):
                return path.lstat()
            with mock.patch.object(validator, 'PREFIX', prefix), mock.patch.object(validator, 'protected', side_effect=protected):
                identity = validator.identity()
                self.assertEqual(identity['payload_sha256'], digest)
                (payload / 'bin/jq').write_text('#!/bin/sh\nexit 1\n')
                with self.assertRaisesRegex(ValueError, 'contents or selection changed'):
                    validator.identity()
                changed_digest = publisher.digest(publisher.inventory(payload))
                replacement = payload.rename(prefix / changed_digest)
                (prefix / 'current').unlink()
                (prefix / 'current').symlink_to(replacement.name)
                self.assertNotEqual(validator.identity(), identity)

    def test_aikido_provider_requires_versioned_content_binding(self):
        def load(name):
            spec = importlib.util.spec_from_file_location(name, ROOT / ('codex/scripts/' + name + '.py'))
            result = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(result)
            return result
        validator = load('validate-hook-toolchain')
        publisher = load('install-hook-toolchain')
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            prefix = Path(directory)
            payload = prefix / 'staging'
            (payload / 'bin').mkdir(parents=True)
            for name in ('python3', 'jq', 'gh', 'aikido-mcp'):
                path = payload / 'bin' / name
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o700)
            receipt = payload / 'providers/aikido-mcp.json'
            receipt.parent.mkdir()
            executable = payload / 'bin/aikido-mcp'
            record = {'schema_version': 1, 'package': '@aikidosec/mcp', 'version': '1.0.10',
                      'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
            receipt.write_text(json.dumps(record))
            self.assertEqual(publisher.aikido_provider(payload), executable)
            receipt.write_text(json.dumps(record | {'version': '1.0.9'}))
            with self.assertRaisesRegex(ValueError, 'wrong version'):
                publisher.aikido_provider(payload)
            receipt.write_text(json.dumps(record))
            digest = publisher.digest(publisher.inventory(payload))
            payload = payload.rename(prefix / digest)
            (prefix / 'current').symlink_to(payload.name)
            with mock.patch.object(validator, 'PREFIX', prefix), \
                    mock.patch.object(validator, 'protected', side_effect=lambda path: path.lstat()):
                self.assertEqual(validator.runtime_aikido(), payload / 'bin/aikido-mcp')
                (payload / 'bin/aikido-mcp').write_text('#!/bin/sh\nexit 1\n')
                with self.assertRaisesRegex(ValueError, 'contents or selection changed'):
                    validator.runtime_aikido()

    def test_missing_toolchain_blocks_policy_and_stop_retry_terminates(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            root = Path(directory)
            hooks, scripts = root / 'hooks', root / 'scripts'
            hooks.mkdir()
            scripts.mkdir()
            blocking = ('pre-tool-use-dispatch.sh', 'stop-guard.sh',
                'pre-tool-use-guard.sh', 'permission-request-guard.sh',
                'pr-readiness-guard.sh', 'pre-commit-tests.sh',
                'pre-scaffold-typecheck.sh', 'user-prompt-submit.sh')
            for name in ('hook-runtime-path.sh', 'subagent-stop.sh', *blocking):
                shutil.copyfile(ROOT / 'codex/hooks' / name, hooks / name)
            (scripts / 'validate-hook-toolchain.py').write_text('raise SystemExit("synthetic missing payload")\n')
            environment = {'PATH': '/usr/bin:/bin', 'HOME': str(root)}
            for name in blocking:
                with self.subTest(name=name):
                    blocked = subprocess.run(['/bin/bash', '-p', str(hooks / name)],
                        input='{}', env=environment, capture_output=True, text=True, timeout=10, check=False)
                    self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
                    self.assertTrue(blocked.stderr.strip(), 'Exit 2 needs a blocking reason')
            repeated = subprocess.run(['/bin/bash', '-p', str(hooks / 'stop-guard.sh')],
                input='{"stop_hook_active":true}', env=environment,
                capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertEqual(json.loads(repeated.stdout), {'continue': True})
            stopped = subprocess.run(['/bin/bash', '-p', str(hooks / 'subagent-stop.sh')],
                input='{}', env=environment, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(stopped.returncode, 1, stopped.stdout + stopped.stderr)
            self.assertTrue(stopped.stderr.strip())
            nested = subprocess.run(['/bin/bash', '-p', str(hooks / 'stop-guard.sh')],
                input='{"nested":' + '[' * 1500 + '0' + ']' * 1500 + '}',
                env=environment, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(nested.returncode, 2, nested.stdout + nested.stderr)
            self.assertTrue(nested.stderr.strip())

    def test_validation_selector_isolates_modules_and_rejects_writable_fallback(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory).resolve()
            scripts = home / "dev/dots/codex/scripts"
            scripts.mkdir(parents=True)
            for name in ("codex-validation-lib.sh", "admit-hook-fixture.py", "migration_scope.py"):
                shutil.copyfile(ROOT / "codex/scripts" / name, scripts / name)
            temporary = home / "tmp"
            temporary.mkdir()
            workspace = home / "workspace"
            workspace.mkdir()
            marker = home / "poisoned"
            poison = '#!/bin/sh\nprintf poisoned >> "' + str(marker) + '"\nexit 97\n'
            binary_dir = home / ".venvs/pyyaml/bin"
            binary_dir.mkdir(parents=True)
            for name in ("python", "uv"):
                path = binary_dir / name
                path.write_text(poison)
                path.chmod(0o755)
            for name in ("tomllib", "yaml"):
                (workspace / (name + ".py")).write_text(
                    'open(' + repr(str(marker)) + ', "w").write("poisoned")\nraise RuntimeError("poison")\n')
            environment = {
                "HOME": str(home), "DOTS_TEST_HOME": str(home), "TMPDIR": str(temporary),
                "PATH": os.pathsep.join((str(Path(sys.executable).parent), str(binary_dir), "/usr/bin", "/bin")),
                "CODEX_VALIDATION_PYTHON": sys.executable,
            }
            command = ["/bin/bash", "-c", '. "$1" && codex_select_validation_python fixture',
                       "fixture", str(scripts / "codex-validation-lib.sh")]
            valid = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                   text=True, timeout=15, check=False)
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            self.assertEqual(valid.stdout.strip(), sys.executable)
            # A missing protected selection must fail instead of trying HOME,
            # PATH Python, mise or the uv fallback, even if those would work.
            environment["CODEX_VALIDATION_PYTHON"] = "/opt/dots-hook-tools/" + "0" * 64 + "/bin/python3"
            missing = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                     text=True, timeout=15, check=False)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("no Python", missing.stderr)
            self.assertFalse(marker.exists())

    def test_bootstrap_failure_blocks_first_events_but_stop_retry_terminates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = root / 'hooks'
            scripts = root / 'scripts'
            hooks.mkdir()
            scripts.mkdir()
            for name in ('stop-guard.sh', 'pre-tool-use-dispatch.sh', 'hook-runtime-path.sh'):
                shutil.copyfile(ROOT / 'codex/hooks' / name, hooks / name)
            (scripts / 'validate-hook-toolchain.py').write_text('raise SystemExit(1)\n')
            marker = root / 'unexpected-guard-access'
            (scripts / 'admit-hook-fixture.py').write_text(
                f'open({str(marker)!r}, "w").write("called")\n')
            for hook in ('stop-guard.sh', 'pre-tool-use-dispatch.sh'):
                for command in ('git status --short', 'git commit --no-verify -m bad'):
                    with self.subTest(hook=hook, command=command):
                        result = subprocess.run(['/bin/bash', str(hooks / hook)],
                            input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}}),
                            text=True, capture_output=True, check=False, timeout=10)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            result = subprocess.run(['/bin/bash', str(hooks / 'stop-guard.sh')],
                input='{"stop_hook_active":true}', text=True, capture_output=True,
                check=False, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {'continue': True})
            self.assertFalse(marker.exists())

    def test_stop_blocks_when_library_bootstrap_revalidation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks, scripts, binary = (root / name for name in ('hooks', 'scripts', 'bin'))
            for path in (hooks, scripts, binary):
                path.mkdir()
            for name in ('stop-guard.sh', 'hook-runtime-lib.sh', 'hook-runtime-path.sh'):
                shutil.copyfile(ROOT / 'codex/hooks' / name, hooks / name)
            (binary / 'python3').symlink_to(sys.executable)
            (scripts / 'admit-hook-fixture.py').write_text('')
            marker = root / 'validated-once'
            (scripts / 'validate-hook-toolchain.py').write_text(
                'from pathlib import Path\n'
                f'marker = Path({str(marker)!r})\n'
                'if marker.exists(): raise SystemExit(1)\n'
                'marker.touch()\n'
                f'print({str(binary)!r})\n')
            result = subprocess.run(['/bin/bash', str(hooks / 'stop-guard.sh')],
                input='{}', text=True, capture_output=True, check=False, timeout=10)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertTrue(marker.exists())

    def test_launchers_stop_before_python_when_bootstrap_fails(self):
        with tempfile.TemporaryDirectory(dir=Path('/tmp').resolve()) as directory:
            home = Path(directory)
            hooks = home / 'hooks'
            scripts = home / 'scripts'
            hooks.mkdir()
            scripts.mkdir()
            (hooks / 'hook-runtime-path.sh').write_text('return 7\n')
            marker = home / 'python-invoked'
            (scripts / 'admit-hook-fixture.py').write_text(
                f'open({str(marker)!r}, "w").write("unexpected")\n')
            for name in ('lifeos-codex.sh', 'hook-runtime-lib.sh', 'post-tool-use-review.sh'):
                shutil.copyfile(ROOT / 'codex/hooks' / name, hooks / name)
                command = ['/bin/bash', '-p', str(hooks / name)]
                if name == 'hook-runtime-lib.sh':
                    command = ['/bin/bash', '-p', '-c', '. "$1"', 'fixture', str(hooks / name)]
                result = subprocess.run(command, input='{}', cwd=home,
                                        env={'HOME': str(home), 'PATH': '/usr/bin:/bin'},
                                        capture_output=True, text=True, timeout=10, check=False)
                if name == 'lifeos-codex.sh':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout)
                    self.assertTrue(output['continue'])
                    self.assertIn('unavailable', output['systemMessage'])
                else:
                    self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                if name != 'post-tool-use-review.sh':
                    self.assertIn('bootstrap failed (status 7)', result.stderr)
                self.assertFalse(marker.exists())

    def archive(self, directory, members):
        archive = directory / "payload.tar"
        with tarfile.open(archive, "w") as stream:
            for name, content, link in members:
                item = tarfile.TarInfo(name)
                if link is not None:
                    item.type = tarfile.SYMTYPE
                    item.linkname = link
                    stream.addfile(item)
                else:
                    item.size = len(content)
                    item.mode = 0o755
                    stream.addfile(item, io.BytesIO(content))
        return archive

    def test_internal_executable_link_retains_complete_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "output"
            payload.mkdir()
            archive = self.archive(root, [("bin/python3.12", b"fixture", None),
                                          ("bin/python3", b"", "python3.12")])
            PREPARE.extract(archive, payload)
            self.assertEqual((payload / "bin/python3").read_bytes(), b"fixture")
            self.assertTrue((payload / "bin/python3").is_symlink())

    def test_archive_traversal_and_external_links_leave_sentinel_unchanged(self):
        for members in (
            [("../sentinel", b"changed", None)],
            [("bin/python3", b"", "../../sentinel")],
            [("bin", b"", "/tmp"), ("bin/sentinel", b"changed", None)],
        ):
            with self.subTest(members=members), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                sentinel = root / "sentinel"
                sentinel.write_bytes(b"preserve")
                payload = root / "output"
                payload.mkdir()
                with self.assertRaises(ValueError):
                    PREPARE.extract(self.archive(root, members), payload)
                self.assertEqual(sentinel.read_bytes(), b"preserve")
