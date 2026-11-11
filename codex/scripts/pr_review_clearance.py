"""Parse supporting dispositions; this module never grants review clearance.

The input extends PR #274's pending export by completing each disposition.
Callers must still verify live source fingerprints, evidence blobs, independent
review, unresolved threads and checks before using the record in a receipt.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys at every object depth."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate disposition JSON field")
        result[key] = value
    return result


def _absolute_http_url(value: Any) -> bool:
    """Require credential-free HTTP(S) references with ASCII DNS or IP hosts."""
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value) or not re.fullmatch(r"https?://[^/?#\s]+(?:[/?#][^\s]*)?", value):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if not host or not parsed.netloc.isascii() or parsed.username is not None or parsed.password is not None:
            return False
        if parsed.netloc.startswith("["):
            if not re.fullmatch(r"\[[0-9A-Fa-f:.]+\](?::[0-9]+)?", parsed.netloc):
                return False
            ipaddress.IPv6Address(host)
        else:
            if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc):
                return False
            host = host.removesuffix(".")
            if len(host) > 253 or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in host.split(".")):
                return False
            if re.fullmatch(r"[0-9.]+", host):
                ipaddress.IPv4Address(host)
        # Normalize decimal ports before Python's bounded integer conversion.
        authority, separator, port = parsed.netloc.rpartition(":")
        if separator and port.isascii() and port.isdecimal():
            parsed = parsed._replace(netloc=authority + ":" + (port.lstrip("0") or "0"))
        return parsed.port is None or 0 <= parsed.port <= 65535
    except ValueError:
        return False


def _open_root(root: Path) -> int:
    """Open an absolute root from its anchor without following any symlink."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root.anchor, flags)
    try:
        for part in root.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def load_review_clearance(path: object, root: object, *, repository: str,
                          repository_host: str, pr_number: int,
                          head_sha: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load bounded, descriptor-bound evidence matching the caller's identity.

    The root must be absolute and every component must be a real directory,
    not a symlink. Relative roots and aliases are rejected rather than resolved.
    """
    descriptor: int | None = None
    try:
        if not isinstance(path, Path) or not isinstance(root, Path):
            raise TypeError("disposition path and root must be pathlib.Path values")
        if not isinstance(repository, str) or not re.fullmatch(r"(?!\.{1,2}/)[A-Za-z0-9_.-]+/(?!\.{1,2}$)[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid expected repository")
        if not isinstance(repository_host, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", repository_host):
            raise ValueError("invalid expected repository host")
        if type(pr_number) is not int or pr_number < 1 or not isinstance(head_sha, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head_sha):
            raise ValueError("invalid expected PR or head")
        if ".." in path.parts:
            raise ValueError("disposition path must not traverse parent directories")
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("disposition root must be an absolute non-traversing path")
        absolute = path if path.is_absolute() else root / path
        relative = absolute.relative_to(root)
        descriptor = _open_root(root)
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(file_descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("disposition evidence must be a regular file")
            raw = handle.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("disposition evidence exceeds 1 MiB")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
        expected = {"service": "pr-readiness", "schema_version": "pr-review-clearance/v1",
                    "repository": repository, "repository_host": repository_host,
                    "pr_number": pr_number, "head_sha": head_sha}
        if not isinstance(payload, dict) or set(payload) != set(expected) | {"sources"}:
            raise ValueError("disposition evidence must contain exactly the required fields")
        if any(type(payload[key]) is not type(value) or payload[key] != value for key, value in expected.items()):
            raise ValueError("disposition evidence identity does not match")
        if not isinstance(payload["sources"], list) or not payload["sources"]:
            raise ValueError("disposition source inventory is required")
        urls: set[str] = set()
        for source in payload["sources"]:
            if not isinstance(source, dict) or set(source) != {"url", "sha256", "disposition", "reason", "evidence_urls"}:
                raise ValueError("invalid disposition source fields")
            if not _absolute_http_url(source["url"]) or source["url"] in urls:
                raise ValueError("duplicate or invalid disposition source URL")
            urls.add(source["url"])
            if not isinstance(source["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
                raise ValueError("invalid disposition source digest")
            if source["disposition"] not in ("addressed", "not_actionable"):
                raise ValueError("every source needs a completed disposition")
            if not isinstance(source["reason"], str) or not source["reason"].strip():
                raise ValueError("source disposition requires a reason")
            evidence = source["evidence_urls"]
            if not isinstance(evidence, list) or not evidence or not all(_absolute_http_url(url) for url in evidence):
                raise ValueError("source disposition requires absolute evidence URLs")
        return {**payload, "path": str(absolute), "sha256": hashlib.sha256(raw).hexdigest()}, None
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return None, f"disposition evidence invalid: {exc}"
    finally:
        if descriptor is not None:
            os.close(descriptor)
