"""Validate solo-dev Codex config governance and MCP hygiene."""
from __future__ import annotations

from migration_scope import deployment_module, local_path_text, require_policy_scope

require_policy_scope()
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from collections.abc import Iterator
from fnmatch import fnmatchcase
from importlib import import_module
from pathlib import Path
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = import_module('tomli')
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_REPO_ROOT = REPO_ROOT.parent
CONFIG_PATH = REPO_ROOT / 'config.toml'
REPO_LOCAL_CONFIG_PATH = REPO_ROOT / '.codex' / 'config.toml'
PROJECT_CONFIG_SEARCH_ROOTS = tuple(Path(path).expanduser() for path in os.environ.get('CODEX_PROJECT_CONFIG_SEARCH_ROOTS', os.pathsep.join((str(Path.home() / 'dev'), str(Path.home() / 'Documents')))).split(os.pathsep) if path)
HOME_CONFIG_PATH = Path.home() / '.codex' / 'config.toml'
HOME_HOOKS_PATH = Path.home() / '.codex' / 'hooks.json'
HOME_AGENTS_PATH = Path.home() / '.codex' / 'agents'
CONFIG_SCHEMA_PATH = REPO_ROOT / 'schemas' / 'config.schema.json'
CODEX_SOURCE_SCHEMA_PATH = Path(os.environ.get('CODEX_SOURCE_SCHEMA_PATH', Path.home() / 'dev' / 'codex' / 'codex-rs' / 'core' / 'config.schema.json')).expanduser()
CANON_ROOT_DEFAULT = Path(local_path_text('@HOME@/dev/dots/codex'))
HOME_PROJECTION_SOURCE_ROOT = Path(os.environ.get('CODEX_CONFIG_SOURCE_ROOT', CANON_ROOT_DEFAULT if CANON_ROOT_DEFAULT.exists() else REPO_ROOT)).expanduser()
HOOKS_CONFIG_PATH = HOME_PROJECTION_SOURCE_ROOT / 'hooks' / 'hooks.json'
CANONICAL_AGENTS_MANIFEST_PATH = HOME_PROJECTION_SOURCE_ROOT / 'agents' / 'manifest.json'
CODEX_SESSION_EVIDENCE_PATHS = (local_path_text('@HOME@/.local/share/codex-storage/sessions'), local_path_text('@HOME@/dev/dots/codex/usage-data'), local_path_text('@HOME@/.agents/session-collector'))
DISALLOWED_PROJECT_PREFIXES = (local_path_text('@HOME@/Documents/Codex/'),)
BORUMI_GENERATED_CONFIG_PATH = Path(local_path_text('@HOME@/Documents/Borumi AI Workspace/.codex/config.toml'))
ALLOWED_PROJECT_LOCAL_CONFIG_PATHS = (Path(local_path_text('@HOME@/dev/lifeOS/.codex/config.toml')), BORUMI_GENERATED_CONFIG_PATH)
ALLOWED_LIFEOS_PROJECT_CONFIG_KEYS = frozenset({'model_verbosity'})
ALLOWED_LIFEOS_PROJECT_CONFIG_VERBOSITY = frozenset({'low', 'medium', 'high'})
WORKSTATION_HOME_PATH = local_path_text('@HOME@')
COREPACK_CACHE_PATH = local_path_text('@HOME@/.cache/corepack')
REQUIRED_TOOL_CACHE_PATHS = (local_path_text('@HOME@/.npm'), local_path_text('@HOME@/.local/bin'), local_path_text('@HOME@/.local/lib'), local_path_text('@HOME@/.local/share/tessl'), local_path_text('@HOME@/.tessl'), local_path_text('@HOME@/.cache/node'), local_path_text('@HOME@/.cache/uv'), local_path_text('@HOME@/.local/share/mise'), local_path_text('@HOME@/.pnpm-store'), local_path_text('@HOME@/go'), local_path_text('@HOME@/Library/Caches/go-build'), local_path_text('@HOME@/.cargo'), local_path_text('@HOME@/.rustup'), local_path_text('@HOME@/Library/Python'), local_path_text('@HOME@/Library/Caches/pip'), local_path_text('@HOME@/Library/Caches/Homebrew'), local_path_text('@HOME@/.gem'), local_path_text('@HOME@/.bundle'), local_path_text('@HOME@/.codex/tmp'), COREPACK_CACHE_PATH, local_path_text('@HOME@/Library/Caches/mise'), local_path_text('@HOME@/Library/Caches/org.swift.swiftpm'), local_path_text('@HOME@/Library/org.swift.swiftpm'), local_path_text('@HOME@/Library/Developer/Xcode/DerivedData'), local_path_text('@HOME@/Library/Developer/Xcode/SourcePackages'), local_path_text('@HOME@/.swiftpm'))
PLUGIN_RUNTIME_WRITE_PATHS = (local_path_text('@HOME@/.codex/.tmp/bundled-marketplaces'), local_path_text('@HOME@/.codex/plugins/cache'), local_path_text('@HOME@/.cache/codex-runtimes'))
BROWSER_RUNTIME_WRITE_PATHS = (local_path_text('@HOME@/Library/Caches/ms-playwright'), local_path_text('@HOME@/Library/Caches/Chromium'), local_path_text('@HOME@/Library/Application Support/Chromium'), local_path_text('@HOME@/.codex/computer-use'), local_path_text('@HOME@/.codex/plugins/cache/openai-bundled/computer-use'))
BROWSER_RUNTIME_DOWNLOAD_DOMAINS = ('cdn.playwright.dev', 'playwright.azureedge.net', 'playwright.download.prss.microsoft.com')
TESSL_RUNTIME_DOWNLOAD_DOMAINS = ('get.tessl.io', 'install.tessl.io')
TOOLCHAIN_RUNTIME_DOWNLOAD_DOMAINS = ('nodejs.org', 'github.com', 'raw.githubusercontent.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com', 'pypi.org', 'files.pythonhosted.org', 'crates.io', 'index.crates.io', 'static.crates.io', 'static.rust-lang.org', 'proxy.golang.org', 'sum.golang.org', 'go.dev', 'rubygems.org', 'formulae.brew.sh', 'ghcr.io', 'pkg-containers.githubusercontent.com')
UNIFIED_COMPUTER_USE_PLUGIN_ROOT = Path(os.environ.get('CODEX_UNIFIED_COMPUTER_USE_PLUGIN_ROOT', '/Applications/ChatGPT.app/Contents/Resources/plugins/openai-bundled/plugins/unified-computer-use')).expanduser()
UNIFIED_COMPUTER_USE_NODE_PATH = Path(os.environ.get('CODEX_UNIFIED_COMPUTER_USE_NODE_PATH', '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node')).expanduser()
UNIFIED_COMPUTER_USE_NODE_REPL_PATH = Path(os.environ.get('CODEX_UNIFIED_COMPUTER_USE_NODE_REPL_PATH', '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl')).expanduser()
UNIFIED_COMPUTER_USE_NODE_MODULE_DIR = UNIFIED_COMPUTER_USE_NODE_PATH.parent.parent / 'lib' / 'node_modules'
COMPUTER_USE_LAUNCHER_COMPONENTS = frozenset({'node_repl', 'unified-computer-use', 'computer-use-client-launcher', 'SkyComputerUseService', 'Codex Computer Use.app'})
COMPUTER_USE_LAUNCHER_BOUNDARY_PATTERN = re.compile('(?:^|[/\\\\\'\\"`\\s({<=,:;|&])(?:' + '|'.join(re.escape(component) for component in sorted(COMPUTER_USE_LAUNCHER_COMPONENTS, key=len, reverse=True)) + ')(?=$|[/\\\\\'\\"`\\s)$}>;,<:|&\\]}])')
COMPUTER_USE_LAUNCHER_VALUE_SEPARATOR_PATTERN = re.compile('[/\\\\\'\\"`\\s($<>=,:;|&){}]+')
COMPUTER_USE_EXECUTION_WRAPPERS = frozenset({'bash', 'dash', 'env', 'fish', 'sh', 'zsh'})
LEGACY_NODE_REPL_ENV_KEYS = frozenset({'NODE_REPL_NODE_MODULE_DIRS', 'NODE_REPL_NODE_PATH', 'NODE_REPL_TRUSTED_CODE_PATHS', 'NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S', 'CODEX_NODE_REPL_TRUSTED_SERVICES', 'NODE_REPL_UNTRUSTED_ENV_ALLOWLIST', 'BROWSER_USE_AVAILABLE_BACKENDS', 'BROWSER_USE_CODEX_APP_BUILD_FLAVOR', 'BROWSER_USE_CODEX_APP_VERSION', 'CODEX_CLI_PATH', 'SKY_CUA_SERVICE_PATH'})

