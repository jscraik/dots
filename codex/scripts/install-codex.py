"""Prepare, apply, check or restore one validated Codex installation."""
import argparse
import contextlib
import copy
import fcntl
import functools
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
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPY_DIRECTORIES = frozenset({'hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules'})
# Exact source-only differences in the reviewed 21ff7a3 installation. These
# exceptions never change the package, normal dispatch or runtime policy.
FORMATTING_REVIEW_BASELINE = {
    'codex/scripts/install-codex.py': 'd24b350b23fbb1e4dbfc3a3bcd6f16fdcccf4d3cb5397ab19f9ae1123eca4485',
    'codex/templates/projection-provenance.json': '9745b0c16d0a66b47516c44c58af1d6d3b71f05ab84c6d178a2d6065a0d8bd61',
    'tests/test_installation_route.py': '8483d068de8e37693549ef3e04256ccdce141ad7faa58e98ef67ee8fe926c9d5',
}


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


def load_previous_review(descriptor, home):
    if (not isinstance(descriptor, dict) or set(descriptor) !=
            {'state_dir', 'plan_digest', 'review_sha256', 'home'} or descriptor['home'] != str(home)):
        raise ValueError('Invalid previous Desktop review descriptor')
    previous = SCOPE.physical(Path(descriptor['state_dir']))
    if not previous.is_relative_to(home) or previous.is_relative_to(home / '.codex'):
        raise ValueError('Previous Desktop review leaves private state')
    raw = SCOPE.read_regular(previous / 'plan.json')
    if hashlib.sha256(raw).hexdigest() != descriptor['plan_digest']:
        raise ValueError('Previous installation plan changed')
    plan = json.loads(raw, object_pairs_hook=SCOPE.unique)
    result = load_result(previous, plan)
    if plan.get('home') != str(home) or result['status'] != 'applied':
        raise ValueError('Previous installation is not applied')
    compat = module('previous_desktop', ROOT / 'codex/scripts/desktop_compatibility.py')
    review = compat.load(previous / 'desktop-review.json', descriptor['review_sha256'],
                         state=previous, plan_digest=descriptor['plan_digest'], plan=plan)
    return review, plan, result


def packaged_previous_review():
    path = ROOT / 'codex/.previous-desktop-review.json'
    if not path.exists():
        return None
    context = SCOPE.context()
    descriptor = read_json(path)
    review, plan, _ = load_previous_review(descriptor, Path(context['home']))
    previous_payload = Path(descriptor['state_dir']) / 'payload'
    marker = read_json(previous_payload / 'codex/.deployment.json')
    if not isinstance(marker, dict):
        raise ValueError('Previous Desktop package marker is invalid')
    files = marker.get('files')
    if (not isinstance(files, list) or marker.get('package_digest') != plan['package_digest']
            or SCOPE.identity(files) != plan['package_digest']):
        raise ValueError('Previous Desktop package inventory changed')
    selected = [row for row in files if row.get('path') == 'codex/config.toml']
    canonical = SCOPE.read_regular(previous_payload / 'codex/config.toml')
    if len(selected) != 1 or hashlib.sha256(canonical).hexdigest() != selected[0].get('sha256'):
        raise ValueError('Previous Desktop canonical input changed')
    return dict(review, canonical=canonical.decode())


THEME_PATHS = {('desktop', 'appearanceDarkChromeTheme'), ('desktop', 'appearanceDarkCodeThemeId')}
TRANSITION_PRESERVED_PATHS = {('model',), ('model_reasoning_effort',), ('desktop', 'daybreak-enabled')}


def policy_transition():
    path = ROOT / 'codex/.policy-transition.json'
    if not path.exists():
        return None
    proof = read_json(path)
    if (not isinstance(proof, dict) or set(proof) - {'usage_directory_repair'} != {'schema_version', 'previous',
            'canonical_sha256', 'bindings_sha256', 'source_inventory_sha256',
            'approved_projects', 'observed_config', 'next_state_dir'} or type(proof['schema_version']) is not int
            or proof['schema_version'] != 1):
        raise ValueError('Invalid canonical policy transition')
    if proof['next_state_dir'] != str(ROOT.parent):
        raise ValueError('Canonical transition belongs to another package')
    if hashlib.sha256(SCOPE.read_regular(ROOT / 'codex/config.toml')).hexdigest() != proof['canonical_sha256']:
        raise ValueError('Canonical transition configuration changed')
    if SCOPE.identity(read_json(ROOT / 'codex/.public-source.json')) != proof['source_inventory_sha256']:
        raise ValueError('Canonical transition source inventory changed')
    return proof


def rebase_reviewed_hook_keys(text, review):
    """Rebase package-local historical keys only; never change hook trust values."""
    compat = module('rebase_hook_keys', ROOT / 'codex/scripts/desktop_compatibility.py')
    data = tomllib.loads(text)
    states = data.get('hooks', {}).get('state', {})
    old_prefix = str(Path(review['state_dir']) / 'payload') + '/'
    new_prefix = str(ROOT) + '/'
    rebased = {}
    for key, value in states.items():
        target = new_prefix + key[len(old_prefix):] if key.startswith(old_prefix) else key
        if target in rebased:
            raise ValueError('Hook identity rebase is ambiguous')
        rebased[target] = value
    if states == rebased:
        return text
    return compat.overlay(text, [{'path': ['hooks', 'state'],
                                 'after': {'present': True, 'value': rebased}}])


