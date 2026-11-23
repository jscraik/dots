"""Join the generated policy and actual projector without live resources."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib

from hook_fixture import ROOT, HookFixture

SPEC = importlib.util.spec_from_file_location('controls', ROOT / 'scripts/generate-codex-controls.py')
CONTROLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLS)


class PolicyFixture(HookFixture):
    def __init__(self, testcase):
        super().__init__(testcase)
        self.env['DOTS_PROJECTION_FIXTURE'] = 'full-policy-v1'
        for name in ('scripts/link-configs.sh', 'codex/scripts/admit-policy-fixture.py',
                     'codex/scripts/install-codex.py', 'codex/scripts/deployment_scope.py',
                     'codex/scripts/validate-execpolicy-rules.py',
                     'codex/scripts/desktop_compatibility.py',
                     'codex/scripts/reconcile-config-projection.sh',
                     'codex/scripts/audit-codex-symlinks.sh', 'codex/scripts/check-runtime-config-path.sh'):
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        provenance = json.loads((ROOT / 'codex/templates/guidance-provenance.json').read_text())
        for name in ('codex/instructions/migration-scope.md', *[
                row['path'] for row in provenance['files']
                if row['path'].endswith('.md') and not row['path'].startswith('codex/rules/')]):
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        rules, requirements = CONTROLS.render_controls(
            tomllib.loads(self.base.generated['config']), self.codex, self.home)
        (self.codex / 'rules').mkdir(exist_ok=True)
        for name, text in rules.items():
            (self.codex / 'rules' / name).write_text(text)
        shutil.copy2(ROOT / 'codex/rules/workflow-guardrails.md', self.codex / 'rules/workflow-guardrails.md')
        (self.codex / 'requirements.toml').write_text(requirements)
        self.map = json.loads((ROOT / 'codex/templates/projection-map.json').read_text())
        (self.codex / 'projection-map.json').write_text(json.dumps(self.map))
        # Remove only the manually assembled managed targets from the earlier
        # handler fixture. Keep every auth/session/database sentinel in place.
        for row in self.map['codex_projection']:
            target = self.runtime / row['name']
            if target.is_symlink() or target.is_file():
                target.unlink()

    def project(self, mode='--repair', *extra):
        return subprocess.run(['bash', str(self.repo / 'scripts/link-configs.sh'), mode,
            '--scope', 'codex', '--codex-home', str(self.runtime), *extra], env=self.env,
            cwd=self.repo, text=True, capture_output=True, timeout=45, check=False)

    def script(self, name, *arguments):
        command = ['bash'] if name.endswith('.sh') else [sys.executable, '-B']
        return subprocess.run([*command, str(self.codex / 'scripts' / name), *arguments],
            env=self.env, cwd=self.repo, text=True, capture_output=True, timeout=45, check=False)

    def managed_snapshot(self):
        result = {}
        for row in self.map['codex_projection']:
            path = self.runtime / row['name']
            if path.is_symlink():
                result[row['name']] = ('link', str(path.readlink()))
            elif path.is_file():
                result[row['name']] = ('file', path.read_bytes())
            elif path.is_dir():
                result[row['name']] = ('directory',)
            else:
                result[row['name']] = ('missing',)
        return result
