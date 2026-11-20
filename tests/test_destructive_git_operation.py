"""Classify review reproductions as data; never execute their shell commands."""
import subprocess
import os
import sys
import tempfile
import unittest
import contextlib
import io
import runpy
from pathlib import Path
from unittest import mock


DETECTOR = Path(__file__).resolve().parents[1] / 'codex/hooks/destructive-git-operation.py'


def seed_checkout_ref(repository, environment, branch='topic'):
    """Create inert fixture objects, without executing a commit or any hook."""
    def git(*arguments, content=None):
        return subprocess.run(['/usr/bin/git', '-C', str(repository), *arguments],
            input=content, env=environment, check=True, capture_output=True, text=True,
            timeout=10).stdout.strip()
    tree = git('hash-object', '-t', 'tree', '-w', '--stdin', content='')
    commit = git('hash-object', '-t', 'commit', '-w', '--stdin', content=(
        f'tree {tree}\nauthor Fixture <fixture@example.invalid> 1 +0000\n'
        'committer Fixture <fixture@example.invalid> 1 +0000\n\nInert test object\n'))
    git('update-ref', 'refs/heads/' + branch, commit)


class DestructiveGitOperationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path('/tmp').resolve())
        self.addCleanup(temporary.cleanup)
        self.repository = Path(temporary.name)
        self.environment = {'PATH': '/usr/bin:/bin', 'HOME': str(self.repository),
                            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        subprocess.run(['/usr/bin/git', 'init', '-q', str(self.repository)],
                       env=self.environment, check=True, capture_output=True, timeout=10)
        seed_checkout_ref(self.repository, self.environment)

    def classify(self, command, cwd=None):
        arguments = [sys.executable, '-I', '-S', str(DETECTOR), command]
        if cwd is not None:
            arguments.append(str(cwd))
        result = subprocess.run(arguments,
                                capture_output=True, text=True, timeout=5, check=False,
                                cwd=self.repository, env=self.environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_reviewed_execution_forms_do_not_clear_destructive_git(self):
        commands = (
            '2>/dev/null git reset --hard',
            '> /dev/null git reset --hard',
            'FOO+=x git reset --hard',
            'echo x |& git reset --hard',
            "printf '%s\\n' word\\ #fragment; git reset --hard",
            "bash -eo pipefail -c 'git reset --hard'",
            "bash -lo pipefail -c 'git reset --hard'",
            "bash -ec 'git reset --hard'",
            "bash --rcfile /dev/null -c 'git reset --hard'",
            "bash -c 'echo \"$(git reset --hard)\"'",
            'echo "$(echo before # )\ngit reset --hard\n)"',
            "eval 'git reset --hard'",
            'nohup git reset --hard',
            'timeout 5 git reset --hard',
            'nice git reset --hard',
            'xargs git reset --hard',
            "dash -c 'git reset --hard'",
            "ksh -c 'git reset --hard'",
            "env -S 'git reset --hard'",
            "env --split-string='git reset --hard'",
            "git config alias.nuke '!git reset --hard'; git nuke",
            "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.nuke GIT_CONFIG_VALUE_0='reset --hard'; git nuke",
            "GIT_PAGER='git reset --hard' git --paginate log",
            "git -c core.askpass='git reset --hard' status",
            "git -c core.gitproxy='git reset --hard' status",
            "git -c gpg.program='git reset --hard' log",
            "git -c diff.fixture.textconv='git reset --hard' diff",
            'git checkout .',
            'git checkout tracked.txt',
            'rm  -rf  /',
            'rm --force --recursive /',
            '2>/dev/null FOO+=x git reset --hard',
            'cat <<EOF\n$(git reset --hard)\nEOF',
            'printf %s $((1<<2))\ngit reset --hard\n2',
            '((1<<2))\ngit reset --hard\n2',
            'git >/dev/null reset --hard',
            'git -C /tmp >/dev/null reset --hard',
            'cat <<EOF\n\\\\$(git reset --hard)\nEOF',
            'builtin eval "git reset --hard"',
            'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.nuke GIT_CONFIG_VALUE_0="reset --hard"; export GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0; git nuke',
            'env -C /tmp git checkout topic',
            'env --chdir=/tmp git checkout topic',
            'sudo -D /tmp git checkout topic',
            'sudo -R /tmp git checkout topic',
            'pushd /tmp; git checkout topic',
            'popd; git checkout topic',
            'chdir /tmp; git checkout topic',
            "bash <<'EOF'\ngit reset --hard\nEOF",
            "bash < script.sh",
            'cat <<"EOF"|/bin/bash\ngit reset --hard\nEOF',
            'shopt -s expand_aliases\nalias nuke="git reset --hard"\nnuke',
            'shopt -s expand_aliases\nalias cat=bash\ncat <<"EOF"\ngit reset --hard\nEOF',
            'cat() { bash; }; cat <<"EOF"\ngit reset --hard\nEOF',
            'git checkout --quiet topic topic',
            'git checkout --ours topic',
            'git checkout -3 topic',
            'git checkout -p topic',
            'git checkout --patch topic',
            'git checkout --pat topic',
            'git checkout --recurse-submodules topic',
            'sudo -T 10 git reset --hard',
            'sudo --command-timeout=10 git reset --hard',
            'sudo -s "git reset --hard"',
            'env -C/tmp git checkout topic',
            'sudo -D/tmp git checkout topic',
            'cat <<EOF\nEO\\\nF\ngit reset --hard\nexit\nEOF',
            "printf '%s\\n' 'git reset --hard'|/bin/bash",
            "printf '%s\\n' 'git reset --hard'|command /bin/bash",
            "cat <<'EOF' > >(bash)\ngit reset --hard\nEOF\nwait",
            "NOTE='first\nsecond' git reset --hard",
            "cmd='git reset --hard'; $cmd",
            '$(printf git) reset --hard',
            'env --unknown-option value git reset --hard',
            'exec -cl git reset --hard',
            'exec -a label -c git reset --hard',
            'exec -ca label git reset --hard',
            'exec -z git reset --hard',
            "cat <<'EOF' && git reset --hard\nliteral data\nEOF",
            "cat <<'EOF' || git reset --hard\nliteral data\nEOF",
            'cd other; git checkout topic',
            'builtin cd other; git checkout topic',
            'OPTS="COLOR_VALUE -C /other-repository"; git --config-env=color.ui=$OPTS checkout topic',
            'OPTS="never -C /other-repository"; git -c color.ui=$OPTS checkout topic',
            'git -ccolor.ui=$OPTS status',
            'git -C $OPTS status',
            'coproc git reset --hard; wait',
            'coproc task { git reset --hard; }; wait',
            'find . -maxdepth 0 -exec git reset --hard \\;',
            'find . -execdir git reset --hard +',
            'find . -ok rm -rf / \\;',
            'fd --exec git reset --hard',
            'fd -X git reset --hard',
            'op=-exec; find . "$op" git reset --hard \\;',
            'find . "$(printf %s -exec)" git reset --hard \\;',
            'op=--exec; fd "$op" git reset --hard',
            'busybox find . -exec git reset --hard \\;',
            'toybox find . -exec git reset --hard \\;',
            'find . -* git reset --hard \\;',
            'fd * git reset --hard',
            'git checkout --quiet{,} --force topic',
            "cat <<$'EOF'\nEOF\ngit reset --hard\nexit\n$EOF",
            "bash -c -e 'git reset --hard'",
            "bash +B -c 'git reset --hard'",
            "bash +O extglob -c 'git reset --hard'",
            'nice -n0 git reset --hard',
            'nice -- git reset --hard',
            'caffeinate git reset --hard',
            'caffeinate -d -t1 git reset --hard',
            "unreviewed-launcher --payload 'git reset --hard'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertNotEqual(self.classify(command), 'safe')

    def test_literal_text_and_neighboring_forms_remain_safe(self):
        commands = (
            "# don't change anything\ngit status --short",
            "printf '%s\\n' bash -c 'git reset --hard'",
            "printf '%s\\n' 'then' git -C . reset --hard",
            "printf '%s\\n' 'rm -rf\n/'",
            "cat > notes.md <<'EOF'\ndon't\nEOF",
            "cat <<'EOF'\ngit reset --hard\nEOF",
            'git commit -m "$(cat <<\'EOF\'\nfix: don\'t change behavior\nEOF\n)"',
            "printf '%s\\n' $'don\\'t'",
            'git checkout -bfeature',
            'git checkout topic',
            'git -c core.fileMode status --short',
            'git commit -m\'quoted \'message',
            'git status # quoted \' comment',
            'sudo -T 10 git status --short',
            'git checkout -bnew topic',
            'cat <<EOF\nordinary data\nEOF',
            'git checkout -qb newbranch',
            'git checkout -qbfeature',
            'git checkout -qB newbranch',
            'git checkout -qb newbranch topic',
            "printf '%s' '$literal'",
            'printf %s "$(git status --short)"',
            'X=$(printf x) git status --short',
            "cat <<'EOF' && printf '%s\\n' done\nliteral data\nEOF",
            "cat <<'EOF' || printf '%s\\n' done\nliteral data\nEOF",
            "printf '%s\\n' cd; git checkout topic",
            'git checkout topic; cd other',
            'git --config-env=color.ui=DOTS_COLOUR checkout topic',
            'git --config-env color.ui=DOTS_COLOUR checkout topic',
            'exec -a git printf x',
            'exec -a rm printf x',
            'exec -a cd printf x; git checkout topic',
            'find . -maxdepth 0 -type d',
            'fd --type f notes',
            'fd -- -x',
            'fd -e=xlsx pattern',
            'fd -exlsx pattern',
            'fd -e xlsx pattern',
            'find . -name -exec',
            'busybox find . -type f',
            "fd 'foo$'",
            r"find . -regex '.*\.py$'",
            'fd "*.py"',
            r'fd foo\$',
            r'fd "\*"',
            r'find . -name "\["',
            r'fd "\?\[\]\{\}"',
            "cat <<$'EOF'\ngit reset --hard\nEOF",
            "printf '%s' '--quiet{,}'",
            "bash +B -c 'printf hello'",
            'nice -n0 git status --short',
            'caffeinate -d git status --short',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.classify(command), 'safe')

    def test_large_ordinary_argument_list_is_bounded(self):
        self.assertEqual(self.classify('printf %s ' + 'word ' * 5000), 'safe')
        self.assertEqual(self.classify('printf %s ' + 'git ' * 15000), 'safe')
        self.assertEqual(self.classify('printf %s ' + 'rm ' * 15000), 'safe')
        self.assertEqual(self.classify("cat <<'EOF'\n" + 'x' * 70000 + '\nEOF'), 'safe')

    def test_opaque_data_cannot_become_a_file_backed_shell_payload(self):
        commands = (
            "cat > /tmp/payload <<'EOF'\ngit reset --hard\nEOF\nbash /tmp/payload",
            "cat <<< 'git reset --hard' > /tmp/payload; sh /tmp/payload",
            "printf '%s\\n' 'git reset --hard' > /tmp/payload; bash /tmp/payload",
            "printf '%s\\n' 'git reset --hard' | tee /tmp/payload; bash /tmp/payload",
            "cat > /tmp/payload <<'EOF'\ngit reset --hard\nEOF\nbash -c 'sh /tmp/payload'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertNotEqual(self.classify(command), 'safe')
        for command in ('bash scripts/verify-work.sh --fast',
                        'bash -n scripts/verify-work.sh',
                        "printf '%s' '>'; bash scripts/verify-work.sh",
                        "cat > notes.md <<'EOF'\nliteral data\nEOF"):
            with self.subTest(command=command):
                self.assertEqual(self.classify(command), 'safe')

    def test_here_strings_keep_literal_data_and_inspect_expansions(self):
        for command in ('cat <<< "hello"', "cat <<< 'git reset --hard'",
                        'cat <<< "hello"; git checkout topic'):
            with self.subTest(command=command):
                self.assertEqual(self.classify(command), 'safe')
        for command in ('cat <<< "$(git reset --hard)"',
                        'bash <<< "git reset --hard"'):
            with self.subTest(command=command):
                self.assertNotEqual(self.classify(command), 'safe')

    def test_checkout_ref_is_verified_in_requested_directory(self):
        other = self.repository / 'other'
        other.mkdir()
        subprocess.run(['/usr/bin/git', 'init', '-q', str(other)], env=self.environment,
                       check=True, capture_output=True, timeout=10)
        seed_checkout_ref(other, self.environment, branch='main')
        (other / 'topic').write_text('local edits\n')
        self.assertEqual(self.classify('git checkout --quiet topic', cwd=self.repository), 'safe')
        self.assertEqual(self.classify('git checkout --quiet topic', cwd=other), 'checkout-unresolved')

    def test_remote_guess_requires_an_explicit_tracking_operand(self):
        commit = subprocess.run(['/usr/bin/git', 'rev-parse', 'topic'], cwd=self.repository,
            env=self.environment, capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        subprocess.run(['/usr/bin/git', 'update-ref', 'refs/remotes/origin/remote-topic', commit],
            cwd=self.repository, env=self.environment, check=True, timeout=10)
        self.assertEqual(self.classify('git checkout remote-topic'), 'checkout-unresolved')
        self.assertEqual(self.classify('git checkout --track origin/remote-topic'), 'safe')
        self.assertNotEqual(self.classify('git checkout --no-guess remote-topic'), 'safe')

    def test_old_git_verifies_local_refs_without_enabling_lazy_fetch(self):
        real_run, calls = subprocess.run, []

        def legacy_run(arguments, **kwargs):
            calls.append((arguments, kwargs))
            if '--no-lazy-fetch' in arguments:
                return subprocess.CompletedProcess(arguments, 129, '', 'unknown option: --no-lazy-fetch\n')
            return real_run(arguments, **kwargs)

        def classify():
            output = io.StringIO()
            with mock.patch.object(sys, 'argv', [str(DETECTOR), 'git checkout topic', str(self.repository)]), \
                    mock.patch.object(subprocess, 'run', side_effect=legacy_run), \
                    mock.patch('signal.alarm'), mock.patch('signal.signal'), \
                    contextlib.redirect_stdout(output):
                try:
                    runpy.run_path(str(DETECTOR))
                except SystemExit as stopped:
                    self.assertEqual(stopped.code, 0)
            return output.getvalue().strip()

        self.assertEqual(classify(), 'safe')
        probes = [(arguments, kwargs) for arguments, kwargs in calls if 'rev-parse' in arguments]
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0][1]['env']['GIT_ALLOW_PROTOCOL'], '')
        self.assertEqual(probes[0][1]['env']['GIT_NO_LAZY_FETCH'], '1')
        for key, value in (('remote.origin.promisor', 'true'),
                           ('remote.origin.partialclonefilter', 'blob:none'),
                           ('extensions.partialClone', 'origin')):
            with self.subTest(key=key):
                real_run(['/usr/bin/git', '-C', str(self.repository), 'config', key, value],
                         env=self.environment, check=True, capture_output=True, timeout=10)
                calls.clear()
                try:
                    self.assertEqual(classify(), 'checkout-unresolved')
                    self.assertFalse(any('rev-parse' in arguments for arguments, _kwargs in calls))
                finally:
                    real_run(['/usr/bin/git', '-C', str(self.repository), 'config', '--unset', key],
                             env=self.environment, check=True, capture_output=True, timeout=10)
