#!/usr/bin/env python3
"""Validate the metadata boundary of a 1Password-mounted auth environment."""

from __future__ import annotations

import importlib.util as _scope_import
from pathlib import Path

# Isolated auth validation must not add the mutable source directory to sys.path.
_scope_spec = _scope_import.spec_from_file_location(
    'auth_migration_scope', Path(__file__).resolve().with_name('migration_scope.py'))
_scope = _scope_import.module_from_spec(_scope_spec)
_scope_spec.loader.exec_module(_scope)
require_policy_scope = _scope.require_policy_scope
require_policy_path = _scope.require_policy_path
require_policy_scope()

import argparse
import os
import stat
import sys

EXIT_MOUNT_INVALID = 66


class MountValidationError(ValueError):
    """Raised when a mounted auth environment violates the local contract."""


def validate_mount(path: Path, *, expected_uid: int) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise MountValidationError(f"mounted auth env is missing: {path}") from error
    except OSError as error:
        raise MountValidationError(
            f"mounted auth env metadata is unavailable: {path}: {error.strerror}"
        ) from error

    if stat.S_ISLNK(metadata.st_mode):
        raise MountValidationError(f"mounted auth env must not be a symlink: {path}")
    if not stat.S_ISFIFO(metadata.st_mode):
        raise MountValidationError(f"mounted auth env must be a FIFO: {path}")
    if metadata.st_uid != expected_uid:
        raise MountValidationError(
            f"mounted auth env must be owned by the current user: {path}"
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise MountValidationError(
            f"mounted auth env must not grant group or other access: {path}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a 1Password-mounted auth environment FIFO."
    )
    parser.add_argument("--path", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    require_policy_path(args.path)
    try:
        validate_mount(args.path, expected_uid=os.getuid())
    except MountValidationError as error:
        print(f"run-auth-backed.sh: {error}", file=sys.stderr)
        return EXIT_MOUNT_INVALID
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
