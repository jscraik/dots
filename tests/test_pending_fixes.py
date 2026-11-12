"""Check reconciled public fixes through real disposable operator paths."""
import json
import re
import unittest

from helper_fixture import HelperFixture


class PendingFixTests(unittest.TestCase):
    def setUp(self):
        self.fixture = HelperFixture(self)
        self.addCleanup(self.fixture.assert_preserved, self)

    def test_original_hook_regressions_with_supported_denial(self):
        result = self.fixture.accepted_tests('test_pending_hook_findings.py', timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('skipped=', result.stderr)
        cases = re.findall(r'^test_\w+ \(([^)]+)\)', result.stderr, re.MULTILINE)
        self.assertTrue(cases, 'The maintained loader executed no named regressions')
        self.assertEqual(len(cases), len(set(cases)), 'A source suite was collected twice')

    def test_unsupported_handler_ask_is_denied(self):
        handler = self.fixture.codex / 'hooks/pr-readiness-guard.sh'
        response = json.dumps({'hookSpecificOutput': {'permissionDecision': 'ask'}})
        handler.write_text("#!/bin/sh\nprintf '%s\\n' '" + response + "'\n")
        result = self.fixture.run('pre-tool-use-dispatch.sh',
            {'tool_input': {'command': 'gh pr create --base main'}})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertIn('unsupported ask decision', output['permissionDecisionReason'])

    def test_direct_syntax_does_not_grant_execution_authority(self):
        candidate = self.fixture.home / 'unadmitted candidate'
        for relative, command in (
            ('scripts/validate-codestyle.sh', 'bash scripts/validate-codestyle.sh'),
            ('codex/scripts/verify-work.sh', 'bash codex/scripts/verify-work.sh --fast'),
            ('scripts/verify-work.sh', 'bash scripts/verify-work.sh --fast --all'),
        ):
            with self.subTest(command=command):
                path = candidate / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#!/bin/sh\ntouch SHOULD_NOT_RUN\nexit 97\n')
                result = self.fixture.run('pre-tool-use-dispatch.sh',
                    {'cwd': str(candidate), 'tool_input': {'command': command}})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                reason = json.loads(result.stdout)['hookSpecificOutput']['permissionDecisionReason']
                self.assertIn('not admitted', reason)
                self.assertIn('Direct syntax alone does not grant execution authority', reason)
                self.assertNotIn('Run the command directly so its policy handler', reason)
                self.assertFalse((candidate / 'SHOULD_NOT_RUN').exists())

    def test_reconciled_review_evidence_suites(self):
        # The maintained loader includes native Codex and structured CodeRabbit
        # cases once. Do not load those suites independently here as well.
        result = self.fixture.accepted_tests('test_pr_readiness.py', timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('skipped=', result.stderr)
        cases = re.findall(r'^test_\w+ \(([^)]+)\)', result.stderr, re.MULTILINE)
        self.assertTrue(cases, 'The maintained loader executed no named regressions')
        self.assertEqual(len(cases), len(set(cases)), 'A source suite was collected twice')
