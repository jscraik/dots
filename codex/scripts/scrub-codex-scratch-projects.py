"""Remove explicitly selected retired project entries; never infer retirement from location."""

from __future__ import annotations

from migration_scope import require_policy_path, require_policy_scope

require_policy_scope()

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR.parent / "config.toml"
PROJECT_TABLE_RE = re.compile(r'^\[projects\."(?P<path>.*)"\]\s*$')
TABLE_RE = re.compile(r"^\[")


@dataclass(frozen=True)
class ProjectBlock:
    path: str
    start: int
    end: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "start_line": self.start + 1, "end_line": self.end}


def parse_project_blocks(lines: list[str]) -> list[ProjectBlock]:
    blocks: list[ProjectBlock] = []
    index = 0
    while index < len(lines):
        match = PROJECT_TABLE_RE.match(lines[index])
        if not match:
            index += 1
            continue

        end = index + 1
        while end < len(lines) and not TABLE_RE.match(lines[end]):
            end += 1
        blocks.append(ProjectBlock(path=match.group("path"), start=index, end=end))
        index = end
    return blocks


def scratch_blocks(lines: list[str], prefixes: tuple[str, ...]) -> list[ProjectBlock]:
    return [block for block in parse_project_blocks(lines) if block.path.startswith(prefixes)]


def remove_blocks(lines: list[str], blocks: list[ProjectBlock]) -> list[str]:
    if not blocks:
        return lines

    ranges = {(block.start, block.end) for block in blocks}
    cleaned: list[str] = []
    index = 0
    while index < len(lines):
        removed = False
        for start, end in ranges:
            if index == start:
                index = end
                removed = True
                break
        if removed:
            while cleaned and cleaned[-1] == "\n" and index < len(lines) and lines[index] == "\n":
                index += 1
            continue
        cleaned.append(lines[index])
        index += 1
    return cleaned


def load_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def write_lines(path: Path, lines: list[str]) -> None:
    target_path = path.resolve(strict=True) if path.is_symlink() else path
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target_path.parent, delete=False) as handle:
        tmp_path = Path(handle.name)
        handle.writelines(lines)
    tmp_path.replace(target_path)


def scrub_config(path: Path, *, repair: bool, prefixes: tuple[str, ...]) -> dict[str, Any]:
    lines = load_lines(path)
    offenders = scratch_blocks(lines, prefixes)
    result: dict[str, Any] = {
        "schema_version": "codex-scratch-project-scrub/v1",
        "config_path": str(path),
        "prefixes": list(prefixes),
        "removed": [block.as_dict() for block in offenders],
        "removed_count": len(offenders),
        "mode": "repair" if repair else "check",
    }

    if offenders and repair:
        write_lines(path, remove_blocks(lines, offenders))
        result["status"] = "repaired"
    elif offenders:
        result["status"] = "fail"
    else:
        result["status"] = "pass"

    return result


def run_self_test() -> dict[str, Any]:
    sample = [
        'model = "gpt-5"\n',
        "\n",
        f'[projects."{Path.home()}/dev/dots"]\n',
        'trust_level = "trusted"\n',
        "\n",
        f'[projects."{Path.home()}/Documents/Codex/2026-06-24/example"]\n',
        'trust_level = "trusted"\n',
        "\n",
        "[[skills.config]]\n",
        'name = "kept"\n',
        "\n",
        "[mcp_servers.example]\n",
        'command = "/bin/true"\n',
    ]
    offenders = scratch_blocks(sample, (str(Path.home() / 'Documents/Codex') + '/',))
    cleaned = remove_blocks(sample, offenders)
    expected = [
        'model = "gpt-5"\n',
        "\n",
        f'[projects."{Path.home()}/dev/dots"]\n',
        'trust_level = "trusted"\n',
        "\n",
        "[[skills.config]]\n",
        'name = "kept"\n',
        "\n",
        "[mcp_servers.example]\n",
        'command = "/bin/true"\n',
    ]
    status = "pass" if len(offenders) == 1 and cleaned == expected else "fail"
    return {
        "schema_version": "codex-scratch-project-scrub-self-test/v1",
        "status": status,
        "removed_count": len(offenders),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--prefix", action="append", dest="prefixes")
    parser.add_argument("--check", action="store_true", help="Fail if scratch project tables exist")
    parser.add_argument("--repair", action="store_true", help="Remove scratch project tables")
    parser.add_argument("--self-test", action="store_true", help="Run an in-memory parser/removal test")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser.parse_args()


def emit(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    status = result.get("status", "unknown")
    removed_count = result.get("removed_count", 0)
    print(f"codex scratch project scrub: {status} ({removed_count} scratch project table(s))")
    for item in result.get("removed", []):
        print(f"  - {item['path']}")


def main() -> int:
    args = parse_args()
    require_policy_path(args.config)
    if args.self_test:
        result = run_self_test()
        emit(result, as_json=args.json)
        return 0 if result["status"] == "pass" else 1

    if args.check and args.repair:
        raise SystemExit("choose only one of --check or --repair")

    if not args.prefixes or any(not prefix.strip() for prefix in args.prefixes):
        raise SystemExit('Project cleanup requires an explicitly selected --prefix; workspace location does not imply retirement')
    prefixes = tuple(args.prefixes)
    result = scrub_config(args.config, repair=args.repair, prefixes=prefixes)
    emit(result, as_json=args.json)
    return 0 if result["status"] in {"pass", "repaired"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
