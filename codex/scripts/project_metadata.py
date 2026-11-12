"""Bound project metadata mutations to opened directories, without symlinks."""


from migration_scope import require_policy_path, require_policy_scope

require_policy_scope()

import argparse
import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def metadata_directory(repo: Path, parts: tuple[str, ...], *, create: bool = False):
    """Hold each selected directory open across validation and mutation."""
    descriptors = []
    try:
        current = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(current)
        for part in parts:
            if part in {"", ".", ".."} or "/" in part:
                raise ValueError("metadata component must be a single directory name")
            if create:
                try:
                    os.mkdir(part, dir_fd=current)
                except FileExistsError:
                    pass
            current = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current
            )
            descriptors.append(current)
        yield current
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def write_metadata(repo: Path, parts: tuple[str, ...], leaf: str, content: str) -> None:
    """Atomically publish a regular metadata leaf under verified directories."""
    if leaf in {"", ".", ".."} or "/" in leaf:
        raise ValueError("metadata leaf must be a single filename")
    with metadata_directory(repo, parts, create=True) as directory:
        try:
            existing = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise OSError("metadata output must be a regular file, not a link")
        temporary = f".metadata-{secrets.token_hex(12)}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o666,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                if existing is not None:
                    os.fchmod(handle.fileno(), stat.S_IMODE(existing.st_mode))
                handle.write(content)
            os.replace(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass


def write_environment(repo: Path, content: str) -> None:
    write_metadata(repo, (".codex", "environments"), "environment.toml", content)


def append_learning(repo: Path, entry: str) -> None:
    """Append once through the opened regular project leaf, never a link."""
    with metadata_directory(repo, (".harness", "memory")) as directory:
        descriptor = os.open(
            "LEARNINGS.md",
            os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError("learning log must be a regular file without links")
            if entry not in handle.read():
                handle.write("\n" + entry + "\n")


def _preflight_brain_destination(repo: Path, parts: tuple[str, ...], directory: bool) -> None:
    """Inspect existing destinations without creating or replacing anything."""
    try:
        with metadata_directory(repo, parts if directory else parts[:-1]) as parent:
            if not directory:
                existing = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(existing.st_mode):
                    raise OSError("metadata output must be a regular file, not a link")
    except FileNotFoundError:
        # A missing directory prefix has no existing descendants to overwrite.
        # Publication still validates every directory and leaf when writing.
        pass


def publish_brain(repo: Path, staging: Path) -> None:
    """Validate the complete template and destination tree before publication."""
    source = staging / ".harness"
    if source.is_symlink() or not source.is_dir():
        raise OSError("staged template root must be a directory, not a link")
    entries: list[tuple[tuple[str, ...], str | None]] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise OSError("staged template must not be a symlink")
        relative = path.relative_to(staging)
        if path.is_dir():
            entries.append((relative.parts, None))
        elif path.is_file():
            entries.append((relative.parts, path.read_text()))
        else:
            raise OSError("staged template must be a regular file")
    with metadata_directory(repo, ()):
        _preflight_brain_destination(repo, (".harness",), True)
        for parts, content in entries:
            _preflight_brain_destination(repo, parts, content is None)
        for parts, content in entries:
            if content is None:
                with metadata_directory(repo, parts, create=True):
                    pass
            else:
                write_metadata(repo, parts[:-1], parts[-1], content)


def ensure_ignore(repo: Path) -> None:
    """Append the fixed ignore entry only to a regular, unlinked project file."""
    with metadata_directory(repo, ()) as directory:
        descriptor = os.open(
            ".gitignore",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o644,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError(".gitignore must be a regular file without links")
            content = handle.read()
            if any(
                line in {".codex/config.toml", "/.codex/config.toml"}
                for line in content.splitlines()
            ):
                return
            handle.seek(0, os.SEEK_END)
            handle.write(
                ("\n" if content and not content.endswith("\n") else "")
                + ".codex/config.toml\n"
            )


def remove_config(repo: Path) -> None:
    """Remove the project leaf itself, never a linked parent directory's file."""
    with metadata_directory(repo, (".codex",)) as directory:
        os.unlink("config.toml", dir_fd=directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("ensure-ignore", "remove-config", "append-learning", "publish-brain"),
    )
    parser.add_argument("repo", type=Path)
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    require_policy_path(args.repo)
    try:
        if args.operation == "append-learning" and args.value:
            append_learning(args.repo, args.value)
        elif args.operation == "publish-brain" and args.value:
            require_policy_path(Path(args.value))
            publish_brain(args.repo, Path(args.value))
        elif (
            args.operation in {"ensure-ignore", "remove-config"} and args.value is None
        ):
            {"ensure-ignore": ensure_ignore, "remove-config": remove_config}[
                args.operation
            ](args.repo)
        else:
            parser.error("operation requires its exact operands")
    except OSError as error:
        parser.exit(1, f"project metadata repair blocked: {error}\n")
