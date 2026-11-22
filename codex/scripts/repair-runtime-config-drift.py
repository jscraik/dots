"""Detect and repair recurring Codex runtime config drift."""
from __future__ import annotations

from migration_scope import deployment_module, local_path_text, require_policy_path, require_policy_scope

require_policy_scope()
import argparse  # noqa: E402
import contextlib  # noqa: E402
import copy  # noqa: E402
import ctypes  # noqa: E402
import errno  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import tomllib  # noqa: E402
from collections.abc import Callable  # noqa: E402
from fnmatch import fnmatchcase  # noqa: E402
from pathlib import Path  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
_DESKTOP_SPEC = importlib.util.spec_from_file_location('repair_desktop_compatibility',
    require_policy_path(SCRIPT_DIR / 'desktop_compatibility.py'))
if _DESKTOP_SPEC is None or _DESKTOP_SPEC.loader is None:
    raise RuntimeError('Desktop compatibility helper is unavailable')
_DESKTOP_COMPATIBILITY = importlib.util.module_from_spec(_DESKTOP_SPEC)
_DESKTOP_SPEC.loader.exec_module(_DESKTOP_COMPATIBILITY)
DESKTOP_OWNED_COMPUTER_USE_PLUGIN_IDS = _DESKTOP_COMPATIBILITY.DESKTOP_OWNED_COMPUTER_USE_PLUGIN_IDS
computer_use_plugin_preservation_errors = _DESKTOP_COMPATIBILITY.computer_use_plugin_preservation_errors
CONFIG_PATH = (deployment_module().ROOT / 'codex' if deployment_module() is not None else SCRIPT_DIR.parent) / 'config.toml'
SCHEMA_VERSION = 'runtime-config-drift-repair/v1'
SERVICE = 'runtime-config-drift-repair'
EXPECTED_APPROVALS_REVIEWER = 'auto_review'
DESKTOP_PRESENTATION_VALUES = {'model_verbosity': frozenset({'low', 'medium', 'high'}), 'model_reasoning_summary': frozenset({'auto', 'concise', 'detailed', 'none'})}
MANAGED_ROOT_STRINGS = ('model', 'developer_instructions', 'plan_mode_reasoning_effort', 'model_verbosity', 'experimental_compact_prompt_file')
MANAGED_ROOT_STRING_LISTS = ('project_doc_fallback_filenames',)
MANAGED_DESKTOP_STRINGS = ('git-pr-watch-instructions', 'git-commit-instructions', 'git-pr-instructions')
LEGACY_NODE_REPL_ENV_KEYS = ('BROWSER_USE_CODEX_APP_VERSION', 'SKY_CUA_SERVICE_PATH', 'NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S', 'NODE_REPL_TRUSTED_CODE_PATHS', 'NODE_REPL_NODE_MODULE_DIRS', 'NODE_REPL_NODE_PATH', 'CODEX_NODE_REPL_TRUSTED_SERVICES', 'NODE_REPL_UNTRUSTED_ENV_ALLOWLIST', 'BROWSER_USE_AVAILABLE_BACKENDS', 'BROWSER_USE_CODEX_APP_BUILD_FLAVOR', 'CODEX_CLI_PATH')
DESKTOP_RUNTIME_ENV_NAMES = ('CUA_REPL_ENABLED_SURFACES', 'NODE_REPL_UNTRUSTED_ENV_ALLOWLIST', 'NODE_REPL_TRUSTED_SERVICES', 'NODE_REPL_JS_BANNER', 'NODE_REPL_TRUSTED_RPC_ENABLED', 'NODE_REPL_NODE_MODULE_DIRS', 'NODE_REPL_TRUSTED_CODE_PATHS', 'BROWSER_USE_TINYSKY_ENABLED')
REQUIRED_SHELL_ENV_INCLUDE_ONLY = ('CODEX_HOME', 'CODEX_AUTH_ENVIRONMENT_ID', *DESKTOP_RUNTIME_ENV_NAMES)
UNIFIED_COMPUTER_USE_PLUGIN_ROOT = Path(os.environ.get('CODEX_UNIFIED_COMPUTER_USE_PLUGIN_ROOT', '/Applications/ChatGPT.app/Contents/Resources/plugins/openai-bundled/plugins/unified-computer-use')).expanduser()
UNIFIED_COMPUTER_USE_NODE_PATH = Path(os.environ.get('CODEX_UNIFIED_COMPUTER_USE_NODE_PATH', '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node')).expanduser()
UNIFIED_COMPUTER_USE_NODE_REPL_PATH = Path(os.environ.get('CODEX_UNIFIED_COMPUTER_USE_NODE_REPL_PATH', '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl')).expanduser()
RETIRED_MACOS_ONEPASSWORD_SOCKET = local_path_text('@HOME@/Library/Group Containers/2BUA8C4S2C.com.1password/t/s.sock')
CANONICAL_MACOS_ONEPASSWORD_AGENT_SOCKET = local_path_text('@HOME@/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock')
ONEPASSWORD_SOCKET_PATHS = (RETIRED_MACOS_ONEPASSWORD_SOCKET, CANONICAL_MACOS_ONEPASSWORD_AGENT_SOCKET)
CIRCLECI_CLI_TELEMETRY_OPTOUT = 'CIRCLECI_CLI_TELEMETRY_OPTOUT'
CIRCLECI_CLI_TELEMETRY_OPTOUT_VALUE = '1'
NETWORKED_PERMISSION_PROFILES = ('workspace-net', 'readonly-net')
LEGACY_PINNED_CUA_SHA256 = '149d490fc3e32e510f3b9d7926334d276315f9d6af78c6fe35edac73dd459b45'
LEGACY_CUA_DRIFT = 'legacy_repository_pinned_cua_requires_cutover'
LEGACY_CUA_CUTOVER = "The runtime matches the retired repository-pinned cua_repl table. No desktop registration was changed. Back up this config, verify the table's repository provenance, and obtain approval for a one-time removal of only that table and its env subtable; then use Desktop's supported activation path. Make intentional settings changes in the canonical repository config; subsequent reconciliation preserves Desktop-owned Computer Use plugin consent."
DESKTOP_OWNED_PLUGIN_IDS = DESKTOP_OWNED_COMPUTER_USE_PLUGIN_IDS

def _has_legacy_pinned_cua(config: dict[str, object]) -> bool:
    """Recognize only the full historical launcher, never a partial match."""
    servers = config.get('mcp_servers')
    server = servers.get('cua_repl') if isinstance(servers, dict) else None
    if not isinstance(server, dict):
        return False
    try:
        serialized = json.dumps(server, sort_keys=True, separators=(',', ':'))
    except (TypeError, ValueError):
        return False
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest() == LEGACY_PINNED_CUA_SHA256

def _has_retired_notify(config: dict[str, object]) -> bool:
    """Identify the already-retired client notifier without claiming MCP ownership."""
    notify = config.get('notify')
    return isinstance(notify, list) and any(isinstance(part, str) and 'SkyComputerUseClient' in part for part in notify)

def _remove_retired_notify(text: str) -> tuple[str, bool, str | None]:
    """Remove a root assignment only after parsed proof preserves every other field."""
    config, error = _loads_toml(text)
    if config is None:
        return (text, False, f'notify cleanup cannot parse config: {error}')
    if not _has_retired_notify(config):
        return (text, False, None)
    expected = dict(config)
    del expected['notify']
    lines = text.splitlines(keepends=True)
    assignment = re.compile('^[ \\t]*(?:notify|"notify"|\'notify\')[ \\t]*=')
    for start, line in enumerate(lines):
        if not assignment.match(line):
            continue
        for end in range(start + 1, len(lines) + 1):
            candidate = ''.join(lines[:start] + lines[end:])
            parsed, _ = _loads_toml(candidate)
            if _same_toml_values(parsed, expected):
                return (candidate, True, None)
    return (text, False, 'cannot safely remove retired root notify assignment')

def _same_toml_values(left: object, right: object) -> bool:
    """Compare parsed state without Python's bool/int or int/float coercion."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all((_same_toml_values(value, right[key]) for key, value in left.items()))
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all((_same_toml_values(a, b) for a, b in zip(left, right)))
    if isinstance(left, float) and math.isnan(left) and math.isnan(right):
        return True
    return left == right

def _without_desktop_owned_plugins(config: dict[str, object]) -> dict[str, object]:
    """Compare repository settings without Desktop's Computer Use consent."""
    result = copy.deepcopy(config)
    plugins = result.get('plugins')
    if isinstance(plugins, dict):
        for plugin_id in DESKTOP_OWNED_PLUGIN_IDS:
            plugins.pop(plugin_id, None)
        if not plugins:
            result.pop('plugins')
    return result

def _invalid_presentation(config: dict[str, object]) -> list[str]:
    return [key for key, choices in DESKTOP_PRESENTATION_VALUES.items() if key in config and (not isinstance(config[key], str) or config[key] not in choices)]

def _with_desktop_presentation(canonical_text: str, runtime: dict[str, object]) -> tuple[str | None, str | None]:
    """Preserve validated preferences, including absence meaning model default."""
    for key in DESKTOP_PRESENTATION_VALUES:
        if key in runtime:
            canonical_text, _, error = _ensure_managed_assignment(canonical_text, key, runtime[key])
            if error:
                return (None, error)
            continue
        parsed, _ = _loads_toml(canonical_text)
        assert parsed is not None
        if key not in parsed:
            continue
        expected = copy.deepcopy(parsed)
        del expected[key]
        lines = canonical_text.splitlines(keepends=True)
        assignment = re.compile(f"""^[ \\t]*(?:{key}|"{key}"|'{key}')[ \\t]*=""")
        for start, line in enumerate(lines):
            if not assignment.match(line):
                continue
            for end in range(start + 1, len(lines) + 1):
                candidate = ''.join(lines[:start] + lines[end:])
                state, _ = _loads_toml(candidate)
                if _same_toml_values(state, expected):
                    canonical_text = candidate
                    break
            else:
                continue
            break
        else:
            return (None, f'cannot preserve default for {key} without changing policy')
    return (canonical_text, None)

