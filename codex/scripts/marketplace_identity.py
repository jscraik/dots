"""Compute a stable identity for a local Codex plugin marketplace tree."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

REVISION_PATTERN = re.compile(r'sha256:[0-9a-f]{64}')
_OPEN_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_OPEN_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


class MarketplaceIdentityError(ValueError):
    """The marketplace cannot be represented as one safe immutable tree."""


@dataclass(frozen=True)
class MarketplaceTreeIdentity:
    """Stable physical and content identity for one marketplace root."""

    revision: str
    device: int
    inode: int


class _Digest(Protocol):
    def update(self, value: bytes) -> None:
        """Add bytes to the digest state."""


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _validate_metadata(info: os.stat_result, relative: bytes, owner_uid: int) -> None:
    label = os.fsdecode(relative) or '.'
    if info.st_uid != owner_uid:
        raise MarketplaceIdentityError(f'marketplace entry has an unsafe owner: {label}')
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise MarketplaceIdentityError(f'marketplace entry is group/world-writable: {label}')
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise MarketplaceIdentityError(f'marketplace file has multiple hard links: {label}')


def _field(digest: _Digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, 'big'))
    digest.update(value)


def _relative_bytes(parts: tuple[str, ...]) -> bytes:
    return b'/'.join(os.fsencode(part) for part in parts)


def _names(fd: int) -> tuple[str, ...]:
    return tuple(sorted(os.listdir(fd), key=os.fsencode))


def _digest_entry(
    parent_fd: int,
    name: str,
    parts: tuple[str, ...],
    digest: _Digest,
    owner_uid: int,
) -> None:
    relative = _relative_bytes(parts)
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(before.st_mode):
        raise MarketplaceIdentityError(
            f'marketplace tree contains a symlink: {os.fsdecode(relative)}'
        )
    if stat.S_ISDIR(before.st_mode):
        child_fd = os.open(name, _OPEN_DIRECTORY_FLAGS, dir_fd=parent_fd)
        try:
            opened = os.fstat(child_fd)
            if _metadata(opened) != _metadata(before):
                raise MarketplaceIdentityError(
                    f'marketplace directory changed while opening: {os.fsdecode(relative)}'
                )
            _validate_metadata(opened, relative, owner_uid)
            digest.update(b'D')
            _field(digest, relative)
            _field(digest, str(stat.S_IMODE(opened.st_mode)).encode())
            names = _names(child_fd)
            for child_name in names:
                _digest_entry(child_fd, child_name, (*parts, child_name), digest, owner_uid)
            if _names(child_fd) != names or _metadata(os.fstat(child_fd)) != _metadata(opened):
                raise MarketplaceIdentityError(
                    f'marketplace directory changed while hashing: {os.fsdecode(relative)}'
                )
        finally:
            os.close(child_fd)
        return
    if not stat.S_ISREG(before.st_mode):
        raise MarketplaceIdentityError(
            f'marketplace tree contains a non-regular entry: {os.fsdecode(relative)}'
        )
    child_fd = os.open(name, _OPEN_FILE_FLAGS, dir_fd=parent_fd)
    try:
        opened = os.fstat(child_fd)
        if _metadata(opened) != _metadata(before):
            raise MarketplaceIdentityError(
                f'marketplace file changed while opening: {os.fsdecode(relative)}'
            )
        _validate_metadata(opened, relative, owner_uid)
        digest.update(b'F')
        _field(digest, relative)
        _field(digest, str(stat.S_IMODE(opened.st_mode)).encode())
        digest.update(opened.st_size.to_bytes(8, 'big'))
        while chunk := os.read(child_fd, 1024 * 1024):
            digest.update(chunk)
        if _metadata(os.fstat(child_fd)) != _metadata(opened):
            raise MarketplaceIdentityError(
                f'marketplace file changed while hashing: {os.fsdecode(relative)}'
            )
    finally:
        os.close(child_fd)


def _open_directory(path: Path) -> int:
    raw = os.fspath(path)
    if not path.is_absolute() or os.path.normpath(raw) != raw:
        raise MarketplaceIdentityError(
            f'marketplace source must be an absolute normalized path: {path}'
        )
    fd = os.open(path.anchor, _OPEN_DIRECTORY_FLAGS)
    try:
        for component in path.parts[1:]:
            child_fd = os.open(component, _OPEN_DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _snapshot(path: Path, owner_uid: int) -> tuple[tuple[int, ...], str]:
    root_fd = _open_directory(path)
    try:
        opened = os.fstat(root_fd)
        _validate_metadata(opened, b'', owner_uid)
        digest = hashlib.sha256()
        digest.update(b'codex-marketplace-tree-v1\0')
        digest.update(b'D')
        _field(digest, b'')
        _field(digest, str(stat.S_IMODE(opened.st_mode)).encode())
        names = _names(root_fd)
        for name in names:
            _digest_entry(root_fd, name, (name,), digest, owner_uid)
        if _names(root_fd) != names or _metadata(os.fstat(root_fd)) != _metadata(opened):
            raise MarketplaceIdentityError('marketplace root changed while hashing')
        return (_metadata(opened), 'sha256:' + digest.hexdigest())
    finally:
        os.close(root_fd)


def _stable_identity(path: Path, owner_uid: int) -> MarketplaceTreeIdentity:
    first_identity, first_revision = _snapshot(path, owner_uid)
    second_identity, second_revision = _snapshot(path, owner_uid)
    if first_identity != second_identity or first_revision != second_revision:
        raise MarketplaceIdentityError('marketplace source changed during identity verification')
    return MarketplaceTreeIdentity(
        revision=first_revision,
        device=first_identity[0],
        inode=first_identity[1],
    )


def marketplace_tree_revision(path: Path, *, owner_uid: int | None = None) -> str:
    """Return a content revision after two matching symlink-free tree reads."""
    expected_owner = os.getuid() if owner_uid is None else owner_uid
    return _stable_identity(path, expected_owner).revision


def verify_marketplace_revision(path: Path, expected_revision: object) -> MarketplaceTreeIdentity:
    """Require a canonical expected revision to match the current safe tree."""
    if not isinstance(expected_revision, str) or not REVISION_PATTERN.fullmatch(expected_revision):
        raise MarketplaceIdentityError(
            'local marketplace last_revision must be sha256 followed by 64 lowercase hex characters'
        )
    identity = _stable_identity(path, os.getuid())
    if not hmac.compare_digest(identity.revision, expected_revision):
        raise MarketplaceIdentityError('local marketplace content does not match last_revision')
    return identity
