#!/usr/bin/env bash
set -euo pipefail

# Deliberately ignore PATH and inherited DOTS_CODEX_BIN: runtime proof must use
# the CLI shipped with the desktop app, not a mise/npm installation.
app_cli='/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
if [[ ! -f "$app_cli" || ! -x "$app_cli" ]]; then
  printf 'App-bundled Codex CLI unavailable: %s\n' "$app_cli" >&2
  exit 1
fi
export DOTS_CODEX_BIN="$app_cli"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$repo_root"
python3 -I -B - <<'PY'
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys

for requirement in Path('requirements/codex-validation.txt').read_text().splitlines():
    if not requirement or requirement.startswith('#'):
        continue
    name, expected = requirement.split('==')
    try:
        actual = version(name)
    except PackageNotFoundError:
        actual = 'missing'
    if actual != expected:
        sys.exit(f'Validation dependency {name}: expected {expected}, got {actual}. '
                 'Activate an environment provisioned from requirements/codex-validation.txt.')
PY
"$DOTS_CODEX_BIN" --version
if [[ "$#" -eq 0 ]]; then
  set -- -v
fi
exec python3 -B -m unittest discover -s tests "$@"
