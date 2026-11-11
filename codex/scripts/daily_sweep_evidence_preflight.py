"""Check that daily-sweep evidence artifacts are discoverable before analysis."""

from __future__ import annotations

import argparse
import glob
import json
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
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


SCHEMA_VERSION = "daily-sweep-evidence-preflight/v1"
SERVICE = "daily_sweep_evidence_preflight"
DEFAULT_SESSION_COLLECTOR_ROOT = Path.home() / ".agents" / "session-collector"
DEFAULT_USAGE_DATA_ROOT = Path(__file__).resolve().parents[1] / "usage-data"
DEFAULT_MAX_AGE_HOURS = 36.0
SESSION_COLLECTOR_BUNDLE_GLOBS = (
    "/private/tmp/*session-collector*-bundle",
    "/tmp/*session-collector*-bundle",
)
ARTIFACT_PATTERNS = (
    "*.json",
    "*.jsonl",
    "data/**/*.json",
    "data/**/*.jsonl",
    "runtime-cards/**/*.json",
    "session-meta/**/*.json",
    "facets/**/*.json",
    "hook-warnings.jsonl",
)
ALLOWED_FILE_ROOT_NAMES = frozenset({"session-collector.json"})


@dataclass(frozen=True)
class Artifact:
    path: Path
    mtime: float


def parse_args() -> argparse.Namespace:
    usage_data_default = Path(
        os.environ.get("DAILY_SWEEP_USAGE_DATA_ROOT", str(DEFAULT_USAGE_DATA_ROOT))
    )
    parser = argparse.ArgumentParser(
        description="Assert that the daily workflow improvement sweep can discover session collector and usage-data artifacts."
    )
    parser.add_argument(
        "--session-collector-root",
        type=Path,
        default=None,
        help="session collector artifact root",
    )
    parser.add_argument(
        "--usage-data-root",
        type=Path,
        default=usage_data_default,
        help="Codex usage-data artifact root",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=float(
            os.environ.get("DAILY_SWEEP_MAX_AGE_HOURS", DEFAULT_MAX_AGE_HOURS)
        ),
        help="maximum age for the newest artifact in each root",
    )
    parser.add_argument(
        "--now", type=float, default=time.time(), help=argparse.SUPPRESS
    )
    args = _fixture_args(parser.parse_args())
    if args.session_collector_root is None:
        env_root = os.environ.get("DAILY_SWEEP_SESSION_COLLECTOR_ROOT")
        if env_root:
            args.session_collector_root = Path(env_root)
        else:
            args.session_collector_root = discover_default_session_collector_root(
                now=args.now, max_age_hours=args.max_age_hours
            )
    return args


def discover_default_session_collector_root(
    *, now: float | None = None, max_age_hours: float = DEFAULT_MAX_AGE_HOURS
) -> Path:
    if now is None:
        now = time.time()
    canonical_summary = summarize_root(
        DEFAULT_SESSION_COLLECTOR_ROOT, now, max_age_hours
    )
    if canonical_summary.get("status") == "pass":
        return DEFAULT_SESSION_COLLECTOR_ROOT
    bundles: list[Artifact] = []
    for pattern in SESSION_COLLECTOR_BUNDLE_GLOBS:
        for candidate_name in _fixture_resource(glob).glob(pattern):
            candidate = Path(candidate_name)
            if not candidate.is_dir():
                continue
            try:
                stat = _fixture_resource(candidate).stat()
            except OSError:
                continue
            bundles.append(Artifact(path=candidate, mtime=stat.st_mtime))
    if not bundles:
        return DEFAULT_SESSION_COLLECTOR_ROOT

    def _summary_age_seconds(candidate: Artifact) -> float:
        summary = summarize_root(candidate.path, now, max_age_hours)
        if summary.get("status") != "pass":
            return float("inf")
        age_hours = summary.get("latest_age_hours")
        if age_hours is None:
            return float("inf")
        return float(age_hours)

    candidates = sorted(
        (
            candidate
            for candidate in bundles
            if _summary_age_seconds(candidate) < float("inf")
        ),
        key=lambda candidate: summarize_root(candidate.path, now, max_age_hours)[
            "latest_age_hours"
        ],
    )
    if candidates:
        return candidates[0].path
    return DEFAULT_SESSION_COLLECTOR_ROOT