def effective_previous_review():
    review = packaged_previous_review()
    if review:
        compat = module('effective_desktop', ROOT / 'codex/scripts/desktop_compatibility.py')
        old_prefix = str(Path(review['state_dir']) / 'payload') + '/'
        new_prefix = str(ROOT) + '/'
        rows = copy.deepcopy(review['changes'])
        for row in rows:
            path = row['path']
            if path[:2] == ['hooks', 'state'] and path[2].startswith(old_prefix):
                path[2] = new_prefix + path[2][len(old_prefix):]
        review = dict(review, canonical=rebase_reviewed_hook_keys(review['canonical'], review),
                      observed=rebase_reviewed_hook_keys(review['observed'], review), changes=rows)
        previous = tomllib.loads(review['canonical'])
        observed = tomllib.loads(review['observed'])
        changes = {tuple(row['path']): row for row in review['changes']}
        # A follow-up review can have no new delta even though earlier
        # generations already carried independently approved registrations.
        # Preserve their accepted effective values AND absences, using only
        # the existing finite Desktop slot contract. Themes/archive remain
        # canonical choices handled by their existing transition rules.
        for path in compat.PATHS:
            if path in THEME_PATHS or path == ('desktop', 'autoArchiveAfterDays'):
                continue
            value = compat.get(observed, path)
            compat.validate_desktop_change(path, value)
            changes[path] = {'path': list(path), 'before': compat.get(previous, path), 'after': value}
        old_states = previous.get('hooks', {}).get('state', {})
        new_states = observed.get('hooks', {}).get('state', {})
        if old_states.keys() != new_states.keys():
            raise ValueError('Reviewed hook identities changed')
        for identity, value in new_states.items():
            old = old_states[identity]
            if 'enabled' not in value:
                continue
            if (type(value.get('enabled')) is not bool
                    or not compat.equal({k: v for k, v in old.items() if k != 'enabled'},
                                        {k: v for k, v in value.items() if k != 'enabled'})):
                raise ValueError('Reviewed hook trust changed')
            path = ('hooks', 'state', identity, 'enabled')
            changes[path] = {'path': list(path), 'before': compat.get(previous, path),
                             'after': compat.get(observed, path)}
        review = dict(review, changes=list(changes.values()))
    if review and policy_transition():
        review = dict(review, changes=[row for row in review['changes'] if tuple(row['path']) not in THEME_PATHS | TRANSITION_PRESERVED_PATHS])
    return review


def update_desktop_text(canonical, original):
    import tomllib
    repair = module('update_policy', ROOT / 'codex/scripts/repair-runtime-config-drift.py')
    merged, error = repair._canonical_with_desktop_plugins(canonical, original)
    if merged is None:
        raise ValueError('Unsupported Desktop state: ' + str(error))
    review = effective_previous_review()
    if review:
        compat = module('update_desktop', ROOT / 'codex/scripts/desktop_compatibility.py')
        parsed = tomllib.loads(canonical)
        for row in review['changes']:
            path = tuple(row['path'])
            if path[:1] == ('plugins',) and path[1] in repair.DESKTOP_OWNED_PLUGIN_IDS:
                continue
            if path[:2] == ('hooks', 'state'):
                previous = tomllib.loads(review['canonical'])
                old = previous.get('hooks', {}).get('state', {}).get(path[2])
                new = parsed.get('hooks', {}).get('state', {}).get(path[2])
                if (not isinstance(old, dict) or not isinstance(new, dict)
                        or not compat.equal({k: v for k, v in old.items() if k != 'enabled'},
                                            {k: v for k, v in new.items() if k != 'enabled'})):
                    raise ValueError('New canonical hook trust differs from reviewed identity')
            value = compat.get(parsed, path)
            if not compat.equal(value, row['before']) and not compat.equal(value, row['after']):
                raise ValueError('New canonical policy conflicts with approved Desktop state')
        merged = compat.overlay(merged, review['changes'])
    transition = policy_transition()
    if transition:
        compat = module('transition_preferences', ROOT / 'codex/scripts/desktop_compatibility.py')
        observed_preferences = tomllib.loads(transition['observed_config'])
        selected = []
        for path in TRANSITION_PRESERVED_PATHS:
            value = compat.get(observed_preferences, path)
            compat.validate_desktop_change(path, value)
            selected.append({'path': list(path), 'after': value})
        merged = compat.overlay(merged, selected)
    observed = tomllib.loads(rebase_reviewed_hook_keys(original, review) if review else original)
    disabled = {key: value for key, value in observed.get('hooks', {}).get('state', {}).items()
                if isinstance(value, dict) and value.get('enabled') is False}
    if disabled:
        compat = module('disabled_hook_values', ROOT / 'codex/scripts/desktop_compatibility.py')
        parsed = tomllib.loads(merged)
        observed_states = observed['hooks']['state']
        if len(disabled) == len(observed_states):
            # A generation may add or relocate hook identities. An operator
            # who disabled every hook must not acquire enabled replacements.
            preserved = copy.deepcopy(parsed)
            for value in preserved.get('hooks', {}).get('state', {}).values():
                value['enabled'] = False
            disabled = preserved.get('hooks', {}).get('state', {})
        else:
            preserved = preserve_hook_disables(parsed, observed)
        if not compat.equal(parsed, preserved):
            merged = compat.overlay(merged, [
                {'path': ['hooks', 'state', key, 'enabled'], 'after': {'present': True, 'value': False}}
                for key in disabled])
    return merged


def normalized_desktop_update(original, canonical):
    review = effective_previous_review()
    if not review:
        return original, None
    compat = module('normalize_desktop', ROOT / 'codex/scripts/desktop_compatibility.py')
    import tomllib
    observed, policy = tomllib.loads(original), tomllib.loads(canonical)
    normalizers = []
    changes = list(review['changes'])
    transition = policy_transition()
    if transition:
        # Repair must preserve the same pinned revocations as installation.
        # Derive them from the transition, never from mutable runtime flags.
        selected = tomllib.loads(update_desktop_text(canonical, transition['observed_config']))
        for path in TRANSITION_PRESERVED_PATHS:
            changes.append({'path': list(path), 'after': compat.get(selected, path)})
        for identity, value in selected.get('hooks', {}).get('state', {}).items():
            path = ('hooks', 'state', identity, 'enabled')
            if value.get('enabled') is False and not any(tuple(row['path']) == path for row in changes):
                changes.append({'path': ['hooks', 'state', identity, 'enabled'],
                                'after': {'present': True, 'value': False}})
    for row in changes:
        path = tuple(row['path'])
        if not compat.equal(compat.get(observed, path), row['after']):
            raise ValueError('Approved Desktop registration changed after update')
        normalizers.append({'path': row['path'], 'after': compat.get(policy, path)})
    return compat.overlay(original, normalizers), changes


