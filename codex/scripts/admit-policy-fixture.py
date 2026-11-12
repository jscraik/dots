"""Preflight the complete generated-policy projection in a disposable HOME."""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from migration_scope import deployment_module, require_policy_path

SPEC = importlib.util.spec_from_file_location('hook_admission', Path(__file__).with_name('admit-hook-fixture.py'))
ADMISSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADMISSION)

PROFILES = ('docs', 'oss-local', 'oss-local-code', 'oss-local-fallback',
            'oss-security', 'oss-cloud', 'oss-inspect')
RESOURCE_DIRECTORIES = ('hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules')


def expected_map(deployed=False):
    rows = [{'name': 'config.toml', 'source': 'codex/config.toml',
             'target': '{CODEX_HOME}/config.toml', 'strategy': 'copy-runtime'}]
    for name in PROFILES:
        filename = name + '.config.toml'
        rows.append({'name': filename, 'source': 'codex/' + filename,
                     'target': '{CODEX_HOME}/' + filename})
    rows.append({'name': 'AGENTS.md', 'source': 'codex/AGENTS.md', 'target': '{CODEX_HOME}/AGENTS.md'})
    for name in RESOURCE_DIRECTORIES:
        rows.append({'name': name, 'source': 'codex/' + name, 'target': '{CODEX_HOME}/' + name})
    rows.append({'name': 'hooks.json', 'source': 'codex/hooks/hooks.json',
                 'target': '{CODEX_HOME}/hooks.json', 'strategy': 'hook-copy'})
    for name in ('agents', 'automations', 'usage-data'):
        rows.append({'name': name, 'target': '{CODEX_HOME}/' + name,
                     'strategy': 'preserve' if deployed else 'runtime-directory'})
    return {'schema_version': 1, 'codex_projection': rows, 'global_projection': []}


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate projection-map key')
        value[key] = item
    return value


def preflight(map_path):
    repo = Path(__file__).resolve().parents[2]
    deployed = deployment_module()
    home = ADMISSION.admit({'cwd': str(repo)})
    require_policy_path(map_path)
    if map_path != repo / 'codex/projection-map.json' or map_path.is_symlink():
        raise ValueError('Full fixture map must belong to this isolated checkout')
    data = json.loads(map_path.read_text(), object_pairs_hook=unique)
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data != expected_map(deployed is not None):
        raise ValueError('Only the closed full-policy fixture map is admitted')
    backup_root = require_policy_path(home / '.config-symlink-backups' if deployed is None
        else Path(deployed.context()['state_dir']) / 'publisher-backups')
    if backup_root.is_symlink():
        raise ValueError('Fixture backup directory must not be symlinked')
    if backup_root.exists():
        for path in backup_root.rglob('*'):
            require_policy_path(path)
            if path.is_symlink():
                raise ValueError('Fixture backups must not contain symlinks')
    for row in data['codex_projection']:
        target = require_policy_path(home / '.codex' / row['name'])
        strategy = row.get('strategy', 'symlink')
        if 'source' in row:
            source = require_policy_path(repo / row['source'])
            if not source.exists() or source.is_symlink():
                raise ValueError('Missing or symlinked canonical source: ' + row['name'])
            if (row['name'] in RESOURCE_DIRECTORIES) != source.is_dir() or (
                    row['name'] not in RESOURCE_DIRECTORIES and not source.is_file()):
                raise ValueError('Canonical source has the wrong resource type: ' + row['name'])
            if source.is_dir():
                for child in source.rglob('*'):
                    require_policy_path(child)
                    if child.is_symlink():
                        raise ValueError('Canonical source tree must not contain symlinks')
            if target.is_symlink() and (strategy != 'symlink' or target.resolve() != source):
                admitted_old = False
                if deployed is not None and strategy == 'symlink':
                    before = deployed.context()['before'][row['name']]
                    info = target.lstat()
                    admitted_old = (before.get('kind') == 'symlink'
                        and before.get('link') == str(target.readlink())
                        and before.get('inode') == info.st_ino
                        and before.get('device') == info.st_dev
                        and before.get('mtime_ns') == info.st_mtime_ns)
                if not admitted_old:
                    raise ValueError('Unexpected runtime target symlink: ' + row['name'])
            if strategy in {'copy-runtime', 'hook-copy'} and target.exists() and (
                    not target.is_file() or target.samefile(source)):
                raise ValueError('Runtime copy must be a separate regular file: ' + row['name'])
        elif strategy == 'preserve':
            if deployed is None:
                raise ValueError('Preservation requires a packaged context')
        elif (target.exists() or target.is_symlink()) and (not target.is_dir() or target.is_symlink()):
            raise ValueError('Local runtime directory conflict: ' + row['name'])
    # Capture and validate canonical policy before the projector can create or
    # replace any target, including when the main runtime copy is absent.
    canonical = (repo / 'codex/config.toml').read_bytes()
    result = subprocess.run([sys.executable, '-B', str(repo / 'codex/scripts/validate-codex-config.py'),
        '--config-stdin'], input=canonical, capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError('Canonical governance rejected projection: ' + result.stderr.decode() + result.stdout.decode())
    result = subprocess.run([sys.executable, '-B', str(repo / 'codex/scripts/project-codex-hooks.py'),
        '--source', str(repo / 'codex/hooks/hooks.json'), '--without-braid'], capture_output=True, timeout=15, check=False)
    if result.returncode:
        raise ValueError('Canonical hook manifest rejected projection: ' + result.stderr.decode())
    result = subprocess.run([sys.executable, '-B', str(repo / 'codex/scripts/validate-execpolicy-rules.py'),
        '--static-only'], capture_output=True, timeout=15, check=False)
    if result.returncode:
        raise ValueError('Canonical controls rejected projection: ' + result.stderr.decode() + result.stdout.decode())
    return canonical


def publish_initial(canonical):
    repo = Path(__file__).resolve().parents[2]
    home = ADMISSION.admit({'cwd': str(repo)})
    target = require_policy_path(home / '.codex/config.toml')
    if target.exists() or target.is_symlink():
        raise ValueError('Initial publication requires an absent runtime config')
    spec = importlib.util.spec_from_file_location('runtime_repair', repo / 'codex/scripts/repair-runtime-config-drift.py')
    repair = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repair)
    repair._validate_canonical_snapshot(canonical.decode())
    target.parent.mkdir(parents=True, exist_ok=True)
    repair._write_repair(target, canonical.decode(),
                         unchanged=((repo / 'codex/config.toml', canonical),))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--publish-initial-config', action='store_true')
    args = parser.parse_args()
    try:
        canonical = preflight(args.map)
        if args.publish_initial_config:
            publish_initial(canonical)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Full-policy fixture preflight failed: {exc}\n')
