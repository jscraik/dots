"""Validate machine-consumed subagent governance markers.

Instruction discovery links are checked by validate-instruction-routing.py;
static marker checks cannot prove the meaning of natural-language guidance.
"""

from __future__ import annotations

import argparse
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


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = _fixture_scope().SCOPE.policy_source_root(SCRIPT_DIR.parent)


@dataclass(frozen=True)
class ContainsCheck:
    path: str
    description: str
    needles: tuple[str, ...]


GOVERNANCE_CHECKS = (
    ContainsCheck(
        "instructions/agents/07b-agent-governance.md",
        "runtime blocker schema is present",
        (
            "STATUS: complete | blocked_runtime | blocked_missing_artifact | blocked_validation",
            "blocker_class",
            "exact_failure",
        ),
    ),
    ContainsCheck(
        "instructions/agents/07b-agent-governance.md",
        "validation ownership classification is required",
        ("introduced by current patch", "pre-existing", "unrelated dirty worktree"),
    ),
    ContainsCheck(
        "instructions/agents/09-audit-trail-policy.md",
        "agent-run schema and retired memory boundary are explicit",
        (
            "agents/schemas/agent-run-manifest.schema.json",
            "manifest_path",
            "retired service is not required for new provenance",
        ),
    ),
    ContainsCheck(
        "instructions/agents/10-agent-testing-gates.md",
        "artifact contract validation gate is documented",
        (
            "Subagent artifact contract",
            "python3 scripts/validate-agent-artifacts.py",
            "agent-artifact-contract-validation",
        ),
    ),
    ContainsCheck(
        "agents/templates/review-artifact.md",
        "review artifact template includes receipt and manifest path",
        ("Accountability Receipt", "manifest_path", "WROTE: <artifact_path>"),
    ),
    ContainsCheck(
        "agents/templates/coordinator-ledger.md",
        "coordinator ledger template includes accounting and positive performance",
        ("Agent Accounting", "Positive Performance", "Coverage gap"),
    ),
    ContainsCheck(
        "agents/evals/subagent-artifact-quality.json",
        "subagent quality eval fixtures cover failure and good-job cases",
        ("missing-artifact-path", "good-reviewer", "agent-native-gap"),
    ),
    ContainsCheck(
        "scripts/validate-agent-artifacts.py",
        "artifact validator script exists and checks contracts",
        ("validate_contract", "REQUIRED_FIXTURES", "REQUIRED_MANIFEST_FIELDS"),
    ),
    ContainsCheck(
        "scripts/render-agent-artifact-summary.py",
        "artifact summary renderer exists for accountability review",
        ("Positive Performance", "Blocker Counts", "manifest.json"),
    ),
    ContainsCheck(
        "hooks/subagent-start.sh",
        "subagent start hook carries evidence ownership and explicit artifact compatibility",
        ("coordinator owns durable records", "orchestrator/mailbox instruction"),
    ),
)


def check_contains(root: Path, check: ContainsCheck) -> list[str]:
    """Return missing-file or missing-text failures for a governance check."""
    target = root / check.path
    if not target.is_file():
        return [f"missing file: {check.path}"]
    text = _fixture_resource(target).read_text(encoding="utf-8")
    return [
        f"{check.path}: missing {check.description}: {needle!r}"
        for needle in check.needles
        if needle not in text
    ]


def validate(root: Path) -> list[str]:
    """Validate subagent governance docs against the retained evidence contracts."""
    failures: list[str] = []
    for check in GOVERNANCE_CHECKS:
        failures.extend(check_contains(root, check))
    return failures


def main() -> int:
    """Run subagent governance validation and print a stable summary."""
    parser = argparse.ArgumentParser(
        description="Validate subagent fault-prevention governance requirements"
    )
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Codex subtree root path (defaults to this script's parent)",
    )
    args = _fixture_args(parser.parse_args())
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"[validate-agent-governance] root not found: {root}")
        return 1
    failures = validate(root)
    if failures:
        print("[validate-agent-governance] validation failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        "[validate-agent-governance] OK: machine-consumed subagent markers are present"
    )
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