def _runtime_matches_canonical_policy(runtime_text: str, canonical_text: str) -> bool:
    runtime, _ = _loads_toml(runtime_text)
    canonical, _ = _loads_toml(canonical_text)
    if (runtime is None or canonical is None or _invalid_presentation(runtime)
            or _invalid_presentation(canonical)
            or computer_use_plugin_preservation_errors(runtime)):
        return False
    runtime = copy.deepcopy(runtime)
    canonical = copy.deepcopy(canonical)
    for key in DESKTOP_PRESENTATION_VALUES:
        runtime.pop(key, None)
        canonical.pop(key, None)
    canonical_plugins = canonical.get('plugins') if isinstance(canonical, dict) else None
    if isinstance(canonical_plugins, dict) and any(plugin_id in canonical_plugins for plugin_id in DESKTOP_OWNED_PLUGIN_IDS):
        return False
    policy_matches = isinstance(runtime, dict) and isinstance(canonical, dict) and _same_toml_values(_without_desktop_owned_plugins(runtime), _without_desktop_owned_plugins(canonical))
    if not policy_matches:
        return False
    runtime_plugins = runtime.get('plugins') if isinstance(runtime, dict) else None
    if isinstance(runtime_plugins, dict) and any(plugin_id in runtime_plugins for plugin_id in DESKTOP_OWNED_PLUGIN_IDS):
        _, preservation_error = _canonical_with_desktop_plugins(canonical_text, runtime_text)
        return preservation_error is None
    return True

def _canonical_with_desktop_plugins(canonical_text: str, runtime_text: str) -> tuple[str | None, str | None]:
    """Preserve Desktop consent and presentation on a canonical policy snapshot."""
    runtime, runtime_error = _loads_toml(runtime_text)
    canonical, canonical_error = _loads_toml(canonical_text)
    if runtime is None or canonical is None:
        return (None, runtime_error or canonical_error or 'invalid TOML')
    if isinstance(runtime.get('hooks'), dict) and 'state' in runtime['hooks']:
        return (None, 'native hook consent requires an explicit installation-bound preservation review')
    if _invalid_presentation(runtime) or _invalid_presentation(canonical):
        return (None, 'invalid Desktop presentation preference')
    plugin_errors = computer_use_plugin_preservation_errors(runtime)
    if plugin_errors:
        return (None, '; '.join(plugin_errors))
    canonical_text, preference_error = _with_desktop_presentation(canonical_text, runtime)
    if canonical_text is None:
        return (None, preference_error)
    canonical, _ = _loads_toml(canonical_text)
    assert canonical is not None
    runtime_plugins = runtime.get('plugins')
    canonical_plugins = canonical.get('plugins', {})
    if runtime_plugins is None:
        runtime_plugins = {}
    if not isinstance(canonical_plugins, dict):
        return (None, 'canonical plugins must be a TOML table')
    if not isinstance(runtime_plugins, dict):
        runtime_plugins = {}
    owned = {plugin_id: runtime_plugins[plugin_id] for plugin_id in DESKTOP_OWNED_PLUGIN_IDS if plugin_id in runtime_plugins}
    if any(plugin_id in canonical_plugins for plugin_id in DESKTOP_OWNED_PLUGIN_IDS):
        return (None, 'canonical config must not declare Desktop-owned Computer Use plugins')
    if not owned:
        return (canonical_text, None)
    sections: list[str] = []
    lines = runtime_text.splitlines(keepends=True)
    start: int | None = None
    for index, line in enumerate(lines):
        if not line.lstrip(' \t').startswith('['):
            continue
        parsed_header, _ = _loads_toml(line)
        if parsed_header is None:
            continue
        header_plugins = parsed_header.get('plugins')
        owned_header = isinstance(header_plugins, dict) and any(plugin_id in header_plugins for plugin_id in owned)
        if start is None and (not owned_header):
            continue
        if _loads_toml(''.join(lines[:index]))[0] is not None:
            if start is not None:
                sections.append(''.join(lines[start:index]))
                start = None
            if owned_header:
                start = index
    if start is not None:
        sections.append(''.join(lines[start:]))
    if not sections:
        return (None, 'cannot locate Desktop-owned Computer Use plugin tables')
    candidate = canonical_text.rstrip('\n') + '\n\n' + ''.join(sections)
    parsed, parse_error = _loads_toml(candidate)
    expected = copy.deepcopy(canonical)
    expected_plugins = expected.setdefault('plugins', {})
    assert isinstance(expected_plugins, dict)
    expected_plugins.update(owned)
    if parsed is None or not _same_toml_values(parsed, expected):
        return (None, f"Desktop-owned plugin preservation failed: {parse_error or 'parsed values changed'}")
    return (candidate, None)

class CanonicalSourceUnavailable(RuntimeError):
    """The tracked source cannot safely provide protected runtime expectations."""

def discover_installed_unified_computer_use_contract() -> list[str]:
    """Validate the installed app-owned CUA launcher without importing it."""
    errors: list[str] = []
    manifest_path = UNIFIED_COMPUTER_USE_PLUGIN_ROOT / '.mcp.json'
    launch_path = UNIFIED_COMPUTER_USE_PLUGIN_ROOT / 'scripts' / 'launch.mjs'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        server = manifest['mcpServers']['cua_repl']
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        errors.append(f'unified Computer Use manifest is unavailable or invalid: {exc}')
        server = None
    expected_server = {'command': 'node', 'args': ['scripts/launch.mjs'], 'enabled': False, 'enabled_tools': ['js', 'js_reset'], 'omit_tools_from': ['code_mode', 'deferred'], 'startup_timeout_sec': 120}
    if not isinstance(server, dict):
        errors.append('unified Computer Use manifest cua_repl must be a table')
    else:
        for key, expected in expected_server.items():
            if server.get(key) != expected:
                errors.append(f'unified Computer Use manifest cua_repl.{key} must be {expected!r}')
    try:
        launch_text = launch_path.read_text(encoding='utf-8')
    except OSError as exc:
        errors.append(f'unified Computer Use launcher is unavailable: {exc}')
        launch_text = ''
    for required_fragment in ('CUA_REPL_NODE_REPL_PATH', 'NODE_REPL_TRUSTED_SERVICES', 'browser: "@oai/browser-desktop/service"', 'sky: "@oai/sky/service"'):
        if required_fragment not in launch_text:
            errors.append(f'unified Computer Use launcher must contain {required_fragment!r}')
    for executable in (UNIFIED_COMPUTER_USE_NODE_PATH, UNIFIED_COMPUTER_USE_NODE_REPL_PATH):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            errors.append(f'unified Computer Use executable is unavailable: {executable}')
    return errors

def _toml_value(value: object) -> str:
    return json.dumps(value)

def _table_pattern(table_name: str) -> re.Pattern[str]:
    escaped = re.escape(table_name)
    return re.compile(f'(?ms)^\\[{escaped}\\][ \\t]*(?:#[^\\n]*)?(?:\\n|\\Z)(?P<body>.*?)(?=^\\[[^\\n]+\\][ \\t]*(?:#[^\\n]*)?(?:\\n|\\Z)|\\Z)')

def _loads_toml(text: str) -> tuple[dict[str, object] | None, str | None]:
    try:
        return (tomllib.loads(text), None)
    except tomllib.TOMLDecodeError as exc:
        return (None, str(exc))

def _canonical_control_settings() -> dict[str, object]:
    """Return the small canonical-owned runtime control-plane subset."""
    try:
        config, parse_error = _loads_toml(CONFIG_PATH.read_text(encoding='utf-8'))
    except OSError as exc:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: {exc}') from exc
    if parse_error is not None or not isinstance(config, dict):
        raise CanonicalSourceUnavailable(f"{CONFIG_PATH}: {parse_error or 'invalid TOML'}")
    features = config.get('features')
    agents = config.get('agents')
    desktop = config.get('desktop')
    settings = {**{key: config.get(key) for key in (*MANAGED_ROOT_STRINGS, *MANAGED_ROOT_STRING_LISTS)}, 'features.network_proxy': features.get('network_proxy') if isinstance(features, dict) else None, 'agents.max_depth': agents.get('max_depth') if isinstance(agents, dict) else None, 'agents.interrupt_message': agents.get('interrupt_message') if isinstance(agents, dict) else None, 'desktop.git-pr-watch-auto-merge': desktop.get('git-pr-watch-auto-merge') if isinstance(desktop, dict) else None, **{f'desktop.{key}': desktop.get(key) if isinstance(desktop, dict) else None for key in MANAGED_DESKTOP_STRINGS}}
    if not isinstance(settings['model'], str):
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: canonical model is missing')
    if settings['features.network_proxy'] is not True:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: features.network_proxy must be true')
    if type(settings['agents.max_depth']) is not int:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: agents.max_depth is missing')
    if settings['agents.interrupt_message'] is not True:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: agents.interrupt_message must be true')
    if type(settings['desktop.git-pr-watch-auto-merge']) is not bool:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: desktop.git-pr-watch-auto-merge must be a boolean')
    for key in (*MANAGED_ROOT_STRINGS, *(f'desktop.{key}' for key in MANAGED_DESKTOP_STRINGS)):
        value = settings[key]
        if not isinstance(value, str) or not value.strip():
            raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: {key} must be a non-empty string')
    for key in MANAGED_ROOT_STRING_LISTS:
        value = settings[key]
        if not isinstance(value, list) or not value or any(not isinstance(name, str) or not name.strip() or name in {'.', '..'} or ('/' in name) or ('\\' in name) for name in value):
            raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: {key} must be a list of non-empty filenames')
    for key, value in _permission_descriptions(config).items():
        if not isinstance(value, str) or not value.strip():
            raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: {key} must be a non-empty string')
        settings[key] = value
    permissions = config.get('permissions')
    for name in NETWORKED_PERMISSION_PROFILES:
        profile = permissions.get(name) if isinstance(permissions, dict) else None
        description = profile.get('description') if isinstance(profile, dict) else None
        if not isinstance(description, str) or not description.strip():
            raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: permissions.{name}.description must be a non-empty string')
        settings[f'permissions.{name}.description'] = description
        roots = profile.get('workspace_roots') if isinstance(profile, dict) else None
        if not isinstance(roots, dict) or not roots or any((not isinstance(path, str) or not path or access is not True for path, access in roots.items())):
            raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: permissions.{name}.workspace_roots is invalid')
        settings[f'permissions.{name}.workspace_roots'] = roots
    return settings

