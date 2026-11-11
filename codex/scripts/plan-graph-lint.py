"""
plan-graph-lint.py

Validate a markdown plan file that contains a YAML task graph contract:

tasks:
  - id: T1
    title: ...
    depends_on: []

The linter checks:
- a YAML block with `tasks:` exists
- each task has `id` and `depends_on`
- task IDs are unique
- dependencies reference existing IDs
- no self-dependency
- dependency graph is acyclic
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    preferred = Path.home() / ".venvs" / "pyyaml" / "bin" / "python"
    already_reexec = os.environ.get("PLAN_GRAPH_PYYAML_REEXEC") == "1"
    if preferred.exists() and (not already_reexec):
        env = dict(os.environ)
        env["PLAN_GRAPH_PYYAML_REEXEC"] = "1"
        os.execve(str(preferred), [str(preferred), __file__, *sys.argv[1:]], env)
    print(
        "ERROR: PyYAML is required (install in ~/.venvs/pyyaml or current env).",
        file=sys.stderr,
    )
    raise SystemExit(1)


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


def read_text(path: Path) -> str:
    try:
        return _fixture_resource(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _fixture_resource(path).read_text(encoding="utf-8", errors="replace")


def extract_task_graphs(markdown: str) -> list[dict[str, Any]]:
    graphs: list[dict[str, Any]] = []
    in_fence = False
    block_lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not in_fence:
            if stripped.startswith("```"):
                in_fence = True
                block_lines = []
            continue
        if stripped.startswith("```"):
            block = "\n".join(block_lines)
            if "tasks:" in block:
                try:
                    loaded = yaml.safe_load(block)
                except yaml.YAMLError:
                    loaded = None
                if isinstance(loaded, dict) and "tasks" in loaded:
                    graphs.append(loaded)
            in_fence = False
            block_lines = []
            continue
        block_lines.append(line)
    return graphs


def _task_id(task: dict[str, Any]) -> str:
    raw = task.get("id")
    return raw.strip() if isinstance(raw, str) else ""


def _depends(task: dict[str, Any]) -> list[str]:
    raw = task.get("depends_on")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def detect_cycle(ids: set[str], deps: dict[str, list[str]]) -> tuple[bool, list[str]]:
    visiting: set[str] = set()
    visited: set[str] = set()
    parent: dict[str, str] = {}

    def dfs(node: str) -> tuple[bool, list[str]]:
        visiting.add(node)
        for nxt in deps.get(node, []):
            if nxt not in ids:
                continue
            if nxt in visited:
                continue
            if nxt in visiting:
                cycle = [nxt]
                cur = node
                while cur != nxt and cur in parent:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.append(nxt)
                cycle.reverse()
                return (True, cycle)
            parent[nxt] = node
            hit, cycle = dfs(nxt)
            if hit:
                return (True, cycle)
        visiting.remove(node)
        visited.add(node)
        return (False, [])

    for nid in sorted(ids):
        if nid in visited:
            continue
        hit, cycle = dfs(nid)
        if hit:
            return (True, cycle)
    return (False, [])


def validate_graph(graph: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    tasks = graph.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return ["`tasks` must be a non-empty list."]
    ids: set[str] = set()
    duplicates: set[str] = set()
    deps_map: dict[str, list[str]] = {}
    for idx, raw in enumerate(tasks, start=1):
        if not isinstance(raw, dict):
            errs.append(f"tasks[{idx}] must be a mapping/object.")
            continue
        tid = _task_id(raw)
        if not tid:
            errs.append(f"tasks[{idx}] missing non-empty `id`.")
            continue
        if "depends_on" not in raw:
            errs.append(f"{tid}: missing required `depends_on`.")
        depends = _depends(raw)
        if "depends_on" in raw and (not isinstance(raw.get("depends_on"), list)):
            errs.append(f"{tid}: `depends_on` must be a list.")
        if tid in ids:
            duplicates.add(tid)
        ids.add(tid)
        deps_map[tid] = depends
        if tid in depends:
            errs.append(f"{tid}: self-dependency is not allowed.")
    if duplicates:
        errs.append(f"duplicate task id(s): {', '.join(sorted(duplicates))}.")
    for tid, depends in deps_map.items():
        unknown = sorted([d for d in depends if d not in ids])
        if unknown:
            errs.append(f"{tid}: unknown dependency id(s): {', '.join(unknown)}.")
    has_cycle, cycle = detect_cycle(ids, deps_map)
    if has_cycle:
        errs.append(f"dependency cycle detected: {' -> '.join(cycle)}.")
    return errs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint markdown task graph contract files."
    )
    parser.add_argument(
        "path", help="Path to plan markdown file (e.g. .agent/PLANS.md)"
    )
    args = _fixture_args(parser.parse_args(list(argv) if argv is not None else None))
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"[FAIL] file not found: {path}", file=sys.stderr)
        return 1
    text = read_text(path)
    graphs = extract_task_graphs(text)
    if not graphs:
        print(
            f"[FAIL] {path}: no YAML task graph block with `tasks:` found.",
            file=sys.stderr,
        )
        return 2
    failures: list[str] = []
    for i, graph in enumerate(graphs, start=1):
        errs = validate_graph(graph)
        if errs:
            failures.append(f"graph #{i}:")
            failures.extend([f"  - {e}" for e in errs])
    if failures:
        print(f"[FAIL] {path}: task graph lint failed", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        return 2
    print(f"[OK] {path}: task graph lint passed ({len(graphs)} graph block(s)).")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
