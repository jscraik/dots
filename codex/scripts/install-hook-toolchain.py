"""Install an explicitly reviewed toolchain snapshot into a protected prefix."""

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


PREFIX = Path("/opt/dots-hook-tools")
AIKIDO_MCP_PACKAGE = "@aikidosec/mcp"
AIKIDO_MCP_VERSION = "1.0.10"


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate provider receipt key")
        value[key] = item
    return value


def aikido_provider(root):
    """Validate the reviewed Aikido launcher and its version receipt."""
    executable = root / "bin/aikido-mcp"
    receipt = root / "providers/aikido-mcp.json"
    if not executable.exists() and not receipt.exists():
        return None
    for path in (executable, receipt):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Aikido provider files must be unshared regular files")
    if not os.access(executable, os.X_OK):
        raise ValueError("Aikido provider launcher must be executable")
    if receipt.stat().st_size > 4096:
        raise ValueError("Aikido provider receipt is too large")
    record = json.loads(receipt.read_text(), object_pairs_hook=unique)
    expected = {"schema_version", "package", "version", "executable_sha256"}
    digest = record.get("executable_sha256") if isinstance(record, dict) else None
    if (not isinstance(record, dict) or set(record) != expected
            or type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or record.get("package") != AIKIDO_MCP_PACKAGE
            or record.get("version") != AIKIDO_MCP_VERSION
            or not isinstance(digest, str) or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError("Aikido provider receipt is invalid or has the wrong version")
    if hashlib.sha256(executable.read_bytes()).hexdigest() != digest:
        raise ValueError("Aikido provider launcher differs from its receipt")
    return executable


def check_runtime(root):
    """Prove the provisioned payload works before changing the selection."""
    for name in ("python3", "jq", "gh"):
        path = root / "bin" / name
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("Toolchain executable is missing: " + name)
    commands = (
        [str(root / "bin/python3"), "-I", "-B", "-c",
         "import sys,tomllib,ssl,yaml,pydantic,markdown_it; assert sys.version_info >= (3, 11)"],
        [str(root / "bin/jq"), "--version"],
        [str(root / "bin/gh"), "--version"],
    )
    if (root / 'bin/bun').exists() or (root / 'bin/bun').is_symlink():
        if not (root / 'bin/bun').is_file() or not os.access(root / 'bin/bun', os.X_OK):
            raise ValueError('Optional Bun provider must be executable')
        commands += ([str(root / 'bin/bun'), '--version'],)
    aikido_provider(root)
    with tempfile.TemporaryDirectory(prefix='dots-hook-runtime-check-', dir=Path('/tmp').resolve()) as temporary:
        home = Path(temporary).resolve()
        environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / '.config'), "XDG_DATA_HOME": str(home / '.local/share'),
            "XDG_CACHE_HOME": str(home / '.cache'), "XDG_STATE_HOME": str(home / '.local/state'),
            "GH_CONFIG_DIR": str(home / '.config/gh'), "TMPDIR": str(home / 'tmp')}
        (home / 'tmp').mkdir()
        for command in commands:
            result = subprocess.run(command, env=environment, cwd=home, capture_output=True,
                                    text=True, timeout=30, check=False)
            if result.returncode:
                raise ValueError("Protected toolchain runtime check failed: " + command[0])


def inventory(root):
    records = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            link = path.readlink()
            if link.is_absolute() or not path.resolve(strict=True).is_relative_to(root.resolve()):
                raise ValueError("Toolchain link leaves the payload")
            records[relative] = {"link": str(link)}
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise ValueError("Toolchain contains a shared inode")
            records[relative] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "executable": bool(info.st_mode & stat.S_IXUSR),
            }
        elif stat.S_ISDIR(info.st_mode):
            records[relative] = {"directory": True}
        else:
            raise ValueError("Toolchain contains a special file")
    return records


def digest(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ensure_prefix():
    # The prefix and its ancestors must be physical root-controlled directories.
    for path in reversed((PREFIX, *PREFIX.parents)):
        if not path.exists():
            path.mkdir(mode=0o755)
            path.chmod(0o755)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Toolchain prefix is not protected")


def install(source, expected, select=False):
    if os.geteuid() != 0:
        raise ValueError("Protected toolchain installation requires an explicit admin invocation")
    if not sys.flags.isolated or not sys.flags.no_site:
        raise ValueError("Run admin provisioning with system Python -I -S")
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError("An exact reviewed SHA-256 inventory digest is required")
    ensure_prefix()
    records = inventory(source)
    if digest(records) != expected:
        raise ValueError("Source differs from the reviewed toolchain snapshot")
    destination = PREFIX / expected
    if destination.exists() or destination.is_symlink():
        if not stat.S_ISDIR(destination.lstat().st_mode):
            raise ValueError("Existing version must be a physical directory")
        for path in (destination, *destination.rglob("*")):
            info = path.lstat()
            if info.st_uid != 0 or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
                raise ValueError("Existing version is not protected")
        if inventory(destination) != records:
            raise ValueError("Existing version differs from the reviewed snapshot")
    else:
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=PREFIX) as temporary:
            staged = Path(temporary) / "payload"
            shutil.copytree(source, staged, symlinks=True)
            if inventory(staged) != records:
                raise ValueError("Toolchain changed during copy")
            for path in sorted(staged.rglob("*"), reverse=True):
                if path.is_symlink():
                    os.lchown(path, 0, 0)
                else:
                    os.chown(path, 0, 0)
                    mode = 0o755 if path.is_dir() or records[path.relative_to(staged).as_posix()].get("executable") else 0o644
                    path.chmod(mode)
            staged.chmod(0o755)
            os.rename(staged, destination)
    check_runtime(destination)
    if select:
        current = PREFIX / "current"
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if not stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
                raise ValueError("Existing selection is not an admin-owned link")
        with tempfile.TemporaryDirectory(prefix=".select-", dir=PREFIX) as temporary:
            link = Path(temporary) / "current"
            link.symlink_to(destination.name)
            os.replace(link, current)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--reviewed-sha256")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--select", action="store_true",
                        help="Explicitly select the installed version for hooks")
    args = parser.parse_args()
    if args.inspect:
        print(digest(inventory(args.payload.resolve(strict=True))))
    elif args.reviewed_sha256:
        print(install(args.payload.resolve(strict=True), args.reviewed_sha256, args.select))
    else:
        parser.error("select --inspect or supply --reviewed-sha256 for admin installation")
