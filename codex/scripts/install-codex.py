"""Prepare, apply, check or restore one validated Codex installation."""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import shlex
import ctypes
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPY_DIRECTORIES = frozenset({'hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules'})


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
        if path.name in COPY_DIRECTORIES:
            return {'kind': 'directory', 'mode': stat.S_IMODE(info.st_mode), 'files': SCOPE.fingerprint(path),
                    'directories': SCOPE.directory_modes(path)}
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


def copy_resource(source, target):
    """Copy an inventoried regular file/tree, never dereference source aliases."""
    before = describe(source)
    if before['kind'] == 'file':
        write(target, SCOPE.read_regular(source), before['mode'])
    elif before['kind'] == 'directory' and 'files' in before:
        target.mkdir(mode=0o700)
        for row in before['directories']:
            (target / row['path']).mkdir(mode=0o700, parents=True, exist_ok=True)
        for row in before['files']:
            destination = target / row['path']
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write(destination, SCOPE.read_regular(source / row['path']), row['mode'])
        # Preserve sealed code directories: imports must not create bytecode
        # inside the managed tree and turn the next hook into drift.
        for row in reversed(before['directories']):
            (target / row['path']).chmod(row['mode'])
        target.chmod(before['mode'])
    else:
        raise ValueError('Only managed regular resources may be copied')
    if semantic(describe(source)) != semantic(before) or semantic(describe(target)) != semantic(before):
        raise ValueError('Resource changed during copy')


def remove_resource(path):
    # Displaced directory trees always remain in private recovery storage.
    path.unlink()


def recover_rename_permissions(state, runtime):
    """Recover only inode-bound temporary modes from an interrupted rename."""
    journal = state / 'rename-modes.json'
    if not os.path.lexists(journal):
        return
    data = read_json(journal)
    if (not isinstance(data, dict) or set(data) != {'schema_version', 'entries'}
            or data['schema_version'] != 1 or not isinstance(data['entries'], list)
            or not 1 <= len(data['entries']) <= 2):
        raise ValueError('Invalid directory rename journal')
    opened = []
    try:
        for entry in data['entries']:
            if (not isinstance(entry, dict) or set(entry) != {'device', 'inode', 'mode', 'paths'}
                    or any(type(entry[key]) is not int or entry[key] < 0 for key in ('device', 'inode', 'mode'))
                    or entry['mode'] > 0o777 or entry['mode'] & 0o022
                    or not isinstance(entry['paths'], list) or not 1 <= len(entry['paths']) <= 2):
                raise ValueError('Invalid directory rename record')
            matched = []
            for value in entry['paths']:
                path = Path(value)
                allowed = path.parent == runtime or (path.parent.parent == state and
                    path.parent.name.startswith(('.copy-', '.restore-', '.restore-created-')))
                if not allowed or path.name not in COPY_DIRECTORIES:
                    raise ValueError('Directory recovery path is not managed')
                SCOPE.physical(path.parent)
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (entry['device'], entry['inode']):
                    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    current = os.fstat(fd)
                    if ((current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
                            or current.st_uid != os.getuid()
                            or stat.S_IMODE(current.st_mode) not in {entry['mode'], entry['mode'] | 0o200}):
                        os.close(fd)
                        raise ValueError('Directory recovery target changed')
                    matched.append(fd)
            if len(matched) != 1:
                for fd in matched:
                    os.close(fd)
                raise ValueError('Directory recovery inode is missing or ambiguous')
            opened.append((matched[0], entry['mode']))
        for fd, mode in opened:
            os.fchmod(fd, mode)
        journal.unlink()
    finally:
        for fd, _ in opened:
            os.close(fd)


@contextlib.contextmanager
def renameable_directories(state, *paths):
    """Journal temporary rename modes and restore them by open inode."""
    opened, entries = [], []
    journal = state / 'rename-modes.json'
    if os.path.lexists(journal):
        raise ValueError('Recover the previous directory rename before continuing')
    saved = False
    try:
        if sys.platform == 'darwin' or sys.platform.startswith('linux'):
            for path in paths:
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    current = os.fstat(fd)
                    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                        os.close(fd)
                        raise ValueError('Managed directory changed before rename')
                    mode = stat.S_IMODE(current.st_mode)
                    opened.append((fd, mode))
                    entries.append({'device': current.st_dev, 'inode': current.st_ino,
                                    'mode': mode, 'paths': [str(p) for p in paths]})
            if entries:
                save(journal, {'schema_version': 1, 'entries': entries})
                saved = True
                directory_fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                for fd, mode in opened:
                    os.fchmod(fd, mode | 0o200)
        yield
    finally:
        restored = True
        error = None
        for fd, mode in reversed(opened):
            try:
                os.fchmod(fd, mode)
            except OSError as caught:
                restored, error = False, caught
            finally:
                os.close(fd)
        if saved and restored:
            journal.unlink()
        if error is not None:
            raise error


def retire_created_target(target, state, expected):
    """Retain newly installed resources rather than recursively delete in place."""
    recovery = Path(tempfile.mkdtemp(prefix='.restore-created-', dir=state))
    displaced = recovery / target.name
    with renameable_directories(state, target, displaced):
        os.rename(target, displaced)
    if describe(displaced) != expected:
        raise ValueError('Concurrent replacement preserved in private recovery directory')


def install_absent(staged, target):
    """Publish without replacing a concurrently created destination."""
    if staged.is_file():
        os.link(staged, target, follow_symlinks=False)
        staged.unlink()
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(staged), os.fsencode(target), 4)  # RENAME_EXCL
    elif sys.platform.startswith('linux'):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(staged), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    else:
        raise ValueError('Atomic directory publication is unavailable on this OS')
    if result:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), target)


