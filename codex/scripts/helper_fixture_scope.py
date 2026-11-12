"""Confine migrated helper entrypoints and filesystem resources to test fixtures."""

import importlib.util
import json
import os
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "helper_migration_scope", Path(__file__).with_name("migration_scope.py")
)
SCOPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCOPE)

PATH_ARGUMENTS = {
    "root",
    "repo_root",
    "cwd",
    "path",
    "paths",
    "file",
    "files",
    "manifest",
    "schema",
    "inventory",
    "ownership",
    "policy",
    "runtime_policy",
    "rules",
    "classification",
    "metrics",
    "out",
    "output",
    "input",
    "fixture",
    "changed_files",
    "scope_file",
    "body_file",
    "clearance_file",
    "report",
    "reports",
    "report_file",
    "evidence",
    "workspace_root",
    "plan_file",
    "source",
    "sources",
    "config",
    "target",
}


def admit_file(file: str, arguments=None):
    SCOPE.require_policy_scope()
    SCOPE.require_policy_path(Path(file).resolve())
    if not os.environ.get("TMPDIR"):
        raise RuntimeError("Helper validation requires an explicit fixture TMPDIR")
    SCOPE.require_policy_path(Path(os.environ["TMPDIR"]))
    SCOPE.require_policy_environment()
    if arguments is not None:
        for name, value in vars(arguments).items():
            if value is None or isinstance(value, bool):
                continue
            for item in value if isinstance(value, (list, tuple)) else (value,):
                if (isinstance(item, Path) or name in PATH_ARGUMENTS) and item != "-":
                    # Keep the parser's original spelling for its own traversal
                    # checks; admission only bounds the resolved resource here.
                    guard = SCOPE.require_policy_output if name in {
                        'out', 'output', 'out_dir', 'output_dir'} else SCOPE.require_policy_path
                    guard(Path(item).expanduser().resolve())
    return arguments


def resource(value):
    """Guard Path I/O without changing string methods with the same names."""
    if isinstance(value, Path):
        SCOPE.require_policy_path(value)
    return value


def fixture_open(file, *args, **kwargs):
    mode = args[0] if args else kwargs.get('mode', 'r')
    guard = SCOPE.require_policy_output if any(flag in mode for flag in 'wax+') else SCOPE.require_policy_path
    guard(Path(file).expanduser())
    return open(file, *args, **kwargs)


def output(value):
    """Admit an explicit mutating Path operation without changing fixture scope."""
    if isinstance(value, Path):
        SCOPE.require_policy_output(value)
    return value


def require_helper_bundle(root):
    """Fail before the aggregate can skip a missing migrated validator."""
    admit_file(__file__)
    SCOPE.require_policy_path(Path(root))
    # The accepted aggregate can inspect another target repository. Check the
    # canonical helper bundle independently; do not select helpers from that
    # target or forbid the original target-owned duplication regression.
    policy_root = Path(__file__).resolve().parents[1]
    manifest_path = resource(policy_root / "templates/helper-provenance.json")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("files"), list
    ):
        raise ValueError("Migrated helper inventory is invalid")
    paths = [row["path"] for row in manifest["files"]]
    if not paths or len(paths) != len(set(paths)):
        raise ValueError("Migrated helper inventory must be nonempty and unique")
    for name in paths:
        if not isinstance(name, str) or not name.startswith("codex/"):
            # Original Configs consumer recipes are inert regression resources.
            continue
        candidate = SCOPE.require_policy_path(policy_root.parent / name)
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("Missing migrated helper dependency: " + name)


if __name__ == "__main__":
    import sys

    try:
        if len(sys.argv) != 3 or sys.argv[1] != "--verify-bundle":
            raise ValueError(
                "Usage: helper_fixture_scope.py --verify-bundle POLICY_ROOT"
            )
        require_helper_bundle(sys.argv[2])
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as error:
        print("helper dependency admission failed: " + str(error), file=sys.stderr)
        raise SystemExit(2) from error