def _permission_descriptions(config: dict[str, object]) -> dict[str, object]:
    """Select display labels only, never permission grants or profile defaults."""
    permissions = config.get('permissions')
    if not isinstance(permissions, dict):
        return {}
    return {f'permissions.{name}.description': profile['description'] for name in NETWORKED_PERMISSION_PROFILES if isinstance((profile := permissions.get(name)), dict) and 'description' in profile}

def _incomplete_label_profiles(config: dict[str, object], expected: dict[str, object]) -> list[str]:
    """Reject incomplete grant structures; label maintenance cannot rebuild them."""
    permissions = config.get('permissions')
    failures: list[str] = []
    for name in NETWORKED_PERMISSION_PROFILES:
        if f'permissions.{name}.description' not in expected:
            continue
        profile = permissions.get(name) if isinstance(permissions, dict) else None
        if not isinstance(profile, dict):
            failures.append(f'permissions.{name}.incomplete_profile')
            continue
        roots = profile.get('workspace_roots')
        required_roots = expected.get(f'permissions.{name}.workspace_roots', {})
        network = profile.get('network')
        domains = network.get('domains') if isinstance(network, dict) else None
        if profile.get('extends') != (':workspace' if name == 'workspace-net' else ':read-only') or not isinstance(roots, dict) or (not roots) or any((not isinstance(path, str) or not path or type(access) is not bool for path, access in roots.items())) or (not isinstance(required_roots, dict)) or any((roots.get(path) is not access for path, access in required_roots.items())) or (not isinstance(network, dict)) or (network.get('enabled') is not True) or (network.get('allow_local_binding') is not True) or (not isinstance(domains, dict)) or (domains.get('*') == 'allow') or any(domains.get(host) != 'allow' for host in ('localhost', '127.0.0.1')):
            failures.append(f'permissions.{name}.incomplete_profile')
    return failures

def _canonical_auto_review_policy() -> str | None:
    """Read the protected auto-review policy from the tracked source."""
    try:
        config, parse_error = _loads_toml(CONFIG_PATH.read_text(encoding='utf-8'))
    except OSError as exc:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: {exc}') from exc
    if parse_error is not None or not isinstance(config, dict):
        raise CanonicalSourceUnavailable(f"{CONFIG_PATH}: {parse_error or 'invalid TOML'}")
    auto_review = config.get('auto_review')
    if 'auto_review' not in config or (isinstance(auto_review, dict) and 'policy' not in auto_review):
        return None
    policy = auto_review.get('policy') if isinstance(auto_review, dict) else None
    if not isinstance(policy, str) or not policy:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: auto_review.policy is missing or invalid')
    return policy

def _canonical_signing_agent_socket() -> str | None:
    """Read the protected signing-agent socket contract from tracked source."""
    try:
        config, parse_error = _loads_toml(CONFIG_PATH.read_text(encoding='utf-8'))
    except OSError as exc:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: {exc}') from exc
    if parse_error is not None or not isinstance(config, dict):
        raise CanonicalSourceUnavailable(f"{CONFIG_PATH}: {parse_error or 'invalid TOML'}")
    shell_policy = config.get('shell_environment_policy')
    env_set = shell_policy.get('set') if isinstance(shell_policy, dict) else None
    if not isinstance(env_set, dict) or 'SSH_AUTH_SOCK' not in env_set:
        return None
    socket_path = env_set.get('SSH_AUTH_SOCK')
    if socket_path != CANONICAL_MACOS_ONEPASSWORD_AGENT_SOCKET:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: shell_environment_policy.set.SSH_AUTH_SOCK is missing or noncanonical')
    return socket_path

def _canonical_circle_no_telemetry() -> str:
    """Read the protected CircleCI sandbox startup setting from tracked source."""
    try:
        config, parse_error = _loads_toml(CONFIG_PATH.read_text(encoding='utf-8'))
    except OSError as exc:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: {exc}') from exc
    if parse_error is not None or not isinstance(config, dict):
        raise CanonicalSourceUnavailable(f"{CONFIG_PATH}: {parse_error or 'invalid TOML'}")
    shell_policy = config.get('shell_environment_policy')
    env_set = shell_policy.get('set') if isinstance(shell_policy, dict) else None
    value = env_set.get(CIRCLECI_CLI_TELEMETRY_OPTOUT) if isinstance(env_set, dict) else None
    if value != CIRCLECI_CLI_TELEMETRY_OPTOUT_VALUE:
        raise CanonicalSourceUnavailable(f'{CONFIG_PATH}: shell_environment_policy.set.{CIRCLECI_CLI_TELEMETRY_OPTOUT} is missing or noncanonical')
    return value

def _has_protected_shell_env_pattern(pattern: str) -> bool:
    """Block wildcard/case aliases; exact names follow the inheritance policy."""
    protected = (*LEGACY_NODE_REPL_ENV_KEYS, *DESKTOP_RUNTIME_ENV_NAMES, 'SSH_AUTH_SOCK')
    if pattern in protected:
        return False
    wildcard = pattern.casefold().replace('[', '[[]')
    return any(fnmatchcase(name.casefold(), wildcard) for name in protected)

def detect_drift(text: str, expected_env: dict[str, str] | None=None, *, expected_shell_env: dict[str, str] | None=None, include_missing_env: bool=False, expected_auto_review_policy: str | None=None, expected_signing_agent_socket: str | None=None, expected_circle_no_telemetry: str | None=None, expected_control_settings: dict[str, object] | None=None) -> list[str]:
    config, parse_error = _loads_toml(text)
    if config is None:
        return [f'toml_parse_error:{parse_error}']
    drift: list[str] = _invalid_presentation(config)
    features = config.get('features')
    if isinstance(features, dict) and 'context_management' in features:
        drift.append('features.context_management')
    if _has_legacy_pinned_cua(config):
        drift.append(LEGACY_CUA_DRIFT)
    if _has_retired_notify(config):
        drift.append('notify.SkyComputerUseClient')
    if expected_control_settings is not None:
        drift.extend(_incomplete_label_profiles(config, expected_control_settings))
        features = config.get('features')
        agents = config.get('agents')
        desktop = config.get('desktop')
        actual_control_settings = {**_permission_descriptions(config), **{key: config.get(key) for key in (*MANAGED_ROOT_STRINGS, *MANAGED_ROOT_STRING_LISTS)}, 'features.network_proxy': features.get('network_proxy') if isinstance(features, dict) else None, 'agents.max_depth': agents.get('max_depth') if isinstance(agents, dict) else None, 'agents.interrupt_message': agents.get('interrupt_message') if isinstance(agents, dict) else None, 'desktop.git-pr-watch-auto-merge': desktop.get('git-pr-watch-auto-merge') if isinstance(desktop, dict) else None, **{f'desktop.{key}': desktop.get(key) if isinstance(desktop, dict) else None for key in MANAGED_DESKTOP_STRINGS}}
        for key, expected in expected_control_settings.items():
            if key in DESKTOP_PRESENTATION_VALUES:
                continue
            if key.endswith('.workspace_roots'):
                continue
            if not _same_toml_values(actual_control_settings.get(key), expected):
                drift.append(key)
    projects = config.get('projects')
    if isinstance(projects, dict):
        for project_path in projects:
            if not isinstance(project_path, str):
                continue
            if project_path.startswith(('/private/var/folders/', '/tmp/')) and (not Path(project_path).exists()):
                drift.append(f'projects.ephemeral_missing:{project_path}')
    if config.get('approvals_reviewer') != EXPECTED_APPROVALS_REVIEWER:
        drift.append('approvals_reviewer')
    auto_review = config.get('auto_review')
    if 'auto_review' in config and (not isinstance(auto_review, dict)):
        drift.append('auto_review.invalid_type')
    policy = auto_review.get('policy') if isinstance(auto_review, dict) else None
    if policy != expected_auto_review_policy:
        drift.append('auto_review.policy')
    shell_policy = config.get('shell_environment_policy')
    if not isinstance(shell_policy, dict) or shell_policy.get('inherit') != 'all':
        drift.append('shell_environment_policy.inherit')
    if not isinstance(shell_policy, dict) or shell_policy.get('ignore_default_excludes') is not False:
        drift.append('shell_environment_policy.ignore_default_excludes')
    include_only = shell_policy.get('include_only') if isinstance(shell_policy, dict) else None
    if not isinstance(include_only, list) or any(key not in include_only for key in REQUIRED_SHELL_ENV_INCLUDE_ONLY):
        drift.append('shell_environment_policy.include_only.required')
    if isinstance(include_only, list) and any(key in include_only and key not in DESKTOP_RUNTIME_ENV_NAMES for key in LEGACY_NODE_REPL_ENV_KEYS):
        drift.append('shell_environment_policy.include_only.legacy_node_repl')
    if isinstance(include_only, list) and 'SSH_AUTH_SOCK' in include_only:
        drift.append('shell_environment_policy.include_only.SSH_AUTH_SOCK')
    if isinstance(include_only, list) and any(not isinstance(key, str) or re.match('[A-Za-z_]', key) is None or _has_protected_shell_env_pattern(key) for key in include_only):
        drift.append('shell_environment_policy.include_only.unsafe')
    shell_set = shell_policy.get('set') if isinstance(shell_policy, dict) else None
    if isinstance(shell_set, dict) and any(key in shell_set for key in (*LEGACY_NODE_REPL_ENV_KEYS, *DESKTOP_RUNTIME_ENV_NAMES)):
        drift.append('shell_environment_policy.set.legacy_node_repl')
    expected_socket = expected_signing_agent_socket
    if expected_socket is None:
        try:
            expected_socket = _canonical_signing_agent_socket()
        except CanonicalSourceUnavailable as exc:
            drift.append(f'shell_environment_policy.set.SSH_AUTH_SOCK canonical_source_unavailable:{exc}')
    if expected_socket is not None and (not isinstance(shell_set, dict) or shell_set.get('SSH_AUTH_SOCK') != expected_socket) or (expected_socket is None and isinstance(shell_set, dict) and ('SSH_AUTH_SOCK' in shell_set)):
        drift.append('shell_environment_policy.set.SSH_AUTH_SOCK')
    if expected_circle_no_telemetry is not None and (not isinstance(shell_set, dict) or shell_set.get(CIRCLECI_CLI_TELEMETRY_OPTOUT) != expected_circle_no_telemetry):
        drift.append(f'shell_environment_policy.set.{CIRCLECI_CLI_TELEMETRY_OPTOUT}')
    features = config.get('features')
    if isinstance(features, dict) and 'js_repl' in features:
        drift.append('features.js_repl')
    permissions = config.get('permissions')
    for profile_name in NETWORKED_PERMISSION_PROFILES:
        profile = permissions.get(profile_name) if isinstance(permissions, dict) else None
        network = profile.get('network') if isinstance(profile, dict) else None
        unix_sockets = network.get('unix_sockets') if isinstance(network, dict) else None
        if isinstance(unix_sockets, dict) and any(socket_path in unix_sockets for socket_path in ONEPASSWORD_SOCKET_PATHS):
            drift.append(f'permissions.{profile_name}.network.unix_sockets.1password')
        if isinstance(network, dict) and network.get('dangerously_allow_all_unix_sockets'):
            drift.append(f'permissions.{profile_name}.network.dangerously_allow_all_unix_sockets')
    return drift