def publish_copy(state, row, expected, prepared_before, repair):
    target = Path(SCOPE.context()['home']) / '.codex' / row['name']
    before = describe(target)
    if same(before, expected):
        return
    if before != prepared_before:
        raise ValueError('Managed target changed after preparation')
    staging = Path(tempfile.mkdtemp(prefix='.copy-', dir=state))
    staged = staging / row['name']
    copy_resource(ROOT / row['source'], staged)
    if not same(describe(staged), expected) or describe(target) != before:
        raise ValueError('Managed copy changed before publication')
    if before['kind'] == 'absent':
        with renameable_directories(state, staged, target):
            install_absent(staged, target)
    else:
        with renameable_directories(state, staged, target):
            repair._exchange_paths(staged, target)
        if describe(staged) != before:
            raise ValueError('Concurrent replacement retained in private recovery directory')
        if before['kind'] == 'directory':
            return  # Retain the displaced tree as private recovery material.
        remove_resource(staged)
    staging.rmdir()


def check_copy(name):
    admission = module('installation_copy_map', ROOT / 'codex/scripts/admit-policy-fixture.py')
    rows = {row['name']: row for row in admission.expected_map(deployed=True)['codex_projection']
            if row.get('strategy') == 'copy-managed'}
    if name not in rows:
        raise ValueError('Unknown managed copy')
    target = Path(SCOPE.context()['home']) / '.codex' / name
    expected = semantic(describe(ROOT / rows[name]['source']))
    if not same(describe(target), expected):
        raise ValueError('Installed copy differs from the sealed package')
    return {'status': 'copied', 'name': name}