def discover_installed_unified_computer_use_contract() -> list[str]:
    """Validate the app-owned CUA launcher without importing its runtime."""
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
DISALLOWED_GLOBAL_REPOSITORY_WRITE_PATHS = (local_path_text('@HOME@/dev/dots'), local_path_text('@HOME@/dev/dots/.git'), local_path_text('@HOME@/dev/dots/.codex'), local_path_text('@HOME@/dev/agent-skills'), local_path_text('@HOME@/dev/agent-skills/.git'))
DESKTOP_RUNTIME_ENV_NAMES = ('CUA_REPL_ENABLED_SURFACES', 'NODE_REPL_UNTRUSTED_ENV_ALLOWLIST', 'NODE_REPL_TRUSTED_SERVICES', 'NODE_REPL_JS_BANNER', 'NODE_REPL_TRUSTED_RPC_ENABLED', 'NODE_REPL_NODE_MODULE_DIRS', 'NODE_REPL_TRUSTED_CODE_PATHS', 'BROWSER_USE_TINYSKY_ENABLED')
REQUIRED_SHELL_ENV_INCLUDE_ONLY = ('NODE_EXTRA_CA_CERTS', 'CODEX_HOME', 'CODEX_AUTH_ENVIRONMENT_ID', *DESKTOP_RUNTIME_ENV_NAMES)
RETIRED_MACOS_ONEPASSWORD_SOCKET = local_path_text('@HOME@/Library/Group Containers/2BUA8C4S2C.com.1password/t/s.sock')
ONEPASSWORD_SSH_AGENT_SOCKET = local_path_text('@HOME@/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock')
NETWORKED_PERMISSION_PROFILES = ('workspace-net', 'readonly-net')
AUTH_ENV_FIFO_PATH = local_path_text('@HOME@/.codex/.env')
DISALLOWED_TRACKED_PROJECTION_PATHS = ('.codex/environments',)
LOCAL_MEMORY_CLI_STATE_PATH = local_path_text('@HOME@/.local-memory')
COMPUTER_USE_PLUGIN_ID = 'unified-computer-use@openai-bundled'
COMPUTER_USE_PLUGIN_SERVER_NAME = 'cua_repl'
REQUIRED_COMPACT_PROMPT_PHRASES = ('Summarise the conversation as an execution handoff', 'Objective, scope, and completion contract', 'subject to active higher-priority instructions and controls', 'Parent objective status separately from the status of the current child task', 'retain and compress every lane whose state changes the completion claim', 'Do not invent cwd, branch, files, diffs, validation, command output', 'Do not include hidden reasoning, secrets, tokens, credentials', 'Previous compaction summary', 'Do not search session history, rollout logs, hook receipts, or handoff files', 'pre_existing_user_changes:', 'codex_changes:', 'Command: (cwd=<absolute cwd>) <exact command> -> pass|fail|blocked', 'After compaction, continue from completed work and the live state', 'Resume from: <one concrete next command, file edit, validation step, decision point, or unknown>')
REQUIRED_DEVELOPER_INSTRUCTION_PHRASES = ('For reviews and diagnoses, investigate and report findings; implement when authorized', 'Do not infer authority for external mutations', 'Ask before destructive actions, dependency changes, or secret handling unless explicitly authorized', 'try materially different, safe alternatives within the authorized scope', "After compaction, resume from the handoff's objective, authorization, completed work, and blockers", 'Keep local validation, live runtime, hosted checks, reviews, and delivery status distinct', 'Carry forward authorization already granted for the same scope')
REQUIRED_PROFILE_KEYS = {'default_permissions', 'approval_policy', 'model_reasoning_summary', 'web_search'}
ROOT_PERMISSION_PROFILE_NAME = 'workspace-net'
EDIT_PERMISSION_PROFILE_NAMES = {'workspace-net', 'workspace-no-net'}
READONLY_PERMISSION_PROFILE_NAMES = {'readonly-net'}
KNOWN_PERMISSION_PROFILE_NAMES = EDIT_PERMISSION_PROFILE_NAMES | READONLY_PERMISSION_PROFILE_NAMES
EXPECTED_PROFILE_NAMES = {'docs', 'oss-cloud', 'oss-inspect', 'oss-local', 'oss-local-code', 'oss-local-fallback', 'oss-security'}
OSS_PROFILE_NAMES = frozenset({'oss-cloud', 'oss-inspect', 'oss-local', 'oss-local-code', 'oss-local-fallback', 'oss-security'})
OSS_PROFILE_PROVIDER_NAMES = {'oss-cloud': 'ollama-cloud', 'oss-inspect': 'ollama', 'oss-local': 'ollama', 'oss-local-code': 'ollama', 'oss-local-fallback': 'ollama', 'oss-security': 'ollama'}
OSS_CLOUD_PROVIDER_ID = 'ollama-cloud'
OSS_CLOUD_PROVIDER_CONTRACT = {'name': 'Ollama Cloud', 'base_url': 'https://ollama.com/v1', 'wire_api': 'responses', 'env_key': 'OLLAMA_API_KEY'}
CODEX_NON_OVERRIDABLE_MODEL_PROVIDER_IDS = frozenset({'openai', 'ollama', 'lmstudio'})
ISOLATED_OSS_PROFILE_NAMES = frozenset({'oss-cloud', 'oss-inspect', 'oss-local', 'oss-local-code', 'oss-local-fallback', 'oss-security'})
OSS_ISOLATION_FEATURES = frozenset({'plugins', 'skill_mcp_dependency_install', 'apps', 'code_mode', 'code_mode_only'})
OSS_INHERITED_MCP_NAMES = frozenset({'1password', 'aikido', 'chrome-devtools', 'codex-repo', 'context7', 'cua_repl', 'ditto-local', 'github', 'linear', 'mobbin', 'openaiDeveloperDocs', 'repo-prompt', 'spiral', 'tessl-docs'})
READONLY_OSS_1PASSWORD_OVERLAY_PROFILES = frozenset({'oss-cloud', 'oss-inspect', 'oss-local', 'oss-local-code', 'oss-local-fallback', 'oss-security'})
OSS_CLOUD_DISABLED_MCP_OVERLAYS = frozenset({'ditto-local', 'spiral'})
BUILTIN_APPROVALS_REVIEWERS = {'user', 'auto_review'}
LEGACY_APPROVALS_REVIEWERS = {'guardian_subagent'}
APP_TOOL_APPROVAL_MODES = {'auto', 'prompt', 'writes', 'approve'}
FORBIDDEN_GLOBAL_PROFILE_NAMES = {'custom'}
REQUIRED_MCP_TOOL_APPROVALS = {('github', 'add_issue_comment'): 'prompt', ('github', 'create_pull_request'): 'prompt', ('github', 'create_pull_request_review'): 'prompt', ('github', 'get_file_contents'): 'approve', ('github', 'get_pull_request'): 'approve', ('github', 'get_pull_request_comments'): 'approve', ('github', 'get_pull_request_reviews'): 'approve', ('github', 'get_pull_request_status'): 'approve', ('github', 'list_pull_requests'): 'approve', ('github', 'push_files'): 'prompt', ('linear', 'save_comment'): 'approve', ('openaiDeveloperDocs', 'fetch_openai_doc'): 'approve', ('openaiDeveloperDocs', 'search_openai_docs'): 'approve'}
VALID_REASONING_EFFORTS = {'low', 'medium', 'high', 'xhigh'}
MODELS_WITHOUT_REASONING_EFFORT = {'CyberCrew/notmythos-8b', 'deepseek-v4-flash:0731-cloud', 'minimax-m2.7:cloud', 'gpt-oss:20b', 'qwen3-coder:30b', 'qwen3.5:9b-mlx', 'qwen3.5:latest'}
STATIC_ALLOWED_PLUGIN_IDS = {'github@openai-curated', 'cloudflare@openai-curated', 'build-web-apps@openai-curated', 'build-web-data-visualization@openai-curated', 'linear@openai-curated', 'build-ios-apps@openai-curated', 'build-macos-apps@openai-curated', 'circleci@openai-curated', 'coderabbit@agent-skills-local', 'coderabbit@openai-curated', 'codex-security@openai-curated', 'unified-computer-use@openai-bundled', 'record-and-replay@openai-bundled', 'sites@openai-bundled', 'skill-factory@agent-skills-local', 'video-reference-analysis@created-by-me-remote', 'plugin-factory@agent-skills-local', 'harness-engineering@agent-skills-local', 'synaipse-harness@agent-skills-local', 'aidevcon@agent-skills-local', 'atlassian-rovo@openai-curated-remote', 'box@openai-curated-remote', 'figma@openai-curated', 'figma@openai-curated-remote', 'gmail@openai-curated-remote', 'google-calendar@openai-curated-remote', 'google-drive@openai-curated-remote', 'notion@openai-curated-remote', 'sentry@openai-curated', 'sharepoint@openai-curated-remote', 'slack@openai-curated', 'teams@openai-curated-remote', 'gmail@openai-curated', 'openai-developers@openai-curated', 'plugin-eval@openai-curated', 'remotion@openai-curated', 'browser@openai-bundled', 'browser-use@openai-bundled', 'chrome@openai-bundled', 'visualize@openai-bundled', 'documents@openai-primary-runtime', 'pdf@openai-primary-runtime', 'spreadsheets@openai-primary-runtime', 'presentations@openai-primary-runtime', 'template-creator@openai-primary-runtime'}
PLUGIN_CACHE_ROOT_CANDIDATES = (REPO_ROOT / '.agents' / 'plugins-runtime' / 'cache', REPO_ROOT / 'plugins' / 'cache', REPO_ROOT / 'Plugins' / 'cache')
PLUGIN_MARKETPLACE_CANDIDATES = (REPO_ROOT / 'plugins' / 'marketplace.json', REPO_ROOT / '.agents' / 'plugins-runtime' / 'marketplace.json')
OPTIONAL_CONFIG_MARKETPLACES = {'openai-curated'}
ALLOWED_NEVER_PROFILES: set[str] = set()
ALLOWED_LIVE_WEB_PROFILES = {'docs'}
DISALLOWED_EPHEMERAL_MCP_COMMANDS = {'npx', 'uvx', 'bunx', 'pnpm', 'npm', 'yarn', 'bun'}
REQUIRED_FEATURES_TRUE = {'unified_exec', 'memories', 'runtime_metrics', 'code_mode', 'code_mode_only'}
REQUIRED_REJECT_APPROVAL_KEYS = {'sandbox_approval', 'rules', 'mcp_elicitations'}
REQUIRED_MULTI_AGENT_FEATURES_TRUE = {'multi_agent', 'multi_agent_v2'}
REQUIRED_MULTI_AGENT_FEATURES_FALSE: set[str] = set()
REQUIRED_HOOK_FEATURE_KEYS_TRUE = {'hooks'}
REMOVED_OR_NOOP_FEATURE_KEYS = {'apply_patch_freeform', 'codex_git_commit', 'enable_fanout', 'guardian_approval', 'image_detail_original', 'js_repl', 'js_repl_tools_only', 'plugin_hooks', 'responses_websockets', 'responses_websockets_v2', 'skill_env_var_dependency_prompt', 'sqlite', 'tool_search', 'undo'}
UNSUPPORTED_LOCAL_FEATURE_KEYS = {'apps_mcp_gateway', 'auto_review', 'child_agents_md', 'general_analytics', 'multi_agent_mcp_gateway', 'request_user_input', 'smart_approvals', 'voice_transcription'}
ROOT_TABLE_NAME = '<root>'
DUPLICATE_SINGLETON_KEYS = {'approval_policy', 'approvals_reviewer', 'model', 'model_provider', 'profile', 'sandbox_mode'}
SYSTEM_AGENT_TABLE_KEYS = {'interrupt_message', 'job_max_runtime_seconds', 'max_depth', 'max_threads'}

def configured_agent_role_names(agents: object) -> set[str]:
    """Return configured role-object names, excluding [agents] system settings."""
    if not isinstance(agents, dict):
        return set()
    return {role_name for role_name, role_config in agents.items() if isinstance(role_name, str) and role_name not in SYSTEM_AGENT_TABLE_KEYS and (role_name != 'enabled') and isinstance(role_config, dict)}
CONFIG_TOML_TOP_LEVEL_KEYS = {'model', 'review_model', 'model_provider', 'model_context_window', 'model_auto_compact_token_limit', 'approval_policy', 'approvals_reviewer', 'shell_environment_policy', 'allow_login_shell', 'sandbox_mode', 'sandbox_workspace_write', 'default_permissions', 'permissions', 'notify', 'instructions', 'developer_instructions', 'include_permissions_instructions', 'include_apps_instructions', 'include_environment_context', 'model_instructions_file', 'compact_prompt', 'commit_attribution', 'forced_chatgpt_workspace_id', 'forced_login_method', 'cli_auth_credentials_store', 'mcp_servers', 'mcp_oauth_credentials_store', 'mcp_oauth_callback_port', 'mcp_oauth_callback_url', 'model_providers', 'project_doc_max_bytes', 'project_doc_fallback_filenames', 'tool_output_token_limit', 'background_terminal_max_timeout', 'js_repl_node_path', 'js_repl_node_module_dirs', 'zsh_path', 'profile', 'profiles', 'history', 'sqlite_home', 'log_dir', 'file_opener', 'tui', 'hide_agent_reasoning', 'show_raw_agent_reasoning', 'model_reasoning_effort', 'plan_mode_reasoning_effort', 'model_reasoning_summary', 'model_verbosity', 'model_supports_reasoning_summaries', 'model_catalog_json', 'personality', 'service_tier', 'chatgpt_base_url', 'openai_base_url', 'audio', 'experimental_realtime_ws_base_url', 'experimental_realtime_ws_model', 'realtime', 'experimental_realtime_ws_backend_prompt', 'experimental_realtime_ws_startup_context', 'experimental_realtime_start_instructions', 'projects', 'web_search', 'tools', 'tool_suggest', 'agents', 'memories', 'skills', 'plugins', 'marketplaces', 'feature', 'features', 'suppress_unstable_features_warning', 'ghost_snapshot', 'project_root_markers', 'check_for_update_on_startup', 'disable_paste_burst', 'analytics', 'feedback', 'apps', 'otel', 'windows', 'windows_wsl_setup_acknowledged', 'notice', 'experimental_instructions_file', 'experimental_compact_prompt_file', 'experimental_use_unified_exec_tool', 'experimental_use_freeform_apply_patch', 'oss_provider'}

def validate_top_level_reasoning_effort(config: dict[str, object]) -> list[str]:
    """
    Validate supported values for plan-mode reasoning effort at the config root.

    Parameters:
        config (dict[str, object]): Parsed root config table.

    Returns:
        list[str]: Validation errors for unsupported values.
    """
    errors: list[str] = []
    effort = config.get('plan_mode_reasoning_effort')
    if effort is not None and (not isinstance(effort, str) or effort not in VALID_REASONING_EFFORTS):
        errors.append(f'plan_mode_reasoning_effort must be one of {sorted(VALID_REASONING_EFFORTS)}')
    return errors

def validate_root_model(config: dict[str, object]) -> list[str]:
    """Allow the root model to be omitted, while rejecting blank or non-string values."""
    root_model = config.get('model')
    if root_model is not None and (not isinstance(root_model, str) or not root_model.strip()):
        return ['root model must be a non-empty string when provided']
    return []

def validate_goal_feature(config: dict[str, object]) -> list[str]:
    """
    Validate the root-level `[features]` goals toggle.

    Parameters:
        config (dict[str, object]): Parsed root config table.

    Returns:
        list[str]: Validation errors for missing or disabled goal feature config.
    """
    features = config.get('features')
    if not isinstance(features, dict):
        return ['[features] table must exist with goals = true']
    if features.get('goals') is not True:
        return ['features.goals must stay true']
    return []

def active_permission_profile(config: dict[str, object]) -> tuple[str | None, dict[str, object] | None]:
    """Return the selected permission profile name and table, when configured."""
    selected = config.get('default_permissions')
    permissions = config.get('permissions')
    if not isinstance(selected, str) or not selected.strip():
        return (None, None)
    if not isinstance(permissions, dict):
        return (selected, None)
    profile = permissions.get(selected)
    if not isinstance(profile, dict):
        return (selected, None)
    return (selected, profile)

def permission_profile_workspace_roots(config: dict[str, object]) -> list[str]:
    """Return enabled workspace roots from the selected permission profile."""
    _, profile = active_permission_profile(config)
    if profile is None:
        return []
    workspace_roots = profile.get('workspace_roots')
    if not isinstance(workspace_roots, dict):
        return []
    return [str(path) for path, enabled in workspace_roots.items() if enabled is True and isinstance(path, str)]

def validate_root_permission_profile_policy(config: dict[str, object]) -> list[str]:
    """Require root config to use permission profiles, not legacy sandbox settings."""
    errors: list[str] = []
    if 'sandbox_mode' in config:
        errors.append('root sandbox_mode must be removed when default_permissions is active; use permissions.workspace-net so plugin/tool cache roots and network allowlists stay enforced inside the sandbox')
    if 'sandbox_workspace_write' in config:
        errors.append('root sandbox_workspace_write must be removed; use permissions.<profile>.workspace_roots')
    selected = config.get('default_permissions')
    permissions = config.get('permissions')
    if selected != ROOT_PERMISSION_PROFILE_NAME:
        errors.append(f'root default_permissions must be "{ROOT_PERMISSION_PROFILE_NAME}"')
    if not isinstance(permissions, dict):
        errors.append('[permissions] table must exist for profile-based sandboxing')
        return errors
    missing_profiles = sorted(KNOWN_PERMISSION_PROFILE_NAMES - set(permissions.keys()))
    if missing_profiles:
        errors.append(f'[permissions] missing required profiles: {missing_profiles}')
    selected_name, selected_profile = active_permission_profile(config)
    if selected_name is None or selected_profile is None:
        errors.append(f'default_permissions {selected!r} must resolve to a configured [permissions.<name>] table')
        return errors
    for profile_name, profile in sorted(permissions.items()):
        if not isinstance(profile, dict):
            errors.append(f'permissions.{profile_name} must be a table')
            continue
        errors.extend(validate_permission_profile_network(profile_name, profile))
    return errors

def validate_permission_profile_network(profile_name: str, profile: dict[str, object]) -> list[str]:
    """Validate network policy shape for a named permission profile."""
    errors: list[str] = []
    network = profile.get('network')
    if not isinstance(network, dict):
        errors.append(f'permissions.{profile_name}.network must exist')
        return errors
    if profile_name == 'workspace-no-net':
        if network.get('enabled') is not False:
            errors.append('permissions.workspace-no-net.network.enabled must be false')
        return errors
    if network.get('enabled') is not True:
        errors.append(f'permissions.{profile_name}.network.enabled must be true')
    if network.get('allow_local_binding') is not True:
        errors.append(f'permissions.{profile_name}.network.allow_local_binding must be true for local runtime access')
    domains = network.get('domains')
    if not isinstance(domains, dict):
        errors.append(f'permissions.{profile_name}.network.domains must exist')
        return errors
    if domains.get('*') == 'allow':
        errors.append(f'permissions.{profile_name}.network.domains."*" must not allow wildcard network egress')
    for host in ('localhost', '127.0.0.1'):
        if domains.get(host) != 'allow':
            errors.append(f'permissions.{profile_name}.network.domains."{host}" must allow local runtime access')
    return errors

def validate_codex_session_evidence_access(config: dict[str, object]) -> list[str]:
    """
    Ensure Codex has permanent access to raw session logs and usage evidence paths.

    Checks that every path in CODEX_SESSION_EVIDENCE_PATHS is:
    - listed in the active permission profile workspace roots,
    Project trust is separate from filesystem access and is not required here.

    Parameters:
        config (dict[str, object]): Parsed root configuration table.

    Returns:
        list[str]: A list of validation error messages for any missing or misconfigured access entries; empty if all checks pass.
    """
    errors: list[str] = []
    selected_name, _ = active_permission_profile(config)
    writable_roots = permission_profile_workspace_roots(config)
    for required_path in CODEX_SESSION_EVIDENCE_PATHS:
        if required_path not in writable_roots:
            errors.append(f'permissions.{selected_name}.workspace_roots must include {required_path} for Codex session evidence access')
    return errors

