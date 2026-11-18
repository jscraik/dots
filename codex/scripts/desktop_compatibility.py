"""Exact, operator-pinned Desktop restart delta; never an automatic exemption."""
import copy
import hashlib
import importlib.util
import json
import os
import re
import shlex
import stat
import tomllib
from pathlib import Path


PATHS = (
    ('desktop', 'selected-avatar-id'),
    ('marketplaces', 'openai-bundled', 'last_updated'),
    ('mcp_servers', 'node_repl'), ('notify',),
    ('plugins', 'computer-history@openai-bundled'),
    ('plugins', 'computer-use@openai-bundled'),
    ('plugins', 'unified-computer-use@openai-bundled'),
    ('desktop', 'appearanceDarkChromeTheme'),
    ('desktop', 'appearanceDarkCodeThemeId'),
    ('desktop', 'autoArchiveAfterDays'),
    ('plugins', 'codex-app-tools@openai-bundled'),
    ('desktop', 'codex-micro-layout'),
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def requires_preservation(config: dict) -> bool:
    """Independent executable registrations also need an operator decision."""
    return any(get(config, path)['present'] for path in (
        ('mcp_servers', 'node_repl'), ('notify',),
        ('plugins', 'computer-history@openai-bundled'),
        ('plugins', 'codex-app-tools@openai-bundled'),
        ('desktop', 'codex-micro-layout'), ('hooks', 'state')))


def get(data: dict, path: tuple) -> dict:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return {'present': False}
        data = data[key]
    return {'present': True, 'value': data}


def put(data: dict, path: tuple, value: dict) -> None:
    if not value['present']:
        current = data
        for key in path[:-1]:
            if not isinstance(current, dict):
                raise ValueError('Desktop path conflicts with a policy scalar')
            if key not in current:
                return
            current = current[key]
        if not isinstance(current, dict):
            raise ValueError('Desktop path conflicts with a policy scalar')
        current.pop(path[-1], None)
        return
    current = data
    for key in path[:-1]:
        current = current.setdefault(key, {})
        if not isinstance(current, dict):
            raise ValueError('Desktop path conflicts with a policy scalar')
    current[path[-1]] = copy.deepcopy(value['value'])


def equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return left == right


def delta(installed: str, observed: str, *, hook_source: str | None = None) -> list:
    """Permit only finite reviewed slots; all other policy must agree exactly."""
    before, after = tomllib.loads(installed), tomllib.loads(observed)
    reduced = copy.deepcopy(after)
    changes = []
    for path in PATHS:
        old, new = get(before, path), get(after, path)
        if not equal(old, new):
            validate_desktop_change(path, new)
            changes.append({'path': list(path), 'before': old, 'after': new})
            put(reduced, path, old)
    # Only an installation-bound proposal may retain newly granted native
    # consent. Existing hashes cannot be replaced through this route.
    path = ('hooks', 'state')
    old, new = get(before, path), get(after, path)
    if not old['present'] and new['present'] and hook_source is not None:
        validate_native_consent(new['value'], hook_source)
        changes.append({'path': list(path), 'before': old, 'after': new})
        put(reduced, path, old)
    # Empty parent tables are semantic TOML state too. Do not erase arbitrary
    # tables to manufacture policy agreement after deleting a known leaf.
    for parent in ('plugins', 'mcp_servers', 'marketplaces', 'desktop', 'hooks'):
        if parent not in before and reduced.get(parent) == {}:
            reduced.pop(parent)
    if not equal(before, reduced):
        raise ValueError('Desktop delta contains an unreviewable policy change')
    return changes


def validate_native_consent(states: object, hook_source: str) -> None:
    """Restrict an explicit review to this installation's native user hooks."""
    source = Path(hook_source)
    if not source.is_absolute() or '..' in source.parts or type(states) is not dict or not states:
        raise ValueError('Native consent needs the exact installed hook source and nonempty state')
    events = {'session_start', 'session_end', 'interrupt', 'user_prompt_submit', 'pre_tool_use', 'permission_request',
              'post_tool_use', 'pre_compact', 'post_compact', 'stop',
              'subagent_start', 'subagent_stop'}
    for key, row in states.items():
        parts = key.rsplit(':', 3) if type(key) is str else []
        if (len(parts) != 4 or parts[0] not in {hook_source, 'user:' + hook_source} or parts[1] not in events
                or any(not re.fullmatch(r'0|[1-9][0-9]*', index) for index in parts[2:])
                or type(row) is not dict or set(row) != {'enabled', 'trusted_hash'}
                or type(row['enabled']) is not bool or type(row['trusted_hash']) is not str
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', row['trusted_hash'])):
            raise ValueError('Native consent contains an unbound identity or invalid trust state')


def validate_desktop_change(path: tuple, new: dict) -> None:
    """Validate new slots narrowly; custom themes need a separate schema port."""
    if not new['present']:
        return
    value = new['value']
    if path == ('desktop', 'codex-micro-layout'):
        flag = value.get('separateMicrophoneKeys') if type(value) is dict else None
        expected = micro_layout()
        expected['separateMicrophoneKeys'] = flag
        if type(flag) is not bool or not equal(value, expected):
            raise ValueError('Unreviewed Codex Micro bindings remain blocking')
    if path == ('desktop', 'appearanceDarkChromeTheme'):
        raise ValueError('Custom Chrome theme changes require schema validation')
    if path == ('desktop', 'appearanceDarkCodeThemeId') and value != 'codex':
        raise ValueError('Only the verified codex dark code theme is supported')
    if path == ('desktop', 'autoArchiveAfterDays') and (type(value) is not int or value < 0):
        raise ValueError('Auto-archive days must be a nonnegative integer')
    if path == ('plugins', 'codex-app-tools@openai-bundled') and (
            type(value) is not dict or set(value) != {'enabled'}
            or type(value['enabled']) is not bool):
        raise ValueError('App tools permits only an explicit enabled boolean')


def micro_layout() -> dict:
    """Verified bundled default in TOML form; nullable encoder fields are absent."""
    return {'version': 1, 'encoderMode': 'composer-navigation',
        'voiceButtonMode': 'push-to-talk', 'separateMicrophoneKeys': False,
        'slots': {key: {'keycapId': value} for key, value in (
            ('ACT06', 'FAST'), ('ACT07', 'APPR'), ('ACT08', 'REJ'), ('ACT09', 'SPLIT'),
            ('ACT10', 'MIC1'), ('ACT11', 'EMPT1'), ('ACT10_ACT11', 'MIC'), ('ACT12', 'CODEX'))},
        'analogStick': {key: {'type': 'command', 'commandId': value} for key, value in (
            ('up', 'composer.togglePlanMode'), ('right', 'navigateForward'),
            ('down', 'toggleSidebar'), ('left', 'navigateBack'))}, 'encoder': {}}


def hook_quote_candidate(expected_text: str, observed_text: str) -> dict:
    """Restore sealed text only when changed Braid commands have identical literals."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate hook JSON key')
            result[key] = value
        return result
    expected = json.loads(expected_text, object_pairs_hook=unique)
    observed = json.loads(observed_text, object_pairs_hook=unique)
    if (type(expected) is not dict or type(observed) is not dict
            or type(expected.get('hooks')) is not dict or type(observed.get('hooks')) is not dict):
        raise ValueError('Hook declarations must be objects')
    reduced, changes = copy.deepcopy(observed), []
    for event, groups in expected['hooks'].items():
        current_groups = observed['hooks'].get(event)
        if type(groups) is not list or type(current_groups) is not list or len(groups) != len(current_groups):
            raise ValueError('Changed hook groups remain blocking')
        for group_index, (group, current_group) in enumerate(zip(groups, current_groups)):
            if type(group) is not dict or type(current_group) is not dict:
                raise ValueError('Hook groups must be objects')
            handlers, current_handlers = group.get('hooks'), current_group.get('hooks')
            if type(handlers) is not list or type(current_handlers) is not list or len(handlers) != len(current_handlers):
                raise ValueError('Changed hook handlers remain blocking')
            for handler_index, (handler, current_handler) in enumerate(zip(handlers, current_handlers)):
                if equal(handler, current_handler):
                    continue
                if (type(handler) is not dict or type(current_handler) is not dict
                        or handler.get('type') != 'command' or current_handler.get('type') != 'command'):
                    raise ValueError('Only Braid command quoting may be restored')
                commands = (handler.get('command'), current_handler.get('command'))
                arguments = []
                for command in commands:
                    if type(command) is not str or any(char in command for char in '\n\r\x00'):
                        raise ValueError('Command must be one literal line')
                    tokens = shlex.split(command)
                    if (not tokens or not Path(tokens[0]).is_absolute() or Path(tokens[0]).name != 'braid'
                            or any(not re.fullmatch(r'[A-Za-z0-9_./:@=+,-]+', token) for token in tokens)):
                        raise ValueError('Nonliteral Braid command remains blocking')
                    arguments.append(tokens)
                if arguments[0] != arguments[1]:
                    raise ValueError('Changed Braid arguments remain blocking')
                reduced['hooks'][event][group_index]['hooks'][handler_index]['command'] = commands[0]
                changes.append((re.sub('[^a-z]', '', event.lower()), group_index, handler_index))
    if not equal(expected, reduced) or len(set(changes)) != len(changes):
        raise ValueError('Other hook declaration changes remain blocking')
    return {'status': 'quote_candidate_only', 'candidate': expected_text,
            'candidate_sha256': sha(expected_text.encode()),
            'observed_sha256': sha(observed_text.encode()), 'identities': changes}


def paired_repair_candidate(installed: str, observed: str, expected_hooks: str,
                            observed_hooks: str, *, hook_source: str) -> dict:
    """Propose a matched sealed pair; never generate or grant fresh hook consent.

    Callers retain sealed-input/native provenance checks and publication authority.
    Mixed pairs remain rejected by the existing installer and receipt checks.
    """
    source = Path(hook_source)
    if not source.is_absolute() or '..' in source.parts:
        raise ValueError('Hook source must be an absolute admitted path')
    hook_candidate = hook_quote_candidate(expected_hooks, observed_hooks)
    before, after = tomllib.loads(installed), tomllib.loads(observed)
    old_states, new_states = get(before, ('hooks', 'state')), get(after, ('hooks', 'state'))
    old = old_states.get('value', {})
    new = new_states.get('value', {})
    if type(old) is not dict or type(new) is not dict or old.keys() != new.keys():
        raise ValueError('Changed hook consent identities remain blocking')
    restored, identities = [], set()
    for key in old:
        if equal(old[key], new[key]):
            continue
        parts = key.rsplit(':', 3)
        if (len(parts) != 4 or parts[0] not in {hook_source, 'user:' + hook_source}
                or not all(re.fullmatch('[0-9]+', part) for part in parts[-2:])
                or type(old[key]) is not dict or type(new[key]) is not dict):
            raise ValueError('Unbound hook consent change')
        identity = (re.sub('[^a-z]', '', parts[1].lower()), int(parts[2]), int(parts[3]))
        if identity in identities:
            raise ValueError('Ambiguous hook consent identity')
        if (not equal({k: v for k, v in old[key].items() if k != 'trusted_hash'},
                      {k: v for k, v in new[key].items() if k != 'trusted_hash'})
                or any(type(row.get('trusted_hash')) is not str or
                       not re.fullmatch('sha256:[0-9a-f]{64}', row['trusted_hash']) for row in (old[key], new[key]))):
            raise ValueError('Only an existing consent hash may be restored')
        identities.add(identity)
        restored.append({'path': ['hooks', 'state', key, 'trusted_hash'],
            'before': {'present': True, 'value': new[key]['trusted_hash']},
            'after': {'present': True, 'value': old[key]['trusted_hash']}})
    if identities != set(hook_candidate['identities']):
        raise ValueError('Consent changes do not match quote-only declarations')
    proposal = repair_candidate(installed, overlay(observed, restored))
    proposal.update(status='paired_repair_candidate_only',
        observed_sha256=sha(observed.encode()), hooks_candidate=hook_candidate['candidate'],
        hooks_candidate_sha256=hook_candidate['candidate_sha256'],
        observed_hooks_sha256=hook_candidate['observed_sha256'])
    proposal['canonical_restorations'].extend(restored)
    return proposal


def repair_candidate(installed: str, observed: str) -> dict:
    """Prepare text only; never accept unrepaired drift or publish runtime state.

    Installation callers retain canonical validation, sealed-plan validation,
    managed-target checks and explicit digest-bound operator acceptance.
    """
    canonical, current = tomllib.loads(installed), tomllib.loads(observed)
    feature_path = ('features', 'multi_agent')
    expected, actual = get(canonical, feature_path), get(current, feature_path)
    if not expected['present'] or type(expected['value']) is not bool:
        raise ValueError('Canonical multi_agent must be explicit')
    restorations = []
    if not equal(expected, actual):
        if actual['present']:
            raise ValueError('Explicit multi_agent policy changes remain blocking')
        restorations.append({'path': list(feature_path), 'before': actual, 'after': expected})
    aliases = ('sandbox_mode', 'sandbox_workspace_write')
    if any(key in canonical for key in aliases):
        raise ValueError('Canonical policy must use named permissions without legacy aliases')
    if any(key in current for key in aliases):
        selected = canonical.get('default_permissions')
        permissions = canonical.get('permissions')
        if type(selected) is not str or type(permissions) is not dict:
            raise ValueError('Canonical named permissions are required')
        profile = permissions.get(selected)
        if (type(profile) is not dict or profile.get('extends') != ':workspace'
                or type(profile.get('network')) is not dict
                or profile['network'].get('enabled') is not True
                or current.get('sandbox_mode') != 'workspace-write'
                or not equal(current.get('sandbox_workspace_write'), {'network_access': True})):
            raise ValueError('Legacy alias shape is outside this bounded repair')
        for key in aliases:
            restorations.append({'path': [key], 'before': get(current, (key,)),
                                 'after': {'present': False}})
    normalized = overlay(observed, restorations)
    desktop_changes = delta(installed, normalized)
    candidate = overlay(installed, desktop_changes)
    if not equal(delta(installed, candidate), desktop_changes):
        raise ValueError('Repaired Desktop delta did not roundtrip')
    return {'schema_version': 1, 'status': 'repair_candidate_only',
            'installed_sha256': sha(installed.encode()),
            'observed_sha256': sha(observed.encode()),
            'candidate_sha256': sha(candidate.encode()), 'candidate': candidate,
            'desktop_changes': desktop_changes, 'canonical_restorations': restorations}


def overlay(original: str, changes: list) -> str:
    """Render through the existing generator and prove a lossless TOML roundtrip."""
    spec = importlib.util.spec_from_file_location(
        'desktop_toml', Path(__file__).resolve().parents[2] / 'scripts/generate-codex-policy.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    data = tomllib.loads(original)
    for change in changes:
        put(data, tuple(change['path']), change['after'])
    rendered = generator.toml_document(json.loads(json.dumps(data, sort_keys=True)))
    if not equal(tomllib.loads(rendered), data):
        raise ValueError('Desktop rollback TOML could not roundtrip')
    return rendered


def load(path: Path, digest: str, *, state: Path, plan_digest: str,
         plan: dict) -> dict:
    """Validate the private review pin and recompute every derived field."""
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
            or info.st_size > 2 * 1024 * 1024):
        raise ValueError('Desktop review must be a private unaliased regular file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(2 * 1024 * 1024 + 1)
    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or sha(raw) != digest:
        raise ValueError('Desktop review digest or generation changed')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate Desktop review field')
            result[key] = value
        return result

    data = json.loads(raw, object_pairs_hook=unique)
    keys = {'schema_version', 'state_dir', 'home', 'package_digest', 'plan_digest',
            'installed', 'observed', 'original', 'rollback', 'changes'}
    if (not isinstance(data, dict) or set(data) != keys
            or type(data['schema_version']) is not int or data['schema_version'] != 1
            or data['state_dir'] != str(state) or data['home'] != plan['home']
            or data['package_digest'] != plan['package_digest']
            or data['plan_digest'] != plan_digest):
        raise ValueError('Desktop review belongs to another installation')
    if any(not isinstance(data[k], str) for k in ('installed', 'observed', 'original', 'rollback')):
        raise ValueError('Invalid Desktop review configuration')
    backup = state / 'backups/config.toml'
    original_record = plan['before']['config.toml']
    if original_record['kind'] == 'absent':
        if data['original'] != '' or os.path.lexists(backup):
            raise ValueError('Desktop review absent baseline changed')
    elif original_record['kind'] == 'file':
        backup_info = backup.lstat()
        if (not stat.S_ISREG(backup_info.st_mode) or backup_info.st_uid != os.getuid()
                or backup_info.st_nlink != 1):
            raise ValueError('Desktop review backup must be an owned unaliased regular file')
        backup_fd = os.open(backup, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(backup_fd, 'rb') as stream:
            backup_raw = stream.read(2 * 1024 * 1024 + 1)
        if (sha(data['original'].encode()) != original_record['sha256']
                or sha(backup_raw) != original_record['sha256']):
            raise ValueError('Desktop review backup changed')
    else:
        raise ValueError('Unsupported Desktop review config baseline')
    if (sha(data['installed'].encode()) != plan['expected']['config.toml']['sha256']
            or not equal(delta(data['installed'], data['observed'],
                               hook_source=str(Path(plan['home']) / '.codex/hooks.json')), data['changes'])
            or overlay(data['original'], data['changes']) != data['rollback']):
        raise ValueError('Desktop review disagrees with the verified installation')
    return data
