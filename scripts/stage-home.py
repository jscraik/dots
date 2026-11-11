"""Stage reviewed defaults in a disposable home; never modify the live home."""
import argparse
import os
from pathlib import Path
import stat
import tempfile

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

def read_regular(path):
    parent = open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Only regular files are supported')
        return stream.read()

def stage(target):
    target = Path(os.path.abspath(target))
    temporary_roots = tuple(p.resolve() for p in (Path('/private/tmp'), Path('/tmp'), Path(tempfile.gettempdir())))
    if not any(target.is_relative_to(p) and target != p for p in temporary_roots):
        raise ValueError('Target must be a disposable directory under the system temporary directory')
    # Resolve only for the exclusion check; actual access never follows symlinks.
    resolved = target.resolve()
    if resolved == Path.home().resolve() or resolved == ROOT or ROOT.is_relative_to(resolved):
        raise ValueError('Live home and source directories are not staging targets')
    root_fd = open_directory(target)
    plans = []
    try:
        # Preflight all conflicts before creating any files or directories.
        for source, relative in FILES.items():
            payload = read_regular(ROOT / source)
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
            plans.append((relative, payload))
        for relative, payload in plans:
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
                    existing = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    with os.fdopen(existing, 'rb') as stream:
                        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read() != payload:
                            raise ValueError('Concurrent target conflict preserved')
                else:
                    with os.fdopen(output, 'wb') as stream:
                        stream.write(payload)
            finally:
                os.close(fd)
    finally:
        os.close(root_fd)
    return len(plans)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-home', required=True, type=Path)
    args = parser.parse_args()
    try:
        print('Staged %d defaults; no packages installed and no secrets loaded.' % stage(args.target_home))
    except (ValueError, OSError) as error:
        parser.exit(1, 'Staging refused: %s\n' % error)

if __name__ == '__main__':
    main()

