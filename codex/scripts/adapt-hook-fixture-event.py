"""Bind original generic test payload locations to an owned disposable fixture."""

import json
import sys
from pathlib import Path

from migration_scope import require_disposable_scope

home = require_disposable_scope()
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    sys.stdout.write(raw)
    raise SystemExit(0)
if isinstance(data, dict):
    if data.get("cwd") == "/tmp":
        data["cwd"] = str(home)
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        source = str(Path(__file__).resolve().parents[1])
        tool_input["command"] = tool_input["command"].replace(
            "${HOME}/dev/dots/codex", source
        )
print(json.dumps(data), end="")
