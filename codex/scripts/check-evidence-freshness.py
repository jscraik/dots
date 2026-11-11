"""Check whether evidence artifacts exist and are fresh enough for closeout claims."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check evidence artifact freshness.")
    parser.add_argument(
        "paths", nargs="*", type=Path, help="Evidence artifact paths to check."
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=24.0,
        help="Maximum artifact age in hours.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run deterministic fresh/stale/missing self-test.",
    )
    return _fixture_args(parser.parse_args())


def check_path(
    path: Path, max_age_seconds: float, now: float | None = None
) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    if not path.exists():
        return {
            "path": str(path),
            "status": "blocked",
            "reason": "missing artifact",
            "age_seconds": None,
        }
    if not path.is_file():
        return {
            "path": str(path),
            "status": "blocked",
            "reason": "not a file",
            "age_seconds": None,
        }
    age_seconds = max(0.0, current_time - _fixture_resource(path).stat().st_mtime)
    if age_seconds > max_age_seconds:
        return {
            "path": str(path),
            "status": "fail",
            "reason": "stale artifact",
            "age_seconds": round(age_seconds, 3),
        }
    return {
        "path": str(path),
        "status": "pass",
        "reason": "fresh artifact",
        "age_seconds": round(age_seconds, 3),
    }


def aggregate(results: list[dict[str, Any]]) -> str:
    statuses = {str(result["status"]) for result in results}
    if "blocked" in statuses:
        return "blocked"
    if "fail" in statuses:
        return "fail"
    return "pass"


def build_report(paths: list[Path], max_age_hours: float) -> dict[str, Any]:
    max_age_seconds = max_age_hours * 3600
    results = [check_path(path, max_age_seconds) for path in paths]
    return {
        "schema_version": "evidence-freshness/v1",
        "max_age_hours": max_age_hours,
        "status": aggregate(results),
        "results": results,
    }


def run_self_test() -> tuple[bool, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="evidence-freshness-") as temp_dir:
        temp_root = Path(temp_dir)
        fresh = temp_root / "fresh.txt"
        stale = temp_root / "stale.txt"
        missing = temp_root / "missing.txt"
        _fixture_resource(fresh).write_text("fresh\n", encoding="utf-8")
        _fixture_resource(stale).write_text("stale\n", encoding="utf-8")
        now = time.time()
        old_mtime = now - 7200
        _fixture_resource(stale).touch()
        _fixture_resource(fresh).touch()
        stale_stat = (old_mtime, old_mtime)
        import os

        os.utime(stale, stale_stat)
        report = {
            "schema_version": "evidence-freshness-self-test/v1",
            "fresh": check_path(fresh, 3600, now=now),
            "stale": check_path(stale, 3600, now=now),
            "missing": check_path(missing, 3600, now=now),
        }
        ok = (
            report["fresh"]["status"] == "pass"
            and report["stale"]["status"] == "fail"
            and (report["missing"]["status"] == "blocked")
        )
        report["status"] = "pass" if ok else "fail"
        return (ok, report)


def human_summary(report: dict[str, Any]) -> str:
    lines = [f"Evidence freshness: {report['status']}"]
    for result in report.get("results", []):
        age = result.get("age_seconds")
        age_text = "unknown age" if age is None else f"{age}s old"
        lines.append(
            f"- {result['status']}: {result['path']} ({result['reason']}; {age_text})"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    if args.self_test:
        ok, report = run_self_test()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if ok else 1
    if not args.paths:
        print(
            "check-evidence-freshness: provide at least one path or --self-test",
            flush=True,
        )
        return 2
    report = build_report(args.paths, args.max_age_hours)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(human_summary(report))
        print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