def validate_tool_cache_write_access(config: dict[str, object]) -> list[str]:
    """
    Validate that permission profile workspace roots include tool cache write paths.

    Returns:
        list[str]: Error messages for each missing required writable root; empty if all required paths are present.
    """
    selected_name, _ = active_permission_profile(config)
    writable_roots = permission_profile_workspace_roots(config)
    errors: list[str] = []
    for required_path in REQUIRED_TOOL_CACHE_PATHS:
        if required_path not in writable_roots:
            errors.append(f'permissions.{selected_name}.workspace_roots must include {required_path} for mise/npm/uv/corepack/SwiftPM/Tessl runtime writes')
    return errors

def validate_config_maintenance_write_access(config: dict[str, object]) -> list[str]:
    """Keep repository writes task-scoped instead of granting them globally."""
    errors: list[str] = []
    permissions = config.get('permissions')
    if not isinstance(permissions, dict):
        return errors
    protected = [Path(path).resolve() for path in DISALLOWED_GLOBAL_REPOSITORY_WRITE_PATHS]
    for profile_name, profile in sorted(permissions.items()):
        if not isinstance(profile, dict):
            continue
        for surface in ('workspace_roots', 'filesystem'):
            roots = profile.get(surface)
            if not isinstance(roots, dict):
                continue
            entries = list(roots.items())
            if surface == 'filesystem':
                entries = []
                for base, access in roots.items():
                    if isinstance(base, str) and isinstance(access, dict):
                        entries.extend(((base if subpath == '.' else str(Path(base) / subpath), mode) for subpath, mode in access.items() if isinstance(subpath, str)))
                    else:
                        entries.append((base, access))
            for root, access in entries:
                writable = access is True if surface == 'workspace_roots' else access == 'write'
                if not isinstance(root, str) or not writable:
                    continue
                path_text = '/' if root == ':root' else root
                if surface == 'filesystem' and path_text.endswith('/**'):
                    path_text = path_text[:-3] or '/'
                if surface == 'filesystem' and any(char in path_text for char in '*?[]{}'):
                    errors.append(f'permissions.{profile_name}.{surface} must use an exact write path instead of {root}; use task-scoped access')
                    continue
                try:
                    resolved = Path(path_text).expanduser().resolve()
                except (OSError, RuntimeError):
                    errors.append(f'permissions.{profile_name}.{surface} cannot resolve {root}')
                    continue
                if any(path == resolved or resolved in path.parents for path in protected):
                    errors.append(f'permissions.{profile_name}.{surface} must not grant {root} globally; use task-scoped access')
    return errors

def validate_auth_environment_fifo_access(config: dict[str, object]) -> list[str]:
    """Require exact read access to the auth FIFO, not a directory workspace root."""
    errors: list[str] = []
    permissions = config.get('permissions')
    if not isinstance(permissions, dict):
        return errors
    for profile_name in NETWORKED_PERMISSION_PROFILES:
        profile = permissions.get(profile_name)
        filesystem = profile.get('filesystem') if isinstance(profile, dict) else None
        roots = profile.get('workspace_roots') if isinstance(profile, dict) else None
        if not isinstance(filesystem, dict) or filesystem.get(AUTH_ENV_FIFO_PATH) != 'read' or (isinstance(roots, dict) and AUTH_ENV_FIFO_PATH in roots):
            errors.append(f'permissions.{profile_name}.filesystem must grant read-only access to {AUTH_ENV_FIFO_PATH}, without a FIFO workspace root')
    return errors

def validate_browser_runtime_policy(config: dict[str, object]) -> list[str]:
    """Keep Browser, Chrome, Playwright, and Computer Use runtime paths aligned."""
    errors: list[str] = []
    notify = config.get('notify')
    if isinstance(notify, list) and any('SkyComputerUseClient' in str(part) for part in notify):
        errors.append('notify must not launch SkyComputerUseClient; route Computer Use through SkyComputerUseService')
    permissions = config.get('permissions')
    if not isinstance(permissions, dict):
        return errors
    for profile_name in sorted(EDIT_PERMISSION_PROFILE_NAMES):
        profile = permissions.get(profile_name)
        if not isinstance(profile, dict):
            continue
        workspace_roots = profile.get('workspace_roots')
        if not isinstance(workspace_roots, dict):
            errors.append(f'permissions.{profile_name}.workspace_roots must exist')
            continue
        for required_path in (*PLUGIN_RUNTIME_WRITE_PATHS, *BROWSER_RUNTIME_WRITE_PATHS):
            if workspace_roots.get(required_path) is not True:
                errors.append(f'permissions.{profile_name}.workspace_roots must include {required_path} for installed plugin, Browser, Playwright, and Computer Use runtime access')
    workspace_net = permissions.get('workspace-net')
    if isinstance(workspace_net, dict):
        network = workspace_net.get('network')
        domains = network.get('domains') if isinstance(network, dict) else None
        if isinstance(domains, dict):
            for domain in BROWSER_RUNTIME_DOWNLOAD_DOMAINS:
                if domains.get(domain) != 'allow':
                    errors.append(f'permissions.workspace-net.network.domains."{domain}" must allow Playwright browser downloads')
            for domain in TESSL_RUNTIME_DOWNLOAD_DOMAINS:
                if domains.get(domain) != 'allow':
                    errors.append(f'permissions.workspace-net.network.domains."{domain}" must allow Tessl native CLI downloads')
            for domain in TOOLCHAIN_RUNTIME_DOWNLOAD_DOMAINS:
                if domains.get(domain) != 'allow':
                    errors.append(f'permissions.workspace-net.network.domains."{domain}" must allow language and package-manager downloads')
    return errors

def validate_unified_computer_use_runtime_policy(config: dict[str, object], discovery_errors: list[str] | tuple[str, ...]=()) -> list[str]:
    """Keep canonical config out of desktop-owned runtime registration."""
    errors = [f'unified Computer Use runtime discovery failed: {error}' for error in discovery_errors] + validate_computer_use_mcp_policy(config)
    plugins = config.get('plugins')
    if isinstance(plugins, dict):
        for plugin_id in (COMPUTER_USE_PLUGIN_ID, 'computer-use@openai-bundled'):
            if plugin_id in plugins:
                errors.append(f'plugins.{plugin_id} must not appear in canonical config; the desktop app owns plugin consent')
    return errors

def enabled_http_mcp_hosts(config: dict[str, object]) -> set[str]:
    """Return public HTTP MCP hostnames that need sandbox network allow rules."""
    mcp_servers = config.get('mcp_servers')
    if not isinstance(mcp_servers, dict):
        return set()
    hosts: set[str] = set()
    for server in mcp_servers.values():
        if not isinstance(server, dict) or server.get('enabled', True) is not True:
            continue
        url = server.get('url')
        if not isinstance(url, str):
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            continue
        hostname = parsed.hostname
        if hostname in {'localhost', '127.0.0.1'}:
            continue
        hosts.add(hostname)
    return hosts

def validate_mcp_network_access(config: dict[str, object]) -> list[str]:
    """Ensure enabled HTTP MCP servers are reachable from the active network sandbox."""
    errors: list[str] = []
    permissions = config.get('permissions')
    if not isinstance(permissions, dict):
        return errors
    workspace_net = permissions.get('workspace-net')
    if not isinstance(workspace_net, dict):
        return errors
    network = workspace_net.get('network')
    domains = network.get('domains') if isinstance(network, dict) else None
    if not isinstance(domains, dict):
        return errors
    for hostname in sorted(enabled_http_mcp_hosts(config)):
        if domains.get(hostname) != 'allow':
            errors.append(f'permissions.workspace-net.network.domains."{hostname}" must allow the enabled HTTP MCP server inside the sandbox')
    return errors

def validate_no_retired_macos_1password_socket(config: dict[str, object]) -> list[str]:
    """Reject 1Password socket permissions and unrestricted socket access."""
    errors: list[str] = []
    permissions = config.get('permissions')
    if not isinstance(permissions, dict):
        return errors
    for profile_name in NETWORKED_PERMISSION_PROFILES:
        profile = permissions.get(profile_name)
        network = profile.get('network') if isinstance(profile, dict) else None
        unix_sockets = network.get('unix_sockets') if isinstance(network, dict) else None
        if isinstance(unix_sockets, dict):
            for socket_path, label in ((RETIRED_MACOS_ONEPASSWORD_SOCKET, 'retired'), (ONEPASSWORD_SSH_AGENT_SOCKET, 'active')):
                if socket_path in unix_sockets:
                    if label == 'retired':
                        errors.append(f'permissions.{profile_name}.network.unix_sockets."{socket_path}" must be absent on macOS; 1Password CLI uses signed XPC through its bounded host route')
                    else:
                        errors.append(f'permissions.{profile_name}.network.unix_sockets."{socket_path}" must be absent; signed commits use the bounded host-capable Git route')
        if isinstance(network, dict) and network.get('dangerously_allow_all_unix_sockets') is True:
            errors.append(f'permissions.{profile_name}.network.dangerously_allow_all_unix_sockets must be false or absent; arbitrary Unix sockets are forbidden')
    return errors

def _shell_env_pattern_matches(pattern: str, name: str) -> bool:
    """Match Codex's case-insensitive * and ? wildcards, treating brackets literally."""
    return fnmatchcase(name.casefold(), pattern.casefold().replace('[', '[[]'))

def validate_default_signing_socket_absence(config: dict[str, object], *, label: str='') -> list[str]:
    """Reject default-environment access to the 1Password signing socket."""
    shell_env = config.get('shell_environment_policy')
    if not isinstance(shell_env, dict):
        return []
    errors: list[str] = []
    prefix = f'{label} ' if label else ''
    include_only = shell_env.get('include_only')
    if isinstance(include_only, list) and any(isinstance(pattern, str) and _shell_env_pattern_matches(pattern, 'SSH_AUTH_SOCK') for pattern in include_only):
        errors.append(f'{prefix}shell_environment_policy.include_only must not inherit SSH_AUTH_SOCK; signed commits use the bounded host-capable Git route')
    env_values = shell_env.get('set')
    if isinstance(env_values, dict) and 'SSH_AUTH_SOCK' in env_values:
        errors.append(f'{prefix}shell_environment_policy.set must not configure SSH_AUTH_SOCK; the 1Password signing-agent socket must be absent from the default environment; signed commits use the bounded host-capable Git route')
    return errors

def validate_shell_environment_policy(config: dict[str, object]) -> list[str]:
    """Enforce shell env allowlist and cache locations that prevent drift."""
    shell_env = config.get('shell_environment_policy')
    if not isinstance(shell_env, dict):
        return ['shell_environment_policy must be a table']
    errors = validate_default_signing_socket_absence(config)
    if shell_env.get('inherit') != 'all':
        errors.append('shell_environment_policy.inherit must be all before allowlist filtering')
    if shell_env.get('ignore_default_excludes') is not False:
        errors.append('shell_environment_policy.ignore_default_excludes must be false')
    include_only = shell_env.get('include_only')
    include_values = include_only if isinstance(include_only, list) else []
    if not include_values or not all(isinstance(name, str) for name in include_values):
        errors.append('shell_environment_policy.include_only must be a nonempty string list')
    elif any(re.match('[A-Za-z_]', name) is None or name == 'SSH_AUTH_SOCK' for name in include_values):
        errors.append('shell_environment_policy.include_only must not allow unrestricted inheritance')
    for required_name in REQUIRED_SHELL_ENV_INCLUDE_ONLY:
        if required_name not in include_values:
            errors.append(f'shell_environment_policy.include_only must include {required_name} for managed runtime propagation')
    env_set = shell_env.get('set')
    env_values = env_set if isinstance(env_set, dict) else {}
    if env_values.get('COREPACK_HOME') != COREPACK_CACHE_PATH:
        errors.append(f'shell_environment_policy.set.COREPACK_HOME must be {COREPACK_CACHE_PATH}, not a shared temporary directory')
    for name in sorted(LEGACY_NODE_REPL_ENV_KEYS | set(DESKTOP_RUNTIME_ENV_NAMES)):
        if any(isinstance(pattern, str) and _shell_env_pattern_matches(pattern, name) and (not (pattern == name and name in DESKTOP_RUNTIME_ENV_NAMES)) for pattern in include_values):
            errors.append(f'shell_environment_policy.include_only must not retain legacy {name}')
        if name in env_values:
            errors.append(f'shell_environment_policy.set must not retain legacy {name}')
    return errors

def validate_auth_environment_routing_id(config: dict[str, object]) -> list[str]:
    """Validate the local runtime routing ID when Desktop has materialized it."""
    shell_environment_policy = config.get('shell_environment_policy')
    shell_environment_set = shell_environment_policy.get('set') if isinstance(shell_environment_policy, dict) else None
    environment_id = shell_environment_set.get('CODEX_AUTH_ENVIRONMENT_ID') if isinstance(shell_environment_set, dict) else None
    if environment_id is None:
        return []
    valid = False
    if isinstance(environment_id, str):
        compact_id = len(environment_id) == 26 and all(character.isdigit() or 'a' <= character <= 'z' for character in environment_id)
        try:
            uuid_id = str(uuid.UUID(environment_id)) == environment_id.lower()
        except ValueError:
            uuid_id = False
        valid = compact_id or uuid_id
    if valid:
        return []
    return ['~/.codex/config.toml shell_environment_policy.set.CODEX_AUTH_ENVIRONMENT_ID must be a 26-character or UUID 1Password Environment routing ID when set']

def validate_tracked_projection_paths(tracked_paths: list[str]) -> list[str]:
    """Reject tracked repo-local projection paths that should remain generated."""
    errors: list[str] = []
    for tracked_path in tracked_paths:
        normalized = tracked_path.strip('/')
        for disallowed_path in DISALLOWED_TRACKED_PROJECTION_PATHS:
            if normalized == disallowed_path or normalized.startswith(f'{disallowed_path}/'):
                errors.append(f'{disallowed_path}/ must not be tracked; track codex/environments/ as canonical source and leave repo-local .codex/environments/ as generated projection state')
                break
    return sorted(set(errors))