def verify_previous(home, descriptor=None):
    """Refuse automatic promotion of changed runtime bytes into an update."""
    reference = home / '.codex/.dots-package.json'
    if not os.path.lexists(reference):
        if descriptor:
            raise ValueError('Previous installation reference disappeared')
        return
    data = read_json(reference)
    if not isinstance(data, dict) or set(data) != {'schema_version', 'state_dir'} or data['schema_version'] != 1:
        raise ValueError('Invalid previous installation reference')
    previous = SCOPE.physical(Path(data['state_dir']))
    review = None
    if descriptor:
        if descriptor['state_dir'] != str(previous):
            raise ValueError('Previous installation reference changed')
        review, plan, result = load_previous_review(descriptor, home)
    if not previous.is_relative_to(home) or previous.is_relative_to(home / '.codex'):
        raise ValueError('Previous installation state leaves its private boundary')
    if not descriptor:
        plan = read_json(previous / 'plan.json')
        result = read_json(previous / 'result.json')
    if (plan.get('home') != str(home) or result.get('status') != 'applied'
            or set(result.get('after', {})) != set(plan.get('expected', {}))):
        raise ValueError('Previous installation is incomplete')
    for name, record in result['after'].items():
        if Path(name).name != name or name in {'.', '..'}:
            raise ValueError('Invalid previous managed path')
        expected = record
        if review and name == 'config.toml':
            expected = dict(record, sha256=hashlib.sha256(review['observed'].encode()).hexdigest(),
                            size=len(review['observed'].encode()))
        if not same(record, plan['expected'][name]) or semantic(describe(home / '.codex' / name)) != semantic(expected):
            raise ValueError('Runtime drift must be reviewed before update')


@contextlib.contextmanager
def transition_inspector(state, package_digest, marker_digest, usage_repair=None):
    """Inspect an exactly pinned old package using the trusted current installer."""
    payload = state / 'payload'
    raw = SCOPE.read_regular(payload / 'codex/.deployment.json')
    marker = json.loads(raw, object_pairs_hook=SCOPE.unique)
    files = SCOPE.fingerprint(payload)
    if (hashlib.sha256(raw).hexdigest() != marker_digest or files != marker['files']
            or SCOPE.identity(files) != package_digest or marker['package_digest'] != package_digest
            or any(row['mode'] & 0o222 for row in files)):
        raise ValueError('Previous policy package or marker changed')
    inspector = module('policy_transition_source', ROOT / 'codex/scripts/install-codex.py')
    inspector.ROOT = payload
    inspector.SCOPE.ROOT = payload
    inspector.SCOPE.MARKER = payload / 'codex/.deployment.json'
    if usage_repair is not None:
        # Only this pinned historical inspection gets the explicit repair proof.
        # Running hooks keep normal context validation with no override.
        inspector.SCOPE.context = functools.partial(inspector.SCOPE.context,
                                                    retained_usage_repair=usage_repair)
    inspector.SCOPE.context()
    previous_scope = sys.modules.get('migration_scope')
    try:
        migration = module('policy_transition_scope', payload / 'codex/scripts/migration_scope.py')
        # Helper imports must use the same pinned, proof-bound inspection scope.
        # Loading an unbound second scope would reject the selected retained repair.
        migration._DEPLOYMENT_MODULE = inspector.SCOPE
        sys.modules['migration_scope'] = migration
        yield inspector
    finally:
        if previous_scope is None:
            sys.modules.pop('migration_scope', None)
        else:
            sys.modules['migration_scope'] = previous_scope


def preserve_hook_disables(expected, observed):
    """Carry operator revocation forward without granting new hook consent."""
    result = copy.deepcopy(expected)
    before = expected.get('hooks', {}).get('state', {})
    after = observed.get('hooks', {}).get('state', {})
    if not isinstance(before, dict) or not isinstance(after, dict) or before.keys() != after.keys():
        raise ValueError('Hook identities changed during transition')
    for identity, value in after.items():
        original = before[identity]
        if value == original:
            continue
        if (not isinstance(value, dict) or not isinstance(original, dict)
                or value.get('enabled') is not False
                or {k: v for k, v in value.items() if k != 'enabled'}
                != {k: v for k, v in original.items() if k != 'enabled'}):
            raise ValueError('Only existing hook disable flags may change during transition')
        result['hooks']['state'][identity]['enabled'] = False
    return result


