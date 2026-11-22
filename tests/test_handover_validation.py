"""Exercise handover error paths in disposable homes, without real services."""

import json
import subprocess
import sys
import unittest

from helper_fixture import HelperFixture
from policy_fixture import ROOT


class HandoverValidationTests(unittest.TestCase):
    def test_scrub_lock_failure_respects_requested_output_format(self):
        fixture = self.fixture
        child = '''import contextlib,importlib.util,io,json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(sys.argv[1]).parent))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
module=load("scrub_lock_format",sys.argv[1]);home=Path(sys.argv[2])
installer=load("parent_lock",Path(sys.argv[1]).with_name("install-codex.py"))
module.deployment_module=lambda:SimpleNamespace(context=lambda:{"home":str(home)})
target=home/"missing-config.toml"
with installer.installation_lock(home):
    for use_json in (False,True):
        sys.argv=[sys.argv[1],"--config-path",str(target),"--repair"]+(["--json"] if use_json else [])
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            assert module.main()==1
        text=output.getvalue()
        if use_json:
            payload=json.loads(text)
            assert payload["reason"]=="installation_lock_unavailable"
            assert payload["path"]==str(target)
        else:
            assert text.startswith("FAIL  installation_lock_unavailable:"),text
            assert str(target) in text
assert not target.exists()
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/scrub-computer-use-config.py'), str(fixture.home)],
            env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_repair_errors_after_lock_acquisition_keep_their_cause(self):
        fixture = self.fixture
        child = '''import importlib.util,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(sys.argv[1]).parent))