def tracked_repo_paths() -> tuple[list[str], str | None]:
    """Use Git, or its captured public-source inventory in a sealed package."""
    deployed = deployment_module()
    if deployed is not None:
        try:
            deployed.context()
            source = json.loads(deployed.read_regular(deployed.ROOT / 'codex/.public-source.json'))
            paths = [row['path'] for row in source]
            if not paths or len(paths) != len(set(paths)):
                raise ValueError('Source inventory must be nonempty and unique')
            return paths, None
        except (KeyError, OSError, TypeError, ValueError) as error:
            return [], 'unable to inspect captured public-source inventory: ' + str(error)
    try:
        result = subprocess.run(['git', '-C', str(CONFIG_REPO_ROOT), 'ls-files'], check=False, capture_output=True, text=True)
    except OSError as exc:
        return ([], f'unable to inspect git-tracked files: {exc}')
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        return ([], f'unable to inspect git-tracked files: {stderr}')
    return (result.stdout.splitlines(), None)

def validate_local_memory_cli_policy(config: dict[str, object]) -> list[str]:
    """Reject restored access to the retired Local Memory service."""
    errors: list[str] = []
    retired_names = {'local-memory', 'local-memory-mcp', 'localmemory'}
    servers = config.get('mcp_servers', {})
    if isinstance(servers, dict):
        for name, server in servers.items():
            if not isinstance(server, dict) or server.get('enabled') is False:
                continue
            values = [name, server.get('command', '')]
            arguments = server.get('args', [])
            if isinstance(arguments, list):
                values.extend(arguments)
            found = False
            for value in values:
                if not isinstance(value, str):
                    continue
                try:
                    lexer = shlex.shlex(value, posix=True, punctuation_chars=True)
                    lexer.whitespace_split = True
                    tokens = list(lexer)
                except ValueError:
                    tokens = [value]
                for token in tokens:
                    for component in Path(token).parts:
                        candidate = component.lower().replace('_', '-').removeprefix('npm:')
                        candidate = candidate.split('@', 1)[0]
                        if candidate in retired_names:
                            found = True
            if found:
                errors.append(f'mcp_servers.{name} must not enable the retired Local Memory service')
    permissions = config.get('permissions', {})
    profiles = permissions.values() if isinstance(permissions, dict) else ()
    if any(isinstance(profile, dict) and isinstance(profile.get('workspace_roots'), dict) and (profile['workspace_roots'].get(LOCAL_MEMORY_CLI_STATE_PATH) is True) for profile in profiles):
        errors.append('retired Local Memory state must not be a writable root')
    projects = config.get('projects', {})
    if isinstance(projects, dict) and LOCAL_MEMORY_CLI_STATE_PATH in projects:
        errors.append('retired Local Memory state must not be a trusted project')
    return errors

def _contains_computer_use_launcher_component(value: str, *, allow_shell_patterns: bool=False) -> bool:
    """Match launcher names only at executable or path-component boundaries."""
    if COMPUTER_USE_LAUNCHER_BOUNDARY_PATTERN.search(value) is not None:
        return True
    components = COMPUTER_USE_LAUNCHER_VALUE_SEPARATOR_PATTERN.split(value)
    try:
        shell_tokens = shlex.split(value)
    except ValueError:
        shell_tokens = []
    for token in shell_tokens:
        components.extend(re.split('[/\\\\]', token))
    if any(component in COMPUTER_USE_LAUNCHER_COMPONENTS for component in components):
        return True
    if not allow_shell_patterns:
        return False
    extglob_prefixes = ('?(', '*(', '+(', '@(', '!(')
    if any(component.startswith(launcher) and component[len(launcher):].startswith(extglob_prefixes) for component in components for launcher in COMPUTER_USE_LAUNCHER_COMPONENTS):
        return True
    glob_components = (component for component in components if any(character in component for character in '*?['))
    return any(fnmatchcase(launcher, component) for component in glob_components for launcher in COMPUTER_USE_LAUNCHER_COMPONENTS)

def _is_computer_use_launcher(server: object) -> bool:
    """Return whether an MCP server starts a known Computer Use runtime."""
    if not isinstance(server, dict):
        return False
    command = server.get('command')
    parts = [command] if isinstance(command, str) else []
    cwd = server.get('cwd')
    if isinstance(cwd, str):
        parts.append(cwd)
    args = server.get('args')
    if isinstance(args, list):
        parts.extend(str(arg) for arg in args)
    normalized_args = [str(arg) for arg in args] if isinstance(args, list) else []
    expected_root = str(UNIFIED_COMPUTER_USE_PLUGIN_ROOT)
    expected_launcher = str(UNIFIED_COMPUTER_USE_PLUGIN_ROOT / 'scripts' / 'launch.mjs')
    matches_resolved_contract = command == str(UNIFIED_COMPUTER_USE_NODE_PATH) and expected_launcher in normalized_args and (cwd == expected_root)
    if matches_resolved_contract:
        return True
    command_name = Path(command).name if isinstance(command, str) else ''
    for index, part in enumerate(parts):
        if _contains_computer_use_launcher_component(part, allow_shell_patterns=index >= (2 if isinstance(cwd, str) else 1) and command_name in COMPUTER_USE_EXECUTION_WRAPPERS):
            return True
    return False

def validate_computer_use_mcp_policy(config: dict[str, object]) -> list[str]:
    """Use only the app-managed unified Computer Use plugin."""
    errors: list[str] = []
    mcp_servers = config.get('mcp_servers')
    if isinstance(mcp_servers, dict):
        for server_name, server in mcp_servers.items():
            if not isinstance(server, dict):
                continue
            if server_name in {'computer-use', 'node_repl', 'cua_repl'} or _is_computer_use_launcher(server):
                errors.append(f'mcp_servers.{server_name} must not alias a Computer Use launcher; the desktop app owns runtime registration')
    return errors

def validate_trusted_project_scope(config: dict[str, object]) -> list[str]:
    """
    Reject project entries whose path begins with a disallowed scratch-workspace prefix.

    Parameters:
        config (dict[str, object]): Parsed Codex configuration mapping top-level keys to values.

    Returns:
        list[str]: Error messages for each project whose path starts with an entry in `DISALLOWED_PROJECT_PREFIXES`. Returns an empty list if there are no violations or if `projects` is not a mapping.
    """
    projects = config.get('projects')
    if not isinstance(projects, dict):
        return []
    errors: list[str] = []
    for project_path, project_config in projects.items():
        if not isinstance(project_path, str):
            continue
        if not isinstance(project_config, dict):
            continue
        candidate_paths = {project_path}
        try:
            candidate_paths.add(str(Path(project_path).expanduser().resolve(strict=False)))
        except OSError:
            pass
        if any(path.startswith(DISALLOWED_PROJECT_PREFIXES) for path in candidate_paths):
            errors.append(f'''projects."{project_path}{local_path_text('" must not persist in config.toml; Codex scratch workspaces under @HOME@/Documents/Codex/ are transient and must stay project-local under tmp/')}''')
    return errors

def classify_trusted_project_blast_radius(config: dict[str, object]) -> list[str]:
    """Return warning notes for broad or overlapping trusted project roots."""
    projects = config.get('projects')
    if not isinstance(projects, dict):
        return []
    trusted_paths = sorted((project_path for project_path, project_config in projects.items() if isinstance(project_path, str) and isinstance(project_config, dict) and (project_config.get('trust_level') == 'trusted')))
    warnings: list[str] = []
    broad_roots = {'/', WORKSTATION_HOME_PATH, str(Path.home())}
    for project_path in trusted_paths:
        if project_path in broad_roots:
            warnings.append(f'warning: trusted_project_blast_radius=broad path={project_path!r}; requires explicit workstation acceptance')
    overlaps: list[tuple[str, str]] = []
    for index, parent in enumerate(trusted_paths):
        parent_prefix = parent.rstrip('/') + '/'
        for child in trusted_paths[index + 1:]:
            if child.startswith(parent_prefix):
                overlaps.append((parent, child))
    if overlaps:
        examples = ', '.join((f'{parent!r}->{child!r}' for parent, child in overlaps[:5]))
        warnings.append(f'warning: trusted_project_overlap count={len(overlaps)} examples={examples}')
    return warnings

