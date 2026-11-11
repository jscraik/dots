"""Configs adapter for the shared git-metadata-preflight/v1 contract.

The revision-bound shared implementation is stored beside this adapter as
``git_metadata_core.py``. Missing local code remains blocking. Environment or
inspected-repository paths cannot choose a different implementation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _fixture_scope():
    import importlib.util
    from pathlib import Path

    directory = Path(__file__).resolve().parent
    if directory.name == "hook-governance":
        directory = directory.parent
    spec = importlib.util.spec_from_file_location(
        "dots_helper_scope", directory / "helper_fixture_scope.py"
    )
    scope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scope)
    return scope


def _fixture_args(arguments):
    return _fixture_scope().admit_file(__file__, arguments)


def _fixture_resource(value):
    return _fixture_scope().resource(value)


def _fixture_text(text):
    from pathlib import Path

    directory = Path(__file__).resolve().parent
    if directory.name == "hook-governance":
        directory = directory.parent
    policy = directory.parent
    return (
        text.replace("@POLICY_SOURCE@", str(policy))
        .replace("@REPO@", str(policy.parent))
        .replace("@HOME@", str(Path.home()))
    )


def _fixture_open(*args, **kwargs):
    return _fixture_scope().fixture_open(*args, **kwargs)


CONTRACT = "git-metadata-preflight/v1"
SERVICE = "configs-git-metadata-preflight"
EXIT_BLOCKED = 78


def _same_path(left: object, right: object) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    try:
        return Path(left).expanduser().resolve(strict=False) == Path(
            right
        ).expanduser().resolve(strict=False)
    except OSError:
        return left == right


def _enforce_lock_policy(
    payload: dict[str, object], allow_current_index_lock: bool
) -> int:
    locks = payload.get("locks")
    if not isinstance(locks, list):
        return 0
    current_path = payload.get("index_lock_path")
    disallowed: list[dict[str, object]] = []
    for lock in locks:
        if not isinstance(lock, dict):
            continue
        path = lock.get("path")
        if allow_current_index_lock and _same_path(path, current_path):
            continue
        disallowed.append(lock)
    if not disallowed:
        return 0
    reason_codes = payload.setdefault("reason_codes", [])
    if not isinstance(reason_codes, list):
        reason_codes = []
        payload["reason_codes"] = reason_codes
    for lock in disallowed:
        classification = lock.get("classification", "unrelated_metadata_lock")
        if classification not in reason_codes:
            reason_codes.append(classification)
    payload["status"] = "blocked"
    payload["next_action"] = (
        "wait for every unrelated Git metadata lock owner; do not delete locks"
    )
    return EXIT_BLOCKED


def _current_index_lock_is_the_only_blocker(
    payload: dict[str, object], allow_current_index_lock: bool
) -> bool:
    """Return true only when the allowed current lock explains every blocker."""
    if not allow_current_index_lock:
        return False
    locks = payload.get("locks")
    current_path = payload.get("index_lock_path")
    reasons = payload.get("reason_codes")
    if (
        not isinstance(locks, list)
        or not locks
        or (not isinstance(current_path, str))
        or (not isinstance(reasons, list))
    ):
        return False
    allowed_lock_reasons = {
        "active_index_lock",
        "recent_index_lock_unknown",
        "stale_index_lock_candidate",
        "index_lock",
        "current_worktree_locked",
    }
    for lock in locks:
        if not isinstance(lock, dict) or not _same_path(lock.get("path"), current_path):
            return False
        classification = lock.get("classification")
        if classification is not None and classification not in allowed_lock_reasons:
            return False
    return all(
        isinstance(reason, str) and reason in allowed_lock_reasons for reason in reasons
    )


def shared_path() -> Path:
    """Resolve trusted implementation independently of the inspected checkout."""
    import pwd

    home = pwd.getpwuid(os.getuid()).pw_dir
    if not home or not Path(home).is_absolute():
        raise ValueError("OS account home must be absolute")
    return Path(__file__).resolve().with_name("git_metadata_core.py")


def blocked(reason: str, **details: object) -> int:
    print(
        json.dumps(
            {
                "schema_version": 1,
                "service": SERVICE,
                "contract": CONTRACT,
                "status": "blocked",
                "reason_codes": [reason],
                **details,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return EXIT_BLOCKED


def main() -> int:
    args = sys.argv[1:]
    try:
        target = shared_path()
    except (ImportError, AttributeError, KeyError, ValueError, OSError):
        return blocked(
            "unavailable_account_home", next_action="restore the OS account home lookup"
        )
    if not target.is_file():
        return blocked(
            "missing_shared_adapter",
            adapter_path=str(target),
            next_action="restore the revision-bound local git_metadata_core.py sibling",
        )
    if "--json" not in args:
        return subprocess.run(
            [sys.executable, str(target), *args], check=False
        ).returncode
    proc = subprocess.run(
        [sys.executable, str(target), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return blocked(
            "invalid_shared_adapter_output",
            next_action="repair or reinstall the shared adapter",
        )
    if not isinstance(payload, dict):
        return blocked("invalid_shared_adapter_output")
    payload["service"] = SERVICE
    exit_code = _enforce_lock_policy(payload, "--allow-current-index-lock" in args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if exit_code:
        return exit_code
    if proc.returncode == EXIT_BLOCKED and _current_index_lock_is_the_only_blocker(
        payload, "--allow-current-index-lock" in args
    ):
        return 0
    return proc.returncode


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
