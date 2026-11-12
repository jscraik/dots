"""Evaluate docstring severity ratchet state from API classification output."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


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


PATH_ANCHOR = Path(__file__).resolve().parents[2]
FALSE_POSITIVE_THRESHOLD = 0.05


class DocstringRatchetError(ValueError):
    """Raised when ratchet inputs are invalid."""


def load_structured_file(path: Path) -> object:
    raw_text = _fixture_resource(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        if yaml is not None:
            return yaml.safe_load(raw_text)
    raise DocstringRatchetError(
        f"unable to parse structured file '{path}' as JSON or YAML"
    )


def utc_now_rfc3339() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def portable_path(path: Path, *, anchor: Path | None = None) -> str:
    """Render canonical paths relative to `anchor` when possible."""
    resolved_path = path.expanduser().resolve(strict=False)
    if anchor is not None:
        resolved_anchor = anchor.expanduser().resolve(strict=False)
        try:
            return resolved_path.relative_to(resolved_anchor).as_posix()
        except ValueError:
            pass
    return resolved_path.as_posix()


def _normalize_false_positive_rates(value: object) -> list[float]:
    if not isinstance(value, list):
        raise DocstringRatchetError("false_positive_rate_weekly must be a list")
    rates: list[float] = []
    for entry in value:
        if isinstance(entry, (int, float)):
            rates.append(float(entry))
            continue
        raise DocstringRatchetError(
            "false_positive_rate_weekly entries must be numeric"
        )
    return rates


def _collect_rule_ids(rules_payload: object) -> set[str]:
    if not isinstance(rules_payload, dict):
        raise DocstringRatchetError("rules payload must be an object")
    allowlist: set[str] = set()
    default_rules = rules_payload.get("default_rules", [])
    if not isinstance(default_rules, list):
        raise DocstringRatchetError("rules.default_rules must be a list")
    for entry in default_rules:
        if not isinstance(entry, dict):
            continue
        rule_id = entry.get("rule_id")
        if isinstance(rule_id, str) and rule_id:
            allowlist.add(rule_id)
    repositories = rules_payload.get("repositories", {})
    if not isinstance(repositories, dict):
        raise DocstringRatchetError("rules.repositories must be an object")
    for repo_payload in repositories.values():
        if not isinstance(repo_payload, dict):
            continue
        repo_rules = repo_payload.get("rules", [])
        if not isinstance(repo_rules, list):
            raise DocstringRatchetError("repository rules entries must be lists")
        for entry in repo_rules:
            if not isinstance(entry, dict):
                continue
            rule_id = entry.get("rule_id")
            if isinstance(rule_id, str) and rule_id:
                allowlist.add(rule_id)
    if not allowlist:
        raise DocstringRatchetError("rules payload produced an empty rule_id allowlist")
    return allowlist


def _resolve_rules_path(
    *,
    classification_payload: dict[str, object],
    classification_path: Path,
    explicit_rules_path: Path | None,
) -> Path:
    if explicit_rules_path is not None:
        return explicit_rules_path
    rules_path_value = classification_payload.get("rules_path")
    if isinstance(rules_path_value, str) and rules_path_value:
        candidate = Path(rules_path_value)
        if candidate.is_absolute() or candidate.exists():
            return candidate
        classification_relative = classification_path.parent / candidate
        if classification_relative.exists():
            return classification_relative
        home_relative = Path.home() / candidate
        if home_relative.exists():
            return home_relative
        return candidate
    candidate = classification_path.parent / "public-api-rules.yaml"
    if candidate.exists():
        return candidate
    raise DocstringRatchetError(
        "unable to resolve rules path; pass --rules or include rules_path in classification payload"
    )


def evaluate_repo(
    repo_payload: dict[str, object],
    metrics_payload: dict[str, object],
    rule_id_allowlist: set[str],
    window_days: int,
) -> dict[str, object]:
    repo_name = repo_payload.get("repo_name")
    repo_path = repo_payload.get("repo_path")
    if not isinstance(repo_name, str) or not repo_name:
        raise DocstringRatchetError("classification repository is missing repo_name")
    if not isinstance(repo_path, str) or not repo_path:
        raise DocstringRatchetError(
            f"classification repo '{repo_name}' is missing repo_path"
        )
    repositories_metrics = metrics_payload.get("repositories", {})
    if not isinstance(repositories_metrics, dict):
        repositories_metrics = {}
    repo_metrics = repositories_metrics.get(repo_name, {})
    if not isinstance(repo_metrics, dict):
        repo_metrics = {}
    false_positive_rates_value = repo_metrics.get("false_positive_rate_weekly", [])
    false_positive_rates = _normalize_false_positive_rates(false_positive_rates_value)
    unresolved_suppressions_value = repo_metrics.get(
        "unresolved_high_conf_suppressions_over_7d", 0
    )
    if not isinstance(unresolved_suppressions_value, int):
        raise DocstringRatchetError(
            "unresolved_high_conf_suppressions_over_7d must be an integer"
        )
    unresolved_suppressions = unresolved_suppressions_value
    import math

    expected_points = math.ceil(window_days / 7)
    ratchet_reasons: list[str] = []
    if len(false_positive_rates) < expected_points:
        ratchet_reasons.append(
            f"insufficient false-positive metrics for the full {window_days}-day window ({len(false_positive_rates)}/{expected_points} weeks)"
        )
    elif max(false_positive_rates) > FALSE_POSITIVE_THRESHOLD:
        ratchet_reasons.append(
            f"false-positive rate exceeds threshold ({max(false_positive_rates):.3f} > {FALSE_POSITIVE_THRESHOLD:.3f})"
        )
    if unresolved_suppressions > 0:
        ratchet_reasons.append(
            f"{unresolved_suppressions} high-confidence suppression(s) unresolved over 7d"
        )
    ratchet_ready = len(ratchet_reasons) == 0
    files_payload = repo_payload.get("files", [])
    if not isinstance(files_payload, list):
        raise DocstringRatchetError(
            f"classification files for '{repo_name}' must be a list"
        )
    evaluated_files: list[dict[str, object]] = []
    for file_entry in files_payload:
        if not isinstance(file_entry, dict):
            continue
        path = file_entry.get("path")
        label = file_entry.get("label")
        matched_rule_id = file_entry.get("matched_rule_id")
        if not isinstance(path, str) or not path:
            continue
        if not isinstance(label, str) or not label:
            continue
        if not isinstance(matched_rule_id, str):
            matched_rule_id = ""
        elif matched_rule_id and matched_rule_id not in rule_id_allowlist:
            raise DocstringRatchetError(
                f"classification repo '{repo_name}' path '{path}' references unknown matched_rule_id '{matched_rule_id}'"
            )
        severity_mode = "warning"
        drift_flags: list[str] = []
        if label == "public" and ratchet_ready:
            severity_mode = "hard-block"
        elif label == "unknown-surface":
            drift_flags.append("classifier-drift")
        evaluated_files.append(
            {
                "path": path,
                "label": label,
                "matched_rule_id": matched_rule_id,
                "severity_mode": severity_mode,
                "drift_flags": drift_flags,
            }
        )
    evaluated_files.sort(key=lambda item: item["path"])
    return {
        "repo_name": repo_name,
        "repo_path": repo_path,
        "ratchet_ready": ratchet_ready,
        "ratchet_reasons": ratchet_reasons,
        "false_positive_rate_weekly": false_positive_rates,
        "unresolved_high_conf_suppressions_over_7d": unresolved_suppressions,
        "files": evaluated_files,
    }


def evaluate_docstring_ratchet(
    classification_path: Path,
    metrics_path: Path,
    rules_path: Path | None,
    window_days: int,
) -> dict[str, object]:
    working_dir = PATH_ANCHOR
    if window_days <= 0:
        raise DocstringRatchetError("--window-days must be greater than zero")
    classification_payload = load_structured_file(classification_path)
    if not isinstance(classification_payload, dict):
        raise DocstringRatchetError("classification payload must be an object")
    resolved_rules_path = _resolve_rules_path(
        classification_payload=classification_payload,
        classification_path=classification_path,
        explicit_rules_path=rules_path,
    )
    rules_payload = load_structured_file(resolved_rules_path)
    rule_id_allowlist = _collect_rule_ids(rules_payload)
    repositories = classification_payload.get("repositories", [])
    if not isinstance(repositories, list):
        raise DocstringRatchetError("classification.repositories must be a list")
    metrics_payload = load_structured_file(metrics_path)
    if not isinstance(metrics_payload, dict):
        raise DocstringRatchetError("metrics payload must be an object")
    evaluated_repositories = [
        evaluate_repo(
            repo_payload=repo_payload,
            metrics_payload=metrics_payload,
            rule_id_allowlist=rule_id_allowlist,
            window_days=window_days,
        )
        for repo_payload in repositories
        if isinstance(repo_payload, dict)
    ]
    evaluated_repositories.sort(key=lambda item: item["repo_name"])
    return {
        "schema_version": "docstring-ratchet-evaluation.v1",
        "evaluated_at": utc_now_rfc3339(),
        "window_days": window_days,
        "classification_path": portable_path(classification_path, anchor=working_dir),
        "metrics_path": portable_path(metrics_path, anchor=working_dir),
        "rules_path": portable_path(resolved_rules_path, anchor=working_dir),
        "repositories": evaluated_repositories,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--classification",
        type=Path,
        required=True,
        help="path to public API classification JSON. Pass an explicit project-local or workspace file.",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        required=True,
        help="path to docstring ratchet metrics JSON. Pass an explicit project-local or workspace file.",
    )
    parser.add_argument("--window-days", type=int, default=14)
    parser.add_argument(
        "--rules",
        type=Path,
        help="optional path to public API rules YAML/JSON. Defaults to classification.rules_path or sibling public-api-rules.yaml.",
    )
    parser.add_argument("--out", type=Path)
    return _fixture_args(parser.parse_args())


def main() -> int:
    args = parse_args()
    try:
        result = evaluate_docstring_ratchet(
            classification_path=args.classification,
            metrics_path=args.metrics,
            rules_path=args.rules,
            window_days=args.window_days,
        )
    except (DocstringRatchetError, FileNotFoundError) as exc:
        print(f"[evaluate_docstring_ratchet] {exc}")
        return 1
    output = json.dumps(result, indent=2, sort_keys=True)
    if args.out is None:
        print(output)
    else:
        _fixture_scope().output(args.out.parent).mkdir(parents=True, exist_ok=True)
        _fixture_scope().output(args.out).write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
