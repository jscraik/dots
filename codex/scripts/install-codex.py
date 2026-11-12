"""Prepare, apply, check or restore one validated Codex installation."""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


SCOPE = module('installation_scope', ROOT / 'codex/scripts/deployment_scope.py')


def write(path, raw, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def save(path, value):
    fd, name = tempfile.mkstemp(prefix='.installation-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path):
    return json.loads(SCOPE.read_regular(path, 2 * 1024 * 1024), object_pairs_hook=SCOPE.unique)


def describe(path):
    """Read only a managed leaf, never the contents behind an old link."""
    SCOPE.physical(path.parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {'kind': 'absent'}
    if info.st_uid != os.getuid():
        raise ValueError('Managed target has another owner')
    if stat.S_ISDIR(info.st_mode):
        return {'kind': 'directory'}
    details = {'mode': stat.S_IMODE(info.st_mode), 'inode': info.st_ino,
               'device': info.st_dev, 'mtime_ns': info.st_mtime_ns}
    if stat.S_ISLNK(info.st_mode):
        return details | {'kind': 'symlink', 'link': os.readlink(path)}
    raw = SCOPE.read_regular(path)
    return details | {'kind': 'file', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def same(actual, expected):
    return all(actual.get(key) == value for key, value in expected.items())


def semantic(record):
    return {key: value for key, value in record.items() if key not in {'inode', 'device', 'mtime_ns'}}


def public_files(root):
    names = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=root, capture_output=True, text=True, check=True, timeout=15).stdout.split('\0')
    result = []
    for name in sorted(set(filter(None, names))):
        path = root / name
        raw = SCOPE.read_regular(path)
        result.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                       'mode': stat.S_IMODE(path.stat().st_mode)})
    if 'scripts/install-codex.py' not in {row['path'] for row in result}:
        raise ValueError('Installation source is not in the reviewed public allowlist')
    return result


def clean_environment(home, payload):
    env = {name: value for name, value in os.environ.items()
           if name in {'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE'}}
    env.update(HOME=str(home), CODEX_HOME=str(home / '.codex'), TMPDIR=str(home / 'tmp'),
        XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local/share'),
        XDG_CACHE_HOME=str(home / '.cache'), PYTHONDONTWRITEBYTECODE='1', UV_OFFLINE='1',
        CODEX_SESSION_REPAIR_MODE='check', CODEX_CONFIG_SOURCE_ROOT=str(payload / 'codex'),
        CODEX_VALIDATION_PYTHON=sys.executable, CODEX_VALIDATION_UV_PYTHON=sys.executable)
    return env


@contextlib.contextmanager
def installation_lock(home):
    directory = SCOPE.physical(home / '.local/state/dots')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = SCOPE.physical(directory / 'installation.lock')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_nlink != 1 or os.fstat(fd).st_uid != os.getuid():
            raise ValueError('Unsafe installation lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        os.close(fd)


def projector(state, *args, lock_fd=None):
    context = SCOPE.context()
    command = ['bash', str(ROOT / 'scripts/link-configs.sh'), *args,
               '--scope', 'codex', '--codex-home', str(Path(context['home']) / '.codex')]
    result = subprocess.run(command, env=os.environ, cwd=ROOT, capture_output=True, text=True,
        timeout=120, check=False, pass_fds=() if lock_fd is None else (lock_fd,))
    if result.returncode:
        save(state / 'projector-diagnostic.json', {'exit_code': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr})
        raise ValueError('Projector refused; see the private diagnostic')


def assemble(args):
    home = SCOPE.target_home(args.home, args.mode)
    state = SCOPE.physical(args.state_dir)
    if (not state.is_relative_to(home) or state == home
            or state.is_relative_to(home / '.codex') or state.is_relative_to(ROOT)
            or ROOT.is_relative_to(state)):
        raise ValueError('Use a fresh private state directory outside Codex and the source')
    SCOPE.physical(home / '.codex')
    if not (home / '.codex').is_dir() or state.exists():
        raise ValueError('An existing Codex home and a fresh installation state are required')
    files = public_files(ROOT)
    state.mkdir(mode=0o700, parents=True)
    payload = state / 'payload'
    payload.mkdir(mode=0o700)
    for row in files:
        target = payload / row['path']
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write(target, SCOPE.read_regular(ROOT / row['path']), 0o700 if row['mode'] & 0o111 else 0o600)
    generator = module('installation_generator', payload / 'scripts/generate-codex-policy.py')
    generated = generator.render(args.bindings)
    for name, text in generated.items():
        filename = 'config.toml' if name == 'config' else name + '.config.toml'
        write(payload / 'codex' / filename, text.encode())
    controls = module('installation_controls', payload / 'scripts/generate-codex-controls.py')
    import tomllib
    rules, requirements = controls.render_controls(tomllib.loads(generated['config']), payload / 'codex', home)
    for name, text in rules.items():
        target = payload / 'codex/rules' / name
        if target.exists():
            target.unlink()
        write(target, text.encode())
    write(payload / 'codex/requirements.toml', requirements.encode())
    braid = Path(args.braid_bin)
    if not braid.is_absolute() or not braid.is_file():
        raise ValueError('An explicit existing Braid executable is required; it is not executed')
    manifest = (payload / 'codex/templates/hooks.json').read_text().replace('@BRAID_COMMAND@', shlex.quote(str(braid)))
    write(payload / 'codex/hooks/hooks.json', manifest.encode())
    mapping = read_json(payload / 'codex/templates/projection-map.json')
    for row in mapping['codex_projection']:
        if row.get('strategy') == 'runtime-directory':
            row['strategy'] = 'preserve'
    write(payload / 'codex/projection-map.json', json.dumps(mapping, indent=2).encode())
    write(payload / 'codex/.public-source.json', json.dumps(files, indent=2).encode())
    before = {row['name']: describe(home / '.codex' / row['name']) for row in mapping['codex_projection']}
    retained = {}
    for name in ('automations', 'usage-data', 'browser', 'pets'):
        path = home / '.codex' / name
        retained[name] = {'type': 'symlink', 'target': os.readlink(path)} if path.is_symlink() else {
            'type': 'directory' if path.is_dir() else 'absent' if not path.exists() else 'conflict'}
    for path in payload.rglob('*'):
        if path.is_file():
            path.chmod(0o500 if path.stat().st_mode & 0o111 else 0o400)
    frozen = SCOPE.fingerprint(payload)
    marker = {'schema_version': 1, 'mode': args.mode, 'home': str(home), 'state_dir': str(state),
              'files': frozen, 'package_digest': SCOPE.identity(frozen), 'retained': retained, 'before': before}
    write(payload / 'codex/.deployment.json', json.dumps(marker, indent=2).encode(), 0o400)
    for path in sorted(payload.rglob('*'), reverse=True):
        if path.is_dir():
            path.chmod(0o500)
    payload.chmod(0o500)
    save(state / 'origin.json', {'root': str(ROOT), 'files': files})
    env = clean_environment(home, payload)
    (home / 'tmp').mkdir(mode=0o700, exist_ok=True)
    result = subprocess.run([sys.executable, '-B', str(payload / 'scripts/install-codex.py'),
        'prepare', '--state-dir', str(state)], env=env, cwd=payload, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode:
        save(state / 'diagnostic.json', {'stdout': result.stdout, 'stderr': result.stderr})
        raise ValueError('Preparation refused; see the private diagnostic')
    return json.loads(result.stdout)


def finish_prepare(state):
    context = SCOPE.context()
    home = Path(context['home'])
    admission = module('installation_preflight', ROOT / 'codex/scripts/admit-policy-fixture.py')
    with installation_lock(home):
        admission.preflight(ROOT / 'codex/projection-map.json')
        repair = module('installation_repair', ROOT / 'codex/scripts/repair-runtime-config-drift.py')
        canonical = SCOPE.read_regular(ROOT / 'codex/config.toml').decode()
        old = context['before']['config.toml']
        runtime = home / '.codex'
        original = SCOPE.read_regular(runtime / 'config.toml').decode() if old['kind'] == 'file' else canonical
        merged, error = repair._canonical_with_desktop_plugins(canonical, original)
        if merged is None:
            raise ValueError('Unsupported Desktop state: ' + str(error))
        after = {}
        backup = state / 'backups'
        backup.mkdir(mode=0o700)
        for row in admission.expected_map(deployed=True)['codex_projection']:
            name = row['name']
            before = context['before'][name]
            if describe(runtime / name) != before:
                raise ValueError('Target changed while preparing')
            strategy = row.get('strategy', 'symlink')
            if strategy == 'preserve':
                after[name] = before
            elif strategy == 'symlink':
                if before['kind'] == 'directory':
                    raise ValueError('An existing directory needs separate ownership review')
                after[name] = {'kind': 'symlink', 'link': str(ROOT / row['source'])}
            else:
                raw = merged.encode() if name == 'config.toml' else SCOPE.read_regular(ROOT / row['source'])
                after[name] = {'kind': 'file', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
            if before['kind'] == 'file':
                write(backup / name, SCOPE.read_regular(runtime / name))
        (state / 'publisher-backups').mkdir(mode=0o700)
        plan = {'schema_version': 1, 'home': str(home), 'package_digest': context['package_digest'],
                'before': context['before'], 'expected': after}
        save(state / 'plan.json', plan)
        digest = hashlib.sha256(SCOPE.read_regular(state / 'plan.json')).hexdigest()
        save(state / 'result.json', {'status': 'prepared', 'after': {}})
    return {'schema_version': 1, 'status': 'prepared', 'plan_digest': digest, 'targets': len(after)}


def load_plan(state, digest):
    context = SCOPE.context()
    if state != Path(context['state_dir']):
        raise ValueError('State directory does not belong to this package')
    raw = SCOPE.read_regular(state / 'plan.json')
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Plan digest mismatch')
    plan = json.loads(raw, object_pairs_hook=SCOPE.unique)
    if (not isinstance(plan, dict) or set(plan) != {
            'schema_version', 'home', 'package_digest', 'before', 'expected'}
            or type(plan['schema_version']) is not int or plan['schema_version'] != 1
            or plan['package_digest'] != context['package_digest'] or plan['home'] != context['home']
            or plan['before'] != context['before'] or set(plan['expected']) != set(plan['before'])):
        raise ValueError('Plan and package disagree')
    return plan


def load_result(state, plan):
    result = read_json(state / 'result.json')
    if (not isinstance(result, dict) or set(result) != {'status', 'after'}
            or not isinstance(result['after'], dict)
            or result['status'] not in {'prepared', 'applying', 'failed', 'applied', 'restoring', 'rolled_back'}):
        raise ValueError('Invalid installation result')
    complete = result['status'] in {'applied', 'restoring', 'rolled_back'}
    if set(result['after']) != (set(plan['before']) if complete else set()):
        raise ValueError('Incomplete installation result')
    expected = {name: semantic(record) for name, record in plan['before'].items()} if result['status'] == 'rolled_back' else plan['expected']
    if complete and any(not same(record, expected[name]) for name, record in result['after'].items()):
        raise ValueError('Recorded result disagrees with the prepared plan')
    return result


def apply(state, digest):
    plan = load_plan(state, digest)
    runtime = Path(plan['home']) / '.codex'
    with installation_lock(Path(plan['home'])) as fd:
        result = load_result(state, plan)
        if result['status'] == 'applied':
            return check(state, digest)
        if result['status'] not in {'prepared', 'applying', 'failed'}:
            raise ValueError('Prepare a new plan after restoration')
        for name, before in plan['before'].items():
            actual = describe(runtime / name)
            # Already-correct partial results are no-ops in the existing projector.
            if actual != before and not same(actual, plan['expected'][name]):
                raise ValueError('Target changed after preparation; no repair attempted')
        save(state / 'result.json', {'status': 'applying', 'after': {}})
        try:
            # A migration changes canonical resource paths; it is not a
            # selective drift repair. Reuse its validated atomic publisher.
            admission = module('installation_preflight', ROOT / 'codex/scripts/admit-policy-fixture.py')
            canonical = admission.preflight(ROOT / 'codex/projection-map.json')
            repair = module('installation_repair', ROOT / 'codex/scripts/repair-runtime-config-drift.py')
            target = runtime / 'config.toml'
            original = SCOPE.read_regular(target) if target.exists() else None
            merged, error = repair._canonical_with_desktop_plugins(canonical.decode(),
                canonical.decode() if original is None else original.decode())
            if merged is None or not same({'kind': 'file', 'sha256': hashlib.sha256(
                    merged.encode()).hexdigest(), 'size': len(merged.encode())}, plan['expected']['config.toml']):
                raise ValueError('Prepared canonical policy or Desktop state changed: ' + str(error))
            repair._validate_canonical_snapshot(canonical.decode())
            if original != merged.encode():
                repair._write_repair(target, merged, expected=original,
                    unchanged=((ROOT / 'codex/config.toml', canonical),))
            projector(state, '--repair', lock_fd=fd)
            observed = {name: describe(runtime / name) for name in plan['expected']}
            if any(not same(observed[name], expected) for name, expected in plan['expected'].items()):
                raise ValueError('Managed readback failed')
            save(state / 'result.json', {'status': 'applied', 'after': observed})
        except (OSError, ValueError, subprocess.SubprocessError):
            save(state / 'result.json', {'status': 'failed', 'after': {}})
            raise
    return {'schema_version': 1, 'status': 'applied', 'plan_digest': digest}


def check(state, digest):
    plan = load_plan(state, digest)
    result = load_result(state, plan)
    runtime = Path(plan['home']) / '.codex'
    if (result['status'] != 'applied' or set(result['after']) != set(plan['before'])
            or any(describe(runtime / name) != record for name, record in result['after'].items())):
        raise ValueError('Installed state changed or is incomplete')
    projector(state, '--check')
    return {'schema_version': 1, 'status': 'applied', 'plan_digest': digest}


def restore(state, digest):
    plan = load_plan(state, digest)
    runtime = Path(plan['home']) / '.codex'
    with installation_lock(Path(plan['home'])):
        result = load_result(state, plan)
        if result['status'] == 'prepared':
            observed = {name: describe(runtime / name) for name in plan['before']}
            if observed != plan['before']:
                raise ValueError('Prepared targets changed; no restoration attempted')
            save(state / 'result.json', {'status': 'rolled_back', 'after': observed})
            return {'schema_version': 1, 'status': 'rolled_back', 'writes': 0}
        if result['status'] not in {'applied', 'restoring', 'rolled_back'}:
            raise ValueError('Resume the interrupted apply before restoring')
        observed = result['after']
        for name, before in plan['before'].items():
            actual = describe(runtime / name)
            if semantic(actual) != semantic(before) and actual != observed[name]:
                raise ValueError('Newer managed state detected; backup retained')
        save(state / 'result.json', {'status': 'restoring', 'after': observed})
        repair = module('restoration_exchange', ROOT / 'codex/scripts/repair-runtime-config-drift.py')
        for name, before in reversed(list(plan['before'].items())):
            target = runtime / name
            actual = describe(target)
            if semantic(actual) == semantic(before):
                continue
            if actual != observed[name]:
                raise ValueError('Target changed during restoration')
            if before['kind'] == 'absent':
                target.unlink()
                continue
            staging = Path(tempfile.mkdtemp(prefix='.restore-', dir=state))
            staged = staging / name
            if before['kind'] == 'symlink':
                staged.symlink_to(before['link'])
            elif before['kind'] == 'file':
                raw = SCOPE.read_regular(state / 'backups' / name)
                if hashlib.sha256(raw).hexdigest() != before['sha256']:
                    raise ValueError('Managed backup changed')
                write(staged, raw, before['mode'])
            else:
                raise ValueError('Runtime directories are never replaced')
            repair._exchange_paths(staged, target)
            if describe(staged) != observed[name]:
                raise ValueError('Concurrent replacement preserved in private recovery file')
            staged.unlink()
            staging.rmdir()
        if any(semantic(describe(runtime / name)) != semantic(before) for name, before in plan['before'].items()):
            raise ValueError('Restoration readback failed')
        save(state / 'result.json', {'status': 'rolled_back', 'after': {
            name: describe(runtime / name) for name in plan['before']}})
    return {'schema_version': 1, 'status': 'rolled_back', 'plan_digest': digest}


def dispatch(args):
    state = SCOPE.physical(args.state_dir)
    if (ROOT / 'codex/.deployment.json').exists():
        if args.operation == 'prepare':
            return finish_prepare(state)
        if not args.plan_digest:
            raise ValueError('An exact prepared plan digest is required')
        return {'apply': apply, 'check': check, 'rollback': restore}[args.operation](state, args.plan_digest)
    if args.operation == 'prepare':
        if not all((args.home, args.bindings, args.braid_bin, args.mode)):
            raise ValueError('Preparation needs explicit home, bindings, Braid path and mode')
        return assemble(args)
    # Never execute package code merely because a caller supplied its manifest.
    # Every public executable must still equal this trusted source candidate.
    frozen = read_json(state / 'origin.json')
    if frozen != {'root': str(ROOT), 'files': public_files(ROOT)}:
        raise ValueError('Source candidate changed; prepare again')
    payload = state / 'payload'
    generated = {'codex/config.toml', 'codex/projection-map.json', 'codex/requirements.toml',
                 'codex/hooks/hooks.json', 'codex/.public-source.json'}
    generated.update('codex/' + name + '.config.toml' for name in (
        'docs', 'oss-local', 'oss-local-code', 'oss-local-fallback', 'oss-security', 'oss-cloud', 'oss-inspect'))
    generated.update('codex/rules/' + name for name in ('automation.rules', 'default.rules',
        'foundation.rules', 'guard.rules', 'pr.rules', 'project.rules'))
    actual_files = {row['path'] for row in SCOPE.fingerprint(payload)}
    if actual_files != {row['path'] for row in frozen['files']} | generated:
        raise ValueError('Packaged file inventory changed')
    if read_json(payload / 'codex/.public-source.json') != frozen['files']:
        raise ValueError('Captured public-source inventory changed')
    for row in frozen['files']:
        if row['path'] not in generated and hashlib.sha256(SCOPE.read_regular(payload / row['path'])).hexdigest() != row['sha256']:
            raise ValueError('Packaged public source changed')
    marker = read_json(payload / 'codex/.deployment.json')
    env = clean_environment(Path(marker['home']), payload)
    result = subprocess.run([sys.executable, '-B', str(payload / 'scripts/install-codex.py'),
        args.operation, '--state-dir', str(state), '--plan-digest', args.plan_digest or ''],
        env=env, cwd=payload, capture_output=True, text=True, timeout=150, check=False)
    if result.returncode:
        save(state / 'diagnostic.json', {'stdout': result.stdout, 'stderr': result.stderr})
        raise ValueError('Installation refused; inspect the private diagnostic')
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'apply', 'check', 'rollback'))
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--home', type=Path)
    parser.add_argument('--bindings', type=Path)
    parser.add_argument('--braid-bin', type=Path)
    parser.add_argument('--mode', choices=('rehearsal', 'machine'))
    parser.add_argument('--plan-digest')
    args = parser.parse_args()
    try:
        result = dispatch(args)
    except (KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'schema_version': 1, 'status': 'blocked', 'reason': str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
