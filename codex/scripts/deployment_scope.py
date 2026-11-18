"""Validate a packaged deployment context; this is scope, never task authority."""
import functools
import ctypes
import errno
import hashlib
import json
import os
import pwd
import stat
import subprocess
import sys
import tomllib
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = ROOT / 'codex/.deployment.json'
PROVIDER_KEYS = ('GITHUB_TOKEN', 'GH_TOKEN', 'GH_ENTERPRISE_TOKEN',
                 'GITHUB_ENTERPRISE_TOKEN', 'OPENAI_API_KEY', 'OP_SERVICE_ACCOUNT_TOKEN')
_CHECKED_MARKER = None
_MACOS_TEMP_PARENT = Path('/private/var/folders')
# Native app metadata is not consumed by migrated handlers. It adds no resource
# root, provider input or execution authority; rehearsals retain path isolation.
_NATIVE_APP_METADATA = frozenset({
    'CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_TECTONIC_PATH',
    'CODEX_APP_RUNTIME_CLI_PATH', 'CODEX_MCP_NODE_PATH',
})
_ENVIRONMENT_PATHS = ('GH_CONFIG_DIR', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                      'TMPDIR', 'CODEX_CONFIG_SOURCE_ROOT', 'CODEX_SOURCE_SCHEMA_PATH',
                      'CODEX_PROJECT_CONFIG_SEARCH_ROOTS')
_DIAGNOSTIC_FIELDS = {
    'deployment': frozenset({'context', 'policy_roots', 'final_context'}),
    'environment': frozenset(_ENVIRONMENT_PATHS) | _NATIVE_APP_METADATA | {
        'configuration', 'CODEX_HOME', 'CODEX_HOOK_USAGE_ROOT', 'CODEX_COMPACT_HOOK_LOG',
        'CODEX_SUBAGENT_HOOK_LOG', 'CODEX_HOOK_BYPASS_LOG', 'CODEX_RUNTIME_CARD_PATH',
        'other_CODEX_path', 'other_DOTS_path',
    },
    'event': frozenset({'cwd', 'transcript_path', 'tool_input.cwd',
                        'tool_input.workdir', 'runtime_card.path'}),
    'outputs': frozenset({'.codex/state', '.codex/usage-data', '.codex/.tmp'}),
}
_ADMISSION_ERRORS = (IndexError, OSError, TypeError, ValueError, RuntimeError)
_SAFE_DIAGNOSTICS = frozenset(
    f'stage={stage}; field={field}; error={kind.__name__}'
    for stage, fields in _DIAGNOSTIC_FIELDS.items() for field in fields
    for kind in _ADMISSION_ERRORS
)


def _checked(stage, field, operation, *args, **kwargs):
    """Annotate a rejection with fixed labels, without changing its semantics."""
    try:
        return operation(*args, **kwargs)
    except _ADMISSION_ERRORS as error:
        try:
            if getattr(error, '_dots_admission_diagnostic', None) not in _SAFE_DIAGNOSTICS:
                kind = next(kind for kind in _ADMISSION_ERRORS if isinstance(error, kind))
                diagnostic = f'stage={stage}; field={field}; error={kind.__name__}'
                if diagnostic in _SAFE_DIAGNOSTICS:
                    error._dots_admission_diagnostic = diagnostic
        except (AttributeError, TypeError):
            # Diagnostic metadata must never replace the original rejection.
            pass
        raise


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate deployment field')
        result[key] = value
    return result


