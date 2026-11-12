#!/usr/bin/env python3
"""Remove Computer Use client launch drift from Codex config."""

from __future__ import annotations

from migration_scope import require_policy_scope, require_policy_path
require_policy_scope()

import argparse
import json
from pathlib import Path

try:
    import tomlkit
except ImportError:
    tomlkit = None  # type: ignore


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR.parent / "config.toml"
FORBIDDEN_NOTIFY_TOKEN = "SkyComputerUseClient"


def scrub_forbidden_notify(text: str) -> tuple[str, int]:
    """Remove top-level notify assignments that launch SkyComputerUseClient."""
    if tomlkit is None:
        return _scrub_forbidden_notify_fallback(text)

    try:
        doc = tomlkit.parse(text)
    except Exception:
        return _scrub_forbidden_notify_fallback(text)

    removed = 0
    if "notify" in doc and FORBIDDEN_NOTIFY_TOKEN in str(doc["notify"]):
        del doc["notify"]
        removed = 1

    return tomlkit.dumps(doc), removed


def _scrub_forbidden_notify_fallback(text: str) -> tuple[str, int]:
    """Fallback to line-based scrubbing when tomlkit is unavailable."""
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    removed = 0
    index = 0
    in_table = False

    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        if stripped.startswith("["):
            in_table = True

        if not in_table and stripped.startswith("notify"):
            block = [line]
            balance = line.count("[") - line.count("]")
            index += 1
            while balance > 0 and index < len(lines):
                block.append(lines[index])
                balance += lines[index].count("[") - lines[index].count("]")
                index += 1

            block_text = "".join(block)
            if FORBIDDEN_NOTIFY_TOKEN in block_text:
                removed += 1
                while output and output[-1].strip() == "":
                    output.pop()
                if output and index < len(lines) and lines[index].strip() != "":
                    output.append("\n")
                continue

            output.extend(block)
            continue

        output.append(line)
        index += 1

    new_text = "".join(output)
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect or repair forbidden Computer Use client notifier drift."
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=CONFIG_PATH,
        help="Path to the Codex config.toml file.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Rewrite the config when forbidden notify drift is present.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_policy_path(args.config_path)
    config_path = args.config_path.expanduser()
    try:
        original = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        payload = {
            "schema_version": "computer-use-config-scrub/v1",
            "service": "computer-use-config-scrub",
            "status": "blocked",
            "reason": "config_unreadable",
            "path": str(config_path),
            "error": str(exc),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"FAIL  config unreadable: {config_path} ({exc})")
        return 1

    scrubbed, removed = scrub_forbidden_notify(original)
    if removed and args.repair:
        repair_path = config_path.resolve() if config_path.is_symlink() else config_path
        tmp_path = repair_path.with_suffix(f"{repair_path.suffix}.tmp")
        try:
            tmp_path.write_text(scrubbed, encoding="utf-8")
            tmp_path.replace(repair_path)
        except OSError as exc:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            payload = {
                "schema_version": "computer-use-config-scrub/v1",
                "service": "computer-use-config-scrub",
                "status": "blocked",
                "reason": "config_write_failed",
                "path": str(config_path),
                "removed_count": removed,
                "error": str(exc),
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(f"FAIL  could not repair config: {config_path} ({exc})")
            return 1

    if removed and not args.repair:
        status = "fail"
        reason = "forbidden_computer_use_client_notify"
        exit_code = 1
    elif removed:
        status = "repaired"
        reason = "removed_forbidden_computer_use_client_notify"
        exit_code = 0
    else:
        status = "pass"
        reason = "no_forbidden_computer_use_client_notify"
        exit_code = 0

    payload = {
        "schema_version": "computer-use-config-scrub/v1",
        "service": "computer-use-config-scrub",
        "status": status,
        "reason": reason,
        "path": str(config_path),
        "removed_count": removed,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        label = "OK" if exit_code == 0 else "FAIL"
        print(f"{label}  {reason}: {config_path} (removed_count={removed})")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
