"""Check copied source digests and mise pins without evaluating configuration."""
import hashlib
import json
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'migration-sources.json').read_text())
for entry in manifest['files']:
    path = root / entry['destination']
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['candidate_sha256']:
        raise SystemExit('Candidate digest mismatch: ' + entry['destination'])
handler_manifest = root / 'codex/templates/handler-provenance.json'
if handler_manifest.exists():
    for entry in json.loads(handler_manifest.read_text())['files']:
        path = root / entry['path']
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['candidate_sha256']:
            raise SystemExit('Handler port digest mismatch: ' + entry['path'])
    wrapper = (root / 'codex/scripts/codex-validation-python-uv.sh').read_text()
    for requirement in (root / 'requirements/codex-validation.txt').read_text().splitlines():
        if requirement and not requirement.startswith('#') and f'"{requirement}"' not in wrapper:
            raise SystemExit('Validation dependency pin mismatch: ' + requirement)
projection_manifest = root / 'codex/templates/projection-provenance.json'
if projection_manifest.exists():
    projection = json.loads(projection_manifest.read_text())
    for entry in projection['source_files']:
        path = root / entry['path']
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['candidate_sha256']:
            raise SystemExit('Projection dependency digest mismatch: ' + entry['path'])
    if hashlib.sha256((root / 'codex/templates/projection-map.json').read_bytes()).hexdigest() != projection['fixture_map_sha256']:
        raise SystemExit('Closed fixture projection-map digest mismatch')
guidance_manifest = root / 'codex/templates/guidance-provenance.json'
if guidance_manifest.exists():
    for entry in json.loads(guidance_manifest.read_text())['files']:
        path = root / entry['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != entry['candidate_sha256']:
            raise SystemExit('Public guidance or controls digest mismatch: ' + entry['path'])
helper_manifest = root / 'codex/templates/helper-provenance.json'
if helper_manifest.exists():
    helper_data = json.loads(helper_manifest.read_text())
    entries = helper_data['files']
    if helper_data.get('schema_version') != 1 or not entries or len({entry['path'] for entry in entries}) != len(entries):
        raise SystemExit('Helper provenance must contain unique reviewed files')
    for entry in entries:
        path = root / entry['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != entry['candidate_sha256']:
            raise SystemExit('Helper port digest mismatch: ' + entry['path'])
elif (root / 'codex/scripts/verify-work.sh').exists():
    raise SystemExit('Migrated helper inventory is required')
reconciled = root / 'codex/templates/reconciliation-provenance.json'
if reconciled.exists():
    entries = json.loads(reconciled.read_text())['files']
    if not entries or len({entry['path'] for entry in entries}) != len(entries):
        raise SystemExit('Reconciliation inventory must contain unique reviewed files')
    for entry in entries:
        path = root / entry['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != entry['candidate_sha256']:
            raise SystemExit('Reconciled candidate digest mismatch: ' + entry['path'])
for config_name, lock_name in [('mise/config.toml', 'mise/mise.lock')]:
    config = tomllib.loads((root / config_name).read_text())
    lock = tomllib.loads((root / lock_name).read_text())
    for name, value in config['tools'].items():
        version = value['version'] if isinstance(value, dict) else value
        if version == 'latest' or not any(item['version'] == version or item['version'].startswith(version + '.') for item in lock['tools'].get(name, [])):
            raise SystemExit('Missing or inconsistent lock pin: ' + name)
for path in root.rglob('*'):
    if '.git' in path.parts or '__pycache__' in path.parts:
        continue
    if path.is_symlink():
        raise SystemExit('Candidate symlink rejected: ' + path.relative_to(root).as_posix())
    if path.is_file() and (path.name in {'auth.json', '.env'} or path.suffix in {'.db', '.log', '.pem', '.key'}):
        raise SystemExit('Runtime or secret file rejected: ' + path.relative_to(root).as_posix())
print('PASS: copied digests, scalar/inline mise pins, lock coverage and runtime-file boundaries')
