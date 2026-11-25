"""Stage reviewed defaults in a disposable home; never modify the live home."""
import argparse
import os
import pwd
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'Brewfile': '.Brewfile',
    'mise/config.toml': '.config/mise/config.toml',
    'mise/mise.lock': '.config/mise/mise.lock',
    'terminal/ghostty/config.ghostty': '.config/ghostty/config',
    'terminal/zellij/config.kdl': '.config/zellij/config.kdl',
    'terminal/shell/env': '.local/bin/env',
    'terminal/shell/zshenv': '.zshenv',
    'codex/policy.md': '.codex/AGENTS.md',
}

def open_directory(path):
    """Open each component without following symlinks, including ancestors."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise

def read_regular_at(parent_fd, name, *, non_regular_error='Only regular files are supported'):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(non_regular_error)
        return stream.read()

def read_regular(path):
    parent = open_directory(path.parent)
    try:
        return read_regular_at(parent, path.name)
    finally:
        os.close(parent)

def stage(target, *, preview=None):
    target = Path(os.path.abspath(target))
    temporary_root = Path('/tmp').resolve()
    if target == temporary_root or not target.is_relative_to(temporary_root):
        raise ValueError('Target must be a disposable directory under the system temporary directory')
    # Resolve only for the exclusion check; actual access never follows symlinks.
    resolved = target.resolve()
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    if resolved.is_relative_to(account_home) or resolved == Path.home().resolve() or resolved == ROOT or ROOT.is_relative_to(resolved):
        raise ValueError('Live home and source directories are not staging targets')
    root_fd = open_directory(target)
    try:
        # Preflight all conflicts before creating any files or directories.
        payloads = [(relative, read_regular(ROOT / source)) for source, relative in FILES.items()]
        if preview is not None:
            if not isinstance(preview, bytes):
                raise ValueError('Preview must be validated bytes')
            # Never project an experimental template over real Codex configuration.
            payloads.append(('.dots-preview/codex-config.toml', preview))
        for relative, payload in payloads:
            candidate = target / relative
            for parent in [candidate, *candidate.parents]:
                if parent == target:
                    break
                if parent.is_symlink():
                    raise ValueError('Symlink target rejected')
                if parent != candidate and parent.exists() and not parent.is_dir():
                    raise ValueError('Non-directory target ancestor rejected')
            if candidate.exists() and read_regular(candidate) != payload:
                raise ValueError('Existing different file preserved: ' + relative)
        for relative, payload in payloads:
            fd = os.dup(root_fd)
            try:
                parts = Path(relative).parts
                for component in parts[:-1]:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
                try:
                    output = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                except FileExistsError:
                    # Revalidate the anchored file after preflight, avoiding a replacement race.
                    conflict = 'Concurrent target conflict preserved'
                    if read_regular_at(fd, parts[-1], non_regular_error=conflict) != payload:
                        raise ValueError(conflict)
                else:
                    with os.fdopen(output, 'wb') as stream:
                        stream.write(payload)
            finally:
                os.close(fd)
    finally:
        os.close(root_fd)
    return len(payloads)

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog='A write error can leave partial output in the disposable directory.',
    )
    parser.add_argument('--target-home', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(f'Staged {stage(args.target_home)} defaults; no packages installed and no secrets loaded.')
    except (ValueError, OSError) as error:
        parser.exit(1, f'Staging failed: {error}\n')

if __name__ == '__main__':
    main()

