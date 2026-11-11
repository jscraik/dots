"""Render a synthetic Codex template into a disposable home, never live policy."""
import argparse
import importlib.util
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('dots_stage', ROOT / 'scripts/stage-home.py')
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate machine field')
        result[key] = value
    return result


def render(machine_path):
    """Accept one path field; reject secrets and policy overrides by construction."""
    machine = json.loads(STAGE.read_regular(Path(machine_path).absolute()),
                         object_pairs_hook=unique_object)
    if not isinstance(machine, dict) or set(machine) != {'project_root'}:
        raise ValueError('Machine input requires only project_root')
    project = machine['project_root']
    if (not isinstance(project, str) or not project.startswith('/')
            or project == '/' or '..' in project.split('/')
            or any(ord(char) < 32 or ord(char) == 127 for char in project)):
        raise ValueError('Invalid absolute project path')
    template = STAGE.read_regular(ROOT / 'codex/templates/preview.toml').decode()
    if template.count('{{project_root}}') != 1:
        raise ValueError('Template requires exactly one project placeholder')
    # JSON quoted strings are compatible here; TOML parsing below verifies output.
    output = template.replace('{{project_root}}', json.dumps(project, ensure_ascii=False))
    parsed = tomllib.loads(output)
    expected = {'approval_policy': 'on-request', 'sandbox_mode': 'read-only',
                'projects': {project: {'trust_level': 'untrusted'}}}
    if parsed != expected:
        raise ValueError('Preview policy contract changed')
    return output.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--machine-input', type=Path, required=True)
    parser.add_argument('--target-home', type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = render(args.machine_input)
        STAGE.stage(args.target_home, preview=payload)
    except (ValueError, OSError, UnicodeError) as error:
        # Error details can contain machine input; report the class only.
        parser.exit(1, 'Preview refused: ' + type(error).__name__ + '\n')
    print('Staged preview and defaults; live Codex policy was not installed.')


if __name__ == '__main__':
    main()
