"""Validate the complete manifest before exposing its unchanged core test view."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from migration_scope import require_policy_path, require_policy_scope

require_policy_scope()
source = require_policy_path(Path(sys.argv[1]))
# The publisher's CLI verifies every core and Braid definition first. The view
# below is solely for pre-existing core assertions; full native tests retain all.
snapshot = source.read_bytes()
with tempfile.TemporaryDirectory(
    dir=require_policy_path(Path(os.environ["TMPDIR"]))
) as directory:
    captured = Path(directory) / "hooks.json"
    captured.write_bytes(snapshot)
    for artifact in source.parent.glob("braid-*/braid"):
        target = captured.parent / artifact.relative_to(source.parent)
        target.parent.mkdir()
        shutil.copy2(artifact, target)
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
