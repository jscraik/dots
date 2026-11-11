"""Validate the complete manifest before exposing its unchanged core test view."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from migration_scope import require_disposable_scope, require_fixture_path

require_disposable_scope()
source = require_fixture_path(Path(sys.argv[1]))
# The publisher's CLI verifies every core and Braid definition first. The view
# below is solely for pre-existing core assertions; full native tests retain all.
snapshot = source.read_bytes()
with tempfile.TemporaryDirectory(
    dir=require_fixture_path(Path(os.environ["TMPDIR"]))
) as directory:
    captured = Path(directory) / "hooks.json"
    captured.write_bytes(snapshot)
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