def _ensure_managed_assignment(text: str, key: str, value: object, *, table: str | None=None) -> tuple[str, bool, str | None]:
    """Replace one parsed assignment only when every other TOML value survives.

    Instruction strings can contain table headers, quotes, and comments. Prove
    the complete candidate against parsed expected state instead of treating
    those contents as structure or trusting a regex-selected section.
    """
    config, error = _loads_toml(text)
    label = f'{table}.{key}' if table else key
    if not isinstance(value, str) and (not (table is None and isinstance(value, list) and all(isinstance(item, str) for item in value))):
        return (text, False, f'{label} requires a string or root string list')
    if config is None:
        return (text, False, f'{label} cannot parse config: {error}')
    owner = config
    for part in table.split('.') if table else ():
        child = owner.get(part, {})
        if not isinstance(child, dict):
            return (text, False, f'{table} must be a table')
        owner = child
    if not isinstance(owner, dict):
        return (text, False, f'{table} must be a table')
    if owner.get(key) == value:
        return (text, False, None)
    old_value = owner.get(key)
    if key in owner and (type(old_value) is not type(value) or (isinstance(old_value, list) and (not all(isinstance(item, str) for item in old_value)))):
        return (text, False, f'{label} must retain its managed value type')
    expected = copy.deepcopy(config)
    target = expected
    for part in table.split('.') if table else ():
        child = target.setdefault(part, {})
        if not isinstance(child, dict):
            return (text, False, f'{table} must be a table')
        target = child
    target[key] = value
    rendered = f'{key} = {_toml_value(value)}\n'
    if key not in owner:
        if table is None:
            candidate = rendered + text
        elif isinstance(value, str):
            candidate, _, _ = _ensure_table_string(text, table, key, value)
        else:
            return (text, False, f'{label} string lists must be root assignments')
        parsed, _ = _loads_toml(candidate)
        if _same_toml_values(parsed, expected):
            return (candidate, True, None)
        return (text, False, f'{label} cannot be inserted without changing other fields')
    lines = text.splitlines(keepends=True)
    assignment = re.compile(f"""^[ \\t]*(?:{re.escape(key)}|"{re.escape(key)}"|'{re.escape(key)}')[ \\t]*=""")
    for start, line in enumerate(lines):
        if not assignment.match(line):
            continue
        for end in range(start + 1, len(lines) + 1):
            existing = ''.join(lines[start:end])
            parsed_assignment, _ = _loads_toml(existing)
            if parsed_assignment is None:
                continue
            if not _same_toml_values(parsed_assignment, {key: old_value}):
                break
            comment = _trailing_toml_comment(existing, 'assignment', key, old_value)
            indent = line[:len(line) - len(line.lstrip())]
            replacement = indent + rendered.rstrip('\n')
            if comment is not None:
                replacement += ' ' + comment
            if existing.endswith('\n'):
                replacement += '\n'
            candidate = ''.join(lines[:start]) + replacement + ''.join(lines[end:])
            parsed, _ = _loads_toml(candidate)
            if _same_toml_values(parsed, expected):
                return (candidate, True, None)
            break
    return (text, False, f'{label} cannot be replaced without changing other fields')

def _ensure_root_string(text: str, key: str, value: str) -> tuple[str, bool]:
    """Set one root TOML string without reserializing unrelated runtime state."""
    lines = text.splitlines(keepends=True)
    root_end = len(lines)
    for index, line in enumerate(lines):
        if line.lstrip().startswith('['):
            root_end = index
            break
    for index, line in enumerate(lines[:root_end]):
        if '=' not in line:
            continue
        raw_key, raw_value = line.split('=', 1)
        if raw_key.strip() != key:
            continue
        comment = ''
        if '#' in raw_value:
            _, comment_value = raw_value.split('#', 1)
            comment = f' #{comment_value}'
        newline = '\n' if line.endswith('\n') else ''
        indent = line[:len(line) - len(line.lstrip())]
        replacement = f'{indent}{key} = {_toml_value(value)}{comment}{newline}'
        if line == replacement:
            return (text, False)
        lines[index] = replacement
        return (''.join(lines), True)
    lines.insert(root_end, f'{key} = {_toml_value(value)}\n')
    return (''.join(lines), True)

def _ensure_table_scalar(text: str, table_name: str, key: str, value: object) -> tuple[str, bool, str | None]:
    """Set one scalar in an existing TOML table without reserializing it."""
    table_match = _table_pattern(table_name).search(text)
    if table_match is None:
        separator = '' if not text or text.endswith('\n\n') else '\n'
        return (f'{text}{separator}[{table_name}]\n{key} = {_toml_value(value)}\n', True, None)
    body = table_match.group('body')
    key_pattern = re.compile(f'(?m)^(?P<indent>[ \\t]*){re.escape(key)}[ \\t]*=[ \\t]*(?P<value>[^#\\n]+?)[ \\t]*(?P<tail>#.*)?$')
    key_match = key_pattern.search(body)
    rendered = f'{key} = {_toml_value(value)}'
    if key_match is not None:
        replacement = f"{key_match.group('indent')}{rendered}"
        if key_match.group('tail'):
            replacement = f"{replacement} {key_match.group('tail')}"
        new_body, count = key_pattern.subn(replacement, body, count=1)
        if count == 0 or new_body == body:
            return (text, False, None)
        return (text[:table_match.start('body')] + new_body + text[table_match.end('body'):], True, None)
    new_body = f'{rendered}\n{body}'
    return (text[:table_match.start('body')] + new_body + text[table_match.end('body'):], True, None)

def _trailing_toml_comment(assignment: str, table_name: str, key: str, parsed_value: object) -> str | None:
    """Return a trailing comment only when it is outside the parsed TOML value."""
    without_newline = assignment.removesuffix('\n')
    for candidate in re.finditer('#', without_newline):
        uncommented = without_newline[:candidate.start()].rstrip()
        try:
            parsed = tomllib.loads(f'[{table_name}]\n{uncommented}\n')
        except tomllib.TOMLDecodeError:
            continue
        if parsed[table_name].get(key) == parsed_value:
            return without_newline[candidate.start():]
    return None

def _ensure_table_string(text: str, table_name: str, key: str, value: str) -> tuple[str, bool, str | None]:
    """Set one string in an existing TOML table without reserializing it."""
    table_match = _table_pattern(table_name).search(text)
    rendered = f'{key} = {_toml_value(value)}\n'
    if table_match is None:
        separator = '' if not text or text.endswith('\n\n') else '\n'
        return (f'{text}{separator}[{table_name}]\n{rendered}', True, None)
    body = table_match.group('body')
    multiline_pattern = re.compile(f"""(?ms)^(?P<indent>[ \\t]*){re.escape(key)}[ \\t]*=[ \\t]*(?P<quote>'''|\\"\\"\\").*?(?P=quote)[ \\t]*(?:#[^\\n]*)?(?:\\n|\\Z)""")
    multiline_match = multiline_pattern.search(body)
    if multiline_match is not None:
        existing = multiline_match.group(0)
        try:
            parsed_existing = tomllib.loads(f'[{table_name}]\n{existing}')
        except tomllib.TOMLDecodeError:
            return (text, False, f'{table_name}.{key} has invalid TOML')
        if parsed_existing[table_name][key] == value:
            return (text, False, None)
        comment = _trailing_toml_comment(existing, table_name, key, parsed_existing[table_name][key])
        replacement = f"{multiline_match.group('indent')}{rendered.rstrip()}"
        if comment is not None:
            replacement = f'{replacement} {comment}'
        if existing.endswith('\n'):
            replacement += '\n'
        new_body = multiline_pattern.sub(lambda _match: replacement, body, count=1)
        return (text[:table_match.start('body')] + new_body + text[table_match.end('body'):], True, None)
    assignment_pattern = re.compile(f'(?m)^(?P<indent>[ \\t]*){re.escape(key)}[ \\t]*=.*(?:\\n|\\Z)')
    assignment_match = assignment_pattern.search(body)
    if assignment_match is not None:
        existing = assignment_match.group(0)
        try:
            parsed_existing = tomllib.loads(f'[{table_name}]\n{existing}')
        except tomllib.TOMLDecodeError:
            return (text, False, f'{table_name}.{key} has unsupported layout')
        if not isinstance(parsed_existing[table_name].get(key), str):
            return (text, False, f'{table_name}.{key} must be a string')
        if parsed_existing[table_name][key] == value:
            return (text, False, None)
        comment = _trailing_toml_comment(existing, table_name, key, parsed_existing[table_name][key])
        replacement = f"{assignment_match.group('indent')}{rendered.rstrip()}"
        if comment is not None:
            replacement = f'{replacement} {comment}'
        if existing.endswith('\n'):
            replacement += '\n'
        new_body = assignment_pattern.sub(lambda _match: replacement, body, count=1)
        return (text[:table_match.start('body')] + new_body + text[table_match.end('body'):], True, None)
    new_body = rendered + body
    return (text[:table_match.start('body')] + new_body + text[table_match.end('body'):], True, None)

def _remove_complete_table(text: str, table_name: str) -> tuple[str, bool]:
    """Remove one exact TOML table while leaving all neighboring tables intact."""
    table_match = _table_pattern(table_name).search(text)
    if table_match is None:
        return (text, False)
    return (text[:table_match.start()] + text[table_match.end():], True)

