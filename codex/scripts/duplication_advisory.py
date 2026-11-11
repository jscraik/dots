"""Report new Python structural clones; enforce only declared ownership."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


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


EXCLUDED = {
    "tests",
    "test",
    "fixtures",
    "generated",
    "vendor",
    "node_modules",
    "__pycache__",
}


class Boundary(BaseModel):
    """An explicit symbol ownership contract, not inferred similarity."""

    model_config = ConfigDict(extra="forbid", strict=True)
    owner: str
    symbol: str
    scope: str
    reason: str

    @field_validator("owner", "scope")
    @classmethod
    def relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or ("\\" in value):
            raise ValueError(
                "ownership paths must be repository-relative without traversal"
            )
        return str(path)

    @field_validator("symbol")
    @classmethod
    def identifier(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("owner symbol must be a Python identifier")
        return value

    @field_validator("reason")
    @classmethod
    def explanation(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("boundary requires a concrete reason")
        return value


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    boundaries: list[Boundary]


class Location(BaseModel):
    path: str
    symbol: str
    line: int


class Advisory(BaseModel):
    fingerprint: str
    locations: list[Location]
    action: str = "Review shared maintenance responsibility; similarity alone does not require refactoring."


class Violation(BaseModel):
    owner: str
    location: Location
    reason: str


class Report(BaseModel):
    schema_version: Literal[1] = 1
    service: Literal["duplication-advisory"] = "duplication-advisory"
    status: Literal["pass", "fail", "unverified", "error"]
    base: str = ""
    language: Literal["python"] = "python"
    advisories: list[Advisory] = []
    violations: list[Violation] = []
    diagnostics: list[str] = []


def git(root: Path, *args: str) -> bytes:
    """Read Git state without shell interpolation or mutations."""
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=30,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_")
            },
            "GIT_NO_LAZY_FETCH": "1",
        },
    ).stdout


def included(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return (
        path.endswith(".py")
        and (not any(part in EXCLUDED or part.startswith(".") for part in parts))
        and (not PurePosixPath(path).name.startswith("test_"))
        and (not PurePosixPath(path).name.endswith("_test.py"))
    )


def snapshots(
    root: Path, base: str
) -> tuple[str, dict[str, str], dict[str, str], list[str], set[str]]:
    """Compare a verified commit with tracked and non-ignored working files."""
    sha = git(root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    records = os.fsdecode(git(root, "ls-tree", "-rz", sha)).split("\x00")
    old_paths = [
        record.split("\t", 1)[1]
        for record in records
        if record.startswith(("100644 ", "100755 "))
    ]
    paths = os.fsdecode(
        git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    ).split("\x00")
    sparse_paths = {
        record[2:]
        for record in os.fsdecode(git(root, "ls-files", "-t", "-z", "--cached")).split(
            "\x00"
        )
        if record.startswith("S ")
    }
    before: dict[str, str] = {}
    unavailable_baselines: set[str] = set()
    unsupported_paths = {
        path
        for path in [*old_paths, *paths]
        if included(path)
        and any(56448 <= ord(character) <= 56575 for character in path)
        and (
            path in sparse_paths
            or ((root / path).is_file() and (not (root / path).is_symlink()))
        )
    }
    diagnostics = [
        f"{path!a}: non-UTF-8 path; not inspected" for path in sorted(unsupported_paths)
    ]
    for path in old_paths:
        if not included(path) or path in unsupported_paths:
            continue
        target = root / path
        if path not in sparse_paths and (not target.is_file() or target.is_symlink()):
            continue
        try:
            if int(git(root, "cat-file", "-s", f"{sha}:{path}")) > 1048576:
                diagnostics.append(f"{path}: baseline exceeds 1 MiB inspection bound")
                unavailable_baselines.add(path)
                continue
            before[path] = git(root, "show", f"{sha}:{path}").decode("utf-8")
        except subprocess.CalledProcessError:
            diagnostics.append(f"{path}: baseline blob unavailable; not inspected")
            unavailable_baselines.add(path)
        except UnicodeDecodeError:
            diagnostics.append(f"{path}: baseline is not valid UTF-8; not inspected")
            unavailable_baselines.add(path)
    after: dict[str, str] = {}
    for path in set(paths):
        if path in unsupported_paths:
            continue
        target = root / path
        if included(path) and path in sparse_paths and (not target.exists()):
            diagnostics.append(f"{path}: sparse-checkout omission; not inspected")
            continue
        if not included(path) or not target.is_file() or target.is_symlink():
            continue
        if not target.resolve().is_relative_to(root):
            diagnostics.append(f"{path}: resolved outside repository; not inspected")
            continue
        if _fixture_resource(target).stat().st_size > 1048576:
            diagnostics.append(f"{path}: exceeds 1 MiB inspection bound")
            continue
        try:
            after[path] = _fixture_resource(target).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            diagnostics.append(
                f"{path}: working file is not valid UTF-8; not inspected"
            )
    return (sha, before, after, diagnostics, unavailable_baselines)


class LocalNames(ast.NodeTransformer):
    """Rename only bound locals; retain globals, attributes and constants."""

    def __init__(self, names: dict[str, str], parameters: dict[str, str]) -> None:
        self.names = names
        self.parameters = parameters

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if (
            isinstance(node.func, ast.Name)
            and self.names.get(node.func.id) == "$recursive:self"
        ):
            for keyword in node.keywords:
                if keyword.arg is not None:
                    keyword.arg = self.parameters.get(keyword.arg, keyword.arg)
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        node.id = self.names.get(node.id, node.id)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = self.names.get(node.arg, node.arg)
        return node

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.AST:
        if node.name is not None:
            node.name = self.names.get(node.name, node.name)
        return self.generic_visit(node)


def fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Conservative whole-function structure, not semantic equivalence."""
    tree = copy.deepcopy(node)
    if any(
        isinstance(
            child,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Global,
                ast.Nonlocal,
                ast.Lambda,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        )
        for statement in tree.body
        for child in ast.walk(statement)
    ):
        return None
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body.pop(0)
    if (
        sum(1 for child in ast.walk(tree) if isinstance(child, ast.stmt)) < 5
        or len(list(ast.walk(tree))) < 40
    ):
        return None
    names: dict[str, str] = {}
    arguments = [*tree.args.posonlyargs, *tree.args.args, *tree.args.kwonlyargs]
    if tree.args.vararg:
        arguments.append(tree.args.vararg)
    if tree.args.kwarg:
        arguments.append(tree.args.kwarg)
    for child in [
        *arguments,
        *(child for statement in tree.body for child in ast.walk(statement)),
    ]:
        name = (
            child.arg
            if isinstance(child, ast.arg)
            else child.id
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
            else child.name
            if isinstance(child, ast.ExceptHandler)
            else None
        )
        if name is not None and name not in names:
            names[name] = f"$local:{len(names)}"
    if tree.name not in names:
        names[tree.name] = "$recursive:self"
    tree.name = "function"
    normalizer = LocalNames(
        names,
        {
            argument.arg: names[argument.arg]
            for argument in [*tree.args.args, *tree.args.kwonlyargs]
        },
    )
    for argument in arguments:
        argument.arg = names[argument.arg]
    for statement in tree.body:
        normalizer.visit(statement)
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def module_functions(node: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Find global function bindings, including module control-flow blocks."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node]
    if isinstance(node, (ast.ClassDef, ast.Lambda)):
        return []
    return [
        function
        for child in ast.iter_child_nodes(node)
        for function in module_functions(child)
    ]


def inventory(
    files: dict[str, str],
) -> tuple[dict[str, list[Location]], dict[str, Counter[str]], list[str]]:
    groups: dict[str, list[Location]] = defaultdict(list)
    definitions: dict[str, Counter[str]] = {}
    diagnostics = []
    for path, text in sorted(files.items()):
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            diagnostics.append(
                f"{path}:{exc.lineno}: syntax unavailable; no duplication proof"
            )
            continue
        functions = module_functions(tree)
        definitions[path] = Counter(node.name for node in functions)
        for node in functions:
            if key := fingerprint(node):
                groups[key].append(
                    Location(path=path, symbol=node.name, line=node.lineno)
                )
    return (dict(groups), definitions, diagnostics)


def analyze(root: Path, base: str, policy: Policy) -> Report:
    sha, before, after, diagnostics, unavailable_baselines = snapshots(root, base)
    old_groups, old_defs, old_errors = inventory(before)
    groups, definitions, errors = inventory(after)
    diagnostics.extend(old_errors + errors)
    advisories = []
    for key, locations in groups.items():
        existing = Counter((item.path, item.symbol) for item in old_groups.get(key, []))
        current = Counter((item.path, item.symbol) for item in locations)
        if len(locations) > 1 and current - existing:
            advisories.append(Advisory(fingerprint=key, locations=locations))
    violations = []
    for boundary in policy.boundaries:
        if boundary.owner not in definitions and any(
            item.startswith(f"{boundary.owner}:") for item in diagnostics
        ):
            continue
        if not definitions.get(boundary.owner, Counter())[boundary.symbol]:
            raise ValueError(
                f"declared owner {boundary.owner}:{boundary.symbol} is unavailable"
            )
        for path, names in definitions.items():
            if (
                path != boundary.owner
                and PurePosixPath(path).is_relative_to(boundary.scope)
                and (path not in before or path in old_defs)
                and (path not in unavailable_baselines)
                and (
                    names[boundary.symbol]
                    > old_defs.get(path, Counter())[boundary.symbol]
                )
            ):
                tree = ast.parse(after[path])
                nodes = [
                    item
                    for item in module_functions(tree)
                    if item.name == boundary.symbol
                ]
                for node in nodes[old_defs.get(path, Counter())[boundary.symbol] :]:
                    violations.append(
                        Violation(
                            owner=boundary.owner,
                            location=Location(
                                path=path, symbol=node.name, line=node.lineno
                            ),
                            reason=boundary.reason,
                        )
                    )
    status = "unverified" if diagnostics else "fail" if violations else "pass"
    return Report(
        status=status,
        base=sha,
        advisories=advisories,
        violations=violations,
        diagnostics=diagnostics,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--base",
        help="baseline commit; otherwise CODEX_DUPLICATION_BASE, origin/main merge-base, or unverified HEAD",
    )
    parser.add_argument(
        "--require-target-baseline",
        action="store_true",
        help="return blocked inspection when the default target baseline is unavailable",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        help="explicit single-owner contract, relative to the repository",
    )
    args = _fixture_args(parser.parse_args())
    policy = Policy(schema_version=1, boundaries=[])
    baseline_unavailable = False
    try:
        root = Path(
            os.fsdecode(git(args.root, "rev-parse", "--show-toplevel")).strip()
        ).resolve()
        policy_path = args.policy or (
            Path("codex/duplication-policy.json")
            if (root / "codex/duplication-policy.json").is_file()
            else None
        )
        if policy_path:
            path = (root / policy_path).resolve()
            if not path.is_relative_to(root):
                raise ValueError("policy must stay inside repository")
            policy = Policy.model_validate_json(
                _fixture_resource(path).read_text(encoding="utf-8")
            )
        base = (
            args.base
            if args.base is not None
            else os.environ.get("CODEX_DUPLICATION_BASE")
        )
        if base is None:
            try:
                base = (
                    git(root, "merge-base", "HEAD", "refs/remotes/origin/main")
                    .decode()
                    .strip()
                )
            except subprocess.CalledProcessError:
                base = "HEAD"
                baseline_unavailable = True
        report = analyze(root, base, policy)
        if baseline_unavailable:
            report.diagnostics.append(
                "target baseline unavailable: origin/main merge-base missing; HEAD comparison covers uncommitted changes only, not the branch range"
            )
            report.status = "unverified"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report = Report(status="error", diagnostics=[str(exc)])
    print(report.model_dump_json(indent=2))
    return (
        2
        if report.status == "error"
        else 3
        if report.status == "unverified"
        and (
            policy.boundaries or (args.require_target_baseline and baseline_unavailable)
        )
        else 1
        if report.status == "fail"
        else 0
    )


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
