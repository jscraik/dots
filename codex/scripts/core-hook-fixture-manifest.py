"""Validate the complete manifest before exposing its unchanged core test view."""

import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from migration_scope import require_policy_path, require_policy_scope

require_policy_scope()
publisher = importlib.import_module("project-codex-hooks")


def capture_artifact(artifact: Path, target: Path) -> None:
    """Validate the source and bound the capture before writing any bytes."""
    before = artifact.lstat()
    digest = artifact.parent.name.removeprefix("braid-")
    publisher.validate_braid_copy(artifact, digest)
    fd = os.open(artifact, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        def identity(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                    info.st_uid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or opened.st_uid != os.getuid() or opened.st_mode & 0o222
                or not opened.st_mode & stat.S_IXUSR
                or opened.st_size > publisher.MAX_BRAID_BYTES):
            raise ValueError("Managed Braid must be an owned, sealed, unshared executable")
        if identity(before) != identity(opened):
            raise ValueError("Managed Braid changed before capture")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(publisher.MAX_BRAID_BYTES + 1)
        if (len(raw) > publisher.MAX_BRAID_BYTES
                or identity(opened) != identity(os.fstat(fd))):
            raise ValueError("Managed Braid changed during capture")
        target.parent.mkdir()
        target.write_bytes(raw)
        target.chmod(stat.S_IMODE(opened.st_mode))
    finally:
        os.close(fd)


def main() -> None:
    source = require_policy_path(Path(sys.argv[1]))
    # The publisher's CLI verifies every core and Braid definition first. The view
    # below is solely for pre-existing core assertions; full native tests retain all.
    snapshot = source.read_bytes()
    original = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).with_name("project-codex-hooks.py")),
         "--source", str(source), "--without-braid"],
        capture_output=True, check=False,
    )
    if original.returncode:
        raise SystemExit("Complete hook manifest validation failed")
    with tempfile.TemporaryDirectory(
        dir=require_policy_path(Path(os.environ["TMPDIR"]))
    ) as directory:
        captured = Path(directory) / "hooks.json"
        captured.write_bytes(snapshot)
        for artifact in source.parent.glob("braid-*/braid"):
            target = captured.parent / artifact.relative_to(source.parent)
            capture_artifact(artifact, target)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("project-codex-hooks.py")),
                "--source",
                str(captured),
                "--without-braid",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise SystemExit("Complete hook manifest validation failed")
    # Consume the publisher's validated view instead of implementing a second,
    # substring-based Braid filter in the test adapter.
    print(json.dumps(json.loads(result.stdout)))


if __name__ == "__main__":
    main()