def validate_policy_transition(home, proof, canonical, *, check_runtime=True):
    """Accept only source-derived preference changes, never arbitrary runtime policy."""
    fields = {'schema_version', 'previous', 'canonical_sha256', 'bindings_sha256',
              'source_inventory_sha256', 'approved_projects', 'observed_config', 'next_state_dir'}
    previous_fields = {'state_dir', 'plan_digest', 'package_digest', 'marker_sha256',
                       'result_sha256', 'expected_config_sha256', 'observed_config_sha256', 'overlay'}
    if (not isinstance(proof, dict) or set(proof) - {'usage_directory_repair'} != fields or type(proof['schema_version']) is not int
            or proof['schema_version'] != 1 or not isinstance(proof['previous'], dict)
            or set(proof['previous']) != previous_fields or not isinstance(proof['observed_config'], str)
            or not isinstance(proof['approved_projects'], list) or len(proof['approved_projects']) < 4
            or any(not isinstance(path, str) or Path(path).anchor != '/' or '..' in Path(path).parts
                   or str(Path(path)) != path or Path(path).parent == Path(path)
                   for path in proof['approved_projects'])
            or len(set(proof['approved_projects'])) != len(proof['approved_projects'])):
        raise ValueError('Invalid canonical policy transition proof')
    previous = proof['previous']
    hashes = [proof[name] for name in ('canonical_sha256', 'bindings_sha256', 'source_inventory_sha256')]
    hashes.extend(previous[name] for name in ('plan_digest', 'package_digest', 'marker_sha256',
                                             'result_sha256', 'expected_config_sha256', 'observed_config_sha256'))
    if any(not isinstance(value, str) or len(value) != 64 or
           any(char not in '0123456789abcdef' for char in value) for value in hashes):
        raise ValueError('Canonical policy transition pins must be SHA-256 values')
    if (hashlib.sha256(canonical.encode()).hexdigest() != proof['canonical_sha256']
            or hashlib.sha256(proof['observed_config'].encode()).hexdigest() != previous['observed_config_sha256']):
        raise ValueError('Canonical policy transition configuration pin mismatch')
    inventory = (read_json(ROOT / 'codex/.public-source.json')
                 if (ROOT / 'codex/.deployment.json').exists() else public_files(ROOT))
    if SCOPE.identity(inventory) != proof['source_inventory_sha256']:
        raise ValueError('Canonical policy transition source changed')
    state = SCOPE.physical(Path(previous['state_dir']))
    if not state.is_relative_to(home) or state == home or state.is_relative_to(home / '.codex'):
        raise ValueError('Previous policy state leaves the target home')
    next_state = SCOPE.physical(Path(proof['next_state_dir']))
    if (next_state == state or not next_state.is_relative_to(home) or next_state == home
            or next_state.is_relative_to(home / '.codex')):
        raise ValueError('Next policy state leaves its private boundary')
    usage_repair = proof.get('usage_directory_repair')
    if usage_repair is not None and (
            usage_repair['previous_state'] != str(state)
            or usage_repair['previous_package_digest'] != previous['package_digest']
            or usage_repair['previous_plan_digest'] != previous['plan_digest']
            or usage_repair['previous_marker_sha256'] != previous['marker_sha256']
            or usage_repair['observed_config_sha256'] not in {
                previous['observed_config_sha256'], previous['expected_config_sha256']}
            or SCOPE.usage_directory_pair(home, usage_repair) != 'migrated'):
        raise ValueError('Usage repair differs from the selected previous generation')
    with transition_inspector(state, previous['package_digest'], previous['marker_sha256'], usage_repair) as old:
        plan = old.load_plan(state, previous['plan_digest'])
        result_raw = old.SCOPE.read_regular(state / 'result.json')
        if hashlib.sha256(result_raw).hexdigest() != previous['result_sha256']:
            raise ValueError('Previous policy result changed')
        result = old.load_result(state, plan)
        if (plan['home'] != str(home) or result['status'] != 'applied'
                or plan['expected']['config.toml']['sha256'] != previous['expected_config_sha256']):
            raise ValueError('Previous policy generation is not the pinned applied state')
        overlay = old.read_json(old.ROOT / 'codex/.previous-desktop-review.json')
        compat = old.module('transition_typed_values', old.ROOT / 'codex/scripts/desktop_compatibility.py')
        if not compat.equal(overlay, previous['overlay']):
            raise ValueError('Previous Desktop overlay identity changed')
        old.load_previous_review(overlay, home)
        original = old.SCOPE.read_regular(state / 'backups/config.toml').decode()
        if hashlib.sha256(original.encode()).hexdigest() != plan['before']['config.toml']['sha256']:
            raise ValueError('Previous policy backup changed')
        baseline = old.update_desktop_text(old.SCOPE.read_regular(old.ROOT / 'codex/config.toml').decode(), original)
        if hashlib.sha256(baseline.encode()).hexdigest() != previous['expected_config_sha256']:
            raise ValueError('Previous policy baseline changed')
        desired, target = tomllib.loads(baseline), tomllib.loads(canonical)
        old_projects = desired.get('projects', {})
        target_projects = target.get('projects', {})
        if not isinstance(old_projects, dict) or not isinstance(target_projects, dict):
            raise ValueError('Canonical transition project trust must be a table')
        # Package-local policy references move with every normal generation.
        # Compare the source-derived trust table in the old address space;
        # user-selected project bindings remain literal and must still match.
        new_projects = {}
        for path, value in target_projects.items():
            candidate = Path(path)
            name = str(old.ROOT / candidate.relative_to(next_state / 'payload')) if candidate.is_relative_to(
                next_state / 'payload') else path
            if name in new_projects:
                raise ValueError('Canonical transition project references collide')
            new_projects[name] = value
        if (not isinstance(old_projects, dict) or not isinstance(new_projects, dict)
                or not set(old_projects).issubset(new_projects)
                or any(not compat.equal(value, new_projects[path]) for path, value in old_projects.items())
                or not (set(new_projects) - set(old_projects)).issubset(proof['approved_projects'])
                or any(not compat.equal(new_projects.get(path), {'trust_level': 'trusted'})
                       for path in proof['approved_projects'])):
            raise ValueError('Canonical transition changes unselected project trust')
        for key in ('model', 'model_reasoning_effort'):
            desired[key] = copy.deepcopy(target[key])
        desired['projects'] = copy.deepcopy(new_projects)
        for path in THEME_PATHS | {('desktop', 'autoArchiveAfterDays'),
                                  ('marketplaces', 'openai-primary-runtime', 'last_updated')}:
            compat.put(desired, path, compat.get(target, path))
        observed = tomllib.loads(proof['observed_config'])
        desired = preserve_hook_disables(desired, observed)
        current_compat = module('transition_preferences', ROOT / 'codex/scripts/desktop_compatibility.py')
        desired_text = current_compat.overlay('', [
            {'path': [key], 'after': {'present': True, 'value': value}}
            for key, value in desired.items()])
        repaired = current_compat.repair_candidate(desired_text, proof['observed_config'])
        if any(tuple(row['path']) not in TRANSITION_PRESERVED_PATHS for row in repaired['desktop_changes']):
            raise ValueError('Runtime differs from the exact source-selected preference transition')

        if check_runtime:
            runtime = home / '.codex'
            if old.SCOPE.read_regular(runtime / '.dots-package.json') != old.SCOPE.read_regular(
                    old.ROOT / 'codex/.runtime-source.json'):
                raise ValueError('Previous policy reference changed')
            for name, record in result['after'].items():
                expected = dict(record)
                if name == 'config.toml':
                    expected.update(sha256=previous['observed_config_sha256'],
                                    size=len(proof['observed_config'].encode()))
                if name == 'usage-data' and usage_repair is not None:
                    if record != usage_repair['old_link']:
                        raise ValueError('Usage repair does not preserve the recorded original link')
                    expected = {'kind': 'directory'}
                if old.semantic(old.describe(runtime / name)) != old.semantic(expected):
                    raise ValueError('Managed runtime changed during the canonical transition')
        if old.SCOPE.read_regular(state / 'result.json') != result_raw:
            raise ValueError('Previous policy result changed during validation')