def discover_artifacts(root: Path) -> list[Artifact]:
    if root.is_file():
        if root.name not in ALLOWED_FILE_ROOT_NAMES:
            return []
        try:
            stat = _fixture_resource(root).stat()
        except OSError:
            return []
        return [Artifact(path=root, mtime=stat.st_mtime)]
    if not root.exists() or not root.is_dir():
        return []
    found: dict[Path, Artifact] = {}
    for pattern in ARTIFACT_PATTERNS:
        for candidate in _fixture_resource(root).glob(pattern):
            if not candidate.is_file():
                continue
            try:
                stat = _fixture_resource(candidate).stat()
            except OSError:
                continue
            found[candidate] = Artifact(path=candidate, mtime=stat.st_mtime)
    return sorted(found.values(), key=lambda item: item.mtime, reverse=True)


def summarize_root(root: Path, now: float, max_age_hours: float) -> dict[str, object]:
    artifacts = discover_artifacts(root)
    root_summary: dict[str, object] = {
        "root": str(root),
        "exists": root.exists(),
        "artifact_count": len(artifacts),
        "latest_artifact": None,
        "latest_age_hours": None,
        "status": "pass",
        "reason": None,
    }
    if not root.exists() or not (root.is_dir() or root.is_file()):
        root_summary["status"] = "blocked"
        root_summary["reason"] = "artifact root missing"
        return root_summary
    if not artifacts:
        root_summary["status"] = "blocked"
        root_summary["reason"] = "no matching artifacts found"
        return root_summary
    latest = artifacts[0]
    age_hours = max(0.0, (now - latest.mtime) / 3600)
    root_summary["latest_artifact"] = str(latest.path)
    root_summary["latest_age_hours"] = round(age_hours, 3)
    if age_hours > max_age_hours:
        root_summary["status"] = "blocked"
        root_summary["reason"] = (
            f"latest artifact is older than {max_age_hours:g} hours"
        )
    return root_summary


def blocked_reasons(summaries: Iterable[dict[str, object]]) -> list[str]:
    reasons: list[str] = []
    for summary in summaries:
        if summary.get("status") != "blocked":
            continue
        reasons.append(f"{summary.get('root')}: {summary.get('reason')}")
    return reasons


def build_payload(
    roots: list[dict[str, object]],
    status: str,
    args: argparse.Namespace,
    reasons: list[str],
) -> dict[str, object]:
    fingerprint_parts = [
        f"session_collector_root:{args.session_collector_root}",
        f"usage_data_root:{args.usage_data_root}",
        f"status:{status}",
    ]
    if reasons:
        fingerprint_parts.extend(sorted(reasons))
    return {
        "service": SERVICE,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "fingerprint": "|".join(fingerprint_parts),
        "checked_patterns": list(ARTIFACT_PATTERNS),
        "session_collector_bundle_globs": list(SESSION_COLLECTOR_BUNDLE_GLOBS),
        "max_age_hours": args.max_age_hours,
        "roots": roots,
        "blocked_reason": "; ".join(reasons) if reasons else None,
    }


def main() -> int:
    args = parse_args()
    roots = [
        summarize_root(args.session_collector_root, args.now, args.max_age_hours),
        summarize_root(args.usage_data_root, args.now, args.max_age_hours),
    ]
    reasons = blocked_reasons(roots)
    status = "blocked" if reasons else "pass"
    payload = build_payload(roots, status, args, reasons)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if status == "blocked" else 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
