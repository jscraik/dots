"""Resolve only the administrator-published, root-protected hook toolchain."""

import os
import stat
import importlib.util
import json
import sys
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


def identity():
    """Reuse the administrator installer's inventory format to bind contents."""
    binary_dir = resolve()
    root = binary_dir.parent
    spec = importlib.util.spec_from_file_location(
        'hook_toolchain_inventory', Path(__file__).with_name('install-hook-toolchain.py'))
    inventory_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory_module)
    digest = inventory_module.digest(inventory_module.inventory(root))
    if digest != root.name or resolve() != binary_dir:
        raise ValueError('Protected toolchain contents or selection changed')
    return {'schema_version': 1, 'bin_dir': str(binary_dir), 'payload_sha256': digest}


def runtime_resolve():
    """Keep installed hooks on their sealed selection before child execution."""
    binary_dir = resolve()
    scripts = Path(__file__).resolve().parent
    binding = scripts / '.hook-toolchain.json'
    if not os.path.lexists(binding):
        if any(os.path.lexists(scripts.parent / name)
               for name in ('.deployment.json', '.dots-package.json')):
            raise ValueError('Packaged hook toolchain binding is missing')
        return binary_dir
    info = binding.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
        raise ValueError('Packaged hook toolchain binding is not a bounded regular file')
    expected = {'schema_version': 1, 'bin_dir': str(binary_dir),
                'payload_sha256': binary_dir.parent.name}
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate hook toolchain binding key')
            value[key] = item
        return value
    actual = json.loads(binding.read_text(), object_pairs_hook=unique)
    if not isinstance(actual, dict) or actual != expected or type(actual.get('schema_version')) is not int:
        raise ValueError('Selected toolchain differs from the sealed hook binding')
    return binary_dir


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ['--identity']:
            print(json.dumps(identity(), sort_keys=True))
        elif not sys.argv[1:]:
            print(runtime_resolve())
        else:
            raise ValueError('Unknown toolchain validation operation')
    except (OSError, ValueError) as error:
        raise SystemExit("Protected hook toolchain unavailable: " + str(error))
