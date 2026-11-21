"""Publish the canonical hook manifest as a regular runtime file."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shlex
import stat
import tempfile
from pathlib import Path

from migration_scope import deployment_module, require_policy_path, require_policy_scope

require_policy_scope()

BRAID_STORE_PREFIX = "braid-"
MAX_BRAID_BYTES = 64 * 1024 * 1024


def guard_manifest() -> dict:
    """The existing guards must survive every hook publication unchanged."""
    def group(script: str, timeout: int = 10, matcher: str | None = None) -> dict:
        value = {"hooks": [{"type": "command", "command": f"/bin/bash -p ~/.codex/hooks/{script}", "timeout": timeout}]}
        if matcher is not None:
            value["matcher"] = matcher
        return value

    bash, edits, compact = "^Bash$", "^(apply_patch|Edit|Write)$", "^(manual|auto)$"
    prompt = group("user-prompt-submit.sh")
    prompt["hooks"].extend(group("lifeos-codex.sh")["hooks"])
    return {"hooks": {
        "PreToolUse": [group("pre-tool-use-dispatch.sh", 130, bash), group("pre-tool-use-guard.sh", 10, edits)],
        "PostToolUse": [group("post-tool-use-review.sh", 10, bash), group("post-tool-use-review.sh", 10, edits)],
        "PermissionRequest": [group("permission-request-guard.sh", 10, bash), group("permission-request-guard.sh", 10, edits)],
        "SessionStart": [group("session-start.sh", 10, "^(startup|resume|clear)$")],
        "PreCompact": [group("pre-compact-guard.sh", 5, compact)],
        "PostCompact": [group("post-compact-recorder.sh", 5, compact)],
        "SubagentStart": [group("subagent-start.sh")],
        "SubagentStop": [group("subagent-stop.sh")],
        "UserPromptSubmit": [prompt],
        "Stop": [group("stop-guard.sh")],
    }}


def unique_keys(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def command_launcher(command: str) -> str | None:
    """Return a literal launcher token without interpreting shell syntax."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    return tokens[0] if tokens else None


def braid_launcher(payload: dict) -> tuple[Path, str] | None:
    """Find the single digest-bearing runtime Braid path, if one is present."""
    store = require_policy_scope() / ".codex/hooks"
    launchers = set()
    for groups in payload["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                command = hook.get("command", "")
                launcher_token = command_launcher(command)
                if launcher_token is None:
                    continue
                tokens = shlex.split(command)
                if len(tokens) < 3 or tokens[1:3] != ["hook", "codex"]:
                    continue
                launcher = Path(launcher_token)
                try:
                    relative = launcher.relative_to(store)
                except ValueError:
                    continue
                if (len(relative.parts) == 2 and relative.name == "braid"
                        and relative.parts[0].startswith(BRAID_STORE_PREFIX)):
                    digest = relative.parts[0].removeprefix(BRAID_STORE_PREFIX)
                    if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
                        launchers.add((launcher, digest))
    if len(launchers) > 1:
        raise ValueError("Braid hook definitions must use one content address")
    return next(iter(launchers)) if launchers else None


def validate_braid_copy(source: Path, digest: str) -> None:
    """Bind the stored adapter name to stable, sealed executable bytes."""
    source = require_policy_path(source)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o222
                or not before.st_mode & stat.S_IXUSR or before.st_size > MAX_BRAID_BYTES):
            raise ValueError("Managed Braid must be an owned, sealed, unshared executable")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_BRAID_BYTES + 1)
        after = os.fstat(fd)
        if (len(raw) > MAX_BRAID_BYTES
                or (before.st_dev, before.st_ino, before.st_mode, before.st_nlink,
                    before.st_uid, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_mode, after.st_nlink,
                    after.st_uid, after.st_size, after.st_mtime_ns)):
            raise ValueError("Managed Braid changed while it was validated")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Managed Braid bytes do not match the hook command")
    finally:
        os.close(fd)


def without_braid(payload: dict, source: Path | None = None) -> dict:
    """Validate the approved Braid alpha.17 contract, retaining all other hooks."""
    binding = braid_launcher(payload)
    if binding is None:
        return copy.deepcopy(payload)
    command = shlex.quote(str(binding[0])) + " hook codex"
    capture = {"type": "command", "command": command + " --capture"}
    inject = {"type": "command", "command": command + " --inject", "additionalContextLimit": 2500}
    asynchronous = {**capture, "async": True}
    expected = {
        "Interrupt": {"hooks": [capture]},
        "SessionEnd": {"matcher": "other", "hooks": [capture]},
        "SessionStart": {"matcher": "startup|resume|clear|compact", "hooks": [inject, capture]},
        **{event: {"hooks": [asynchronous]} for event in (
            "PermissionRequest", "PostCompact", "PostToolUse", "PreCompact", "PreToolUse")},
        **{event: {"hooks": [inject, capture]} for event in ("SubagentStart", "UserPromptSubmit")},
        **{event: {"hooks": [capture]} for event in ("Stop", "SubagentStop")},
    }
    result = copy.deepcopy(payload)
    found = set()
    for event, groups in list(result["hooks"].items()):
        remaining = []
        for group in groups:
            if any(
                    command_launcher(hook.get("command", "")) == str(binding[0])
                    for hook in group["hooks"]):
                if event in found or json.dumps(group, sort_keys=True) != json.dumps(expected.get(event), sort_keys=True):
                    raise ValueError(f"unexpected Braid hook definition for {event}")
                found.add(event)
            else:
                remaining.append(group)
        if remaining:
            result["hooks"][event] = remaining
        else:
            del result["hooks"][event]
    if found and found != set(expected):
        raise ValueError("Braid hook event coverage is incomplete")
    if found and source is not None:
        relative = binding[0].relative_to(require_policy_scope() / ".codex/hooks")
        validate_braid_copy(source.parent / relative, binding[1])
    return result


