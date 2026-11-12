"""Validate ownership and no-follow paths before trusting cached executables."""
import ctypes
import hashlib
import os
import runpy
import secrets
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path


def _physical(path: Path) -> Path:
    path = path.expanduser().absolute()
    if sys.platform == "darwin":
        for alias, physical in (("/tmp", "/private/tmp"), ("/var", "/private/var")):
            if str(path).startswith(alias + "/"):
                return Path(physical + str(path)[len(alias) :])
    return path

def _open_ancestry(path: Path, *, create: bool, leaf_user_only: bool, follow_symlinks: bool = False) -> int:
    path = _physical(path); fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try: os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError: pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | (0 if follow_symlinks else os.O_NOFOLLOW), dir_fd=fd)
            os.close(fd); fd = child; info = os.fstat(fd)
            sticky = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_uid not in (0, os.getuid()) or (info.st_mode & 0o022 and not sticky):
                raise OSError("Cache ancestry has an unsafe owner or permissions")
        info = os.fstat(fd)
        if leaf_user_only and (info.st_uid != os.getuid() or info.st_mode & 0o022):
            raise OSError("Cache must be owned by the current user and not writable by others")
        return fd
    except Exception:
        os.close(fd); raise

def owned_directory(path: Path) -> None:
    os.close(_open_ancestry(path, create=True, leaf_user_only=True))

def _open_provider() -> int:
    provider = os.path.realpath(sys._base_executable)
    if not provider: raise OSError("Cached Python must refer to the current trusted provider")
    os.close(_open_ancestry(Path(provider).parent, create=False, leaf_user_only=False))
    final = Path(provider).resolve(); parent_fd = _open_ancestry(final.parent, create=False, leaf_user_only=False)
    try: return os.open(final.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    finally: os.close(parent_fd)

def provider_key() -> str:
    fd = _open_provider()
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022: raise OSError("Unsafe Python provider")
        return hashlib.sha256(repr((os.path.realpath(sys._base_executable), info.st_dev, info.st_ino, sys.version)).encode()).hexdigest()[:24]
    finally: os.close(fd)

@contextmanager
def _staging_directory(root: Path, name: str, device: int, inode: int):
    if os.name != "posix" or Path(name).name != name or not name.startswith(".semgrep-build-"): raise OSError("Expected an owned staging leaf")
    root_fd = _open_ancestry(root, create=False, leaf_user_only=True)
    try:
        stage_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            info = os.fstat(stage_fd)
            if (info.st_dev, info.st_ino) != (device, inode) or info.st_uid != os.getuid() or info.st_mode & 0o022: raise OSError("Staging identity changed; preserve replacement")
            cwd_fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fchdir(stage_fd)
                yield stage_fd
            finally:
                os.fchdir(cwd_fd); os.close(cwd_fd)
        finally: os.close(stage_fd)
    finally: os.close(root_fd)

def create_venv(root: Path, name: str, device: int, inode: int) -> None:
    """Build the private cache environment relative to its captured directory."""
    import venv
    with _staging_directory(root, name, device, inode):
        builder = venv.EnvBuilder(symlinks=True, with_pip=False)
        # create() makes env_dir absolute, reopening a mutable pathname.
        context = builder.ensure_directories(".")
        builder.create_configuration(context)
        builder.setup_python(context)
        builder.setup_scripts(context)

def install_staged(root: Path, name: str, device: int, inode: int, arguments: list[str]) -> None:
    root = _physical(root)
    with _staging_directory(root, name, device, inode) as stage_fd:
        run_cached(root, f"{name}/bin/semgrep", arguments, _stage_fd=stage_fd)

def publish_staging(root: Path, source: str, destination: str, device: int, inode: int) -> None:
    if any(name in ("", ".", "..") or Path(name).name != name for name in (source, destination)): raise OSError("Expected cache leaf names")
    fd = _open_ancestry(root, create=False, leaf_user_only=True)
    try:
        stage_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            info = os.fstat(stage_fd)
            if (info.st_dev, info.st_ino) != (device, inode) or info.st_uid != os.getuid() or info.st_mode & 0o022: raise OSError("Staging identity changed; preserve replacement")
            _rename_exclusive(fd, source, destination)
            final = os.stat(destination, dir_fd=fd, follow_symlinks=False)
            if (final.st_dev, final.st_ino) != (device, inode): raise OSError("Published identity changed; preserve destination")
        finally: os.close(stage_fd)
    finally: os.close(fd)

def _rename_exclusive(fd: int, source: str, destination: str) -> None:
    name, flag = ("renameatx_np", 4) if sys.platform == "darwin" else ("renameat2", 1)
    rename = getattr(ctypes.CDLL(None, use_errno=True), name, None)
    if rename is None or sys.platform not in ("darwin", "linux"): raise OSError("Exclusive cache publication is unavailable")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]; rename.restype = ctypes.c_int
    if rename(fd, os.fsencode(source), fd, os.fsencode(destination), flag):
        error = ctypes.get_errno(); raise OSError(error, os.strerror(error))

