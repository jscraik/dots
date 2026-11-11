"""Verify a maintainer-attested independent review from live GitHub comments.

The caller authenticates and paginates the inventory. The maintainer must
personally attest reviewer independence; task names alone do not prove it.
This route supplies review evidence only, never CI, thread or merge authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime


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


REPORT = "pr-independent-report/v1\n"
ACCEPT = "pr-maintainer-acceptance/v1\n"


def body_digest(entry: dict) -> str:
    return hashlib.sha256(entry["body"].encode("utf-8")).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _record(entry: dict, marker: str, fields: set[str]) -> dict:
    body = entry.get("body")
    if (
        not isinstance(body, str)
        or not body.startswith(marker)
        or len(body.encode()) > 131072
    ):
        raise ValueError("missing marker or oversized record")
    record = json.loads(body[len(marker) :], object_pairs_hook=_unique)
    if not isinstance(record, dict) or set(record) != fields:
        raise ValueError("record fields do not match the contract")
    return record


def _time(entry: dict, field: str) -> datetime:
    value = entry.get(field)
    if not isinstance(value, str):
        raise ValueError("source timestamp missing")  # noqa: TRY004 - MIG-HELPER-1: preserve the domain-invalid-evidence API; instructions/migration-scope.md#helper-boundary-decisions
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("source timestamp is not timezone-bound")
    return stamp


def _owner(entry: dict) -> bool:
    user = entry.get("user")
    return (
        isinstance(user, dict)
        and user.get("login") == "jscraik"
        and (user.get("type") == "User")
    )


def verify_acceptance(
    *,
    entries: list[dict],
    outages: list[dict],
    number: int,
    head: str,
    base: str,
    paths: list[str],
    head_time: str,
) -> dict | None:
    """Require exact candidate, source digests and personal owner attestation.

    Configs-only policy: the authenticated owner accepts a separate read-only
    agent's report, including its asserted provenance. No local file supplies
    clearance, and the coding agent must never post the acceptance itself.
    """
    records = [
        entry
        for entry in entries
        if isinstance(entry.get("body"), str)
        and entry["body"].startswith(ACCEPT)
        and _owner(entry)
    ]
    if not records:
        return None
    identity = {
        "repository": "jscraik/configs",
        "pr_number": number,
        "head_sha": head,
        "base_sha": base,
    }
    common = {"schema_version", *identity}
    acceptance_fields = common | {
        "report_url",
        "report_sha256",
        "outage_url",
        "outage_sha256",
        "independence_verified",
        "accepted",
    }
    parsed = [(entry, _record(entry, ACCEPT, acceptance_fields)) for entry in records]
    matching = [
        (entry, record)
        for entry, record in parsed
        if all(
            (
                record[key] == value and type(record[key]) is type(value)
                for key, value in identity.items()
            )
        )
    ]
    if len(matching) != 1:
        raise ValueError("exactly one current-head acceptance is required")
    entry, acceptance = matching[0]
    if not _owner(entry):
        raise ValueError("acceptance is not from the authenticated human owner")
    if any(
        (
            acceptance[key] != value or type(acceptance[key]) is not type(value)
            for key, value in identity.items()
        )
    ):
        raise ValueError("acceptance candidate identity mismatch")
    if (
        acceptance["schema_version"] != ACCEPT.rstrip()
        or acceptance["accepted"] is not True
        or acceptance["independence_verified"] is not True
    ):
        raise ValueError(
            "explicit acceptance and reviewer-independence attestation required"
        )
    prefix = f"https://github.com/jscraik/configs/pull/{number}#issuecomment-"
    by_url = {}
    for source in entries:
        url = source.get("html_url")
        if not isinstance(url, str) or not re.fullmatch(
            re.escape(prefix) + "[1-9][0-9]*", url
        ):
            raise ValueError("source URL is outside this GitHub PR")
        if url in by_url:
            raise ValueError("duplicate source URL")
        by_url[url] = source
    if entry.get("html_url") not in by_url:
        raise ValueError("acceptance source missing")
    report = by_url.get(acceptance["report_url"])
    outage = next(
        (item for item in outages if item.get("html_url") == acceptance["outage_url"]),
        None,
    )
    original = by_url.get(acceptance["outage_url"])
    if (
        report is None
        or outage is None
        or original is None
        or (original.get("user") != outage.get("user"))
        or (body_digest(original) != body_digest(outage))
    ):
        raise ValueError("review report or authenticated provider outage missing")
    outage = original
    for source, key in ((report, "report_sha256"), (outage, "outage_sha256")):
        if body_digest(source) != acceptance[key]:
            raise ValueError("accepted source digest changed")
    report_fields = common | {
        "writer_task",
        "reviewer_task",
        "covered_paths",
        "review_summary",
        "unresolved_findings",
        "conclusion",
        "reviewer_kind",
    }
    review = _record(report, REPORT, report_fields)
    if any(
        (
            review[key] != value or type(review[key]) is not type(value)
            for key, value in identity.items()
        )
    ):
        raise ValueError("report candidate identity mismatch")
    if (
        review["schema_version"] != REPORT.rstrip()
        or review["reviewer_kind"] != "separate_read_only_agent"
        or review["conclusion"] != "no_remaining_findings"
        or (review["unresolved_findings"] != [])
    ):
        raise ValueError(
            "independent completed review with no remaining findings required"
        )
    for key in ("writer_task", "reviewer_task"):
        if (
            not isinstance(review[key], str)
            or not review[key].strip()
            or len(review[key]) > 1024
        ):
            raise ValueError("task provenance missing")
    if (
        not isinstance(review["review_summary"], str)
        or not review["review_summary"].strip()
    ):
        raise ValueError("completed review summary missing")
    if review["writer_task"].strip() == review["reviewer_task"].strip():
        raise ValueError("coding task cannot supply its own independent review")
    coverage = review["covered_paths"]
    if (
        not isinstance(coverage, list)
        or any(not isinstance(path, str) for path in coverage)
        or (not paths)
        or (sorted(coverage) != sorted(paths))
        or (len(set(coverage)) != len(coverage))
    ):
        raise ValueError("report does not cover the complete committed diff")
    committed = datetime.fromisoformat(head_time)
    chronology = [
        (source, _time(source, "created_at"), _time(source, "updated_at"))
        for source in (outage, report, entry)
    ]
    if (
        committed.tzinfo is None
        or any((updated < created for _, created, updated in chronology))
        or (
            not committed
            <= chronology[0][1]
            <= chronology[0][2]
            < chronology[1][1]
            <= chronology[1][2]
            < chronology[2][1]
        )
    ):
        raise ValueError("outage, review and acceptance do not follow this candidate")
    return {
        "review_mode": "maintainer_accepted_independent_report",
        "head_sha": head,
        "base_sha": base,
        "report_url": report["html_url"],
        "report_sha256": body_digest(report),
        "acceptance_url": entry["html_url"],
        "acceptance_sha256": body_digest(entry),
        "outage_url": outage["html_url"],
        "outage_sha256": body_digest(outage),
        "reviewer_task": review["reviewer_task"],
        "independence_basis": "personal maintainer attestation",
    }