def validated_bytes(source: Path) -> bytes:
    """Reject incomplete manifests before touching the current runtime file."""
    require_policy_path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Canonical hooks must be a regular source file')
    data = source.read_bytes()
    payload = json.loads(data, object_pairs_hook=unique_keys)
    if not isinstance(payload, dict) or not isinstance(payload.get("hooks"), dict):
        raise TypeError("canonical hooks must contain a hooks object")
    if not payload["hooks"]:
        raise ValueError("canonical hooks must not be empty")
    for groups in payload["hooks"].values():
        if not isinstance(groups, list) or not groups:
            raise ValueError("hook events must contain nonempty groups")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list) or not group["hooks"]:
                raise ValueError("hook groups must contain commands")
            for hook in group["hooks"]:
                if not isinstance(hook, dict) or hook.get("type") != "command" or not isinstance(hook.get("command"), str) or not hook["command"].strip():
                    raise ValueError("hook must be a nonempty command")
    if json.dumps(without_braid(payload, source), sort_keys=True) != json.dumps(guard_manifest(), sort_keys=True):
        raise ValueError("canonical manifest must preserve every existing guard definition")
    return data


def identity(path: Path) -> tuple:
    """Snapshot the named inode without following a redirected runtime path."""
    entry = path.lstat()
    if stat.S_ISLNK(entry.st_mode):
        content = os.readlink(path)
    elif stat.S_ISREG(entry.st_mode):
        content = path.read_bytes()
    else:
        raise ValueError(f"refusing non-file runtime target: {path}")
    return (entry.st_dev, entry.st_ino, entry.st_mode, content)


def publish(source: Path, target: Path, check: bool = False, backup_dir: Path | None = None) -> str:
    """Keep canonical bytes authoritative; preserve displaced files for recovery."""
    require_policy_path(source)
    require_policy_path(target)
    deployed = deployment_module()
    if deployed is not None and target != Path(deployed.context()['home']) / '.codex/hooks.json':
        raise ValueError('Deployed hook publication requires its declared runtime target')
    if target.exists() and not target.is_symlink() and target.samefile(source):
        raise ValueError('Runtime target must not share the canonical inode')
    data = validated_bytes(source)
    # macOS exposes these system-owned aliases to its temporary directories.
    # Normalize only the known aliases; user-controlled redirects still fail.
    for alias, physical in (("/var", "/private/var"), ("/tmp", "/private/tmp")):
        if target.is_relative_to(alias) and Path(alias).is_symlink() and Path(alias).resolve() == Path(physical):
            target = Path(physical) / target.relative_to(alias)
    if target.parent.resolve() != target.parent.absolute():
        raise ValueError("runtime parent must not contain symlinks")
    previous = identity(target) if target.exists() or target.is_symlink() else None
    if previous and not target.is_symlink() and previous[3] == data:
        return "unchanged"
    if check:
        raise ValueError("runtime hooks must be a regular file matching canonical bytes")
    if target.resolve() == source.resolve() and not target.is_symlink():
        raise ValueError("runtime target must be separate from canonical source")
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup_dir is not None:
        if deployed is None or backup_dir != Path(deployed.context()['state_dir']) / 'publisher-backups':
            raise ValueError('Hook backup directory must belong to this installation')
        require_policy_path(backup_dir)
    fd, name = tempfile.mkstemp(prefix=".hooks-backup-", dir=target.parent if backup_dir is None else backup_dir)
    staged = Path(name)
    exchanged = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if source.read_bytes() != data or (previous is not None and identity(target) != previous):
            raise ValueError("hook files changed during publication")
        if previous is None:
            os.link(staged, target, follow_symlinks=False)
            staged.unlink()
            return "created"
        module_path = Path(__file__).with_name("repair-runtime-config-drift.py")
        spec = importlib.util.spec_from_file_location("runtime_repair", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module._exchange_paths(staged, target)
        exchanged = True
        if identity(staged) != previous or source.read_bytes() != data or target.is_symlink() or target.read_bytes() != data:
            raise ValueError(f"concurrent hook change; displaced file preserved at {staged}")
        return f"published; previous file preserved at {staged}"
    finally:
        if not exchanged:
            staged.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--without-braid", action="store_true")
    args = parser.parse_args()
    try:
        if args.without_braid:
            print(json.dumps(without_braid(json.loads(validated_bytes(args.source)))))
            return
        if args.target is None:
            parser.error("--target is required for publication")
        result = publish(args.source, args.target, args.check, args.backup_dir)
    except (OSError, TypeError, ValueError) as error:
        parser.exit(1, f"project-codex-hooks: {error}\n")
    print(json.dumps({"schema_version": 1, "service": "project-codex-hooks", "status": "pass", "result": result}))


if __name__ == "__main__":
    main()