spec=importlib.util.spec_from_file_location("locked_diagnostic",sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
home=Path(sys.argv[2])
deployment=SimpleNamespace(ROOT=Path(sys.argv[1]).parents[2],context=lambda:{"home":str(home)})
module.deployment_module=lambda:deployment
sys.argv=[sys.argv[1],"--config-path",str(home/"config.toml"),"--repair","--json"]
with patch.object(module,"_main_locked",side_effect=OSError("synthetic-action-failure")):
    try:
        module.main()
    except OSError as error:
        assert str(error)=="synthetic-action-failure"
    else:
        raise AssertionError("Action error was relabelled as lock unavailability")
'''
        for name in ('repair-runtime-config-drift.py', 'scrub-computer-use-config.py'):
            with self.subTest(name=name):
                result = subprocess.run([sys.executable, '-B', '-c', child,
                    str(fixture.codex / 'scripts' / name), str(fixture.home)],
                    env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')

    def setUp(self):
        self.fixture = HelperFixture(self)
        self.addCleanup(self.fixture.assert_preserved, self)

    def scrub(self, exception):
        fixture = self.fixture
        marker = fixture.home / 'parser-called'
        stub = fixture.codex / 'scripts/tomlkit.py'
        stub.write_text('from pathlib import Path\n'
                        'def parse(text):\n'
                        f'    Path({str(marker)!r}).write_text("called")\n'
                        f'    raise {exception}("synthetic-private-parser-data")\n')
        config = fixture.home / 'synthetic-scrub.toml'
        original = 'model = "keep"\nnotify = ["SkyComputerUseClient"]\n[other]\nnotify = ["keep"]\n'
        config.write_text(original)
        result = fixture.helper('scrub-computer-use-config.py', '--config-path', str(config), '--repair', '--json')
        self.assertTrue(marker.is_file(), result.stdout + result.stderr)
        return result, config, original

    def test_unexpected_parser_failure_never_rewrites_configuration(self):
        for error in ('RuntimeError', 'TypeError', 'AssertionError'):
            with self.subTest(error=error):
                result, config, original = self.scrub(error)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(config.read_text(), original)
                self.assertEqual(json.loads(result.stdout)['reason'], 'config_parser_failed')
                self.assertEqual(json.loads(result.stdout)['status'], 'blocked')
                self.assertNotIn('synthetic-private-parser-data', result.stdout + result.stderr)
                self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_expected_parser_error_retains_the_existing_bounded_fallback(self):
        result, config, _ = self.scrub('ValueError')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(config.read_text(), 'model = "keep"\n\n[other]\nnotify = ["keep"]\n')
        self.assertEqual(json.loads(result.stdout)['removed_count'], 1)

    def test_desktop_registration_scan_failure_is_bounded_and_preserves_config(self):
        fixture = self.fixture
        config = fixture.home / 'scan-failure.toml'
        original = 'model = "keep"\nnotify = ["SkyComputerUseClient"]\n'
        config.write_text(original)
        child = '''import importlib.util,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("scan_failure",sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
deployment = SimpleNamespace(ROOT=Path(sys.argv[1]).parents[2])
state = sys.argv[3]
deployment.context = lambda: {"state_dir":state,"home":state}
module.deployment_module = lambda: deployment
sys.argv=[sys.argv[1],"--config-path",sys.argv[2],"--repair","--json"]
with patch.object(module.os,"scandir",side_effect=OSError("synthetic-private-scan-data")):
    raise SystemExit(module.main())
'''
        result = subprocess.run([sys.executable, '-B', '-c', child,
            str(fixture.codex / 'scripts/scrub-computer-use-config.py'), str(config), str(fixture.home)],
            env=fixture.env, cwd=fixture.repo, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['reason'], 'desktop_registration_scan_failed')
        self.assertEqual(config.read_text(), original)
        self.assertNotIn('synthetic-private-scan-data', result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_invalid_binding_document_is_a_bounded_cli_rejection(self):
        path = self.fixture.home / 'invalid-bindings.json'
        path.write_text('[]')
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/generate-codex-policy.py'),
                                 '--bindings', str(path)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(path.read_text(), '[]')

    def test_wrong_typed_auth_configuration_remains_a_bounded_rejection(self):
        path = self.fixture.home / 'synthetic-auth.toml'
        path.write_text('[shell_environment_policy.set]\nCODEX_AUTH_ENVIRONMENT_ID = 17\n')
        result = self.fixture.helper('read-runtime-auth-environment.py', '--config', str(path))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)

    def test_wrong_typed_hook_manifests_never_replace_the_runtime(self):
        source, target = self.fixture.source, self.fixture.target
        target.write_bytes(b'caller-owned runtime sentinel')
        before = target.read_bytes()
        for value in ([], None, {'hooks': []}):
            with self.subTest(value=value):
                source.write_text(json.dumps(value))
                result = self.fixture.base.publish(source, target)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(target.read_bytes(), before)

    def test_handler_failure_metadata_stays_denied_and_hides_payloads(self):
        handler = self.fixture.codex / 'hooks/pre-tool-use-guard.sh'
        private = 'synthetic-private-handler-data'
        cases = (
            ('exit 17', 'exit status 17; stdout empty'),
            ('exit 0', 'exit status 0; stdout empty'),
            ('printf \'%s\' \'{"continue":true}\'; exit 23', 'exit status 23; stdout non-empty'),
            (f'printf \'%s\' \'{private}\'; exit 0', 'exit status 0; invalid JSON output'),
        )
        for body, detail in cases:
            with self.subTest(detail=detail):
                handler.write_text(f'#!/bin/bash\nprintf \'%s\' \'{private}\' >&2\n{body}\n')
                result = self.fixture.run('pre-tool-use-dispatch.sh', {'tool_input': {'command': 'git remote -v'}})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                output = json.loads(result.stdout)['hookSpecificOutput']
                self.assertEqual(output['permissionDecision'], 'deny')
                self.assertEqual(output['permissionDecisionReason'],
                                 f'Required policy handler failed: {handler.name} ({detail})')
                self.assertNotIn(private, result.stdout + result.stderr)
        handler.write_text('#!/bin/bash\nprintf \'%s\' \'{}\'\n')
        result = self.fixture.run('pre-tool-use-dispatch.sh', {'tool_input': {'command': 'git remote -v'}})
        self.assertEqual(json.loads(result.stdout), {})
        handler.write_text('#!/bin/bash\nprintf \'%s\' \'{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"fixture policy denial"}}\'\n')
        result = self.fixture.run('pre-tool-use-dispatch.sh', {'tool_input': {'command': 'git remote -v'}})
        self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecisionReason'],
                         'fixture policy denial')
