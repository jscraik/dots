"""Admit the inactive handler port only with disposable event resources."""
import json
import os
import sys
from pathlib import Path

from migration_scope import (
    deployment_module,
    require_policy_environment,
    require_policy_path,
    require_policy_scope,
)


def admit(event):
    deployed = deployment_module()
    if deployed is not None:
        return deployed.admit_event(event)
    home = require_policy_scope()
    require_policy_environment()
    require_policy_path(Path(__file__).resolve())
    if not os.environ.get('TMPDIR'):
        raise ValueError('An explicit disposable TMPDIR is required for hook fixtures')
    for relative in ('.codex', '.codex/state', '.codex/usage-data', '.codex/config.toml', 'dev'):
        require_policy_path(home / relative)
    if not isinstance(event, dict):
        raise TypeError('Hook event must be an object')
    # These values can become actual filesystem reads/writes; tool arguments
    # remain data for the original command/path guards to classify.
    for name in ('cwd', 'transcript_path'):
        value = event.get(name)
        if value:
            # Read-only event inputs retain the original normalisation tests.
            # Output paths below keep their stricter lexical/alias checks.
            require_policy_path(Path(value).expanduser().resolve())
    tool_input = event.get('tool_input')
    if isinstance(tool_input, dict):
        for name in ('cwd', 'workdir'):
            if tool_input.get(name):
                require_policy_path(Path(tool_input[name]).expanduser())
    card = event.get('runtime_card')
    if isinstance(card, dict) and card.get('path'):
        require_policy_path(Path(card['path']).expanduser())
    resources = [(home / '.codex', False), (home / '.cache', False), (home / 'tmp', True)]
    mutable_names = (
        'CODEX_HOME', 'CODEX_PROJECT_CONFIG_TARGET', 'DOTS_PROJECT_CONFIG_EXCEPTION',
        'CODEX_HOOK_USAGE_ROOT', 'CODEX_COMPACT_HOOK_LOG', 'CODEX_SUBAGENT_HOOK_LOG',
        'CODEX_HOOK_BYPASS_LOG',
        'CODEX_RUNTIME_CARD_PATH', 'CODEX_RUNTIME_CONFIG_DRIFT_PATH',
        'CODEX_SCRATCH_PROJECT_SCRUB_PATH', 'CODEX_COMPUTER_USE_CONFIG_SCRUB_PATH',
        'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'UV_CACHE_DIR',
        'PYTHONPYCACHEPREFIX', 'CODEX_VALIDATION_UV_CACHE_DIR',
        'CODEX_VALIDATION_XDG_CACHE_HOME', 'CODEX_VALIDATION_PYTHONPYCACHEPREFIX',
    )
    input_names = (
        'CODEX_DEV_ROOT',
        'CODEX_LIFEOS_DIR', 'LIFEOS_DIR', 'CODEX_LIFEOS_RETRIEVER',
        'CODEX_LIFEOS_PROJECT_ROOT', 'CODEX_LIFEOS_BUN', 'TMPDIR',
    )
    for name in (*mutable_names, *input_names):
        if os.environ.get(name):
            resource = require_policy_path(Path(os.environ[name]).expanduser())
            resources.append((resource, name in input_names))
    # Writers and runtime-card readers choose nested default paths. Reject
    # pre-existing escaping symlinks at those leaves, including writer-health,
    # context-dedupe and card paths, before any handler reads or appends.
    # This is fixture admission, not protection against concurrent mutation.
    code_root = Path(__file__).resolve().parents[1]
    code_links = {home / '.codex' / name: code_root / name
                  for name in ('hooks', 'scripts', 'instructions', 'schemas', 'model-catalogs', 'rules')}

    def inspect_resource(path, input_aliases):
        require_policy_path(path)
        if not input_aliases and path.is_symlink() and path.is_dir():
            expected = code_links.get(path)
            if expected is None or path.resolve() != expected:
                raise ValueError('Mutable fixture resource directories must not be symlinks')

    seen = set()
    for resource, input_aliases in resources:
        pending = [resource]
        while pending:
            path = pending.pop()
            inspect_resource(path, input_aliases)
            key = (path.resolve(), input_aliases)
            if path.is_dir() and key not in seen:
                seen.add(key)
                # Follow in-root input aliases; their children still undergo
                # admission. Mutable output aliases are rejected above.
                pending.extend(path.iterdir())
    # The original telemetry exporter remains intact, but this inactive fixture
    # entrypoint admits no endpoint or credentials. It exercises local receipts.
    telemetry_names = (
        'CODEX_HOOK_OTEL', 'CODEX_HOOK_TELEMETRY', 'CODEX_HOOK_OTEL_ENABLED', 'CODEX_HOOK_OTEL_ENDPOINT',
        'OTEL_EXPORTER_OTLP_ENDPOINT', 'OTEL_EXPORTER_OTLP_LOGS_ENDPOINT',
    )
    if any(os.environ.get(name) for name in telemetry_names):
        probes = os.environ.get('DOTS_LEGACY_HOOK_PROBES') == '1' and os.environ.get('DOTS_FIXTURE_ROOT')
        endpoints = [os.environ[name] for name in telemetry_names if 'ENDPOINT' in name and os.environ.get(name)]
        if not probes or any(endpoint not in {'http://127.0.0.1:1', 'not-a-url'} for endpoint in endpoints):
            raise ValueError('Only the original unavailable-loopback telemetry probes are admitted')
    return home


if __name__ == '__main__':
    try:
        if len(sys.argv) == 3 and sys.argv[1] == '--provider-path':
            admit({})
            deployed = deployment_module()
            if deployed is None:
                require_policy_path(Path(sys.argv[2]))
            else:
                deployed.require_provider_input(sys.argv[2], 'onepassword')
        elif len(sys.argv) == 4 and sys.argv[1] == '--aikido-input':
            if sys.argv[2] not in {'aikido-binary', 'aikido-reference'}:
                raise ValueError('Unknown Aikido provider-input role')
            admit({})
            deployed = deployment_module()
            if deployed is None:
                require_policy_path(Path(sys.argv[3]))
            else:
                deployed.require_provider_input(sys.argv[3], sys.argv[2])
        else:
            admit(json.loads(sys.argv[1]))
    except (IndexError, OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f'hook fixture admission failed: {exc}', file=sys.stderr)
        raise SystemExit(2)
