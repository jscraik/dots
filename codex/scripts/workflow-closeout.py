"""Generate and validate workflow closeout receipts."""

from __future__ import annotations

import argparse
import json
import sys
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


REQUIRED_TOP_LEVEL = (
    "schema_version",
    "objective",
    "repo",
    "ticket_id",
    "files_changed",
    "durable_surface",
    "repeated_failure_prevented",
    "validation",
    "proof_lanes",
    "blocker_class",
    "evidence_refs",
    "tomorrow_effect",
    "remaining_risk",
    "next_owner",
)
REQUIRED_LANES = (
    "local_validation",
    "generated_artifacts",
    "runtime_reachability",
    "remote_branch",
    "open_pr",
    "ci",
    "review_threads",
    "tracker",
    "merge_readiness",
)
ALLOWED_TOP_LEVEL = set(REQUIRED_TOP_LEVEL)
ALLOWED_VALIDATION_FIELDS = {
    "command",
    "outcome",
    "evidence",
    "blocker_class",
    "reason",
}
ALLOWED_PROOF_LANE_FIELDS = {"status", "evidence", "checked_at"}
LANE_STATUSES = {"pass", "fail", "blocked", "unknown", "not_applicable"}
VALIDATION_OUTCOMES = {"pass", "fail", "blocked", "skipped"}
DURABLE_SURFACES = {
    "script",
    "schema",
    "hook",
    "project_rule",
    "test",
    "skill",
    "memory",
    "linear",
    "documentation",
}


def sample_receipt() -> dict[str, Any]:
    lane_unknown = {"status": "unknown", "evidence": "not checked in this closeout"}
    return {
        "schema_version": "workflow-closeout/v1",
        "objective": "Add session-start priority gate for open P0 workflow fixes",
        "repo": _fixture_text("@POLICY_SOURCE@"),
        "ticket_id": "EXAMPLE-1",
        "files_changed": [
            "codex/scripts/workflow-priority-gate.py",
            "codex/hooks/session-start.sh",
        ],
        "durable_surface": ["script", "hook", "linear"],
        "repeated_failure_prevented": "Open workflow P0 work is visible before unrelated work starts.",
        "validation": [
            {
                "command": "python3 scripts/workflow-priority-gate.py --json --max-items 1",
                "outcome": "pass",
                "evidence": "emitted workflow-priority-gate/v1 JSON",
            }
        ],
        "proof_lanes": {
            "local_validation": {
                "status": "pass",
                "evidence": "focused local checks passed",
            },
            "generated_artifacts": {"status": "pass", "evidence": "receipt generated"},
            "runtime_reachability": {
                "status": "blocked",
                "evidence": "runtime hook trust not checked",
            },
            "remote_branch": lane_unknown,
            "open_pr": lane_unknown,
            "ci": lane_unknown,
            "review_threads": lane_unknown,
            "tracker": {"status": "pass", "evidence": "Linear issue updated"},
            "merge_readiness": lane_unknown,
        },
        "blocker_class": "pre_existing_config_drift",
        "evidence_refs": ["EXAMPLE-1", "codex/scripts/workflow-priority-gate.py"],
        "tomorrow_effect": "Session start points at the next P0 workflow guardrail.",
        "remaining_risk": [
            "Hosted CI and merge readiness remain separate proof lanes."
        ],
        "next_owner": "workspace-write implementation profile",
    }


def load_json(path: Path) -> tuple[object | None, str | None]:
    try:
        with _fixture_resource(path).open("r", encoding="utf-8") as handle:
            return (json.load(handle), None)
    except OSError as exc:
        return (None, f"unable to read {path}: {exc}")
    except json.JSONDecodeError as exc:
        return (
            None,
            f"invalid JSON in {path}: {exc.msg} (line {exc.lineno}, column {exc.colno})",
        )


def require_non_empty_string(
    receipt: dict[str, Any], key: str, errors: list[str]
) -> None:
    value = receipt.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key} must be a non-empty string")


