"""Check copied source digests and mise pins without evaluating configuration."""
import hashlib
import json
from pathlib import Path
import tomllib

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'migration-sources.json').read_text())
for entry in manifest['files']:
    path = root / entry['destination']
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['candidate_sha256']:
        raise SystemExit('Candidate digest mismatch: ' + entry['destination'])
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
