"""Synthetic local resources for handler and real app-server tests."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import test_governance_port as governance

ROOT = Path(__file__).resolve().parents[1]


class HookFixture:
    def __init__(self, testcase):
        self.base = governance.GovernancePortTests()
        self.base.setUp()
        testcase.addCleanup(self.base.doCleanups)
        self.home, self.repo, self.codex = self.base.home, self.base.repo, self.base.codex
        self.env = dict(self.base.env)
        self.source, self.target = self.base.runtime_fixture()
        for entry in json.loads((ROOT / 'codex/templates/handler-provenance.json').read_text())['files']:
            source = ROOT / entry['path']
            target = self.repo / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        shutil.copy2(ROOT / 'codex/scripts/admit-hook-fixture.py', self.codex / 'scripts/admit-hook-fixture.py')
        (self.codex / 'hooks/hooks.json').write_bytes(self.source.read_bytes())
        self.runtime = self.target.parent
        (self.runtime / 'hooks').symlink_to(self.codex / 'hooks')
        (self.runtime / 'scripts').symlink_to(self.codex / 'scripts')
        result = self.base.publish(self.source, self.target)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        self.bin = self.home / '.local/bin'
        self.bin.mkdir(parents=True, exist_ok=True)
        (self.bin / 'python3').symlink_to(sys.executable)
        # This launcher is test-only. Discovery does not run it. It neither
        # captures real prompts nor supplies production Braid consent.
        (self.bin / 'braid').write_text('#!/bin/sh\nprintf \'{"continue":true}\\n\'\n')
        (self.bin / 'braid').chmod(0o755)
        self.temp = self.home / 'tmp'
        self.temp.mkdir()
        self.env.update({
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
            'CODEX_HOME': str(self.runtime), 'TMPDIR': str(self.temp),
            'XDG_CONFIG_HOME': str(self.home / '.config'),
            'XDG_DATA_HOME': str(self.home / '.local/share'),
            'XDG_CACHE_HOME': str(self.home / '.cache'),
            'CODEX_VALIDATION_PYTHON': sys.executable,
            'CODEX_VALIDATION_UV_PYTHON': sys.executable,
            'UV_OFFLINE': '1', 'CODEX_SESSION_REPAIR_MODE': 'check',
            'CODEX_HOOK_USAGE_ROOT': str(self.runtime / 'usage-data'),
        })
        self.sentinels = {}
        for name in ('auth.json', 'session_index.json', 'state.db', 'sessions/synthetic.jsonl'):
            path = self.runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'caller-owned synthetic sentinel')
            self.sentinels[path] = path.read_bytes()
        self.payload = {
            'session_id': 'fixture-session', 'turn_id': 'fixture-turn',
            'cwd': str(self.repo), 'permission_mode': 'default',
            'tool_name': 'Bash', 'tool_input': {'command': 'git status --short'},
        }

    def run(self, hook, payload=None, env=None):
        event = dict(self.payload)
        event.update(payload or {})
        return subprocess.run(['bash', str(self.codex / 'hooks' / hook)],
            input=json.dumps(event), text=True, capture_output=True, timeout=30,
            cwd=self.repo, env=self.env | (env or {}), check=False)

    def assert_preserved(self, testcase):
        for path, contents in self.sentinels.items():
            testcase.assertEqual(path.read_bytes(), contents, str(path))