def _staging_holder_alive(root_fd: int, name: str) -> bool:
    # Lock records the installer process group so SIGKILL of the Bash supervisor
    # preserves live children; kill(0) sees zombies, so census decides abandonment.
    try: lock = os.open(os.path.join(name, ".installer-lock"), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    except OSError: return False
    try:
        pgid = int(os.read(lock, 64).decode().strip())
        if pgid <= 0: return True
        try: os.kill(-pgid, 0)
        except ProcessLookupError: return False
        result = subprocess.run(["/bin/ps", "-A", "-o", "pgid=", "-o", "stat="], capture_output=True, text=True, timeout=2, check=False)
        if result.returncode: return True
        matched = False
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2: return True
            if int(fields[0]) != pgid: continue
            matched = True
            if not fields[1].startswith("Z"): return True
        return not matched
    except (ValueError, OSError, subprocess.TimeoutExpired): return True
    finally: os.close(lock)

def reclaim_stale_staging(root: Path, keep: str | None = None) -> None:
    # keep is accepted for callers but unused: final semgrep-venv-* envs are never
    # auto-pruned so a peer provider key cannot delete an environment still in use.
    fd = _open_ancestry(root, create=True, leaf_user_only=True)
    try:
        for name in os.listdir(fd):
            # Only reclaim abandoned build trees. Init names stay non-reclaimable until rename.
            if Path(name).name != name or not name.startswith(".semgrep-build-"): continue
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or _staging_holder_alive(fd, name): continue
                cleanup_staging(root, name, info.st_dev, info.st_ino)
            except OSError: continue
    finally: os.close(fd)

def create_staging(root: Path) -> tuple[str, int, int]:
    # Initialize under a non-reclaimable name, write the holder PGID, then expose .semgrep-build-*.
    reclaim_stale_staging(root)
    fd = _open_ancestry(root, create=True, leaf_user_only=True)
    try:
        init, name = ".semgrep-init-" + secrets.token_hex(12), ".semgrep-build-" + secrets.token_hex(12)
        os.mkdir(init, mode=0o700, dir_fd=fd)
        lock = os.open(os.path.join(init, ".installer-lock"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try: os.write(lock, str(os.getpgrp()).encode())
        finally: os.close(lock)
        os.rename(init, name, src_dir_fd=fd, dst_dir_fd=fd)
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        return name, info.st_dev, info.st_ino
    finally: os.close(fd)

def cleanup_staging(root: Path, name: str, device: int, inode: int) -> None:
    if Path(name).name != name or not name.startswith((".semgrep-build-", ".semgrep-init-", "semgrep-venv-")): raise OSError("Expected an owned staging leaf")
    fd = _open_ancestry(root, create=False, leaf_user_only=True)
    try:
        stage_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            info = os.fstat(stage_fd)
            if (info.st_dev, info.st_ino) != (device, inode) or info.st_uid != os.getuid(): raise OSError("Staging identity changed; preserve replacement")
            _clear_directory(stage_fd)
            current = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (device, inode): raise OSError("Staging name changed; preserve replacement")
            os.rmdir(name, dir_fd=fd)
        finally: os.close(stage_fd)
    finally: os.close(fd)

def _clear_directory(fd: int) -> None:
    for name in os.listdir(fd):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                captured = os.fstat(child)
                if (captured.st_dev, captured.st_ino) != (info.st_dev, info.st_ino): raise OSError("Staging child changed; preserve replacement")
                _clear_directory(child)
                current = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino): raise OSError("Staging child name changed; preserve replacement")
                os.rmdir(name, dir_fd=fd)
            finally: os.close(child)
        else: os.unlink(name, dir_fd=fd)

def open_cached_file(root: Path, relative: str, *, python: bool = False, _directory_fd: int | None = None) -> int:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part == ".." for part in parts): raise OSError("Invalid cached executable path")
    fd = _open_ancestry(root, create=True, leaf_user_only=True) if _directory_fd is None else os.dup(_directory_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child; info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o022: raise OSError("Unsafe cached executable ancestry")
        leaf = parts[-1]; leaf_stat = os.stat(leaf, dir_fd=fd, follow_symlinks=False); provider_link = False
        if python:
            provider = os.path.realpath(sys._base_executable)
            if not provider: raise OSError("Cached Python must refer to the current trusted provider")
            if stat.S_ISLNK(leaf_stat.st_mode):
                link = os.readlink(leaf, dir_fd=fd)
                target = Path(link) if os.path.isabs(link) else root.joinpath(*parts[:-1], link)
                os.close(_open_ancestry(target.parent, create=False, leaf_user_only=False, follow_symlinks=True))
                if target.resolve() != Path(provider).resolve(): raise OSError("Cached Python must refer to the current trusted provider")
                file_fd, provider_link = _open_provider(), True
            else: file_fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        else: file_fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if python and not provider_link:
                provider_fd = _open_provider()
                try:
                    pinfo = os.fstat(provider_fd)
                    if (info.st_dev, info.st_ino) != (pinfo.st_dev, pinfo.st_ino): raise OSError("Cached Python must refer to the current trusted provider")
                finally: os.close(provider_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022 or (info.st_nlink != 1 and not provider_link):
                raise OSError("Unsafe cached executable")
        except BaseException:
            os.close(file_fd); raise
        return file_fd
    finally: os.close(fd)

def cached_file(root: Path, relative: str, *, python: bool = False) -> None:
    os.close(open_cached_file(root, relative, python=python))

def run_cached(root: Path, relative: str, arguments: list[str], *, _stage_fd: int | None = None) -> None:
    root = _physical(root)
    provider = Path(os.path.realpath(sys._base_executable))
    parts = Path(relative).parts
    if len(parts) != 3 or parts[-2:] != ("bin", "semgrep"): raise OSError("Expected a Semgrep venv launcher")
    pip_mode = arguments[:1] in (["--pip"], ["--bootstrap-pip"])
    if pip_mode != (_stage_fd is not None): raise OSError("Package installation requires captured staging identity")
    provider_fd = open_cached_file(root / parts[0], "bin/python", python=True, _directory_fd=_stage_fd) if pip_mode else open_cached_file(root, str(Path(relative).parent / "python"), python=True)
    try:
        if not pip_mode:
            with os.fdopen(open_cached_file(root, relative), "rb") as launcher: source = launcher.read(2_000_001)
            if len(source) > 2_000_000: raise OSError("Cached launcher exceeds the inspection limit")
        venv = Path(".") if pip_mode else root / parts[0]
        if sys.platform == "linux":
            child_provider = f"/proc/{os.getpid()}/fd/{provider_fd}"
        else:
            # macOS cannot exec /dev/fd. Trust the original outside-cache provider,
            # preserving its validated FD; this does not freeze that trusted path.
            current, held = os.stat(provider, follow_symlinks=False), os.fstat(provider_fd)
            if provider.is_relative_to(root.resolve()) or (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
                raise OSError("Trusted provider changed; preserve the cache")
            child_provider = str(provider)
        sys.executable = sys._base_executable = child_provider
        sys.prefix = sys.exec_prefix = str(venv)
        os.environ.pop("__PYVENV_LAUNCHER__", None)
        import site

        site.ENABLE_USER_SITE = False
        if pip_mode:
            for setting in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT", "PIP_USER", "PIP_EDITABLE", "PIP_SRC"): os.environ.pop(setting, None)
            os.environ["PIP_CONFIG_FILE"] = os.devnull
            sys.path[:0] = site.getsitepackages([str(venv)])
        else:
            for packages in site.getsitepackages([str(venv)]): site.addsitedir(packages)
        if pip_mode:
            if arguments[:1] == ["--bootstrap-pip"]:
                import ensurepip
                wheel = next(Path(ensurepip.__file__).with_name("_bundled").glob("pip-*.whl"), None)
                if wheel is None: raise OSError("Trusted provider has no bundled pip bootstrap wheel")
                sys.path.insert(0, str(wheel))
                arguments = ["--pip", "install", "--no-index", "--no-deps", "--disable-pip-version-check", str(wheel)]
            sys.argv = ["pip", *arguments[1:]]; runpy.run_module("pip", run_name="__main__", alter_sys=True)
        else:
            __import__("pkg_resources")
            sys.argv = [str(root / relative), "--legacy", *arguments]
            # MIG-HELPER-1: execute the validated FD snapshot, never reload a mutable cache path.
            exec(compile(source, str(root / relative), "exec"), {"__name__": "__main__", "__file__": str(root / relative)})  # noqa: S102
    finally:
        os.close(provider_fd)

def main() -> int:
    try:
        if sys.argv[1:] == ["provider-key"]: print(provider_key())
        elif len(sys.argv) == 3 and sys.argv[1] == "stage": print(*create_staging(Path(sys.argv[2])))
        elif len(sys.argv) == 6 and sys.argv[1] == "create-venv": create_venv(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
        elif len(sys.argv) >= 7 and sys.argv[1] == "install-staged": install_staged(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), sys.argv[6:])
        elif len(sys.argv) == 4 and sys.argv[1] == "reclaim": reclaim_stale_staging(Path(sys.argv[2]), keep=sys.argv[3])
        elif len(sys.argv) == 6 and sys.argv[1] == "cleanup": cleanup_staging(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
        elif len(sys.argv) == 7 and sys.argv[1] == "publish":
            try: publish_staging(Path(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6]))
            except FileExistsError: return 73
        elif len(sys.argv) == 3 and sys.argv[1] == "directory": owned_directory(Path(sys.argv[2]))
        elif len(sys.argv) in (4, 5) and sys.argv[1] == "file" and (len(sys.argv) == 4 or sys.argv[4] == "--python"):
            cached_file(Path(sys.argv[2]), sys.argv[3], python=len(sys.argv) == 5)
        elif len(sys.argv) >= 4 and sys.argv[1] == "run": run_cached(Path(sys.argv[2]), sys.argv[3], sys.argv[4:])
        else: raise OSError("Expected directory PATH or file ROOT RELATIVE [--python]")
    except (OSError, ValueError, ImportError, SyntaxError) as exc:
        print(f"Cache rejected: {exc}", file=sys.stderr); return 78
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
