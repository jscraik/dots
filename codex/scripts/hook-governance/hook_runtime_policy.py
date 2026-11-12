"""Shared runtime policy helpers for hook governance logic."""

from __future__ import annotations

import argparse
import json
from typing import Any

OWNER_PRECEDENCE: tuple[str, ...] = (
    "git_local",
    "project_codex",
    "global_codex",
)

OWNER_RANK = {owner: idx for idx, owner in enumerate(OWNER_PRECEDENCE)}

RUNTIME_POLICY: dict[str, Any] = {
    "owner_precedence": list(OWNER_PRECEDENCE),
    "pretool_supported_blockers": [
        "hookSpecificOutput.permissionDecision=deny",
        "decision=block",
        "exit_code=2",
    ],
    "pretool_unsupported_blockers": [
        "continue:false",
    ],
    "events": {
        "PreToolUse": {
            "matcher_supported": True,
            "timeout_class": "pre_safety_fail_closed",
            "default_failure_policy": "block_on_explicit_deny_only",
        },
        "PostToolUse": {
            "matcher_supported": True,
            "timeout_class": "post_quality_advisory_fail_open",
            "default_failure_policy": "allow_with_warning",
        },
        "SessionStart": {
            "matcher_supported": True,
            "timeout_class": "startup_non_blocking",
            "default_failure_policy": "allow_with_warning",
        },
        "UserPromptSubmit": {
            "matcher_supported": False,
            "timeout_class": "prompt_guard_fail_closed",
            "default_failure_policy": "block_on_explicit_deny_only",
        },
        "Stop": {
            "matcher_supported": False,
            "timeout_class": "stop_guard_fail_closed",
            "default_failure_policy": "block_on_explicit_deny_only",
        },
    },
}


def owner_rank(owner_layer: str | None) -> int:
    """
    Return the precedence rank for an owner-layer identifier.

    Parameters:
        owner_layer (str | None): Owner-layer identifier to rank; may be None.

    Returns:
        int: Integer rank where lower values indicate higher precedence. Returns 999 if `owner_layer` is not a recognised string.
    """

    if not isinstance(owner_layer, str):
        return 999
    return OWNER_RANK.get(owner_layer, 999)


def _as_int(value: Any) -> int | None:
    """
    Coerce a value to an integer when it represents a non-boolean whole number.

    Parameters:
        value (Any): Input to coerce; boolean values are treated as non-numeric.

    Returns:
        int | None: The integer value if `value` is an `int` or a string of decimal digits, `None` otherwise.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def normalize_action(candidate: dict[str, Any], event_name: str | None = None) -> str:
    """
    Normalize a hook result into a single arbitration action.

    Parameters:
        candidate (dict[str, Any]): A hook output or reason candidate containing heterogeneous fields
            (e.g. `permissionDecision`, `decision`, `action`, `exit_code`, `warning`) to be interpreted.
        event_name (str | None): Optional event name (e.g. `"PreToolUse"`) which may influence interpretation.

    Returns:
        str: `'block'` if the candidate indicates a blocking decision, `'allow-with-warning'` if it
        indicates allowance with a warning, or `'allow'` otherwise.
    """

    hook_out = candidate.get("hookSpecificOutput")
    if isinstance(hook_out, dict):
        permission_decision = hook_out.get("permissionDecision")
    else:
        permission_decision = None

    if not permission_decision:
        permission_decision = candidate.get("permissionDecision")
    if not permission_decision:
        permission_decision = candidate.get("permission_decision")
    if isinstance(permission_decision, str) and permission_decision.lower() == "deny":
        return "block"

    decision = candidate.get("decision")
    if isinstance(decision, str):
        decision_lc = decision.strip().lower()
        if decision_lc == "block":
            return "block"
        if decision_lc in {"allow-with-warning", "warning", "warn"}:
            return "allow-with-warning"

    action = candidate.get("action")
    if isinstance(action, str):
        action_lc = action.strip().lower()
        if action_lc in {"block", "deny"}:
            return "block"
        if action_lc in {"allow-with-warning", "warning", "warn"}:
            return "allow-with-warning"
        if action_lc == "allow":
            return "allow"

    exit_code_value = None
    if candidate.get("exit_code") is not None:
        exit_code_value = candidate.get("exit_code")
    elif candidate.get("exitCode") is not None:
        exit_code_value = candidate.get("exitCode")
    elif candidate.get("returncode") is not None:
        exit_code_value = candidate.get("returncode")
    elif candidate.get("code") is not None:
        exit_code_value = candidate.get("code")
    exit_code = _as_int(exit_code_value)
    if event_name == "PreToolUse" and exit_code == 2:
        return "block"

    warning_like = candidate.get("warning")
    if isinstance(warning_like, bool) and warning_like:
        return "allow-with-warning"

    return "allow"


def arbitration_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """
    Produce a deterministic sort key for selecting the winning reason among candidates.

    The returned tuple contains, in order: owner rank, source_path, gate_id, reason and the integer index (defaults used when fields are missing).

    Returns:
        tuple: Sort key (owner_rank, source_path, gate_id, reason, index).
    """

    return (
        owner_rank(candidate.get("owner_layer")),
        str(candidate.get("source_path") or ""),
        str(candidate.get("gate_id") or ""),
        str(candidate.get("reason") or ""),
        int(candidate.get("_index") or 0),
    )


def get_event_policy(event_name: str) -> dict[str, Any]:
    """
    Retrieve the runtime policy entry for a named event.

    Parameters:
        event_name (str): The event name to look up in the runtime policy.

    Returns:
        dict[str, Any]: The event's policy dictionary, or an empty dict if the events section or the named event is missing or not a dictionary.
    """
    events = RUNTIME_POLICY.get("events", {})
    if not isinstance(events, dict):
        return {}
    event_policy = events.get(event_name, {})
    return event_policy if isinstance(event_policy, dict) else {}


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for the runtime policy CLI.

    Provides two optional string flags: `--event` to select an event-specific policy, and `--field` to emit a single field from the chosen payload.

    Returns:
        argparse.Namespace: The parsed arguments with attributes `event` and `field` (both may be None).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", help="emit event-specific runtime policy")
    parser.add_argument("--field", help="emit a single field value")
    return parser.parse_args()


def main() -> int:
    """
    Emit the runtime policy (or an event-specific subset or single field) to standard output.

    If `--event` was supplied, the event-specific policy is emitted; otherwise the full runtime policy is emitted.
    If `--field` was supplied, only that field's value is emitted and the function returns failure if the field is missing.

    Returns:
        int: Exit code: `0` on success, `1` when a requested field is not present.
    """
    args = parse_args()
    payload: dict[str, Any]
    if args.event:
        payload = get_event_policy(args.event)
    else:
        payload = RUNTIME_POLICY

    if args.field:
        value = payload.get(args.field) if isinstance(payload, dict) else None
        if value is None:
            return 1
        if isinstance(value, (dict, list)):
            print(json.dumps(value, sort_keys=True))
        else:
            print(value)
        return 0

    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())