def detect_duplicate_singleton_keys(raw_toml: str) -> list[str]:
    """Detect duplicate singleton assignments in the same TOML table."""
    current_table = ROOT_TABLE_NAME
    array_table_counts: dict[str, int] = {}
    seen: dict[tuple[str, str], int] = {}
    warnings: list[str] = []
    for line_number, raw_line in enumerate(raw_toml.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('[[') and ']]' in stripped:
            table_name = stripped[2:stripped.index(']]')].strip()
            array_table_counts[table_name] = array_table_counts.get(table_name, 0) + 1
            current_table = f'{table_name}[{array_table_counts[table_name]}]'
            continue
        if stripped.startswith('[') and ']' in stripped:
            current_table = stripped[1:stripped.index(']')].strip()
            continue
        if '=' not in stripped:
            continue
        key = stripped.split('=', 1)[0].strip().strip('"')
        if key not in DUPLICATE_SINGLETON_KEYS:
            continue
        seen_key = (current_table, key)
        previous_line = seen.get(seen_key)
        if previous_line is None:
            seen[seen_key] = line_number
            continue
        warnings.append(f'warning: duplicate_singleton_key table={current_table!r} key={key!r} lines={previous_line},{line_number}')
    return warnings

def approvals_reviewer_is_valid(approvals_reviewer: object, valid_agent_roles: set[str]) -> bool:
    """
    Determine whether an approvals reviewer identifier refers to a built-in reviewer or a defined agent role.

    Parameters:
        approvals_reviewer (object): The reviewer identifier to validate; expected to be a string.
        valid_agent_roles (set[str]): Set of agent role names considered valid reviewers.

    Returns:
        True if approvals_reviewer is a string and refers to a built-in reviewer or a member of valid_agent_roles, False otherwise.
    """
    if not isinstance(approvals_reviewer, str):
        return False
    if approvals_reviewer in LEGACY_APPROVALS_REVIEWERS:
        return False
    return approvals_reviewer in BUILTIN_APPROVALS_REVIEWERS or approvals_reviewer in valid_agent_roles

def resolve_config_path(value: str, base_path: Path | None=None) -> Path:
    """Resolve a config path the way this repo expects durable prompt files to resolve."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if base_path is None:
        base_path = HOME_PROJECTION_SOURCE_ROOT
    return base_path / path

def is_canonical_absolute_path(path: Path) -> bool:
    """Return whether a path is absolute and already normalized to its real target."""
    return path.is_absolute() and path == path.resolve(strict=False)

def canonical_paths_match(path: Path, expected: Path) -> bool:
    """Accept case-only spelling differences only for the same filesystem object."""
    if path == expected:
        return True
    if str(path).casefold() != str(expected).casefold():
        return False
    try:
        return path.samefile(expected)
    except OSError:
        return False

def expected_compact_prompt_path() -> Path:
    """Return the canonical compact prompt file path for this repo."""
    return HOME_PROJECTION_SOURCE_ROOT / 'instructions' / 'compact-prompt.md'

def validate_compact_prompt_file_content(path: Path, content: str) -> list[str]:
    """Validate structural drift canaries; runtime evaluation owns semantic quality."""
    errors: list[str] = []
    for required_phrase in REQUIRED_COMPACT_PROMPT_PHRASES:
        if required_phrase not in content:
            errors.append(f'experimental_compact_prompt_file must preserve compact prompt canary {required_phrase!r}: {path}')
    return errors

def validate_prompt_customization(config: dict[str, object]) -> list[str]:
    """Validate root prompt customization fields used by Codex CLI and app sessions."""
    errors: list[str] = []
    developer_instructions = config.get('developer_instructions')
    if developer_instructions is None:
        errors.append('developer_instructions must be defined in the root config')
    elif not isinstance(developer_instructions, str) or not developer_instructions.strip():
        errors.append('developer_instructions must be a non-empty string when provided')
    elif isinstance(developer_instructions, str):
        for required_phrase in REQUIRED_DEVELOPER_INSTRUCTION_PHRASES:
            if required_phrase not in developer_instructions:
                errors.append(f'developer_instructions must preserve operating-contract canary {required_phrase!r}')
    compact_prompt = config.get('compact_prompt')
    if compact_prompt is not None and (not isinstance(compact_prompt, str) or not compact_prompt.strip()):
        errors.append('compact_prompt must be a non-empty string when provided')
    compact_prompt_file = config.get('experimental_compact_prompt_file')
    if compact_prompt_file is not None:
        if not isinstance(compact_prompt_file, str) or not compact_prompt_file.strip():
            errors.append('experimental_compact_prompt_file must be a non-empty string when provided')
        else:
            resolved = resolve_config_path(compact_prompt_file)
            expected_prompt = expected_compact_prompt_path()
            if not canonical_paths_match(resolved, expected_prompt):
                errors.append(f'experimental_compact_prompt_file must point at the canonical repo compact prompt: {expected_prompt}')
            if not resolved.exists():
                errors.append(f'experimental_compact_prompt_file must point at an existing file: {resolved}')
            elif not resolved.is_file():
                errors.append(f'experimental_compact_prompt_file must point at a file: {resolved}')
            else:
                try:
                    content = resolved.read_text(encoding='utf-8')
                except OSError as exc:
                    errors.append(f'experimental_compact_prompt_file must be readable: {resolved} ({exc})')
                except UnicodeDecodeError as exc:
                    errors.append(f'experimental_compact_prompt_file must be valid UTF-8 text: {resolved} ({exc})')
                else:
                    if not content.strip():
                        errors.append(f'experimental_compact_prompt_file must not be empty: {resolved}')
                    else:
                        errors.extend(validate_compact_prompt_file_content(resolved, content))
    if compact_prompt is not None and compact_prompt_file is not None:
        errors.append('compact_prompt and experimental_compact_prompt_file must not both be set; inline compact_prompt takes precedence and would shadow the file')
    return errors

def is_https_or_local(url: str) -> bool:
    """
    Determine whether a URL uses HTTPS or refers to a local HTTP host.

    Returns:
        `true` if the URL's scheme is `https`, or if the scheme is `http` and the hostname is `127.0.0.1` or `localhost`, `false` otherwise.
    """
    parsed = urlparse(url)
    if parsed.scheme == 'https':
        return True
    return bool(parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'})

def scan_cache_roots(cache_root_candidates: tuple[Path, ...]) -> tuple[set[str], list[str]]:
    """
    Scan plugin cache root directories for marketplace/plugin subdirectories.

    Parameters:
        cache_root_candidates (tuple[Path, ...]): Candidate cache root directories to scan.

    Returns:
        allowed (set[str]): Plugin IDs found in the form "<plugin_name>@<marketplace>".
        sources (list[str]): Paths that were found and scanned.
    """
    allowed: set[str] = set()
    sources: list[str] = []
    for cache_root in cache_root_candidates:
        if not cache_root.exists():
            continue
        if not cache_root.is_dir():
            continue
        sources.append(str(cache_root))
        for marketplace_dir in sorted(p for p in cache_root.iterdir() if p.is_dir()):
            for plugin_dir in sorted(p for p in marketplace_dir.iterdir() if p.is_dir()):
                if has_codex_plugin_marker(plugin_dir):
                    allowed.add(f'{plugin_dir.name}@{marketplace_dir.name}')
    return (allowed, sources)

class ValidationResourceError(str):
    """A diagnostic for resources unavailable to the policy validator."""

def parse_marketplace_file(path: Path) -> tuple[set[str], str, list[str]]:
    """
    Parse a marketplace JSON file and extract plugin IDs.

    Parameters:
        path (Path): Path to the marketplace JSON file.

    Returns:
        allowed (set[str]): Plugin IDs found in the form "<plugin_name>@<marketplace>".
        source (str): Path that was parsed.
        errors (list[str]): Parsing errors encountered.
    """
    allowed: set[str] = set()
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        error_msg = f'Failed to parse marketplace JSON {path}: {exc}'
        print(f'[validate-codex-config] {error_msg}', file=sys.stderr)
        errors.append(ValidationResourceError(error_msg) if isinstance(exc, OSError) else error_msg)
        return (allowed, str(path), errors)
    if not isinstance(payload, dict):
        error_msg = f'Marketplace JSON {path} must be an object/dict, got {type(payload).__name__}'
        errors.append(error_msg)
        return (allowed, str(path), errors)
    marketplace_name = payload.get('name')
    if not isinstance(marketplace_name, str) or not marketplace_name.strip():
        error_msg = f"Marketplace JSON {path} missing valid 'name' field"
        errors.append(error_msg)
        return (allowed, str(path), errors)
    entries = payload.get('plugins')
    if not isinstance(entries, list):
        error_msg = f"Marketplace JSON {path} 'plugins' must be a list"
        errors.append(error_msg)
        return (allowed, str(path), errors)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        plugin_name = entry.get('name')
        if not isinstance(plugin_name, str) or not plugin_name.strip():
            continue
        plugin_marketplace = entry.get('marketplace')
        if not isinstance(plugin_marketplace, str) or not plugin_marketplace.strip():
            source = entry.get('source')
            if isinstance(source, dict):
                plugin_marketplace = source.get('marketplace')
        if not isinstance(plugin_marketplace, str) or not plugin_marketplace.strip():
            plugin_marketplace = marketplace_name
        allowed.add(f'{plugin_name}@{plugin_marketplace}')
    return (allowed, str(path), errors)

def parse_marketplaces(paths: tuple[Path, ...]) -> tuple[set[str], list[str], list[str]]:
    """
    Parse marketplace JSON files and extract plugin IDs.

    Parameters:
        paths (tuple[Path, ...]): Paths to marketplace JSON files.

    Returns:
        allowed (set[str]): Plugin IDs found in the form "<plugin_name>@<marketplace>".
        sources (list[str]): Paths that were found and parsed.
        errors (list[str]): Parsing errors encountered across all marketplace files.
    """
    allowed: set[str] = set()
    sources: list[str] = []
    errors: list[str] = []
    for marketplace_path in paths:
        if not marketplace_path.exists():
            continue
        ids, source, parse_errors = parse_marketplace_file(marketplace_path)
        allowed.update(ids)
        sources.append(source)
        errors.extend(parse_errors)
    return (allowed, sources, errors)

def apply_fallback(allowed: set[str], sources: list[str], static_fallback: set[str]) -> tuple[set[str], list[str]]:
    """
    Apply static fallback allowlist when no plugins are discovered.

    Parameters:
        allowed (set[str]): Plugin IDs discovered so far.
        sources (list[str]): Sources consulted so far.
        static_fallback (set[str]): Static fallback allowlist to use when empty.

    Returns:
        allowed (set[str]): The original set if non-empty, otherwise the static fallback.
        sources (list[str]): The original sources if allowed was non-empty, otherwise with "static fallback allowlist" appended.
    """
    if not allowed:
        return (set(static_fallback), [*sources, 'static fallback allowlist'])
    return (allowed, sources)

def has_codex_plugin_marker(plugin_dir: Path) -> bool:
    if (plugin_dir / '.codex-plugin').exists():
        return True
    try:
        return any(version_dir.is_dir() and (version_dir / '.codex-plugin').exists() for version_dir in plugin_dir.iterdir())
    except OSError:
        return False

def validate_marketplace_manifest_paths(marketplace_name: str, source_path: Path) -> tuple[set[str], list[str]]:
    manifests = [source_path / '.agents' / 'plugins' / 'marketplace.json', source_path / 'marketplace.json']
    existing_manifests = [manifest for manifest in manifests if manifest.exists()]
    errors: list[str] = []
    allowed: set[str] = set()
    if not existing_manifests:
        return (allowed, [f'marketplace {marketplace_name!r} source does not contain a supported manifest: {source_path}'])
    for manifest in existing_manifests:
        manifest_allowed, _source, parse_errors = parse_marketplace_file(manifest)
        allowed.update(manifest_allowed)
        errors.extend(parse_errors)
        try:
            payload = json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        entries = payload.get('plugins') if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source = entry.get('source')
            if not isinstance(source, dict):
                continue
            if source.get('source') != 'local':
                continue
            path = source.get('path')
            if not isinstance(path, str) or not path.strip():
                continue
            plugin_path = source_path / path
            if not plugin_path.exists():
                errors.append(f'marketplace {marketplace_name!r} manifest {manifest} references missing local plugin path: {plugin_path}')
    return (allowed, errors)

def scan_config_marketplace_sources(marketplaces: object) -> tuple[set[str], list[str], list[str]]:
    """
    Discover plugin IDs from configured `[marketplaces.*].source` directories in config.toml.

    Parameters:
        marketplaces (object): Parsed `marketplaces` table from config.toml.

    Returns:
        allowed (set[str]): Plugin IDs found in the form "<plugin_name>@<marketplace>".
        sources (list[str]): Marketplace source paths that were scanned.
        errors (list[str]): Validation errors encountered while reading marketplace sources.
    """
    allowed: set[str] = set()
    sources: list[str] = []
    errors: list[str] = []
    if not isinstance(marketplaces, dict):
        return (allowed, sources, errors)
    for marketplace_name, marketplace in sorted(marketplaces.items()):
        if not isinstance(marketplace_name, str) or not marketplace_name.strip():
            continue
        if not isinstance(marketplace, dict):
            continue
        source = marketplace.get('source')
        if not isinstance(source, str) or not source.strip():
            continue
        source_path = Path(source).expanduser()
        if not source_path.exists():
            message = f'marketplace {marketplace_name!r} source path is not currently accessible: {source_path}'
            if marketplace_name in OPTIONAL_CONFIG_MARKETPLACES:
                sources.append(f'{source_path} [{marketplace_name}; optional missing]')
            else:
                errors.append(ValidationResourceError(message))
            continue
        if not source_path.is_dir():
            errors.append(f'marketplace {marketplace_name!r} source must be a directory when provided: {source_path}')
            continue
        sources.append(f'{source_path} [{marketplace_name}]')
        manifest_allowed, manifest_errors = validate_marketplace_manifest_paths(marketplace_name, source_path)
        allowed.update(manifest_allowed)
        errors.extend(manifest_errors)
        for plugin_dir in sorted(p for p in source_path.iterdir() if p.is_dir()):
            if has_codex_plugin_marker(plugin_dir):
                allowed.add(f'{plugin_dir.name}@{marketplace_name}')
        for plugins_dir in (source_path / 'plugins', source_path / '.agents' / 'plugins'):
            if not plugins_dir.exists() or not plugins_dir.is_dir():
                continue
            for plugin_dir in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
                if has_codex_plugin_marker(plugin_dir):
                    allowed.add(f'{plugin_dir.name}@{marketplace_name}')
    return (allowed, sources, errors)

def _discover_allowed_plugin_ids(marketplaces: object) -> tuple[set[str], list[str], list[str]]:
    """
    Build an allowlist of plugin IDs by scanning local plugin caches and marketplace registry files.

    Scans directories listed in PLUGIN_CACHE_ROOT_CANDIDATES for marketplace/plugin subdirectories and parses JSON files in PLUGIN_MARKETPLACE_CANDIDATES for declared plugins. If no plugin IDs are discovered, falls back to STATIC_ALLOWED_PLUGIN_IDS.

    Returns:
        allowed (set[str]): Plugin IDs in the form "<plugin_name>@<marketplace>".
        sources (list[str]): Descriptions of inputs consulted (paths found) or "static fallback allowlist" when the fallback is used.
        errors (list[str]): Parsing errors encountered during marketplace discovery.
    """
    cache_ids, cache_sources = scan_cache_roots(PLUGIN_CACHE_ROOT_CANDIDATES)
    marketplace_ids, marketplace_sources, marketplace_errors = parse_marketplaces(PLUGIN_MARKETPLACE_CANDIDATES)
    configured_ids, configured_sources, configured_errors = scan_config_marketplace_sources(marketplaces)
    allowed = cache_ids | marketplace_ids | configured_ids | STATIC_ALLOWED_PLUGIN_IDS
    sources = cache_sources + marketplace_sources + configured_sources
    discovery_errors = marketplace_errors + configured_errors
    final_allowed, final_sources = apply_fallback(allowed, sources, STATIC_ALLOWED_PLUGIN_IDS)
    return (final_allowed, final_sources, discovery_errors)

def plugin_id_is_allowed(plugin_id: str, allowed_plugin_ids: set[str]) -> bool:
    """
    Determine whether a plugin ID is allowed.

    Parameters:
        plugin_id (str): Plugin ID in "<name>@<marketplace>" format from config.toml.
        allowed_plugin_ids (set[str]): Discovered canonical allowlist entries.

    Returns:
        bool: True when plugin_id is directly present.
    """
    return plugin_id in allowed_plugin_ids

def root_approval_policy_is_allowed(value: object) -> bool:
    """
    Determine whether a repository root `approval_policy` value is allowed under repository rules.

    Parameters:
        value (object): Parsed `approval_policy` from config.toml; may be a string or a mapping.

    Returns:
        bool: `True` if `value` is the string `"never"` or `"on-request"`, or if it is a mapping containing a `"reject"` mapping where every key in `REQUIRED_REJECT_APPROVAL_KEYS` is `True`; `False` otherwise.
    """
    if value in {'never', 'on-request'}:
        return True
    if not isinstance(value, dict):
        return False
    reject = value.get('reject')
    if not isinstance(reject, dict):
        return False
    return all(reject.get(key) is True for key in REQUIRED_REJECT_APPROVAL_KEYS)

def validate_root_approvals_reviewer(data: dict[str, object]) -> list[str]:
    """Require auto-review as the root approval reviewer."""
    if data.get('approvals_reviewer') == 'auto_review':
        return []
    return ['root approvals_reviewer must stay auto_review; guardian_subagent is retired']

def validate_app_approvals_reviewers(data: dict[str, object]) -> list[str]:
    """Require app approval prompts to route through supported reviewers."""
    errors: list[str] = []
    apps = data.get('apps')
    if not isinstance(apps, dict):
        return errors
    default_app_config = apps.get('_default')
    if not isinstance(default_app_config, dict):
        errors.append('apps._default must stay configured for app approval defaults')
    elif default_app_config.get('approvals_reviewer') != 'auto_review':
        errors.append('apps._default.approvals_reviewer must stay auto_review')
    else:
        if default_app_config.get('default_tools_approval_mode') != 'prompt':
            errors.append('apps._default.default_tools_approval_mode must stay prompt')
        if default_app_config.get('destructive_enabled') is not False:
            errors.append('apps._default.destructive_enabled must stay false')
        if default_app_config.get('open_world_enabled') is not False:
            errors.append('apps._default.open_world_enabled must stay false')
    for app_id, app_config in apps.items():
        if not isinstance(app_config, dict):
            errors.append(f'apps.{app_id} must be a table')
            continue
        reviewer = app_config.get('approvals_reviewer')
        if reviewer is not None and reviewer not in BUILTIN_APPROVALS_REVIEWERS:
            errors.append(f'apps.{app_id}.approvals_reviewer must be one of {sorted(BUILTIN_APPROVALS_REVIEWERS)}')
        default_mode = app_config.get('default_tools_approval_mode')
        if default_mode is not None and default_mode not in APP_TOOL_APPROVAL_MODES:
            errors.append(f'apps.{app_id}.default_tools_approval_mode must be one of {sorted(APP_TOOL_APPROVAL_MODES)}')
        tools = app_config.get('tools')
        if tools is not None and (not isinstance(tools, dict)):
            errors.append(f'apps.{app_id}.tools must be a table')
            continue
        if isinstance(tools, dict):
            for tool_name, tool_config in tools.items():
                if not isinstance(tool_config, dict):
                    errors.append(f'apps.{app_id}.tools.{tool_name} must be a table')
                    continue
                approval_mode = tool_config.get('approval_mode')
                if approval_mode is not None and approval_mode not in APP_TOOL_APPROVAL_MODES:
                    errors.append(f'apps.{app_id}.tools.{tool_name}.approval_mode must be one of {sorted(APP_TOOL_APPROVAL_MODES)}')
    return errors

def validate_mcp_tool_approval_modes(data: dict[str, object]) -> list[str]:
    """Keep known MCP tool approval modes aligned with their risk profile."""
    errors: list[str] = []
    mcp_servers = data.get('mcp_servers')
    if not isinstance(mcp_servers, dict):
        return errors
    for (server_name, tool_name), expected_mode in sorted(REQUIRED_MCP_TOOL_APPROVALS.items()):
        if server_name == 'github' and server_name not in mcp_servers:
            continue
        server = mcp_servers.get(server_name)
        if not isinstance(server, dict):
            errors.append(f'mcp server {server_name!r} must stay configured')
            continue
        tools = server.get('tools')
        if not isinstance(tools, dict):
            errors.append(f'mcp_servers.{server_name}.tools must stay configured')
            continue
        tool_config = tools.get(tool_name)
        if not isinstance(tool_config, dict):
            errors.append(f'mcp_servers.{server_name}.tools.{tool_name} must stay configured')
            continue
        approval_mode = tool_config.get('approval_mode')
        if approval_mode != expected_mode:
            errors.append(f'mcp_servers.{server_name}.tools.{tool_name}.approval_mode must stay {expected_mode}')
    return errors

def validate_feature_table(features: object, *, label: str, errors: list[str]) -> dict[str, object]:
    """
    Validate a feature table and append human-readable errors for deprecated, unsupported, or removed feature keys.

    Parameters:
        features (object): Mapping of feature keys to values; if not a mapping, no validation is performed.
        label (str): Prefix used in error messages (e.g., "features" or "profiles.<name>.features").
        errors (list[str]): Mutable list to append validation error messages.

    Returns:
        dict[str, object]: The original `features` mapping when it is a dict; otherwise an empty dict.
    """
    if not isinstance(features, dict):
        errors.append(f'{label} must be a table')
        return {}
    for key in sorted(UNSUPPORTED_LOCAL_FEATURE_KEYS & set(features)):
        errors.append(f'{label}.{key} is not a live Codex feature key; remove it or map it to a current feature')
    for key in sorted(REMOVED_OR_NOOP_FEATURE_KEYS & set(features)):
        errors.append(f'{label}.{key} is removed or ignored by the live Codex feature registry')
    if 'codex_hooks' in features:
        errors.append(f'{label}.codex_hooks is deprecated; use {label}.hooks')
    if 'context_management' in features:
        context_management = features['context_management']
        if not isinstance(context_management, bool) and (not isinstance(context_management, dict) or set(context_management) - {'experimental_mode'} or any(not isinstance(value, bool) for value in context_management.values())):
            errors.append(f'{label}.context_management must be a boolean or a table containing only boolean experimental_mode')
    return features

def validate_multi_agent_v2_schema_policy(features: dict[str, object]) -> list[str]:
    """Keep the local collaboration tool schema aligned with model-reserved functions."""
    multi_agent_v2 = features.get('multi_agent_v2')
    if not isinstance(multi_agent_v2, dict):
        return ['features.multi_agent_v2 must use table form so its reserved tool schema policy is explicit']
    if multi_agent_v2.get('hide_spawn_agent_metadata') is not True:
        return ['features.multi_agent_v2.hide_spawn_agent_metadata must stay true so collaboration.spawn_agent matches the model-reserved schema']
    return []

def feature_enabled(features: dict[str, object], key: str) -> bool:
    """Return whether a boolean or table-form feature is explicitly enabled."""
    feature = features.get(key)
    if isinstance(feature, bool):
        return feature
    if isinstance(feature, dict):
        return feature.get('enabled') is True
    return False

def validate_config_schema_feature_flags() -> list[str]:
    """Reject stale aliases and preserve the checked runtime feature contract."""
    if not CONFIG_SCHEMA_PATH.is_file():
        return [ValidationResourceError(f'config schema does not exist: {CONFIG_SCHEMA_PATH}')]
    try:
        schema = json.loads(CONFIG_SCHEMA_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        message = f'config schema is not readable: {CONFIG_SCHEMA_PATH} ({exc})'
        return [ValidationResourceError(message) if isinstance(exc, OSError) else message]
    feature_properties = schema.get('properties', {}).get('features', {}).get('properties', {}) if isinstance(schema, dict) else {}
    if not isinstance(feature_properties, dict):
        return ['schemas/config.schema.json must define properties.features.properties']
    if 'codex_hooks' in feature_properties:
        return ['schemas/config.schema.json must not advertise deprecated features.codex_hooks; use features.hooks']
    if 'guardian_approval' in feature_properties:
        return ['schemas/config.schema.json must not advertise legacy features.guardian_approval; use features.auto_review']
    removed_feature_keys = [key for key in sorted(REMOVED_OR_NOOP_FEATURE_KEYS) if key in feature_properties]
    if removed_feature_keys:
        return ['schemas/config.schema.json must not advertise removed or ignored feature keys: ' + ', '.join(removed_feature_keys)]
    definitions = schema.get('definitions', {})
    profile = definitions.get('ConfigProfile', {}) if isinstance(definitions, dict) else {}
    profile_properties = profile.get('properties', {}) if isinstance(profile, dict) else {}
    profile_features = profile_properties.get('features', {}) if isinstance(profile_properties, dict) else {}
    profile_feature_properties = profile_features.get('properties', {}) if isinstance(profile_features, dict) else {}
    errors: list[str] = []
    for location, properties in (('properties.features', feature_properties), ('definitions.ConfigProfile.properties.features', profile_feature_properties)):
        context_management = properties.get('context_management') if isinstance(properties, dict) else None
        if context_management != {'$ref': '#/definitions/FeatureToml_for_ContextManagementConfigToml'}:
            errors.append(f'schemas/config.schema.json must reference FeatureToml_for_ContextManagementConfigToml at {location}.properties.context_management')
    union = definitions.get('FeatureToml_for_ContextManagementConfigToml') if isinstance(definitions, dict) else None
    if not isinstance(union, dict) or union.get('anyOf') != [{'type': 'boolean'}, {'$ref': '#/definitions/ContextManagementConfigToml'}]:
        errors.append('context_management schema must accept a boolean or ContextManagementConfigToml')
    table = definitions.get('ContextManagementConfigToml') if isinstance(definitions, dict) else None
    if not isinstance(table, dict) or table.get('type') != 'object' or table.get('additionalProperties') is not False or (not isinstance(table.get('properties'), dict)) or (set(table['properties']) != {'experimental_mode'}) or (not isinstance(table['properties'].get('experimental_mode'), dict)) or (table['properties']['experimental_mode'].get('type') != 'boolean'):
        errors.append('context_management schema must define a closed table with boolean experimental_mode')
    return errors

def app_tool_approval_modes_from_schema(schema_path: Path) -> tuple[set[str], str | None]:
    """Read the AppToolApproval enum from a generated Codex config schema."""
    try:
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        message = f'config schema is not readable: {schema_path} ({exc})'
        return (set(), ValidationResourceError(message) if isinstance(exc, OSError) else message)
    definitions = schema.get('definitions') if isinstance(schema, dict) else None
    approval = definitions.get('AppToolApproval') if isinstance(definitions, dict) else None
    modes = approval.get('enum') if isinstance(approval, dict) else None
    if not isinstance(modes, list) or not all(isinstance(mode, str) for mode in modes):
        return (set(), f'config schema must define definitions.AppToolApproval.enum: {schema_path}')
    return (set(modes), None)

def validate_app_tool_approval_schema_parity(notes: list[str] | None=None) -> list[str]:
    """Keep local approval modes aligned with generated local and live Codex schemas."""
    errors: list[str] = []
    schema_paths = [CONFIG_SCHEMA_PATH]
    if CODEX_SOURCE_SCHEMA_PATH.is_file() and CODEX_SOURCE_SCHEMA_PATH != CONFIG_SCHEMA_PATH:
        schema_paths.append(CODEX_SOURCE_SCHEMA_PATH)
    elif notes is not None:
        notes.append(f'warning: CODEX_SOURCE_SCHEMA_PATH is unavailable ({CODEX_SOURCE_SCHEMA_PATH}); live-schema parity was skipped')
    for schema_path in schema_paths:
        modes, error = app_tool_approval_modes_from_schema(schema_path)
        if error is not None:
            errors.append(error)
        elif modes != APP_TOOL_APPROVAL_MODES:
            errors.append(f'APP_TOOL_APPROVAL_MODES must match {schema_path}: expected {sorted(modes)}, actual {sorted(APP_TOOL_APPROVAL_MODES)}')
    return errors

def profile_model_supports_reasoning_effort(profile: dict[str, object], root_model: object) -> bool:
    """
    Determine whether a profile model supports model_reasoning_effort.

    Parameters:
        profile (dict[str, object]): Parsed standalone `<profile>.config.toml`.
        root_model (object): Root `model` value for inheritance fallback.

    Returns:
        bool: True when the resolved model supports model_reasoning_effort.
    """
    model = profile.get('model', root_model)
    return not isinstance(model, str) or model not in MODELS_WITHOUT_REASONING_EFFORT

def resolved_profile_model(profile: dict[str, object], root_model: object) -> object:
    """Return profile model value with root-level inheritance fallback."""
    return profile.get('model', root_model)

def profile_config_path(profile_name: str) -> Path:
    """Return the repository path for a standalone profile config."""
    return REPO_ROOT / f'{profile_name}.config.toml'

def load_profile_configs(errors: list[str]) -> dict[str, dict[str, object]]:
    """Load and parse standalone profile config files."""
    profiles: dict[str, dict[str, object]] = {}
    discovered_names = {path.name.removesuffix('.config.toml') for path in REPO_ROOT.glob('*.config.toml') if path.name != 'config.toml'}
    unexpected_names = sorted(discovered_names - EXPECTED_PROFILE_NAMES)
    if unexpected_names:
        errors.append(f'unexpected standalone profile configs: {unexpected_names}')
    for name in sorted(EXPECTED_PROFILE_NAMES):
        path = profile_config_path(name)
        if not path.is_file():
            errors.append(f'profile {name!r} must exist at {path.name}')
            continue
        try:
            profile = tomllib.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            errors.append(f'profile {name!r} invalid TOML in {path.name}: {exc}')
            continue
        if not isinstance(profile, dict):
            errors.append(f'profile {name!r} must parse as a TOML table')
            continue
        profiles[name] = profile
    return profiles

def validate_forbidden_global_profiles(*, include_home: bool=True) -> list[str]:
    """Reject workstation-global profile files that Jamie intentionally does not use."""
    errors: list[str] = []
    for name in sorted(FORBIDDEN_GLOBAL_PROFILE_NAMES):
        repo_path = profile_config_path(name)
        home_path = Path.home() / '.codex' / f'{name}.config.toml'
        if repo_path.exists() or repo_path.is_symlink():
            errors.append(f"{repo_path.name} is forbidden; Jamie's global config uses no custom profile")
        if include_home and (home_path.exists() or home_path.is_symlink()):
            errors.append(f"{home_path} is forbidden; Jamie's global config uses no custom profile")
    return errors
_PRUNE_DIR_NAMES = frozenset({'.git', '.tmp', '.venv', 'build', 'dist', 'node_modules', 'target', 'vendor'})
OWNED_GENERATED_CONFIG_ROOTS = (Path.home() / 'dev' / 'trace-narrative' / 'tmp' / 'screenshots',)

def _is_owned_generated_config_root(path: Path) -> bool:
    """Return whether path is inside an explicitly owned generated-output tree."""
    resolved = path.resolve()
    return any(resolved == generated_root.resolve() or generated_root.resolve() in resolved.parents for generated_root in OWNED_GENERATED_CONFIG_ROOTS)

def _iter_codex_config_files(root: Path) -> Iterator[Path]:
    """Yield project-local Codex configs while pruning dependency and build trees."""
    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)
        symlinked_codex_dir = current_dir / '.codex'
        if symlinked_codex_dir.is_symlink():
            config_path = symlinked_codex_dir / 'config.toml'
            if config_path.is_file():
                yield config_path
        dirnames[:] = [name for name in dirnames if name not in _PRUNE_DIR_NAMES and (not _is_owned_generated_config_root(current_dir / name))]
        if current_dir.name == '.codex' and 'config.toml' in filenames:
            yield (current_dir / 'config.toml')

def _is_allowed_project_local_config(path: Path) -> bool:
    """Return whether ``path`` has an explicit, content-validated contract."""
    candidate = Path(os.path.abspath(path))
    return any(candidate == Path(os.path.abspath(allowed_path)) for allowed_path in ALLOWED_PROJECT_LOCAL_CONFIG_PATHS)

def validate_allowed_project_local_config(path: Path) -> list[str]:
    """Validate the narrow content contract for a retained project config."""
    if Path(os.path.abspath(path)) == BORUMI_GENERATED_CONFIG_PATH:
        return validate_borumi_generated_config(path)
    if any(candidate.is_symlink() for candidate in (path, path.parent, path.parent.parent)):
        return [f'allowed LifeOS project config {path} must be a regular file, not a symlink']
    try:
        with path.open('rb') as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f'allowed LifeOS project config {path} is not valid TOML: {exc}']
    if not isinstance(data, dict):
        return [f'allowed LifeOS project config {path} must contain a TOML table']
    unsupported = sorted(set(data) - ALLOWED_LIFEOS_PROJECT_CONFIG_KEYS)
    if unsupported:
        return [f'allowed LifeOS project config {path} contains unsupported top-level keys: {unsupported}; keep only {sorted(ALLOWED_LIFEOS_PROJECT_CONFIG_KEYS)}']
    verbosity = data.get('model_verbosity')
    if verbosity is not None and (not isinstance(verbosity, str)):
        return [f'allowed LifeOS project config {path}.model_verbosity must be a string']
    if verbosity is not None and verbosity not in ALLOWED_LIFEOS_PROJECT_CONFIG_VERBOSITY:
        return [f'allowed LifeOS project config {path}.model_verbosity must be one of {sorted(ALLOWED_LIFEOS_PROJECT_CONFIG_VERBOSITY)}']
    return []

def validate_borumi_generated_config(path: Path) -> list[str]:
    """Accept only Borumi's app-owned MCP descriptor, never policy overrides."""
    if any(candidate.is_symlink() for candidate in (path, path.parent, path.parent.parent)):
        return [f'Borumi generated config {path} must be a regular file, not a symlink']
    try:
        with path.open('rb') as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f'Borumi generated config {path} is not valid TOML: {exc}']
    expected = {'mcp_servers': {'borumi': {'command': '/Applications/Borumi.app/Contents/MacOS/borumi', 'args': ['mcp'], 'cwd': str(path.parent.parent), 'startup_timeout_sec': 10}}}
    if data != expected:
        return [f'Borumi generated config {path} must match the exact app-owned MCP descriptor; policy overrides and additional fields are forbidden']
    return []

