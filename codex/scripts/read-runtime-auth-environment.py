#!/usr/bin/env python3
"""Read the managed Environment ID from a regular Codex runtime config."""

from __future__ import annotations

import importlib.util as _scope_import
from pathlib import Path

# Isolated auth validation must not add the mutable source directory to sys.path.
_scope_spec = _scope_import.spec_from_file_location(
    'auth_migration_scope', Path(__file__).resolve().with_name('migration_scope.py'))
_scope = _scope_import.module_from_spec(_scope_spec)
_scope_spec.loader.exec_module(_scope)
require_disposable_scope = _scope.require_disposable_scope
require_fixture_path = _scope.require_fixture_path
require_disposable_scope()

import argparse
import ast
import stat
import sys
from typing import Any

SECTION = "shell_environment_policy.set"
KEY = "CODEX_AUTH_ENVIRONMENT_ID"


def _strict_fallback(text: str) -> str | None:
    """Read one quoted string assignment without pretending to parse all TOML."""
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != SECTION:
            continue
        key, separator, raw_value = line.partition("=")
        if not separator or key.strip() != KEY:
            continue
        try:
            value = ast.literal_eval(raw_value.strip())
        except (SyntaxError, ValueError) as exc:
            raise ValueError("managed Environment ID is not a quoted string") from exc
        if not isinstance(value, str):
            raise ValueError("managed Environment ID is not a string")
        return value
    return None


def _load_toml(path: Path) -> dict[str, Any] | None:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError:
            return None
    with path.open("rb") as handle:
        return tomllib.load(handle)


def read_environment_id(path: Path) -> str | None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("runtime config must be a regular non-symlink file")

    parsed = _load_toml(path)
    if parsed is None:
        return _strict_fallback(path.read_text(encoding="utf-8"))

    shell_policy = parsed.get("shell_environment_policy")
    if not isinstance(shell_policy, dict):
        return None
    environment = shell_policy.get("set")
    if not isinstance(environment, dict):
        return None
    value = environment.get(KEY)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("managed Environment ID is not a string")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    require_fixture_path(args.config)

    try:
        value = read_environment_id(args.config)
    except (OSError, ValueError) as exc:
        print(f"read-runtime-auth-environment: {exc}", file=sys.stderr)
        return 2
    if not value:
        return 1
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
