"""Report local branch truth and optional hosted PR state without blending lanes."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


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


PROBE_TIMEOUT_SECONDS = 15


def run(command: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            124,
            exc.stdout or "",
            f"command timed out after {PROBE_TIMEOUT_SECONDS}s",
        )
    return (completed.returncode, completed.stdout.strip(), completed.stderr.strip())


def git_value(args: list[str], cwd: Path) -> str | None:
    code, stdout, _stderr = run(["git", *args], cwd)
    if code != 0 or not stdout:
        return None
    return stdout


def git_dirty_count(cwd: Path) -> int | None:
    code, stdout, _stderr = run(["git", "status", "--porcelain=v1"], cwd)
    if code != 0:
        return None
    if not stdout:
        return 0
    return len(stdout.splitlines())


def local_git_report(cwd: Path) -> dict[str, Any]:
    git_root = git_value(["rev-parse", "--show-toplevel"], cwd)
    if git_root is None:
        return {
            "status": "blocked",
            "reason": "not inside a git repository",
            "cwd": str(cwd),
        }
    root = Path(git_root)
    branch = git_value(["symbolic-ref", "--quiet", "--short", "HEAD"], root)
    head = git_value(["rev-parse", "HEAD"], root)
    upstream = git_value(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root
    )
    main_contains = None
    if head:
        local_code, _stdout, _stderr = run(
            ["git", "merge-base", "--is-ancestor", head, "main"], root
        )
        remote_code, _stdout, _stderr = run(
            ["git", "merge-base", "--is-ancestor", head, "origin/main"], root
        )
        if local_code in {0, 1} or remote_code in {0, 1}:
            main_contains = local_code == 0 or remote_code == 0
    return {
        "status": "pass",
        "cwd": str(cwd),
        "git_root": str(root),
        "branch": branch or "detached",
        "head": head,
        "upstream": upstream,
        "dirty_count": git_dirty_count(root),
        "main_contains_head": main_contains,
    }


def hosted_pr_report(cwd: Path) -> dict[str, Any]:
    if shutil.which("gh") is None:
        return {"status": "unknown", "reason": "gh not found"}
    code, stdout, stderr = run(
        [
            "gh",
            "pr",
            "view",
            "--json",
            "number,state,url,headRefName,baseRefName,isDraft,mergeable",
        ],
        cwd,
    )
    if code != 0:
        reason = stderr or stdout or "gh pr status failed"
        return {"status": "unknown", "reason": reason}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {"status": "unknown", "reason": "gh pr status returned non-JSON output"}
    if not data.get("number"):
        return {"status": "unknown", "reason": "no current branch PR found"}
    return {"status": "pass", "pull_request": data}


def build_report(cwd: Path) -> dict[str, Any]:
    local = local_git_report(cwd)
    hosted = hosted_pr_report(Path(local.get("git_root", cwd)))
    return {
        "schema_version": "branch-pr-truth/v1",
        "local_git": local,
        "hosted_pr": hosted,
        "proof_boundary": {
            "local_git": "direct git command evidence",
            "hosted_pr": "gh evidence when available; otherwise unknown",
            "does_not_prove": [
                "CI status",
                "review thread state",
                "tracker state",
                "merge readiness",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report branch and PR truth lanes.")
    parser.add_argument(
        "--cwd", type=Path, default=Path.cwd(), help="Repository path to inspect."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Alias for default read-only behavior."
    )
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    report = build_report(args.cwd.resolve())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        local = report["local_git"]
        hosted = report["hosted_pr"]
        print(f"Branch/PR truth: local={local['status']} hosted_pr={hosted['status']}")
        print(json.dumps(report, sort_keys=True))
    return 0 if report["local_git"]["status"] == "pass" else 1


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