def _remove_retired_context_management(text: str) -> tuple[str, bool, str | None]:
    """Remove the retired opt-in only when every unrelated parsed value survives."""
    parsed, error = _loads_toml(text)
    if parsed is None:
        return (text, False, f'toml_parse_error:{error}')
    features = parsed.get('features')
    if not isinstance(features, dict) or 'context_management' not in features:
        return (text, False, None)
    expected = copy.deepcopy(parsed)
    expected_features = expected['features']
    assert isinstance(expected_features, dict)
    del expected_features['context_management']
    candidates = [_remove_complete_table(text, 'features.context_management')[0], _remove_table_key(text, 'features', 'context_management')[0]]
    for candidate in candidates:
        candidate_parsed, _ = _loads_toml(candidate)
        if _same_toml_values(candidate_parsed, expected):
            return (candidate, True, None)
    return (text, False, 'features.context_management cannot be removed without changing other fields')

def _ensure_auto_review_policy(text: str, expected_policy: str | None) -> tuple[str, bool, str | None]:
    """Prepare a selective policy edit before the CLI's full canonical sync."""
    if expected_policy is None:
        parsed, parse_error = _loads_toml(text)
        if parsed is None:
            return (text, False, f'toml_parse_error:{parse_error}')
        auto_review = parsed.get('auto_review')
        if 'auto_review' in parsed and (not isinstance(auto_review, dict)):
            return (text, False, 'auto_review must be a table')
        if not isinstance(auto_review, dict) or 'policy' not in auto_review:
            return (text, False, None)
        table_match = _table_pattern('auto_review').search(text)
        if table_match is None:
            return (text, False, 'auto_review.policy has unsupported layout')
        body = table_match.group('body')
        pattern = re.compile('(?ms)^[ \\t]*policy[ \\t]*=[ \\t]*(?:(?P<quote>\'\'\'|\\"\\"\\").*?(?P=quote)|[^\\n]*)[ \\t]*(?:#.*)?(?:\\n|\\Z)')
        new_body, count = pattern.subn('', body, count=1)
        candidate = text[:table_match.start('body')] + new_body + text[table_match.end('body'):]
        expected = tomllib.loads(text)
        del expected['auto_review']['policy']
        try:
            actual = tomllib.loads(candidate)
        except tomllib.TOMLDecodeError:
            return (text, False, 'auto_review.policy has unsupported layout')
        if count != 1 or actual != expected:
            return (text, False, 'auto_review.policy removal changed unrelated settings')
        return (candidate, True, None)
    if "'''" in expected_policy:
        return (text, False, 'canonical auto_review.policy cannot be rendered safely')
    table_match = _table_pattern('auto_review').search(text)
    rendered = f"policy = '''{expected_policy}'''\n"
    if table_match is None:
        separator = '' if not text or text.endswith('\n\n') else '\n'
        return (f'{text}{separator}[auto_review]\n{rendered}', True, None)
    body = table_match.group('body')
    policy_pattern = re.compile('(?ms)^[ \\t]*policy[ \\t]*=[ \\t]*(?P<quote>\'\'\'|\\"\\"\\").*?(?P=quote)[ \\t]*(?:#.*)?(?:\\n|\\Z)')
    policy_match = policy_pattern.search(body)
    if policy_match is None:
        if re.search('(?m)^[ \\t]*policy[ \\t]*=', body):
            return (text, False, 'auto_review.policy has unsupported layout')
        new_body = rendered + body
    else:
        existing = policy_match.group(0)
        try:
            parsed_existing = tomllib.loads(f'[auto_review]\n{existing}')
        except tomllib.TOMLDecodeError:
            return (text, False, 'auto_review.policy has invalid TOML')
        if parsed_existing['auto_review']['policy'] == expected_policy:
            return (text, False, None)
        new_body = policy_pattern.sub(rendered, body, count=1)
    return (text[:table_match.start('body')] + new_body + text[table_match.end('body'):], True, None)

def _remove_features_js_repl(text: str) -> tuple[str, bool]:
    pattern = _table_pattern('features')
    match = pattern.search(text)
    if match is None:
        return (text, False)
    body = match.group('body')
    new_body, count = re.subn('(?m)^[ \\t]*js_repl[ \\t]*=.*(?:\\n|\\Z)', '', body)
    if count == 0:
        return (text, False)
    return (text[:match.start('body')] + new_body + text[match.end('body'):], True)

def _repair_shell_environment_policy(text: str) -> tuple[str, bool, bool, str | None]:
    """Keep required shell keys and remove the retired Node REPL environment."""
    lines = text.splitlines(keepends=True)
    in_policy = False
    list_start: int | None = None
    list_end: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_policy = stripped == '[shell_environment_policy]'
            if list_start is not None:
                break
            continue
        if not in_policy:
            continue
        if list_start is None and stripped.startswith('include_only') and ('=' in stripped):
            if '[' not in stripped:
                return (text, False, False, 'shell_environment_policy.include_only has unsupported layout')
            list_start = index
            if ']' in stripped.split('[', 1)[1]:
                list_end = index
                break
            continue
        if list_start is not None and ']' in stripped:
            list_end = index
            break
    if list_start is None or list_end is None:
        return (text, False, False, 'shell_environment_policy.include_only is missing')
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return (text, False, False, f'toml_parse_error:{exc}')
    policy = parsed.get('shell_environment_policy')
    include_only = policy.get('include_only') if isinstance(policy, dict) else None
    if not isinstance(include_only, list) or not all(isinstance(value, str) for value in include_only):
        return (text, False, False, 'shell_environment_policy.include_only must be a string list')
    if any(re.match('[A-Za-z_]', value) is None for value in include_only):
        return (text, False, False, 'shell_environment_policy.include_only permits unrestricted inheritance')
    if any(_has_protected_shell_env_pattern(value) for value in include_only):
        return (text, False, False, 'shell_environment_policy.include_only matches protected runtime variables')
    removed_legacy = any(value in LEGACY_NODE_REPL_ENV_KEYS and value not in DESKTOP_RUNTIME_ENV_NAMES for value in include_only)
    restored_required = any(key not in include_only for key in REQUIRED_SHELL_ENV_INCLUDE_ONLY)
    retained = [value for value in include_only if value not in LEGACY_NODE_REPL_ENV_KEYS or value in DESKTOP_RUNTIME_ENV_NAMES]
    for key in REQUIRED_SHELL_ENV_INCLUDE_ONLY:
        if key not in retained:
            retained.append(key)
    if retained == include_only:
        repaired = text
        changed = False
    elif list_start == list_end:
        line = lines[list_start]
        indent = line[:len(line) - len(line.lstrip())]
        newline = '\n' if line.endswith('\n') else ''
        lines[list_start] = f'{indent}include_only = {_toml_value(retained)}{newline}'
        repaired = ''.join(lines)
        changed = True
    else:
        indent = '  '
        rendered = [lines[list_start]]
        rendered.extend(f'{indent}{_toml_value(key)},\n' for key in retained)
        rendered.append(lines[list_end])
        lines[list_start:list_end + 1] = rendered
        repaired = ''.join(lines)
        changed = True
    for key in dict.fromkeys((*LEGACY_NODE_REPL_ENV_KEYS, *DESKTOP_RUNTIME_ENV_NAMES)):
        repaired, removed = _remove_table_key(repaired, 'shell_environment_policy.set', key)
        changed = changed or removed
        removed_legacy = removed_legacy or removed
    return (repaired, removed_legacy, restored_required, None)

def _remove_inherited_signing_agent_socket(text: str) -> tuple[str, bool, str | None]:
    """Remove SSH_AUTH_SOCK from include_only without reserializing the file."""
    parsed, parse_error = _loads_toml(text)
    if parsed is None:
        return (text, False, f'toml_parse_error:{parse_error}')
    shell_policy = parsed.get('shell_environment_policy')
    include_only = shell_policy.get('include_only') if isinstance(shell_policy, dict) else None
    if not isinstance(include_only, list):
        return (text, False, 'shell_environment_policy.include_only is missing')
    if 'SSH_AUTH_SOCK' not in include_only:
        return (text, False, None)
    lines = text.splitlines(keepends=True)
    in_policy = False
    list_start: int | None = None
    list_end: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if list_start is not None:
                break
            in_policy = stripped == '[shell_environment_policy]'
            continue
        if not in_policy:
            continue
        if list_start is None and stripped.startswith('include_only') and ('=' in stripped):
            if '[' not in stripped:
                return (text, False, 'shell_environment_policy.include_only has unsupported layout')
            list_start = index
            if ']' in stripped.split('[', 1)[1]:
                list_end = index
                break
            continue
        if list_start is not None and ']' in stripped:
            list_end = index
            break
    if list_start is None or list_end is None:
        return (text, False, 'shell_environment_policy.include_only is missing')
    if list_start == list_end:
        if 'SSH_AUTH_SOCK' not in include_only:
            return (text, False, None)
        line = lines[list_start]
        equals = line.index('=')
        value_start = line.find('[', equals)
        value_end = line.rfind(']')
        if value_start < 0 or value_end < value_start:
            return (text, False, 'shell_environment_policy.include_only has unsupported layout')
        tail = line[value_end + 1:]
        values = [value for value in include_only if value != 'SSH_AUTH_SOCK']
        lines[list_start] = f'{line[:equals + 1]} {_toml_value(values)}{tail}'
        return (''.join(lines), True, None)
    for index in range(list_start + 1, list_end):
        stripped = lines[index].strip()
        if '"SSH_AUTH_SOCK"' not in stripped:
            continue
        if stripped.rstrip(',') != '"SSH_AUTH_SOCK"':
            return (text, False, 'shell_environment_policy.include_only has unsupported layout')
        del lines[index]
        return (''.join(lines), True, None)
    return (text, False, 'shell_environment_policy.include_only.SSH_AUTH_SOCK could not be removed')

