"""Verify gate taxonomy coverage and commit-msg vectors across governed repos."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


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


REQUIRED_ENTRYPOINTS = ("hooks-pre-commit", "hooks-pre-push", "hooks-commit-msg")
VALID_COMMIT_MSG = (
    "feat: gate taxonomy verification\n\nCo-authored-by: Codex <noreply@openai.com>"
)
INVALID_COMMIT_MSG = "bad message"


class GateTaxonomyError(ValueError):
    """Raised when the gate taxonomy verification cannot run."""


def load_inventory(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(_fixture_resource(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateTaxonomyError(f"invalid inventory JSON '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise GateTaxonomyError("inventory payload must be a JSON object")
    if payload.get("schema_version") != 1:
        raise GateTaxonomyError("inventory schema_version must be 1")
    return payload


def validate_entrypoints(inventory: dict[str, object]) -> list[str]:
    errors: list[str] = []
    repositories = inventory.get("repositories", [])
    if not isinstance(repositories, list):
        return ["inventory.repositories must be a list"]
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        repo_name = repo.get("repo_name")
        if not isinstance(repo_name, str) or not repo_name:
            continue
        gate_entrypoints = repo.get("gate_entrypoints", {})
        if not isinstance(gate_entrypoints, dict):
            gate_entrypoints = {}
        for target in REQUIRED_ENTRYPOINTS:
            command = gate_entrypoints.get(target)
            if not isinstance(command, str) or not command.strip():
                errors.append(
                    f"repo '{repo_name}' missing required gate entrypoint '{target}'"
                )
    return errors


def run_commit_msg_vector(
    repo_name: str,
    repo_path: Path,
    message: str,
    should_pass: bool,
    make_bin: str = "make",
) -> str | None:
    env = os.environ.copy()
    env["HOOK_COMMIT_MSG"] = message
    proc = subprocess.run(
        [make_bin, "-C", str(repo_path), "hooks-commit-msg"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if should_pass and proc.returncode != 0:
        return f"repo '{repo_name}' valid commit-msg vector failed (exit={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
    if not should_pass and proc.returncode == 0:
        return f"repo '{repo_name}' invalid commit-msg vector unexpectedly passed"
    return None


def verify_commit_msg_vectors(
    inventory: dict[str, object], make_bin: str = "make"
) -> list[str]:
    errors: list[str] = []
    repositories = inventory.get("repositories", [])
    if not isinstance(repositories, list):
        return ["inventory.repositories must be a list"]
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        repo_name = repo.get("repo_name")
        repo_path_raw = repo.get("repo_path")
        if not isinstance(repo_name, str) or not repo_name:
            continue
        if not isinstance(repo_path_raw, str) or not repo_path_raw:
            errors.append(f"repo '{repo_name}' missing repo_path in inventory")
            continue
        repo_path = Path(repo_path_raw)
        if not repo_path.is_dir():
            errors.append(f"repo '{repo_name}' path missing on disk: {repo_path}")
            continue
        valid_error = run_commit_msg_vector(
            repo_name=repo_name,
            repo_path=repo_path,
            message=VALID_COMMIT_MSG,
            should_pass=True,
            make_bin=make_bin,
        )
        if valid_error is not None:
            errors.append(valid_error)
        invalid_error = run_commit_msg_vector(
            repo_name=repo_name,
            repo_path=repo_path,
            message=INVALID_COMMIT_MSG,
            should_pass=False,
            make_bin=make_bin,
        )
        if invalid_error is not None:
            errors.append(invalid_error)
    return errors


def verify_gate_taxonomy(
    inventory_path: Path, run_commit_msg_vectors_flag: bool, make_bin: str
) -> list[str]:
    inventory = load_inventory(inventory_path)
    errors = validate_entrypoints(inventory)
    if run_commit_msg_vectors_flag:
        errors.extend(verify_commit_msg_vectors(inventory, make_bin=make_bin))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--make-bin", default="make")
    parser.add_argument(
        "--commit-msg-vectors",
        action="store_true",
        default=False,
        help="enable dynamic hooks-commit-msg valid/invalid vector execution",
    )
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    errors = verify_gate_taxonomy(
        inventory_path=args.inventory.resolve(),
        run_commit_msg_vectors_flag=args.commit_msg_vectors,
        make_bin=args.make_bin,
    )
    if errors:
        for error in errors:
            print(f"[verify_gate_taxonomy] {error}")
        return 1
    print("[verify_gate_taxonomy] OK")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