def physical(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Deployment paths must be absolute without traversal')
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Deployment control paths cannot contain symlinks')
    return path


def read_regular(path, limit=16 * 1024 * 1024):
    path = physical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o022
                or before.st_size > limit):
            raise ValueError('Deployment input must be an owned unshared regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        if (len(data) > limit or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise ValueError('Deployment input changed while reading')
        return data
    finally:
        os.close(fd)


def fingerprint(root):
    result = []
    for path in sorted(root.rglob('*')):
        if path == root / 'codex/.deployment.json':
            continue
        physical(path)
        if path.is_dir():
            continue
        data = read_regular(path)
        result.append({'path': path.relative_to(root).as_posix(),
                       'sha256': hashlib.sha256(data).hexdigest(),
                       'mode': stat.S_IMODE(path.stat().st_mode)})
    return result


def directory_modes(root):
    result = []
    for path in sorted(root.rglob('*')):
        physical(path)
        if path.is_dir():
            info = path.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError('Managed directories must be owned and unshared')
            result.append({'path': str(path.relative_to(root)), 'mode': stat.S_IMODE(info.st_mode)})
    return result


def identity(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def target_home(value, mode):
    home = physical(Path(value))
    account = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    temporary = Path('/tmp').resolve()
    if not home.is_dir() or home.stat().st_uid != os.getuid():
        raise ValueError('An existing owned target home is required')
    if mode == 'rehearsal':
        if home == temporary or not home.is_relative_to(temporary) or home.is_relative_to(account):
            raise ValueError('Rehearsal cannot target an account home')
    elif mode == 'machine':
        if home != account:
            raise ValueError('Machine deployment must name the current OS account home')
    else:
        raise ValueError('Unknown deployment mode')
    return home


def usage_directory_parents(home, backup):
    """Bind directory identities without pinning mutable log contents or mtimes."""
    parents = set()
    for leaf in (home / '.codex/usage-data', backup):
        physical(leaf.parent)
        for parent in leaf.parents:
            if not parent.is_relative_to(home):
                break
            parents.add(parent)
    result = []
    for parent in sorted(parents):
        info = parent.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('Retained repair parent is unsafe')
        result.append({'path': str(parent), 'device': info.st_dev, 'inode': info.st_ino,
                       'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode)})
    return result


def usage_directory_pair(home, proof):
    """Validate both ends of a reversible, explicitly selected retained repair."""
    fields = {'schema_version', 'home', 'previous_state', 'previous_package_digest',
              'previous_plan_digest', 'previous_marker_sha256', 'observed_config_sha256',
              'backup', 'old_link', 'new_directory', 'parents', 'target_parents'}
    if (not isinstance(proof, dict) or set(proof) != fields or type(proof['schema_version']) is not int or proof['schema_version'] != 1
            or proof['home'] != str(home)):
        raise ValueError('Invalid retained usage repair proof')
    for name in ('previous_package_digest', 'previous_plan_digest', 'previous_marker_sha256', 'observed_config_sha256'):
        value = proof[name]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Retained repair requires exact previous-generation pins')
    backup = Path(proof['backup'])
    if (not backup.is_absolute() or '..' in backup.parts or backup.name != 'usage-data'
            or not backup.is_relative_to(home) or backup.is_relative_to(home / '.codex')):
        raise ValueError('Retained repair backup leaves its private boundary')
    physical(backup.parent)
    if usage_directory_parents(home, backup) != proof['parents']:
        raise ValueError('Retained repair parent identities changed')
    for parent in (backup.parent, *backup.parent.parents):
        if parent == home:
            break
        info = parent.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('Retained repair backup parent is unsafe')
    old = proof['old_link']
    if (not isinstance(old, dict) or set(old) != {'kind', 'mode', 'device', 'inode', 'mtime_ns', 'link'}
            or old['kind'] != 'symlink' or not isinstance(old['link'], str) or not old['link']):
        raise ValueError('Retained repair requires the original symlink record')
    runtime = home / '.codex/usage-data'
    physical(runtime.parent)
    # Relative targets retain their ORIGINAL parent, never the backup parent.
    if os.path.lexists(runtime.parent / old['link']):
        raise ValueError('Retained repair target is no longer absent')
    if usage_target_parents(home, old['link']) != proof['target_parents']:
        raise ValueError('Retained repair target ancestors changed')
    new = proof['new_directory']
    if (not isinstance(new, dict) or set(new) != {'device', 'inode', 'uid', 'mode'}
            or new['uid'] != os.getuid() or new['mode'] != 0o700
            or any(type(value) is not int for value in new.values())):
        raise ValueError('Retained repair requires an owned private directory')

    def link_matches(path):
        info = path.lstat()
        return stat.S_ISLNK(info.st_mode) and old == {
            'kind': 'symlink', 'mode': stat.S_IMODE(info.st_mode), 'device': info.st_dev,
            'inode': info.st_ino, 'mtime_ns': info.st_mtime_ns, 'link': os.readlink(path)}

    def directory_matches(path):
        info = path.lstat()
        return stat.S_ISDIR(info.st_mode) and new == {
            'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid,
            'mode': stat.S_IMODE(info.st_mode)}

    if link_matches(runtime) and directory_matches(backup):
        return 'original'
    if directory_matches(runtime) and link_matches(backup):
        return 'migrated'
    raise ValueError('Retained usage repair identities changed')


def usage_target_parents(home, link):
    target = physical(Path(os.path.abspath(home / '.codex' / link)))
    if not target.is_relative_to(home) or target == home:
        raise ValueError('Retained usage target leaves the selected home')
    rows = []
    for parent in target.parents:
        if not parent.is_relative_to(home):
            break
        if not parent.exists():
            rows.append({'path': str(parent), 'kind': 'absent'})
            continue
        info = parent.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('Retained usage target ancestor is unsafe')
        rows.append({'path': str(parent), 'device': info.st_dev, 'inode': info.st_ino,
                     'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode)})
    return rows


def exchange_usage_directory(home, proof):
    """Exchange the verified pair atomically; never fall back to unlink/rename."""
    before = usage_directory_pair(home, proof)
    library = ctypes.CDLL(None, use_errno=True)
    first, second = os.fsencode(proof['backup']), os.fsencode(home / '.codex/usage-data')
    if sys.platform == 'darwin':
        rename = getattr(library, 'renamex_np', None)
        arguments = (first, second, 2)
        types = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    elif sys.platform.startswith('linux'):
        rename = getattr(library, 'renameat2', None)
        arguments = (-100, first, -100, second, 2)
        types = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    else:
        rename = None
    if rename is None:
        raise OSError(errno.ENOTSUP, 'atomic path exchange is unavailable')
    rename.argtypes, rename.restype = types, ctypes.c_int
    if rename(*arguments) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    if usage_directory_pair(home, proof) == before:
        raise ValueError('Retained usage exchange readback failed')


_ROLLBACK_ADMISSION = None


def context(*, retained_usage_repair=None):
    global _CHECKED_MARKER, ROOT, MARKER
    code_root = Path(__file__).resolve().parents[1]
    reference = code_root / '.dots-package.json'
    copied = code_root == Path(os.environ.get('HOME', '')) / '.codex'
    if copied:
        data = json.loads(read_regular(reference), object_pairs_hook=unique)
        if (not isinstance(data, dict) or set(data) != {'schema_version', 'state_dir'}
                or type(data['schema_version']) is not int or data['schema_version'] != 1):
            raise ValueError('Invalid runtime package reference')
        state = physical(Path(data['state_dir']))
        home = physical(Path(os.environ['HOME']))
        if state == home or not state.is_relative_to(home) or state.is_relative_to(home / '.codex'):
            raise ValueError('Runtime package reference leaves its private state boundary')
        ROOT = state / 'payload'
        MARKER = ROOT / 'codex/.deployment.json'
        if read_regular(reference) != read_regular(ROOT / 'codex/.runtime-source.json'):
            raise ValueError('Runtime reference differs from its package')
    marker_bytes = read_regular(MARKER, 2 * 1024 * 1024)
    data = json.loads(marker_bytes, object_pairs_hook=unique)
    if (not isinstance(data, dict) or set(data) != {'schema_version', 'mode', 'home',
            'state_dir', 'files', 'package_digest', 'retained', 'before', 'session_evidence_root'}
            or type(data['schema_version']) is not int
            or data['schema_version'] != 2 or not isinstance(data['files'], list)):
        raise ValueError('Invalid deployment context')
    if any(os.environ.get(name) for name in ('DOTS_TEST_HOME', 'DOTS_FIXTURE_ROOT', 'DOTS_PROJECTION_FIXTURE')):
        raise ValueError('Deployment context cannot reuse fixture admission flags')
    home = target_home(data['home'], data['mode'])
    state = physical(Path(data['state_dir']))
    if (os.environ.get('HOME') != str(home) or not state.is_relative_to(home)
            or state == home or state.is_relative_to(home / '.codex')
            or ROOT != state / 'payload'):
        raise ValueError('Deployment source, state and HOME disagree')
    physical(home / '.codex')
    names = {row['name'] for row in json.loads(read_regular(
        ROOT / 'codex/projection-map.json'))['codex_projection']}
    if not isinstance(data['before'], dict) or set(data['before']) != names:
        raise ValueError('Incomplete managed-target inventory')
    for name, record in data['before'].items():
        if (Path(name).name != name or name in {'.', '..'} or not isinstance(record, dict)
                or record.get('kind') not in {'absent', 'file', 'symlink', 'directory'}):
            raise ValueError('Invalid managed-target record')
        fields = {'kind'}
        if record['kind'] in {'file', 'symlink'}:
            fields.update(('mode', 'inode', 'device', 'mtime_ns'))
            if any(type(record.get(key)) is not int or record[key] < 0
                    for key in ('mode', 'inode', 'device', 'mtime_ns')) or record['mode'] > 0o7777:
                raise ValueError('Invalid managed-target metadata')
            if record['kind'] == 'file':
                fields.update(('sha256', 'size'))
                digest = record.get('sha256')
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(char not in '0123456789abcdef' for char in digest)
                        or type(record.get('size')) is not int or record['size'] < 0):
                    raise ValueError('Invalid managed-file evidence')
            else:
                fields.add('link')
                if not isinstance(record.get('link'), str) or not record['link'] or '\0' in record['link']:
                    raise ValueError('Invalid managed-link evidence')
        if record['kind'] == 'directory' and name in {'hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules'}:
            fields.update({'files', 'directories', 'mode'})
            if (not isinstance(record.get('files'), list) or not isinstance(record.get('directories'), list)
                    or type(record.get('mode')) is not int or not 0 <= record['mode'] <= 0o7777):
                raise ValueError('Invalid managed directory inventory')
        if set(record) != fields:
            raise ValueError('Unexpected managed-target fields')
    marker_digest = hashlib.sha256(marker_bytes).hexdigest()
    if marker_digest != _CHECKED_MARKER:
        files = fingerprint(ROOT)
        if (files != data['files'] or identity(files) != data['package_digest']
                or any(row['mode'] & 0o222 for row in files)):
            raise ValueError('Deployment package changed or is not sealed read-only')
        # Private packages are sealed before use. Check code once per process;
        # HOME, retention and resource/environment checks remain per call.
        if copied:
            for name in ('hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules'):
                if (fingerprint(code_root / name) != fingerprint(ROOT / 'codex' / name)
                        or directory_modes(code_root / name) != directory_modes(ROOT / 'codex' / name)
                        or stat.S_IMODE((code_root / name).stat().st_mode) != stat.S_IMODE((ROOT / 'codex' / name).stat().st_mode)):
                    raise ValueError('Installed runtime resources differ from their package')
        _CHECKED_MARKER = marker_digest
    if not isinstance(data['retained'], dict) or set(data['retained']) != {'automations', 'usage-data', 'browser', 'pets'}:
        raise ValueError('Incomplete retained-state boundary')
    for name, expected in data['retained'].items():
        path = home / '.codex' / name
        actual = {'type': 'symlink', 'target': os.readlink(path)} if path.is_symlink() else {
            'type': 'directory' if path.is_dir() else 'absent' if not path.exists() else 'conflict'}
        if actual != expected:
            if name == 'usage-data' and retained_usage_repair is not None:
                proof = retained_usage_repair
                if (proof['previous_state'] == str(state)
                        and proof['previous_package_digest'] == data['package_digest']
                        and expected == {'type': 'symlink', 'target': proof['old_link']['link']}
                        and data['before']['usage-data'] == proof['old_link']
                        and usage_directory_pair(home, proof) == 'migrated'):
                    continue
            transition_path = ROOT / 'codex/.policy-transition.json'
            if name == 'usage-data' and expected == {'type': 'directory'} and transition_path.exists():
                transition = json.loads(read_regular(transition_path), object_pairs_hook=unique)
                proof = transition.get('usage_directory_repair')
                result = json.loads(read_regular(state / 'result.json'), object_pairs_hook=unique)
                if _ROLLBACK_ADMISSION is not None:
                    result = _ROLLBACK_ADMISSION(data, proof, result)
                if (proof is not None and result.get('status') in {'restoring', 'rolled_back'}
                        and usage_directory_pair(home, proof) == 'original'):
                    continue
            raise ValueError('Retained-state ownership changed')
    session_root = data['session_evidence_root']
    if (not isinstance(session_root, str) or not Path(session_root).is_absolute()
            or '..' in Path(session_root).parts or Path(session_root).name != 'sessions'):
        raise ValueError('Invalid bound session-evidence root')
    require_path(Path(session_root), data=data)
    return data


@functools.lru_cache(maxsize=16)
def _read_policy(package_digest):
    # The digest has already passed context validation. Dynamic aliases remain
    # checked per path; immutable policy need not be reparsed for every leaf.
    return tomllib.loads(read_regular(ROOT / 'codex/config.toml').decode())


@functools.lru_cache(maxsize=1)
def _macos_temp_path():
    try:
        result = subprocess.run(['/usr/bin/getconf', 'DARWIN_USER_TEMP_DIR'],
                                capture_output=True, text=True, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('OS user temporary directory unavailable') from error
    path = Path(result.stdout.strip())
    if not path.is_absolute() or '..' in path.parts or path.name != 'T':
        raise ValueError('Invalid OS user temporary directory')
    return path


def native_temp_roots(data, policy):
    selected = policy.get('default_permissions')
    settings = policy.get('permissions', {}).get(selected, {})
    if data['mode'] != 'machine' or sys.platform != 'darwin' or settings.get('extends') != ':workspace':
        return []
    path = _macos_temp_path()
    resolved = physical(path.resolve())
    info = resolved.stat()
    if (path.is_symlink() or not resolved.is_relative_to(_MACOS_TEMP_PARENT)
            or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022):
        raise ValueError('Unsafe OS user temporary directory')
    return list(dict.fromkeys((path, resolved)))


def resource_roots(data):
    home = Path(data['home'])
    policy = _read_policy(data['package_digest'])
    selected = policy.get('default_permissions')
    settings = policy.get('permissions', {}).get(selected, {})
    roots = [ROOT, Path(data['state_dir']), home / 'tmp', home / '.codex/state', home / '.codex/reports',
             home / '.codex/.tmp', home / '.codex/usage-data', home / '.codex/agents',
             home / '.codex/sessions']
    roots.extend(native_temp_roots(data, policy))
    for value in (*settings.get('workspace_roots', {}), *policy.get('projects', {})):
        candidate = Path(value)
        if candidate.is_absolute() and candidate != Path('/') and '..' not in candidate.parts:
            if data['mode'] == 'rehearsal' and not candidate.is_relative_to(home):
                raise ValueError('Rehearsal policy resource leaves its owned home')
            roots.append(candidate)
    for name in ('hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules'):
        roots.append(home / '.codex' / name)
    return roots


def _within(path, root):
    # POSIX component containment, without Python 3.12 constructing each parent.
    # Callers still resolve aliases separately and reject traversal explicitly.
    return path.parts[:len(root.parts)] == root.parts


def _event_directory_identity(directory):
    info = physical(directory).lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('Managed worktree directory changed during admission')
    return info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)


def _require_managed_event_directory(value, *, data):
    """Admit a managed Git worktree only as an event working directory."""
    home = Path(data['home'])
    path = Path(value).absolute()
    retained = (Path(data['session_evidence_root']), home / '.codex/sessions',
                home / '.codex/archived_sessions')
    if any(_within(candidate, root) for candidate in (path, path.resolve())
           for root in (*retained, *(item.resolve() for item in retained))):
        raise ValueError('Retained session storage is not an event directory')
    base = home / '.codex/worktrees'
    if not _within(path, base):
        return require_path(path, data=data)
    if not path.is_absolute() or '..' in path.parts or not _within(path, base):
        raise ValueError('Event directory leaves deployment scope')
    relative = path.relative_to(base)
    if len(relative.parts) < 2:
        raise ValueError('Managed worktree directory is incomplete')
    worktree = base.joinpath(*relative.parts[:2])
    physical(path)
    if not path.is_dir():
        raise ValueError('Managed worktree directory is unavailable')
    watched = {directory: _event_directory_identity(directory) for directory in (path, *path.parents)}
    marker_path = worktree / '.git'
    marker = read_regular(marker_path, 4096).decode().splitlines()
    if len(marker) != 1 or not marker[0].startswith('gitdir: '):
        raise ValueError('Managed worktree marker is invalid')
    gitdir = physical(Path(marker[0][8:]))
    if gitdir.parent.name != 'worktrees' or gitdir.parent.parent.name != '.git':
        raise ValueError('Managed worktree Git metadata is invalid')
    repository = gitdir.parent.parent.parent
    policy = _read_policy(data['package_digest'])
    trusted = []
    for value, settings in policy.get('projects', {}).items():
        root = Path(value)
        if (isinstance(settings, dict) and settings.get('trust_level') == 'trusted'
                and root.is_absolute() and '..' not in root.parts
                and root not in {home, Path('/')} and not _within(root, home / '.codex')):
            trusted.append(root)
    if not any(_within(repository, root) and _within(repository.resolve(), root.resolve()) for root in trusted):
        raise ValueError('Managed worktree source is not a trusted project')
    source_ancestors = []
    current = repository
    while current != home and _within(current, home):
        source_ancestors.append(current)
        current = current.parent
    for directory in (base, worktree.parent, worktree, *source_ancestors,
                      gitdir.parent.parent, gitdir.parent, gitdir):
        identity = _event_directory_identity(directory)
        if identity[2] != os.getuid() or identity[3] & 0o022:
            raise ValueError('Managed worktree metadata directory is unsafe')
        watched.setdefault(directory, identity)
    for directory in (gitdir, *gitdir.parents):
        watched.setdefault(directory, _event_directory_identity(directory))
    common = read_regular(gitdir / 'commondir', 4096).decode().splitlines()
    backlink = read_regular(gitdir / 'gitdir', 4096).decode().splitlines()
    if common != ['../..'] or backlink != [str(marker_path)]:
        raise ValueError('Managed worktree metadata does not agree')
    if (read_regular(marker_path, 4096).decode().splitlines() != marker
            or read_regular(gitdir / 'commondir', 4096).decode().splitlines() != common
            or read_regular(gitdir / 'gitdir', 4096).decode().splitlines() != backlink):
        raise ValueError('Managed worktree metadata changed during admission')
    if any(_event_directory_identity(directory) != identity for directory, identity in watched.items()):
        raise ValueError('Managed worktree directory changed during admission')
    if any(_within(candidate, root) for candidate in (path, path.resolve())
           for root in (*retained, *(item.resolve() for item in retained))):
        raise ValueError('Retained session storage is not an event directory')
    return path


def require_event_directory(value, *, data):
    """Recognise Desktop trust for event directories without granting output access."""
    try:
        return _require_managed_event_directory(value, data=data)
    except ValueError:
        if data['mode'] != 'machine':
            raise
    home = Path(data['home'])
    path = physical(Path(value).absolute())
    protected = (home / '.codex', home / '.config', home / '.ssh', home / '.aws',
                 home / 'Library', Path(data['state_dir']), Path(data['session_evidence_root']))
    if any(_within(path, root.resolve()) for root in protected):
        raise ValueError('Private runtime storage is not a project directory')
    config_path = home / '.codex/config.toml'
    original = read_regular(config_path)
    projects = tomllib.loads(original.decode()).get('projects', {})
    if not isinstance(projects, dict):
        raise ValueError('Invalid runtime project registry')
    for name, settings in projects.items():
        if not isinstance(settings, dict) or settings.get('trust_level') != 'trusted':
            continue
        root = Path(name)
        if not root.is_absolute() or home.is_relative_to(root) or '..' in root.parts:
            continue
        if not _within(path, root):
            continue
        physical(root)
        watched = {item: item.stat() for item in (path, *path.parents) if _within(item, root)}
        if any(not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
               or info.st_mode & 0o022 for info in watched.values()):
            raise ValueError('Unsafe runtime project directory')
        if read_regular(config_path) != original or any(physical(item).stat() != info for item, info in watched.items()):
            raise ValueError('Runtime project changed during admission')
        return path
    raise ValueError('Event directory is not a trusted project')



def require_repository_path(repository, value, *, output=False, data=None):
    """Admit readiness resources in one verified managed checkout, never a root."""
    data = context() if data is None else data
    root, path = Path(repository).absolute(), Path(value).absolute()
    if output and _within(root, Path(data['home']) / '.codex/worktrees'):
        if path.parent != root / '.tmp' or path.suffix != '.json':
            raise ValueError('Managed readiness receipts require an existing .tmp JSON destination')
    base = Path(data['home']) / '.codex/worktrees'
    if _within(root, base):
        if not _within(root, base) or len(root.relative_to(base).parts) != 2:
            raise ValueError('Readiness requires an exact managed repository root') from None
        require_event_directory(root, data=data)
        if path.is_symlink():
            raise ValueError('Readiness resource cannot be a symlink')
        if output and os.path.lexists(path):
            leaf = path.lstat()
            if (not stat.S_ISREG(leaf.st_mode) or leaf.st_nlink != 1
                    or leaf.st_uid != os.getuid() or stat.S_IMODE(leaf.st_mode) & 0o022):
                raise ValueError('Readiness receipt destination is unsafe')
        if '..' in path.parts or not _within(path, root):
            raise ValueError('Readiness resource leaves its repository')
        retained = [Path(data['session_evidence_root']), ROOT, Path(data['state_dir'])]
        retained.extend(Path(data['home']) / '.codex' / name for name in (
            'sessions', 'archived_sessions', 'auth.json', '.env', 'plugins', 'browser',
            'pets', 'automations', 'state.db', 'sqlite', 'session_index.json'))
        if any(_within(path.resolve(), item.resolve()) for item in retained):
            raise ValueError('Readiness cannot use retained or installed resources')
        if path != root and path.relative_to(root).parts[0] == '.git':
            raise ValueError('Readiness resources cannot use Git administration')
        parent = path if path.exists() else path.parent
        physical(parent)
        if not parent.exists() or not _within(parent.resolve(), root):
            raise ValueError('Readiness resource parent is unavailable')
        if path.exists() and path.is_file() and path.stat().st_nlink != 1:
            raise ValueError('Readiness resource shares an inode')
        require_event_directory(root, data=data)
        return path
    return require_path(path, output=output, data=data)


def repository_read(repository, value):
    path = require_repository_path(repository, value)
    raw = read_regular(path)
    require_repository_path(repository, value)
    return raw


def repository_identity(repository):
    data = context()
    root = Path(repository).absolute()
    if not _within(root, Path(data['home']) / '.codex/worktrees'):
        return None
    require_repository_path(root, root, data=data)
    marker = read_regular(root / '.git')
    gitdir = Path(marker.decode().splitlines()[0][8:])
    paths = dict.fromkeys((root, *root.parents, gitdir, *gitdir.parents))
    result = (tuple((str(path), _event_directory_identity(path)) for path in paths),
              marker, read_regular(gitdir / 'commondir'), read_regular(gitdir / 'gitdir'))
    require_repository_path(root, root, data=data)
    return result


def require_repository_identity(repository, expected):
    if repository_identity(repository) != expected:
        raise ValueError('Readiness repository identity changed')


def repository_receipt(repository, fallback):
    data = context()
    root = Path(repository).absolute()
    if _within(root, Path(data['home']) / '.codex/worktrees'):
        require_repository_path(root, root, data=data)
        receipt = root / '.tmp/pr-readiness.v1.json'
        ignored = subprocess.run(['git', '-C', str(root), 'check-ignore', '--quiet',
                                  str(receipt)], check=False, capture_output=True)
        if ignored.returncode != 0:
            raise ValueError('Managed receipt destination requires a Git ignore rule or local info/exclude entry')
        receipt.parent.mkdir(mode=0o700, exist_ok=True)
        require_repository_path(root, receipt, output=True, data=data)
        return receipt
    return fallback


def write_repository_receipt(repository, value, raw, expected_identity=None):
    data = context()
    path = require_repository_path(repository, value, output=True, data=data)
    root = Path(repository).absolute()
    if not _within(root, Path(data['home']) / '.codex/worktrees'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return
    parent_identity = _event_directory_identity(path.parent)
    if parent_identity[2] != os.getuid() or parent_identity[3] & 0o022:
        raise ValueError('Readiness receipt parent is unsafe')
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.readiness-' + secrets.token_hex(16)
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != parent_identity[:2]:
            raise ValueError('Readiness receipt parent changed')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=descriptor)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require_repository_path(root, path, output=True, data=data)
        if expected_identity is not None:
            require_repository_identity(root, expected_identity)
        if _event_directory_identity(path.parent) != parent_identity:
            raise ValueError('Readiness receipt parent changed before publication')
        os.replace(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
    finally:
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        os.close(descriptor)


def require_path(value, *, output=False, data=None, _root_resolver=None):
    data = context() if data is None else data
    home = Path(data['home'])
    path = Path(value).absolute()
    if data['mode'] == 'rehearsal' and not _within(path.resolve(), home):
        raise ValueError('Rehearsal resource leaves its owned home')
    # Bulk admission validates these immutable policy roots once up front.
    roots = resource_roots(data) if _root_resolver is None else []
    resolve_root = Path.resolve if _root_resolver is None else _root_resolver
    resolved_path = path.resolve()
    exact = {home, home / '.codex', home / '.cache', home / '.config', home / '.local/share'}
    exact.update(home / '.codex' / name for name in ('config.toml', 'hooks.json', 'AGENTS.md', 'automations', '.dots-package.json',
        'docs.config.toml', 'oss-local.config.toml', 'oss-local-code.config.toml',
        'oss-local-fallback.config.toml', 'oss-security.config.toml',
        'oss-cloud.config.toml', 'oss-inspect.config.toml'))
    if output:
        retained = [Path(data['session_evidence_root']), *[home / '.codex' / name for name in (
            'sessions', 'archived_sessions', 'auth.json', '.env', 'session_index.json',
            'state.db', 'sqlite', 'plugins', 'browser', 'pets', 'automations')]]
        protected_roots = (*retained, *[resolve_root(item) for item in retained])
        if any(_within(candidate, protected)
               for candidate in (path, resolved_path) for protected in protected_roots):
            raise ValueError('Retained local stores are not helper outputs')
        if any(_within(candidate, root)
               for candidate in (path, resolved_path) for root in (ROOT, Path(data['state_dir']))):
            raise ValueError('Deployed source and installation state are not helper outputs')
        policy = _read_policy(data['package_digest'])
        runtime_outputs = [home / 'tmp', *native_temp_roots(data, policy), *[home / '.codex' / name
            for name in ('state', 'reports', '.tmp', 'usage-data')]]
        projects = [Path(value) for value in policy.get('projects', {})
                    if Path(value).is_absolute() and Path(value) not in {home, Path('/')}]
        roots = runtime_outputs + projects
        # A broad project entry must not turn local app/session/auth stores into
        # report destinations. Only these named runtime outputs are writable.
        local = (home / '.codex', home / '.local/share/codex-storage', home / '.config')
        if any(_within(candidate, resolve_root(root)) for candidate in (path, resolved_path) for root in local) and not any(
                _within(path, root) for root in runtime_outputs):
            raise ValueError('Local session, auth and application stores are not helper outputs')
        if path.exists() and not path.is_dir() and path.stat().st_nlink != 1:
            raise ValueError('Helper output must not share an existing file inode')
    if not output and path in exact and '..' not in path.parts:
        return path
    if ('..' in path.parts or not any(_within(path, root) and _within(resolved_path, resolve_root(root)) for root in roots)):
        raise ValueError('Resource leaves the deployment policy scope: ' + path.name)
    return path


def require_provider_input(value, role, data=None):
    """Admit named provider inputs without adding read/write resource roots."""
    data = context() if data is None else data
    home = Path(data['home'])
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Provider inputs need absolute paths without traversal')
    if role == 'aikido-binary':
        root = home / '.codex/utilities/aikido-mcp'
        if path == root / 'bin/aikido-mcp':
            physical(root)
            if not path.resolve().is_relative_to(root):
                raise ValueError('Aikido binary leaves its local installation')
            return path
    elif role == 'aikido-reference':
        if path == home / '.codex/aikido-mcp.env':
            return physical(path)
    elif role == 'onepassword':
        if data['mode'] == 'machine':
            # Match the launcher's existing trusted install locations, including
            # their resolved Homebrew binary. Never admit host providers in a
            # rehearsal; this check is input scope, not execution authority.
            for root in (Path('/opt/homebrew/bin'), Path('/usr/local/bin')):
                for name in ('op', 'op-beta'):
                    trusted = root / name
                    if path in (trusted, trusted.resolve()):
                        return path
    else:
        raise ValueError('Unknown provider-input role')
    return require_path(path, data=data)


def require_environment(data=None):
    data = context() if data is None else data
    if data['mode'] == 'rehearsal':
        if any(os.environ.get(name) for name in PROVIDER_KEYS):
            raise ValueError('Provider credentials are not admitted in rehearsals')
        for name in ('CODEX_HOOK_OTEL', 'CODEX_HOOK_TELEMETRY', 'CODEX_HOOK_OTEL_ENABLED',
                     'CODEX_HOOK_OTEL_ENDPOINT', 'OTEL_EXPORTER_OTLP_ENDPOINT',
                     'OTEL_EXPORTER_OTLP_LOGS_ENDPOINT'):
            if os.environ.get(name):
                raise ValueError('Telemetry is not admitted in rehearsals')
        # Inspect authentication-store paths without reading credential contents.
        # Follow an in-home alias only after checking every nested leaf.
        home = Path(data['home'])
        store = Path(os.environ.get('GH_CONFIG_DIR') or str(
            Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'gh')).expanduser()
        pending, seen = [store], set()
        while pending:
            path = pending.pop()
            if (not path.is_absolute() or '..' in path.parts
                    or not path.resolve().is_relative_to(home)):
                raise ValueError('Rehearsal authentication store leaves its owned home')
            resolved = path.resolve()
            if resolved.is_dir() and resolved not in seen:
                seen.add(resolved)
                pending.extend(resolved.iterdir())
    for name in _ENVIRONMENT_PATHS:
        for value in os.environ.get(name, '').split(os.pathsep):
            if value:
                _checked('environment', name, require_path, Path(value).expanduser(), data=data)


def admit_event(event):
    """Check deployed event resources without walking session or auth stores."""
    data = _checked('deployment', 'context', context)
    _checked('environment', 'configuration', require_environment, data)
    _checked('deployment', 'policy_roots', resource_roots, data)
    resolved_roots = {}

    def resolve_root(path):
        if path not in resolved_roots:
            resolved_roots[path] = path.resolve()
        return resolved_roots[path]
    if not isinstance(event, dict):
        raise TypeError('Hook event must be an object')
    for name in ('cwd', 'transcript_path'):
        if event.get(name):
            operation = require_event_directory if name == 'cwd' else require_path
            _checked('event', name, operation, Path(event[name]).expanduser(), data=data)
    tool_input = event.get('tool_input')
    if isinstance(tool_input, dict):
        for name in ('cwd', 'workdir'):
            if tool_input.get(name):
                _checked('event', 'tool_input.' + name, require_event_directory,
                         Path(tool_input[name]).expanduser(), data=data)
    card = event.get('runtime_card')
    if isinstance(card, dict) and card.get('path'):
        _checked('event', 'runtime_card.path', require_path,
                 Path(card['path']).expanduser(), data=data)
    for name, value in os.environ.items():
        if name.startswith(('CODEX_', 'DOTS_')) and value.startswith('/') and name not in {
                'CODEX_VALIDATION_PYTHON', 'CODEX_VALIDATION_UV_PYTHON'}:
            if data['mode'] == 'machine' and name in _NATIVE_APP_METADATA:
                continue
            field = name if name in _DIAGNOSTIC_FIELDS['environment'] else (
                'other_CODEX_path' if name.startswith('CODEX_') else 'other_DOTS_path')
            for item in value.split(os.pathsep):
                _checked('environment', field, require_path, Path(item), data=data, output=name in {
                    'CODEX_HOOK_USAGE_ROOT', 'CODEX_COMPACT_HOOK_LOG', 'CODEX_SUBAGENT_HOOK_LOG',
                    'CODEX_HOOK_BYPASS_LOG', 'CODEX_RUNTIME_CARD_PATH'})
    # Only own output trees are traversed. Auth/session/plugin state remains local.
    home = Path(data['home'])
    for relative in ('.codex/state', '.codex/usage-data', '.codex/.tmp'):
        root = _checked('outputs', relative, require_path, home / relative, data=data, output=True)
        if root.exists():
            for child in root.rglob('*'):
                _checked('outputs', relative, require_path, child, data=data, output=True,
                         _root_resolver=resolve_root)
    if any(path.resolve() != resolved for path, resolved in resolved_roots.items()):
        raise ValueError('Output resource alias changed during admission')
    _checked('deployment', 'final_context', context)
    return home


if __name__ == '__main__':
    try:
        require_environment()
        if sys.argv[1:] == ['--state-dir']:
            print(context()['state_dir'])
        elif not sys.argv[1:]:
            print('PASS: deployment source and resource context verified; no authority granted')
        else:
            raise ValueError('Unknown context operation')
    except (KeyError, OSError, TypeError, ValueError) as error:
        print('Deployment context refused: ' + str(error), file=sys.stderr)
        raise SystemExit(2) from error