def verify_previous(home):
    """Refuse automatic promotion of changed runtime bytes into an update."""
    reference = home / '.codex/.dots-package.json'
    if not os.path.lexists(reference):
        return
    data = read_json(reference)
    if not isinstance(data, dict) or set(data) != {'schema_version', 'state_dir'} or data['schema_version'] != 1:
        raise ValueError('Invalid previous installation reference')
    previous = SCOPE.physical(Path(data['state_dir']))
    if not previous.is_relative_to(home) or previous.is_relative_to(home / '.codex'):
        raise ValueError('Previous installation state leaves its private boundary')
    plan = read_json(previous / 'plan.json')
    result = read_json(previous / 'result.json')
    if (plan.get('home') != str(home) or result.get('status') != 'applied'
            or set(result.get('after', {})) != set(plan.get('expected', {}))):
        raise ValueError('Previous installation is incomplete')
    for name, record in result['after'].items():
        if Path(name).name != name or name in {'.', '..'}:
            raise ValueError('Invalid previous managed path')
        if not same(record, plan['expected'][name]) or semantic(describe(home / '.codex' / name)) != semantic(record):
            raise ValueError('Runtime drift must be reviewed before update')


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
    verify_previous(home)
    files = public_files(ROOT)
    state.mkdir(mode=0o700, parents=True)
    payload = state / 'payload'
    payload.mkdir(mode=0o700)
    for row in files:
        target = payload / row['path']
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write(target, SCOPE.read_regular(ROOT / row['path']), 0o700 if row['mode'] & 0o111 else 0o600)
    generator = module('installation_generator', payload / 'scripts/generate-codex-policy.py')
    binding_bytes = SCOPE.read_regular(args.bindings)
    generated = generator.render(args.bindings)
    if SCOPE.read_regular(args.bindings) != binding_bytes:
        raise ValueError('Private bindings changed during generation')
    session_root = json.loads(binding_bytes, object_pairs_hook=SCOPE.unique)['value_0006']
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
        strategy = row.get('strategy', 'symlink')
        if strategy == 'runtime-directory':
            row['strategy'] = 'preserve'
        elif strategy == 'symlink':
            row['strategy'] = 'copy-managed'
    mapping['codex_projection'].append({'name': '.dots-package.json',
        'source': 'codex/.runtime-source.json', 'target': '{CODEX_HOME}/.dots-package.json',
        'strategy': 'copy-managed'})
    write(payload / 'codex/.runtime-source.json', json.dumps(
        {'schema_version': 1, 'state_dir': str(state)}, sort_keys=True).encode())
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
    marker = {'schema_version': 2, 'mode': args.mode, 'home': str(home), 'state_dir': str(state),
              'files': frozen, 'package_digest': SCOPE.identity(frozen), 'retained': retained,
              'before': before, 'session_evidence_root': session_root}
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
        verify_previous(home)
        admission.preflight(ROOT / 'codex/projection-map.json')
        repair = module('installation_repair', ROOT / 'codex/scripts/repair-runtime-config-drift.py')
        canonical = SCOPE.read_regular(ROOT / 'codex/config.toml').decode()
        old = context['before']['config.toml']
        runtime = home / '.codex'
        original = SCOPE.read_regular(runtime / 'config.toml').decode() if old['kind'] == 'file' else canonical
        import tomllib
        parsed_original = tomllib.loads(original)
        desktop = module('desktop_preparation_guard', ROOT / 'codex/scripts/desktop_compatibility.py')
        if desktop.requires_preservation(parsed_original):
            raise ValueError('Desktop registration needs preservation review before preparation')
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
            elif strategy == 'copy-managed':
                if before['kind'] == 'directory' and not (runtime / '.dots-package.json').exists():
                    raise ValueError('An existing directory needs separate ownership review')
                after[name] = semantic(describe(ROOT / row['source']))
            else:
                raw = merged.encode() if name == 'config.toml' else SCOPE.read_regular(ROOT / row['source'])
                after[name] = {'kind': 'file', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
            if before['kind'] == 'file':
                write(backup / name, SCOPE.read_regular(runtime / name), before['mode'])
            elif before['kind'] == 'directory' and 'files' in before:
                copy_resource(runtime / name, backup / name)
                if describe(backup / name) != before:
                    raise ValueError('Managed directory changed during backup')
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
    if complete and any(not same(record, expected[name]) and not (
            result['status'] == 'restoring' and semantic(record) == semantic(plan['before'][name]))
            for name, record in result['after'].items()):
        raise ValueError('Recorded result disagrees with the prepared plan')
    return result


def prepare_desktop_review(state, digest):
    """Write a private proposal only; printing its digest is not acceptance."""
    plan = load_plan(state, digest)
    result = load_result(state, plan)
    runtime = Path(plan['home']) / '.codex'
    if result['status'] != 'applied' or plan['before']['config.toml']['kind'] != 'file':
        raise ValueError('Desktop review requires an applied installation with a regular backup')
    current = {name: describe(runtime / name) for name in plan['before']}
    if (any(semantic(current[name]) != semantic(record) for name, record in result['after'].items()
            if name != 'config.toml') or current['config.toml']['kind'] != 'file'
            or current['config.toml']['mode'] != result['after']['config.toml']['mode']):
        raise ValueError('Desktop review cannot accept other managed changes')
    original = SCOPE.read_regular(state / 'backups/config.toml').decode()
    repair = module('desktop_base_repair', ROOT / 'codex/scripts/repair-runtime-config-drift.py')
    installed, error = repair._canonical_with_desktop_plugins(
        SCOPE.read_regular(ROOT / 'codex/config.toml').decode(), original)
    if installed is None:
        raise ValueError('Desktop baseline could not be reconstructed: ' + str(error))
    compat = module('desktop_review', ROOT / 'codex/scripts/desktop_compatibility.py')
    if (compat.sha(installed.encode()) != plan['expected']['config.toml']['sha256']
            or compat.sha(original.encode()) != plan['before']['config.toml']['sha256']):
        raise ValueError('Desktop review baseline or backup changed')
    observed = SCOPE.read_regular(runtime / 'config.toml').decode()
    changes = compat.delta(installed, observed, hook_source=str(runtime / 'hooks.json'))
    proposal = {'schema_version': 1, 'state_dir': str(state), 'home': plan['home'],
        'package_digest': plan['package_digest'], 'plan_digest': digest,
        'installed': installed, 'observed': observed, 'original': original,
        'rollback': compat.overlay(original, changes), 'changes': changes}
    raw = (json.dumps(proposal, sort_keys=True, indent=2) + '\n').encode()
    if {name: describe(runtime / name) for name in plan['before']} != current:
        raise ValueError('Managed state changed while proposing Desktop compatibility')
    review_path = state / 'desktop-review.json'
    # Create once. Never replace an existing proposal or approve on a read path.
    write(review_path, raw)
    compat.load(review_path, compat.sha(raw), state=state, plan_digest=digest, plan=plan)
    return {'schema_version': 1, 'status': 'proposal_only', 'review_sha256': compat.sha(raw),
            'changed_paths': [row['path'] for row in changes]}


def reviewed_desktop(state, digest, plan, review_digest):
    if not review_digest:
        return None
    compat = module('desktop_review', ROOT / 'codex/scripts/desktop_compatibility.py')
    return compat.load(state / 'desktop-review.json', review_digest,
                       state=state, plan_digest=digest, plan=plan)


def apply(state, digest):
    plan = load_plan(state, digest)
    runtime = Path(plan['home']) / '.codex'
    with installation_lock(Path(plan['home'])) as fd:
        recover_rename_permissions(state, runtime)
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
            for row in admission.expected_map(deployed=True)['codex_projection']:
                if row.get('strategy') == 'copy-managed':
                    publish_copy(state, row, plan['expected'][row['name']], plan['before'][row['name']], repair)
            projector(state, '--repair', lock_fd=fd)
            observed = {name: describe(runtime / name) for name in plan['expected']}
            if any(not same(observed[name], expected) for name, expected in plan['expected'].items()):
                raise ValueError('Managed readback failed')
            save(state / 'result.json', {'status': 'applied', 'after': observed})
        except (OSError, ValueError, subprocess.SubprocessError):
            save(state / 'result.json', {'status': 'failed', 'after': {}})
            raise
    return {'schema_version': 1, 'status': 'applied', 'plan_digest': digest}


def check(state, digest, review_digest=None):
    plan = load_plan(state, digest)
    result = load_result(state, plan)
    runtime = Path(plan['home']) / '.codex'
    review = reviewed_desktop(state, digest, plan, review_digest)
    after = dict(result['after'])
    if review:
        after['config.toml'] = dict(after['config.toml'],
            sha256=hashlib.sha256(review['observed'].encode()).hexdigest(),
            size=len(review['observed'].encode()))
    if (result['status'] != 'applied' or set(result['after']) != set(plan['before'])
            or any(semantic(describe(runtime / name)) != semantic(record) for name, record in after.items())):
        raise ValueError('Installed state changed or is incomplete')
    if review:
        # The normal projector still checks every resource. Only its config
        # reader receives the explicit content pin, never a blanket skip flag.
        with desktop_check_environment(state, review_digest):
            projector(state, '--check')
    else:
        projector(state, '--check')
    return {'schema_version': 1, 'status': 'applied', 'plan_digest': digest}


def restore(state, digest, review_digest=None):
    plan = load_plan(state, digest)
    runtime = Path(plan['home']) / '.codex'
    with installation_lock(Path(plan['home'])):
        recover_rename_permissions(state, runtime)
        result = load_result(state, plan)
        review = reviewed_desktop(state, digest, plan, review_digest)
        result_path = state / 'result.json'
        if review:
            if result['status'] != 'applied':
                raise ValueError('Desktop restoration needs the original applied receipt')
            result_path = state / ('desktop-' + review_digest + '-result.json')
            before = dict(plan['before'])
            before['config.toml'] = dict(before['config.toml'],
                sha256=hashlib.sha256(review['rollback'].encode()).hexdigest(),
                size=len(review['rollback'].encode()))
            after = dict(result['after'])
            after['config.toml'] = dict(after['config.toml'],
                sha256=hashlib.sha256(review['observed'].encode()).hexdigest(),
                size=len(review['observed'].encode()))
            plan = dict(plan, before=before, expected={name: semantic(row) for name, row in after.items()})
            if result_path.exists():
                # Reuse the same strict receipt parser for interrupted retries;
                # the original plan and result remain historical evidence.
                result = load_desktop_result(result_path, plan)
            else:
                result = {'status': 'applied', 'after': after}
        if result['status'] == 'prepared':
            observed = {name: describe(runtime / name) for name in plan['before']}
            if observed != plan['before']:
                raise ValueError('Prepared targets changed; no restoration attempted')
            save(state / 'result.json', {'status': 'rolled_back', 'after': observed})
            return {'schema_version': 1, 'status': 'rolled_back', 'writes': 0}
        if result['status'] not in {'applied', 'restoring', 'rolled_back', 'applying', 'failed'}:
            raise ValueError('Invalid rollback state')
        observed = result['after']
        if result['status'] in {'applying', 'failed'}:
            observed = {name: describe(runtime / name) for name in plan['before']}
            if any(semantic(record) != semantic(plan['before'][name]) and
                   not same(record, plan['expected'][name]) for name, record in observed.items()):
                raise ValueError('Interrupted targets changed; backup retained')
        current = {name: describe(runtime / name) for name in plan['before']}
        for name, before in plan['before'].items():
            if semantic(current[name]) != semantic(before) and semantic(current[name]) != semantic(observed[name]):
                raise ValueError('Newer managed state detected; backup retained')
        observed = current  # Bind exchanges to this verified generation, including prior rollback copies.
        save(result_path, {'status': 'restoring', 'after': observed})
        repair = module('restoration_exchange', ROOT / 'codex/scripts/repair-runtime-config-drift.py')
        for name, before in reversed(list(plan['before'].items())):
            target = runtime / name
            actual = describe(target)
            if semantic(actual) == semantic(before):
                continue
            if actual != observed[name]:
                raise ValueError('Target changed during restoration')
            if before['kind'] == 'absent':
                retire_created_target(target, state, observed[name])
                continue
            staging = Path(tempfile.mkdtemp(prefix='.restore-', dir=state))
            staged = staging / name
            if before['kind'] == 'symlink':
                staged.symlink_to(before['link'])
            elif before['kind'] == 'file':
                raw = (review['rollback'].encode() if review and name == 'config.toml'
                       else SCOPE.read_regular(state / 'backups' / name))
                if hashlib.sha256(raw).hexdigest() != before['sha256']:
                    raise ValueError('Managed backup changed')
                write(staged, raw, before['mode'])
            elif before['kind'] == 'directory' and 'files' in before:
                copy_resource(state / 'backups' / name, staged)
                if describe(staged) != before:
                    raise ValueError('Managed directory backup changed')
            else:
                raise ValueError('Runtime directories are never replaced')
            with renameable_directories(state, staged, target):
                repair._exchange_paths(staged, target)
            if describe(staged) != observed[name]:
                raise ValueError('Concurrent replacement preserved in private recovery file')
            if actual['kind'] != 'directory':
                remove_resource(staged)
                staging.rmdir()
        if any(semantic(describe(runtime / name)) != semantic(before) for name, before in plan['before'].items()):
            raise ValueError('Restoration readback failed')
        save(result_path, {'status': 'rolled_back', 'after': {
            name: describe(runtime / name) for name in plan['before']}})
    return {'schema_version': 1, 'status': 'rolled_back', 'plan_digest': digest}


def load_desktop_result(path, plan):
    result = read_json(path)
    if (not isinstance(result, dict) or set(result) != {'status', 'after'}
            or result['status'] not in {'restoring', 'rolled_back'}
            or not isinstance(result['after'], dict) or set(result['after']) != set(plan['before'])):
        raise ValueError('Invalid Desktop recovery receipt')
    for name, row in result['after'].items():
        if (semantic(row) != semantic(plan['before'][name])
                and (result['status'] != 'restoring' or semantic(row) != plan['expected'][name])):
            raise ValueError('Desktop recovery receipt disagrees with the reviewed targets')
    return result


@contextlib.contextmanager
def desktop_check_environment(state, digest):
    names = ('DOTS_DESKTOP_REVIEW_STATE', 'DOTS_DESKTOP_REVIEW_SHA256')
    old = {name: os.environ.get(name) for name in names}
    try:
        os.environ.update(dict(zip(names, (str(state), digest))))
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def dispatch(args):
    state = SCOPE.physical(args.state_dir)
    if (ROOT / 'codex/.deployment.json').exists():
        if args.operation == 'check-copy':
            return check_copy(args.name)
        if args.operation == 'prepare':
            return finish_prepare(state)
        if not args.plan_digest:
            raise ValueError('An exact prepared plan digest is required')
        if args.operation == 'prepare-desktop-review':
            return prepare_desktop_review(state, args.plan_digest)
        if args.desktop_review_sha256 and args.operation not in {'check', 'rollback'}:
            raise ValueError('Desktop review is only valid for explicit check or rollback')
        if args.operation in {'check', 'rollback'}:
            return {'check': check, 'rollback': restore}[args.operation](
                state, args.plan_digest, args.desktop_review_sha256)
        return apply(state, args.plan_digest)
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
                 'codex/hooks/hooks.json', 'codex/.public-source.json', 'codex/.runtime-source.json'}
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
    command = [sys.executable, '-B', str(payload / 'scripts/install-codex.py'),
        args.operation, '--state-dir', str(state), '--plan-digest', args.plan_digest or '']
    if args.desktop_review_sha256:
        command.extend(('--desktop-review-sha256', args.desktop_review_sha256))
    result = subprocess.run(command,
        env=env, cwd=payload, capture_output=True, text=True, timeout=150, check=False)
    if result.returncode:
        save(state / 'diagnostic.json', {'stdout': result.stdout, 'stderr': result.stderr})
        raise ValueError('Installation refused; inspect the private diagnostic')
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'apply', 'check', 'rollback', 'check-copy',
                                            'prepare-desktop-review'))
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--home', type=Path)
    parser.add_argument('--bindings', type=Path)
    parser.add_argument('--braid-bin', type=Path)
    parser.add_argument('--mode', choices=('rehearsal', 'machine'))
    parser.add_argument('--plan-digest')
    parser.add_argument('--name')
    parser.add_argument('--desktop-review-sha256')
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
