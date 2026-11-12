"""Run the repository-owned installation command with the current Python."""
import os
import sys
from pathlib import Path

command = Path(__file__).resolve().parents[1] / 'codex/scripts/install-codex.py'
os.execv(sys.executable, [sys.executable, '-B', str(command), *sys.argv[1:]])
