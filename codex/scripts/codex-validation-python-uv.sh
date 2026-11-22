#!/usr/bin/env bash
set -euo pipefail
dots_script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_script_dir/admit-hook-fixture.py" '{}' || exit $?

tmpdir="${TMPDIR:?explicit disposable TMPDIR is required}"
export UV_CACHE_DIR="${CODEX_VALIDATION_UV_CACHE_DIR:-${tmpdir}/configs-uv-cache}"
export XDG_CACHE_HOME="${CODEX_VALIDATION_XDG_CACHE_HOME:-${tmpdir}/configs-xdg-cache}"
export PYTHONPYCACHEPREFIX="${CODEX_VALIDATION_PYTHONPYCACHEPREFIX:-${tmpdir}/configs-pycache}"

# Reuse an explicitly selected, already provisioned interpreter only after the
# exact existing dependency contract passes. This route never installs packages.
if [[ -n "${CODEX_VALIDATION_PYTHON:-}" ]] && "${CODEX_VALIDATION_PYTHON}" -I -B - <<'PY'
import tomllib
import yaml
import pydantic
import markdown_it
assert yaml.__version__ == "6.0.3"
assert pydantic.__version__ == "2.13.4"
assert markdown_it.__version__ == "4.2.0"
PY
then
  exec "${CODEX_VALIDATION_PYTHON}" -B "$@"
fi

uv_python="${CODEX_VALIDATION_UV_PYTHON:-3.12}"
pyyaml_package="pyyaml==6.0.3"
pydantic_package="pydantic==2.13.4"
markdown_package="markdown-it-py==4.2.0"

if bootstrap_stderr="$(uv run --python "${uv_python}" --with "${pyyaml_package}" --with "${pydantic_package}" --with "${markdown_package}" python - 2>&1 >/dev/null <<'PY'
try:
    import tomllib
except ModuleNotFoundError:
    import tomli
import yaml
import pydantic
import markdown_it
assert pydantic.__version__ == "2.13.4"
assert markdown_it.__version__ == "4.2.0"
PY
)"; then
  exec uv run --python "${uv_python}" --with "${pyyaml_package}" --with "${pydantic_package}" --with "${markdown_package}" python "$@"
else
  validation_status=$?
  printf '%s\n' "$bootstrap_stderr" >&2
  printf '[codex-validation-python-uv] dependency bootstrap failed (exit %s)\n' "$validation_status" >&2
  exit "$validation_status"
fi
