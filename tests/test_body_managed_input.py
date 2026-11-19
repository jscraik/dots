"""Prove installed body-helper inputs in a real disposable managed worktree."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from unittest import mock
import test_installation_route as installation_tests


class ManagedBodyInputTests(unittest.TestCase):
    def test_installed_body_template_and_identity_in_managed_worktree(self):
        original_tempdir = tempfile.tempdir
        installation = installation_tests.InstallationRouteTests()
        self.addCleanup(installation.doCleanups)
        installation.setUp()
        root = installation.runtime / 'worktrees/body-helper/project'
        root.parent.mkdir(parents=True)
        project = installation.home / 'dev/agent-skills'
        for args in (['init', '-q', str(project)],
                     ['-C', str(project), '-c', 'user.name=Fixture', '-c',
                      'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
                      'commit', '--allow-empty', '-qm', 'fixture'],
                     ['-C', str(project), 'worktree', 'add', '--detach', '-q', str(root), 'HEAD']):
            subprocess.run(['git', *args], env=installation.env, check=True,
                           capture_output=True, timeout=20)
        (root / '.github').mkdir()
        template = root / '.github/PULL_REQUEST_TEMPLATE.md'
        template.write_text('## Problem\n\n- Summary:\n\n## Testing\n\n- Evidence:\n')
        body = root / 'body.md'
        body.write_text('## Problem\n\n- Summary: contained input\n\n## Testing\n\n- Evidence: fixture\n- Command: `python3 -m unittest` -> pass\n')
        digest = installation.success(installation.prepare())['plan_digest']
        installation.success(installation.operation('apply', digest))
        path = installation.runtime / 'scripts/pr-body-refresh.py'
        spec = importlib.util.spec_from_file_location('installed_body_input', path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        receipt = {'status': 'pass', 'lanes': {'pull_request': {'details': {'number': 1}}}}
        with (mock.patch.dict(os.environ, installation.installed_env(), clear=True),
              mock.patch.object(tempfile, 'tempdir', installation.env['TMPDIR']),
              mock.patch.object(helper, 'receipt_for_current_pr', return_value=receipt),
              mock.patch.object(helper, 'current_repository_slug', return_value='fixture/project') as slug,
              mock.patch.object(helper, 'run_command') as hosted):
            args = helper.parse_args(['--repo-root', str(root), '--body-file', str(body),
                                      '--repo', 'fixture/project', '--pr', '1', '--dry-run'])
            result = helper.execute(args)
            self.assertEqual(result['action'], 'dry_run')
            self.assertEqual(result['template_sections'], ['Problem', 'Testing'])
            outside = installation.home / 'outside-body.md'
            outside.write_text('must not be admitted')
            alias = root / 'alias.md'
            alias.symlink_to(body)
            for invalid in (outside, alias):
                args.body_file = invalid
                with self.subTest(path=invalid.name), self.assertRaises(helper.RefreshBlocked):
                    helper.execute(args)
            args.body_file = body
            saved_template = template.read_bytes()
            template.unlink()
            template.symlink_to(outside)
            with self.assertRaises(helper.RefreshBlocked):
                helper.execute(args)
            template.unlink()
            template.write_bytes(saved_template)
            marker = root / '.git'
            original = marker.read_bytes()
            def replace_identity(_root):
                marker.write_text('gitdir: /unselected/.git/worktrees/other\n')
                return 'fixture/project'
            slug.side_effect = replace_identity
            with self.assertRaises(ValueError):
                helper.execute(args)
            marker.write_bytes(original)
            hosted.assert_not_called()
        installation.fixture.assert_preserved(self)
        installation.doCleanups()
        self.assertEqual(tempfile.tempdir, original_tempdir)