def _ensure_shell_environment_set_string(text: str, key: str, value: str) -> tuple[str, bool, str | None]:
    """Set one shell_environment_policy.set string while preserving other text."""
    parsed, parse_error = _loads_toml(text)
    if parsed is None:
        return (text, False, f'toml_parse_error:{parse_error}')
    shell_policy = parsed.get('shell_environment_policy')
    if not isinstance(shell_policy, dict):
        return (text, False, 'shell_environment_policy is missing')
    env_set = shell_policy.get('set')
    if isinstance(env_set, dict) and env_set.get(key) == value:
        return (text, False, None)
    lines = text.splitlines(keepends=True)
    header = '[shell_environment_policy.set]'
    table_start: int | None = None
    table_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if table_start is not None:
                table_end = index
                break
            if stripped == header:
                table_start = index
    rendered = f'{key} = {_toml_value(value)}\n'
    if table_start is None:
        separator = '' if not text or text.endswith('\n\n') else '\n'
        return (f'{text}{separator}{header}\n{rendered}', True, None)
    for index in range(table_start + 1, table_end):
        line = lines[index]
        if '=' not in line:
            continue
        try:
            parsed_line = tomllib.loads(line)
        except tomllib.TOMLDecodeError:
            continue
        if key not in parsed_line:
            continue
        indent = line[:len(line) - len(line.lstrip())]
        newline = '\n' if line.endswith('\n') else ''
        comment = ''
        if '#' in line.split('=', 1)[1]:
            comment = ' #' + line.split('#', 1)[1].rstrip('\n')
        lines[index] = f'{indent}{key} = {_toml_value(value)}{comment}{newline}'
        return (''.join(lines), True, None)
    lines.insert(table_end, rendered)
    return (''.join(lines), True, None)

def _remove_table_key(text: str, table_name: str, key: str) -> tuple[str, bool]:
    """Remove one exact TOML table key without reserializing mutable config."""
    lines = text.splitlines(keepends=True)
    header = f'[{table_name}]'
    in_table = False
    changed = False
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_table = stripped == header
            kept.append(line)
            continue
        if in_table and '=' in line:
            try:
                parsed_line = tomllib.loads(line)
            except tomllib.TOMLDecodeError:
                parsed_line = {}
            if key in parsed_line:
                changed = True
                continue
        kept.append(line)
    return (''.join(kept), changed)

def _split_toml_comment(line: str) -> tuple[str, str]:
    """Split one TOML line at an unquoted comment delimiter."""
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if quote is not None:
            if quote == '"' and character == '\\' and (not escaped):
                escaped = True
                continue
            if character == quote and (not escaped):
                quote = None
            escaped = False
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == '#':
            return (line[:index], line[index:])
    return (line, '')

def _remove_inline_table_entry(text: str, table_name: str, table_key: str, entry_key: str) -> tuple[str, bool]:
    """Remove one exact entry from an inline TOML table without reformatting it."""
    table_match = _table_pattern(table_name).search(text)
    if table_match is None:
        return (text, False)
    lines = table_match.group('body').splitlines(keepends=True)
    for index, line in enumerate(lines):
        try:
            parsed_line = tomllib.loads(line)
        except tomllib.TOMLDecodeError:
            continue
        inline_table = parsed_line.get(table_key)
        if not isinstance(inline_table, dict) or entry_key not in inline_table:
            continue
        remaining = {key: value for key, value in inline_table.items() if key != entry_key}
        indent = line[:len(line) - len(line.lstrip())]
        newline = '\n' if line.endswith('\n') else ''
        content = line[:-1] if newline else line
        table_content, comment = _split_toml_comment(content)
        closing_brace = table_content.rfind('}')
        if closing_brace >= 0:
            trailing_whitespace = table_content[closing_brace + 1:]
            comment = f'{trailing_whitespace}{comment}'
        rendered_entries = ', '.join((f'{_toml_value(key)} = {_toml_value(value)}' for key, value in remaining.items()))
        rendered_table = f'{{ {rendered_entries} }}' if rendered_entries else '{}'
        lines[index] = f'{indent}{table_key} = {rendered_table}{comment}{newline}'
        new_body = ''.join(lines)
        return (text[:table_match.start('body')] + new_body + text[table_match.end('body'):], True)
    return (text, False)

def repair_text(text: str, expected_env: dict[str, str] | None=None, *, expected_shell_env: dict[str, str] | None=None, include_missing_env: bool=False, expected_auto_review_policy: str | None=None, expected_signing_agent_socket: str | None=None, expected_circle_no_telemetry: str | None=None, expected_control_settings: dict[str, object] | None=None) -> tuple[str, list[str], list[str]]:
    repairs: list[str] = []
    blocked: list[str] = []
    parsed, _ = _loads_toml(text)
    text, notify_removed, notify_blocker = _remove_retired_notify(text)
    if notify_removed:
        repairs.append('notify.SkyComputerUseClient')
    if notify_blocker is not None:
        return (text, repairs, [notify_blocker])
    if parsed is not None and _has_legacy_pinned_cua(parsed):
        return (text, repairs, [LEGACY_CUA_CUTOVER])
    text, context_removed, context_blocker = _remove_retired_context_management(text)
    if context_removed:
        repairs.append('features.context_management')
    if context_blocker is not None:
        return (text, repairs, [context_blocker])
    if expected_control_settings is not None:
        if parsed is not None:
            incomplete = _incomplete_label_profiles(parsed, expected_control_settings)
            if incomplete:
                return (text, repairs, incomplete)
        for table_name, keys in ((None, (*MANAGED_ROOT_STRINGS, *MANAGED_ROOT_STRING_LISTS)), ('desktop', MANAGED_DESKTOP_STRINGS)):
            for key in keys:
                if table_name is None and key in DESKTOP_PRESENTATION_VALUES:
                    continue
                drift_key = f'{table_name}.{key}' if table_name else key
                text, changed, blocker = _ensure_managed_assignment(text, key, expected_control_settings[drift_key], table=table_name)
                if changed:
                    repairs.append(drift_key)
                if blocker is not None:
                    blocked.append(blocker)
        runtime_config, _ = _loads_toml(text)
        runtime_permissions = runtime_config.get('permissions') if isinstance(runtime_config, dict) else None
        for profile_name in NETWORKED_PERMISSION_PROFILES:
            table_name = f'permissions.{profile_name}'
            drift_key = f'{table_name}.description'
            if drift_key not in expected_control_settings:
                continue
            if not isinstance(runtime_permissions, dict) or not isinstance(runtime_permissions.get(profile_name), dict):
                continue
            text, changed, blocker = _ensure_managed_assignment(text, 'description', expected_control_settings[drift_key], table=table_name)
            if changed:
                repairs.append(drift_key)
            if blocker is not None:
                blocked.append(blocker)
        for table_name, key in (('features', 'network_proxy'), ('agents', 'max_depth'), ('agents', 'interrupt_message'), ('desktop', 'git-pr-watch-auto-merge')):
            drift_key = f'{table_name}.{key}'
            text, changed, blocker = _ensure_table_scalar(text, table_name, key, expected_control_settings[drift_key])
            if changed:
                repairs.append(drift_key)
            if blocker is not None:
                blocked.append(blocker)
    config, _parse_error = _loads_toml(text)
    projects = config.get('projects') if isinstance(config, dict) else None
    if isinstance(projects, dict):
        for project_path in list(projects):
            if not isinstance(project_path, str):
                continue
            if project_path.startswith(('/private/var/folders/', '/tmp/')) and (not Path(project_path).exists()):
                table_name = f'projects.{_toml_value(project_path)}'
                text, changed = _remove_complete_table(text, table_name)
                if changed:
                    repairs.append(f'projects.ephemeral_missing:{project_path}')
    text, changed = _ensure_root_string(text, 'approvals_reviewer', EXPECTED_APPROVALS_REVIEWER)
    if changed:
        repairs.append('approvals_reviewer')
    text, changed, blocker = _ensure_auto_review_policy(text, expected_auto_review_policy)
    if changed:
        repairs.append('auto_review.policy')
    if blocker is not None:
        blocked.append(blocker)
    text, removed_legacy, restored_required, blocker = _repair_shell_environment_policy(text)
    if removed_legacy:
        repairs.append('shell_environment_policy.legacy_node_repl')
    if restored_required:
        repairs.append('shell_environment_policy.include_only.required')
    if blocker is not None:
        blocked.append(blocker)
    else:
        text, changed, blocker = _ensure_table_string(text, 'shell_environment_policy', 'inherit', 'all')
        if changed:
            repairs.append('shell_environment_policy.inherit')
        if blocker is not None:
            blocked.append(blocker)
        text, changed, blocker = _ensure_table_scalar(text, 'shell_environment_policy', 'ignore_default_excludes', False)
        if changed:
            repairs.append('shell_environment_policy.ignore_default_excludes')
        if blocker is not None:
            blocked.append(blocker)
    if expected_circle_no_telemetry is not None:
        text, changed, blocker = _ensure_shell_environment_set_string(text, CIRCLECI_CLI_TELEMETRY_OPTOUT, expected_circle_no_telemetry)
        if changed:
            repairs.append(f'shell_environment_policy.set.{CIRCLECI_CLI_TELEMETRY_OPTOUT}')
        if blocker is not None:
            blocked.append(blocker)
    text, changed, blocker = _remove_inherited_signing_agent_socket(text)
    if changed:
        repairs.append('shell_environment_policy.include_only.SSH_AUTH_SOCK')
    if blocker is not None:
        blocked.append(blocker)
    expected_socket = _canonical_signing_agent_socket() if expected_signing_agent_socket is None else expected_signing_agent_socket
    if expected_socket is None:
        text, changed = _remove_table_key(text, 'shell_environment_policy.set', 'SSH_AUTH_SOCK')
        blocker = None
    else:
        text, changed, blocker = _ensure_shell_environment_set_string(text, 'SSH_AUTH_SOCK', expected_socket)
    if changed:
        repairs.append('shell_environment_policy.set.SSH_AUTH_SOCK')
    if blocker is not None:
        blocked.append(blocker)
    text, changed = _remove_features_js_repl(text)
    if changed:
        repairs.append('features.js_repl')
    for profile_name in NETWORKED_PERMISSION_PROFILES:
        drift_name = f'permissions.{profile_name}.network.unix_sockets.1password'
        profile_drift = detect_drift(text, include_missing_env=include_missing_env, expected_signing_agent_socket=expected_socket)
        if drift_name in profile_drift:
            changed = False
            for socket_path in ONEPASSWORD_SOCKET_PATHS:
                text, removed = _remove_table_key(text, f'permissions.{profile_name}.network.unix_sockets', socket_path)
                changed = changed or removed
                text, removed = _remove_inline_table_entry(text, f'permissions.{profile_name}.network', 'unix_sockets', socket_path)
                changed = changed or removed
            if changed:
                repairs.append(drift_name)
            else:
                blocked.append(f'{drift_name} could not be removed')
        all_sockets_drift = f'permissions.{profile_name}.network.dangerously_allow_all_unix_sockets'
        if all_sockets_drift in profile_drift:
            text, changed = _remove_table_key(text, f'permissions.{profile_name}.network', 'dangerously_allow_all_unix_sockets')
            if changed:
                repairs.append(all_sockets_drift)
            else:
                blocked.append(f'{all_sockets_drift} could not be removed')
    if text and (not text.endswith('\n')):
        text += '\n'
    return (text, repairs, blocked)