def build_policy_transition(args, home, generated, bindings_raw):
    state = SCOPE.physical(Path(read_json(home / '.codex/.dots-package.json')['state_dir']))
    raw = SCOPE.read_regular(home / '.codex/config.toml')
    bindings = json.loads(bindings_raw, object_pairs_hook=SCOPE.unique)
    previous = {'state_dir': str(state), 'plan_digest': args.previous_plan_digest,
        'package_digest': args.previous_package_digest, 'marker_sha256': args.previous_marker_sha256,
        'expected_config_sha256': args.previous_expected_config_sha256,
        'observed_config_sha256': args.previous_observed_config_sha256,
        'result_sha256': hashlib.sha256(SCOPE.read_regular(state / 'result.json')).hexdigest(),
        'overlay': read_json(state / 'payload/codex/.previous-desktop-review.json')}
    proof = {'schema_version': 1, 'previous': previous,
        'canonical_sha256': hashlib.sha256(generated['config'].encode()).hexdigest(),
        'bindings_sha256': hashlib.sha256(bindings_raw).hexdigest(),
        'source_inventory_sha256': SCOPE.identity(public_files(ROOT)),
        'approved_projects': [bindings['value_0174'], bindings['value_0175'], bindings['value_0176'], bindings['value_0177'],
                              *bindings.get('additional_trusted_projects', [])],
        'observed_config': raw.decode(), 'next_state_dir': str(args.state_dir)}
    if getattr(args, 'usage_directory_repair', None):
        proof['usage_directory_repair'] = read_json(args.usage_directory_repair)
    if proof['bindings_sha256'] != args.bindings_sha256:
        raise ValueError('Private policy binding pin mismatch')
    validate_policy_transition(home, proof, generated['config'])
    return proof


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


def assemble(args, *, policy_update=False):
    home = SCOPE.target_home(args.home, args.mode)
    state = SCOPE.physical(args.state_dir)
    if (not state.is_relative_to(home) or state == home
            or state.is_relative_to(home / '.codex') or state.is_relative_to(ROOT)
            or ROOT.is_relative_to(state)):
        raise ValueError('Use a fresh private state directory outside Codex and the source')
    SCOPE.physical(home / '.codex')
    if not (home / '.codex').is_dir() or state.exists():
        raise ValueError('An existing Codex home and a fresh installation state are required')
    previous_descriptor = None
    transition = None
    if policy_update:
        if args.previous_desktop_review_sha256:
            raise ValueError('Policy transition cannot also select an ordinary Desktop review')
        generator = module('transition_generator', ROOT / 'scripts/generate-codex-policy.py')
        binding_bytes = SCOPE.read_regular(args.bindings)
        preview = generator.render(args.bindings)
        if SCOPE.read_regular(args.bindings) != binding_bytes:
            raise ValueError('Private policy bindings changed during generation')
        with installation_lock(home):
            transition = build_policy_transition(args, home, preview, binding_bytes)
        previous_descriptor = transition['previous']['overlay']
    elif args.previous_desktop_review_sha256:
        reference = read_json(home / '.codex/.dots-package.json')
        previous = SCOPE.physical(Path(reference['state_dir']))
        previous_descriptor = {'state_dir': str(previous), 'home': str(home),
            'plan_digest': hashlib.sha256(SCOPE.read_regular(previous / 'plan.json')).hexdigest(),
            'review_sha256': args.previous_desktop_review_sha256}
    if not transition:
        verify_previous(home, previous_descriptor)
    files = public_files(ROOT)
    state.mkdir(mode=0o700, parents=True)
    payload = state / 'payload'
    payload.mkdir(mode=0o700)
    for row in files:
        target = payload / row['path']
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write(target, SCOPE.read_regular(ROOT / row['path']), 0o700 if row['mode'] & 0o111 else 0o600)
    if previous_descriptor:
        write(payload / 'codex/.previous-desktop-review.json',
              json.dumps(previous_descriptor, sort_keys=True).encode())
    if transition:
        write(payload / 'codex/.policy-transition.json', json.dumps(transition, sort_keys=True).encode())
    generator = module('installation_generator', payload / 'scripts/generate-codex-policy.py')
    binding_bytes = SCOPE.read_regular(args.bindings)
    generated = generator.render(args.bindings)
    if SCOPE.read_regular(args.bindings) != binding_bytes:
        raise ValueError('Private bindings changed during generation')
    if transition and hashlib.sha256(binding_bytes).hexdigest() != transition['bindings_sha256']:
        raise ValueError('Private policy binding identity changed after transition review')
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
        descriptor_path = ROOT / 'codex/.previous-desktop-review.json'
        descriptor = read_json(descriptor_path) if descriptor_path.exists() else None
        transition = policy_transition()
        if transition:
            validate_policy_transition(home, transition, SCOPE.read_regular(ROOT / 'codex/config.toml').decode())
        else:
            verify_previous(home, descriptor)
        admission.preflight(ROOT / 'codex/projection-map.json')
        canonical = SCOPE.read_regular(ROOT / 'codex/config.toml').decode()
        old = context['before']['config.toml']
        runtime = home / '.codex'
        original = SCOPE.read_regular(runtime / 'config.toml').decode() if old['kind'] == 'file' else canonical
        import tomllib
        parsed_original = tomllib.loads(original)
        desktop = module('desktop_preparation_guard', ROOT / 'codex/scripts/desktop_compatibility.py')
        if desktop.requires_preservation(parsed_original) and not descriptor:
            raise ValueError('Desktop registration needs preservation review before preparation')
        merged = update_desktop_text(canonical, original)
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