def validate_no_project_local_configs() -> list[str]:
    """Enforce global policy with narrowly validated LifeOS and Borumi files."""
    project_configs: set[Path] = set()
    for search_root in PROJECT_CONFIG_SEARCH_ROOTS:
        if search_root.is_dir():
            project_configs.update(_iter_codex_config_files(search_root))
    project_configs.update(path for path in ALLOWED_PROJECT_LOCAL_CONFIG_PATHS if path.exists() or any(parent.is_symlink() for parent in (path.parent, path.parent.parent)))
    errors: list[str] = []
    disallowed_configs: list[Path] = []
    for path in sorted(project_configs):
        if _is_allowed_project_local_config(path):
            errors.extend(validate_allowed_project_local_config(path))
        else:
            disallowed_configs.append(path)
    if disallowed_configs:
        rendered = ', '.join(str(path) for path in disallowed_configs)
        errors.append(f'project-local .codex/config.toml files are forbidden; use the global ~/.codex/config.toml only: {rendered}')
    return errors

def validate_profile_symlinks(errors: list[str]) -> None:
    """Validate home-directory projection for standalone profile config files."""
    for name in sorted(EXPECTED_PROFILE_NAMES):
        home_path = Path.home() / '.codex' / f'{name}.config.toml'
        expected_target = (HOME_PROJECTION_SOURCE_ROOT / f'{name}.config.toml').resolve()
        if not home_path.exists():
            errors.append(f'~/.codex/{name}.config.toml must exist')
        elif not home_path.is_symlink():
            errors.append(f'~/.codex/{name}.config.toml must be a symlink to {profile_config_path(name)}')
        elif not canonical_paths_match(home_path.resolve(), expected_target):
            errors.append(f"~/.codex/{name}.config.toml must resolve to {HOME_PROJECTION_SOURCE_ROOT / f'{name}.config.toml'} (resolved {home_path.resolve()})")

