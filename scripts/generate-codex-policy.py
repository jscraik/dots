"""Render the complete reviewed policy bundle without installing or executing it."""
import argparse
import json
import math
import re
import tomllib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location('dots_stage', ROOT / 'scripts/stage-home.py')
STAGE = module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)
NAMES = ('config', 'docs', 'oss-local', 'oss-local-code', 'oss-local-fallback',
         'oss-security', 'oss-cloud', 'oss-inspect')
TOKEN = re.compile(r'^@local:([a-z0-9_-]+)$')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def read_json(path):
    return json.loads(STAGE.read_regular(Path(path).absolute()),
                      object_pairs_hook=unique_object)


def substitute(value, bindings, used):
    """Only whole string slots can vary; policy structure and types stay fixed."""
    if isinstance(value, str):
        match = TOKEN.fullmatch(value)
        if not match:
            return value
        name = match.group(1)
        replacement = bindings[name]
        if not isinstance(replacement, str) or not replacement or '\x00' in replacement:
            raise ValueError('Invalid local string binding')
        used.add(name)
        return replacement
    if isinstance(value, list):
        return [substitute(item, bindings, used) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key = substitute(key, bindings, used)
            if key in result:
                raise ValueError('Local bindings collide in a policy table')
            result[key] = substitute(item, bindings, used)
        return result
    if type(value) in (bool, int, float):
        return value
    raise ValueError('Unsupported policy value')


def reject_persisted_hook_trust(data: dict) -> None:
    """Hook trust must come from native discovery and an explicit consent event."""
    hooks = data.get('hooks')
    if isinstance(hooks, dict) and 'state' in hooks:
        raise ValueError('Generated policy cannot carry persisted hook trust state')


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return repr(value)
    if isinstance(value, list):
        return '[' + ', '.join(toml_value(item) for item in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(key) + ' = ' + toml_value(item)
                              for key, item in value.items()) + '}'
    raise ValueError('Unsupported TOML value')


def toml_key(value):
    return value if re.fullmatch(r'[A-Za-z0-9_-]+', value) else json.dumps(value, ensure_ascii=False)


def toml_document(data):
    """Use conventional tables required by the existing runtime repair parser."""
    lines = []

    def table(mapping, path):
        if path:
            lines.append('[' + '.'.join(toml_key(part) for part in path) + ']')
        for key, value in mapping.items():
            if not isinstance(value, dict):
                lines.append(toml_key(key) + ' = ' + toml_value(value))
        lines.append('')
        for key, value in mapping.items():
            if isinstance(value, dict):
                table(value, (*path, key))

    table(data, ())
    return '\n'.join(lines)


def render(bindings_path):
    bindings = read_json(bindings_path)
    if not isinstance(bindings, dict):
        raise TypeError('Bindings must be an object')
    projects = bindings.pop('additional_trusted_projects', [])
    if (not isinstance(projects, list) or any(not isinstance(path, str) or not path
            or '\x00' in path or Path(path).anchor != '/'
            or str(Path(path)) != path or Path(path).parent == Path(path)
            or '..' in Path(path).parts for path in projects)
            or len(projects) != len(set(projects))):
        raise ValueError('Additional trusted projects must be unique absolute paths')
    bundle = read_json(ROOT / 'codex/templates/policy-bundle.json')
    if set(bundle) != set(NAMES):
        raise ValueError('Incomplete policy/profile bundle')
    used = set()
    result = {}
    for name in NAMES:
        data = substitute(bundle[name], bindings, used)
        if not isinstance(data, dict):
            raise TypeError('Policy must be a table')
        if name == 'config':
            for path in projects:
                if path in data['projects']:
                    raise ValueError('Additional project duplicates an existing trust binding')
                data['projects'][path] = {'trust_level': 'trusted'}
        output = toml_document(data)
        if tomllib.loads(output) != data:
            raise ValueError('TOML round-trip mismatch')
        result[name] = output
    if used != set(bindings):
        raise ValueError('Unused or unknown local binding')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings', required=True, type=Path)
    args = parser.parse_args()
    try:
        # Keep output private. This command emits no configuration values and
        # deliberately has no live install or arbitrary output-directory mode.
        result = render(args.bindings)
    except (ValueError, TypeError, KeyError, OSError, UnicodeError):
        parser.exit(1, 'Policy generation refused; inspect inputs locally.\n')
    print(f'PASS: generated and TOML-round-tripped {len(result)} policies; no files installed')


if __name__ == '__main__':
    main()
