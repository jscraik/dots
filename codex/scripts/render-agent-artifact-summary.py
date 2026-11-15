"""Summarize subagent run manifests for coordinator accountability."""

from __future__ import annotations

import argparse
import json
from collections import Counter
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


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = _fixture_scope().SCOPE.policy_source_root(SCRIPT_DIR.parent)


def load_manifest(path: Path) -> tuple[dict[str, object] | None, str | None]:
    """Load one manifest and return a stable error instead of raising."""
    try:
        data = json.loads(_fixture_resource(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (None, f"{path}: unreadable manifest ({exc})")
    if not isinstance(data, dict):
        return (None, f"{path}: manifest must be a JSON object")
    return (data, None)


def summarize(root: Path) -> tuple[str, list[str]]:
    """Return a Markdown summary and validation errors for agent run manifests."""
    manifest_root = root / "artifacts" / "agent-runs"
    manifests = sorted(_fixture_resource(manifest_root).glob("*/manifest.json"))
    errors: list[str] = []
    if not manifests:
        return (
            "# Agent Artifact Summary\n\nNo agent run manifests found under `artifacts/agent-runs/`.\n",
            errors,
        )
    status_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    useful_findings: list[str] = []
    good_jobs: list[str] = []
    for manifest_path in manifests:
        manifest, error = load_manifest(manifest_path)
        if error:
            errors.append(error)
            continue
        assert manifest is not None
        status = manifest.get("status")
        role = manifest.get("agent_role")
        status_counts[str(status or "unknown")] += 1
        role_counts[str(role or "unknown")] += 1
        accountability = manifest.get("accountability")
        if isinstance(accountability, dict):
            blocker = accountability.get("blocked_reason")
            if isinstance(blocker, str) and blocker.strip():
                blocker_counts[blocker.strip()] += 1
            strengths = accountability.get("strengths")
            if isinstance(strengths, list):
                good_jobs.extend(str(item) for item in strengths if str(item).strip())
            findings = accountability.get("findings")
            if isinstance(findings, list):
                useful_findings.extend(
                    str(item) for item in findings if str(item).strip()
                )
    lines = ["# Agent Artifact Summary", ""]
    lines.append(f"- Manifests: {len(manifests)}")
    lines.append("")
    lines.append("## Status Counts")
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")
    lines.append("")
    lines.append("## Role Counts")
    for role, count in sorted(role_counts.items()):
        lines.append(f"- {role}: {count}")
    lines.append("")
    lines.append("## Blocker Counts")
    if blocker_counts:
        for blocker, count in sorted(blocker_counts.items()):
            lines.append(f"- {blocker}: {count}")
    else:
        lines.append("- None recorded.")
    lines.append("")
    lines.append("## Positive Performance")
    if good_jobs:
        for item in good_jobs[:20]:
            lines.append(f"- {item}")
    else:
        lines.append("- None recorded.")
    lines.append("")
    lines.append("## Useful Findings")
    if useful_findings:
        for item in useful_findings[:20]:
            lines.append(f"- {item}")
    else:
        lines.append("- None recorded.")
    lines.append("")
    return ("\n".join(lines), errors)


def main() -> int:
    """Render a coordinator-friendly summary from manifest artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=str(DEFAULT_ROOT), help="Codex subtree root path"
    )
    parser.add_argument("--out", help="Optional Markdown output path")
    args = _fixture_args(parser.parse_args())
    root = Path(args.root).expanduser().resolve()
    summary, errors = summarize(root)
    if errors:
        print("[render-agent-artifact-summary] validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = root / out
        _fixture_scope().output(out.parent).mkdir(parents=True, exist_ok=True)
        _fixture_scope().output(out).write_text(summary, encoding="utf-8")
        print(f"[render-agent-artifact-summary] wrote {out}")
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