def _exchange_paths(first: Path, second: Path) -> None:
    """Atomically exchange two paths without relying on cooperative locks."""
    library = ctypes.CDLL(None, use_errno=True)
    first_bytes = os.fsencode(first)
    second_bytes = os.fsencode(second)
    if sys.platform == 'darwin':
        try:
            rename = library.renamex_np
        except AttributeError as exc:
            raise OSError(errno.ENOTSUP, 'atomic path exchange is unavailable') from exc
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(first_bytes, second_bytes, 2)
    elif sys.platform.startswith('linux'):
        try:
            rename = library.renameat2
        except AttributeError as exc:
            raise OSError(errno.ENOTSUP, 'atomic path exchange is unavailable') from exc
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(-100, first_bytes, -100, second_bytes, 2)
    else:
        raise OSError(errno.ENOTSUP, 'atomic path exchange is unavailable')
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), second)

class SnapshotValidationUnavailable(OSError):
    """The validator could not produce a policy verdict."""

def _validate_snapshot(text: str, *, option: str, label: str) -> None:
    """Validate the exact proposed bytes, not a second read of mutable source."""
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / 'validate-codex-config.py'), option],
            input=text, encoding='utf-8', capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotValidationUnavailable(
            f'{label} snapshot validation unavailable; no publication performed') from exc
    if result.returncode == 65:
        diagnostic = result.stdout.strip()[-1000:]
        raise OSError(
            f'{label} snapshot failed full config validation; no publication performed: {diagnostic}')
    if result.returncode != 0:
        diagnostic = (result.stdout + '\n' + result.stderr).strip()[-1000:]
        raise SnapshotValidationUnavailable(
            f'{label} snapshot validator execution failed (exit {result.returncode}); '
            f'no publication performed: {diagnostic}')

def _validate_canonical_snapshot(text: str) -> None:
    _validate_snapshot(text, option='--config-stdin', label='canonical')

def _validate_runtime_snapshot(text: str) -> None:
    _validate_snapshot(text, option='--runtime-config-stdin', label='repaired runtime')

def _validate_notifier_cutover_snapshot(text: str) -> None:
    """Validate policy around the unchanged, digest-pinned retired launcher."""
    parsed, _ = _loads_toml(text)
    if parsed is None or not _has_legacy_pinned_cua(parsed):
        raise OSError('legacy notifier cleanup lost its exact launcher identity')
    expected = copy.deepcopy(parsed)
    del expected['mcp_servers']['cua_repl']
    # This is a validation view only. Publication retains the complete pinned
    # launcher until the separately authorised cutover; no new launcher passes.
    view = _remove_complete_table(text, 'mcp_servers.cua_repl.env')[0]
    view = _remove_complete_table(view, 'mcp_servers.cua_repl')[0]
    observed, _ = _loads_toml(view)
    if not _same_toml_values(observed, expected):
        raise OSError('legacy validation view changed unrelated configuration')
    _validate_runtime_snapshot(view)

