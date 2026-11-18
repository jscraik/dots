"""Classify review reproductions as data; never execute their shell commands."""
import subprocess
import os
import sys
import tempfile
import unittest
from pathlib import Path


DETECTOR = Path(__file__).resolve().parents[1] / 'codex/hooks/destructive-git-operation.py'


def seed_checkout_ref(repository, environment):
    """Create inert fixture objects, without executing a commit or any hook."""
    def git(*arguments, content=None):
        return subprocess.run(['/usr/bin/git', '-C', str(repository), *arguments],
            input=content, env=environment, check=True, capture_output=True, text=True,
            timeout=10).stdout.strip()
    tree = git('hash-object', '-t', 'tree', '-w', '--stdin', content='')
    commit = git('hash-object', '-t', 'commit', '-w', '--stdin', content=(
        f'tree {tree}\nauthor Fixture <fixture@example.invalid> 1 +0000\n'
        'committer Fixture <fixture@example.invalid> 1 +0000\n\nInert test object\n'))
    git('update-ref', 'refs/heads/topic', commit)


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

    def classify(self, command):
        result = subprocess.run([sys.executable, '-I', '-S', str(DETECTOR), command],
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
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.classify(command), 'safe')

    def test_large_ordinary_argument_list_is_bounded(self):
        self.assertEqual(self.classify('printf %s ' + 'word ' * 5000), 'safe')
        self.assertEqual(self.classify("cat <<'EOF'\n" + 'x' * 70000 + '\nEOF'), 'safe')
