"""Deterministically arbitrate concurrent Codex hook outcomes."""

from __future__ import annotations

import argparse
import importlib.util
import json
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


MODULE_PATH = Path(__file__).resolve().with_name("hook_runtime_policy.py")
SPEC = importlib.util.spec_from_file_location("hook_runtime_policy", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load runtime policy module from {MODULE_PATH}")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class ArbitrationInputError(ValueError):
    """Raised when arbitration input payload is malformed."""


def _string(value: Any, default: str = "") -> str:
    """
    Return the given value if it is a string, otherwise return the supplied default.

    Parameters:
        value: The value to test for being a `str`.
        default (str): Value to return when `value` is not a `str`. Defaults to an empty string.

    Returns:
        The original `value` when it is a `str`, otherwise `default`.
    """
    return value if isinstance(value, str) else default


def _bool(value: Any, default: bool = False) -> bool:
    """
    Return the boolean value unchanged, or a supplied default when the input is not a boolean.

    Parameters:
        value (Any): Value to test for boolean type.
        default (bool): Value to return when `value` is not a `bool`. Defaults to False.

    Returns:
        bool: `value` if it is a `bool`, otherwise `default`.
    """
    return value if isinstance(value, bool) else default


def _load_payload(path: Path) -> dict[str, Any]:
    """
    Load and validate a JSON arbitration fixture from the given filesystem path.

    If the file contains a JSON array it is returned wrapped as {"candidates": [...]}. If it contains a JSON object that object is returned as-is.

    Parameters:
        path (Path): Filesystem path to the JSON fixture.

    Returns:
        dict[str, Any]: The parsed payload object; arrays are converted to a dict with key "candidates".

    Raises:
        ArbitrationInputError: If the file is not valid JSON, or if the top-level JSON value is neither an object nor an array.
    """
    try:
        payload = json.loads(_fixture_resource(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ArbitrationInputError(f"invalid JSON fixture {path}: {exc}") from exc
    if isinstance(payload, list):
        return {"candidates": payload}
    if not isinstance(payload, dict):
        raise ArbitrationInputError("arbitration payload must be an object or array")
    return payload


def _extract_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extracts and normalises hook candidate entries from a parsed payload.

    Reads the first existing top-level key among `candidates`, `results` or `hook_results` and validates it is a list. Skips non-dictionary entries. For each dictionary entry it extracts a `reason` (from `reason`, `permissionDecisionReason`, `hookSpecificOutput.permissionDecisionReason`, or `message`), determines `owner_layer` (from `owner_layer` or `ownerLayer`, defaulting to "global_codex"), and builds a candidate dictionary containing `_index`, `gate_id`, `owner_layer`, `source_path`, `reason`, `is_canonical_owner` and `action`. The `action` is normalised via `POLICY.normalize_action(...)` using `event_name` from the payload.

    Returns:
        A list of candidate dictionaries. Each dictionary contains the keys:
        `_index`, `gate_id`, `owner_layer`, `source_path`, `reason`,
        `is_canonical_owner`, and `action`.
    """
    if "candidates" in payload:
        raw_candidates = payload["candidates"]
    elif "results" in payload:
        raw_candidates = payload["results"]
    elif "hook_results" in payload:
        raw_candidates = payload["hook_results"]
    else:
        raw_candidates = []
    if not isinstance(raw_candidates, list):
        raise ArbitrationInputError("arbitration payload candidates must be a list")
    candidates: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_candidates):
        if not isinstance(raw, dict):
            continue
        reason = _string(raw.get("reason"))
        if not reason:
            reason = _string(raw.get("permissionDecisionReason"))
        if not reason and isinstance(raw.get("hookSpecificOutput"), dict):
            reason = _string(
                raw.get("hookSpecificOutput", {}).get("permissionDecisionReason")
            )
        if not reason:
            reason = _string(raw.get("message"))
        owner_layer = _string(raw.get("owner_layer")).strip()
        if not owner_layer:
            owner_layer = _string(raw.get("ownerLayer")).strip()
        if not owner_layer:
            owner_layer = "global_codex"
        candidate = {
            "_index": idx,
            "gate_id": _string(raw.get("gate_id") or raw.get("gateId")),
            "owner_layer": owner_layer,
            "source_path": _string(raw.get("source_path") or raw.get("sourcePath")),
            "reason": reason,
            "is_canonical_owner": _bool(
                raw.get("is_canonical_owner")
                if "is_canonical_owner" in raw
                else raw.get("canonical_owner"),
                default=False,
            ),
        }
        candidate["action"] = POLICY.normalize_action(
            raw, event_name=_string(payload.get("event_name") or payload.get("event"))
        )
        candidates.append(candidate)
    return candidates


def arbitrate_results(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Arbitrate concurrent hook candidates from a payload and produce a single decision dict.

    Parameters:
        payload (dict): Mapping containing event metadata and a list of candidate hook results.
            The candidate list is expected under one of the keys 'candidates', 'results' or
            'hook_results'. Each candidate may include fields such as 'action', 'is_canonical_owner',
            'reason', 'gate_id', 'owner_layer' and 'source_path'.

    Returns:
        dict: Decision summary with the following keys:
            - event_name (str): Event name extracted from the payload ('event_name' or 'event').
            - action (str): Final arbitration action: 'block', 'allow-with-warning' or 'allow'.
            - gate_id (str): Gate identifier from the selected winning candidate, or empty string.
            - owner_layer (str): Owner layer of the winning candidate, or empty string.
            - source_path (str): Source path of the winning candidate, or empty string.
            - winning_reason (str): Reason text from the winning candidate, or empty string.
            - suppressed_reason_count (int): Number of surviving candidates with non-empty reasons
              whose reasons are suppressed in the output (winner's reason excluded).
            - candidate_count (int): Total number of valid candidates extracted from the payload.
            - surviving_candidate_count (int): Number of candidates considered after arbitration.
    """
    candidates = _extract_candidates(payload)
    canonical_blocks = [
        c for c in candidates if c["action"] == "block" and c["is_canonical_owner"]
    ]
    noncanonical_blocks = [
        c
        for c in candidates
        if c["action"] == "block" and (not c["is_canonical_owner"])
    ]
    warnings = [c for c in candidates if c["action"] == "allow-with-warning"]
    downgraded_blocks = []
    if not canonical_blocks:
        for item in noncanonical_blocks:
            downgraded = dict(item)
            downgraded["action"] = "allow-with-warning"
            downgraded_blocks.append(downgraded)
    if canonical_blocks:
        action = "block"
        surviving = canonical_blocks
    elif warnings or downgraded_blocks:
        action = "allow-with-warning"
        surviving = warnings + downgraded_blocks
    else:
        action = "allow"
        surviving = []
    winner: dict[str, Any] | None = None
    if surviving:
        winner = min(surviving, key=POLICY.arbitration_sort_key)
    reason_candidates = [item for item in surviving if _string(item.get("reason"))]
    suppressed_reason_count = len(reason_candidates)
    if winner is not None and _string(winner.get("reason")):
        suppressed_reason_count = max(suppressed_reason_count - 1, 0)
    return {
        "event_name": _string(payload.get("event_name") or payload.get("event")),
        "action": action,
        "gate_id": _string((winner or {}).get("gate_id")),
        "owner_layer": _string((winner or {}).get("owner_layer")),
        "source_path": _string((winner or {}).get("source_path")),
        "winning_reason": _string((winner or {}).get("reason")),
        "suppressed_reason_count": suppressed_reason_count,
        "candidate_count": len(candidates),
        "surviving_candidate_count": len(surviving),
    }


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for the script.

    Only one required option is provided:
    --fixture: path to the JSON fixture file used as input; returned as a pathlib.Path.

    Returns:
        argparse.Namespace: Parsed arguments with attribute `fixture` (Path).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    return _fixture_args(parser.parse_args())


def main() -> int:
    """
    Run the arbitration process for a fixture file and emit the decision as JSON.

    Loads the fixture specified by command-line arguments, computes the arbitration decision, and prints the result or a tagged error message on malformed input.

    Returns:
        int: Process exit code: `0` on successful arbitration, `1` if the input fixture is malformed.
    """
    args = parse_args()
    try:
        payload = _load_payload(args.fixture.resolve())
        decision = arbitrate_results(payload)
    except ArbitrationInputError as exc:
        print(f"[arbitrate_hook_results] {exc}")
        return 1
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