def validate_home_config_projection() -> list[str]:
    """Require the global config projection to be an isolated mutable copy.

    Codex Desktop persists runtime-owned settings back to ``~/.codex/config.toml``.
    Keeping that path as a symlink (or hard link) makes those writes modify the
    tracked policy source, so the main config is intentionally projected as a
    regular file. Standalone profile files remain symlinked and are validated by
    ``validate_profile_symlinks``.
    """
    errors: list[str] = []
    if not HOME_CONFIG_PATH.exists():
        return ['~/.codex/config.toml must exist as a mutable runtime copy']
    if HOME_CONFIG_PATH.is_symlink():
        return [f'~/.codex/config.toml must be a regular mutable runtime copy, not a symlink; source is {CONFIG_PATH}']
    if not HOME_CONFIG_PATH.is_file():
        return ['~/.codex/config.toml must be a regular mutable runtime copy']
    try:
        if CONFIG_PATH.exists() and HOME_CONFIG_PATH.samefile(CONFIG_PATH):
            errors.append('~/.codex/config.toml must not share the tracked config.toml inode; project it with strategy=copy-runtime')
    except OSError:
        pass
    try:
        parsed = tomllib.loads(HOME_CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        errors.append(f'~/.codex/config.toml mutable runtime copy must be valid TOML: {exc}')
    else:
        if not isinstance(parsed, dict):
            errors.append('~/.codex/config.toml mutable runtime copy must parse as a TOML table')
        elif not errors:
            errors.extend(validate_auth_environment_routing_id(parsed))
            errors.extend(validate_default_signing_socket_absence(parsed, label='~/.codex/config.toml'))
    return errors

def validate_profile_configs(profiles: dict[str, dict[str, object]], root_model: object, valid_agent_roles: set[str], errors: list[str]) -> None:
    """Validate standalone profile config policy."""
    for name, profile in sorted(profiles.items()):
        required_keys = set(REQUIRED_PROFILE_KEYS)
        if profile_model_supports_reasoning_effort(profile, root_model):
            required_keys.add('model_reasoning_effort')
        missing = sorted(required_keys - set(profile.keys()))
        if missing:
            errors.append(f'profile {name!r} missing keys in {name}.config.toml: {missing}')
        resolved_model = resolved_profile_model(profile, root_model)
        if not profile_model_supports_reasoning_effort(profile, root_model) and 'model_reasoning_effort' in profile:
            errors.append(f'profile {name!r} uses model {resolved_model!r}, which does not support model_reasoning_effort')
        approval = profile.get('approval_policy')
        default_permissions = profile.get('default_permissions')
        web_search = profile.get('web_search')
        approvals_reviewer = profile.get('approvals_reviewer')
        if 'sandbox_mode' in profile:
            errors.append(f'profile {name!r} must use default_permissions instead of sandbox_mode')
        if default_permissions not in KNOWN_PERMISSION_PROFILE_NAMES:
            errors.append(f'profile {name!r} default_permissions must be one of {sorted(KNOWN_PERMISSION_PROFILE_NAMES)}')
        if 'features' in profile:
            validate_feature_table(profile.get('features'), label=f'{name}.config.toml features', errors=errors)
        if approvals_reviewer is not None:
            if not isinstance(approvals_reviewer, str):
                errors.append(f'profile {name!r} approvals_reviewer must be a string when provided')
            elif not approvals_reviewer_is_valid(approvals_reviewer, valid_agent_roles):
                errors.append(f'profile {name!r} approvals_reviewer:{approvals_reviewer!r} must resolve to {sorted(BUILTIN_APPROVALS_REVIEWERS)} or a defined agent role')
        if approval == 'never' and name not in ALLOWED_NEVER_PROFILES:
            errors.append(f'profile {name!r} uses approval_policy=never but is not in allowed exceptions {sorted(ALLOWED_NEVER_PROFILES)}')
        if approval == 'on-failure':
            errors.append(f'profile {name!r} uses deprecated approval_policy=on-failure; use on-request or never')
        if web_search == 'live' and name not in ALLOWED_LIVE_WEB_PROFILES:
            errors.append(f'profile {name!r} uses live web search but is not in allowed exceptions {sorted(ALLOWED_LIVE_WEB_PROFILES)}')
    validate_oss_profile_contracts(profiles, errors)
    for name, profile in sorted(profiles.items()):
        validate_default_auto_review_policy(profile, f'profile {name!r}', errors)

def validate_profile_mcp_transports(profiles: dict[str, dict[str, object]], errors: list[str]) -> None:
    """Keep standalone profile MCP overrides parseable and Desktop-owned."""
    for profile_name, profile in sorted(profiles.items()):
        mcp_servers = profile.get('mcp_servers')
        ownership_profile = dict(profile)
        if profile_name in ISOLATED_OSS_PROFILE_NAMES and isinstance(mcp_servers, dict):
            ownership_profile['mcp_servers'] = {name: server for name, server in mcp_servers.items() if not (name == 'cua_repl' and isinstance(server, dict) and (set(server) == {'enabled', 'required'} or (set(server) == {'command', 'enabled', 'required'} and (server.get('command') == '/usr/bin/false'))) and (server['enabled'] is False) and (server['required'] is False))}
        errors.extend(f'profile {profile_name!r}: {error}' for error in validate_unified_computer_use_runtime_policy(ownership_profile))
        if mcp_servers is None:
            continue
        if not isinstance(mcp_servers, dict):
            errors.append(f'profile {profile_name!r} mcp_servers must be a table')
            continue
        for server_name, server in sorted(mcp_servers.items()):
            if not isinstance(server, dict):
                errors.append(f'profile {profile_name!r} mcp_servers.{server_name} must be a table')
                continue
            if profile_name in ISOLATED_OSS_PROFILE_NAMES and server_name in OSS_INHERITED_MCP_NAMES and (not (profile_name == 'oss-local' and server_name == 'cua_repl')) and (server.get('enabled') is False) and (server.get('required') is False) and ('command' not in server) and ('url' not in server):
                continue
            has_command = isinstance(server.get('command'), str) and bool(server['command'].strip())
            has_url = isinstance(server.get('url'), str) and bool(server['url'].strip())
            if has_command == has_url:
                errors.append(f'profile {profile_name!r} mcp_servers.{server_name} must declare exactly one non-empty command or url transport')

def validate_default_auto_review_policy(config: dict[str, object], label: str, errors: list[str]) -> None:
    """Keep the active reviewer policy instead of replacing it with local prose."""
    if 'auto_review' not in config:
        return
    auto_review = config['auto_review']
    if not isinstance(auto_review, dict):
        errors.append(f'{label} auto_review must be a table')
    elif 'policy' in auto_review:
        errors.append(f'{label} must omit auto_review.policy to inherit the active reviewer policy')

def validate_oss_profile_contracts(profiles: dict[str, dict[str, object]], errors: list[str]) -> None:
    """Keep OSS profiles consistent and bound readonly MCP exceptions."""
    for name, profile in sorted(profiles.items()):
        if name in READONLY_OSS_1PASSWORD_OVERLAY_PROFILES:
            continue
        mcp_servers = profile.get('mcp_servers')
        if isinstance(mcp_servers, dict) and '1password' in mcp_servers:
            errors.append(f'profile {name!r} must not declare mcp_servers.1password; only readonly OSS profiles may retain that disabled overlay')
    for name in sorted(OSS_PROFILE_NAMES & profiles.keys()):
        profile = profiles[name]
        model = profile.get('model')
        if not isinstance(model, str) or not model.strip():
            errors.append(f'profile {name!r} must declare a non-empty model')
        if profile.get('default_permissions') != 'readonly-net':
            errors.append(f'profile {name!r} must use default_permissions=readonly-net')
        if profile.get('approval_policy') != 'on-request':
            errors.append(f'profile {name!r} must use approval_policy=on-request')
        if profile.get('approvals_reviewer') != 'auto_review':
            errors.append(f'profile {name!r} must use approvals_reviewer=auto_review')
        expected_provider = OSS_PROFILE_PROVIDER_NAMES[name]
        if profile.get('model_provider') != expected_provider:
            errors.append(f'profile {name!r} must use model_provider={expected_provider!r}')
        model_providers = profile.get('model_providers')
        if isinstance(model_providers, dict):
            for provider_id in sorted(CODEX_NON_OVERRIDABLE_MODEL_PROVIDER_IDS & model_providers.keys()):
                errors.append(f'profile {name!r} must not override the reserved built-in model provider {provider_id!r}')
        if name == 'oss-cloud':
            cloud_provider = model_providers.get(OSS_CLOUD_PROVIDER_ID) if isinstance(model_providers, dict) else None
            if not isinstance(cloud_provider, dict):
                errors.append("profile 'oss-cloud' must declare the model_providers.ollama-cloud custom provider")
            else:
                for field_name, expected_value in OSS_CLOUD_PROVIDER_CONTRACT.items():
                    if cloud_provider.get(field_name) != expected_value:
                        errors.append(f"profile 'oss-cloud' model_providers.ollama-cloud.{field_name} must be {expected_value!r}")
        if profile.get('web_search') == 'live':
            errors.append(f'profile {name!r} must not enable live web search')
        mcp_servers = profile.get('mcp_servers')
        legacy_computer_use_overlay = None
        if isinstance(mcp_servers, dict):
            legacy_computer_use_overlay = next((server_name for server_name in ('computer-use', 'node_repl') if server_name in mcp_servers), None)
        if legacy_computer_use_overlay is not None:
            errors.append(f'profile {name!r} must not declare mcp_servers.{legacy_computer_use_overlay}; the app-managed unified Computer Use plugin is outside OSS profiles')
        onepassword_overlay = mcp_servers.get('1password') if isinstance(mcp_servers, dict) else None
        if name in READONLY_OSS_1PASSWORD_OVERLAY_PROFILES:
            if onepassword_overlay is None:
                errors.append(f'profile {name!r} mcp_servers.1password overlay must retain enabled=false and required=false')
            elif not isinstance(onepassword_overlay, dict):
                errors.append(f'profile {name!r} mcp_servers.1password overlay must be a table')
            else:
                if onepassword_overlay.get('enabled') is not False:
                    errors.append(f'profile {name!r} 1password overlay must stay enabled=false')
                if onepassword_overlay.get('required') is not False:
                    errors.append(f'profile {name!r} 1password overlay must stay required=false')
        if name == 'oss-cloud':
            for server_name in sorted(OSS_CLOUD_DISABLED_MCP_OVERLAYS):
                overlay = mcp_servers.get(server_name) if isinstance(mcp_servers, dict) else None
                if not isinstance(overlay, dict):
                    errors.append(f"profile 'oss-cloud' mcp_servers.{server_name} overlay must retain enabled=false and required=false")
                    continue
                if overlay.get('enabled') is not False:
                    errors.append(f"profile 'oss-cloud' {server_name} overlay must stay enabled=false")
                if overlay.get('required') is not False:
                    errors.append(f"profile 'oss-cloud' {server_name} overlay must stay required=false")

def validate_oss_profile_isolation(profiles: dict[str, dict[str, object]], errors: list[str]) -> None:
    """Require every projected OSS lane to disable inherited private surfaces."""
    for name in sorted(ISOLATED_OSS_PROFILE_NAMES):
        profile = profiles.get(name)
        if not isinstance(profile, dict):
            continue
        features = profile.get('features')
        for feature_name in sorted(OSS_ISOLATION_FEATURES):
            if not isinstance(features, dict) or features.get(feature_name) is not False:
                errors.append(f'profile {name!r} features.{feature_name} must stay false for OSS isolation')
        mcp_servers = profile.get('mcp_servers')
        required_servers = OSS_INHERITED_MCP_NAMES | {'borumi'}
        for server_name in sorted(required_servers):
            overlay = mcp_servers.get(server_name) if isinstance(mcp_servers, dict) else None
            if not isinstance(overlay, dict):
                errors.append(f'profile {name!r} mcp_servers.{server_name} must retain enabled=false and required=false for OSS isolation')
                continue
            if overlay.get('enabled') is not False or overlay.get('required') is not False:
                errors.append(f'profile {name!r} mcp_servers.{server_name} must stay enabled=false and required=false for OSS isolation')

def validate_agent_registry(data: dict[str, object]) -> list[str]:
    """Validate [agents] limits and enforce this repository's role retirement."""
    errors: list[str] = []
    agents = data.get('agents', {})
    if not isinstance(agents, dict):
        return errors
    max_threads = agents.get('max_threads')
    if max_threads is not None and (isinstance(max_threads, bool) or not isinstance(max_threads, int) or max_threads < 1):
        errors.append('[agents].max_threads must be an integer >= 1')
    interrupt_message = agents.get('interrupt_message')
    if interrupt_message is not None and (not isinstance(interrupt_message, bool)):
        errors.append('[agents].interrupt_message must be a boolean when provided')
    if 'enabled' in agents:
        errors.append('[agents].enabled is unsupported; use [features.multi_agent_v2].enabled instead')
    max_depth = agents.get('max_depth')
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 2:
        errors.append('[agents].max_depth must be an integer >= 2')
    job_max_runtime = agents.get('job_max_runtime_seconds')
    if isinstance(job_max_runtime, bool) or not isinstance(job_max_runtime, int) or job_max_runtime < 60:
        errors.append('[agents].job_max_runtime_seconds must be an integer >= 60')
    for agent_name, agent_config in sorted(agents.items()):
        if agent_name in {'enabled', 'interrupt_message', 'job_max_runtime_seconds', 'max_depth', 'max_threads'}:
            continue
        if not isinstance(agent_config, dict):
            errors.append(f'[agents].{agent_name} is unsupported; use a documented [agents] system setting or a role-object table')
            continue
        if isinstance(agent_config, dict):
            config_file = agent_config.get('config_file')
            if config_file is not None:
                if not isinstance(config_file, str) or not config_file.strip():
                    errors.append(f'agent {agent_name!r} config_file must be a non-empty string when provided')
                    continue
                errors.append(f'agent {agent_name!r} config_file is retired by repository policy; route generic collaborators by task capability and evidence requirements instead')
    return errors

def validate_mcp_command_args(name: str, server: dict[str, object]) -> list[str]:
    args = server.get('args', [])
    if not isinstance(args, list):
        return []
    return [f'mcp server {name!r} hides ephemeral package execution command {arg!r} in args; pin an installed binary instead' for arg in args if isinstance(arg, str) and Path(arg).name in DISALLOWED_EPHEMERAL_MCP_COMMANDS]

def validate_mcp_servers(data: dict[str, object]) -> tuple[list[str], list[str]]:
    """Validate active MCP server shape and workstation-required MCP policy."""
    errors: list[str] = []
    notes: list[str] = []
    mcp_servers = data.get('mcp_servers', {})
    if not isinstance(mcp_servers, dict) or not mcp_servers:
        return (['config.toml must define one or more active mcp_servers'], notes)
    disabled_server_count = 0
    active_server_count = 0
    required_count = 0
    for name, server in sorted(mcp_servers.items()):
        if not isinstance(server, dict):
            errors.append(f'mcp server {name!r} must be a table')
            continue
        enabled = server.get('enabled', True)
        if not isinstance(enabled, bool):
            errors.append(f'mcp server {name!r} enabled must be boolean when provided')
            continue
        if not enabled:
            errors.append(f'mcp_servers.{name}.enabled must stay true; configured MCP servers remain available')
            disabled_server_count += 1
            continue
        active_server_count += 1
        has_command = 'command' in server
        has_url = 'url' in server
        if has_command == has_url:
            errors.append(f'mcp server {name!r} must define exactly one of command or url')
            continue
        if 'startup_timeout_sec' not in server:
            errors.append(f'mcp server {name!r} missing startup_timeout_sec')
        if 'required' not in server or not isinstance(server.get('required'), bool):
            errors.append(f'mcp server {name!r} missing boolean required field')
        elif server.get('required') is True:
            required_count += 1
        if server.get('required') is not False:
            errors.append(f'mcp_servers.{name}.required must stay false; MCP startup must stay non-blocking')
        if has_command:
            command = server.get('command')
            if not isinstance(command, str) or not command.startswith('/'):
                errors.append(f'mcp server {name!r} command must use an absolute path')
            elif Path(command).name in DISALLOWED_EPHEMERAL_MCP_COMMANDS:
                errors.append(f'mcp server {name!r} uses ephemeral package execution command {Path(command).name!r}; pin an installed binary instead')
            errors.extend(validate_mcp_command_args(name, server))
        else:
            url = server.get('url')
            if not isinstance(url, str) or not is_https_or_local(url):
                errors.append(f'mcp server {name!r} url must use https or explicit localhost/127.0.0.1 http')
        if 'http_headers' in server:
            errors.append(f'mcp server {name!r} should not use literal http_headers; prefer bearer_token_env_var or env_http_headers')
    notes.append(f'active_mcp_servers={active_server_count}')
    notes.append(f'disabled_mcp_servers={disabled_server_count}')
    notes.append(f'required_mcp_servers={required_count}')
    return (errors, notes)

def main(raw_config: str | None=None) -> int:
    """
    Validate the repository and runtime Codex configuration against repository and runtime governance rules.

    Parses the repository config TOML, checks filesystem symlink/layout expectations and policy constraints for root fields, standalone profiles, agents, projects, MCP servers, and plugins; prints human-readable errors or notes to stdout and returns an exit status suitable for use as a CLI validator.

    Returns:
        int: Exit status code — `0` if validation passed, `1` if validation failed or the TOML could not be parsed.
    """
    snapshot_only = raw_config is not None
    try:
        if raw_config is None:
            raw_config = CONFIG_PATH.read_text(encoding='utf-8')
        data = tomllib.loads(raw_config)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        print(f'[validate-codex-config] invalid TOML: {exc}')
        return 1
    errors: list[str] = []
    notes: list[str] = []
    notes.extend(detect_duplicate_singleton_keys(raw_config))
    tracked_paths, tracked_paths_error = tracked_repo_paths()
    if tracked_paths_error is not None:
        errors.append(tracked_paths_error)
    else:
        errors.extend(validate_tracked_projection_paths(tracked_paths))
    if REPO_LOCAL_CONFIG_PATH.exists():
        errors.append('repo-local .codex/config.toml is deprecated and must not exist; use the tracked codex/config.toml source and its isolated ~/.codex/config.toml runtime copy')
    if not snapshot_only:
        errors.extend(validate_home_config_projection())
        validate_profile_symlinks(errors)
        if not HOME_HOOKS_PATH.exists():
            errors.append('~/.codex/hooks.json must exist')
        elif HOME_HOOKS_PATH.is_symlink() or not HOME_HOOKS_PATH.is_file():
            errors.append('~/.codex/hooks.json must be a regular managed copy, not a symlink')
        elif not HOOKS_CONFIG_PATH.is_file():
            errors.append('Canonical hooks/hooks.json is missing')
        elif HOME_HOOKS_PATH.samefile(HOOKS_CONFIG_PATH):
            errors.append('Runtime hooks must not share the canonical source inode')
        elif HOME_HOOKS_PATH.read_bytes() != HOOKS_CONFIG_PATH.read_bytes():
            errors.append('~/.codex/hooks.json must match canonical hooks/hooks.json')
        if HOME_AGENTS_PATH.exists() and HOME_AGENTS_PATH.is_symlink():
            errors.append('~/.codex/agents must be a real directory (not a symlink) to avoid duplicate role scans')
        elif HOME_AGENTS_PATH.exists() and (not HOME_AGENTS_PATH.is_dir()):
            errors.append('~/.codex/agents must be a directory')
        elif HOME_AGENTS_PATH.is_dir():
            home_manifest = HOME_AGENTS_PATH / 'manifest.json'
            if home_manifest.exists() or home_manifest.is_symlink():
                errors.append('~/.codex/agents/manifest.json is retired; remove the stale manifest projection')
            role_toml_files = sorted(HOME_AGENTS_PATH.rglob('*.toml'))
            if role_toml_files:
                preview = ', '.join(str(path) for path in role_toml_files[:3])
                if len(role_toml_files) > 3:
                    preview += ', ...'
                errors.append(f'~/.codex/agents must remain free of named-role TOMLs; found {len(role_toml_files)} TOML file(s): {preview}')
    if not root_approval_policy_is_allowed(data.get('approval_policy')):
        errors.append('root approval_policy must stay never, on-request, or reject with all required review gates true')
    errors.extend(validate_root_approvals_reviewer(data))
    errors.extend(validate_app_approvals_reviewers(data))
    errors.extend(validate_mcp_tool_approval_modes(data))
    errors.extend(validate_root_permission_profile_policy(data))
    if data.get('web_search') != 'cached':
        errors.append('root web_search must stay cached')
    root_model = data.get('model')
    errors.extend(validate_root_model(data))
    errors.extend(validate_top_level_reasoning_effort(data))
    errors.extend(validate_goal_feature(data))
    errors.extend(validate_codex_session_evidence_access(data))
    errors.extend(validate_tool_cache_write_access(data))
    errors.extend(validate_config_maintenance_write_access(data))
    errors.extend(validate_auth_environment_fifo_access(data))
    errors.extend(validate_browser_runtime_policy(data))
    errors.extend(validate_unified_computer_use_runtime_policy(data))
    errors.extend(validate_mcp_network_access(data))
    errors.extend(validate_no_retired_macos_1password_socket(data))
    errors.extend(validate_local_memory_cli_policy(data))
    errors.extend(validate_trusted_project_scope(data))
    notes.extend(classify_trusted_project_blast_radius(data))
    errors.extend(validate_prompt_customization(data))
    validate_default_auto_review_policy(data, 'root config', errors)
    errors.extend(validate_config_schema_feature_flags())
    if 'profile' in data:
        errors.append('top-level profile selector is no longer supported; use --profile with ~/.codex/<profile>.config.toml')
    if 'profiles' in data:
        errors.append('legacy [profiles.*] tables are no longer supported; move each profile to <profile>.config.toml')
    errors.extend(validate_shell_environment_policy(data))
    history = data.get('history', {})
    if history.get('persistence') != 'save-all':
        errors.append('history.persistence should stay save-all unless intentionally changed')
    max_bytes = history.get('max_bytes')
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        errors.append('history.max_bytes must be a positive integer')
    otel = data.get('otel', {})
    if otel.get('log_user_prompt') is not False:
        errors.append('otel.log_user_prompt must stay false')
    endpoint = otel.get('exporter', {}).get('otlp-http', {}).get('endpoint')
    if not isinstance(endpoint, str) or not endpoint.startswith('http://127.0.0.1:'):
        errors.append('otel exporter endpoint should point at a local collector on 127.0.0.1')
    features = validate_feature_table(data.get('features', {}), label='features', errors=errors)
    for key in sorted(REQUIRED_FEATURES_TRUE):
        if not feature_enabled(features, key):
            errors.append(f'features.{key} must stay true')
    for key in sorted(REQUIRED_MULTI_AGENT_FEATURES_TRUE):
        if not feature_enabled(features, key):
            errors.append(f'features.{key} must stay true for multi-agent runtime stability')
    for key in sorted(REQUIRED_MULTI_AGENT_FEATURES_FALSE):
        if features.get(key) is not False:
            errors.append(f'features.{key} must stay false until its runtime guard is resolved')
    for key in sorted(REQUIRED_HOOK_FEATURE_KEYS_TRUE):
        if not feature_enabled(features, key):
            errors.append(f'features.{key} must stay true for current hooks behavior')
    errors.extend(validate_multi_agent_v2_schema_policy(features))
    if features.get('exec_permission_approvals') is not True and features.get('request_permissions') is not True:
        errors.append('features.exec_permission_approvals (or legacy features.request_permissions) must stay true')
    valid_agent_roles = configured_agent_role_names(data.get('agents', {}))
    parity_notes: list[str] = []
    errors.extend(validate_app_tool_approval_schema_parity(parity_notes))
    notes.extend(parity_notes)
    errors.extend(validate_forbidden_global_profiles(include_home=not snapshot_only))
    if not snapshot_only:
        errors.extend(validate_no_project_local_configs())
    profiles = load_profile_configs(errors)
    validate_profile_configs(profiles, root_model, valid_agent_roles, errors)
    validate_profile_mcp_transports(profiles, errors)
    validate_oss_profile_isolation(profiles, errors)
    errors.extend(validate_agent_registry(data))
    notes.append('desktop_named_role_registry=retired')
    mcp_errors, mcp_notes = validate_mcp_servers(data)
    errors.extend(mcp_errors)
    notes.extend(mcp_notes)
    allowed_plugin_ids, plugin_sources, plugin_discovery_errors = _discover_allowed_plugin_ids(data.get('marketplaces'))
    notes.append('plugin_allowlist_sources=' + ', '.join(plugin_sources))
    errors.extend(plugin_discovery_errors)
    plugins = data.get('plugins')
    plugin_count = 0
    if plugins is None:
        notes.append('plugins=0')
    elif not isinstance(plugins, dict):
        errors.append('plugins must be a table when provided')
    else:
        if features.get('plugins') is not True:
            errors.append('features.plugins must stay true when [plugins] entries are configured')
        if features.get('plugin_hooks') is True:
            notes.append('plugin_hooks=enabled')
        else:
            notes.append('plugin_hooks=disabled')
        for plugin_name, plugin in sorted(plugins.items()):
            if not isinstance(plugin_name, str) or not plugin_name.strip():
                errors.append('plugins keys must be non-empty strings')
                continue
            if not plugin_id_is_allowed(plugin_name, allowed_plugin_ids):
                errors.append(f'plugin {plugin_name!r} is not in allowed plugin IDs: {sorted(allowed_plugin_ids)}')
                continue
            if not isinstance(plugin, dict):
                errors.append(f'plugin {plugin_name!r} must be a table')
                continue
            enabled = plugin.get('enabled')
            if not isinstance(enabled, bool):
                errors.append(f'plugin {plugin_name!r} missing boolean enabled field')
                continue
            plugin_count += 1
        notes.append(f'plugins={plugin_count}')
    if errors:
        print('[validate-codex-config] validation failed')
        for item in errors:
            print(f'  - {item}')
        return 69 if snapshot_only and any(isinstance(item, ValidationResourceError) for item in errors) else 1
    print('[validate-codex-config] OK')
    print(f'  - profiles={len(profiles)}')
    mcp_servers_for_summary = data.get('mcp_servers', {})
    mcp_server_count = len(mcp_servers_for_summary) if isinstance(mcp_servers_for_summary, dict) else 0
    print(f'  - mcp_servers={mcp_server_count}')
    for note in notes:
        print(f'  - {note}')
    return 0
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-stdin', action='store_true', help='Validate the supplied config snapshot with all normal policy checks')
    arguments = parser.parse_args()
    result = main(sys.stdin.read() if arguments.config_stdin else None)
    raise SystemExit(65 if arguments.config_stdin and result == 1 else result)