def _repair_file_snapshot(path: Path) -> tuple[tuple[int, ...], bytes]:
    """Read one bounded regular generation without following recovery aliases."""
    def generation(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise OSError('repair generation is not a regular file')
        raw = stream.read(16 * 1024 * 1024 + 1)
        if (len(raw) > 16 * 1024 * 1024
                or generation(os.fstat(stream.fileno())) != generation(before)
                or generation(path.lstat()) != generation(before)):
            raise OSError('repair generation changed during inspection')
    return generation(before), raw


class RepairPublicationError(OSError):
    """A failed publication with a retained, potentially still writable inode."""

    def __init__(self, recovery_path: Path):
        self.recovery_path = recovery_path
        super().__init__(f'repair verification failed; recovery file remains at {recovery_path}')


def _write_repair(config_path: Path, text: str, *, expected: bytes | None=None, unchanged: tuple[tuple[Path, bytes], ...]=(), before_exchange: Callable[[Path], None] | None=None) -> Path | None:
    if config_path.is_symlink():
        raise OSError(f'runtime config must be a regular file, not a symlink: {config_path}')
    repair_path = config_path
    recovery_dir = Path(tempfile.mkdtemp(prefix=f'.{repair_path.name}.recovery-', dir=repair_path.parent))
    fd, tmp_name = tempfile.mkstemp(prefix='generation-', suffix='.toml', dir=recovery_dir)
    tmp_path = Path(tmp_name)
    retain_slot = False
    try:
        os.fchmod(fd, 384)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        staged = _repair_file_snapshot(tmp_path)
        if expected is not None and (repair_path.is_symlink() or repair_path.read_bytes() != expected):
            raise OSError('runtime config changed during reconciliation; retry from fresh state')
        for guarded_path, guarded_bytes in unchanged:
            if guarded_path.is_symlink() or guarded_path.read_bytes() != guarded_bytes:
                raise OSError('guarded file changed during reconciliation; retry from fresh state')
        if expected is None:
            os.link(tmp_path, repair_path, follow_symlinks=False)
            tmp_path.unlink()
            recovery_dir.rmdir()
            return None
        # A signal may arrive after the syscall succeeds but before it returns.
        # Retain before handing the slot to durable bookkeeping as well.
        retain_slot = True
        if before_exchange is not None:
            before_exchange(tmp_path)
        _exchange_paths(tmp_path, repair_path)
        displaced = _repair_file_snapshot(tmp_path)
        if displaced[1] != expected:
            raise OSError('runtime config changed during reconciliation; retry from fresh state')
        for guarded_path, guarded_bytes in unchanged:
            if guarded_path.is_symlink() or guarded_path.read_bytes() != guarded_bytes:
                raise OSError(f'guarded file changed during reconciliation; retry from fresh state: {guarded_path}')
        published = _repair_file_snapshot(repair_path)
        if published[0][:4] != staged[0][:4] or published[1] != staged[1]:
            raise OSError('runtime config changed during reconciliation; retry from fresh state')
        # An open native writer can still save through the displaced inode.
        # Keep its name even on success; the private directory bounds access.
        return tmp_path
    except BaseException as exc:
        if retain_slot:
            # There is no conditional exchange primitive: compensation could
            # displace another native save after its last comparison. Leave
            # both generations named and require explicit recovery instead.
            raise RepairPublicationError(tmp_path) from exc
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        with contextlib.suppress(FileNotFoundError):
            recovery_dir.rmdir()
        raise

def _sha256_and_bytes(path: Path) -> tuple[str, int]:
    import hashlib
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    return (digest.hexdigest(), size)

def _create_backup(config_path: Path, backup_path: Path, *, expected: bytes) -> tuple[str, int]:
    """Create a private, exclusive backup before replacing the runtime file."""
    if config_path.is_symlink() or not config_path.is_file():
        raise OSError(f'runtime config must be a regular file: {config_path}')
    source_fd = os.open(config_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(source_fd, 'rb') as source:
        source_info = os.fstat(source.fileno())
        if not stat.S_ISREG(source_info.st_mode) or source.read(len(expected) + 1) != expected:
            raise OSError('runtime config changed before backup; retry from fresh state')
    backup_path = backup_path.expanduser()
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.is_symlink():
        raise OSError(f'backup path must not be a symlink: {backup_path}')
    fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 384)
    created = os.fstat(fd)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(expected)
            target.flush()
            os.fsync(target.fileno())
        backup_digest, backup_bytes = _sha256_and_bytes(backup_path)
        if (hashlib.sha256(expected).hexdigest(), len(expected)) != (backup_digest, backup_bytes):
            raise OSError(f'backup digest/size mismatch: {backup_path}')
        return (backup_digest, backup_bytes)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            current = backup_path.lstat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                backup_path.unlink()
        raise

def _payload(*, status: str, path: Path, drift: list[str] | None=None, repairs: list[str] | None=None, reason: str | None=None, error: str | None=None, backup_path: Path | None=None, backup_sha256: str | None=None, backup_bytes: int | None=None) -> dict[str, object]:
    payload: dict[str, object] = {'schema_version': SCHEMA_VERSION, 'service': SERVICE, 'status': status, 'path': str(path), 'drift': drift or [], 'repairs': repairs or []}
    if reason:
        payload['reason'] = reason
    if error:
        payload['error'] = error
    if backup_path is not None:
        payload['backup_path'] = str(backup_path)
    if backup_sha256 is not None:
        payload['backup_sha256'] = backup_sha256
    if backup_bytes is not None:
        payload['backup_bytes'] = backup_bytes
    return payload

def parse_args(argv: list[str] | None=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Detect or repair recurring Codex runtime config drift.')
    parser.add_argument('--config-path', type=Path, default=CONFIG_PATH, help='Path to the Codex config.toml file.')
    parser.add_argument('--require-installed-cua-contract', action='store_true', help='Block unless the installed app-owned Computer Use launcher is valid.')
    parser.add_argument('--repair', action='store_true', help='Rewrite known runtime drift patterns in config.toml.')
    parser.add_argument('--check', action='store_true', help='Fail when runtime drift is present. This is the default without --repair.')
    parser.add_argument('--backup-path', type=Path, help='Create an exact backup at this path before an atomic repair.')
    parser.add_argument('--json', action='store_true', help='Emit JSON output.')
    return parser.parse_args(argv)

def _emit(payload: dict[str, object], json_output: bool, message: str='') -> None:
    print(json.dumps(payload, sort_keys=True) if json_output else f'''service:"{SERVICE}" {message or payload.get('error') or payload['status']}''')

def main(argv: list[str] | None=None) -> int:
    args = parse_args(argv)
    config_path = args.config_path.expanduser()
    require_policy_path(config_path)
    if args.backup_path is not None:
        require_policy_path(args.backup_path)
    if config_path.is_symlink() or not config_path.is_file():
        payload = _payload(status='blocked', path=config_path, reason='config_unreadable', error='runtime config must be a regular file, not a symlink')
        _emit(payload, args.json)
        return 1
    if args.require_installed_cua_contract:
        installed_errors = discover_installed_unified_computer_use_contract()
        if installed_errors:
            payload = _payload(status='blocked', path=config_path, reason='installed_cua_contract_invalid', error='; '.join(installed_errors))
            _emit(payload, args.json)
            return 1
    try:
        original_bytes = config_path.read_bytes()
        original = original_bytes.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        payload = _payload(status='blocked', path=config_path, reason='config_unreadable', error=str(exc))
        _emit(payload, args.json)
        return 1
    try:
        expected_auto_review_policy = _canonical_auto_review_policy()
        expected_signing_agent_socket = _canonical_signing_agent_socket()
        expected_circle_no_telemetry = _canonical_circle_no_telemetry()
        expected_control_settings = _canonical_control_settings()
        canonical_bytes = CONFIG_PATH.read_bytes()
        canonical_text = canonical_bytes.decode('utf-8')
        canonical_drift = detect_drift(canonical_text, expected_auto_review_policy=expected_auto_review_policy, expected_signing_agent_socket=expected_signing_agent_socket, expected_circle_no_telemetry=expected_circle_no_telemetry, expected_control_settings=expected_control_settings)
        if canonical_drift:
            raise CanonicalSourceUnavailable('canonical config has drift: ' + ', '.join(canonical_drift))
    except (CanonicalSourceUnavailable, OSError, UnicodeError) as exc:
        payload = _payload(status='blocked', path=config_path, reason='canonical_source_unavailable', error=str(exc))
        _emit(payload, args.json)
        return 1
    # An explicit installer check may validate the pinned Desktop overlay and
    # then inspect its original policy view. Never let the ordinary repair path
    # erase that registration or accept whatever Desktop currently contains.
    review_state = os.environ.get('DOTS_DESKTOP_REVIEW_STATE')
    review_digest = os.environ.get('DOTS_DESKTOP_REVIEW_SHA256')
    if review_state or review_digest:
        try:
            if args.repair or not review_state or not review_digest:
                raise ValueError('Desktop review is read-only and needs its explicit digest')
            spec = importlib.util.spec_from_file_location(
                'desktop_check_installer', CONFIG_PATH.parent / 'scripts/install-codex.py')
            installer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(installer)
            context = installer.SCOPE.context()
            state = installer.SCOPE.physical(Path(review_state))
            if state != Path(context['state_dir']) or config_path != Path(context['home']) / '.codex/config.toml':
                raise ValueError('Desktop review targets another runtime')
            digest = hashlib.sha256(installer.SCOPE.read_regular(state / 'plan.json')).hexdigest()
            plan = installer.load_plan(state, digest)
            if installer.load_result(state, plan)['status'] != 'applied':
                raise ValueError('Desktop review requires an applied installation')
            review = installer.reviewed_desktop(state, digest, plan, review_digest)
            if original_bytes != review['observed'].encode():
                raise ValueError('Desktop registration changed after review')
            original = review['installed']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _emit(_payload(status='blocked', path=config_path,
                reason='desktop_review_invalid', error=str(exc)), args.json)
            return 1
    approved_update_changes = None
    update_descriptor = Path(__file__).resolve().parents[1] / '.previous-desktop-review.json'
    if update_descriptor.exists() or deployment_module() is not None:
        try:
            spec = importlib.util.spec_from_file_location('desktop_update_installer', CONFIG_PATH.parent / 'scripts/install-codex.py')
            updater = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(updater)
            original, approved_update_changes = updater.normalized_desktop_update(original, canonical_text)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _emit(_payload(status='blocked', path=config_path, reason='desktop_update_invalid', error=str(exc)), args.json)
            return 1
    drift = detect_drift(original, expected_auto_review_policy=expected_auto_review_policy, expected_signing_agent_socket=expected_signing_agent_socket, expected_circle_no_telemetry=expected_circle_no_telemetry, expected_control_settings=expected_control_settings)
    if args.repair and deployment_module() is not None:
        runtime, _ = _loads_toml(original)
        deployment = deployment_module()
        spec = importlib.util.spec_from_file_location('desktop_repair_guard',
            deployment.ROOT / 'codex/scripts/desktop_compatibility.py')
        desktop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(desktop)
        state = Path(deployment.context()['state_dir'])
        try:
            with os.scandir(state) as entries:
                pending = any(entry.name.startswith('desktop-review') and entry.name.endswith('.json')
                              for entry in entries)
        except OSError as exc:
            _emit(_payload(status='blocked', path=config_path,
                reason='desktop_registration_scan_failed', error=str(exc)), args.json)
            return 1
        if runtime is None or desktop.requires_preservation(runtime) or pending:
            _emit(_payload(status='blocked', path=config_path,
                reason='desktop_registration_preservation_required',
                error='Review Desktop registration before repair; no config was changed'), args.json)
            return 1
    if not _runtime_matches_canonical_policy(original, canonical_text) and (not drift):
        drift.append('canonical_file_mismatch')
    if LEGACY_CUA_DRIFT in drift and (not args.repair or 'notify.SkyComputerUseClient' not in drift):
        payload = _payload(status='blocked', path=config_path, drift=drift, reason='legacy_repository_pinned_cua_cutover_required', error=LEGACY_CUA_CUTOVER)
        _emit(payload, args.json)
        return 1
    if not drift:
        payload = _payload(status='pass', path=config_path)
        _emit(payload, args.json, 'OK')
        return 0
    if not args.repair:
        payload = _payload(status='fail', path=config_path, drift=drift, reason='runtime_config_drift')
        _emit(payload, args.json, f"FAIL runtime config drift: {', '.join(drift)}; Repair with: {Path(sys.argv[0]).name} --repair")
        return 1
    # Update normalisation may remove approved consent from the comparison view.
    # A no-drift check is harmless; any repair write must inspect the raw file.
    runtime, _ = _loads_toml(original_bytes.decode('utf-8'))
    if isinstance(runtime, dict) and isinstance(runtime.get('hooks'), dict) and 'state' in runtime['hooks']:
        _emit(_payload(status='blocked', path=config_path,
            reason='native_hook_consent_preservation_required',
            error='Review native hook consent through the installation-bound proposal before repair; no config was changed'), args.json)
        return 1
    repaired_text, repairs, blocked = repair_text(original, expected_auto_review_policy=expected_auto_review_policy, expected_signing_agent_socket=expected_signing_agent_socket, expected_circle_no_telemetry=expected_circle_no_telemetry, expected_control_settings=expected_control_settings)
    remaining_drift = detect_drift(repaired_text, expected_auto_review_policy=expected_auto_review_policy, expected_signing_agent_socket=expected_signing_agent_socket, expected_circle_no_telemetry=expected_circle_no_telemetry, expected_control_settings=expected_control_settings)
    notifier_only_cutover = LEGACY_CUA_DRIFT in remaining_drift and repairs == ['notify.SkyComputerUseClient'] and (blocked == [LEGACY_CUA_CUTOVER])
    if (blocked or remaining_drift) and (not notifier_only_cutover):
        payload = _payload(status='blocked', path=config_path, drift=remaining_drift, repairs=repairs, reason='runtime_config_drift_unrepairable', error=', '.join([*blocked, *remaining_drift]))
        _emit(payload, args.json)
        return 1
    canonical_repair, plugin_error = _canonical_with_desktop_plugins(canonical_text, original)
    if canonical_repair is None:
        _emit(_payload(status='blocked', path=config_path, drift=drift, reason='desktop_plugin_preservation_failed', error=plugin_error), args.json)
        return 1
    if not notifier_only_cutover:
        repaired_text = canonical_repair
        repairs = [*repairs, 'canonical_file_sync']
    # A blocked legacy cleanup is still a publication. Apply the same consent
    # and exact-snapshot checks before creating a backup or replacing bytes.
    try:
        if notifier_only_cutover:
            _validate_notifier_cutover_snapshot(repaired_text)
        else:
            _validate_runtime_snapshot(repaired_text)
    except SnapshotValidationUnavailable as exc:
        _emit(_payload(status='blocked', path=config_path, drift=drift, reason='canonical_validation_unavailable', error=str(exc)), args.json)
        return 1
    except OSError as exc:
        _emit(_payload(status='blocked', path=config_path, drift=drift, reason='canonical_source_invalid', error=str(exc)), args.json)
        return 1
    if args.backup_path is None:
        backup_dir = Path(tempfile.mkdtemp(prefix='codex-config-backup-'))
        args.backup_path = backup_dir / 'config.toml'
    backup_sha256: str | None = None
    backup_bytes: int | None = None
    if args.backup_path is not None:
        try:
            backup_sha256, backup_bytes = _create_backup(config_path, args.backup_path, expected=original_bytes)
        except OSError as exc:
            payload = _payload(status='blocked', path=config_path, drift=drift, repairs=repairs, reason='config_backup_failed', error=str(exc), backup_path=args.backup_path)
            _emit(payload, args.json)
            return 1
    if approved_update_changes:
        repaired_text = updater.module('restore_desktop_overlay', CONFIG_PATH.parent / 'scripts/desktop_compatibility.py').overlay(repaired_text, approved_update_changes)
    recovery_path = None
    try:
        recovery_path = _write_repair(config_path, repaired_text, expected=original_bytes, unchanged=((CONFIG_PATH, canonical_bytes),))
        if config_path.read_bytes() != repaired_text.encode('utf-8'):
            raise OSError('runtime config changed after reconciliation; expected state not verified')
    except OSError as exc:
        if isinstance(exc, RepairPublicationError):
            recovery_path = exc.recovery_path
        payload = _payload(status='blocked', path=config_path, drift=drift, repairs=repairs, reason='config_write_failed', error=str(exc), backup_path=args.backup_path, backup_sha256=backup_sha256, backup_bytes=backup_bytes)
        payload['retained_generation_path'] = str(recovery_path) if recovery_path is not None else None
        _emit(payload, args.json)
        return 1
    payload = _payload(status='blocked' if notifier_only_cutover else 'repaired', path=config_path, drift=remaining_drift if notifier_only_cutover else drift, repairs=repairs, reason='legacy_repository_pinned_cua_cutover_required' if notifier_only_cutover else None, error='Retired notifier removed; ' + LEGACY_CUA_CUTOVER if notifier_only_cutover else None, backup_path=args.backup_path, backup_sha256=backup_sha256, backup_bytes=backup_bytes)
    payload['retained_generation_path'] = str(recovery_path) if recovery_path is not None else None
    _emit(payload, args.json)
    return 1 if notifier_only_cutover else 0
if __name__ == '__main__':
    raise SystemExit(main())
