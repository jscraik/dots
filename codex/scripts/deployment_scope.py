"""Validate a packaged deployment context; this is scope, never task authority."""
import functools
import hashlib
import json
import os
import pwd
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = ROOT / 'codex/.deployment.json'
PROVIDER_KEYS = ('GITHUB_TOKEN', 'GH_TOKEN', 'GH_ENTERPRISE_TOKEN',
                 'GITHUB_ENTERPRISE_TOKEN', 'OPENAI_API_KEY', 'OP_SERVICE_ACCOUNT_TOKEN')
_CHECKED_MARKER = None
_MACOS_TEMP_PARENT = Path('/private/var/folders')
# Native app metadata is not consumed by migrated handlers. It adds no resource
# root, provider input or execution authority; rehearsals retain path isolation.
_NATIVE_APP_METADATA = frozenset({'CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_TECTONIC_PATH'})


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


def context():
    global _CHECKED_MARKER
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
        ROOT / 'codex/templates/projection-map.json'))['codex_projection']}
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
        _CHECKED_MARKER = marker_digest
    if not isinstance(data['retained'], dict) or set(data['retained']) != {'automations', 'usage-data', 'browser', 'pets'}:
        raise ValueError('Incomplete retained-state boundary')
    for name, expected in data['retained'].items():
        path = home / '.codex' / name
        actual = {'type': 'symlink', 'target': os.readlink(path)} if path.is_symlink() else {
            'type': 'directory' if path.is_dir() else 'absent' if not path.exists() else 'conflict'}
        if actual != expected:
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
    exact.update(home / '.codex' / name for name in ('config.toml', 'hooks.json', 'AGENTS.md', 'automations',
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
    for name in ('GH_CONFIG_DIR', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                 'TMPDIR', 'CODEX_CONFIG_SOURCE_ROOT', 'CODEX_SOURCE_SCHEMA_PATH',
                 'CODEX_PROJECT_CONFIG_SEARCH_ROOTS'):
        for value in os.environ.get(name, '').split(os.pathsep):
            if value:
                require_path(Path(value).expanduser(), data=data)


def admit_event(event):
    """Check deployed event resources without walking session or auth stores."""
    data = context()
    require_environment(data)
    resource_roots(data)
    resolved_roots = {}

    def resolve_root(path):
        if path not in resolved_roots:
            resolved_roots[path] = path.resolve()
        return resolved_roots[path]
    if not isinstance(event, dict):
        raise TypeError('Hook event must be an object')
    for name in ('cwd', 'transcript_path'):
        if event.get(name):
            require_path(Path(event[name]).expanduser(), data=data)
    tool_input = event.get('tool_input')
    if isinstance(tool_input, dict):
        for name in ('cwd', 'workdir'):
            if tool_input.get(name):
                require_path(Path(tool_input[name]).expanduser(), data=data)
    card = event.get('runtime_card')
    if isinstance(card, dict) and card.get('path'):
        require_path(Path(card['path']).expanduser(), data=data)
    for name, value in os.environ.items():
        if name.startswith(('CODEX_', 'DOTS_')) and value.startswith('/') and name not in {
                'CODEX_VALIDATION_PYTHON', 'CODEX_VALIDATION_UV_PYTHON'}:
            if data['mode'] == 'machine' and name in _NATIVE_APP_METADATA:
                continue
            for item in value.split(os.pathsep):
                require_path(Path(item), data=data, output=name in {
                    'CODEX_HOOK_USAGE_ROOT', 'CODEX_COMPACT_HOOK_LOG', 'CODEX_SUBAGENT_HOOK_LOG',
                    'CODEX_HOOK_BYPASS_LOG', 'CODEX_RUNTIME_CARD_PATH'})
    # Only own output trees are traversed. Auth/session/plugin state remains local.
    home = Path(data['home'])
    for relative in ('.codex/state', '.codex/usage-data', '.codex/.tmp'):
        root = require_path(home / relative, data=data, output=True)
        if root.exists():
            for child in root.rglob('*'):
                require_path(child, data=data, output=True, _root_resolver=resolve_root)
    if any(path.resolve() != resolved for path, resolved in resolved_roots.items()):
        raise ValueError('Output resource alias changed during admission')
    context()
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