def prepare_desktop_review(state, digest, *, before_write=None):
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
    installed = update_desktop_text(
        SCOPE.read_regular(ROOT / 'codex/config.toml').decode(), original)
    compat = module('desktop_review', ROOT / 'codex/scripts/desktop_compatibility.py')
    if (compat.sha(installed.encode()) != plan['expected']['config.toml']['sha256']
            or compat.sha(original.encode()) != plan['before']['config.toml']['sha256']):
        raise ValueError('Desktop review baseline or backup changed')
    observed = SCOPE.read_regular(runtime / 'config.toml').decode()
    changes = compat.delta(installed, observed)
    proposal = {'schema_version': 1, 'state_dir': str(state), 'home': plan['home'],
        'package_digest': plan['package_digest'], 'plan_digest': digest,
        'installed': installed, 'observed': observed, 'original': original,
        'rollback': compat.reviewed_rollback(original, installed, changes), 'changes': changes}
    raw = (json.dumps(proposal, sort_keys=True, indent=2) + '\n').encode()
    if {name: describe(runtime / name) for name in plan['before']} != current:
        raise ValueError('Managed state changed while proposing Desktop compatibility')
    if before_write is not None:
        before_write(proposal)
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
        descriptor_path = ROOT / 'codex/.previous-desktop-review.json'
        transition = policy_transition()
        if transition:
            validate_policy_transition(Path(plan['home']), transition,
                SCOPE.read_regular(ROOT / 'codex/config.toml').decode(),
                check_runtime=result['status'] == 'prepared')
        if descriptor_path.exists():
            descriptor = read_json(descriptor_path)
            load_previous_review(descriptor, Path(plan['home']))
            if result['status'] == 'prepared' and not transition:
                verify_previous(Path(plan['home']), descriptor)
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
            error = None
            merged = update_desktop_text(canonical.decode(),
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
        transition = policy_transition()
        usage_repair = transition.get('usage_directory_repair') if transition else None
        prepared_before = plan['before']
        if usage_repair is not None:
            # Preflight the exact inverse before restoring ANY managed target.
            SCOPE.usage_directory_pair(Path(plan['home']), usage_repair)
            plan = dict(plan, before=dict(plan['before'], **{'usage-data': usage_repair['old_link']}))
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
            if observed != prepared_before:
                raise ValueError('Prepared targets changed; no restoration attempted')
            if usage_repair is None:
                save(state / 'result.json', {'status': 'rolled_back', 'after': observed})
                return {'schema_version': 1, 'status': 'rolled_back', 'writes': 0}
            result = {'status': 'restoring', 'after': observed}
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
            if name == 'usage-data' and usage_repair is not None:
                if SCOPE.usage_directory_pair(Path(plan['home']), usage_repair) != 'migrated':
                    raise ValueError('Usage repair changed before restoration')
                SCOPE.exchange_usage_directory(Path(plan['home']), usage_repair)
                if SCOPE.usage_directory_pair(Path(plan['home']), usage_repair) != 'original':
                    raise ValueError('Usage restoration readback failed')
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


def verified_public_payload(state, *, formatting_review=False):
    """Authenticate the package before importing any of its executable files."""
    frozen = read_json(state / 'origin.json')
    expected = public_files(ROOT)
    if formatting_review and frozen.get('files') != expected:
        for row in expected:
            historical = FORMATTING_REVIEW_BASELINE.get(row['path'])
            if historical:
                row['sha256'] = historical
    if frozen != {'root': str(ROOT), 'files': expected}:
        raise ValueError('Source candidate changed; prepare again')
    payload = state / 'payload'
    generated = {'codex/config.toml', 'codex/projection-map.json', 'codex/requirements.toml',
                 'codex/hooks/hooks.json', 'codex/.public-source.json', 'codex/.runtime-source.json'}
    if (payload / 'codex/.previous-desktop-review.json').exists():
        generated.add('codex/.previous-desktop-review.json')
    if (payload / 'codex/.policy-transition.json').exists():
        generated.add('codex/.policy-transition.json')
    generated.update('codex/' + name + '.config.toml' for name in (
        'docs', 'oss-local', 'oss-local-code', 'oss-local-fallback', 'oss-security', 'oss-cloud', 'oss-inspect'))
    generated.update('codex/rules/' + name for name in (
        'automation.rules', 'default.rules', 'foundation.rules', 'guard.rules', 'pr.rules', 'project.rules'))
    actual_files = {row['path'] for row in SCOPE.fingerprint(payload)}
    if actual_files != {row['path'] for row in frozen['files']} | generated:
        raise ValueError('Packaged file inventory changed')
    if read_json(payload / 'codex/.public-source.json') != frozen['files']:
        raise ValueError('Captured public-source inventory changed')
    for row in frozen['files']:
        if row['path'] not in generated and hashlib.sha256(SCOPE.read_regular(payload / row['path'])).hexdigest() != row['sha256']:
            raise ValueError('Packaged public source changed')
    return read_json(payload / 'codex/.deployment.json')


def prepare_formatting_review(args, state, *, presentation=False):
    """External source recovery proposes a pin; it never accepts or repairs."""
    pins = (args.plan_digest, args.package_digest, args.expected_config_sha256, args.observed_config_sha256)
    if any(not isinstance(pin, str) or len(pin) != 64 or
           any(char not in '0123456789abcdef' for char in pin) for pin in pins):
        raise ValueError('Formatting review needs exact plan, package, expected and observed pins')
    marker = verified_public_payload(state, formatting_review=True)
    if marker['package_digest'] != args.package_digest:
        raise ValueError('Formatting review package pin mismatch')
    # Execute the trusted source implementation, not the historical installer.
    inspector = module('formatting_review_source', ROOT / 'codex/scripts/install-codex.py')
    inspector.ROOT = state / 'payload'
    inspector.SCOPE.ROOT = inspector.ROOT
    inspector.SCOPE.MARKER = inspector.ROOT / 'codex/.deployment.json'
    context = inspector.SCOPE.context()
    home = Path(context['home'])
    with inspector.installation_lock(home):
        plan = inspector.load_plan(state, args.plan_digest)
        if plan['expected']['config.toml']['sha256'] != args.expected_config_sha256:
            raise ValueError('Formatting review expected pin mismatch')
        runtime = home / '.codex'
        if inspector.SCOPE.read_regular(runtime / '.dots-package.json') != inspector.SCOPE.read_regular(
                inspector.ROOT / 'codex/.runtime-source.json'):
            raise ValueError('Formatting review is not the active installation')
        paths = [state / name for name in ('origin.json', 'plan.json', 'result.json',
                 'payload/codex/.deployment.json', 'backups/config.toml')]
        paths.append(runtime / '.dots-package.json')
        descriptor = inspector.ROOT / 'codex/.previous-desktop-review.json'
        prior_packages = []
        seen = {str(state)}
        while descriptor.exists():
            prior = inspector.read_json(descriptor)
            _, prior_plan, _ = inspector.load_previous_review(prior, home)
            prior_state = Path(prior['state_dir'])
            if str(prior_state) in seen or len(seen) >= 8:
                raise ValueError('Formatting review prior chain is cyclic or too deep')
            seen.add(str(prior_state))
            paths.append(descriptor)
            paths.extend(prior_state / name for name in (
                'plan.json', 'result.json', 'desktop-review.json', 'backups/config.toml',
                'payload/codex/.deployment.json'))
            prior_files = inspector.SCOPE.fingerprint(prior_state / 'payload')
            prior_marker = inspector.read_json(prior_state / 'payload/codex/.deployment.json')
            if (prior_files != prior_marker['files'] or
                    inspector.SCOPE.identity(prior_files) != prior_plan['package_digest']):
                raise ValueError('Formatting review prior package changed')
            prior_packages.append((prior_state / 'payload', prior_files))
            descriptor = prior_state / 'payload/codex/.previous-desktop-review.json'
        snapshots = {str(path): inspector.describe(path) for path in paths}
        files = inspector.SCOPE.fingerprint(inspector.ROOT)
        managed = {name: inspector.describe(runtime / name) for name in plan['before']}

        def revalidate(proposal):
            presentation_paths = {('desktop', 'appearanceDarkChromeTheme'),
                                  ('desktop', 'appearanceDarkCodeThemeId')}
            unexpected = (any(tuple(row['path']) not in presentation_paths for row in proposal['changes'])
                          if presentation else bool(proposal['changes']))
            if (unexpected or hashlib.sha256(proposal['observed'].encode()).hexdigest()
                    != args.observed_config_sha256):
                raise ValueError('Desktop recovery cannot accept unselected changes or different bytes')
            verified_public_payload(state, formatting_review=True)
            if ({str(path): inspector.describe(path) for path in paths} != snapshots
                    or inspector.SCOPE.fingerprint(inspector.ROOT) != files
                    or any(inspector.SCOPE.fingerprint(root) != rows for root, rows in prior_packages)):
                raise ValueError('Formatting review evidence changed during preparation')
            if {name: inspector.describe(runtime / name) for name in plan['before']} != managed:
                raise ValueError('Formatting review managed targets changed during preparation')

        previous_scope = sys.modules.get('migration_scope')
        try:
            sys.modules['migration_scope'] = module(
                'formatting_package_scope', inspector.ROOT / 'codex/scripts/migration_scope.py')
            return inspector.prepare_desktop_review(state, args.plan_digest, before_write=revalidate)
        finally:
            if previous_scope is None:
                sys.modules.pop('migration_scope', None)
            else:
                sys.modules['migration_scope'] = previous_scope


def validate_usage_previous(old, previous, home, args, proof=None):
    plan = old.load_plan(previous, args.previous_plan_digest)
    result = old.load_result(previous, plan)
    if plan['home'] != str(home) or result['status'] != 'applied':
        raise ValueError('Usage repair requires the pinned applied installation')
    for name, expected in result['after'].items():
        actual = describe(home / '.codex' / name)
        if name == 'usage-data' and proof is not None:
            if expected != proof['old_link']:
                raise ValueError('Usage repair differs from the recorded original link')
            SCOPE.usage_directory_pair(home, proof)
        elif name == 'config.toml':
            if (actual['kind'] != 'file' or actual['mode'] != expected['mode']
                    or actual['sha256'] != args.previous_observed_config_sha256):
                raise ValueError('Runtime settings changed before usage repair')
        elif semantic(actual) != semantic(expected):
            raise ValueError('Other managed runtime state changed before usage repair')
    return result


def repair_usage_directory(args):
    """Exchange one dangling retained link with a private directory, keeping both."""
    if args.mode == 'machine' and args.operation == 'repair-usage-directory':
        raise ValueError('Standalone live usage repair would invalidate active hook admission; '
                         'prepare an integrated migration before changing retained state')
    home = SCOPE.target_home(args.home, args.mode)
    state = SCOPE.physical(args.state_dir)
    if (not state.is_relative_to(home) or state == home or state.is_relative_to(home / '.codex')
            or state.is_relative_to(ROOT) or ROOT.is_relative_to(state)):
        raise ValueError('Usage repair requires a separate private state directory')
    with installation_lock(home):
        previous = SCOPE.physical(Path(read_json(home / '.codex/.dots-package.json')['state_dir']))
        if state == previous:
            raise ValueError('Usage repair cannot modify an installation package')
        runtime = home / '.codex/usage-data'
        proof_path = state / 'proof.json'
        inverse = args.operation == 'restore-usage-directory'
        if inverse and not proof_path.exists():
            raise ValueError('Usage restoration requires its existing repair proof')
        if state.exists():
            proof = read_json(proof_path)
        else:
            with transition_inspector(previous, args.previous_package_digest, args.previous_marker_sha256) as old:
                result = validate_usage_previous(old, previous, home, args)
                before = describe(runtime)
                if (before['kind'] != 'symlink' or before != result['after']['usage-data']
                        or os.path.lexists(runtime.parent / before['link'])):
                    raise ValueError('Usage repair requires the recorded dangling symlink')
                if hashlib.sha256(SCOPE.read_regular(home / '.codex/config.toml')).hexdigest() != args.previous_observed_config_sha256:
                    raise ValueError('Runtime settings changed before usage repair')
                target_parents = SCOPE.usage_target_parents(home, before['link'])
                state.mkdir(mode=0o700, parents=True)
                backup = state / 'usage-data'
                backup.mkdir(mode=0o700)
                info = backup.stat()
                proof = {'schema_version': 1, 'home': str(home), 'previous_state': str(previous),
                    'previous_package_digest': args.previous_package_digest,
                    'previous_plan_digest': args.previous_plan_digest,
                    'previous_marker_sha256': args.previous_marker_sha256,
                    'observed_config_sha256': args.previous_observed_config_sha256,
                    'backup': str(backup), 'old_link': before,
                    'parents': SCOPE.usage_directory_parents(home, backup),
                    'target_parents': target_parents,
                    'new_directory': {'device': info.st_dev, 'inode': info.st_ino,
                                      'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode)}}
                save(proof_path, proof)
        if (proof['previous_state'] != str(previous)
                or proof['previous_package_digest'] != args.previous_package_digest
                or proof['previous_plan_digest'] != args.previous_plan_digest
                or proof['previous_marker_sha256'] != args.previous_marker_sha256
                or proof['observed_config_sha256'] != args.previous_observed_config_sha256
                or hashlib.sha256(SCOPE.read_regular(home / '.codex/config.toml')).hexdigest() != proof['observed_config_sha256']):
            raise ValueError('Usage repair identity or settings changed')
        pair = SCOPE.usage_directory_pair(home, proof)
        with transition_inspector(previous, args.previous_package_digest, args.previous_marker_sha256,
                                  proof if pair == 'migrated' else None) as old:
            validate_usage_previous(old, previous, home, args, proof)
            desired = 'original' if inverse else 'migrated'
            if pair != desired:
                SCOPE.exchange_usage_directory(home, proof)
        if SCOPE.usage_directory_pair(home, proof) != desired:
            raise ValueError('Usage repair readback failed')
        status = 'rolled_back' if inverse else 'applied'
        save(state / 'result.json', {'status': status, 'proof_sha256': hashlib.sha256(SCOPE.read_regular(proof_path)).hexdigest()})
        return {'schema_version': 1, 'status': status, 'proof': str(proof_path)}


def dispatch(args):
    if args.previous_desktop_review_sha256 and args.operation != 'prepare':
        raise ValueError('Previous Desktop review is valid only for preparation')
    state = SCOPE.physical(args.state_dir)
    transition_inputs = (args.bindings_sha256, args.previous_plan_digest, args.previous_package_digest,
                         args.previous_marker_sha256, args.previous_expected_config_sha256,
                         args.previous_observed_config_sha256)
    if args.operation in {'repair-usage-directory', 'restore-usage-directory'}:
        if (ROOT / 'codex/.deployment.json').exists() or not all((args.home, args.mode,
                args.previous_plan_digest, args.previous_package_digest,
                args.previous_marker_sha256, args.previous_observed_config_sha256)):
            raise ValueError('Usage repair requires reviewed source and exact previous-generation pins')
        return repair_usage_directory(args)
    if args.operation == 'prepare-policy-update':
        if (ROOT / 'codex/.deployment.json').exists():
            raise ValueError('Policy updates require the reviewed source entrypoint')
        if not all((*transition_inputs, args.home, args.bindings, args.braid_bin, args.mode)):
            raise ValueError('Policy updates require explicit bindings and previous-generation pins')
        return assemble(args, policy_update=True)
    if any(transition_inputs):
        raise ValueError('Policy transition inputs are valid only for prepare-policy-update')
    if args.usage_directory_repair:
        raise ValueError('Usage repair proof is valid only for prepare-policy-update')
    if args.operation in {'prepare-formatting-review', 'prepare-presentation-review'}:
        if (ROOT / 'codex/.deployment.json').exists():
            raise ValueError('Formatting recovery requires the reviewed source entrypoint')
        return prepare_formatting_review(args, state,
                                         presentation=args.operation == 'prepare-presentation-review')
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
    marker = verified_public_payload(state)
    payload = state / 'payload'
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
                                            'prepare-desktop-review', 'prepare-formatting-review',
                                            'prepare-presentation-review', 'prepare-policy-update',
                                            'repair-usage-directory', 'restore-usage-directory'))
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--home', type=Path)
    parser.add_argument('--bindings', type=Path)
    parser.add_argument('--braid-bin', type=Path)
    parser.add_argument('--mode', choices=('rehearsal', 'machine'))
    parser.add_argument('--plan-digest')
    parser.add_argument('--name')
    parser.add_argument('--desktop-review-sha256')
    parser.add_argument('--previous-desktop-review-sha256')
    parser.add_argument('--package-digest')
    parser.add_argument('--expected-config-sha256')
    parser.add_argument('--observed-config-sha256')
    parser.add_argument('--bindings-sha256')
    parser.add_argument('--previous-plan-digest')
    parser.add_argument('--previous-package-digest')
    parser.add_argument('--previous-marker-sha256')
    parser.add_argument('--previous-expected-config-sha256')
    parser.add_argument('--previous-observed-config-sha256')
    parser.add_argument('--usage-directory-repair', type=Path)
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