def validate_receipt(receipt: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(receipt, dict):
        return ["receipt must be a JSON object"]
    for key in REQUIRED_TOP_LEVEL:
        if key not in receipt:
            errors.append(f"missing required field: {key}")
    for key in sorted(set(receipt) - ALLOWED_TOP_LEVEL):
        errors.append(f"unexpected field: {key}")
    if receipt.get("schema_version") != "workflow-closeout/v1":
        errors.append("schema_version must be workflow-closeout/v1")
    for key in (
        "objective",
        "repo",
        "ticket_id",
        "repeated_failure_prevented",
        "tomorrow_effect",
        "next_owner",
    ):
        require_non_empty_string(receipt, key, errors)
    for key in ("files_changed", "evidence_refs", "remaining_risk"):
        value = receipt.get(key)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            errors.append(f"{key} must be an array of non-empty strings")
    surfaces = receipt.get("durable_surface")
    if not isinstance(surfaces, list) or not surfaces:
        errors.append("durable_surface must be a non-empty array")
    elif any(surface not in DURABLE_SURFACES for surface in surfaces):
        errors.append(
            f"durable_surface values must be one of: {', '.join(sorted(DURABLE_SURFACES))}"
        )
    validation = receipt.get("validation")
    if not isinstance(validation, list) or not validation:
        errors.append("validation must be a non-empty array")
    else:
        for index, entry in enumerate(validation):
            if not isinstance(entry, dict):
                errors.append(f"validation[{index}] must be an object")
                continue
            for key in sorted(set(entry) - ALLOWED_VALIDATION_FIELDS):
                errors.append(f"validation[{index}] unexpected field: {key}")
            command = entry.get("command")
            outcome = entry.get("outcome")
            if not isinstance(command, str) or not command.strip():
                errors.append(f"validation[{index}].command must be a non-empty string")
            if outcome not in VALIDATION_OUTCOMES:
                errors.append(
                    f"validation[{index}].outcome must be one of: {', '.join(sorted(VALIDATION_OUTCOMES))}"
                )
            if outcome in {"blocked", "skipped"}:
                reason = (
                    entry.get("reason")
                    or entry.get("blocker_class")
                    or entry.get("evidence")
                )
                if not isinstance(reason, str) or not reason.strip():
                    errors.append(
                        f"validation[{index}] blocked/skipped outcome requires reason, blocker_class, or evidence"
                    )
    lanes = receipt.get("proof_lanes")
    if not isinstance(lanes, dict):
        errors.append("proof_lanes must be an object")
    else:
        for lane in sorted(set(lanes) - set(REQUIRED_LANES)):
            errors.append(f"proof_lanes unexpected lane: {lane}")
        for lane in REQUIRED_LANES:
            value = lanes.get(lane)
            if not isinstance(value, dict):
                errors.append(f"proof_lanes.{lane} must be an object")
                continue
            for key in sorted(set(value) - ALLOWED_PROOF_LANE_FIELDS):
                errors.append(f"proof_lanes.{lane} unexpected field: {key}")
            status = value.get("status")
            evidence = value.get("evidence")
            if status not in LANE_STATUSES:
                errors.append(
                    f"proof_lanes.{lane}.status must be one of: {', '.join(sorted(LANE_STATUSES))}"
                )
            if not isinstance(evidence, str) or not evidence.strip():
                errors.append(f"proof_lanes.{lane}.evidence must be a non-empty string")
    blocker_class = receipt.get("blocker_class")
    if blocker_class is not None and (not isinstance(blocker_class, str)):
        errors.append("blocker_class must be a string or null")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or validate workflow closeout receipts."
    )
    parser.add_argument(
        "--emit-sample",
        action="store_true",
        help="Print a sample workflow-closeout/v1 receipt.",
    )
    parser.add_argument(
        "--validate", type=Path, help="Validate a workflow closeout receipt JSON file."
    )
    parser.add_argument(
        "--validate-sample",
        action="store_true",
        help="Validate the built-in sample receipt.",
    )
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    if args.emit_sample:
        print(json.dumps(sample_receipt(), indent=2, sort_keys=True))
        return 0
    if args.validate_sample:
        errors = validate_receipt(sample_receipt())
    elif args.validate is not None:
        payload, load_error = load_json(args.validate)
        errors = [load_error] if load_error else validate_receipt(payload)
    else:
        print(
            "usage: workflow-closeout.py --emit-sample | --validate PATH | --validate-sample",
            file=sys.stderr,
        )
        return 2
    if errors:
        for error in errors:
            print(f"workflow-closeout: {error}", file=sys.stderr)
        return 1
    print("workflow-closeout: OK")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
