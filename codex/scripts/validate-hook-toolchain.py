"""Resolve only the administrator-published, root-protected hook toolchain."""

import os
import stat
from pathlib import Path


PREFIX = Path("/opt/dots-hook-tools")


def protected(path):
    info = path.lstat()
    if info.st_uid != 0 or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
        raise ValueError("Hook toolchain has writable or non-root resources")
    return info


def resolve():
    for parent in (PREFIX, *PREFIX.parents):
        if not stat.S_ISDIR(protected(parent).st_mode):
            raise ValueError("Hook toolchain prefix must be a physical directory")
    current = PREFIX / "current"
    if not stat.S_ISLNK(protected(current).st_mode):
        raise ValueError("Hook toolchain selection must be an admin-owned link")
    root = current.resolve(strict=True)
    if root.parent != PREFIX or len(root.name) != 64 or any(c not in "0123456789abcdef" for c in root.name):
        raise ValueError("Hook toolchain selection is not a versioned payload")
    protected(root)
    for path in root.rglob("*"):
        info = protected(path)
        if stat.S_ISLNK(info.st_mode):
            if not path.resolve(strict=True).is_relative_to(root):
                raise ValueError("Hook toolchain link leaves its protected payload")
        elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError("Hook toolchain contains a special file")
        elif stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("Hook toolchain contains a shared file")
    for name in ("python3", "jq", "gh"):
        executable = root / "bin" / name
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("Hook toolchain executable is missing: " + name)
    return root / "bin"


if __name__ == "__main__":
    try:
        print(resolve())
    except (OSError, ValueError) as error:
        raise SystemExit("Protected hook toolchain unavailable: " + str(error))
